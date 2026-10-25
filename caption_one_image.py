# -*- coding: utf-8 -*-
"""
Описание ОДНОЙ картинки через работающий llama-server.

Подпись пишется в папку testTxt (путь берётся из Config.txt) и ПЕРЕЗАПИСЫВАЕТСЯ,
поэтому скрипт удобно использовать, чтобы переделать описание уже подписанной
картинки. Имя файла подписи совпадает с именем картинки.

Запуск вручную:
    python caption_one_image.py "Flux_SeedVR_UPSCALER__31.jpg"
    python caption_one_image.py "D:\\Other\\pic.png"
    python caption_one_image.py pic.png --output "D:\\tmp\\caption.txt"
    python caption_one_image.py pic.png --no-overwrite

Код возврата: 0 — успех; 2 — ошибка аргументов или Config.txt;
3 — файл не найден; 1 — ошибка API.
"""

import argparse
import base64
import json
import mimetypes
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Всё (папки, файлы промптов, адрес сервера) берётся из Config.txt
from captionaizer_config import ConfigError, api_url, load_dirs, prompt_file

# ======================== НАСТРОЙКИ ========================

# Адрес работающего llama-server (ключ api_url в Config.txt)
try:
    API_URL = api_url()
except ConfigError as exc:
    print(f"ОШИБКА конфигурации: {exc}")
    raise SystemExit(2)

PROMPT_FILE = prompt_file("system_prompt_file", "system_prompt.txt")

MAX_TOKENS = 512
TEMPERATURE = 0.2
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


def resolve_image(argument: str, image_dir: Path) -> Path | None:
    """Находит картинку: абсолютный путь, путь относительно текущей папки или имя в testImg."""
    candidates = []

    raw = Path(argument).expanduser()
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(Path.cwd() / raw)
        candidates.append(image_dir / raw)

    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
            return candidate.resolve()

    # Имя без расширения или с другим регистром — ищем в testImg
    stem = raw.stem or argument
    for suffix in sorted(IMAGE_EXTENSIONS):
        for found in image_dir.glob(f"{stem}{suffix}"):
            if found.is_file():
                return found.resolve()
    for found in image_dir.glob(f"{stem}.*"):
        if found.is_file() and found.suffix.lower() in IMAGE_EXTENSIONS:
            return found.resolve()

    return None


def caption_output_for(image: Path, image_dir: Path, txt_dir: Path) -> Path:
    """Путь для подписи: сохраняем структуру папок относительно testImg."""
    try:
        relative = image.relative_to(image_dir)
    except ValueError:
        relative = Path(image.name)
    return txt_dir / relative.with_suffix(".txt")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Создать (или переписать) описание одной картинки; путь берётся из Config.txt."
    )
    parser.add_argument(
        "image",
        help="Путь к картинке или её имя в папке testImg (можно без расширения)"
    )
    parser.add_argument(
        "--output",
        default="",
        help="Необязательный явный путь для TXT-подписи"
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Не перезаписывать существующую непустую подпись"
    )
    args = parser.parse_args()

    try:
        config = load_dirs()
    except ConfigError as exc:
        print(f"ОШИБКА конфигурации: {exc}")
        return 2

    image_dir = config["testImg"]
    txt_dir = config["testTxt"]

    image = resolve_image(args.image, image_dir)
    if image is None:
        print(f"ОШИБКА: картинка не найдена: {args.image}")
        print(f"Искали в: {image_dir} и в текущей папке.")
        return 3

    if not PROMPT_FILE.is_file():
        print(f"ОШИБКА: не найден файл системного промпта:\n{PROMPT_FILE}")
        return 2

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not system_prompt:
        print(f"ОШИБКА: файл промпта пустой:\n{PROMPT_FILE}")
        return 2

    if args.output:
        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path = output_path.resolve()
    else:
        output_path = caption_output_for(image, image_dir, txt_dir)

    if (
        args.no_overwrite
        and output_path.is_file()
        and output_path.stat().st_size > 0
    ):
        print(f"Подпись уже есть, перезапись отменена (--no-overwrite):\n{output_path}")
        return 0

    print(f"Картинка: {image}")
    print(f"Подпись:  {output_path}")

    try:
        caption = request_caption(image, system_prompt)
    except Exception as exc:
        print(f"ОШИБКА: {exc}")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(caption + "\n", encoding="utf-8")

    print(f"Сохранено: {output_path}")
    print("Текст подписи:")
    print(caption)
    return 0


if __name__ == "__main__":
    sys.exit(main())
