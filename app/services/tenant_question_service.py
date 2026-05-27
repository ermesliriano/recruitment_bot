# app/services/tenant_question_service.py
from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.question import Question, TenantQuestion
from app.schemas.tenant_question import TenantQuestionCreate, TenantQuestionUpdate


class TenantQuestionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _serialize(self, tq: TenantQuestion, q: Question) -> dict:
        return {
            "tq_id": str(tq.id),
            "question_id": str(q.id),
            "question_order": tq.question_order,
            "field_key": tq.field_key,
            "prompt_text": tq.prompt_override or q.prompt_text,
            "answer_type": q.answer_type,
            "display_condition": tq.display_condition or {},
            "required": tq.required,
            "ask_before_cv": tq.ask_before_cv,
            "include_in_cv_score": tq.include_in_cv_score,
        }

    def list_questions(self, tenant_id: str) -> list[dict]:
        rows = self.db.execute(
            select(TenantQuestion, Question)
            .join(Question, Question.id == TenantQuestion.question_id)
            .where(
                TenantQuestion.tenant_id == tenant_id,
                TenantQuestion.is_active.is_(True),
            )
            .order_by(TenantQuestion.question_order.asc())
        ).all()

        return [self._serialize(tq, q) for tq, q in rows]

    def create_question(self, tenant_id: str, data: TenantQuestionCreate) -> dict:
        # Reutilizar pregunta del catálogo si ya existe con el mismo código.
        question = self.db.execute(
            select(Question).where(
                Question.tenant_id == tenant_id,
                Question.code == data.question_code,
            )
        ).scalar_one_or_none()

        if question and question.answer_type != data.answer_type:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una pregunta con ese código y otro tipo de respuesta.",
            )

        if not question:
            question = Question(
                id=uuid4(),
                tenant_id=tenant_id,
                code=data.question_code,
                prompt_text=data.prompt_text,
                answer_type=data.answer_type,
                default_validation=data.default_validation or {},
                is_active=True,
            )
            self.db.add(question)
            self.db.flush()

        tq = TenantQuestion(
            id=uuid4(),
            tenant_id=tenant_id,
            question_id=question.id,
            question_order=data.question_order,
            field_key=data.field_key,
            prompt_override=data.prompt_override,
            validation=data.validation or {},
            display_condition=data.display_condition or {},
            required=data.required,
            ask_before_cv=data.ask_before_cv,
            include_in_cv_score=data.include_in_cv_score,
            is_active=True,
        )

        try:
            self.db.add(tq)
            self.db.commit()
            self.db.refresh(tq)
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una pregunta genérica activa con ese orden o field_key para este tenant.",
            ) from exc

        return self._serialize(tq, question)

    def update_question(self, tenant_id: str, tq_id: str, data: TenantQuestionUpdate) -> dict:
        tq = self.db.execute(
            select(TenantQuestion).where(
                TenantQuestion.id == tq_id,
                TenantQuestion.tenant_id == tenant_id,
                TenantQuestion.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if not tq:
            raise ValueError(f"Pregunta genérica {tq_id} no encontrada")

        if data.question_order is not None:
            duplicated_order = self.db.execute(
                select(TenantQuestion).where(
                    TenantQuestion.tenant_id == tenant_id,
                    TenantQuestion.question_order == data.question_order,
                    TenantQuestion.is_active.is_(True),
                    TenantQuestion.id != tq_id,
                )
            ).scalar_one_or_none()

            if duplicated_order:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ya existe una pregunta genérica activa con ese orden.",
                )

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(tq, field, value)

        self.db.commit()
        self.db.refresh(tq)

        q = self.db.execute(
            select(Question).where(Question.id == tq.question_id)
        ).scalar_one()

        return self._serialize(tq, q)

    def delete_question(self, tenant_id: str, tq_id: str) -> None:
        tq = self.db.execute(
            select(TenantQuestion).where(
                TenantQuestion.id == tq_id,
                TenantQuestion.tenant_id == tenant_id,
                TenantQuestion.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if not tq:
            raise ValueError(f"Pregunta genérica {tq_id} no encontrada")

        tq.is_active = False
        self.db.commit()
