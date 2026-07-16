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
    stage: str | None = None
    # Fecha de aplicacion (Application.created_at, ISO). Campo aditivo para la
    # pantalla de ranking; no altera la logica de ordenacion.
    applied_at: str | None = None

    model_config = {"from_attributes": True}


class RankingResponse(BaseModel):
    vacancy_id: str
    total: int
    items: list[RankingRow]
    incomplete_total: int = 0
    incomplete: list[RankingRow] = []
    # Presupuesto de puntuacion de la vacante (aditivo): cv_max_score +
    # questions_max_score = 100. Permite mostrar "52 / 60" en el frontend.
    cv_max_score: float | None = None
    questions_max_score: float | None = None
