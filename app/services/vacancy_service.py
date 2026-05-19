# app/services/vacancy_service.py
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import VacancyStatus
from app.models.vacancy import Vacancy
from app.models.question import Question, VacancyQuestion
from app.models.scoring_rule import ScoringRule
from app.schemas.vacancy import VacancyCreate, VacancyQuestionCreate, VacancyQuestionUpdate, VacancyUpdate
from app.services.question_generation_llm import generate_questions_from_requirements
from app.services.scoring import validate_scoring_budget
from app.services.vacancy_budget import validate_active_vacancy_budget

class VacancyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── CRUD vacantes ──────────────────────────────────────────────────────

    def list_vacancies(self, tenant_id: str | None = None) -> list[Vacancy]:
        stmt = select(Vacancy).where(Vacancy.deleted_at.is_(None))
        if tenant_id:
            stmt = stmt.where(Vacancy.tenant_id == tenant_id)
        return self.db.execute(stmt).scalars().all()

    def get_vacancy(self, vacancy_id: str, tenant_id: str | None = None) -> Vacancy:
        stmt = select(Vacancy).where(Vacancy.id == vacancy_id, Vacancy.deleted_at.is_(None))
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

        next_cv_max_score = (
            data.cv_max_score
            if data.cv_max_score is not None
            else vacancy.cv_max_score
        )

        validate_active_vacancy_budget(
            self.db,
            vacancy_id,
            cv_max_score_override=next_cv_max_score,
        )

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(vacancy, field, value)

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
        # Soft-delete: desactivar todas las preguntas asociadas y marcar la vacante.
        # No se borra ningún registro físico para preservar el historial.
        self.db.execute(
            update(VacancyQuestion)
            .where(
                VacancyQuestion.vacancy_id == vacancy_id,
                VacancyQuestion.is_active.is_(True),
            )
            .values(is_active=False)
        )
        vacancy.deleted_at = datetime.now(timezone.utc)
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

        validate_active_vacancy_budget(
            self.db,
            vacancy_id,
            new_question_max_score=data.max_points,
        )

        # Verificar que no exista ya una pregunta activa con el mismo orden.
        # Esto ocurre si el usuario reutiliza el número de orden de una pregunta
        # previamente eliminada con soft-delete.
        existing_order = self.db.execute(
            select(VacancyQuestion).where(
                VacancyQuestion.vacancy_id == vacancy_id,
                VacancyQuestion.question_order == data.question_order,
                VacancyQuestion.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if existing_order:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DUPLICATED_ACTIVE_QUESTION_ORDER",
                    "message": (
                        f"Ya existe una pregunta activa con el orden {data.question_order}. "
                        "Usa otro número o edita la pregunta existente."
                    ),
                    "field": "question_order",
                    "value": data.question_order,
                },
            )

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
        try:
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

            self.db.commit()

        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "QUESTION_ORDER_CONFLICT",
                    "message": (
                        "No se pudo crear la pregunta porque ya existe una pregunta activa "
                        "con ese orden o campo para esta vacante."
                    ),
                },
            ) from exc

        ok, total = validate_scoring_budget(self.db, vacancy_id)
        if not ok:
            raise ValueError(
                f"El presupuesto de puntuación no suma 100 (actual: {total}). "
                f"Ajusta cv_max_score y los max_points de las preguntas."
            )

        return {"vq_id": str(vq.id), "question_id": str(question.id)}

    def update_question(
        self,
        vacancy_id: str,
        vq_id: str,
        data: VacancyQuestionUpdate,
    ) -> dict:
        vq = self.db.execute(
            select(VacancyQuestion).where(
                VacancyQuestion.id == vq_id,
                VacancyQuestion.vacancy_id == vacancy_id,
                VacancyQuestion.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if not vq:
            raise ValueError(f"Pregunta {vq_id} no encontrada")

        next_max_points = (
            data.max_points
            if data.max_points is not None
            else vq.max_points
        )

        validate_active_vacancy_budget(
            self.db,
            vacancy_id,
            question_max_score_overrides={
                str(vq.id): next_max_points,
            },
        )

        for field, value in data.model_dump(exclude_none=True).items():
            setattr(vq, field, value)
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

    # ── Generación automática de preguntas desde requisitos obligatorios ─────────

    def generate_questions_from_mandatory_requirements(
        self,
        vacancy_id: str,
        tenant_id: str | None = None,
    ) -> dict:
        """
        Llama al LLM para generar preguntas de screening a partir de los
        `mandatory_requirements` de la vacante y las persiste como VacancyQuestion.

        Reglas de negocio aplicadas en este método:
        - La vacante debe existir y tener entre 1 y 10 requisitos obligatorios.
        - Si ya existen preguntas activas, se rechaza la operación (409).
        - Los puntos se redistribuyen automáticamente para respetar el presupuesto.
        """
        vacancy = self.get_vacancy(vacancy_id, tenant_id)

        mandatory_requirements: list[str] = vacancy.mandatory_requirements or []

        if not mandatory_requirements:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La vacante no tiene requisitos obligatorios.",
            )

        if len(mandatory_requirements) > 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "TOO_MANY_MANDATORY_REQUIREMENTS",
                    "message": (
                        "La generación automática solo está disponible para "
                        "vacantes con 10 requisitos obligatorios o menos."
                    ),
                    "count": len(mandatory_requirements),
                },
            )

        existing_active_questions = (
            self.db.execute(
                select(VacancyQuestion).where(
                    VacancyQuestion.vacancy_id == vacancy_id,
                    VacancyQuestion.is_active.is_(True),
                )
            )
            .scalars()
            .all()
        )

        if existing_active_questions:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "VACANCY_ALREADY_HAS_QUESTIONS",
                    "message": (
                        "La vacante ya tiene preguntas configuradas. "
                        "Edita o elimina las preguntas existentes antes de generar nuevas."
                    ),
                },
            )

        # ── Llamada al LLM ───────────────────────────────────────────────────
        generated_questions = generate_questions_from_requirements(
            vacancy_title=vacancy.title,
            vacancy_description=vacancy.description,
            mandatory_requirements=mandatory_requirements,
            cv_max_score=vacancy.cv_max_score,
        )

        # ── Persistencia ─────────────────────────────────────────────────────────
        created_items: list[dict] = []

        for generated in generated_questions:
            # Reutiliza Question existente por code+tenant o crea una nueva.
            question = self.db.execute(
                select(Question).where(
                    Question.code == generated.question_code,
                    Question.tenant_id == vacancy.tenant_id,
                )
            ).scalar_one_or_none()

            if not question:
                question = Question(
                    id=uuid4(),
                    tenant_id=vacancy.tenant_id,
                    code=generated.question_code,
                    prompt_text=generated.prompt_text,
                    answer_type=generated.answer_type,
                    default_validation=generated.validation,
                )
                self.db.add(question)
                self.db.flush()

            vq = VacancyQuestion(
                id=uuid4(),
                tenant_id=vacancy.tenant_id,
                vacancy_id=vacancy.id,
                question_id=question.id,
                question_order=generated.question_order,
                field_key=generated.field_key,
                prompt_override=None,
                validation=generated.validation,
                required=generated.required,
                scoring_enabled=generated.scoring_enabled,
                max_points=generated.max_points,
            )
            self.db.add(vq)
            self.db.flush()

            created_items.append(
                {
                    "vq_id": vq.id,
                    "question_id": question.id,
                    "question_order": vq.question_order,
                    "field_key": vq.field_key,
                    "prompt_text": question.prompt_text,
                    "answer_type": question.answer_type,
                    "required": vq.required,
                    "scoring_enabled": vq.scoring_enabled,
                    "max_points": vq.max_points,
                    "scoring_rule": None,
                }
            )

        self.db.commit()

        return {
            "vacancy_id": vacancy.id,
            "created_count": len(created_items),
            "questions": created_items,
        }

    def delete_question(self, vacancy_id: str, vq_id: str) -> None:
        vq = self.db.execute(
            select(VacancyQuestion).where(
                VacancyQuestion.id == vq_id,
                VacancyQuestion.vacancy_id == vacancy_id,
                VacancyQuestion.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if not vq:
            raise ValueError(f"Pregunta {vq_id} no encontrada")

        validate_active_vacancy_budget(
            self.db,
            vacancy_id,
            excluded_question_id=str(vq.id),
        )

        # Soft-delete: se marca como inactiva, no se elimina el registro.
        vq.is_active = False
        self.db.commit()
