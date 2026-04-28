# app/schemas/ranking.py
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.enums import Classification


class RankingRow(BaseModel):
    application_id: UUID
    nombre: str | None
    telefono: str
    vacante: str
    score_rules: Decimal
    score_cv: Decimal | None
    score_total: Decimal | None
    estado: Classification | None
    created_at: str | None = None

    model_config = {"from_attributes": True}


class RankingResponse(BaseModel):
    vacancy_id: str
    total: int
    items: list[RankingRow]


class ApplicationDetail(BaseModel):
    application_id: str
    status: str
    classification: str | None
    score_rules: float
    score_cv: float | None
    score_total: float | None
    is_disqualified: bool
    disqualification_reason: str | None
