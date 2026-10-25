# -*- coding: utf-8 -*-
"""
Загрузчик путей и адреса сервера из Config.txt.

Config.txt лежит рядом с этим модулем (в папке проекта) и содержит строки
вида «КЛЮЧ = значение». Пустые строки и строки, начинающиеся с #,
игнорируются; значение можно заключить в кавычки.

Относительный путь считается относительно папки Config.txt.

Используется скриптами проекта: caption_images.py, translate_text_files.py,
caption_one_image.py, translate_one_text.py, TextImageGradioApp4.py.
Ключи Config.txt: testImg, testTxt, testEn, api_url
(и необязательные system_prompt_file, translation_prompt_file).
"""

from pathlib import Path

# Ключи, без которых скрипты работать не могут (в нижнем регистре:
# ключи в Config.txt не зависят от регистра)
REQUIRED_KEYS = ("testimg", "testtxt", "testen")

# Как эти ключи подписаны в Config.txt (для сообщений об ошибках)
DISPLAY_NAMES = {"testimg": "testImg", "testtxt": "testTxt", "testen": "testEn"}

# Ключи, которые можно не указывать (тогда берётся значение по умолчанию)
OPTIONAL_KEYS = {
    "system_prompt_file": "system_prompt.txt",
    "translation_prompt_file": "translation_prompt.txt",
}

# Ключ Config.txt с адресом llama-server и значение по умолчанию
API_URL_KEY = "api_url"
DEFAULT_API_URL = "http://127.0.0.1:8080/v1/chat/completions"

CONFIG_FILE = Path(__file__).resolve().with_name("Config.txt")


class ConfigError(RuntimeError):
    """Ошибка чтения или содержимого Config.txt."""


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def read_config(config_file: Path | None = None) -> dict:
    """Читает Config.txt и возвращает словарь {ключ: значение} без обработки путей."""
    config_file = CONFIG_FILE if config_file is None else Path(config_file)
    if not config_file.is_file():
        raise ConfigError(
            f"Не найден файл конфигурации:\n{config_file}"
        )

    raw = {}
    for number, line in enumerate(
        config_file.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(
                f"Config.txt, строка {number}: нет «=» в строке:\n{line}"
            )
        key, value = line.split("=", 1)
        key = _strip_quotes(key.strip()).lower()
        value = _strip_quotes(value.strip())
        if not key:
            raise ConfigError(f"Config.txt, строка {number}: пустой ключ.")
        raw[key] = value

    return raw


def _resolve(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def load_dirs(config_file: Path | None = None) -> dict:
    """
    Читает Config.txt и возвращает словарь:
        testImg  — Path с исходными изображениями
        testTxt  — Path с подписями (сюда пишет caption_images.py)
        testEn   — Path с переводом (сюда пишет translate_text_files.py)
        base     — Path с папкой Config.txt
    Относительные пути разрешаются относительно папки Config.txt.
    """
    config_file = CONFIG_FILE if config_file is None else Path(config_file)
    raw = read_config(config_file)
    base_dir = config_file.resolve().parent

    missing = [key for key in REQUIRED_KEYS if not raw.get(key)]
    if missing:
        raise ConfigError(
            "В Config.txt не заданы ключи: "
            + ", ".join(DISPLAY_NAMES[key] for key in missing)
            + f"\nФайл: {config_file}"
        )

    return {
        "base": base_dir,
        "testImg": _resolve(base_dir, raw["testimg"]),
        "testTxt": _resolve(base_dir, raw["testtxt"]),
        "testEn": _resolve(base_dir, raw["testen"]),
    }


def prompt_file(key: str, default_name: str, config_file: Path | None = None) -> Path:
    """
    Путь к файлу системного промпта: значение из Config.txt, если ключ задан,
    иначе default_name рядом с Config.txt. На направление перевода это не влияет:
    содержимое промпта скрипт читает как обычно.
    """
    config_file = CONFIG_FILE if config_file is None else Path(config_file)
    try:
        raw = read_config(config_file)
    except ConfigError:
        raw = {}

    value = raw.get(key.strip().lower()) or OPTIONAL_KEYS.get(key.strip().lower(), default_name)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_file.resolve().parent / path
    return path.resolve()


def api_url(config_file: Path | None = None) -> str:
    """
    Адрес llama-server из Config.txt (ключ api_url) — один на все скрипты.
    Если ключа нет или он пустой, берётся DEFAULT_API_URL.

    Можно указать как полный адрес запроса
    (http://127.0.0.1:8080/v1/chat/completions), так и только адрес сервера
    (http://127.0.0.1:8080 или http://127.0.0.1:8080/v1) — тогда нужный путь
    добавится сам.
    """
    config_file = CONFIG_FILE if config_file is None else Path(config_file)
    try:
        raw = read_config(config_file)
    except ConfigError:
        raw = {}

    value = (raw.get(API_URL_KEY) or "").strip()
    if not value:
        value = DEFAULT_API_URL

    if not value.lower().startswith(("http://", "https://")):
        raise ConfigError(
            f"В Config.txt ключ {API_URL_KEY} должен начинаться с http:// или https://\n"
            f"Прочитано: {value!r}\nФайл: {config_file}"
        )

    value = value.rstrip("/")
    if "chat/completions" not in value.lower():
        if value.lower().endswith("/v1"):
            value += "/chat/completions"
        else:
            value += "/v1/chat/completions"
    return value


def show_config(config_file: Path | None = None) -> None:
    """Печатает прочитанные пути и адрес сервера — удобно для проверки конфигурации."""
    dirs = load_dirs(config_file)
    print(f"Файл конфигурации: {(CONFIG_FILE if config_file is None else Path(config_file)).resolve()}")
    print(f"  testImg (изображения): {dirs['testImg']}")
    print(f"  testTxt (подписи):     {dirs['testTxt']}")
    print(f"  testEn  (перевод):      {dirs['testEn']}")
    print(f"  api_url (llama-server): {api_url(config_file)}")


if __name__ == "__main__":
    show_config()
