# app/models/session.py
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SAEnum, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base
from app.enums import ChatState, Platform


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", create_type=False),
        default=Platform.TELEGRAM,
    )
    platform_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform_user_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    application_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    current_state: Mapped[ChatState] = mapped_column(
        SAEnum(ChatState, name="state_enum", create_type=False),
        default=ChatState.WELCOME,
    )
    state_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_incoming_update_id: Mapped[int | None] = mapped_column(BigInteger)
    invalid_input_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    level: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    event: Mapped[str] = mapped_column(String)
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    traceback: Mapped[str | None] = mapped_column(Text)
    application_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    conversation_session_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
