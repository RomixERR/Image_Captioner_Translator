# -*- coding: utf-8 -*-
"""
Перевод ОДНОГО текстового файла через работающий llama-server.

Перевод пишется в папку testEn (путь берётся из Config.txt) и ПЕРЕЗАПИСЫВАЕТСЯ,
поэтому скрипт удобно использовать, чтобы переделать перевод уже переведённого
файла. Имя файла перевода совпадает с именем исходного TXT.

Запуск вручную:
    python translate_one_text.py "Flux_SeedVR_UPSCALER__31.txt"
    python translate_one_text.py "Flux_SeedVR_UPSCALER__31.jpg"   # найдёт testTxt\\Flux_SeedVR_UPSCALER__31.txt
    python translate_one_text.py "D:\\Other\\caption.txt" --output "D:\\Other\\caption_en.txt"
    python translate_one_text.py caption.txt --no-overwrite

Направление перевода задаётся только текстом translation_prompt.txt.

Код возврата: 0 — успех; 2 — ошибка аргументов или Config.txt;
3 — файл не найден или пустой; 1 — ошибка API.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Всё (папки, файлы промптов, адрес сервера) берётся из Config.txt
from captionaizer_config import ConfigError, api_url, load_dirs, prompt_file

# ================= НАСТРОЙКИ =================

# Адрес работающего llama-server (ключ api_url в Config.txt)
try:
    API_URL = api_url()
except ConfigError as exc:
    print(f"ОШИБКА конфигурации: {exc}")
    raise SystemExit(2)

PROMPT_FILE = prompt_file("translation_prompt_file", "translation_prompt.txt")

MAX_TOKENS = 2048
TEMPERATURE = 0.1
TIMEOUT_SECONDS = 600

# ==========================================================


def translate_text(text: str, system_prompt: str) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
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

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {details}") from exc
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
        raise RuntimeError(f"Неожиданный ответ API: {result}") from exc

    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )

    translated = str(content).strip()
    if not translated:
        raise RuntimeError("Модель вернула пустой перевод.")
    return translated


def resolve_source(argument: str, txt_dir: Path) -> Path | None:
    """
    Находит исходный TXT: явный путь, путь относительно текущей папки,
    имя в testTxt или имя картинки (тогда берётся testTxt\\<имя>.txt).
    """
    raw = Path(argument).expanduser()
    candidates = []

    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(Path.cwd() / raw)
        candidates.append(txt_dir / raw)
        if raw.suffix.lower() != ".txt":
            candidates.append(txt_dir / (raw.stem + ".txt"))

    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() == ".txt":
            return candidate.resolve()

    # Имя без расширения или с другим расширением — ищем TXT в testTxt
    stem = raw.stem or argument
    for found in txt_dir.glob(f"{stem}.*"):
        if found.is_file() and found.suffix.lower() == ".txt":
            return found.resolve()
    for found in txt_dir.glob(f"{stem}.txt"):
        if found.is_file():
            return found.resolve()

    return None


def translate_output_for(source: Path, txt_dir: Path, en_dir: Path) -> Path:
    """Путь для перевода: сохраняем структуру папок относительно testTxt."""
    try:
        relative = source.relative_to(txt_dir)
    except ValueError:
        relative = Path(source.name)
    return en_dir / relative.with_suffix(".txt")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Перевести один TXT-файл; путь берётся из Config.txt."
    )
    parser.add_argument(
        "source",
        help="Путь к TXT (или его имя в testTxt), либо имя картинки — тогда берётся её подпись"
    )
    parser.add_argument(
        "--output",
        default="",
        help="Необязательный явный путь для TXT-перевода"
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Не перезаписывать существующий непустой перевод"
    )
    args = parser.parse_args()

    try:
        config = load_dirs()
    except ConfigError as exc:
        print(f"ОШИБКА конфигурации: {exc}")
        return 2

    txt_dir = config["testTxt"]
    en_dir = config["testEn"]

    source = resolve_source(args.source, txt_dir)
    if source is None:
        print(f"ОШИБКА: текстовый файл не найден: {args.source}")
        print(f"Искали в: {txt_dir} и в текущей папке.")
        return 3

    if not PROMPT_FILE.is_file():
        print(f"ОШИБКА: не найден системный промпт:\n{PROMPT_FILE}")
        return 2

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8-sig").strip()
    if not system_prompt:
        print(f"ОШИБКА: файл промпта пустой:\n{PROMPT_FILE}")
        return 2

    source_text = source.read_text(encoding="utf-8-sig")
    if not source_text.strip():
        print(f"ОШИБКА: исходный файл пустой, переводить нечего:\n{source}")
        return 3

    if args.output:
        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path = output_path.resolve()
    else:
        output_path = translate_output_for(source, txt_dir, en_dir)

    if (
        args.no_overwrite
        and output_path.is_file()
        and output_path.stat().st_size > 0
    ):
        print(f"Перевод уже есть, перезапись отменена (--no-overwrite):\n{output_path}")
        return 0

    print(f"Источник: {source}")
    print(f"Перевод:  {output_path}")

    try:
        translated = translate_text(source_text, system_prompt)
    except Exception as exc:
        print(f"ОШИБКА: {exc}")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(translated + "\n", encoding="utf-8")

    print(f"Сохранено: {output_path}")
    print("Текст перевода:")
    print(translated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
