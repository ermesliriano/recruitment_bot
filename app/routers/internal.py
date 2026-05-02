# app/routers/internal.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_admin_token
from app.models.tenant import Tenant
from app.telegram_api import TelegramGateway

router = APIRouter(prefix="/internal/v1", tags=["Internal"], dependencies=[Depends(require_admin_token)])


@router.post("/tenants/{tenant_id}/telegram/set-webhook")
def set_telegram_webhook(tenant_id: str, public_base_url: str, db: Session = Depends(get_db)):
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one()
    tg = TelegramGateway(tenant.telegram_bot_token)
    return tg.set_webhook(
        url=f"{public_base_url}/webhooks/telegram/{tenant.slug}",
        secret_token=tenant.telegram_webhook_secret,
    )
