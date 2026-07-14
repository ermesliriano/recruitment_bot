# app/services/conversation_log.py
"""
Registro de la transcripcion de conversaciones (conversation_messages).

Puntos de registro (sin duplicados):
  - Mensajes ENTRANTES del candidato: en RecruitmentService.dispatch, justo
    despues del filtro de deduplicacion por event_id.
  - Mensajes SALIENTES del bot en conversaciones inbound: en los webhooks, tras
    obtener las respuestas del dispatch (antes de entregarlas al gateway).
  - Mensajes SALIENTES directos (plantilla seeded de WhatsApp, correo outbound
    con preguntas agrupadas): en OutboundMessageService.deliver y en el envio
    de email del intake.

El registro NUNCA debe romper el flujo: todas las funciones capturan y
loguean sus propios errores.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.enums import Platform
from app.models.conversation_message import ConversationMessage
from app.models.session import ConversationSession

logger = logging.getLogger(__name__)


def _thread_chat_id(event) -> str:
    return str(event.chat_id or event.from_address or "")


def _session_for_thread(db, tenant_id, platform: Platform, chat_id: str) -> ConversationSession | None:
    try:
        return db.execute(
            select(ConversationSession).where(
                ConversationSession.tenant_id == tenant_id,
                ConversationSession.platform == platform,
                ConversationSession.platform_chat_id == chat_id,
                ConversationSession.is_active.is_(True),
            )
        ).scalar_one_or_none()
    except Exception:
        return None


def record_incoming(db, tenant, event, session: ConversationSession | None = None) -> None:
    """Registra el mensaje entrante del candidato (texto y/o adjunto)."""
    try:
        chat_id = _thread_chat_id(event)
        if not chat_id:
            return
        if session is None:
            session = _session_for_thread(db, tenant.id, event.platform, chat_id)

        attachment = event.attachments[0] if event.attachments else None
        message_type = "text"
        if attachment is not None:
            mime = (attachment.mime_type or "").lower()
            if "pdf" in mime or "msword" in mime or "officedocument" in mime:
                message_type = "document"
            elif mime.startswith("image/"):
                message_type = "image"
            elif mime.startswith("audio/"):
                message_type = "audio"
            else:
                message_type = "document"

        db.add(ConversationMessage(
            tenant_id=tenant.id,
            candidate_id=session.candidate_id if session else None,
            application_id=session.application_id if session else None,
            session_id=session.id if session else None,
            platform=event.platform,
            platform_chat_id=chat_id,
            direction="in",
            message_text=event.text or None,
            message_type=message_type,
            attachment_filename=attachment.filename if attachment else None,
            external_id=event.event_id,
        ))
        db.flush()
    except Exception:
        logger.exception("No se pudo registrar el mensaje entrante en la transcripcion")


def record_outgoing_batch(db, tenant, event, messages: list[dict[str, Any]]) -> None:
    """Registra las respuestas del bot a un mensaje inbound (una fila por mensaje)."""
    try:
        chat_id = _thread_chat_id(event)
        if not chat_id or not messages:
            return
        session = _session_for_thread(db, tenant.id, event.platform, chat_id)

        for message in messages:
            text = message.get("text")
            if not text:
                continue
            db.add(ConversationMessage(
                tenant_id=tenant.id,
                candidate_id=session.candidate_id if session else None,
                application_id=session.application_id if session else None,
                session_id=session.id if session else None,
                platform=event.platform,
                platform_chat_id=chat_id,
                direction="out",
                message_text=text,
                message_type="text",
            ))
        db.flush()
    except Exception:
        logger.exception("No se pudo registrar la respuesta del bot en la transcripcion")


def record_outgoing_direct(
    db,
    *,
    tenant_id,
    platform: Platform,
    platform_chat_id: str,
    text: str | None,
    candidate_id=None,
    application_id=None,
    session_id=None,
    message_type: str = "text",
    external_id: str | None = None,
) -> None:
    """Registra un mensaje saliente directo (plantilla seeded, email outbound...)."""
    try:
        if not platform_chat_id:
            return
        db.add(ConversationMessage(
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            application_id=application_id,
            session_id=session_id,
            platform=platform,
            platform_chat_id=platform_chat_id,
            direction="out",
            message_text=text,
            message_type=message_type,
            external_id=external_id,
        ))
        db.flush()
    except Exception:
        logger.exception("No se pudo registrar el mensaje saliente directo en la transcripcion")
