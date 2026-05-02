# app/models/scoring_rule.py
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base
from app.enums import ScoringOperator, SourceScope


class ScoringRule(Base):
    __tablename__ = "scoring_rules"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    vacancy_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_scope: Mapped[SourceScope] = mapped_column(
        SAEnum(SourceScope, name="source_scope_enum", create_type=False)
    )
    field_key: Mapped[str] = mapped_column(String(120))
    operator: Mapped[ScoringOperator] = mapped_column(
        SAEnum(ScoringOperator, name="scoring_operator_enum", create_type=False)
    )
    expected_text: Mapped[str | None] = mapped_column(Text)
    expected_number: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    expected_boolean: Mapped[bool | None] = mapped_column(Boolean)
    points: Mapped[int] = mapped_column(Integer, default=0)
    is_disqualifier: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
