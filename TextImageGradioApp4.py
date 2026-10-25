# -*- coding: utf-8 -*-
"""
Фотоальбом Gradio: изображение + описание + перевод.

Все пути читаются из файла Config.txt (ключи testImg, testTxt, testEn),
здесь путей не захардкожено. Направление перевода задаётся только текстом
промпта в translation_prompt.txt и на пути не влияет.

Кнопки:
  • «Изменить» — сохранить отредактированные описание и перевод;
  • «Описать картинку» — запускает caption_one_image.py для выбранной картинки
    и перезаписывает её подпись в testTxt;
  • «Перевести текст» — запускает translate_one_text.py для текущей подписи
    и перезаписывает перевод в testEn;
  • под спойлером «Пакетная обработка»: «Описать все картинки»
    (caption_images.py) и «Перевести описания» (translate_text_files.py).

Для кнопок описания/перевода нужен работающий llama-server — его адрес
берётся из ключа api_url в Config.txt (как и у всех скриптов).
Если сервера нет, приложение не падает: текст ошибки виден в «Журнале скриптов».
"""

import glob
import os
import re
import subprocess
import sys
from pathlib import Path

import gradio as gr

from captionaizer_config import ConfigError, api_url, load_dirs

try:
    CONFIG = load_dirs()
    # Адрес сервера нужен только чтобы показать его в интерфейсе:
    # сами запросы делают внешние скрипты, они читают Config.txt сами
    API_URL = api_url()
except ConfigError as exc:
    raise SystemExit(f"ОШИБКА конфигурации: {exc}")

# Папка с изображениями (testImg из Config.txt)
IMAGE_DIR = str(CONFIG["testImg"])

# Папка с исходными описаниями (testTxt из Config.txt, туда пишет caption_images.py)
EN_DIR = str(CONFIG["testTxt"])

# Папка с переводом описаний (testEn из Config.txt, туда пишет translate_text_files.py)
RU_DIR = str(CONFIG["testEn"])

# Папка, где лежат Config.txt и сами скрипты
BASE_DIR = str(CONFIG["base"])

CAPTION_ALL_SCRIPT = Path(__file__).with_name("caption_images.py")
TRANSLATE_ALL_SCRIPT = Path(__file__).with_name("translate_text_files.py")
CAPTION_ONE_SCRIPT = Path(__file__).with_name("caption_one_image.py")
TRANSLATE_ONE_SCRIPT = Path(__file__).with_name("translate_one_text.py")

PYTHON_EXE = sys.executable or "python"

# Сколько секунд ждём завершение внешних скриптов
BATCH_TIMEOUT = 7200
ONE_TIMEOUT = 900

# Сколько последних строк вывода скрипта показывать в журнале
LOG_LINES = 40

SUPPORTED_FORMATS = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp", "*.tif", "*.tiff")


def description_path(directory: str, base_name: str) -> str:
    """Путь к TXT-файлу описания в нужной папке."""
    return os.path.join(directory, f"{base_name}.txt")


def read_text(path: str) -> str:
    """Читает текстовый файл; если файла нет — возвращает пустую строку."""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8-sig") as file:
        return file.read().strip()


