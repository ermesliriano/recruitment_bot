from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CvImportItemOut(BaseModel):
    id: UUID
    candidate_id: UUID | None = None
    application_id: UUID | None = None
    original_filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    status: str
    outbound_status: str | None = None
    extraction_status: str | None = None
    detected_phone_e164: str | None = None
    phone_confidence: float | None = None
    phone_candidates_json: dict[str, Any] | None = None
    extracted_preview: str | None = None
    candidate_reused: bool = False
    application_reused: bool = False
    error_message: str | None = None

    model_config = {"from_attributes": True}


class ResolvePhoneIn(BaseModel):
    phone: str


class CvImportJobOut(BaseModel):
    id: UUID
    tenant_id: UUID
    vacancy_id: UUID
    requested_by: str | None = None
    total_files: int
    processed_files: int
    status: str
    summary_json: dict[str, Any] = Field(default_factory=dict)
    items: list[CvImportItemOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}
