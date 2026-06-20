# app/services/score_backfill.py
"""
Logica de backfill de scores para candidaturas atascadas SIN score_total.

Reutiliza la MISMA logica que RecruitmentService._apply_scoring (sin volver a
llamar al LLM: reaprovecha ai_eval.cv_score_0_10). La usan tanto el script CLI
backfill_scores.py como el endpoint admin de mantenimiento.

Una candidatura es candidata a backfill si tiene una AiEvaluation SUCCESS y
score_total IS NULL. Solo se puntua si todas las preguntas obligatorias ACTIVAS
(de vacante y de tenant) estan respondidas.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import AiEvalStatus, ApplicationStatus, Classification, SourceScope
from app.models import (
    AiEvaluation,
    Answer,
    Application,
    Candidate,
    ScoringRule,
    Vacancy,
    VacancyQuestion,
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


def _latest_success_eval(db: Session, application_id):
    return db.execute(
        select(AiEvaluation)
        .where(
            AiEvaluation.application_id == application_id,
            AiEvaluation.status == AiEvalStatus.SUCCESS,
        )
        .order_by(AiEvaluation.created_at.desc())
    ).scalars().first()


def _required_questions_pending(db: Session, svc: RecruitmentService, app: Application) -> bool:
    """Replica los guards de _apply_scoring (con el filtro is_active corregido)."""
    required_ids = db.execute(
        select(VacancyQuestion.id).where(
            VacancyQuestion.vacancy_id == app.vacancy_id,
            VacancyQuestion.required.is_(True),
            VacancyQuestion.is_active.is_(True),
        )
    ).scalars().all()
    answered_ids = db.execute(
        select(Answer.vacancy_question_id).where(Answer.application_id == app.id)
    ).scalars().all()
    if set(required_ids) - set(answered_ids):
        return True

    tenant_questions = svc._get_ordered_tenant_questions(db, app.tenant_id)
    answers_by_field = svc._tenant_answer_map(db, app.id)
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
        for tq, _q in tenant_questions
        if tq.required
        and tq.is_active
        and tq.ask_before_cv
        and svc._matches_display_condition(tq.display_condition, answers_by_field)
    ]
    return bool(set(required_tenant_ids) - answered_tenant_ids)


def _recompute_application(db: Session, svc: RecruitmentService, app: Application) -> dict:
    """Recalcula y asigna (sin commit) el score de una candidatura."""
    vacancy = db.execute(select(Vacancy).where(Vacancy.id == app.vacancy_id)).scalar_one()
    answers = db.execute(select(Answer).where(Answer.application_id == app.id)).scalars().all()
    ai_eval = _latest_success_eval(db, app.id)

    if ai_eval is None:
        return {"status": "skipped", "reason": "sin evaluacion IA SUCCESS"}

    if _required_questions_pending(db, svc, app):
        return {"status": "skipped", "reason": "faltan respuestas obligatorias activas"}

    answer_map: dict = {}
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
        "status": "fixed",
        "score_rules": float(score_rules),
        "score_cv": float(score_cv_normalized),
        "score_total": float(total),
        "classification": classification.value,
    }


def backfill_scores(
    db: Session,
    *,
    dry_run: bool = True,
    tenant_id: str | None = None,
    vacancy_id: str | None = None,
    application_id: str | None = None,
) -> dict:
    """Recorre las candidaturas atascadas y recalcula su score.

    Con dry_run=True no persiste nada (hace rollback por item). Devuelve un
    resumen con el detalle por candidatura.
    """
    svc = RecruitmentService()

    stmt = (
        select(Application.id)
        .join(AiEvaluation, AiEvaluation.application_id == Application.id)
        .where(
            Application.score_total.is_(None),
            AiEvaluation.status == AiEvalStatus.SUCCESS,
        )
        .distinct()
    )
    if application_id:
        stmt = stmt.where(Application.id == application_id)
    if tenant_id:
        stmt = stmt.where(Application.tenant_id == tenant_id)
    if vacancy_id:
        stmt = stmt.where(Application.vacancy_id == vacancy_id)

    app_ids = db.execute(stmt).scalars().all()

    fixed = 0
    skipped = 0
    items: list[dict] = []

    for app_id in app_ids:
        app = db.execute(select(Application).where(Application.id == app_id)).scalar_one()
        try:
            result = _recompute_application(db, svc, app)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            skipped += 1
            items.append({"application_id": str(app_id), "status": "error", "reason": str(exc)})
            continue

        if result["status"] == "fixed":
            fixed += 1
            if dry_run:
                db.rollback()
            else:
                db.commit()
        else:
            skipped += 1
            db.rollback()

        items.append({"application_id": str(app_id), **result})

    return {
        "dry_run": dry_run,
        "candidates": len(app_ids),
        "fixed": fixed,
        "skipped": skipped,
        "items": items,
    }
