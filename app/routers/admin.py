# app/routers/admin.py
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, aliased
from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db
from app.core.security import require_admin_token
from app.enums import AiEvalStatus, Classification
from app.models.application import Application, Answer
from app.models.candidate import Candidate
from app.models.cv import CvDocument, AiEvaluation
from app.models.outbound_message import OutboundMessage
from app.models.question import Question, TenantQuestion, VacancyQuestion
from app.models.session import ConversationSession
from app.models.tenant import Tenant
from app.models.vacancy import Vacancy
from app.schemas.application import ApplicationOut
from app.schemas.ranking import RankingRow
from app.services.score_backfill import backfill_scores, diagnose_application
from app.services.llm_conversation import (
    DEFAULT_CONTRACT,
    DEFAULT_GUIDE_PROMPT,
    DEFAULT_PERSONALITY_PROMPT,
    INSTITUTIONAL_INFO_FIELDS,
    INSTITUTIONAL_INFO_TEMPLATE,
    get_flow_settings,
)

router = APIRouter(prefix="/v1", tags=["Admin"], dependencies=[Depends(require_admin_token)])


# ── Flujo de conversacion por tenant (bot clasico vs flujo LLM) ───────────
# Reservado a los maximos administradores (portadores del ADMIN_TOKEN).

class ConversationFlowIn(BaseModel):
    conversation_mode: Literal["classic", "llm"]
    llm_flow_prompt: str | None = None
    llm_personality_prompt: str | None = None
    llm_flow_contract: dict[str, Any] | None = None
    llm_rewrite_messages: bool = True


class CompanyInfoIn(BaseModel):
    institutional_info: dict[str, Any] | None = None
    email_from: str | None = None
    email_from_name: str | None = None


def _flow_response(tenant) -> dict[str, Any]:
    """Configuracion efectiva + defaults, para que el frontend pueda mostrar y
    editar los textos por defecto aunque el tenant no los haya personalizado."""
    flow = get_flow_settings(tenant)
    flow["defaults"] = {
        "llm_flow_prompt": DEFAULT_GUIDE_PROMPT,
        "llm_personality_prompt": DEFAULT_PERSONALITY_PROMPT,
        "llm_flow_contract": DEFAULT_CONTRACT,
        "institutional_info_template": INSTITUTIONAL_INFO_TEMPLATE,
        "institutional_info_fields": list(INSTITUTIONAL_INFO_FIELDS),
    }
    return flow


@router.get("/tenants/{tenant_id}/conversation-flow")
def get_conversation_flow(tenant_id: str, db: Session = Depends(get_db)):
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    return _flow_response(tenant)


@router.put("/tenants/{tenant_id}/conversation-flow")
def update_conversation_flow(
    tenant_id: str,
    payload: ConversationFlowIn,
    db: Session = Depends(get_db),
):
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")

    prompt = (payload.llm_flow_prompt or "").strip() or None
    if prompt and "{contract}" not in prompt:
        raise HTTPException(
            status_code=422,
            detail="El prompt del guía debe incluir el marcador {contract} "
            "donde se insertara el contrato JSON de salida.",
        )
    # Si el texto coincide con el default, se guarda None: asi el tenant sigue
    # heredando futuras mejoras del prompt por defecto.
    if prompt == DEFAULT_GUIDE_PROMPT.strip():
        prompt = None

    personality = (payload.llm_personality_prompt or "").strip() or None
    if personality == DEFAULT_PERSONALITY_PROMPT.strip():
        personality = None

    # Nota: institutional_info NO se toca desde aqui; se gestiona en su propio
    # endpoint (company-info) para que guardar prompts no pise los datos de la
    # empresa introducidos por el cliente.
    tenant.settings_json = {
        **(tenant.settings_json or {}),
        "conversation_mode": payload.conversation_mode,
        "llm_flow_prompt": prompt,
        "llm_personality_prompt": personality,
        "llm_flow_contract": payload.llm_flow_contract,
        "llm_rewrite_messages": payload.llm_rewrite_messages,
    }
    db.commit()
    return _flow_response(tenant)


@router.get("/tenants/{tenant_id}/company-info")
def get_company_info(tenant_id: str, db: Session = Depends(get_db)):
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return {
        "institutional_info": (tenant.settings_json or {}).get("institutional_info") or {},
        "email_from": (tenant.settings_json or {}).get("email_from") or None,
        "email_from_name": (tenant.settings_json or {}).get("email_from_name") or None,
        "fields": list(INSTITUTIONAL_INFO_FIELDS),
    }


