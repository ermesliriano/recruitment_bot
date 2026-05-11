# app/services/scoring.py  (antes scoring_service)
"""
Lógica pura de scoring: comparación de reglas y clasificación.
Sin dependencias de red ni de estado conversacional.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import Classification, ScoringOperator


def norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def compare_rule(current_value: Any, rule) -> bool:
    if rule.operator == ScoringOperator.EQUALS:
        if rule.expected_boolean is not None:
            return current_value is rule.expected_boolean
        if rule.expected_number is not None:
            return Decimal(str(current_value or 0)) == rule.expected_number
        return norm(current_value) == norm(rule.expected_text)

    if rule.operator == ScoringOperator.CONTAINS:
        if isinstance(current_value, list):
            return norm(rule.expected_text) in [norm(x) for x in current_value]
        return norm(rule.expected_text) in norm(current_value)

    if rule.operator == ScoringOperator.GTE:
        return Decimal(str(current_value or 0)) >= Decimal(str(rule.expected_number))

    return False


def classify_candidate(
    vacancy,
    score_rules: Decimal,
    score_cv_raw: Decimal,
    is_disqualified: bool,
) -> tuple[Classification, Decimal, Decimal]:
    """Devuelve (classification, score_total, score_cv_normalizado)."""
    if is_disqualified:
        return Classification.REJECT, Decimal("0"), Decimal("0")

    cv_max = Decimal(str(vacancy.cv_max_score))
    score_cv_normalized = (score_cv_raw / Decimal("10")) * cv_max
    total = score_rules + score_cv_normalized
    thresholds = vacancy.classification_thresholds or {"review": 35, "interview": 60, "shortlist": 75}

    if total >= Decimal(str(thresholds["shortlist"])):
        return Classification.SHORTLIST, total, score_cv_normalized
    if total >= Decimal(str(thresholds["interview"])):
        return Classification.INTERVIEW, total, score_cv_normalized
    if total >= Decimal(str(thresholds["review"])):
        return Classification.REVIEW, total, score_cv_normalized
    return Classification.REJECT, total, score_cv_normalized


def validate_answer(
    qtype: str, validation: dict[str, Any], raw: str
) -> tuple[str | None, Decimal | None, bool | None]:
    raw = raw.strip()

    if qtype == "text":
        min_len = int(validation.get("min_len", 1))
        max_len = int(validation.get("max_len", 500))
        if not (min_len <= len(raw) <= max_len):
            raise ValueError(f"El texto debe tener entre {min_len} y {max_len} caracteres.")
        return raw, None, None

    if qtype == "number":
        try:
            number = Decimal(raw.replace(",", "."))
        except Exception as exc:
            raise ValueError("Debes responder con un número.") from exc
        if "min" in validation and number < Decimal(str(validation["min"])):
            raise ValueError(f"El valor debe ser >= {validation['min']}.")
        if "max" in validation and number > Decimal(str(validation["max"])):
            raise ValueError(f"El valor debe ser <= {validation['max']}.")
        return None, number, None

    if qtype == "boolean":
        true_vals = {norm(x) for x in validation.get("true_values", ["si", "sí", "s", "yes", "true"])}
        false_vals = {norm(x) for x in validation.get("false_values", ["no", "n", "false"])}
        v = norm(raw)
        if v in true_vals:
            return None, None, True
        if v in false_vals:
            return None, None, False
        raise ValueError("Debes responder sí o no.")

    raise ValueError(f"Tipo de respuesta no soportado: {qtype}")


def validate_scoring_budget(db: Session, vacancy_id: str) -> tuple[bool, int]:
    """Comprueba que cv_max_score + suma de max_points de preguntas activas == 100.
    Devuelve (ok, total_actual)."""
    from app.models.vacancy import Vacancy
    from app.models.question import VacancyQuestion

    vacancy = db.execute(select(Vacancy).where(Vacancy.id == vacancy_id)).scalar_one()
    question_points = db.execute(
        select(func.coalesce(func.sum(VacancyQuestion.max_points), 0)).where(
            VacancyQuestion.vacancy_id == vacancy_id,
            VacancyQuestion.is_active.is_(True),
        )
    ).scalar()
    total = vacancy.cv_max_score + int(question_points)
    return total == 100, total
