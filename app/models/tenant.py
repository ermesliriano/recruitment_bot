# app/models/tenant.py
from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    hr_email: Mapped[str | None] = mapped_column(String(255))
    telegram_bot_token: Mapped[str | None] = mapped_column(Text)
    telegram_webhook_secret: Mapped[str | None] = mapped_column(Text)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
