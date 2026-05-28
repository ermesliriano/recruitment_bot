# app/models/candidate.py
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    phone_e164: Mapped[str] = mapped_column(String(32), index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    location_text: Mapped[str | None] = mapped_column(String(255))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)

    whatsapp_wa_id: Mapped[str | None] = mapped_column(String(64), index=True)
    whatsapp_from: Mapped[str | None] = mapped_column(String(128))
    whatsapp_profile_name: Mapped[str | None] = mapped_column(String(255))
    whatsapp_opt_in_status: Mapped[str] = mapped_column(String(40), default="unknown")
    whatsapp_opt_in_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_inbound_whatsapp_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
