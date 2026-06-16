# app/schemas/vacancy.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.enums import AnswerType, ScoringOperator, VacancyStatus


class VacancyBase(BaseModel):
    title: str
    description: str
    responsibilities: list[str] = []
    mandatory_requirements: list[str] = []
    desirable_requirements: list[str] = []
    salary_text: str | None = None
    schedule_text: str | None = None
    location_text: str | None = None
    benefits: list[str] = []
    faq_context: dict[str, Any] = Field(default_factory=lambda: {"items": []})
    cv_max_score: int = Field(default=40, ge=1, le=100)
    classification_thresholds: dict[str, Any] = Field(
        default_factory=lambda: {"review": 35, "interview": 60, "shortlist": 75}
    )


class VacancyCreate(VacancyBase):
    code: str
    tenant_id: UUID


class VacancyUpdate(VacancyBase):
    pass


class VacancyStatusUpdate(BaseModel):
    status: VacancyStatus


class VacancyOut(VacancyBase):
    id: UUID
    code: str
    tenant_id: UUID
    tenant_name: str | None = None
    status: VacancyStatus
    created_at: datetime | None = None
    # Agregados calculados en list_vacancies (atributos transitorios sobre el ORM).
    # Tienen default para que los endpoints que devuelven la vacante sin estos
    # cálculos (create/update/status/get) no fallen al serializar.
    questions_total_points: int = 0
    applications_count: int = 0

    model_config = {"from_attributes": True}


# ── Preguntas de vacante (creación conjunta) ────────────────────────────────

class ScoringRuleInline(BaseModel):
    name: str
    operator: ScoringOperator
    expected_text: str | None = None
    expected_number: Decimal | None = None
    expected_boolean: bool | None = None
    points: int = 0
    is_disqualifier: bool = False
    priority: int = 100


class VacancyQuestionUpdate(BaseModel):
    prompt_override: str | None = None
    max_points: int | None = Field(default=None, ge=0, le=100)
    question_order: int | None = Field(default=None, ge=1)
    required: bool | None = None


class VacancyQuestionCreate(BaseModel):
    question_code: str = Field(..., max_length=80)
    prompt_text: str
    answer_type: AnswerType
    default_validation: dict[str, Any] = {}
    field_key: str = Field(..., max_length=120)
    question_order: int = Field(..., ge=1)
    prompt_override: str | None = None
    validation: dict[str, Any] = {}
    required: bool = True
    scoring_enabled: bool = True
    max_points: int = Field(default=0, ge=0, le=100)
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
    max_points: int
    scoring_rule: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


# ── Generación automática de preguntas desde requisitos obligatorios ───────────

class GenerateQuestionsFromRequirementsRequest(BaseModel):
    """Body del endpoint POST /vacancies/{id}/questions/generate-from-requirements."""
    force: bool = False


class GeneratedVacancyQuestionsOut(BaseModel):
    """Respuesta del endpoint de generación automática de preguntas."""
    vacancy_id: UUID
    created_count: int
    questions: list[VacancyQuestionOut]
