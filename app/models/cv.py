# app/models/cv.py
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base
from app.enums import AiEvalStatus, CvParseStatus, StorageBackendType


class CvDocument(Base):
    __tablename__ = "cv_documents"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
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
    storage_backend: Mapped[StorageBackendType] = mapped_column(
        SAEnum(StorageBackendType, name="storage_backend_enum", create_type=False)
    )
    storage_key: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes | None] = mapped_column(BYTEA)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[CvParseStatus] = mapped_column(
        SAEnum(CvParseStatus, name="cv_parse_status_enum", create_type=False),
        default=CvParseStatus.PENDING,
    )
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiEvaluation(Base):
    __tablename__ = "ai_evaluations"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    application_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    cv_document_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[AiEvalStatus] = mapped_column(
        SAEnum(AiEvalStatus, name="ai_eval_status_enum", create_type=False),
        default=AiEvalStatus.PENDING,
    )
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
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
