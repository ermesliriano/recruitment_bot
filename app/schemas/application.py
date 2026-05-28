# app/schemas/application.py
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.enums import ApplicationOrigin, ApplicationStatus, Classification, Platform


class ApplicationOut(BaseModel):
    id: UUID
    tenant_id: UUID
    candidate_id: UUID
    vacancy_id: UUID
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
    last_outbound_template_sid: str | None = None
    latest_cv: dict[str, Any] | None = None

    model_config = {"from_attributes": True}