def base_name_of(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


# Получаем список изображений
def load_images_and_descriptions():
    all_images = []
    for fmt in SUPPORTED_FORMATS:
        all_images.extend(sorted(glob.glob(os.path.join(IMAGE_DIR, fmt))))
    return all_images


def find_image_path(name: str) -> str:
    """Находит файл изображения в папке testImg по имени или относительному пути."""
    candidate = os.path.normpath(os.path.join(IMAGE_DIR, name))
    if os.path.isfile(candidate):
        return candidate

    base_name = os.path.basename(name)
    for fmt in SUPPORTED_FORMATS:
        for path in glob.glob(os.path.join(IMAGE_DIR, "**", base_name), recursive=True):
            if os.path.isfile(path):
                return path
        for path in glob.glob(os.path.join(IMAGE_DIR, fmt)):
            if os.path.basename(path) == base_name:
                return path
    return candidate


def base_name_from_event(event_data) -> str:
    """Достаёт имя выбранного файла из данных события выбора галереи."""
    value = getattr(event_data, "value", None)
    if isinstance(value, dict):
        image = value.get("image")
        if isinstance(image, dict):
            for key in ("orig_name", "name", "path"):
                if image.get(key):
                    return os.path.basename(str(image[key]))
        for key in ("orig_name", "name", "path", "url"):
            if value.get(key):
                return os.path.basename(str(value[key]))
    if isinstance(value, str):
        return os.path.basename(value)
    return ""


def description_paths_for(image_path: str) -> tuple[str, str]:
    """
    Пути подписи и перевода для выбранной картинки.
    Структура вложенных папок сохраняется так же, как в caption_images.py
    и translate_text_files.py (testImg\\sub\\pic.jpg -> captions\\sub\\pic.txt).
    """
    relative = Path(os.path.basename(image_path))
    if image_path:
        try:
            relative = Path(image_path).resolve().relative_to(Path(IMAGE_DIR).resolve())
        except ValueError:
            relative = Path(os.path.basename(image_path))

    relative = relative.with_suffix(".txt")
    return os.path.join(EN_DIR, relative), os.path.join(RU_DIR, relative)


def current_texts(image_path: str) -> tuple[str, str, bool]:
    """
    Возвращает (описание, перевод, можно_ли_переводить) для выбранной картинки.
    Отсутствующие файлы читаются как пустые строки — приложение не падает.
    """
    if not image_path:
        return "", "", False

    en_desc_path, ru_desc_path = description_paths_for(image_path)
    description = read_text(en_desc_path)
    translation = read_text(ru_desc_path)
    return description, translation, bool(description.strip())


def run_python_script(script: Path, args: list[str], timeout: int) -> tuple[bool, str]:
    """Запускает внешний скрипт и возвращает (успех, вывод)."""
    if not script.is_file():
        return False, f"Не найден скрипт: {script}"

    command = [PYTHON_EXE, str(script), *args]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=BASE_DIR,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"Скрипт не завершился за {timeout} сек. и был остановлен:\n"
            + " ".join(command)
        )
    except Exception as exc:
        return False, f"Не удалось запустить скрипт: {exc}"

    output = process.stdout or ""
    if process.stderr:
        output += "\n" + process.stderr
    output = output.strip()
    tail = "\n".join(output.splitlines()[-LOG_LINES:]) if output else "(вывод пустой)"

    if process.returncode != 0:
        return False, f"Скрипт завершился с кодом {process.returncode}:\n{tail}"
    return True, tail


def update_box(value: str, interactive: bool = True) -> dict:
    return gr.update(value=value, interactive=interactive)


def update_button(interactive: bool) -> dict:
    return gr.update(interactive=interactive)


def batch_error_count(log: str) -> int:
    """Сколько файлов не удалось обработать (строка «Ошибок: N» из вывода скрипта)."""
    match = re.search(r"Ошибок:\s*(\d+)", log)
    return int(match.group(1)) if match else 0


# Обработка выбранного изображения
def process_image(image_name):
    image_path = find_image_path(image_name)
    print("Текст к изображению обновлен: ", image_path)

    en_desc_path, ru_desc_path = description_paths_for(image_path)

    # Файл описания из папки testTxt
    english_description = read_text(en_desc_path)

    # Перевод из папки testEn
    russian_translation = read_text(ru_desc_path)

    return {
        "image": image_path,
        "en_desc": english_description,
        "ru_desc": russian_translation,
    }


# Обновление выбранного изображения и описаний
def select_image(event_data: gr.SelectData):
    name = base_name_from_event(event_data)
    if not name:
        return [
            None,
            update_box("", False),
            update_box("", False),
            "Не удалось определить выбранное изображение",
            "",
            update_button(False),
            update_button(False),
            "",
        ]

    image_path = find_image_path(name)
    if not os.path.isfile(image_path):
        return [
            None,
            update_box("", False),
            update_box("", False),
            f"Файл изображения не найден: {name}",
            "",
            update_button(False),
            update_button(False),
            "",
        ]

    process_image(name)
    description, translation, _ = current_texts(image_path)
    en_path, ru_path = description_paths_for(image_path)

    notes = [f"Выбрано: {os.path.basename(image_path)}"]
    if not description:
        notes.append(
            f"Файл подписи отсутствует: {en_path} — напечатай описание и нажми «Изменить» "
            "или нажми «Описать картинку»"
        )
    if not translation:
        notes.append(f"Файл перевода отсутствует: {ru_path} — «Перевести текст» создаст его")

    return [
        image_path,
        update_box(description, True),
        update_box(translation, True),
        " | ".join(notes),
        image_path,
        update_button(True),
        update_button(True),
        "",
    ]


