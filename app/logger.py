import traceback
from app.models import SystemLog
from app.core import SessionLocal

def log_event(
    db=None,  # mantenido por compatibilidad, ya no se usa para escribir
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
    """Escribe un log en su propia sesión y hace commit inmediato,
    de modo que el registro sobrevive aunque la transacción llamante
    haga rollback."""
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