# app/routers/admin.py
from __future__ import annotations

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, aliased
from fastapi import APIRouter, Depends

from app.core.db import get_db
from app.core.security import require_admin_token
from app.enums import Classification
from app.models.application import Application, Answer
from app.models.candidate import Candidate
from app.models.cv import CvDocument, AiEvaluation
from app.models.outbound_message import OutboundMessage
from app.models.question import Question, TenantQuestion, VacancyQuestion
from app.models.tenant import Tenant
from app.models.vacancy import Vacancy
from app.schemas.application import ApplicationOut
from app.schemas.ranking import RankingRow

router = APIRouter(prefix="/v1", tags=["Admin"], dependencies=[Depends(require_admin_token)])


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

    rows = db.execute(
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
    ).all()

    return {
        "vacancy_id": vacancy_id,
        "total": len(rows),
        "items": [
            RankingRow(
                application_id=str(r.application_id),
                nombre=r.nombre,
                telefono=r.telefono,
                vacante=r.vacante,
                origin=r.origin.value if r.origin else None,
                channel=r.channel.value if r.channel else None,
                outbound_status=r.outbound_status,
                score_rules=float(r.score_rules or 0),
                score_cv=float(r.score_cv) if r.score_cv is not None else None,
                score_total=float(r.score_total) if r.score_total is not None else None,
                estado=r.estado.value if r.estado else None,
            ).model_dump()
            for r in rows
        ],
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

    # Recomendación del LLM: última evaluación que realmente trae texto.
    latest_eval = db.execute(
        select(AiEvaluation)
        .where(
            AiEvaluation.application_id == application.id,
            AiEvaluation.recommendation.is_not(None),
        )
        .order_by(AiEvaluation.created_at.desc())
    ).scalars().first()

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
        "preferred_platform": application.preferred_platform,
        "last_outbound_status": latest_outbound.status if latest_outbound else None,
        "last_outbound_channel": latest_outbound.channel if latest_outbound else None,
        "recommendation": latest_eval.recommendation if latest_eval else None,
        "cv_extracted_text": latest_cv.extracted_text if latest_cv else None,
        "answers": answers,
        "other_applications": other_applications,
    }
    return payload
