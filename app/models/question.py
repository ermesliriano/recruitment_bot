# app/models/question.py
from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base
from app.enums import AnswerType


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    code: Mapped[str] = mapped_column(String(80))
    prompt_text: Mapped[str] = mapped_column(Text)
    answer_type: Mapped[AnswerType] = mapped_column(
        SAEnum(AnswerType, name="answer_type_enum", create_type=False)
    )
    default_validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VacancyQuestion(Base):
    __tablename__ = "vacancy_questions"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    vacancy_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    question_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    question_order: Mapped[int] = mapped_column()
    field_key: Mapped[str] = mapped_column(String(120))
    prompt_override: Mapped[str | None] = mapped_column(Text)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    scoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
