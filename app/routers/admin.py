# app/routers/admin.py
from __future__ import annotations

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, aliased
from fastapi import APIRouter, Depends

from app.core.db import get_db
from app.core.security import require_admin_token
from app.enums import Classification
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.cv import CvDocument
from app.models.outbound_message import OutboundMessage
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
                application_id=r.application_id,
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

    payload = {
        "id": application.id,
        "tenant_id": application.tenant_id,
        "candidate_id": application.candidate_id,
        "vacancy_id": application.vacancy_id,
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
        "last_outbound_template_sid": latest_outbound.template_sid if latest_outbound else None,
        "latest_cv": {
            "id": latest_cv.id,
            "version": latest_cv.version,
            "original_filename": latest_cv.original_filename,
            "mime_type": latest_cv.mime_type,
            "parse_status": latest_cv.parse_status.value if latest_cv.parse_status else None,
            "source_platform": latest_cv.source_platform.value if latest_cv.source_platform else None,
        } if latest_cv else None,
    }
    return payload
