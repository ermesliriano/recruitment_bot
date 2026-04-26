import traceback
from sqlalchemy import insert
from app.models import SystemLog  # crea modelo
from app.core import SessionLocal

def log_event(
    db = SessionLocal(),
    *,
    level: str,
    source: str,
    event: str,
    message: str = None,
    payload: dict = None,
    tenant_id=None,
    application_id=None,
    conversation_session_id=None,
    exc: Exception = None,
):
    try:
        log = SystemLog(
            tenant_id=tenant_id,
            level=level,
            source=source,
            event=event,
            message=message,
            payload=payload,
            traceback=traceback.format_exc() if exc else None,
            application_id=application_id,
            conversation_session_id=conversation_session_id,
        )
        db.add(log)
        db.flush()
    except Exception:
        # Nunca romper el flujo por logging
        pass