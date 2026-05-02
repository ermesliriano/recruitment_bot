# app/schemas/question.py
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.enums import AnswerType


class QuestionBase(BaseModel):
    code: str
    prompt_text: str
    answer_type: AnswerType
    default_validation: dict[str, Any] = {}


class QuestionCreate(QuestionBase):
    tenant_id: UUID


class QuestionOut(QuestionBase):
    id: UUID
    tenant_id: UUID
    is_active: bool

    model_config = {"from_attributes": True}
