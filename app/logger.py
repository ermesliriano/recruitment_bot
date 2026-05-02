# app/logger.py
import traceback

from app.core.db import SessionLocal
from app.models.session import SystemLog


def log_event(
    db=None,
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
) -> None:
    """Escribe un log en su propia sesión independiente para que sobreviva
    a un rollback de la transacción llamante."""
    log_db = SessionLocal()
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
        log_db.add(log)
        log_db.commit()
    except Exception:
        try:
            log_db.rollback()
        except Exception:
            pass
    finally:
        log_db.close()
