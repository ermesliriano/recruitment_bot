from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class CvImportJob(Base):
    __tablename__ = "cv_import_jobs"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    vacancy_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CvImportJobItem(Base):
    __tablename__ = "cv_import_job_items"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    job_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    candidate_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    application_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    outbound_status: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    extraction_status: Mapped[str | None] = mapped_column(String(40))
    detected_phone_e164: Mapped[str | None] = mapped_column(String(32), index=True)
    phone_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    phone_candidates_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    extracted_preview: Mapped[str | None] = mapped_column(Text)
    candidate_reused: Mapped[bool] = mapped_column(Boolean, default=False)
    application_reused: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
