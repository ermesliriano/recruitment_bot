# app/schemas/vacancy.py
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import AnswerType, ScoringOperator, SourceScope, VacancyStatus


# ─── Vacancy ──────────────────────────────────────────────────────────────────

class VacancyBase(BaseModel):
    code: str = Field(..., max_length=80)
    title: str = Field(..., max_length=255)
    description: str
    responsibilities: list[str] = []
    mandatory_requirements: list[str] = []
    desirable_requirements: list[str] = []
    salary_text: str | None = None
    schedule_text: str | None = None
    location_text: str | None = None
    benefits: list[str] = []
    faq_context: dict[str, Any] = Field(default_factory=lambda: {"items": []})
    cv_score_factor: Decimal = Decimal("6.00")
    classification_thresholds: dict[str, Any] = Field(
        default_factory=lambda: {"review": 35, "interview": 60, "shortlist": 75}
    )


class VacancyCreate(VacancyBase):
    pass


class VacancyUpdate(VacancyBase):
    pass


class VacancyStatusUpdate(BaseModel):
    status: VacancyStatus


class VacancyOut(VacancyBase):
    id: UUID
    tenant_id: UUID
    status: VacancyStatus
    created_at: Any
    updated_at: Any | None = None

    model_config = {"from_attributes": True}


# ─── Question + ScoringRule (creación conjunta) ────────────────────────────────

class ScoringRuleInline(BaseModel):
    """Regla de scoring que se crea junto con la pregunta de vacante."""
    name: str
    operator: ScoringOperator
    expected_text: str | None = None
    expected_number: Decimal | None = None
    expected_boolean: bool | None = None
    points: int = 0
    is_disqualifier: bool = False
    priority: int = 100


class VacancyQuestionCreate(BaseModel):
    """Crea una Question (si es nueva) y la asocia a la vacante con su regla."""
    # Datos de la pregunta
    question_code: str = Field(..., max_length=80)
    prompt_text: str
    answer_type: AnswerType
    default_validation: dict[str, Any] = {}

    # Datos de la asociación
    field_key: str = Field(..., max_length=120)
    question_order: int = Field(..., ge=1)
    prompt_override: str | None = None
    validation: dict[str, Any] = {}
    required: bool = True
    scoring_enabled: bool = True

    # Regla de scoring opcional
    scoring_rule: ScoringRuleInline | None = None


class VacancyQuestionOut(BaseModel):
    vq_id: UUID
    question_id: UUID
    question_order: int
    field_key: str
    prompt_text: str
    answer_type: AnswerType
    required: bool
    scoring_enabled: bool
    scoring_rule: dict[str, Any] | None = None

    model_config = {"from_attributes": True}
