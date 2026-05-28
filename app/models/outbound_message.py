from __future__ import annotations

from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base
from app.enums import Platform


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), index=True)
    candidate_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    application_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    conversation_session_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    channel: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", create_type=False),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), default="internal")
    to_address: Mapped[str] = mapped_column(String(255))
    template_sid: Mapped[str | None] = mapped_column(String(64))
    content_text: Mapped[str | None] = mapped_column(Text)
    content_variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    provider_message_sid: Mapped[str | None] = mapped_column(String(64), index=True)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
