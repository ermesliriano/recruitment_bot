from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.vacancy import Vacancy
from app.models.question import VacancyQuestion


def _status_value(value: Any) -> str:
    """
    Normaliza status tanto si viene como string como si viene como Enum.
    """
    if value is None:
        return ""

    if hasattr(value, "value"):
        return str(value.value).lower()

    return str(value).lower()


def _is_active_vacancy(vacancy: Vacancy) -> bool:
    return _status_value(vacancy.status) == "active"


def _question_id(question: VacancyQuestion) -> str:
    """
    En algunos modelos el campo puede llamarse id y en otros vq_id.
    Ajusta esto si tu modelo usa otro nombre.
    """
    return str(getattr(question, "id", None) or getattr(question, "vq_id", None))


def get_vacancy_budget(
    db: Session,
    vacancy_id: UUID,
    *,
    cv_max_score_override: int | None = None,
    question_max_score_overrides: dict[str, int] | None = None,
    new_question_max_score: int | None = None,
    excluded_question_id: str | None = None,
) -> dict[str, int]:
    vacancy = (
        db.query(Vacancy)
        .filter(Vacancy.id == vacancy_id)
        .first()
    )

    if not vacancy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vacante no encontrada.",
        )

    cv_max_score = (
        int(cv_max_score_override)
        if cv_max_score_override is not None
        else int(vacancy.cv_max_score or 0)
    )

    question_max_score_overrides = question_max_score_overrides or {}

    questions = (
        db.query(VacancyQuestion)
        .filter(
            VacancyQuestion.vacancy_id == vacancy_id,
            VacancyQuestion.is_active.is_(True),
        )
        .all()
    )

    questions_total = 0

    for question in questions:
        qid = _question_id(question)

        if excluded_question_id and qid == str(excluded_question_id):
            continue

        if qid in question_max_score_overrides:
            questions_total += int(question_max_score_overrides[qid] or 0)
        else:
            questions_total += int(question.max_points or 0)

    if new_question_max_score is not None:
        questions_total += int(new_question_max_score or 0)

    total = cv_max_score + questions_total

    return {
        "cv_max_score": cv_max_score,
        "questions_total": questions_total,
        "total": total,
    }


def validate_active_vacancy_budget(
    db: Session,
    vacancy_id: UUID,
    *,
    cv_max_score_override: int | None = None,
    question_max_score_overrides: dict[str, int] | None = None,
    new_question_max_score: int | None = None,
    excluded_question_id: str | None = None,
) -> None:
    vacancy = (
        db.query(Vacancy)
        .filter(Vacancy.id == vacancy_id)
        .first()
    )

    if not vacancy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vacante no encontrada.",
        )

    if not _is_active_vacancy(vacancy):
        return

    budget = get_vacancy_budget(
        db,
        vacancy_id,
        cv_max_score_override=cv_max_score_override,
        question_max_score_overrides=question_max_score_overrides,
        new_question_max_score=new_question_max_score,
        excluded_question_id=excluded_question_id,
    )

    if budget["total"] != 100:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVALID_ACTIVE_VACANCY_BUDGET",
                "message": (
                    "No se puede guardar el cambio porque la vacante está activa "
                    "y la suma de puntuaciones máximas debe ser exactamente 100 puntos."
                ),
                "total": budget["total"],
                "cv_max_score": budget["cv_max_score"],
                "questions_total": budget["questions_total"],
            },
        )
