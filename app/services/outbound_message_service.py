from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import desc, select

from app.channels.base import OutgoingMessage
from app.channels.whatsapp_twilio import TwilioWhatsAppGateway
from app.enums import Platform
from app.models.outbound_message import OutboundMessage
from app.models.session import ConversationSession
from app.services.conversation_log import record_outgoing_direct
from app.telegram_api import TelegramGateway


class OutboundMessageService:
    def deliver_batch(self, db, tenant, messages: Iterable[OutgoingMessage]) -> list[OutboundMessage]:
        results: list[OutboundMessage] = []
        for message in messages:
            results.append(self.deliver(db, tenant, message))
        db.commit()
        return results

    def deliver(self, db, tenant, message: OutgoingMessage) -> OutboundMessage:
        record = OutboundMessage(
            tenant_id=tenant.id,
            candidate_id=message.metadata.get("candidate_id"),
            application_id=message.metadata.get("application_id"),
            conversation_session_id=message.metadata.get("conversation_session_id"),
            channel=message.platform,
            provider="telegram" if message.platform == Platform.TELEGRAM else "twilio",
            to_address=message.to_user_id,
            template_sid=message.template_sid,
            content_text=message.text,
            content_variables=message.template_variables or {},
            status="queued",
        )
        db.add(record)
        db.flush()

        try:
            if message.platform == Platform.TELEGRAM:
                result = self._send_telegram(tenant, message)
            elif message.platform == Platform.WHATSAPP:
                result = self._send_whatsapp(db, tenant, message)
            else:
                raise RuntimeError(f"Canal no soportado: {message.platform}")

            record.provider_message_sid = result.get("message_id")
            record.status = result.get("status") or "sent"
            record.sent_at = datetime.now(timezone.utc)
            db.flush()

            # Transcripcion: registrar el saliente directo con la MISMA clave de
            # hilo que usara el inbound del canal, para que queden en un hilo unico.
            if message.platform == Platform.WHATSAPP:
                thread_id = f"whatsapp:{message.to_user_id}"
            else:
                thread_id = str(message.to_user_id)
            text = message.text
            if not text and message.template_sid:
                variables = message.template_variables or {}
                text = (
                    f"[Plantilla inicial] Hola {variables.get('1', 'candidato/a')}, "
                    f"te contactamos por la vacante {variables.get('2', '')}."
                ).strip()
            record_outgoing_direct(
                db,
                tenant_id=tenant.id,
                platform=message.platform,
                platform_chat_id=thread_id,
                text=text,
                candidate_id=message.metadata.get("candidate_id"),
                application_id=message.metadata.get("application_id"),
                session_id=message.metadata.get("conversation_session_id"),
                message_type="template" if message.template_sid else "text",
                external_id=record.provider_message_sid,
            )
            return record

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            db.flush()
            raise

    def _send_telegram(self, tenant, message: OutgoingMessage) -> dict:
        gateway = TelegramGateway(tenant.telegram_bot_token)
        reply_markup = None

        if message.metadata.get("telegram_keyboard") == "request_contact":
            reply_markup = TelegramGateway.phone_keyboard()
        elif message.options:
            reply_markup = {
                "inline_keyboard": [
                    [{"text": option["title"], "callback_data": option["id"]}]
                    for option in message.options
                ]
            }

        response = gateway.send_message(
            int(message.to_user_id),
            message.text or "",
            reply_markup,
        )
        result = response.get("result", {})
        return {
            "message_id": str(result.get("message_id") or ""),
            "status": "sent",
        }

    def _assert_whatsapp_window(self, db, message: OutgoingMessage) -> None:
        if message.template_sid:
            return

        session_id = message.metadata.get("conversation_session_id")
        if not session_id:
            raise RuntimeError("No hay session id para validar la ventana de WhatsApp.")

        session = db.execute(
            select(ConversationSession).where(ConversationSession.id == session_id)
        ).scalar_one_or_none()

        if not session or not session.last_user_message_at:
            raise RuntimeError("No existe ventana abierta de 24 horas para mensajes libres.")

        limit = datetime.now(timezone.utc) - timedelta(hours=24)
        if session.last_user_message_at < limit:
            raise RuntimeError("La ventana de 24 horas de WhatsApp está cerrada.")

    def _send_whatsapp(self, db, tenant, message: OutgoingMessage) -> dict:
        self._assert_whatsapp_window(db, message)
        gateway = TwilioWhatsAppGateway.from_tenant(tenant)
        return gateway.send_message(message)

    def send_seeded_template(
        self,
        db,
        tenant,
        *,
        candidate_id,
        application_id,
        conversation_session_id,
        to_phone_e164: str,
        candidate_name: str | None,
        vacancy_title: str,
    ) -> OutboundMessage:
        message = OutgoingMessage(
            platform=Platform.WHATSAPP,
            to_user_id=to_phone_e164,
            template_sid=tenant.whatsapp_initial_template_sid,
            template_variables={
                "1": candidate_name or "candidato/a",
                "2": vacancy_title,
            },
            metadata={
                "candidate_id": str(candidate_id),
                "application_id": str(application_id),
                "conversation_session_id": str(conversation_session_id),
            },
        )
        return self.deliver(db, tenant, message)

    def latest_outbound_for_application(self, db, application_id):
        return db.execute(
            select(OutboundMessage)
            .where(OutboundMessage.application_id == application_id)
            .order_by(desc(OutboundMessage.created_at))
        ).scalars().first()
