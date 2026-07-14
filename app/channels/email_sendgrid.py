# app/channels/email_sendgrid.py
"""
Gateway de correo saliente via Twilio SendGrid (API v3 /mail/send).

Fase 1 del canal email: solo outbound. El remitente por tenant se lee de
tenant.settings_json["email_from"], con respaldo en settings.email_default_from.
El Reply-To apunta al correo institucional del tenant (si existe) para que las
respuestas lleguen a un buzon humano mientras el inbound automatico no exista.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings

SENDGRID_SEND_URL = "https://api.sendgrid.com/v3/mail/send"


class SendGridEmailError(RuntimeError):
    pass


class SendGridEmailGateway:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=30)

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        from_email: str,
        from_name: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        if not settings.sendgrid_api_key:
            raise SendGridEmailError("SENDGRID_API_KEY no esta configurada.")
        if not from_email:
            raise SendGridEmailError("No hay remitente configurado (email_from / EMAIL_DEFAULT_FROM).")

        content = [{"type": "text/plain", "value": text_body}]
        if html_body:
            content.append({"type": "text/html", "value": html_body})

        payload: dict[str, Any] = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email, **({"name": from_name} if from_name else {})},
            "subject": subject,
            "content": content,
        }
        if reply_to:
            payload["reply_to"] = {"email": reply_to}

        resp = self._client.post(
            SENDGRID_SEND_URL,
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code >= 300:
            raise SendGridEmailError(
                f"SendGrid devolvio {resp.status_code}: {resp.text[:500]}"
            )
        return {
            "status_code": resp.status_code,
            # X-Message-Id permite correlacionar con el Event Webhook en el futuro.
            "message_id": resp.headers.get("X-Message-Id"),
        }


def tenant_inbound_address(tenant) -> str | None:
    """Direccion del canal inbound del tenant.
    Prioridad: direccion explicita del tenant > direccion GLOBAL de la plataforma
    (EMAIL_INBOUND_ADDRESS) > slug@EMAIL_INBOUND_DOMAIN."""
    raw = tenant.settings_json or {}
    explicit = (raw.get("email_inbound_address") or "").strip()
    if explicit:
        return explicit
    if settings.email_inbound_address:
        return settings.email_inbound_address.strip()
    if settings.email_inbound_domain and getattr(tenant, "slug", None):
        return f"{tenant.slug}@{settings.email_inbound_domain}"
    return None


def tenant_email_sender(tenant) -> tuple[str | None, str | None, str | None]:
    """(from_email, from_name, reply_to) efectivos para un tenant.

    El reply_to apunta a la direccion inbound automatica si existe (para que las
    respuestas del candidato entren al webhook); si no, al correo institucional
    del tenant (buzon humano)."""
    raw = tenant.settings_json or {}
    from_email = (raw.get("email_from") or settings.email_default_from or "").strip() or None
    from_name = (raw.get("email_from_name") or tenant.name or settings.email_default_from_name or "").strip() or None
    institutional = raw.get("institutional_info") or {}
    reply_to = tenant_inbound_address(tenant) or (institutional.get("email") or "").strip() or None
    return from_email, from_name, reply_to
