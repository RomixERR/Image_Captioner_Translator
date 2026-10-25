
# -*- coding: utf-8 -*-
import json
import time
import urllib.error
import urllib.request

# Настройки (пути и адрес сервера) берутся из файла Config.txt
# (ключи testImg, testTxt, testEn, api_url).
# В этом скрипте пути и адрес не захардкожены — менять их нужно только в Config.txt.
from captionaizer_config import api_url, load_dirs, prompt_file

# ================= НАСТРОЙКИ =================

CONFIG = load_dirs()

# Папка с исходными текстами (testTxt из Config.txt — туда пишет caption_images.py)
INPUT_DIR = CONFIG["testTxt"]

# Папка для переведённых текстов (testEn из Config.txt)
OUTPUT_DIR = CONFIG["testEn"]

# Системный промпт (ключ translation_prompt_file в Config.txt, если он задан)
PROMPT_FILE = prompt_file("translation_prompt_file", "translation_prompt.txt")

# Адрес уже работающего llama-server (ключ api_url в Config.txt)
API_URL = api_url()

# Пропускать файлы, у которых перевод уже существует
SKIP_EXISTING = True

# False — только указанная папка
# True — также обрабатывать вложенные папки
RECURSIVE = False

# Максимальное число токенов на перевод
MAX_TOKENS = 2048

TEMPERATURE = 0.1
TIMEOUT_SECONDS = 600

# ==============================================


def translate_text(text: str, system_prompt: str) -> str:
    payload = {
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": (
                    "Translate the following text according to "
                    "the system instructions. Return only the "
                    "translated text.\n\n"
                    "<TEXT_TO_TRANSLATE>\n"
                    + text
                    + "\n</TEXT_TO_TRANSLATE>"
                )
            }
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False
    }

    data = json.dumps(
        payload, ensure_ascii=False
    ).encode("utf-8")

    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request, timeout=TIMEOUT_SECONDS
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        details = exc.read().decode(
            "utf-8", errors="replace"
        )
        raise RuntimeError(
            f"HTTP {exc.code}: {details}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Не удалось подключиться к llama-server. "
            f"Проверь, что сервер запущен и ключ api_url в Config.txt "
            f"указан верно (сейчас: {API_URL}). "
            f"{exc}"
        ) from exc

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Неожиданный ответ API: {result}"
        ) from exc

    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
        )

    translated = str(content).strip()

    if not translated:
        raise RuntimeError("Модель вернула пустой перевод.")

    return translated


def main():
    if not INPUT_DIR.is_dir():
        print(f"Не найдена папка исходников:\n{INPUT_DIR}")
        print("Измени ключ testTxt в файле Config.txt.")
        return

    if not PROMPT_FILE.is_file():
        print(f"Не найден системный промпт:\n{PROMPT_FILE}")
        return

    system_prompt = PROMPT_FILE.read_text(
        encoding="utf-8-sig"
    ).strip()

    if not system_prompt:
        print("Файл translation_prompt.txt пуст.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    iterator = (
        INPUT_DIR.rglob("*")
        if RECURSIVE
        else INPUT_DIR.iterdir()
    )

    files = sorted(
        path for path in iterator
        if path.is_file()
        and path.suffix.lower() == ".txt"
    )

    if not files:
        print(f"TXT-файлы не найдены:\n{INPUT_DIR}")
        return

    print(f"Найдено файлов: {len(files)}")
    print(f"Источник: {INPUT_DIR}")
    print(f"Результат: {OUTPUT_DIR}\n")

    done = skipped = failed = 0

    for index, source_path in enumerate(files, 1):
        relative_path = source_path.relative_to(INPUT_DIR)
        output_path = OUTPUT_DIR / relative_path
        output_path.parent.mkdir(
            parents=True, exist_ok=True
        )

        if (
            SKIP_EXISTING
            and output_path.exists()
            and output_path.stat().st_size > 0
        ):
            skipped += 1
            print(
                f"[{index}/{len(files)}] Пропуск: "
                f"{relative_path}"
            )
            continue

        try:
            source_text = source_path.read_text(
                encoding="utf-8-sig"
            )
        except Exception as exc:
            failed += 1
            print(f"    ОШИБКА чтения: {exc}")
            continue

        # Пустая подпись не переводится: это то же поведение,
        # что и у caption_images.py (пустой файл не считается подписью).
        if not source_text.strip():
            skipped += 1
            print(
                f"[{index}/{len(files)}] Пропуск "
                f"(пустой файл): {relative_path}"
            )
            continue

        print(
            f"[{index}/{len(files)}] Перевод: "
            f"{relative_path}"
        )

        started = time.time()

        try:
            translated = translate_text(
                source_text, system_prompt
            )

            output_path.write_text(
                translated + "\n",
                encoding="utf-8"
            )

            elapsed = time.time() - started
            done += 1

            print(
                f"    Сохранено: {output_path} "
                f"({elapsed:.1f} сек.)"
            )

        except Exception as exc:
            failed += 1
            print(f"    ОШИБКА: {exc}")

    print("\nОбработка завершена.")
    print(
        f"Переведено: {done} | "
        f"Пропущено: {skipped} | "
        f"Ошибок: {failed}"
    )


if __name__ == "__main__":
    main()
