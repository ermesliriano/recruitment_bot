"""
backfill_scores.py

Patch puntual para regularizar la puntuacion de candidaturas que quedaron
atascadas SIN score_total por el bug de preguntas requeridas inactivas
(una pregunta required + soft-deleted bloqueaba _apply_scoring y dejaba la
aplicacion en IN_PROGRESS aunque el CV ya estuviera evaluado).

Este script NO vuelve a llamar al LLM: reutiliza la evaluacion existente
(ai_eval.cv_score_0_10) y recalcula score_rules / score_cv / score_total /
classification con la MISMA logica que RecruitmentService._apply_scoring.

Uso (desde la raiz del repo, con el entorno del backend activo):

    python backfill_scores.py --dry-run                # solo informa, no escribe
    python backfill_scores.py                          # aplica a todas las atascadas
    python backfill_scores.py --tenant <TENANT_UUID>   # acota por tenant
    python backfill_scores.py --vacancy <VACANCY_UUID> # acota por vacante
    python backfill_scores.py --application <APP_UUID>  # una sola candidatura

Una candidatura se considera "atascada" si tiene una AiEvaluation SUCCESS y
score_total IS NULL. Solo se puntua si todas las preguntas obligatorias ACTIVAS
(de vacante y de tenant) estan respondidas; si el candidato no completo el
flujo, se omite y se informa.
"""
from __future__ import annotations

import argparse
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal
from app.enums import (
    AiEvalStatus,
    ApplicationStatus,
    Classification,
    SourceScope,
)
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


def _latest_success_eval(db, application_id):
    return db.execute(
        select(AiEvaluation)
        .where(
            AiEvaluation.application_id == application_id,
            AiEvaluation.status == AiEvalStatus.SUCCESS,
        )
        .order_by(AiEvaluation.created_at.desc())
    ).scalars().first()


def _required_questions_pending(db, svc: RecruitmentService, app: Application) -> bool:
    """Replica los guards de _apply_scoring (con el filtro is_active ya corregido)."""
    # Preguntas de vacante requeridas y ACTIVAS.
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

    # Preguntas de tenant requeridas (ask_before_cv, activas y visibles).
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


def _recompute_application(db, svc: RecruitmentService, app: Application) -> dict:
    """Recalcula y persiste el score de una candidatura. Devuelve un resumen."""
    vacancy = db.execute(select(Vacancy).where(Vacancy.id == app.vacancy_id)).scalar_one()
    answers = db.execute(select(Answer).where(Answer.application_id == app.id)).scalars().all()
    ai_eval = _latest_success_eval(db, app.id)

    if ai_eval is None:
        return {"status": "skipped", "reason": "sin evaluacion IA SUCCESS"}

    if _required_questions_pending(db, svc, app):
        return {"status": "skipped", "reason": "faltan respuestas obligatorias activas"}

    answer_map = {}
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill de scores de candidaturas atascadas.")
    parser.add_argument("--dry-run", action="store_true", help="No escribe; solo informa.")
    parser.add_argument("--tenant", help="Acota por tenant_id.")
    parser.add_argument("--vacancy", help="Acota por vacancy_id.")
    parser.add_argument("--application", help="Procesa una sola candidatura por id.")
    args = parser.parse_args()

    svc = RecruitmentService()

    with SessionLocal() as db:
        # Candidaturas con evaluacion IA SUCCESS pero sin score_total.
        stmt = (
            select(Application.id)
            .join(AiEvaluation, AiEvaluation.application_id == Application.id)
            .where(
                Application.score_total.is_(None),
                AiEvaluation.status == AiEvalStatus.SUCCESS,
            )
            .distinct()
        )
        if args.application:
            stmt = stmt.where(Application.id == args.application)
        if args.tenant:
            stmt = stmt.where(Application.tenant_id == args.tenant)
        if args.vacancy:
            stmt = stmt.where(Application.vacancy_id == args.vacancy)

        app_ids = db.execute(stmt).scalars().all()

        print(f"Candidaturas candidatas a backfill: {len(app_ids)}")
        if args.dry_run:
            print("(dry-run: no se escribira nada)\n")

        fixed = 0
        skipped = 0
        for app_id in app_ids:
            app = db.execute(select(Application).where(Application.id == app_id)).scalar_one()
            try:
                result = _recompute_application(db, svc, app)
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                print(f"  [ERROR] {app_id}: {exc}")
                db.rollback()
                continue

            if result["status"] == "fixed":
                fixed += 1
                print(
                    f"  [FIX]  {app_id} -> total={result['score_total']:.2f} "
                    f"({result['classification']})"
                )
                if args.dry_run:
                    db.rollback()
                else:
                    db.commit()
            else:
                skipped += 1
                print(f"  [SKIP] {app_id}: {result['reason']}")
                db.rollback()

        print(f"\nResumen: {fixed} corregidas, {skipped} omitidas.")


if __name__ == "__main__":
    main()