@router.put("/tenants/{tenant_id}/company-info")
def update_company_info(
    tenant_id: str,
    payload: CompanyInfoIn,
    db: Session = Depends(get_db),
):
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    institutional = None
    if payload.institutional_info:
        institutional = {
            key: str(payload.institutional_info[key]).strip()
            for key in INSTITUTIONAL_INFO_FIELDS
            if payload.institutional_info.get(key)
            and str(payload.institutional_info[key]).strip()
        } or None

    tenant.settings_json = {
        **(tenant.settings_json or {}),
        "institutional_info": institutional,
        "email_from": (payload.email_from or "").strip() or None,
        "email_from_name": (payload.email_from_name or "").strip() or None,
    }
    db.commit()
    return {
        "institutional_info": institutional or {},
        "email_from": (tenant.settings_json or {}).get("email_from"),
        "email_from_name": (tenant.settings_json or {}).get("email_from_name"),
        "fields": list(INSTITUTIONAL_INFO_FIELDS),
    }


@router.post("/maintenance/backfill-scores")
def maintenance_backfill_scores(
    dry_run: bool = True,
    tenant_id: str | None = None,
    vacancy_id: str | None = None,
    application_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Recalcula score_total de candidaturas atascadas (sin volver a llamar al LLM).

    Por seguridad, dry_run=true por defecto: no escribe, solo informa. Para
    aplicar de verdad, pasar ?dry_run=false. Se puede acotar por tenant_id,
    vacancy_id o application_id.
    """
    return backfill_scores(
        db,
        dry_run=dry_run,
        tenant_id=tenant_id,
        vacancy_id=vacancy_id,
        application_id=application_id,
    )


@router.get("/maintenance/score-diagnosis/{application_id}")
def maintenance_score_diagnosis(application_id: str, db: Session = Depends(get_db)):
    """Explica por que una candidatura no se puede puntuar (CV, evaluacion IA y
    preguntas obligatorias activas sin responder)."""
    return diagnose_application(db, application_id)


# Etiqueta legible del punto del flujo en que se quedó una candidatura incompleta.
_CHAT_STAGE_LABELS = {
    "WELCOME": "Inicio de la conversación",
    "SELECT_VACANCY": "Eligiendo vacante",
    "CAPTURE_NAME": "Indicando su nombre",
    "ASK_TENANT_QUESTIONS": "Preguntas de screening",
    "VACANCY_QA_MODE": "Preguntas de la vacante",
    "ASK_VACANCY_QUESTIONS": "Preguntas de la vacante",
    "REQUEST_CV": "Esperando el envío del CV",
    "WAITING_CANDIDATE_REPLY": "Esperando primer mensaje del candidato",
    "SCORING": "Procesando / pendiente de evaluación",
    "CONFIRM_AND_CLOSE": "Proceso completado",
    "ESCALATE_HUMAN": "Escalado a RRHH",
}

_APP_STATUS_STAGE_LABELS = {
    "draft": "Sin iniciar",
    "in_progress": "En progreso",
    "pending_ai": "Procesando CV",
    "scoring": "Procesando / pendiente de evaluación",
    "waiting_candidate_reply": "Esperando primer mensaje del candidato",
    "blocked_no_opt_in": "Bloqueado (sin opt-in)",
    "needs_human": "Escalado a RRHH",
}


def _incomplete_stage_label(session_state, app_status) -> str:
    """Punto del flujo en que se quedó una candidatura, a partir del estado de la
    conversación; si no hay sesión, cae al estado de la candidatura."""
    state = getattr(session_state, "value", session_state)
    if state in _CHAT_STAGE_LABELS:
        return _CHAT_STAGE_LABELS[state]
    status = getattr(app_status, "value", app_status)
    if status in _APP_STATUS_STAGE_LABELS:
        return _APP_STATUS_STAGE_LABELS[status]
    return "Desconocido"


@router.get("/tenants/{tenant_id}/vacancies/{vacancy_id}/ranking")
def vacancy_ranking(tenant_id: str, vacancy_id: str, db: Session = Depends(get_db)):
    latest_outbound_sq = (
        select(
            OutboundMessage.application_id.label("application_id"),
            func.max(OutboundMessage.created_at).label("created_at"),
        )
        .group_by(OutboundMessage.application_id)
        .subquery()
    )
    last_outbound = aliased(OutboundMessage)

    # Estado actual de la conversacion, para saber en que punto del flujo se
    # quedaron las candidaturas incompletas.
    session_state_sq = (
        select(ConversationSession.current_state)
        .where(
            ConversationSession.application_id == Application.id,
            ConversationSession.is_active.is_(True),
        )
        .order_by(ConversationSession.updated_at.desc())
        .limit(1)
        .correlate(Application)
        .scalar_subquery()
    )

    session_platform_sq = (
        select(ConversationSession.platform)
        .where(
            ConversationSession.application_id == Application.id,
            ConversationSession.is_active.is_(True),
        )
        .order_by(ConversationSession.updated_at.desc())
        .limit(1)
        .correlate(Application)
        .scalar_subquery()
    )

    base_stmt = (
        select(
            Application.id.label("application_id"),
            Candidate.full_name.label("nombre"),
            Candidate.phone_e164.label("telefono"),
            Vacancy.title.label("vacante"),
            Application.origin.label("origin"),
            Application.preferred_platform.label("channel"),
            last_outbound.status.label("outbound_status"),
            Application.score_rules,
            Application.score_cv,
            Application.score_total,
            Application.classification.label("estado"),
            Application.status.label("app_status"),
            session_state_sq.label("session_state"),
            session_platform_sq.label("session_platform"),
        )
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(Vacancy, Vacancy.id == Application.vacancy_id)
        .outerjoin(latest_outbound_sq, latest_outbound_sq.c.application_id == Application.id)
        .outerjoin(
            last_outbound,
            and_(
                last_outbound.application_id == Application.id,
                last_outbound.created_at == latest_outbound_sq.c.created_at,
            ),
        )
        .where(Application.tenant_id == tenant_id, Application.vacancy_id == vacancy_id)
    )

    def _to_row(r) -> dict:
        return RankingRow(
            application_id=str(r.application_id),
            nombre=r.nombre,
            telefono=r.telefono,
            vacante=r.vacante,
            origin=r.origin.value if r.origin else None,
            channel=(
                r.channel.value
                if r.channel
                else (r.session_platform.value if r.session_platform else None)
            ),
            outbound_status=r.outbound_status,
            score_rules=float(r.score_rules or 0),
            score_cv=float(r.score_cv) if r.score_cv is not None else None,
            score_total=float(r.score_total) if r.score_total is not None else None,
            estado=r.estado.value if r.estado else None,
            stage=_incomplete_stage_label(r.session_state, r.app_status),
        ).model_dump()

    # Candidaturas completadas (ya evaluadas, con score_total): el ranking real.
    completed = db.execute(
        base_stmt.where(Application.score_total.is_not(None)).order_by(
            case(
                (Application.classification == Classification.SHORTLIST, 4),
                (Application.classification == Classification.INTERVIEW, 3),
                (Application.classification == Classification.REVIEW, 2),
                else_=1,
            ).desc(),
            Application.score_total.desc().nullslast(),
            Application.created_at.asc(),
        )
    ).all()

    # Candidaturas incompletas (sin score_total): el candidato no termino el flujo.
    incomplete = db.execute(
        base_stmt.where(Application.score_total.is_(None)).order_by(
            Application.created_at.desc(),
        )
    ).all()

    return {
        "vacancy_id": vacancy_id,
        "total": len(completed),
        "items": [_to_row(r) for r in completed],
        "incomplete_total": len(incomplete),
        "incomplete": [_to_row(r) for r in incomplete],
    }


@router.get("/tenants/{tenant_id}/applications/{application_id}", response_model=ApplicationOut)
def application_detail(tenant_id: str, application_id: str, db: Session = Depends(get_db)):
    application = db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == tenant_id,
        )
    ).scalar_one()

    tenant = db.execute(
        select(Tenant).where(Tenant.id == application.tenant_id)
    ).scalar_one_or_none()

    vacancy = db.execute(
        select(Vacancy).where(Vacancy.id == application.vacancy_id)
    ).scalar_one_or_none()

    candidate = db.execute(
        select(Candidate).where(Candidate.id == application.candidate_id)
    ).scalar_one_or_none()

    # Canal: si una candidatura inbound no guardo preferred_platform, lo derivamos
    # de la plataforma de la conversacion (telegram / whatsapp).
    preferred_platform = application.preferred_platform
    if preferred_platform is None:
        preferred_platform = db.execute(
            select(ConversationSession.platform)
            .where(
                ConversationSession.application_id == application.id,
                ConversationSession.is_active.is_(True),
            )
            .order_by(ConversationSession.updated_at.desc())
        ).scalars().first()

    latest_cv = db.execute(
        select(CvDocument)
        .where(CvDocument.application_id == application.id)
        .order_by(CvDocument.version.desc())
    ).scalars().first()

    latest_outbound = db.execute(
        select(OutboundMessage)
        .where(OutboundMessage.application_id == application.id)
        .order_by(OutboundMessage.created_at.desc())
    ).scalars().first()

    # Última evaluación correcta del LLM: de ahí salen recommendation y el análisis cualitativo.
    latest_eval = db.execute(
        select(AiEvaluation)
        .where(
            AiEvaluation.application_id == application.id,
            AiEvaluation.status == AiEvalStatus.SUCCESS,
        )
        .order_by(AiEvaluation.created_at.desc())
    ).scalars().first()

    analysis = None
    if latest_eval is not None:
        parsed = latest_eval.parsed_json or {}
        analysis = {
            "human_readable_summary": parsed.get("human_readable_summary"),
            "qualitative_assessment": parsed.get("qualitative_assessment"),
            "score_rationale": parsed.get("score_rationale"),
            "recommended_next_action": parsed.get("recommended_next_action"),
            "skills": parsed.get("skills") or (latest_eval.skills or []),
            "experience_summary": parsed.get("experience_summary")
            or (latest_eval.experience_summary or []),
            "red_flags": parsed.get("red_flags") or (latest_eval.red_flags or []),
            "missing_evidence": parsed.get("missing_evidence") or [],
            "fit_gaps": parsed.get("fit_gaps") or [],
            "follow_up_questions": parsed.get("follow_up_questions") or [],
        }

    # ── Respuestas del candidato, resueltas a texto legible ──────────────────
    vq = aliased(VacancyQuestion)
    vq_q = aliased(Question)
    tq = aliased(TenantQuestion)
    tq_q = aliased(Question)

    answer_rows = db.execute(
        select(
            Answer.field_key,
            Answer.answer_text,
            Answer.answer_number,
            Answer.answer_boolean,
            vq.question_order.label("vq_order"),
            vq.prompt_override.label("vq_prompt_override"),
            vq_q.prompt_text.label("vq_prompt_text"),
            tq.question_order.label("tq_order"),
            tq.prompt_override.label("tq_prompt_override"),
            tq_q.prompt_text.label("tq_prompt_text"),
        )
        .outerjoin(vq, vq.id == Answer.vacancy_question_id)
        .outerjoin(vq_q, vq_q.id == vq.question_id)
        .outerjoin(tq, tq.id == Answer.tenant_question_id)
        .outerjoin(tq_q, tq_q.id == tq.question_id)
        .where(Answer.application_id == application.id)
        .order_by(Answer.created_at.asc())
    ).all()

    def _human_answer(text, number, boolean) -> str | None:
        if text not in (None, ""):
            return text
        if boolean is not None:
            return "Sí" if boolean else "No"
        if number is not None:
            return str(number)
        return None

    answers: list[dict] = []
    for r in answer_rows:
        if r.vq_prompt_text is not None or r.vq_prompt_override is not None:
            prompt = r.vq_prompt_override or r.vq_prompt_text or r.field_key
            order = r.vq_order
            scope = "vacancy"
        elif r.tq_prompt_text is not None or r.tq_prompt_override is not None:
            prompt = r.tq_prompt_override or r.tq_prompt_text or r.field_key
            order = r.tq_order
            scope = "tenant"
        else:
            prompt = r.field_key
            order = None
            scope = "other"
        answers.append(
            {
                "question_order": order,
                "prompt": prompt,
                "field_key": r.field_key,
                "answer": _human_answer(r.answer_text, r.answer_number, r.answer_boolean),
                "scope": scope,
            }
        )

    # ── Otras candidaturas del mismo candidato dentro de la empresa ──────────
    other_rows = db.execute(
        select(
            Application.id.label("application_id"),
            Application.vacancy_id,
            Vacancy.title.label("vacancy_title"),
            Application.status,
            Application.classification,
            Application.score_total,
        )
        .outerjoin(Vacancy, Vacancy.id == Application.vacancy_id)
        .where(
            Application.candidate_id == application.candidate_id,
            Application.tenant_id == application.tenant_id,
            Application.id != application.id,
        )
        .order_by(Application.created_at.desc())
    ).all()

    other_applications = [
        {
            "application_id": o.application_id,
            "vacancy_id": o.vacancy_id,
            "vacancy_title": o.vacancy_title,
            "status": o.status,
            "classification": o.classification,
            "score_total": float(o.score_total) if o.score_total is not None else None,
        }
        for o in other_rows
    ]

    payload = {
        "id": application.id,
        "tenant_id": application.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "candidate_id": application.candidate_id,
        "candidate_full_name": candidate.full_name if candidate else None,
        "candidate_phone": candidate.phone_e164 if candidate else None,
        "vacancy_id": application.vacancy_id,
        "vacancy_title": vacancy.title if vacancy else None,
        "status": application.status,
        "classification": application.classification,
        "score_rules": float(application.score_rules or 0),
        "score_cv": float(application.score_cv) if application.score_cv is not None else None,
        "score_total": float(application.score_total) if application.score_total is not None else None,
        "is_disqualified": application.is_disqualified,
        "disqualification_reason": application.disqualification_reason,
        "origin": application.origin,
        "preferred_platform": preferred_platform,
        "last_outbound_status": latest_outbound.status if latest_outbound else None,
        "last_outbound_channel": latest_outbound.channel if latest_outbound else None,
        "recommendation": latest_eval.recommendation if latest_eval else None,
        "cv_extracted_text": latest_cv.extracted_text if latest_cv else None,
        "analysis": analysis,
        "answers": answers,
        "other_applications": other_applications,
    }
    return payload
