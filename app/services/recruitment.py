# app/services/recruitment.py
"""
RecruitmentService: máquina de estados de la conversación.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, select

from app.channels.base import IncomingAttachment, IncomingMessageEvent, OutgoingMessage, outgoing_from_legacy
from app.channels.whatsapp_twilio import TwilioWhatsAppGateway
from app.core.config import settings
from app.core.db import SessionLocal
from app.cv_pipeline import extract_cv_text, get_storage, next_cv_version, normalize_phone, sha256_bytes, validate_cv
from app.enums import (
    AiEvalStatus,
    ApplicationOrigin,
    ApplicationStatus,
    ChatState,
    Classification,
    CvParseStatus,
    Platform,
    SourceScope,
    VacancyStatus,
)
from app.logger import log_event
from app.models import (
    AiEvaluation,
    Answer,
    Application,
    Candidate,
    ConversationSession,
    CvDocument,
    Question,
    ScoringRule,
    Tenant,
    TenantQuestion,
    Vacancy,
    VacancyQuestion,
)
from app.services.scoring import classify_candidate, compare_rule, norm, score_answers_from_vacancy_questions, validate_answer
from app.llm_client import LlmClient

logger = logging.getLogger("recruitment")

ALLOWED_TRANSITIONS: dict[ChatState, set[ChatState]] = {
    ChatState.WELCOME: {ChatState.SELECT_VACANCY, ChatState.ESCALATE_HUMAN, ChatState.WELCOME},
    ChatState.SELECT_VACANCY: {ChatState.CAPTURE_NAME, ChatState.ESCALATE_HUMAN, ChatState.SELECT_VACANCY},
    ChatState.CAPTURE_NAME: {ChatState.VACANCY_QA_MODE, ChatState.ESCALATE_HUMAN, ChatState.CAPTURE_NAME},
    ChatState.VACANCY_QA_MODE: {
        ChatState.VACANCY_QA_MODE,
        ChatState.ASK_TENANT_QUESTIONS,
        ChatState.REQUEST_CV,
        ChatState.ESCALATE_HUMAN,
    },
    ChatState.ASK_TENANT_QUESTIONS: {
        ChatState.ASK_TENANT_QUESTIONS,
        ChatState.REQUEST_CV,
        ChatState.ESCALATE_HUMAN,
    },
    ChatState.REQUEST_CV: {
        ChatState.SCORING,
        ChatState.REQUEST_CV,
        ChatState.ESCALATE_HUMAN,
    },
    ChatState.WAITING_CANDIDATE_REPLY: {
        ChatState.WAITING_CANDIDATE_REPLY,
        ChatState.ASK_VACANCY_QUESTIONS,
        ChatState.SCORING,
        ChatState.ESCALATE_HUMAN,
    },
    ChatState.ASK_VACANCY_QUESTIONS: {
        ChatState.ASK_VACANCY_QUESTIONS,
        ChatState.SCORING,
        ChatState.ESCALATE_HUMAN,
    },
    ChatState.SCORING: {
        ChatState.ASK_VACANCY_QUESTIONS,
        ChatState.CONFIRM_AND_CLOSE,
        ChatState.ESCALATE_HUMAN,
        ChatState.SCORING,
    },
    ChatState.CONFIRM_AND_CLOSE: {ChatState.SELECT_VACANCY, ChatState.CONFIRM_AND_CLOSE},
    ChatState.ESCALATE_HUMAN: {ChatState.ESCALATE_HUMAN},
}


def detect_human_request(event: IncomingMessageEvent) -> bool:
    text = norm(event.text)
    return text in {"humano", "asesor", "rrhh", "reclutador", "agent", "human"} \
        or event.callback_data == "go:human"


def answer_faq_question(faq_context: dict[str, Any], user_question: str) -> str | None:
    q_tokens = set(norm(user_question).split())
    best_score, best_answer = 0, None
    for item in faq_context.get("items", []):
        tokens = set(norm(item.get("question", "")).split())
        tokens.update(norm(" ".join(item.get("keywords", []))).split())
        score = len(q_tokens & tokens)
        if score > best_score:
            best_score, best_answer = score, item.get("answer")
    return best_answer if best_score >= 1 else None


class RecruitmentService:
    def __init__(self) -> None:
        self.llm = LlmClient()

    # ── State machine ────────────────────────────────────────────────────────

    def _transition(self, session: ConversationSession, next_state: ChatState) -> None:
        allowed = ALLOWED_TRANSITIONS.get(session.current_state, set())
        if next_state not in allowed:
            raise RuntimeError(f"Transición inválida: {session.current_state} → {next_state}")
        session.current_state = next_state
        session.version += 1

    def _get_or_create_session(self, db, tenant, event: IncomingMessageEvent) -> ConversationSession:
        session = db.execute(
            select(ConversationSession)
            .where(
                ConversationSession.tenant_id == tenant.id,
                ConversationSession.platform == event.platform,
                ConversationSession.platform_chat_id == event.chat_id,
                ConversationSession.is_active.is_(True),
            )
            .with_for_update()
        ).scalar_one_or_none()

        if session:
            return session

        session = ConversationSession(
            tenant_id=tenant.id,
            platform=event.platform,
            platform_chat_id=event.chat_id,
            platform_user_id=event.user_id,
            current_state=ChatState.WELCOME,
            state_payload={},
        )
        db.add(session)
        db.flush()
        return session

    def _invalid(self, session: ConversationSession, message: str) -> list[dict]:
        session.invalid_input_count += 1
        if session.invalid_input_count >= 3:
            self._transition(session, ChatState.ESCALATE_HUMAN)
            return [{"text": "He detectado varios errores consecutivos. Te derivo con RRHH."}]
        return [{"text": message}]

    def dispatch(self, db, tenant: Tenant, event: IncomingMessageEvent, background_tasks) -> list[dict[str, Any]]:
        session = self._get_or_create_session(db, tenant, event)

        if (
            session.last_incoming_event_id
            and event.event_id
            and event.event_id == session.last_incoming_event_id
        ):
            return []
        session.last_incoming_event_id = event.event_id
        session.last_user_message_at = datetime.now(timezone.utc)

        if detect_human_request(event):
            return self._escalate_human(db, session, "Solicitud explícita de humano")

        if session.current_state == ChatState.CONFIRM_AND_CLOSE and norm(event.text) == "/start":
            self._transition(session, ChatState.SELECT_VACANCY)
            return self._show_vacancies(db, tenant, session)

        handlers = {
            ChatState.WELCOME: self._handle_welcome,
            ChatState.SELECT_VACANCY: self._handle_select_vacancy,
            ChatState.CAPTURE_NAME: self._handle_capture_name,
            ChatState.VACANCY_QA_MODE: self._handle_vacancy_qa,
            ChatState.ASK_TENANT_QUESTIONS: self._handle_ask_tenant_questions,
            ChatState.REQUEST_CV: self._handle_request_cv,
            ChatState.ASK_VACANCY_QUESTIONS: self._handle_ask_questions,
            ChatState.SCORING: lambda db, t, s, e: [{"text": "Estoy evaluando tu candidatura. Te escribiré en breve."}],
        }

        handler = handlers.get(session.current_state)
        if handler:
            return handler(db, tenant, session, event, background_tasks) \
                if session.current_state in {ChatState.REQUEST_CV} \
                else handler(db, tenant, session, event)

        return [{"text": "Estado no soportado. Te derivo con RRHH."}]

    # ── Handlers de estado ───────────────────────────────────────────────────

    def _handle_welcome(self, db, tenant, session, event):
        if event.contact_phone:
            phone = normalize_phone(event.contact_phone)
            candidate = db.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant.id,
                    Candidate.phone_e164 == phone,
                )
            ).scalar_one_or_none()

            if not candidate:
                candidate = Candidate(tenant_id=tenant.id, phone_e164=phone)
                db.add(candidate)
                db.flush()

            self._bind_candidate_channel(candidate, event)

            session.candidate_id = candidate.id
            self._transition(session, ChatState.SELECT_VACANCY)
            return self._show_vacancies(db, tenant, session)

        return [{
            "text": "Hola. Para continuar necesito identificarte por teléfono. Pulsa el botón para compartirlo.",
            "reply_markup": TelegramGateway.phone_keyboard(),
        }]

    @staticmethod
    def _bind_candidate_channel(candidate: Candidate, event: IncomingMessageEvent) -> None:
        if event.platform == Platform.TELEGRAM:
            try:
                candidate.telegram_chat_id = int(event.chat_id) if event.chat_id else None
                candidate.telegram_user_id = int(event.user_id) if event.user_id else None
            except (TypeError, ValueError):
                pass
        else:
            candidate.whatsapp_from = event.from_address
            candidate.whatsapp_wa_id = event.user_id
            if event.sender_name:
                candidate.whatsapp_profile_name = event.sender_name

    def _show_vacancies(self, db, tenant, session):
        vacancies = db.execute(
            select(Vacancy.id, Vacancy.title)
            .where(Vacancy.tenant_id == tenant.id, Vacancy.status == VacancyStatus.ACTIVE)
            .order_by(Vacancy.created_at.desc())
        ).all()

        if not vacancies:
            return [{"text": "No hay vacantes activas. RRHH te contactará si abren nuevas posiciones."}]

        session.state_payload = {}
        return [{
            "text": "Estas son las vacantes activas. Elige una.",
            "reply_markup": TelegramGateway.vacancy_keyboard([(str(v.id), v.title) for v in vacancies]),
        }]

    def _handle_select_vacancy(self, db, tenant, session, event):
        vacancy_id = None
        if event.callback_data and event.callback_data.startswith("vac:"):
            vacancy_id = event.callback_data.split(":", 1)[1]
        elif event.text and event.text.strip().isdigit():
            # Canales sin botones (WhatsApp): el candidato responde con el numero
            # de la lista mostrada en _show_vacancies (mismo where + order_by).
            choices = db.execute(
                select(Vacancy.id)
                .where(Vacancy.tenant_id == tenant.id, Vacancy.status == VacancyStatus.ACTIVE)
                .order_by(Vacancy.created_at.desc())
            ).scalars().all()
            idx = int(event.text.strip()) - 1
            if 0 <= idx < len(choices):
                vacancy_id = str(choices[idx])

        if not vacancy_id:
            return self._invalid(session, "Debes seleccionar una vacante de la lista.")

        vacancy = db.execute(
            select(Vacancy).where(
                Vacancy.id == vacancy_id,
                Vacancy.tenant_id == tenant.id,
                Vacancy.status == VacancyStatus.ACTIVE,
            )
        ).scalar_one_or_none()

        if not vacancy:
            return self._invalid(session, "La vacante ya no está disponible.")

        application = Application(
            tenant_id=tenant.id,
            candidate_id=session.candidate_id,
            vacancy_id=vacancy.id,
            status=ApplicationStatus.DRAFT,
        )
        db.add(application)
        db.flush()

        session.application_id = application.id
        session.state_payload = {"vacancy_id": str(vacancy.id), "question_index": 0}
        self._transition(session, ChatState.CAPTURE_NAME)
        return [{"text": f"Has seleccionado: *{vacancy.title}*\n\n¿Cuál es tu nombre y apellido?"}]

    def _handle_capture_name(self, db, tenant, session, event):
        if not event.text or len(event.text.strip()) < 3:
            return self._invalid(session, "Indica tu nombre completo (mínimo 3 caracteres).")

        candidate = db.execute(select(Candidate).where(Candidate.id == session.candidate_id)).scalar_one()
        candidate.full_name = event.text.strip()

        app = db.execute(select(Application).where(Application.id == session.application_id)).scalar_one()
        app.status = ApplicationStatus.IN_PROGRESS

        self._transition(session, ChatState.VACANCY_QA_MODE)
        return [{
            "text": "Perfecto. Puedes hacer preguntas sobre la vacante o pulsa Continuar para enviar tu CV.",
            "reply_markup": TelegramGateway.qa_keyboard(),
        }]

    def _handle_vacancy_qa(self, db, tenant, session, event):
        vacancy = db.execute(
            select(Vacancy).where(Vacancy.id == session.state_payload["vacancy_id"])
        ).scalar_one()

        if event.callback_data == "go:continue":
            tenant_questions = self._get_ordered_tenant_questions(db, tenant.id)

            if tenant_questions:
                session.state_payload = {
                    **session.state_payload,
                    "tenant_question_index": 0,
                }
                self._transition(session, ChatState.ASK_TENANT_QUESTIONS)
                return [
                    {"text": "Antes de enviarme tu CV necesito hacerte unas preguntas generales."},
                    *self._ask_next_tenant_question(db, tenant, session),
                ]

            self._transition(session, ChatState.REQUEST_CV)
            return [{"text": "Ahora envíame tu CV en PDF, JPG o PNG (máx. 20 MB)."}]

        if event.text:
            answer = answer_faq_question(vacancy.faq_context, event.text)
            if answer:
                return [{"text": answer, "reply_markup": TelegramGateway.qa_keyboard()}]
            return [{
                "text": "No tengo esa respuesta. Puedes continuar o pedir hablar con RRHH.",
                "reply_markup": TelegramGateway.qa_keyboard(),
            }]

        return self._invalid(session, "Haz una pregunta o pulsa Continuar.")

    def _handle_request_cv(self, db, tenant, session, event, background_tasks):
        if not event.attachments:
            return self._invalid(session, "Necesito el CV en PDF/JPG/PNG.")
        return self._process_cv(db, tenant, session, event, background_tasks)

    @staticmethod
    def _download_attachment(tenant, event: IncomingMessageEvent, attachment: IncomingAttachment):
        """Descarga el binario del adjunto según el canal.
        Devuelve (bytes, source_file_id, source_file_unique_id).
        """
        if event.platform == Platform.TELEGRAM:
            gateway = TelegramGateway(tenant.telegram_bot_token)
            file_bytes, _ = gateway.get_file_bytes(attachment.attachment_id)
            return file_bytes, attachment.attachment_id, attachment.metadata.get("file_unique_id")

        gateway = TwilioWhatsAppGateway.from_tenant(tenant)
        file_bytes = gateway.download_media(attachment.url)
        return file_bytes, attachment.attachment_id, None

    def _process_cv(self, db, tenant, session, event, background_tasks):
        app = db.execute(select(Application).where(Application.id == session.application_id)).scalar_one()

        attachment = event.attachments[0]
        file_bytes, source_file_id, source_file_unique_id = self._download_attachment(tenant, event, attachment)

        filename = attachment.filename or "cv.bin"
        mime_type = attachment.mime_type or "application/octet-stream"
        size_bytes = attachment.size_bytes or len(file_bytes)
        ext = validate_cv(filename, mime_type, size_bytes)

        version = next_cv_version(db, app.id)
        storage, backend_enum = get_storage()
        storage_key, content_blob = storage.save(tenant.id, app.id, version, filename, file_bytes)

        cv = CvDocument(
            tenant_id=tenant.id,
            application_id=app.id,
            version=version,
            original_filename=filename,
            mime_type=mime_type,
            extension=ext,
            size_bytes=size_bytes,
            sha256=sha256_bytes(file_bytes),
            source_platform=event.platform,
            source_file_id=source_file_id,
            source_file_unique_id=source_file_unique_id,
            source_metadata_json={"source": f"inbound_{event.platform.value}"},
            storage_backend=backend_enum,
            storage_key=storage_key,
            content=content_blob,
            parse_status=CvParseStatus.PENDING,
        )
        db.add(cv)
        db.flush()

        app.status = ApplicationStatus.PENDING_AI
        session.state_payload = {
            **session.state_payload,
            "question_index": 0,
            "cv_document_id": str(cv.id),
        }
        self._transition(session, ChatState.SCORING)

        background_tasks.add_task(self.run_cv_pipeline_async, tenant.id, app.id, cv.id)

        return [{
            "text": (
                "Gracias. Estoy leyendo tu CV y comprobando si algunas preguntas "
                "ya están respondidas en el documento. Te escribiré en breve."
            )
        }]

    # ── Métodos de preguntas genéricas de tenant ───────────────────────────

    def _get_ordered_tenant_questions(self, db, tenant_id):
        return db.execute(
            select(TenantQuestion, Question)
            .join(Question, Question.id == TenantQuestion.question_id)
            .where(
                TenantQuestion.tenant_id == tenant_id,
                TenantQuestion.is_active.is_(True),
                TenantQuestion.ask_before_cv.is_(True),
            )
            .order_by(TenantQuestion.question_order.asc())
        ).all()

    def _tenant_answer_map(self, db, application_id) -> dict[str, Any]:
        """Devuelve un mapa field_key → valor con todas las respuestas genéricas ya dadas."""
        answers = db.execute(
            select(Answer).where(
                Answer.application_id == application_id,
                Answer.tenant_question_id.is_not(None),
                Answer.is_valid.is_(True),
            )
        ).scalars().all()

        result: dict[str, Any] = {}
        for answer in answers:
            if answer.answer_boolean is not None:
                result[answer.field_key] = answer.answer_boolean
            elif answer.answer_number is not None:
                result[answer.field_key] = answer.answer_number
            else:
                result[answer.field_key] = answer.answer_text or ""
        return result

    @staticmethod
    def _matches_display_condition(
        condition: dict[str, Any] | None,
        answers_by_field: dict[str, Any],
    ) -> bool:
        """Evalúa si la pregunta debe mostrarse según su display_condition.

        Estructura de condition:
          {
            "depends_on_field_key": "trabaja_actualmente",
            "operator": "equals" | "not_equals" | "exists" | "not_exists",
            "value": true / false / "texto"
          }

        Si condition está vacía o ausente, la pregunta siempre se muestra.
        """
        if not condition:
            return True

        depends_on = condition.get("depends_on_field_key")
        operator = condition.get("operator", "equals")
        expected = condition.get("value")

        if not depends_on:
            return True

        if depends_on not in answers_by_field:
            # El campo del que depende aún no tiene respuesta: no mostrar.
            return False

        current = answers_by_field[depends_on]

        if operator == "equals":
            return current == expected
        if operator == "not_equals":
            return current != expected
        if operator == "exists":
            return current is not None and str(current).strip() != ""
        if operator == "not_exists":
            return current is None or str(current).strip() == ""

        return False

    def _save_answer(
        self,
        db,
        *,
        tenant_id,
        application_id,
        field_key: str,
        answer_text,
        answer_number,
        answer_boolean,
        raw_payload: dict,
        vacancy_question_id=None,
        tenant_question_id=None,
    ):
        if bool(vacancy_question_id) == bool(tenant_question_id):
            raise ValueError("Debe indicarse exactamente una referencia de pregunta.")

        filters = [Answer.application_id == application_id]
        if vacancy_question_id is not None:
            filters.append(Answer.vacancy_question_id == vacancy_question_id)
        else:
            filters.append(Answer.tenant_question_id == tenant_question_id)

        answer = db.execute(select(Answer).where(*filters)).scalar_one_or_none()

        if not answer:
            answer = Answer(
                tenant_id=tenant_id,
                application_id=application_id,
                vacancy_question_id=vacancy_question_id,
                tenant_question_id=tenant_question_id,
                field_key=field_key,
            )
            db.add(answer)
            db.flush()

        answer.answer_text = answer_text
        answer.answer_number = answer_number
        answer.answer_boolean = answer_boolean
        answer.raw_payload = raw_payload
        answer.is_valid = True
        return answer

    def _ask_next_tenant_question(self, db, tenant, session):
        app = db.execute(select(Application).where(Application.id == session.application_id)).scalar_one()
        questions = self._get_ordered_tenant_questions(db, tenant.id)
        idx = int(session.state_payload.get("tenant_question_index", 0))

        answers_by_field = self._tenant_answer_map(db, app.id)

        while idx < len(questions):
            tq, q = questions[idx]

            # Saltar si la condición de visualización no se cumple.
            if not self._matches_display_condition(tq.display_condition, answers_by_field):
                idx += 1
                continue

            existing_answer = db.execute(
                select(Answer).where(
                    Answer.application_id == app.id,
                    Answer.tenant_question_id == tq.id,
                    Answer.is_valid.is_(True),
                )
            ).scalar_one_or_none()

            if existing_answer:
                idx += 1
                continue

            session.state_payload = {
                **session.state_payload,
                "tenant_question_index": idx,
            }
            return [{"text": tq.prompt_override or q.prompt_text}]

        session.state_payload = {
            **session.state_payload,
            "tenant_question_index": idx,
        }

        if session.current_state != ChatState.REQUEST_CV:
            self._transition(session, ChatState.REQUEST_CV)

        return [{"text": "Gracias. Ahora envíame tu CV en PDF, JPG o PNG (máx. 20 MB)."}]

    def _handle_ask_tenant_questions(self, db, tenant, session, event):
        app = db.execute(select(Application).where(Application.id == session.application_id)).scalar_one()
        questions = self._get_ordered_tenant_questions(db, tenant.id)
        idx = int(session.state_payload.get("tenant_question_index", 0))

        if idx >= len(questions):
            self._transition(session, ChatState.REQUEST_CV)
            return [{"text": "Ahora envíame tu CV en PDF, JPG o PNG (máx. 20 MB)."}]

        tq, q = questions[idx]

        if not event.text:
            return self._invalid(session, "Debes responder con texto.")

        merged_validation = {**(q.default_validation or {}), **(tq.validation or {})}

        try:
            answer_text, answer_number, answer_boolean = validate_answer(
                q.answer_type.value,
                merged_validation,
                event.text,
            )
        except ValueError as exc:
            return self._invalid(session, str(exc))

        self._save_answer(
            db,
            tenant_id=tenant.id,
            application_id=app.id,
            tenant_question_id=tq.id,
            field_key=tq.field_key,
            answer_text=answer_text,
            answer_number=answer_number,
            answer_boolean=answer_boolean,
            raw_payload={"raw_text": event.text, "source": "candidate"},
        )

        session.state_payload = {
            **session.state_payload,
            "tenant_question_index": idx + 1,
        }
        session.invalid_input_count = 0

        return self._ask_next_tenant_question(db, tenant, session)

    # ── Preguntas de vacante ─────────────────────────────────────────────────

    def _get_ordered_questions(self, db, vacancy_id):
        return db.execute(
            select(VacancyQuestion, Question)
            .join(Question, Question.id == VacancyQuestion.question_id)
            .where(VacancyQuestion.vacancy_id == vacancy_id, VacancyQuestion.is_active.is_(True))
            .order_by(VacancyQuestion.question_order.asc())
        ).all()

    def _ask_next_question(self, db, app, session):
        questions = self._get_ordered_questions(db, app.vacancy_id)
        idx = int(session.state_payload.get("question_index", 0))

        while idx < len(questions):
            vq, q = questions[idx]

            # Saltar si ya existe una respuesta válida (insertada por el LLM o por el candidato).
            existing_answer = db.execute(
                select(Answer).where(
                    Answer.application_id == app.id,
                    Answer.vacancy_question_id == vq.id,
                    Answer.is_valid.is_(True),
                )
            ).scalar_one_or_none()

            if existing_answer:
                idx += 1
                continue

            # Pregunta pendiente: actualizar índice y devolver el texto al candidato.
            session.state_payload = {
                **session.state_payload,
                "question_index": idx,
            }
            return [{"text": vq.prompt_override or q.prompt_text}]

        # Todas las preguntas respondidas: pasar a scoring.
        session.state_payload = {
            **session.state_payload,
            "question_index": idx,
        }
        db.commit()

        if session.current_state != ChatState.SCORING:
            self._transition(session, ChatState.SCORING)

        return self._apply_scoring(db, app, session)

    def _handle_ask_questions(self, db, tenant, session, event):
        app = db.execute(select(Application).where(Application.id == session.application_id)).scalar_one()
        questions = self._get_ordered_questions(db, app.vacancy_id)
        idx = int(session.state_payload.get("question_index", 0))

        if idx >= len(questions):
            self._transition(session, ChatState.SCORING)
            return self._apply_scoring(db, app, session)

        vq, q = questions[idx]
        if not event.text:
            return self._invalid(session, "Debes responder con texto.")

        merged_validation = {**(q.default_validation or {}), **(vq.validation or {})}
        try:
            answer_text, answer_number, answer_boolean = validate_answer(
                q.answer_type.value, merged_validation, event.text
            )
        except ValueError as exc:
            return self._invalid(session, str(exc))

        answer = db.execute(
            select(Answer).where(Answer.application_id == app.id, Answer.vacancy_question_id == vq.id)
        ).scalar_one_or_none()

        if not answer:
            answer = Answer(
                tenant_id=tenant.id,
                application_id=app.id,
                vacancy_question_id=vq.id,
                field_key=vq.field_key,
            )
            db.add(answer)
            db.flush()

        answer.answer_text = answer_text
        answer.answer_number = answer_number
        answer.answer_boolean = answer_boolean
        answer.raw_payload = {"raw_text": event.text}
        answer.is_valid = True
        session.state_payload = {**session.state_payload, "question_index": idx + 1}
        session.invalid_input_count = 0
        return self._ask_next_question(db, app, session)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _apply_scoring(self, db, app: Application, session: ConversationSession) -> list[dict]:
        log_event(db=db, level="INFO", source="scoring", event="SCORING_START",
                  message="Iniciando scoring", application_id=app.id)
        try:
            vacancy = db.execute(select(Vacancy).where(Vacancy.id == app.vacancy_id)).scalar_one()
            answers = db.execute(select(Answer).where(Answer.application_id == app.id)).scalars().all()
            ai_eval = db.execute(
                select(AiEvaluation).where(AiEvaluation.application_id == app.id)
            ).scalar_one_or_none()

            # Validar preguntas de vacante requeridas
            required_ids = db.execute(
                select(VacancyQuestion.id).where(
                    VacancyQuestion.vacancy_id == app.vacancy_id,
                    VacancyQuestion.required.is_(True),
                )
            ).scalars().all()
            answered_ids = db.execute(
                select(Answer.vacancy_question_id).where(Answer.application_id == app.id)
            ).scalars().all()
            if set(required_ids) - set(answered_ids):
                app.status = ApplicationStatus.IN_PROGRESS
                return [{"text": "Faltan respuestas obligatorias para completar la postulación."}]

            # Validar preguntas genéricas obligatorias (solo las que se mostraron según su condición).
            tenant_questions = self._get_ordered_tenant_questions(db, app.tenant_id)
            answers_by_field = self._tenant_answer_map(db, app.id)
            answered_tenant_ids = set(
                db.execute(
                    select(Answer.tenant_question_id).where(
                        Answer.application_id == app.id,
                        Answer.tenant_question_id.is_not(None),
                        Answer.is_valid.is_(True),
                    )
                ).scalars().all()
            )
            required_tenant_ids = [
                tq.id
                for tq, q in tenant_questions
                if tq.required
                and tq.is_active
                and tq.ask_before_cv
                and self._matches_display_condition(tq.display_condition, answers_by_field)
            ]
            if set(required_tenant_ids) - answered_tenant_ids:
                app.status = ApplicationStatus.IN_PROGRESS
                return [{"text": "Faltan respuestas obligatorias para completar la postulación."}]

            if not ai_eval or ai_eval.status == AiEvalStatus.PENDING:
                app.status = ApplicationStatus.SCORING
                return [{"text": "Analizando tu CV, un momento…"}]

            if ai_eval.status == AiEvalStatus.FAILED:
                return self._escalate_human(db, session, "Falló la evaluación IA del CV")

            answer_map: dict[str, Any] = {}
            for a in answers:
                if a.answer_boolean is not None:
                    answer_map[a.field_key] = a.answer_boolean
                elif a.answer_number is not None:
                    answer_map[a.field_key] = a.answer_number
                else:
                    answer_map[a.field_key] = a.answer_text or ""

            candidate = db.execute(select(Candidate).where(Candidate.id == app.candidate_id)).scalar_one()
            rules = db.execute(
                select(ScoringRule)
                .where(ScoringRule.vacancy_id == app.vacancy_id, ScoringRule.is_active.is_(True))
                .order_by(ScoringRule.priority.asc())
            ).scalars().all()

            question_score = score_answers_from_vacancy_questions(
                db=db,
                app=app,
                answers=answers,
            )

            rule_score = Decimal("0")
            is_disqualified = False
            disqualification_reason = None

            for rule in rules:
                if rule.source_scope == SourceScope.ANSWER:
                    current = answer_map.get(rule.field_key)
                elif rule.source_scope == SourceScope.CANDIDATE:
                    current = getattr(candidate, rule.field_key, None)
                else:
                    current = (ai_eval.parsed_json or {}).get(rule.field_key)

                matched = compare_rule(current, rule)

                if matched and rule.is_disqualifier:
                    is_disqualified = True
                    disqualification_reason = rule.name
                    break

                # Las reglas ANSWER no suman puntos: las preguntas ya puntúan
                # por VacancyQuestion.max_points para evitar doble puntuación.
                if matched and rule.source_scope != SourceScope.ANSWER:
                    rule_score += Decimal(rule.points)

            score_rules = question_score + rule_score

            score_cv_raw = Decimal(str(ai_eval.cv_score_0_10 or 0))
            classification, total, score_cv_normalized = classify_candidate(
                vacancy,
                score_rules,
                score_cv_raw,
                is_disqualified,
            )

            log_event(
                db=db,
                level="INFO",
                source="scoring",
                event="SCORING_BREAKDOWN",
                payload={
                    "question_score": float(question_score),
                    "rule_score": float(rule_score),
                    "score_rules": float(score_rules),
                    "cv_score_raw": float(score_cv_raw),
                    "cv_score_normalized": float(score_cv_normalized),
                    "score_total": float(total),
                },
                application_id=app.id,
            )

            app.score_rules = score_rules
            app.score_cv = score_cv_normalized
            app.score_total = total
            app.classification = classification
            app.is_disqualified = is_disqualified
            app.disqualification_reason = disqualification_reason
            app.status = {
                Classification.SHORTLIST: ApplicationStatus.SHORTLIST,
                Classification.INTERVIEW: ApplicationStatus.INTERVIEW,
                Classification.REVIEW: ApplicationStatus.REVIEW,
                Classification.REJECT: ApplicationStatus.REJECTED,
            }[classification]

            self._transition(session, ChatState.CONFIRM_AND_CLOSE)
            log_event(db=db, level="INFO", source="scoring", event="SCORING_COMPLETE",
                      payload={"score_total": float(total), "classification": classification.value},
                      application_id=app.id)
            self._notify_top_candidates(db, app.tenant_id, app.vacancy_id)

            labels = {
                Classification.SHORTLIST: "✅ Shortlist — muy buena candidatura",
                Classification.INTERVIEW: "👍 Entrevista recomendada",
                Classification.REVIEW: "🔍 En revisión por RRHH",
                Classification.REJECT: "❌ No seleccionado en esta ocasión",
            }
            return [{"text": (
                f"Hemos procesado tu candidatura.\n"
                f"Resultado: {labels[classification]}\n\n"
                f"Puntuación total: {total:.1f}\n"
                f"Escribe /start para postular a otra vacante."
            )}]
        except Exception as e:
            log_event(db=db, level="ERROR", source="scoring", event="SCORING_EXCEPTION",
                      message=str(e), exc=e, application_id=app.id)
            raise

    def _notify_top_candidates(self, db, tenant_id, vacancy_id):
        rows = db.execute(
            select(Candidate.full_name, Candidate.phone_e164, Application.score_total, Application.classification)
            .join(Application, Application.candidate_id == Candidate.id)
            .where(
                Application.tenant_id == tenant_id,
                Application.vacancy_id == vacancy_id,
                Application.classification.in_([Classification.SHORTLIST, Classification.INTERVIEW]),
            )
            .order_by(
                case(
                    (Application.classification == Classification.SHORTLIST, 2),
                    (Application.classification == Classification.INTERVIEW, 1),
                    else_=0,
                ).desc(),
                Application.score_total.desc(),
            )
        ).all()
        top = [
            {"nombre": r.full_name, "telefono": r.phone_e164,
             "score_total": float(r.score_total), "estado": r.classification.value}
            for r in rows[: settings.top_n_notify]
        ]
        logger.info("HR_TOP_CANDIDATES %s", json.dumps(top, ensure_ascii=False))

    def _escalate_human(self, db, session, reason: str) -> list[dict]:
        if session.application_id:
            app = db.execute(select(Application).where(Application.id == session.application_id)).scalar_one()
            app.status = ApplicationStatus.NEEDS_HUMAN
        self._transition(session, ChatState.ESCALATE_HUMAN)
        return [{"text": f"Voy a derivar tu caso a RRHH. Motivo: {reason}"}]

    # ── CV Pipeline async ─────────────────────────────────────────────────────
    def _questions_for_llm(self, db, vacancy_id) -> list[dict[str, Any]]:
        rows = self._get_ordered_questions(db, vacancy_id)

        result = []

        for vq, q in rows:
            result.append({
                "vacancy_question_id": str(vq.id),
                "field_key": vq.field_key,
                "prompt_text": vq.prompt_override or q.prompt_text,
                "answer_type": q.answer_type.value,
                "required": vq.required,
                "max_points": vq.max_points,
                "validation": {
                    **(q.default_validation or {}),
                    **(vq.validation or {}),
                },
            })

        return result


    def _prefill_answers_from_cv(
        self,
        db,
        tenant_id,
        app: Application,
        inferred_answers: list[Any],
    ) -> int:
        created_count = 0

        if not inferred_answers:
            return created_count

        rows = self._get_ordered_questions(db, app.vacancy_id)

        question_map = {
            str(vq.id): (vq, q)
            for vq, q in rows
        }

        for item in inferred_answers:
            data = item.model_dump() if hasattr(item, "model_dump") else dict(item)

            if not data.get("is_answered_in_cv"):
                continue

            confidence = float(data.get("confidence") or 0)
            if confidence < 0.75:
                continue

            vq_id = str(data.get("vacancy_question_id") or "").strip()
            normalized_answer = str(data.get("normalized_answer") or "").strip()

            if not vq_id or not normalized_answer:
                continue

            pair = question_map.get(vq_id)
            if not pair:
                continue

            vq, q = pair

            existing_answer = db.execute(
                select(Answer).where(
                    Answer.application_id == app.id,
                    Answer.vacancy_question_id == vq.id,
                )
            ).scalar_one_or_none()

            if existing_answer:
                continue

            merged_validation = {
                **(q.default_validation or {}),
                **(vq.validation or {}),
            }

            try:
                answer_text, answer_number, answer_boolean = validate_answer(
                    q.answer_type.value,
                    merged_validation,
                    normalized_answer,
                )
            except ValueError:
                continue

            answer = Answer(
                tenant_id=tenant_id,
                application_id=app.id,
                vacancy_question_id=vq.id,
                field_key=vq.field_key,
                answer_text=answer_text,
                answer_number=answer_number,
                answer_boolean=answer_boolean,
                raw_payload={
                    "source": "llm_cv_prefill",
                    "raw_text": normalized_answer,
                    "evidence": data.get("evidence"),
                    "confidence": confidence,
                    "llm_payload": data,
                },
                is_valid=True,
            )

            db.add(answer)
            created_count += 1

        db.flush()
        return created_count

    def _tenant_answers_for_llm(self, db, app: Application) -> list[dict[str, Any]]:
        rows = db.execute(
            select(Answer, TenantQuestion, Question)
            .join(TenantQuestion, TenantQuestion.id == Answer.tenant_question_id)
            .join(Question, Question.id == TenantQuestion.question_id)
            .where(
                Answer.application_id == app.id,
                Answer.tenant_question_id.is_not(None),
                Answer.is_valid.is_(True),
                TenantQuestion.is_active.is_(True),
                TenantQuestion.include_in_cv_score.is_(True),
            )
            .order_by(TenantQuestion.question_order.asc())
        ).all()

        result: list[dict[str, Any]] = []
        for answer, tq, q in rows:
            if answer.answer_boolean is not None:
                value = answer.answer_boolean
            elif answer.answer_number is not None:
                value = float(answer.answer_number)
            else:
                value = answer.answer_text or ""

            result.append({
                "tenant_question_id": str(tq.id),
                "field_key": tq.field_key,
                "prompt_text": tq.prompt_override or q.prompt_text,
                "answer_type": q.answer_type.value,
                "answer": value,
            })

        return result

    def _send_session_messages(self, db, tenant, session, outgoing: list[dict]) -> None:
        """Envía los dicts legacy de respuesta por el canal de la sesión.
        Se usa desde tareas en background (pipeline de CV), donde no hay webhook
        que entregue la respuesta.
        """
        if not outgoing:
            return

        if session.platform == Platform.TELEGRAM:
            gateway = TelegramGateway(tenant.telegram_bot_token)
            for msg in outgoing:
                try:
                    gateway.send_message(int(session.platform_chat_id), msg["text"], msg.get("reply_markup"))
                except Exception as send_exc:
                    log_event(db=db, level="ERROR", source="cv_pipeline", event="MSG_SEND_FAILED",
                              message=str(send_exc), application_id=session.application_id)
            return

        gateway = TwilioWhatsAppGateway.from_tenant(tenant)
        for msg in outgoing:
            try:
                gateway.send_message(
                    outgoing_from_legacy(Platform.WHATSAPP, session.platform_chat_id, msg)
                )
            except Exception as send_exc:
                log_event(db=db, level="ERROR", source="cv_pipeline", event="MSG_SEND_FAILED",
                          message=str(send_exc), application_id=session.application_id)

    def run_cv_pipeline_async(self, tenant_id, application_id, cv_document_id, dispatch_messages: bool = True):
        with SessionLocal() as db:
            log_event(db=db, level="INFO", source="cv_pipeline", event="PIPELINE_START",
                      tenant_id=tenant_id, application_id=application_id)
            try:
                tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one()
                app = db.execute(select(Application).where(Application.id == application_id)).scalar_one()
                vacancy = db.execute(select(Vacancy).where(Vacancy.id == app.vacancy_id)).scalar_one()
                cv = db.execute(select(CvDocument).where(CvDocument.id == cv_document_id)).scalar_one()
                session = db.execute(
                    select(ConversationSession).where(
                        ConversationSession.application_id == app.id,
                        ConversationSession.is_active.is_(True),
                    )
                ).scalar_one()

                content = cv.content
                if content is None:
                    with open(cv.storage_key, "rb") as fh:
                        content = fh.read()

                text, parse_status = extract_cv_text(cv.extension, content)
                cv.extracted_text = text
                cv.parse_status = parse_status

                ai_eval = db.execute(
                    select(AiEvaluation).where(AiEvaluation.cv_document_id == cv.id)
                ).scalar_one_or_none()

                if not ai_eval:
                    ai_eval = AiEvaluation(
                        tenant_id=tenant.id,
                        application_id=app.id,
                        cv_document_id=cv.id,
                        status=AiEvalStatus.PENDING,
                    )
                    db.add(ai_eval)
                    db.flush()

                try:
                    vacancy_questions_for_llm = self._questions_for_llm(db, vacancy.id)
                    tenant_answers_for_llm = self._tenant_answers_for_llm(db, app)

                    payload, raw, latency_ms = self.llm.evaluate_cv(
                        {
                            "title": vacancy.title,
                            "description": vacancy.description,
                            "mandatory_requirements": vacancy.mandatory_requirements,
                            "desirable_requirements": vacancy.desirable_requirements,
                            "location_text": vacancy.location_text,
                            "schedule_text": vacancy.schedule_text,
                        },
                        text,
                        vacancy_questions=vacancy_questions_for_llm,
                        tenant_screening_answers=tenant_answers_for_llm,
                    )
                    ai_eval.raw_response = raw
                    ai_eval.parsed_json = payload.model_dump()
                    ai_eval.candidate_profile = payload.candidate_profile
                    ai_eval.experience_summary = payload.experience_summary
                    ai_eval.skills = payload.skills
                    ai_eval.red_flags = payload.red_flags
                    ai_eval.cv_score_0_10 = Decimal(str(payload.cv_score_0_10))
                    ai_eval.recommendation = payload.recommendation
                    ai_eval.status = AiEvalStatus.SUCCESS
                    ai_eval.attempts += 1
                    app.status = ApplicationStatus.SCORING
                    prefilled_count = self._prefill_answers_from_cv(
                        db=db,
                        tenant_id=tenant.id,
                        app=app,
                        inferred_answers=payload.answered_vacancy_questions,
                    )

                    log_event(
                        db=db,
                        level="INFO",
                        source="cv_pipeline",
                        event="CV_ANSWERS_PREFILLED",
                        payload={"prefilled_count": prefilled_count},
                        application_id=app.id,
                    )
                    log_event(db=db, level="INFO", source="cv_pipeline", event="LLM_SUCCESS",
                              payload={"score": float(payload.cv_score_0_10), "latency_ms": latency_ms},
                              application_id=app.id)
                except Exception as exc:
                    ai_eval.status = AiEvalStatus.FAILED
                    ai_eval.error_message = str(exc)
                    ai_eval.attempts += 1
                    log_event(db=db, level="ERROR", source="cv_pipeline", event="LLM_FAILED",
                              message=str(exc), exc=exc, application_id=app.id)
                    db.commit()
                    return

                if session.current_state == ChatState.SCORING:
                    self._transition(session, ChatState.ASK_VACANCY_QUESTIONS)
                    outgoing = self._ask_next_question(db, app, session)

                    db.commit()

                    if dispatch_messages:
                        self._send_session_messages(db, tenant, session, outgoing)

                    return

                db.commit()
            except Exception as e:
                log_event(db=db, level="CRITICAL", source="cv_pipeline", event="PIPELINE_CRASH",
                          message=str(e), exc=e, tenant_id=tenant_id, application_id=application_id)
                db.rollback()
                raise
