# app/models/application.py
# app/models/application.py
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base
from app.enums import ApplicationOrigin, ApplicationStatus, Classification, Platform


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    candidate_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    vacancy_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)

    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus, name="application_status_enum", create_type=False),
        default=ApplicationStatus.DRAFT,
    )

    origin: Mapped[ApplicationOrigin] = mapped_column(
        SAEnum(ApplicationOrigin, name="application_origin_enum", create_type=False),
        default=ApplicationOrigin.INBOUND_TELEGRAM,
    )

    preferred_platform: Mapped[Platform | None] = mapped_column(
        SAEnum(Platform, name="platform_enum", create_type=False),
        nullable=True,
    )

    score_rules: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        default=Decimal("0"),
    )

    score_cv: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )

    score_total: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2),
        nullable=True,
    )

    classification: Mapped[Classification | None] = mapped_column(
        SAEnum(Classification, name="classification_enum", create_type=False),
        nullable=True,
    )

    is_disqualified: Mapped[bool] = mapped_column(Boolean, default=False)
    disqualification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    application_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)

    # Pregunta asociada a una vacante concreta.
    vacancy_question_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True),
        index=True,
        nullable=True,
    )

    # Pregunta genérica del tenant.
    tenant_question_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True),
        index=True,
        nullable=True,
    )

    field_key: Mapped[str] = mapped_column(String(120))

    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_number: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    answer_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )