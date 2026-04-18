# app/core.py
import enum
from decimal import Decimal
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, func
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SAEnum, Integer, Numeric, String, Text

class Settings(BaseSettings):
    database_url: str
    admin_token: str = "change-me"
    llm_api_key: str
    llm_url: str = "https://apifreellm.com/api/v1/chat"
    llm_model: str = "apifreellm"
    llm_max_retries: int = 3
    llm_cv_char_limit: int = 18000
    storage_backend: str = "db_blob"  # db_blob | local_fs | s3
    storage_root: str = "./storage"
    default_phone_region: str = "ES"
    top_n_notify: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)

class Base(DeclarativeBase):
    pass

def utcnow():
    return func.now()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class Platform(str, enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"

class VacancyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"

class AnswerType(str, enum.Enum):
    TEXT = "text"
    BOOLEAN = "boolean"
    NUMBER = "number"

class ScoringOperator(str, enum.Enum):
    EQUALS = "equals"
    CONTAINS = "contains"
    GTE = "gte"

class SourceScope(str, enum.Enum):
    ANSWER = "answer"
    CANDIDATE = "candidate"
    AI = "ai"

class ApplicationStatus(str, enum.Enum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    PENDING_AI = "pending_ai"
    SCORING = "scoring"
    REVIEW = "review"
    INTERVIEW = "interview"
    SHORTLIST = "shortlist"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"
    CLOSED = "closed"

class Classification(str, enum.Enum):
    REJECT = "reject"
    REVIEW = "review"
    INTERVIEW = "interview"
    SHORTLIST = "shortlist"

class ChatState(str, enum.Enum):
    WELCOME = "WELCOME"
    SELECT_VACANCY = "SELECT_VACANCY"
    CAPTURE_NAME = "CAPTURE_NAME"
    VACANCY_QA_MODE = "VACANCY_QA_MODE"
    REQUEST_CV = "REQUEST_CV"
    ASK_VACANCY_QUESTIONS = "ASK_VACANCY_QUESTIONS"
    SCORING = "SCORING"
    CONFIRM_AND_CLOSE = "CONFIRM_AND_CLOSE"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"

class CvParseStatus(str, enum.Enum):
    PENDING = "pending"
    PARSED = "parsed"
    OCR_FALLBACK = "ocr_fallback"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"

class AiEvalStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"

class StorageBackendType(str, enum.Enum):
    DB_BLOB = "db_blob"
    LOCAL_FS = "local_fs"
    S3 = "s3"