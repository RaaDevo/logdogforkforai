import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import SecretStr

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")


def _get_env_var(key: str, defaultValue: str | None = None) -> SecretStr:
    value = os.environ.get(key)
    if value is None:
        value = defaultValue
    if value is None:
        raise ValueError(f"Environment variable '{key}' is not defined.")
    value = value.strip().strip("'\"").strip()
    return SecretStr(value)


SECRET_KEY = _get_env_var("SECRET_KEY")

DATABASE_URL = _get_env_var("DATABASE_URL")
MEGABASE_URL = _get_env_var("MEGABASE_URL")

BUCKET_ENDPOINT_URL = _get_env_var("BUCKET_ENDPOINT_URL")
BUCKET_ACCESS_KEY = _get_env_var("BUCKET_ACCESS_KEY")
BUCKET_SECRET_KEY = _get_env_var("BUCKET_SECRET_KEY")
BUCKET_NAME = _get_env_var("BUCKET_NAME")
BUCKET_PREFIX = _get_env_var("BUCKET_PREFIX")

OPENROUTER_API_KEY = _get_env_var("OPENROUTER_API_KEY")
OPENROUTER_TITLE = _get_env_var("OPENROUTER_TITLE")
OPENROUTER_REFERER = _get_env_var("OPENROUTER_REFERER")
OPENROUTER_MODEL = _get_env_var("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
