# app/schemas/application.py
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.enums import ApplicationStatus, Classification


class ApplicationOut(BaseModel):
    id: UUID
    status: ApplicationStatus
    classification: Classification | None = None
    score_rules: float
    score_cv: float | None = None
    score_total: float | None = None
    is_disqualified: bool
    disqualification_reason: str | None = None

    model_config = {"from_attributes": True}
