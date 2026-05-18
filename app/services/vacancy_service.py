# app/services/vacancy_service.py
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import VacancyStatus
from app.models.vacancy import Vacancy
from app.models.question import Question, VacancyQuestion
from app.models.scoring_rule import ScoringRule
from app.schemas.vacancy import VacancyCreate, VacancyQuestionCreate, VacancyQuestionUpdate, VacancyUpdate
from app.services.scoring import validate_scoring_budget
from app.services.vacancy_budget import validate_active_vacancy_budget

class VacancyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── CRUD vacantes ──────────────────────────────────────────────────────

    def list_vacancies(self, tenant_id: str | None = None) -> list[Vacancy]:
        stmt = select(Vacancy)
        if tenant_id:
            stmt = stmt.where(Vacancy.tenant_id == tenant_id)
        return self.db.execute(stmt).scalars().all()

    def get_vacancy(self, vacancy_id: str, tenant_id: str | None = None) -> Vacancy:
        stmt = select(Vacancy).where(Vacancy.id == vacancy_id)
        if tenant_id:
            stmt = stmt.where(Vacancy.tenant_id == tenant_id)
        vacancy = self.db.execute(stmt).scalar_one_or_none()
        if not vacancy:
            raise ValueError(f"Vacante {vacancy_id} no encontrada")
        return vacancy

    def create_vacancy(self, data: VacancyCreate) -> Vacancy:
        vacancy = Vacancy(
            id=uuid4(),
            tenant_id=data.tenant_id,
            code=data.code,
            title=data.title,
            description=data.description,
            mandatory_requirements=data.mandatory_requirements,
            desirable_requirements=data.desirable_requirements,
            salary_text=data.salary_text,
            schedule_text=data.schedule_text,
            location_text=data.location_text,
            benefits=data.benefits,
            faq_context=data.faq_context or {"items": []},
            cv_max_score=data.cv_max_score,
            classification_thresholds=data.classification_thresholds or {},
            status=VacancyStatus.DRAFT,
        )
        self.db.add(vacancy)
        self.db.commit()
        self.db.refresh(vacancy)
        return vacancy

    def update_vacancy(self, vacancy_id: str, data: VacancyUpdate, tenant_id: str | None = None) -> Vacancy:
        vacancy = self.get_vacancy(vacancy_id, tenant_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(vacancy, field, value)
            
        validate_active_vacancy_budget(
            db,
            vacancy_id,
            cv_max_score_override=payload.cv_max_score,
        )
        self.db.commit()
        self.db.refresh(vacancy)
        return vacancy

    def set_status(self, vacancy_id: str, status: VacancyStatus, tenant_id: str | None = None) -> Vacancy:
        vacancy = self.get_vacancy(vacancy_id, tenant_id)
        vacancy.status = status
        self.db.commit()
        self.db.refresh(vacancy)
        return vacancy

    def delete_vacancy(self, vacancy_id: str, tenant_id: str | None = None) -> None:
        vacancy = self.get_vacancy(vacancy_id, tenant_id)
        self.db.delete(vacancy)
        self.db.commit()

    # ── Preguntas de vacante ───────────────────────────────────────────────

    def list_questions(self, vacancy_id: str) -> list[dict]:
        rows = self.db.execute(
            select(VacancyQuestion, Question)
            .join(Question, Question.id == VacancyQuestion.question_id)
            .where(VacancyQuestion.vacancy_id == vacancy_id, VacancyQuestion.is_active.is_(True))
            .order_by(VacancyQuestion.question_order.asc())
        ).all()
        return [
            {
                "vq_id": str(vq.id),
                "question_id": str(q.id),
                "question_order": vq.question_order,
                "field_key": vq.field_key,
                "prompt_text": vq.prompt_override or q.prompt_text,
                "answer_type": q.answer_type,
                "required": vq.required,
                "scoring_enabled": vq.scoring_enabled,
                "max_points": vq.max_points,
            }
            for vq, q in rows
        ]

    def add_question(self, vacancy_id: str, tenant_id: str, data: VacancyQuestionCreate) -> dict:
        # Reutilizar pregunta existente por code+tenant o crear una nueva
        question = self.db.execute(
            select(Question).where(
                Question.code == data.question_code,
                Question.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()

        if not question:
            question = Question(
                id=uuid4(),
                tenant_id=tenant_id,
                code=data.question_code,
                prompt_text=data.prompt_text,
                answer_type=data.answer_type,
                default_validation=data.default_validation,
            )
            self.db.add(question)
            self.db.flush()

        vq = VacancyQuestion(
            id=uuid4(),
            tenant_id=tenant_id,
            vacancy_id=vacancy_id,
            question_id=question.id,
            question_order=data.question_order,
            field_key=data.field_key,
            prompt_override=data.prompt_override,
            validation=data.validation,
            required=data.required,
            scoring_enabled=data.scoring_enabled,
            max_points=data.max_points,
        )
        self.db.add(vq)
        self.db.flush()

        if data.scoring_rule:
            rule = ScoringRule(
                id=uuid4(),
                tenant_id=tenant_id,
                vacancy_id=vacancy_id,
                name=data.scoring_rule.name,
                source_scope="answer",
                field_key=data.field_key,
                operator=data.scoring_rule.operator,
                expected_text=data.scoring_rule.expected_text,
                expected_number=data.scoring_rule.expected_number,
                expected_boolean=data.scoring_rule.expected_boolean,
                points=data.scoring_rule.points,
                is_disqualifier=data.scoring_rule.is_disqualifier,
                priority=data.scoring_rule.priority,
            )
            self.db.add(rule)
        validate_active_vacancy_budget(
            db,
            vacancy_id,
            new_question_max_score=payload.max_points,
        )
        self.db.commit()

        ok, total = validate_scoring_budget(self.db, vacancy_id)
        if not ok:
            raise ValueError(
                f"El presupuesto de puntuación no suma 100 (actual: {total}). "
                f"Ajusta cv_max_score y los max_points de las preguntas."
            )

        return {"vq_id": str(vq.id), "question_id": str(question.id)}

    def update_question(self, vq_id: str, data: VacancyQuestionUpdate) -> dict:
        vq = self.db.execute(
            select(VacancyQuestion).where(VacancyQuestion.vq_id == vq_id)
        ).scalar_one_or_none()
        if not vq:
            raise ValueError(f"Pregunta {vq_id} no encontrada")

        for field, value in data.model_dump(exclude_none=True).items():
            setattr(vq, field, value)
        validate_active_vacancy_budget(
            db,
            vacancy_id,
            new_question_max_score=payload.max_points,
        )
        self.db.commit()
        self.db.refresh(vq)

        q = self.db.execute(
            select(Question).where(Question.id == vq.question_id)
        ).scalar_one()

        return {
            "vq_id": str(vq.id),
            "question_id": str(q.id),
            "question_order": vq.question_order,
            "field_key": vq.field_key,
            "prompt_text": vq.prompt_override or q.prompt_text,
            "answer_type": q.answer_type,
            "required": vq.required,
            "scoring_enabled": vq.scoring_enabled,
            "max_points": vq.max_points,
        }
