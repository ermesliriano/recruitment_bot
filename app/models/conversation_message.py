# app/models/conversation_message.py
from __future__ import annotations

from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base
from app.enums import Platform


class ConversationMessage(Base):
    """Transcripcion de la conversacion con el candidato: una fila por mensaje.

    direction: 'in' (mensaje del candidato) | 'out' (mensaje del bot/sistema).
    platform_chat_id: clave del hilo (whatsapp:+E164, chat_id de Telegram o email),
    la misma que usa conversation_sessions, para poder agrupar por hilo incluso
    antes de que exista el candidato.
    """

    __tablename__ = "conversation_messages"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    candidate_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    application_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    session_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", create_type=False),
        nullable=False,
    )
    platform_chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    message_text: Mapped[str | None] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(30), default="text")
    attachment_filename: Mapped[str | None] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
