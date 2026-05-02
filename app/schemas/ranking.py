# app/schemas/ranking.py
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.enums import Classification


class RankingRow(BaseModel):
    nombre: str | None
    telefono: str
    vacante: str
    score_rules: float
    score_cv: float | None
    score_total: float | None
    estado: str | None

    model_config = {"from_attributes": True}


class RankingResponse(BaseModel):
    vacancy_id: str
    total: int
    items: list[RankingRow]
