# app/routers/webhook.py
from __future__ import annotations

import base64
import hashlib
import json
import re
import traceback

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.channels.base import IncomingAttachment, IncomingMessageEvent, outgoing_from_legacy
from app.channels.email_sendgrid import SendGridEmailGateway, tenant_email_sender, tenant_inbound_address
from app.channels.whatsapp_twilio import TwilioWhatsAppGateway
from app.core.config import settings
from app.core.db import SessionLocal
from app.logger import log_event
from app.enums import ChatState, Platform
from app.models.session import ConversationSession
from app.models.tenant import Tenant
from app.services.outbound_message_service import OutboundMessageService
from app.services.conversation_log import record_outgoing_batch
from app.services.phone_extraction import extract_phone_from_text
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
    tenant = None
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
        record_outgoing_batch(db, tenant, event, outgoing)
        db.commit()

        old_event = parse_telegram_update(payload)
        if old_event.callback_query_id:
            TelegramGateway(tenant.telegram_bot_token).answer_callback_query(old_event.callback_query_id)

        _deliver_inbound_replies(tenant, event, outgoing)

        return {"ok": True}

    except Exception as exc:
        log_event(
            level="ERROR", source="telegram_webhook", event="TELEGRAM_WEBHOOK_EXCEPTION",
            tenant_id=tenant.id if tenant else None,
            message=str(exc), exc=exc,
        )
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
    tenant = None
    try:
        tenant = _load_tenant(db, tenant_slug)
        raw_body = await request.body()
        form_params = TwilioWhatsAppGateway.form_params_from_body(raw_body)
        signature = request.headers.get("X-Twilio-Signature")
        public_url = _public_request_url(request)

        log_event(
            level="INFO", source="whatsapp_webhook", event="WHATSAPP_INBOUND",
            tenant_id=tenant.id,
            payload={
                "from": form_params.get("From"),
                "to": form_params.get("To"),
                "body": form_params.get("Body"),
                "num_media": form_params.get("NumMedia"),
                "message_sid": form_params.get("MessageSid"),
                "has_signature": bool(signature),
                "validation_url": public_url,
            },
        )

        gateway = TwilioWhatsAppGateway.from_tenant(tenant)

        if not gateway.validate_request(
            url=public_url,
            params=form_params,
            signature=signature,
        ):
            log_event(
                level="WARNING", source="whatsapp_webhook", event="WHATSAPP_SIGNATURE_INVALID",
                tenant_id=tenant.id,
                message="La firma de Twilio no valido. Revisa PUBLIC_BASE_URL y que TWILIO_ACCOUNT_SID/AUTH_TOKEN sean de esta cuenta.",
                payload={"validation_url": public_url, "has_signature": bool(signature)},
            )
            return JSONResponse(status_code=403, content={"error": "Firma Twilio inválida"})

        event = gateway.parse_incoming(form_params)
        if not event.chat_id:
            log_event(
                level="WARNING", source="whatsapp_webhook", event="WHATSAPP_NO_CHAT_ID",
                tenant_id=tenant.id, payload={"from": form_params.get("From")},
            )
            return {"ok": True}

        service = RecruitmentService()
        outgoing = service.dispatch(db, tenant, event, background_tasks)
        record_outgoing_batch(db, tenant, event, outgoing)
        db.commit()

        log_event(
            level="INFO", source="whatsapp_webhook", event="WHATSAPP_DISPATCH_OK",
            tenant_id=tenant.id,
            payload={"reply_count": len(outgoing), "to": event.from_address or event.chat_id},
        )

        _deliver_inbound_replies(tenant, event, outgoing)

        log_event(
            level="INFO", source="whatsapp_webhook", event="WHATSAPP_REPLY_SENT",
            tenant_id=tenant.id, payload={"reply_count": len(outgoing)},
        )

        return {"ok": True}

    except Exception as exc:
        log_event(
            level="ERROR", source="whatsapp_webhook", event="WHATSAPP_WEBHOOK_EXCEPTION",
            tenant_id=tenant.id if tenant else None,
            message=str(exc), exc=exc,
        )
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


# ── Canal EMAIL (SendGrid Inbound Parse) ─────────────────────────────

# Marcadores tipicos donde empieza el historial citado en una respuesta de email.
_EMAIL_QUOTE_MARKERS = (
    re.compile(r"^\s*>"),
    re.compile(r"^El .{5,80} escribió:\s*$", re.IGNORECASE),
    re.compile(r"^On .{5,120} wrote:\s*$", re.IGNORECASE),
    re.compile(r"^-{3,}\s*(Original Message|Mensaje original)", re.IGNORECASE),
    re.compile(r"^(De|From):\s.+@", re.IGNORECASE),
    re.compile(r"^_{5,}\s*$"),
)

# Tamaño maximo del CV que se conserva temporalmente (base64 en state_payload)
# cuando llega adjunto antes de que exista la candidatura.
_STASH_MAX_BYTES = 6 * 1024 * 1024

