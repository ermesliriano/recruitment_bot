# app/models/vacancy.py
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, DateTime, Enum as SAEnum, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base
from app.enums import VacancyStatus


class Vacancy(Base):
    __tablename__ = "vacancies"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
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
    classification_thresholds: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: {"review": 35, "interview": 60, "shortlist": 75}
    )
    status: Mapped[VacancyStatus] = mapped_column(
        SAEnum(VacancyStatus, name="vacancy_status_enum", create_type=False),
        default=VacancyStatus.DRAFT,
    )
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
