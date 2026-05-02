# app/services/question_service.py
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.question import Question
from app.schemas.question import QuestionCreate


class QuestionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_questions(self, tenant_id: str | None = None) -> list[Question]:
        stmt = select(Question).where(Question.is_active.is_(True))
        if tenant_id:
            stmt = stmt.where(Question.tenant_id == tenant_id)
        return self.db.execute(stmt).scalars().all()

    def get_question(self, question_id: str) -> Question:
        q = self.db.execute(select(Question).where(Question.id == question_id)).scalar_one_or_none()
        if not q:
            raise ValueError(f"Pregunta {question_id} no encontrada")
        return q

    def create_question(self, data: QuestionCreate) -> Question:
        question = Question(
            id=uuid4(),
            tenant_id=data.tenant_id,
            code=data.code,
            prompt_text=data.prompt_text,
            answer_type=data.answer_type,
            default_validation=data.default_validation or {},
            is_active=True,
        )
        self.db.add(question)
        self.db.commit()
        self.db.refresh(question)
        return question

    def deactivate_question(self, question_id: str) -> Question:
        question = self.get_question(question_id)
        question.is_active = False
        self.db.commit()
        self.db.refresh(question)
        return question