_CV_MIME_HINTS = ("pdf", "msword", "officedocument", "image/")


def _clean_email_reply(text: str | None) -> str:
    """Se queda con el contenido nuevo del correo, cortando el historial citado
    y la firma. Suficientemente conservador: ante duda, conserva la linea."""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    for line in lines:
        if line.strip() == "--":  # separador clasico de firma
            break
        if any(marker.search(line) for marker in _EMAIL_QUOTE_MARKERS):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _email_event_from_form(form, tenant) -> IncomingMessageEvent:
    """Construye el IncomingMessageEvent desde el multipart de Inbound Parse."""
    from_header = str(form.get("from") or "")
    match = re.search(r"<([^>]+)>", from_header)
    from_email = (match.group(1) if match else from_header).strip().lower()
    sender_name = from_header.split("<")[0].strip().strip('"') if "<" in from_header else None

    to_address = None
    envelope_raw = form.get("envelope")
    if envelope_raw:
        try:
            envelope = json.loads(envelope_raw)
            to_list = envelope.get("to") or []
            to_address = (to_list[0] if to_list else None)
        except (ValueError, TypeError):
            to_address = None
    if not to_address:
        to_address = str(form.get("to") or "") or None

    subject = str(form.get("subject") or "")
    text = _clean_email_reply(str(form.get("text") or ""))

    attachments: list[IncomingAttachment] = []
    for key, value in form.multi_items():
        if not hasattr(value, "filename") or not getattr(value, "filename", None):
            continue
        content = value.file.read()
        if not content:
            continue
        attachments.append(
            IncomingAttachment(
                attachment_id=key,
                filename=value.filename,
                mime_type=value.content_type or "application/octet-stream",
                size_bytes=len(content),
                content=content,
            )
        )

    # Prioriza adjuntos con pinta de CV (pdf/doc/imagen) frente a firmas .png minúsculas.
    attachments.sort(
        key=lambda a: (
            not any(h in (a.mime_type or "") for h in _CV_MIME_HINTS),
            -(a.size_bytes or 0),
        )
    )

    event_id = hashlib.sha256(
        f"{from_email}|{subject}|{text}|{len(attachments)}".encode()
    ).hexdigest()[:32]

    return IncomingMessageEvent(
        platform=Platform.EMAIL,
        event_id=f"email:{event_id}",
        chat_id=from_email,
        user_id=from_email,
        text=text or None,
        sender_name=sender_name or None,
        from_address=from_email,
        to_address=to_address,
        attachments=attachments[:1],
        raw_payload={"subject": subject},
    )


def _get_email_session(db, tenant, chat_id: str) -> ConversationSession | None:
    return db.execute(
        select(ConversationSession).where(
            ConversationSession.tenant_id == tenant.id,
            ConversationSession.platform == Platform.EMAIL,
            ConversationSession.platform_chat_id == chat_id,
            ConversationSession.is_active.is_(True),
        )
    ).scalar_one_or_none()


def _resolve_email_identity(db, tenant, event: IncomingMessageEvent) -> None:
    """Inyecta contact_phone en el evento para que WELCOME pueda crear/vincular
    al candidato: por candidato existente con ese email, o por telefono escrito
    en el cuerpo del correo."""
    from app.models.candidate import Candidate

    candidate = db.execute(
        select(Candidate).where(
            Candidate.tenant_id == tenant.id,
            Candidate.email == event.from_address,
        )
    ).scalar_one_or_none()
    if candidate:
        event.contact_phone = candidate.phone_e164
        return

    phone_result = extract_phone_from_text(event.text or "")
    if phone_result.status not in ("phone_not_found", "ambiguous_phone") and phone_result.selected_phone:
        event.contact_phone = phone_result.selected_phone


def _stash_or_inject_cv(db, tenant, service, event, background_tasks) -> list[dict]:
    """Gestiona el CV adjunto del PRIMER correo: si aun no existe candidatura, lo
    conserva (base64) en la sesion; cuando el flujo ya tiene candidatura, lo
    inyecta como adjunto proactivo. Devuelve mensajes extra a enviar."""
    session = _get_email_session(db, tenant, event.chat_id)
    if session is None:
        return []

    payload = dict(session.state_payload or {})

    # 1) Conservar el adjunto recién llegado si el flujo aun no puede procesarlo.
    if event.attachments and not session.application_id and not payload.get("cv_received"):
        att = event.attachments[0]
        if att.content and len(att.content) <= _STASH_MAX_BYTES:
            payload["stashed_cv"] = {
                "filename": att.filename,
                "mime_type": att.mime_type,
                "content_b64": base64.b64encode(att.content).decode(),
            }
            session.state_payload = payload
            db.flush()
        return []

    # 2) Inyectar el CV conservado cuando la candidatura ya existe.
    stashed = payload.get("stashed_cv")
    if (
        stashed
        and session.application_id
        and not payload.get("cv_received")
        and not payload.get("pending_cv_confirm")
        and session.current_state in {ChatState.CAPTURE_NAME, ChatState.ASK_TENANT_QUESTIONS}
    ):
        synthetic = IncomingMessageEvent(
            platform=Platform.EMAIL,
            event_id=f"{event.event_id}:stashed-cv",
            chat_id=event.chat_id,
            user_id=event.user_id,
            text=None,
            from_address=event.from_address,
            to_address=event.to_address,
            attachments=[
                IncomingAttachment(
                    attachment_id="stashed-cv",
                    filename=stashed.get("filename") or "cv.pdf",
                    mime_type=stashed.get("mime_type") or "application/pdf",
                    content=base64.b64decode(stashed["content_b64"]),
                )
            ],
        )
        payload.pop("stashed_cv", None)
        session.state_payload = payload
        db.flush()
        return service.dispatch(db, tenant, synthetic, background_tasks)

    return []


