# app/schemas/application.py
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.enums import ApplicationOrigin, ApplicationStatus, Classification, Platform


class ApplicationAnswerOut(BaseModel):
    """Una respuesta dada por el candidato, ya resuelta a texto legible."""
    question_order: int | None = None
    prompt: str
    field_key: str
    answer: str | None = None
    scope: str  # "vacancy" | "tenant" | "other"


class OtherApplicationOut(BaseModel):
    """Otra candidatura del mismo candidato dentro de la empresa."""
    application_id: UUID
    vacancy_id: UUID
    vacancy_title: str | None = None
    status: ApplicationStatus
    classification: Classification | None = None
    score_total: float | None = None


class CvAnalysisOut(BaseModel):
    """Salida cualitativa del análisis del CV (LLM), para mostrar en el detalle."""
    human_readable_summary: str | None = None
    qualitative_assessment: str | None = None
    score_rationale: str | None = None
    recommended_next_action: str | None = None
    skills: list[str] = []
    experience_summary: list[str] = []
    red_flags: list[str] = []
    missing_evidence: list[str] = []
    fit_gaps: list[str] = []
    follow_up_questions: list[str] = []


class ApplicationOut(BaseModel):
    id: UUID

    tenant_id: UUID
    tenant_name: str | None = None

    candidate_id: UUID
    candidate_full_name: str | None = None
    candidate_phone: str | None = None

    vacancy_id: UUID
    vacancy_title: str | None = None

    status: ApplicationStatus
    classification: Classification | None = None
    score_rules: float
    score_cv: float | None = None
    score_total: float | None = None
    is_disqualified: bool
    disqualification_reason: str | None = None
    origin: ApplicationOrigin | None = None
    preferred_platform: Platform | None = None
    last_outbound_status: str | None = None
    last_outbound_channel: Platform | None = None

    # Salida legible del análisis del CV (LLM) y transcripción del CV.
    recommendation: str | None = None
    cv_extracted_text: str | None = None
    analysis: CvAnalysisOut | None = None

    # Respuestas del candidato y otras candidaturas dentro de la empresa.
    answers: list[ApplicationAnswerOut] = []
    other_applications: list[OtherApplicationOut] = []

    model_config = {"from_attributes": True}
