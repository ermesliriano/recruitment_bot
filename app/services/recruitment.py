# app/services/recruitment.py
"""
RecruitmentService: máquina de estados de la conversación + orquestador del pipeline de CV.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import case, select

from app.config import settings
from app.database import SessionLocal
from app.enums import (
    AiEvalStatus,
    ApplicationStatus,
    ChatState,
    Classification,
    CvParseStatus,
    Platform,
    SourceScope,
)
from app.logger import log_event
from app.models import (
    AiEvaluation,
    Answer,
    Application,
    Candidate,
    ConversationSession,
    Question,
    ScoringRule,
    Tenant,
    Vacancy,
    VacancyQuestion,
    CvDocument,
)
from app.services.scoring import classify_candidate, compare_rule, norm, validate_answer
from app.cv_pipeline import (
    extract_cv_text,
    get_storage,
    next_cv_version,
    normalize_phone,
    sha256_bytes,
    validate_cv,
)
from app.llm_client import LlmClient
from app.telegram_api import IncomingEvent, TelegramGateway

logger = logging.getLogger("recruitment")

ALLOWED_TRANSITIONS: dict[ChatState, set[ChatState]] = {
    ChatState.WELCOME: {ChatState.SELECT_VACANCY, ChatState.ESCALATE_HUMAN, ChatState.WELCOME},
    ChatState.SELECT_VACANCY: {ChatState.CAPTURE_NAME, ChatState.ESCALATE_HUMAN, ChatState.SELECT_VACANCY},
    ChatState.CAPTURE_NAME: {ChatState.VACANCY_QA_MODE, ChatState.ESCALATE_HUMAN, ChatState.CAPTURE_NAME},
    ChatState.VACANCY_QA_MODE: {ChatState.REQUEST_CV, ChatState.ESCALATE_HUMAN, ChatState.VACANCY_QA_MODE},
    ChatState.REQUEST_CV: {ChatState.ASK_VACANCY_QUESTIONS, ChatState.ESCALATE_HUMAN, ChatState.REQUEST_CV},
    ChatState.ASK_VACANCY_QUESTIONS: {ChatState.ASK_VACANCY_QUESTIONS, ChatState.SCORING, ChatState.ESCALATE_HUMAN},
    ChatState.SCORING: {ChatState.CONFIRM_AND_CLOSE, ChatState.ESCALATE_HUMAN, ChatState.SCORING},
    ChatState.CONFIRM_AND_CLOSE: {ChatState.SELECT_VACANCY, ChatState.CONFIRM_AND_CLOSE},
    ChatState.ESCALATE_HUMAN: {ChatState.ESCALATE_HUMAN},
}


def detect_human_request(event: IncomingEvent) -> bool:
    text = norm(event.text)
    return text in {"humano", "asesor", "rrhh", "reclutador", "agent", "human"} or \
        event.callback_data == "go:human"


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

    # ─── State machine ───────────────────────────────────────────────────────

    def _transition(self, session: ConversationSession, next_state: ChatState) -> None:
        allowed = ALLOWED_TRANSITIONS.get(session.current_state, set())
        if next_state not in allowed:
            raise RuntimeError(f"Transición inválida: {session.current_state} → {next_state}")
        session.current_state = next_state
        session.version += 1

    def _get_or_create_session(
        self, db, tenant_id, chat_id: int, user_id: int | None
    ) -> ConversationSession:
        session = db.execute(
            select(ConversationSession)
            .where(
                ConversationSession.tenant_id == tenant_id,
                ConversationSession.platform_chat_id == chat_id,
                ConversationSession.is_active.is_(True),
            )
            .with_for_update()
        ).scalar_one_or_none()

        if session:
            return session

        session = ConversationSession(
            tenant_id=tenant_id,
            platform=Platform.TELEGRAM,
            platform_chat_id=chat_id,
            platform_user_id=user_id,
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

    def dispatch(self, db, tenant: Tenant, event: IncomingEvent, background_tasks) -> list[dict[str, Any]]:
        session = self._get_or_create_session(db, tenant.id, event.chat_id, event.user_id)

        # Deduplicación por update_id
        if session.last_incoming_update_id and event.update_id <= session.last_incoming_update_id:
            return []
        session.last_incoming_update_id = event.update_id

        if detect_human_request(event):
            return self._escalate_human(db, session, "Solicitud explícita de humano")

        # Restart desde CONFIRM_AND_CLOSE
        if session.current_state == ChatState.CONFIRM_AND_CLOSE and norm(event.text) == "/start":
            self._transition(session, ChatState.SELECT_VACANCY)
            return self._show_vacancies(db, tenant, session)

        handlers = {
            ChatState.WELCOME: self._handle_welcome,
            ChatState.SELECT_VACANCY: self._handle_select_vacancy,
            ChatState.CAPTURE_NAME: self._handle_capture_name,
            ChatState.VACANCY_QA_MODE: self._handle_vacancy_qa,
            ChatState.REQUEST_CV: self._handle_request_cv,
            ChatState.ASK_VACANCY_QUESTIONS: self._handle_ask_questions,
            ChatState.SCORING: lambda *_: [{"text": "Estoy evaluando tu candidatura. Te escribiré en breve."}],
        }

        handler = handlers.get(session.current_state)
        if handler:
            return handler(db, tenant, session, event, background_tasks) \
                if session.current_state == ChatState.REQUEST_CV \
                else handler(db, tenant, session, event)

        return [{"text": "Estado no soportado. Te derivo con RRHH."}]

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
                candidate = Candidate(
                    tenant_id=tenant.id,
                    phone_e164=phone,
                    telegram_chat_id=event.chat_id,
                    telegram_user_id=event.user_id,
                )
                db.add(candidate)
                db.flush()
            else:
                candidate.telegram_chat_id = event.chat_id
                candidate.telegram_user_id = event.user_id

            session.candidate_id = candidate.id
            self._transition(session, ChatState.SELECT_VACANCY)
            return self._show_vacancies(db, tenant, session)

        return [{
            "text": "Hola. Para continuar necesito identificarte por teléfono. Pulsa el botón para compartirlo.",
            "reply_markup": TelegramGateway.phone_keyboard(),
        }]

    def _show_vacancies(self, db, tenant, session):
        from app.enums import VacancyStatus
        vacancies = db.execute(
            select(Vacancy.id, Vacancy.title)
            .where(
                Vacancy.tenant_id == tenant.id,
                Vacancy.status == VacancyStatus.ACTIVE,
            )
            .order_by(Vacancy.created_at.desc())
        ).all()

        if not vacancies:
            return [{"text": "Ahora mismo no hay vacantes activas. RRHH te contactará si abren nuevas posiciones."}]

        session.state_payload = {}
        return [{
            "text": "Estas son las vacantes activas. Elige una.",
            "reply_markup": TelegramGateway.vacancy_keyboard([(str(v.id), v.title) for v in vacancies]),
        }]

    def _handle_select_vacancy(self, db, tenant, session, event):
        if not event.callback_data or not event.callback_data.startswith("vac:"):
            return self._invalid(session, "Debes seleccionar una vacante usando los botones.")

        from app.enums import VacancyStatus
        vacancy_id = event.callback_data.split(":", 1)[1]
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
            return self._invalid(session, "Por favor indica tu nombre completo (mínimo 3 caracteres).")

        candidate = db.execute(select(Candidate).where(Candidate.id == session.candidate_id)).scalar_one()
        candidate.full_name = event.text.strip()

        app = db.execute(select(Application).where(Application.id == session.application_id)).scalar_one()
        app.status = ApplicationStatus.IN_PROGRESS

        self._transition(session, ChatState.VACANCY_QA_MODE)
        return [{
            "text": "Perfecto. Antes de enviar tu CV puedes hacer preguntas sobre la vacante, o pulsa Continuar.",
            "reply_markup": TelegramGateway.qa_keyboard(),
        }]

    def _handle_vacancy_qa(self, db, tenant, session, event):
        vacancy = db.execute(
            select(Vacancy).where(Vacancy.id == session.state_payload["vacancy_id"])
        ).scalar_one()

        if event.callback_data == "go:continue":
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
        if not event.document:
            return self._invalid(session, "Necesito el CV en PDF/JPG/PNG.")
        return self._process_cv(db, tenant, session, event, background_tasks)

    def _process_cv(self, db, tenant, session, event, background_tasks):
        app = db.execute(select(Application).where(Application.id == session.application_id)).scalar_one()
        gateway = TelegramGateway(tenant.telegram_bot_token)
        file_bytes, _ = gateway.get_file_bytes(event.document["file_id"])

        filename = event.document["file_name"]
        mime_type = event.document["mime_type"]
        size_bytes = event.document["file_size"]
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
            telegram_file_id=event.document["file_id"],
            telegram_file_unique_id=event.document.get("file_unique_id"),
            storage_backend=backend_enum,
            storage_key=storage_key,
            content=content_blob,
            parse_status=CvParseStatus.PENDING,
        )
        db.add(cv)
        db.flush()

        app.status = ApplicationStatus.PENDING_AI
        session.state_payload = {**session.state_payload, "question_index": 0, "cv_document_id": str(cv.id)}
        self._transition(session, ChatState.ASK_VACANCY_QUESTIONS)

        background_tasks.add_task(self.run_cv_pipeline_async, tenant.id, app.id, cv.id)
        return self._ask_next_question(db, app, session)

    def _get_ordered_questions(self, db, vacancy_id):
        return db.execute(
            select(VacancyQuestion, Question)
            .join(Question, Question.id == VacancyQuestion.question_id)
            .where(
                VacancyQuestion.vacancy_id == vacancy_id,
                VacancyQuestion.is_active.is_(True),
            )
            .order_by(VacancyQuestion.question_order.asc())
        ).all()

    def _ask_next_question(self, db, app, session):
        questions = self._get_ordered_questions(db, app.vacancy_id)
        idx = int(session.state_payload.get("question_index", 0))
        if idx >= len(questions):
            db.commit()
            self._transition(session, ChatState.SCORING)
            return self._apply_scoring(db, app, session)

        _, q = questions[idx]
        vq = questions[idx][0]
        prompt = vq.prompt_override or q.prompt_text
        return [{"text": prompt}]

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
            select(Answer).where(
                Answer.application_id == app.id,
                Answer.vacancy_question_id == vq.id,
            )
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

    # ─── Scoring ──────────────────────────────────────────────────────────────

    def _apply_scoring(self, db, app: Application, session: ConversationSession) -> list[dict]:
        log_event(db=db, level="INFO", source="scoring", event="SCORING_START",
                  message="Iniciando scoring", application_id=app.id)
        try:
            vacancy = db.execute(select(Vacancy).where(Vacancy.id == app.vacancy_id)).scalar_one()
            answers = db.execute(select(Answer).where(Answer.application_id == app.id)).scalars().all()
            ai_eval = db.execute(
                select(AiEvaluation).where(AiEvaluation.application_id == app.id)
            ).scalar_one_or_none()

            # Validar que todas las preguntas requeridas están respondidas
            required_ids = db.execute(
                select(VacancyQuestion.id).where(
                    VacancyQuestion.vacancy_id == app.vacancy_id,
                    VacancyQuestion.required.is_(True),
                )
            ).scalars().all()
            answered_ids = db.execute(
                select(Answer.vacancy_question_id).where(Answer.application_id == app.id)
            ).scalars().all()
            missing = set(required_ids) - set(answered_ids)

            if missing:
                app.status = ApplicationStatus.IN_PROGRESS
                return [{"text": "Aún faltan respuestas obligatorias para completar la postulación."}]

            if not ai_eval:
                app.status = ApplicationStatus.SCORING
                return [{"text": "Procesando tu CV…"}]

            if ai_eval.status == AiEvalStatus.PENDING:
                app.status = ApplicationStatus.SCORING
                return [{"text": "Analizando tu CV, un momento…"}]

            if ai_eval.status == AiEvalStatus.FAILED:
                return self._escalate_human(db, session, "Falló la evaluación IA del CV")

            # Mapear respuestas por field_key
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

            score_rules = Decimal("0")
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
                log_event(db=db, level="DEBUG", source="scoring", event="RULE_EVAL",
                          payload={"rule": rule.name, "matched": matched}, application_id=app.id)

                if matched and rule.is_disqualifier:
                    is_disqualified = True
                    disqualification_reason = rule.name
                    break
                if matched:
                    score_rules += Decimal(rule.points)

            score_cv = Decimal(str(ai_eval.cv_score_0_10 or 0))
            classification, total = classify_candidate(vacancy, score_rules, score_cv, is_disqualified)

            app.score_rules = score_rules
            app.score_cv = score_cv
            app.score_total = total
            app.classification = classification
            app.is_disqualified = is_disqualified
            app.disqualification_reason = disqualification_reason

            status_map = {
                Classification.SHORTLIST: ApplicationStatus.SHORTLIST,
                Classification.INTERVIEW: ApplicationStatus.INTERVIEW,
                Classification.REVIEW: ApplicationStatus.REVIEW,
                Classification.REJECT: ApplicationStatus.REJECTED,
            }
            app.status = status_map[classification]

            self._transition(session, ChatState.CONFIRM_AND_CLOSE)

            log_event(db=db, level="INFO", source="scoring", event="SCORING_COMPLETE",
                      payload={"score_total": float(total), "classification": classification.value},
                      application_id=app.id)

            self._notify_top_candidates(db, app.tenant_id, app.vacancy_id)

            classification_labels = {
                Classification.SHORTLIST: "✅ Shortlist — muy buena candidatura",
                Classification.INTERVIEW: "👍 Entrevista recomendada",
                Classification.REVIEW: "🔍 En revisión por RRHH",
                Classification.REJECT: "❌ No seleccionado en esta ocasión",
            }
            return [{
                "text": (
                    f"Hemos procesado tu candidatura.\n"
                    f"Resultado: {classification_labels.get(classification, classification.value)}\n\n"
                    f"Puntuación total: {total:.1f}\n"
                    f"Escribe /start para postular a otra vacante."
                )
            }]

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

    # ─── CV Pipeline (async background task) ────────────────────────────────

    def run_cv_pipeline_async(self, tenant_id, application_id, cv_document_id):
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

                # Cargar bytes del CV
                content = cv.content
                if content is None:
                    with open(cv.storage_key, "rb") as fh:
                        content = fh.read()

                # Extraer texto
                text, parse_status = extract_cv_text(cv.extension, content)
                cv.extracted_text = text
                cv.parse_status = parse_status

                # Crear/obtener registro de evaluación IA
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

                # Llamar al LLM
                try:
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

                # Si el candidato ya terminó de responder preguntas, lanzar scoring
                if session.current_state == ChatState.SCORING:
                    outgoing = self._apply_scoring(db, app, session)
                    db.commit()
                    gateway = TelegramGateway(tenant.telegram_bot_token)
                    for msg in outgoing:
                        try:
                            gateway.send_message(session.platform_chat_id, msg["text"], msg.get("reply_markup"))
                        except Exception as send_exc:
                            log_event(db=db, level="ERROR", source="cv_pipeline", event="MSG_SEND_FAILED",
                                      message=str(send_exc), application_id=app.id)
                    return

                db.commit()
                log_event(db=db, level="INFO", source="cv_pipeline", event="PIPELINE_END",
                          application_id=app.id)

            except Exception as e:
                log_event(db=db, level="CRITICAL", source="cv_pipeline", event="PIPELINE_CRASH",
                          message=str(e), exc=e, tenant_id=tenant_id, application_id=application_id)
                db.rollback()
                raise