def _deliver_email_reply(tenant, event: IncomingMessageEvent, outgoing: list[dict]) -> None:
    """Agrupa las respuestas del state machine en UN solo correo y lo envia."""
    texts = [m.get("text") for m in outgoing if m.get("text")]
    if not texts:
        return

    body = "\n\n".join(texts)
    subject = event.raw_payload.get("subject") or ""
    subject = f"Re: {subject}" if subject and not subject.lower().startswith("re:") else (subject or f"Tu candidatura - {tenant.name}")

    from_email, from_name, _ = tenant_email_sender(tenant)
    # Las respuestas deben volver SIEMPRE al canal inbound automatico.
    reply_to = tenant_inbound_address(tenant) or event.to_address

    SendGridEmailGateway().send_email(
        to_email=event.from_address,
        subject=subject,
        text_body=body,
        from_email=from_email,
        from_name=from_name,
        reply_to=reply_to,
    )


@router.post("/email/{tenant_slug}")
async def email_webhook(
    tenant_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    # Inbound Parse no firma sus webhooks: se protege con un token en la URL.
    token = request.query_params.get("token")
    if not settings.sendgrid_inbound_token or token != settings.sendgrid_inbound_token:
        return JSONResponse(status_code=403, content={"error": "Token de inbound inválido"})

    db = SessionLocal()
    tenant = None
    try:
        tenant = _load_tenant(db, tenant_slug)
        form = await request.form()
        event = _email_event_from_form(form, tenant)

        log_event(
            level="INFO", source="email_webhook", event="EMAIL_INBOUND",
            tenant_id=tenant.id,
            payload={
                "from": event.from_address,
                "to": event.to_address,
                "subject": event.raw_payload.get("subject"),
                "has_text": bool(event.text),
                "attachments": len(event.attachments),
            },
        )

        if not event.from_address:
            return {"ok": True}

        # Identidad: candidato existente por email, o telefono escrito en el cuerpo.
        _resolve_email_identity(db, tenant, event)

        service = RecruitmentService()
        outgoing = service.dispatch(db, tenant, event, background_tasks)

        # CV del primer correo: conservarlo o inyectarlo cuando ya hay candidatura.
        outgoing += _stash_or_inject_cv(db, tenant, service, event, background_tasks)

        record_outgoing_batch(db, tenant, event, outgoing)
        db.commit()

        _deliver_email_reply(tenant, event, outgoing)

        log_event(
            level="INFO", source="email_webhook", event="EMAIL_REPLY_SENT",
            tenant_id=tenant.id, payload={"reply_count": len(outgoing)},
        )
        return {"ok": True}

    except Exception as exc:
        log_event(
            level="ERROR", source="email_webhook", event="EMAIL_WEBHOOK_EXCEPTION",
            tenant_id=tenant.id if tenant else None,
            message=str(exc), exc=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "trace": traceback.format_exc()},
        )
    finally:
        db.close()


@router.post("/email")
async def email_webhook_default(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Endpoint unico para Inbound Parse: resuelve el tenant por la direccion de
    destino (local part = slug del tenant), con fallback al tenant por defecto."""
    token = request.query_params.get("token")
    if not settings.sendgrid_inbound_token or token != settings.sendgrid_inbound_token:
        return JSONResponse(status_code=403, content={"error": "Token de inbound inválido"})

    form = await request.form()
    slug = None
    envelope_raw = form.get("envelope")
    if envelope_raw:
        try:
            envelope = json.loads(envelope_raw)
            to_list = envelope.get("to") or []
            if to_list:
                local = str(to_list[0]).split("@", 1)[0]
                # Soporta plus-addressing: candidaturas+<slug>@dominio
                slug = local.split("+", 1)[1] if "+" in local else local
        except (ValueError, TypeError):
            slug = None

    slug = slug or settings.email_default_tenant_slug
    if not slug:
        return JSONResponse(status_code=404, content={"error": "No se pudo resolver el tenant del correo"})

    # Reutiliza el endpoint por slug (el form ya fue consumido; Starlette lo cachea).
    return await email_webhook(slug, request, background_tasks)
