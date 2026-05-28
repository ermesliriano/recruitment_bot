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
