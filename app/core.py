# app/core.py
"""
Re-exportaciones para compatibilidad hacia atrás.
Los módulos nuevos importan desde app.enums, app.config y app.database directamente.
"""
from app.enums import (  # noqa: F401
    AiEvalStatus,
    AnswerType,
    ApplicationStatus,
    ChatState,
    Classification,
    CvParseStatus,
    Platform,
    ScoringOperator,
    SourceScope,
    StorageBackendType,
    VacancyStatus,
)
from app.config import settings  # noqa: F401
from app.database import Base, SessionLocal, engine, get_db, utcnow  # noqa: F401
