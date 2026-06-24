# app/schemas/ranking.py
from __future__ import annotations

from pydantic import BaseModel


class RankingRow(BaseModel):
    application_id: str
    nombre: str | None
    telefono: str
    vacante: str
    origin: str | None = None
    channel: str | None = None
    outbound_status: str | None = None
    score_rules: float
    score_cv: float | None
    score_total: float | None
    estado: str | None

    model_config = {"from_attributes": True}


class RankingResponse(BaseModel):
    vacancy_id: str
    total: int
    items: list[RankingRow]
    incomplete_total: int = 0
    incomplete: list[RankingRow] = []
