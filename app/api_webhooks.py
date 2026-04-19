# app/api_webhooks.py
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException
from sqlalchemy import case, select

from app.core import get_db, settings, Classification
from app.models import Application, Candidate, Tenant, Vacancy
from app.scoring import RecruitmentService
from app.telegram_api import TelegramGateway, parse_telegram_update

import traceback
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])
admin_router = APIRouter(prefix="/admin/v1", tags=["admin"])
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])

def require_admin_token(x_admin_token: str | None = Header(None, alias="X-Admin-Token")):
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="admin token inválido")

@webhook_router.post("/telegram/{tenant_slug}")
async def telegram_webhook(tenant_slug: str, request: Request):
    from app.core import SessionLocal
    import traceback
    from fastapi.responses import JSONResponse

    db = SessionLocal()
    tenant = None

    try:
        payload = await request.json()

        # 🔹 1. Obtener tenant PRIMERO
        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()

        if not tenant:
            return JSONResponse(
                status_code=404,
                content={"error": f"Tenant not found: {tenant_slug}"}
            )

        # 🔹 2. Validar secret
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

        if secret != tenant.telegram_webhook_secret:
            return JSONResponse(
                status_code=403,
                content={"error": "secret telegram inválido"}
            )

        # 🔹 3. Procesar payload
        message = payload.get("message") or payload.get("callback_query", {}).get("message")
        if not message:
            return {"ok": True}

        text = message.get("text", "")
        chat_id = message.get("chat", {}).get("id")

        if not chat_id:
            return {"ok": True}

        # 🔹 4. Aquí irá tu state machine    
        event = parse_telegram_update(payload)
        service = RecruitmentService()
        tg = TelegramGateway(tenant.telegram_bot_token)

        outgoing = service.dispatch(db, tenant, event, background_tasks)
        db.commit()

        if event.callback_query_id:
            tg.answer_callback_query(event.callback_query_id)

        for msg in outgoing:
            tg.send_message(event.chat_id, msg["text"], msg.get("reply_markup"))

        return {"ok": True}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "trace": traceback.format_exc()
            }
        )

    finally:
        db.close()

@internal_router.post("/tenants/{tenant_id}/telegram/set-webhook", dependencies=[Depends(require_admin_token)])
def set_telegram_webhook(tenant_id: str, public_base_url: str, db=Depends(get_db)):
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one()
    tg = TelegramGateway(tenant.telegram_bot_token)
    return tg.set_webhook(
        url=f"{public_base_url}/webhooks/telegram/{tenant.slug}",
        secret_token=tenant.telegram_webhook_secret,
    )

@admin_router.get("/tenants/{tenant_id}/vacancies/{vacancy_id}/ranking", dependencies=[Depends(require_admin_token)])
def vacancy_ranking(tenant_id: str, vacancy_id: str, db=Depends(get_db)):
    stmt = (
        select(
            Candidate.full_name.label("nombre"),
            Candidate.phone_e164.label("telefono"),
            Vacancy.title.label("vacante"),
            Application.score_rules,
            Application.score_cv,
            Application.score_total,
            Application.classification.label("estado"),
        )
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(Vacancy, Vacancy.id == Application.vacancy_id)
        .where(Application.tenant_id == tenant_id, Application.vacancy_id == vacancy_id)
        .order_by(
            case(
                (Application.classification == Classification.SHORTLIST, 4),
                (Application.classification == Classification.INTERVIEW, 3),
                (Application.classification == Classification.REVIEW, 2),
                else_=1,
            ).desc(),
            Application.score_total.desc().nullslast(),
            Application.created_at.asc(),
        )
    )
    rows = db.execute(stmt).all()
    return {"items": [dict(r._mapping) for r in rows]}

@admin_router.get("/tenants/{tenant_id}/applications/{application_id}", dependencies=[Depends(require_admin_token)])
def application_detail(tenant_id: str, application_id: str, db=Depends(get_db)):
    app = db.execute(
        select(Application).where(Application.id == application_id, Application.tenant_id == tenant_id)
    ).scalar_one()
    return {
        "application_id": str(app.id),
        "status": app.status.value,
        "classification": app.classification.value if app.classification else None,
        "score_rules": float(app.score_rules or 0),
        "score_cv": float(app.score_cv or 0) if app.score_cv is not None else None,
        "score_total": float(app.score_total or 0) if app.score_total is not None else None,
        "is_disqualified": app.is_disqualified,
        "disqualification_reason": app.disqualification_reason,
    }