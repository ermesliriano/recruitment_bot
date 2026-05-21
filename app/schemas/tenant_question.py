# app/schemas/tenant_question.py
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import AnswerType


class TenantQuestionCreate(BaseModel):
    question_code: str = Field(..., max_length=80)
    prompt_text: str
    answer_type: AnswerType
    default_validation: dict[str, Any] = Field(default_factory=dict)
    field_key: str = Field(..., max_length=120)
    question_order: int = Field(..., ge=1)
    prompt_override: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    ask_before_cv: bool = True
    include_in_cv_score: bool = True


class TenantQuestionUpdate(BaseModel):
    prompt_override: str | None = None
    question_order: int | None = Field(default=None, ge=1)
    required: bool | None = None
    ask_before_cv: bool | None = None
    include_in_cv_score: bool | None = None


class TenantQuestionOut(BaseModel):
    tq_id: UUID
    question_id: UUID
    question_order: int
    field_key: str
    prompt_text: str
    answer_type: AnswerType
    required: bool
    ask_before_cv: bool
    include_in_cv_score: bool

    model_config = {"from_attributes": True}
