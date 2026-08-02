#!/usr/bin/env python3
"""Reprocesa evaluaciones de CV ya completadas sin contactar candidatos.

El lote se deriva de una candidatura de referencia y queda limitado al mismo
 tenant y vacante. Solo incluye candidaturas con score_total no nulo, la misma
 definición que usa el ranking para considerar una candidatura completada.

El modo por defecto es dry-run. Para escribir hay que indicar --apply y un
 --expected-count que coincida exactamente con el número encontrado.

La lógica vive en app/services/cv_reprocessing.py (compartida con el endpoint
HTTP de mantenimiento en app/routers/admin.py, pensado para entornos como
Render free tier sin acceso a Shell ni a logs en vivo).
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.db import SessionLocal
from app.services.cv_reprocessing import completed_scope, reprocess_one
from app.services.recruitment import RecruitmentService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-application-id", required=True)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    with SessionLocal() as db:
        reference, items, incomplete_count = completed_scope(
            db, args.reference_application_id
        )
        print(f"Ámbito: tenant={reference.tenant_id} vacancy={reference.vacancy_id}")
        print(f"Candidaturas completadas seleccionadas: {len(items)}")
        for item in items:
            print(
                "  - {application_id} | {candidate} | {status} | "
                "score={score_total}".format(**item)
            )
        print(f"Candidaturas incompletas excluidas automáticamente: {incomplete_count}")

    if args.expected_count is not None and len(items) != args.expected_count:
        print(
            f"ERROR: se esperaban {args.expected_count} candidaturas, "
            f"pero se encontraron {len(items)}. No se ha modificado nada.",
            file=sys.stderr,
        )
        return 2

    if not args.apply:
        print("Dry-run completado. Añade --apply para reprocesar este lote.")
        return 0

    if args.expected_count is None:
        print("ERROR: --expected-count es obligatorio cuando se usa --apply.", file=sys.stderr)
        return 2

    service = RecruitmentService()
    failures: list[tuple[str, str]] = []

    for item in items:
        application_id = item["application_id"]
        with SessionLocal() as db:
            try:
                result = reprocess_one(db, service, application_id)
                db.commit()
                print(
                    "OK {application_id} | {candidate} | {classification} | "
                    "score={score_total} | documentos={document_inventory}".format(**result)
                )
            except Exception as exc:
                db.rollback()
                failures.append((application_id, str(exc)))
                print(f"ERROR {application_id}: {exc}", file=sys.stderr)

    if failures:
        print(
            f"Finalizado con {len(failures)} error(es). Las candidaturas correctas "
            "sí quedaron actualizadas; vuelve a ejecutar para reintentar las fallidas.",
            file=sys.stderr,
        )
        return 1

    print(f"Reprocesado completado: {len(items)} candidaturas actualizadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
