# app/routers/vacancies.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.db import get_db
from app.core.security import require_admin_token
from app.schemas.vacancy import (
    VacancyCreate,
    VacancyOut,
    VacancyQuestionCreate,
    VacancyQuestionOut,
    VacancyStatusUpdate,
    VacancyUpdate,
)
from app.services.vacancy_service import VacancyService

router = APIRouter(prefix="/vacancies", tags=["Vacancies"])


@router.get("/", response_model=List[VacancyOut])
def list_vacancies(tenant_id: str | None = None, db: Session = Depends(get_db)):
    return VacancyService(db).list_vacancies(tenant_id)


@router.post("/", response_model=VacancyOut, dependencies=[Depends(require_admin_token)])
def create_vacancy(data: VacancyCreate, db: Session = Depends(get_db)):
    return VacancyService(db).create_vacancy(data)


@router.get("/{vacancy_id}", response_model=VacancyOut)
def get_vacancy(vacancy_id: str, tenant_id: str | None = None, db: Session = Depends(get_db)):
    try:
        return VacancyService(db).get_vacancy(vacancy_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{vacancy_id}", response_model=VacancyOut, dependencies=[Depends(require_admin_token)])
def update_vacancy(vacancy_id: str, data: VacancyUpdate, tenant_id: str | None = None, db: Session = Depends(get_db)):
    try:
        return VacancyService(db).update_vacancy(vacancy_id, data, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{vacancy_id}/status", response_model=VacancyOut, dependencies=[Depends(require_admin_token)])
def set_vacancy_status(vacancy_id: str, data: VacancyStatusUpdate, db: Session = Depends(get_db)):
    try:
        return VacancyService(db).set_status(vacancy_id, data.status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{vacancy_id}", status_code=204, dependencies=[Depends(require_admin_token)])
def delete_vacancy(vacancy_id: str, db: Session = Depends(get_db)):
    try:
        VacancyService(db).delete_vacancy(vacancy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Preguntas de vacante ──────────────────────────────────────────────────────

@router.get("/{vacancy_id}/questions")
def list_vacancy_questions(vacancy_id: str, db: Session = Depends(get_db)):
    return VacancyService(db).list_questions(vacancy_id)


@router.post("/{vacancy_id}/questions", dependencies=[Depends(require_admin_token)])
def add_vacancy_question(
    vacancy_id: str,
    tenant_id: str,
    data: VacancyQuestionCreate,
    db: Session = Depends(get_db),
):
    return VacancyService(db).add_question(vacancy_id, tenant_id, data)
