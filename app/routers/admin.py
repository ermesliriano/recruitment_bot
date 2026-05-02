# app/routers/admin.py
from fastapi import APIRouter, Depends
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_admin_token
from app.enums import Classification
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.vacancy import Vacancy
from app.schemas.application import ApplicationOut
from app.schemas.ranking import RankingRow

router = APIRouter(prefix="/admin/v1", tags=["Admin"], dependencies=[Depends(require_admin_token)])


@router.get("/tenants/{tenant_id}/vacancies/{vacancy_id}/ranking")
def vacancy_ranking(tenant_id: str, vacancy_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
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
    ).all()

    return {
        "vacancy_id": vacancy_id,
        "total": len(rows),
        "items": [
            RankingRow(
                nombre=r.nombre,
                telefono=r.telefono,
                vacante=r.vacante,
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
    app = db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == tenant_id,
        )
    ).scalar_one()
    return app
