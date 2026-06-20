"""
backfill_scores.py — script CLI para regularizar la puntuacion de candidaturas
atascadas SIN score_total (bug de preguntas requeridas inactivas).

NO vuelve a llamar al LLM: reutiliza la evaluacion existente. La logica vive en
app.services.score_backfill (compartida con el endpoint admin de mantenimiento).

Uso (desde la raiz del repo, con el entorno del backend activo):

    python backfill_scores.py --dry-run                 # solo informa, no escribe
    python backfill_scores.py                           # aplica a todas las atascadas
    python backfill_scores.py --tenant <TENANT_UUID>    # acota por tenant
    python backfill_scores.py --vacancy <VACANCY_UUID>  # acota por vacante
    python backfill_scores.py --application <APP_UUID>  # una sola candidatura
"""
from __future__ import annotations

import argparse

from app.core.db import SessionLocal
from app.services.score_backfill import backfill_scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill de scores de candidaturas atascadas.")
    parser.add_argument("--dry-run", action="store_true", help="No escribe; solo informa.")
    parser.add_argument("--tenant", help="Acota por tenant_id.")
    parser.add_argument("--vacancy", help="Acota por vacancy_id.")
    parser.add_argument("--application", help="Procesa una sola candidatura por id.")
    args = parser.parse_args()

    with SessionLocal() as db:
        summary = backfill_scores(
            db,
            dry_run=args.dry_run,
            tenant_id=args.tenant,
            vacancy_id=args.vacancy,
            application_id=args.application,
        )

    print(f"Candidaturas candidatas a backfill: {summary['candidates']}")
    if summary["dry_run"]:
        print("(dry-run: no se escribio nada)")
    for item in summary["items"]:
        if item["status"] == "fixed":
            print(f"  [FIX]  {item['application_id']} -> total={item['score_total']:.2f} ({item['classification']})")
        elif item["status"] == "error":
            print(f"  [ERROR] {item['application_id']}: {item['reason']}")
        else:
            print(f"  [SKIP] {item['application_id']}: {item['reason']}")
    print(f"\nResumen: {summary['fixed']} corregidas, {summary['skipped']} omitidas.")


if __name__ == "__main__":
    main()
