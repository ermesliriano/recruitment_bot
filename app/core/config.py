# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Base de datos
    database_url: str

    # Seguridad
    admin_token: str = "change-me"
    allow_origins: str = "*"

    # Telegram (por tenant; aquí valores por defecto opcionales)
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_url: str = "https://api.openai.com/v1/chat/completions"
    llm_max_retries: int = 3
    llm_cv_char_limit: int = 18_000

    # Almacenamiento de CVs
    storage_backend: str = "db_blob"   # db_blob | local_fs
    storage_root: str = "./storage"

    # Opciones de aplicación
    default_phone_region: str = "ES"
    top_n_notify: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