# Сохранение изменений
def save_changes(new_en_desc, new_ru_desc, selected_image):
    if not selected_image or not os.path.isfile(selected_image):
        return ["Сначала выберите изображение в галерее", update_button(False)]

    en_desc_path, ru_desc_path = description_paths_for(selected_image)

    try:
        os.makedirs(os.path.dirname(en_desc_path) or EN_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(ru_desc_path) or RU_DIR, exist_ok=True)

        with open(en_desc_path, "w", encoding="utf-8") as file:
            file.write(new_en_desc or "")

        with open(ru_desc_path, "w", encoding="utf-8") as file:
            file.write(new_ru_desc or "")
    except Exception as exc:
        return [
            f"Не удалось сохранить: {exc}",
            update_button(True),
        ]

    return [
        f"Сохранено: {en_desc_path} и {ru_desc_path}",
        update_button(True),
    ]


# Запуск caption_one_image.py для выбранной картинки
def run_caption_one(selected_image, progress=gr.Progress()):
    if not selected_image or not os.path.isfile(selected_image):
        return [
            update_box("", False),
            update_box("", False),
            "Сначала выберите изображение в галерее",
            update_button(False),
            "",
        ]

    progress(0.2, desc="Описываю картинку...")
    ok, log = run_python_script(CAPTION_ONE_SCRIPT, [selected_image], ONE_TIMEOUT)
    description, translation, _ = current_texts(selected_image)

    message = (
        "Описание картинки обновлено (файл подписи перезаписан)."
        if ok
        else "Описать картинку не удалось — подробности в журнале скриптов."
    )
    return [
        update_box(description, True),
        update_box(translation, True),
        message,
        update_button(True),
        log,
    ]


# Запуск translate_one_text.py для текущей подписи
def run_translate_one(selected_image, current_description, progress=gr.Progress()):
    if not selected_image or not os.path.isfile(selected_image):
        return [
            update_box("", False),
            update_box("", False),
            "Сначала выберите изображение в галерее",
            update_button(False),
            "",
        ]

    en_desc_path, ru_desc_path = description_paths_for(selected_image)
    saved_description = read_text(en_desc_path)
    typed_description = (current_description or "").strip()
    note = ""

    # Если в поле напечатано описание, которого ещё нет в файле — сохраняем его,
    # чтобы перевод делался по тому тексту, который сейчас виден в окне.
    if typed_description and typed_description != saved_description:
        try:
            os.makedirs(os.path.dirname(en_desc_path) or EN_DIR, exist_ok=True)
            with open(en_desc_path, "w", encoding="utf-8") as file:
                file.write(typed_description + "\n")
            saved_description = typed_description
            note = "Описание из поля сохранено. "
        except Exception as exc:
            return [
                update_box(saved_description, True),
                update_box(read_text(ru_desc_path), True),
                f"Не удалось сохранить описание перед переводом: {exc}",
                update_button(True),
                "",
            ]

    if not saved_description:
        return [
            update_box(saved_description, True),
            update_box(read_text(ru_desc_path), True),
            "Переводить нечего: сначала «Описать картинку», либо напечатай описание и нажми «Изменить»",
            update_button(True),
            "",
        ]

    progress(0.2, desc="Перевожу описание...")
    ok, log = run_python_script(TRANSLATE_ONE_SCRIPT, [en_desc_path], ONE_TIMEOUT)
    description, translation, _ = current_texts(selected_image)

    message = note + (
        "Перевод обновлён (файл перевода перезаписан)."
        if ok
        else "Перевести текст не удалось — подробности в журнале скриптов."
    )
    return [
        update_box(description, True),
        update_box(translation, True),
        message,
        update_button(True),
        log,
    ]


# Пакетное описание всех картинок (caption_images.py)
def run_caption_all(selected_image, progress=gr.Progress()):
    selected = bool(selected_image) and os.path.isfile(selected_image)
    progress(0.1, desc="Описываю все картинки...")
    ok, log = run_python_script(CAPTION_ALL_SCRIPT, [], BATCH_TIMEOUT)
    description, translation, _ = current_texts(selected_image)

    errors = batch_error_count(log)
    if not ok:
        message = "Пакетное описание не завершено — подробности в журнале скриптов."
    elif errors:
        message = (
            f"Пакетное описание завершено, но с ошибками ({errors}) — "
            "подробности в журнале скриптов."
        )
    else:
        message = "Пакетное описание завершено."
    return [
        update_box(description, selected),
        update_box(translation, selected),
        message,
        update_button(selected),
        log,
    ]


