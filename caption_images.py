# -*- coding: utf-8 -*-
"""
Пакетное создание описаний изображений через уже запущенный llama-server.
Модель не перезапускается: каждый файл отправляется отдельным API-запросом.
"""

import base64
import json
import mimetypes
import time
import urllib.error
import urllib.request
from pathlib import Path

# Настройки (пути и адрес сервера) берутся из файла Config.txt
# (ключи testImg, testTxt, testEn, api_url).
# В этом скрипте пути и адрес не захардкожены — менять их нужно только в Config.txt.
from captionaizer_config import api_url, load_dirs, prompt_file

# ======================== НАСТРОЙКИ ========================

CONFIG = load_dirs()

# Папка с исходными изображениями (testImg из Config.txt):
INPUT_DIR = CONFIG["testImg"]

# Папка для TXT с подписями (testTxt из Config.txt):
OUTPUT_DIR = CONFIG["testTxt"]

# Системный промпт (ключ system_prompt_file в Config.txt, если он задан):
PROMPT_FILE = prompt_file("system_prompt_file", "system_prompt.txt")

# Адрес работающего llama-server (ключ api_url в Config.txt):
API_URL = api_url()

# Не перезаписывать уже созданные TXT:
SKIP_EXISTING = True

# False = только INPUT_DIR; True = также все вложенные папки.
RECURSIVE = False

# Максимум токенов для одного описания:
MAX_TOKENS = 512

# Температура генерации:
TEMPERATURE = 0.2

# Тайм-аут одного запроса, секунд:
TIMEOUT_SECONDS = 600

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"
}

# ==========================================================


def image_to_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def request_caption(image_path: Path, system_prompt: str) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Создай описание этого изображения согласно системному промпту."},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_to_data_url(image_path)}
                    }
                ]
            }
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Не удалось подключиться к {API_URL}. Убедись, что llama-server запущен. {exc}"
        ) from exc

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Неожиданный ответ API: {json.dumps(result, ensure_ascii=False)[:2000]}") from exc

    # Некоторые OpenAI-совместимые API возвращают content строкой,
    # другие — списком текстовых блоков.
    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )

    caption = str(content).strip()
    if not caption:
        raise RuntimeError("Модель вернула пустое описание.")
    return caption


def main() -> None:
    if not INPUT_DIR.is_dir():
        print(f"ОШИБКА: папка с изображениями не найдена:\n{INPUT_DIR}")
        print("Измени ключ testImg в файле Config.txt.")
        return

    if not PROMPT_FILE.is_file():
        print(f"ОШИБКА: не найден файл системного промпта:\n{PROMPT_FILE}")
        return

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not system_prompt:
        print("ОШИБКА: system_prompt.txt пустой.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    iterator = INPUT_DIR.rglob("*") if RECURSIVE else INPUT_DIR.iterdir()
    images = sorted(
        p for p in iterator
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not images:
        print(f"В папке не найдены изображения:\n{INPUT_DIR}")
        return

    # При RECURSIVE сохраняем структуру вложенных папок, чтобы одинаковые
    # имена файлов не перезаписывали друг друга.
    print(f"Изображений найдено: {len(images)}")
    print(f"Источник: {INPUT_DIR}")
    print(f"TXT-папка: {OUTPUT_DIR}")
    print("Каждое изображение отправляется отдельным запросом; история чата не используется.\n")

    done = 0
    skipped = 0
    failed = 0

    for index, image_path in enumerate(images, start=1):
        relative_path = image_path.relative_to(INPUT_DIR)
        output_path = OUTPUT_DIR / relative_path.with_suffix(".txt")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if SKIP_EXISTING and output_path.exists() and output_path.stat().st_size > 0:
            skipped += 1
            print(f"[{index}/{len(images)}] Пропуск (TXT уже есть): {relative_path}")
            continue

        print(f"[{index}/{len(images)}] Обрабатываю: {relative_path}")
        started = time.time()

        try:
            caption = request_caption(image_path, system_prompt)
            output_path.write_text(caption + "\n", encoding="utf-8")
            elapsed = time.time() - started
            done += 1
            print(f"    Сохранено: {output_path} ({elapsed:.1f} сек.)")
        except Exception as exc:
            failed += 1
            print(f"    ОШИБКА: {exc}")

        # Не запускаем параллельные запросы: это бережёт память и VRAM.
        # Небольшая пауза не обязательна, поэтому по умолчанию её нет.

    print("\nГотово.")
    print(f"Создано: {done} | Пропущено: {skipped} | Ошибок: {failed}")


if __name__ == "__main__":
    main()
