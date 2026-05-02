# app/routers/webhook.py
import traceback

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.tenant import Tenant
from app.services.recruitment import RecruitmentService
from app.telegram_api import TelegramGateway, parse_telegram_update

router = APIRouter(prefix="/webhooks", tags=["Webhook"])


@router.post("/telegram/{tenant_slug}")
async def telegram_webhook(
    tenant_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    db = SessionLocal()
    try:
        payload = await request.json()

        tenant = db.execute(
            select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active.is_(True))
        ).scalar_one_or_none()

        if not tenant:
            return JSONResponse(status_code=404, content={"error": f"Tenant no encontrado: {tenant_slug}"})

        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != tenant.telegram_webhook_secret:
            return JSONResponse(status_code=403, content={"error": "Secret de Telegram inválido"})

        event = parse_telegram_update(payload)
        if not event.chat_id:
            return {"ok": True}

        service = RecruitmentService()
        tg = TelegramGateway(tenant.telegram_bot_token)

        outgoing = service.dispatch(db, tenant, event, background_tasks)
        db.commit()

        if event.callback_query_id:
            tg.answer_callback_query(event.callback_query_id)

        for msg in outgoing:
            tg.send_message(event.chat_id, msg["text"], msg.get("reply_markup"))

        return {"ok": True}

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "trace": traceback.format_exc()},
        )
    finally:
        db.close()