# Пакетный перевод всех описаний (translate_text_files.py)
def run_translate_all(selected_image, progress=gr.Progress()):
    selected = bool(selected_image) and os.path.isfile(selected_image)
    progress(0.1, desc="Перевожу все описания...")
    ok, log = run_python_script(TRANSLATE_ALL_SCRIPT, [], BATCH_TIMEOUT)
    description, translation, _ = current_texts(selected_image)

    errors = batch_error_count(log)
    if not ok:
        message = "Пакетный перевод не завершён — подробности в журнале скриптов."
    elif errors:
        message = (
            f"Пакетный перевод завершён, но с ошибками ({errors}) — "
            "подробности в журнале скриптов."
        )
    else:
        message = "Пакетный перевод завершён."
    return [
        update_box(description, selected),
        update_box(translation, selected),
        message,
        update_button(selected),
        log,
    ]


# Интерфейс Gradio
with gr.Blocks() as demo:
    gr.Markdown("# Фотоальбом с описанием")
    gr.Markdown(
        f"Изображения: **{IMAGE_DIR}**  |  Описания: **{EN_DIR}**  |  Перевод: **{RU_DIR}**"
    )
    gr.Markdown(
        f"llama-server для кнопок описания и перевода: **{API_URL}** "
        "(ключ api_url в Config.txt)"
    )

    # Список изображений
    images_list = load_images_and_descriptions()

    # Галерея изображений
    gallery = gr.Gallery(value=images_list, columns=3, rows=3, height="auto")

    # Компоненты для описания
    with gr.Row():
        image_output = gr.Image(label="Изображение")
        with gr.Column():
            text_input_en = gr.Textbox(
                label="Описание (testTxt)", lines=4, interactive=False
            )
            text_input_ru = gr.Textbox(
                label="Перевод (testEn)", lines=4, interactive=False
            )

    # Кнопки под текстовыми полями
    with gr.Row():
        save_button = gr.Button("Изменить")
        caption_one_btn = gr.Button("Описать картинку", interactive=False)
        translate_one_btn = gr.Button("Перевести текст", interactive=False)

    # Сообщение о результате
    output_message = gr.Textbox(label="Сообщение", lines=2, interactive=False)

    # Вывод внешних скриптов (сюда же попадают ошибки llama-server)
    run_log = gr.Textbox(label="Журнал скриптов", lines=10, interactive=False)

    # Текущая выбранная картинка (пустая строка — ничего не выбрано)
    selected_state = gr.State("")

    # Пакетные действия — под спойлером внизу приложения
    with gr.Accordion("Пакетная обработка (все файлы)", open=False):
        caption_all_btn = gr.Button("Описать все картинки")
        gr.Markdown(
            "Уже подписанные картинки будут игнорироваться; если нужно — удалите файлы "
            "со старыми подписями. Просто пустой файл с подписью будет проигнорирован: "
            "такая картинка будет описана заново."
        )

        translate_all_btn = gr.Button("Перевести описания")
        gr.Markdown(
            "До этого действия нужно сперва «Описать все картинки», иначе переводить "
            "будет просто нечего. Уже переведённые файлы тоже игнорируются: чтобы "
            "перевести заново — удалите файл перевода."
        )

    # Связываем событие выбора изображения с обработчиком
    gallery.select(
        select_image,
        inputs=[],
        outputs=[
            image_output,
            text_input_en,
            text_input_ru,
            output_message,
            selected_state,
            caption_one_btn,
            translate_one_btn,
            run_log,
        ],
    )

    # Нажатие кнопки сохраняет изменения
    save_button.click(
        save_changes,
        inputs=[text_input_en, text_input_ru, selected_state],
        outputs=[output_message, translate_one_btn],
    )

    # Одна картинка / один текст: перезаписывают файл по имени картинки
    caption_one_btn.click(
        run_caption_one,
        inputs=[selected_state],
        outputs=[text_input_en, text_input_ru, output_message, translate_one_btn, run_log],
        concurrency_id="llama",
        concurrency_limit=1,
    )
    translate_one_btn.click(
        run_translate_one,
        inputs=[selected_state, text_input_en],
        outputs=[text_input_en, text_input_ru, output_message, translate_one_btn, run_log],
        concurrency_id="llama",
        concurrency_limit=1,
    )

    # Пакетные кнопки
    caption_all_btn.click(
        run_caption_all,
        inputs=[selected_state],
        outputs=[text_input_en, text_input_ru, output_message, translate_one_btn, run_log],
        concurrency_id="llama",
        concurrency_limit=1,
    )
    translate_all_btn.click(
        run_translate_all,
        inputs=[selected_state],
        outputs=[text_input_en, text_input_ru, output_message, translate_one_btn, run_log],
        concurrency_id="llama",
        concurrency_limit=1,
    )

if __name__ == "__main__":
    # Gradio должен иметь право отдавать файлы из папок из Config.txt
    demo.launch(debug=True, allowed_paths=[IMAGE_DIR, EN_DIR, RU_DIR])
