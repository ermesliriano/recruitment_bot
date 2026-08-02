# app/services/cv_reprocessing.py
"""Lógica compartida de reprocesado puntual de evaluaciones de CV completadas.

Usada por:
  - scripts/reprocess_completed_cv_evaluations.py (CLI, uso local/desarrollo).
  - app/routers/admin.py, endpoints de mantenimiento (uso en Render free tier,
    donde no hay acceso a Shell ni a logs en vivo: la respuesta HTTP devuelve
    directamente lo que antes solo se veía por consola).

No es idempotente: cada ejecución vuelve a llamar al LLM y a recalcular. No debe
dispararse automáticamente en cada arranque.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cv_pipeline import extract_cv_text
from app.enums import AiEvalStatus, ApplicationStatus, Classification, SourceScope
from app.models import (
    AiEvaluation,
    Answer,
    Application,
    Candidate,
    CvDocument,
    ScoringRule,
    Tenant,
    Vacancy,
)
from app.services.recruitment import RecruitmentService
from app.services.scoring import (
    classify_candidate,
    compare_rule,
    score_answers_from_vacancy_questions,
)

STATUS_BY_CLASSIFICATION = {
    Classification.SHORTLIST: ApplicationStatus.SHORTLIST,
    Classification.INTERVIEW: ApplicationStatus.INTERVIEW,
    Classification.REVIEW: ApplicationStatus.REVIEW,
    Classification.REJECT: ApplicationStatus.REJECTED,
}


def load_cv_bytes(cv: CvDocument) -> bytes:
    if cv.content is not None:
        return bytes(cv.content)

    storage_key = (cv.storage_key or "").strip()
    if storage_key and not storage_key.startswith("db://"):
        path = Path(storage_key)
        if path.is_file():
            return path.read_bytes()

    raise RuntimeError(
        f"El fichero original del CV {cv.id} no está disponible en BD ni en disco."
    )


def completed_scope(
    db: Session, reference_application_id: str
) -> tuple[Application, list[dict[str, Any]], int]:
    """Devuelve (referencia, candidaturas completas del mismo tenant+vacante,
    nº de incompletas excluidas)."""
    reference = db.execute(
        select(Application).where(Application.id == reference_application_id)
    ).scalar_one_or_none()
    if reference is None:
        raise RuntimeError(
            f"No existe la candidatura de referencia {reference_application_id}."
        )

    rows = db.execute(
        select(Application, Candidate.full_name)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .where(
            Application.tenant_id == reference.tenant_id,
            Application.vacancy_id == reference.vacancy_id,
            Application.score_total.is_not(None),
        )
        .order_by(Application.created_at.asc())
    ).all()

    items = [
        {
            "application_id": str(app.id),
            "candidate": full_name or "(sin nombre)",
            "status": app.status.value if app.status else None,
            "classification": app.classification.value if app.classification else None,
            "score_total": float(app.score_total) if app.score_total is not None else None,
        }
        for app, full_name in rows
    ]

    incomplete_count = db.execute(
        select(Application.id).where(
            Application.tenant_id == reference.tenant_id,
            Application.vacancy_id == reference.vacancy_id,
            Application.score_total.is_(None),
        )
    ).scalars().all()

    return reference, items, len(incomplete_count)


def remove_previous_llm_prefill(db: Session, application_id) -> int:
    answers = db.execute(
        select(Answer).where(Answer.application_id == application_id)
    ).scalars().all()
    removed = 0
    for answer in answers:
        source = (answer.raw_payload or {}).get("source")
        if source == "llm_cv_prefill":
            db.delete(answer)
            removed += 1
    if removed:
        db.flush()
    return removed


def recalculate_scores(db: Session, app: Application, ai_eval: AiEvaluation) -> dict[str, Any]:
    vacancy = db.execute(select(Vacancy).where(Vacancy.id == app.vacancy_id)).scalar_one()
    candidate = db.execute(select(Candidate).where(Candidate.id == app.candidate_id)).scalar_one()
    answers = db.execute(select(Answer).where(Answer.application_id == app.id)).scalars().all()
    rules = db.execute(
        select(ScoringRule)
        .where(ScoringRule.vacancy_id == app.vacancy_id, ScoringRule.is_active.is_(True))
        .order_by(ScoringRule.priority.asc())
    ).scalars().all()

    answer_map: dict[str, Any] = {}
    for answer in answers:
        if answer.answer_boolean is not None:
            answer_map[answer.field_key] = answer.answer_boolean
        elif answer.answer_number is not None:
            answer_map[answer.field_key] = answer.answer_number
        else:
            answer_map[answer.field_key] = answer.answer_text or ""

    question_score = score_answers_from_vacancy_questions(db=db, app=app, answers=answers)
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
        if matched and rule.source_scope != SourceScope.ANSWER:
            rule_score += Decimal(rule.points)

    score_rules = question_score + rule_score
    score_cv_raw = Decimal(str(ai_eval.cv_score_0_10 or 0))
    classification, total, score_cv_normalized = classify_candidate(
        vacancy, score_rules, score_cv_raw, is_disqualified
    )

    app.score_rules = score_rules
    app.score_cv = score_cv_normalized
    app.score_total = total
    app.classification = classification
    app.is_disqualified = is_disqualified
    app.disqualification_reason = disqualification_reason
    app.status = STATUS_BY_CLASSIFICATION[classification]

    return {
        "score_rules": float(score_rules),
        "score_cv": float(score_cv_normalized),
        "score_total": float(total),
        "classification": classification.value,
    }


def reprocess_one(db: Session, service: RecruitmentService, application_id: str) -> dict[str, Any]:
    app = db.execute(select(Application).where(Application.id == application_id)).scalar_one()
    if app.score_total is None:
        raise RuntimeError("La candidatura está incompleta y no se reprocesará.")

    tenant = db.execute(select(Tenant).where(Tenant.id == app.tenant_id)).scalar_one()
    vacancy = db.execute(select(Vacancy).where(Vacancy.id == app.vacancy_id)).scalar_one()
    candidate = db.execute(select(Candidate).where(Candidate.id == app.candidate_id)).scalar_one()
    cv = db.execute(
        select(CvDocument)
        .where(CvDocument.application_id == app.id)
        .order_by(CvDocument.version.desc(), CvDocument.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if cv is None:
        raise RuntimeError("La candidatura completada no tiene CV registrado.")

    content = load_cv_bytes(cv)
    text, parse_status = extract_cv_text(cv.extension, content)
    cv.extracted_text = text
    cv.parse_status = parse_status

    ai_eval = db.execute(
        select(AiEvaluation)
        .where(AiEvaluation.cv_document_id == cv.id)
        .order_by(AiEvaluation.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if ai_eval is None:
        ai_eval = AiEvaluation(
            tenant_id=tenant.id,
            application_id=app.id,
            cv_document_id=cv.id,
            status=AiEvalStatus.PENDING,
        )
        db.add(ai_eval)
        db.flush()

    vacancy_questions = service._questions_for_llm(db, vacancy.id)
    tenant_answers = service._tenant_answers_for_llm(db, app)
    payload, raw, latency_ms = service.llm.evaluate_cv(
        {
            "title": vacancy.title,
            "description": vacancy.description,
            "mandatory_requirements": vacancy.mandatory_requirements,
            "desirable_requirements": vacancy.desirable_requirements,
            "location_text": vacancy.location_text,
            "schedule_text": vacancy.schedule_text,
        },
        text,
        vacancy_questions=vacancy_questions,
        tenant_screening_answers=tenant_answers,
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
    ai_eval.error_message = None
    ai_eval.attempts = (ai_eval.attempts or 0) + 1

    if payload.candidate_full_name and not (candidate.full_name or "").strip():
        candidate.full_name = payload.candidate_full_name.strip()[:120]

    removed_prefill = remove_previous_llm_prefill(db, app.id)
    created_prefill = service._prefill_answers_from_cv(
        db=db,
        tenant_id=tenant.id,
        app=app,
        inferred_answers=payload.answered_vacancy_questions,
    )
    scoring = recalculate_scores(db, app, ai_eval)

    return {
        "application_id": str(app.id),
        "candidate": candidate.full_name or "(sin nombre)",
        "cv_document_id": str(cv.id),
        "parse_status": parse_status.value,
        "extracted_chars": len(text or ""),
        "document_inventory": payload.document_inventory,
        "removed_llm_prefill": removed_prefill,
        "created_llm_prefill": created_prefill,
        "llm_latency_ms": latency_ms,
        **scoring,
    }
