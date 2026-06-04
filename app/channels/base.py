from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.enums import Platform


@dataclass(slots=True)
class IncomingAttachment:
    attachment_id: str | None = None
    url: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    content: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IncomingMessageEvent:
    platform: Platform
    event_id: str
    chat_id: str
    user_id: str
    text: str | None = None
    callback_data: str | None = None
    sender_name: str | None = None
    from_address: str | None = None
    to_address: str | None = None
    contact_phone: str | None = None
    attachments: list[IncomingAttachment] = field(default_factory=list)
    options: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutgoingMessage:
    platform: Platform
    to_user_id: str
    text: str | None = None
    message_id: str | None = None
    attachments: list[IncomingAttachment] = field(default_factory=list)
    options: list[dict[str, Any]] = field(default_factory=list)
    template_sid: str | None = None
    template_variables: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MessagingGateway(Protocol):
    platform: Platform

    def validate_request(self, *, url: str, params: dict[str, str], signature: str | None) -> bool:
        ...

    def parse_incoming(self, params: dict[str, str]) -> IncomingMessageEvent:
        ...

    def download_media(self, url: str) -> bytes:
        ...

    def send_message(self, message: OutgoingMessage) -> dict[str, Any]:
        ...


def outgoing_from_legacy(platform: Platform, to_user_id: str, msg: dict[str, Any]) -> "OutgoingMessage":
    """Adapta los dicts legacy de la maquina de estados ({"text", "reply_markup"})
    al contrato OutgoingMessage agnostico de canal.

    - inline_keyboard de Telegram -> options [{"id": callback_data, "title": text}]
    - teclado de contacto de Telegram -> metadata["telegram_keyboard"] = "request_contact"
    """
    reply_markup = msg.get("reply_markup") or {}
    options: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}

    for row in reply_markup.get("inline_keyboard") or []:
        for button in row:
            options.append({"id": button.get("callback_data"), "title": button.get("text")})

    for row in reply_markup.get("keyboard") or []:
        for button in row:
            if isinstance(button, dict) and button.get("request_contact"):
                metadata["telegram_keyboard"] = "request_contact"

    return OutgoingMessage(
        platform=platform,
        to_user_id=to_user_id,
        text=msg.get("text"),
        options=options,
        metadata=metadata,
    )
