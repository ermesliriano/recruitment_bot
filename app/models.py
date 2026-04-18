# app/models.py
from typing import Any
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID

from app.core import Base

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    hr_email: Mapped[str | None] = mapped_column(String(255))
    telegram_bot_token: Mapped[str | None] = mapped_column(Text)
    telegram_webhook_secret: Mapped[str | None] = mapped_column(Text)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Vacancy(Base):
    __tablename__ = "vacancies"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    code: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    responsibilities: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    mandatory_requirements: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    desirable_requirements: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    salary_text: Mapped[str | None] = mapped_column(Text)
    schedule_text: Mapped[str | None] = mapped_column(Text)
    location_text: Mapped[str | None] = mapped_column(Text)
    benefits: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    faq_context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cv_score_factor: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("6.00"))
    classification_thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[VacancyStatus] = mapped_column(SAEnum(VacancyStatus, name="vacancy_status_enum"))
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=utcnow())

class Question(Base):
    __tablename__ = "questions"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    code: Mapped[str] = mapped_column(String(80))
    prompt_text: Mapped[str] = mapped_column(Text)
    answer_type: Mapped[AnswerType] = mapped_column(SAEnum(AnswerType, name="answer_type_enum"))
    default_validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

class VacancyQuestion(Base):
    __tablename__ = "vacancy_questions"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    vacancy_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    question_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    question_order: Mapped[int] = mapped_column(Integer)
    field_key: Mapped[str] = mapped_column(String(120))
    prompt_override: Mapped[str | None] = mapped_column(Text)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    scoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class ScoringRule(Base):
    __tablename__ = "scoring_rules"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    vacancy_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_scope: Mapped[SourceScope] = mapped_column(SAEnum(SourceScope, name="source_scope_enum"))
    field_key: Mapped[str] = mapped_column(String(120))
    operator: Mapped[ScoringOperator] = mapped_column(SAEnum(ScoringOperator, name="scoring_operator_enum"))
    expected_text: Mapped[str | None] = mapped_column(Text)
    expected_number: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    expected_boolean: Mapped[bool | None] = mapped_column(Boolean)
    points: Mapped[int] = mapped_column(Integer, default=0)
    is_disqualifier: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    phone_e164: Mapped[str] = mapped_column(String(32), index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    location_text: Mapped[str | None] = mapped_column(String(255))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

class Application(Base):
    __tablename__ = "applications"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    candidate_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    vacancy_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[ApplicationStatus] = mapped_column(SAEnum(ApplicationStatus, name="application_status_enum"))
    score_rules: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    score_cv: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    score_total: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    classification: Mapped[Classification | None] = mapped_column(SAEnum(Classification, name="classification_enum"))
    is_disqualified: Mapped[bool] = mapped_column(Boolean, default=False)
    disqualification_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=utcnow())

class Answer(Base):
    __tablename__ = "answers"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    application_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    vacancy_question_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    field_key: Mapped[str] = mapped_column(String(120))
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_number: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    answer_boolean: Mapped[bool | None] = mapped_column(Boolean)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)

class CvDocument(Base):
    __tablename__ = "cv_documents"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    application_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(255))
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255))
    storage_backend: Mapped[StorageBackendType] = mapped_column(SAEnum(StorageBackendType, name="storage_backend_enum"))
    storage_key: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes | None] = mapped_column(BYTEA)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[CvParseStatus] = mapped_column(SAEnum(CvParseStatus, name="cv_parse_status_enum"))

class AiEvaluation(Base):
    __tablename__ = "ai_evaluations"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    application_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    cv_document_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[AiEvalStatus] = mapped_column(SAEnum(AiEvalStatus, name="ai_eval_status_enum"))
    raw_response: Mapped[str | None] = mapped_column(Text)
    parsed_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    candidate_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    experience_summary: Mapped[list[Any] | None] = mapped_column(JSONB)
    skills: Mapped[list[Any] | None] = mapped_column(JSONB)
    red_flags: Mapped[list[Any] | None] = mapped_column(JSONB)
    cv_score_0_10: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    recommendation: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    platform: Mapped[Platform] = mapped_column(SAEnum(Platform, name="platform_enum"))
    platform_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform_user_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    application_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    current_state: Mapped[ChatState] = mapped_column(SAEnum(ChatState, name="state_enum"))
    state_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_incoming_update_id: Mapped[int | None] = mapped_column(BigInteger)
    invalid_input_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
