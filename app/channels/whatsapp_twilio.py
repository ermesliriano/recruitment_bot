from __future__ import annotations

import json
import mimetypes
from typing import Any
from urllib.parse import parse_qsl

import httpx
from twilio.request_validator import RequestValidator
from twilio.rest import Client

from app.channels.base import IncomingAttachment, IncomingMessageEvent, MessagingGateway, OutgoingMessage
from app.core.config import settings
from app.cv_pipeline import normalize_phone
from app.enums import Platform


def _safe_int(raw: str | None, default: int = 0) -> int:
    try:
        return int(raw or default)
    except (TypeError, ValueError):
        return default


def _file_name_for_media(index: int, mime_type: str | None) -> str:
    ext = mimetypes.guess_extension(mime_type or "") or ""
    return f"media_{index}{ext}"


class TwilioWhatsAppGateway(MessagingGateway):
    platform = Platform.WHATSAPP

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        messaging_service_sid: str | None = None,
        from_address: str | None = None,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.messaging_service_sid = messaging_service_sid
        self.from_address = from_address
        self._validator = RequestValidator(auth_token)
        self._client = Client(account_sid, auth_token)
        self._http = httpx.Client(
            timeout=60,
            auth=(account_sid, auth_token),
            headers={"User-Agent": "recruitment-bot/whatsapp-twilio"},
        )

    @classmethod
    def from_tenant(cls, tenant) -> "TwilioWhatsAppGateway":
        return cls(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            messaging_service_sid=tenant.whatsapp_messaging_service_sid or settings.twilio_whatsapp_messaging_service_sid,
            from_address=tenant.whatsapp_sender_address or settings.twilio_whatsapp_from_address,
        )

    @staticmethod
    def form_params_from_body(raw_body: bytes) -> dict[str, str]:
        return dict(parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True))

    def validate_request(self, *, url: str, params: dict[str, str], signature: str | None) -> bool:
        if not signature:
            return False
        return self._validator.validate(url, params, signature)

    def parse_incoming(self, params: dict[str, str]) -> IncomingMessageEvent:
        num_media = _safe_int(params.get("NumMedia"))
        from_address = params.get("From") or ""
        to_address = params.get("To") or ""
        wa_id = params.get("WaId") or from_address.removeprefix("whatsapp:").lstrip("+")
        body = params.get("Body") or None
        button_payload = params.get("ButtonPayload") or None
        button_text = params.get("ButtonText") or None

        contact_phone = None
        raw_candidate_phone = from_address.removeprefix("whatsapp:")
        if raw_candidate_phone:
            try:
                contact_phone = normalize_phone(raw_candidate_phone)
            except Exception:
                contact_phone = raw_candidate_phone

        attachments: list[IncomingAttachment] = []
        for idx in range(num_media):
            media_url = params.get(f"MediaUrl{idx}")
            if not media_url:
                continue
            mime_type = params.get(f"MediaContentType{idx}") or "application/octet-stream"
            attachments.append(
                IncomingAttachment(
                    attachment_id=media_url.rsplit("/", 1)[-1],
                    url=media_url,
                    filename=_file_name_for_media(idx, mime_type),
                    mime_type=mime_type,
                    metadata={"twilio_media_index": idx},
                )
            )

        return IncomingMessageEvent(
            platform=Platform.WHATSAPP,
            event_id=params.get("MessageSid") or params.get("SmsSid") or "",
            chat_id=from_address or (contact_phone or wa_id),
            user_id=wa_id or from_address,
            text=body or button_text,
            callback_data=button_payload,
            sender_name=params.get("ProfileName") or None,
            from_address=from_address or None,
            to_address=to_address or None,
            contact_phone=contact_phone,
            attachments=attachments,
            raw_payload=params,
        )

    def download_media(self, url: str) -> bytes:
        # La URL de media de Twilio (api.twilio.com/.../Media/ME...) responde con
        # un 307 hacia el CDN pre-firmado (mms.twiliocdn.com). Hay que seguir el
        # redirect; httpx elimina la cabecera Authorization al cambiar de host,
        # y el CDN no la necesita porque la URL ya va firmada.
        response = self._http.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.content

    def _normalize_to(self, raw_to: str) -> str:
        if raw_to.startswith("whatsapp:"):
            return raw_to
        return f"whatsapp:{raw_to}"

    def _render_plain_text(self, text: str | None, options: list[dict[str, Any]]) -> str:
        base = (text or "").strip()
        if not options:
            return base
        lines = [base] if base else []
        for index, option in enumerate(options, start=1):
            lines.append(f"{index}. {option['title']}")
        return "\n".join(lines)

    def send_message(self, message: OutgoingMessage) -> dict[str, Any]:
        to_address = self._normalize_to(message.to_user_id)

        if message.template_sid:
            payload: dict[str, Any] = {
                "to": to_address,
                "content_sid": message.template_sid,
                "content_variables": json.dumps(message.template_variables or {}, ensure_ascii=False),
            }
            if self.messaging_service_sid:
                payload["messaging_service_sid"] = self.messaging_service_sid
            elif self.from_address:
                payload["from_"] = self.from_address

            twilio_message = self._client.messages.create(**payload)
            return {
                "message_id": twilio_message.sid,
                "status": twilio_message.status,
                "raw": twilio_message,
            }

        body = self._render_plain_text(message.text, message.options)

        payload = {
            "to": to_address,
            "body": body,
        }
        if self.messaging_service_sid:
            payload["messaging_service_sid"] = self.messaging_service_sid
        elif self.from_address:
            payload["from_"] = self.from_address

        twilio_message = self._client.messages.create(**payload)
        return {
            "message_id": twilio_message.sid,
            "status": twilio_message.status,
            "raw": twilio_message,
        }
