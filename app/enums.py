# app/enums.py
"""
Única fuente de verdad para todos los enums de la aplicación.
Los valores deben coincidir exactamente con los tipos enum de PostgreSQL en schema.sql.
"""
import enum


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
    WAITING_CANDIDATE_REPLY = "waiting_candidate_reply"
    BLOCKED_NO_OPT_IN = "blocked_no_opt_in"
    REVIEW = "review"
    INTERVIEW = "interview"
    SHORTLIST = "shortlist"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"
    CLOSED = "closed"


class ApplicationOrigin(str, enum.Enum):
    INBOUND_TELEGRAM = "inbound_telegram"
    INBOUND_WHATSAPP = "inbound_whatsapp"
    RECRUITER_UPLOAD = "recruiter_upload"


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
    ASK_TENANT_QUESTIONS = "ASK_TENANT_QUESTIONS"
    REQUEST_CV = "REQUEST_CV"
    WAITING_CANDIDATE_REPLY = "WAITING_CANDIDATE_REPLY"
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
