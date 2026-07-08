# app/core/config.py
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    admin_token: str = "change-me"
    allow_origins: str = "*"
    public_base_url: str | None = None

    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_messaging_service_sid: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "twilio_whatsapp_messaging_service_sid", "TWILIO_MESSAGING_SERVICE_SID"
        ),
    )
    twilio_whatsapp_from_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("twilio_whatsapp_from_address", "TWILIO_WHATSAPP_FROM"),
    )
    twilio_whatsapp_default_template_sid: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "twilio_whatsapp_default_template_sid", "TWILIO_CONTENT_SID_CV_RECEIVED"
        ),
    )
    twilio_whatsapp_default_template_language: str = Field(
        default="es",
        validation_alias=AliasChoices(
            "twilio_whatsapp_default_template_language", "TWILIO_TEMPLATE_LANGUAGE"
        ),
    )
    whatsapp_default_tenant_slug: str | None = None

    # Canal email (Twilio SendGrid)
    sendgrid_api_key: str = ""
    sendgrid_inbound_token: str | None = None
    sendgrid_event_webhook_public_key: str | None = None
    email_default_from: str | None = None
    email_default_from_name: str = "Equipo de Reclutamiento"
    # Dominio con MX apuntando a SendGrid Inbound Parse (p. ej. reply.cesaria.net).
    email_inbound_domain: str | None = None
    email_default_tenant_slug: str | None = None

    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_url: str = "https://api.openai.com/v1/chat/completions"
    llm_max_retries: int = 3
    llm_cv_char_limit: int = 18_000

    storage_backend: str = "db_blob"
    storage_root: str = "./storage"

    default_phone_region: str = "ES"
    top_n_notify: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
