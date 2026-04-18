# app/models_enum.py
from enum import Enum


class VacancyStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class AnswerType(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    CHOICE = "choice"


class SourceScope(str, Enum):
    ANSWER = "answer"
    CV = "cv"
    PROFILE = "profile"


class ScoringOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_OR_EQUAL = "less_or_equal"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"


class ApplicationStatus(str, Enum):
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DISQUALIFIED = "disqualified"
    REVIEWED = "reviewed"
    HIRED = "hired"
    REJECTED = "rejected"


class Classification(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class StorageBackendType(str, Enum):
    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"
    TELEGRAM = "telegram"


class CvParseStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class AiEvalStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class Platform(str, Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    WEB = "web"


class ChatState(str, Enum):
    IDLE = "idle"
    COLLECTING_NAME = "collecting_name"
    COLLECTING_PHONE = "collecting_phone"
    COLLECTING_ANSWERS = "collecting_answers"
    UPLOADING_CV = "uploading_cv"
    AWAITING_CV_PROCESSING = "awaiting_cv_processing"
    COMPLETED = "completed"
    DISQUALIFIED = "disqualified"