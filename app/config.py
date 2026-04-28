# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    admin_token: str = "change-me"

    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_url: str = "https://api.openai.com/v1/chat/completions"
    llm_max_retries: int = 3
    llm_cv_char_limit: int = 18_000

    storage_backend: str = "db_blob"   # db_blob | local_fs | s3
    storage_root: str = "./storage"

    default_phone_region: str = "ES"
    top_n_notify: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
