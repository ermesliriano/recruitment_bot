# app/routers/webhook.py
from __future__ import annotations

import traceback

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.channels.base import IncomingAttachment, IncomingMessageEvent, outgoing_from_legacy
from app.channels.whatsapp_twilio import TwilioWhatsAppGateway
from app.core.config import settings
from app.core.db import SessionLocal
from app.enums import Platform
from app.models.tenant import Tenant
from app.services.outbound_message_service import OutboundMessageService
from app.services.recruitment import RecruitmentService
from app.telegram_api import TelegramGateway, parse_telegram_update

router = APIRouter(prefix="/webhooks", tags=["Webhook"])


def _public_request_url(request: Request) -> str:
    if settings.public_base_url:
        query = f"?{request.url.query}" if request.url.query else ""
        return f"{settings.public_base_url.rstrip('/')}{request.url.path}{query}"
    return str(request.url)


def _telegram_to_event(payload: dict) -> IncomingMessageEvent:
    old_event = parse_telegram_update(payload)

    attachments: list[IncomingAttachment] = []
    if old_event.document:
        attachments.append(
            IncomingAttachment(
                attachment_id=old_event.document["file_id"],
                filename=old_event.document["file_name"],
                mime_type=old_event.document["mime_type"],
                size_bytes=old_event.document["file_size"],
                metadata={"file_unique_id": old_event.document.get("file_unique_id")},
            )
        )

    return IncomingMessageEvent(
        platform=Platform.TELEGRAM,
        event_id=str(old_event.update_id),
        chat_id=str(old_event.chat_id),
        user_id=str(old_event.user_id) if old_event.user_id is not None else str(old_event.chat_id),
        text=old_event.text,
        callback_data=old_event.callback_data,
        contact_phone=old_event.contact_phone,
        attachments=attachments,
        raw_payload=payload,
    )


def _load_tenant(db, tenant_slug: str | None) -> Tenant:
    if not tenant_slug:
        raise HTTPException(status_code=404, detail="Tenant no informado")

    tenant = db.execute(
        select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active.is_(True))
    ).scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant no encontrado: {tenant_slug}")

    return tenant


def _deliver_inbound_replies(tenant, event: IncomingMessageEvent, outgoing: list[dict]) -> None:
    """Entrega las respuestas del state machine por el mismo canal del entrante.

    Para respuestas a un inbound la ventana de 24h de WhatsApp esta abierta por
    definicion (el candidato acaba de escribir), por eso se envia directo por el
    gateway sin pasar por OutboundMessageService (que reserva la validacion de
    ventana para el flujo outbound iniciado por el reclutador).
    """
    if not outgoing:
        return

    if event.platform == Platform.TELEGRAM:
        gateway = TelegramGateway(tenant.telegram_bot_token)
        for msg in outgoing:
            gateway.send_message(int(event.chat_id), msg["text"], msg.get("reply_markup"))
        return

    gateway = TwilioWhatsAppGateway.from_tenant(tenant)
    to_address = event.from_address or event.chat_id
    for msg in outgoing:
        gateway.send_message(outgoing_from_legacy(Platform.WHATSAPP, to_address, msg))


@router.post("/telegram/{tenant_slug}")
async def telegram_webhook(
    tenant_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    db = SessionLocal()
    try:
        payload = await request.json()
        tenant = _load_tenant(db, tenant_slug)

        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != tenant.telegram_webhook_secret:
            return JSONResponse(status_code=403, content={"error": "Secret de Telegram inválido"})

        event = _telegram_to_event(payload)
        if not event.chat_id:
            return {"ok": True}

        service = RecruitmentService()
        outgoing = service.dispatch(db, tenant, event, background_tasks)
        db.commit()

        old_event = parse_telegram_update(payload)
        if old_event.callback_query_id:
            TelegramGateway(tenant.telegram_bot_token).answer_callback_query(old_event.callback_query_id)

        _deliver_inbound_replies(tenant, event, outgoing)

        return {"ok": True}

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "trace": traceback.format_exc()},
        )
    finally:
        db.close()


@router.post("/whatsapp/{tenant_slug}")
async def whatsapp_webhook(
    tenant_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    db = SessionLocal()
    try:
        tenant = _load_tenant(db, tenant_slug)
        raw_body = await request.body()
        form_params = TwilioWhatsAppGateway.form_params_from_body(raw_body)
        signature = request.headers.get("X-Twilio-Signature")
        gateway = TwilioWhatsAppGateway.from_tenant(tenant)

        if not gateway.validate_request(
            url=_public_request_url(request),
            params=form_params,
            signature=signature,
        ):
            return JSONResponse(status_code=403, content={"error": "Firma Twilio inválida"})

        event = gateway.parse_incoming(form_params)
        if not event.chat_id:
            return {"ok": True}

        service = RecruitmentService()
        outgoing = service.dispatch(db, tenant, event, background_tasks)
        db.commit()

        _deliver_inbound_replies(tenant, event, outgoing)

        return {"ok": True}

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "trace": traceback.format_exc()},
        )
    finally:
        db.close()


@router.post("/whatsapp")
async def whatsapp_webhook_default(
    request: Request,
    background_tasks: BackgroundTasks,
):
    if not settings.whatsapp_default_tenant_slug:
        return JSONResponse(status_code=404, content={"error": "No existe tenant por defecto para WhatsApp"})
    return await whatsapp_webhook(settings.whatsapp_default_tenant_slug, request, background_tasks)
