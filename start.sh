#!/bin/sh
# Punto de arranque del contenedor.
#
# Si la variable RUN_BACKFILL esta definida, ejecuta el backfill de scores ANTES
# de arrancar el servidor. Pensado para Render free tier (sin acceso a consola):
#
#   RUN_BACKFILL=dry  -> ejecuta en seco (solo informa en los logs, no escribe)
#   RUN_BACKFILL=1    -> aplica los cambios en la base de datos
#
# IMPORTANTE: quita la variable (o ponla a 0) despues de usarla, para que el
# backfill no se repita en cada arranque/cold-start del servicio. Es idempotente
# (solo toca candidaturas con score_total NULL), asi que un reintento es inocuo,
# pero no tiene sentido ejecutarlo en cada reinicio.

if [ "${RUN_BACKFILL}" = "dry" ]; then
  echo "[start] RUN_BACKFILL=dry -> python backfill_scores.py --dry-run"
  python backfill_scores.py --dry-run || echo "[start] backfill (dry-run) fallo; continuo arrancando"
elif [ "${RUN_BACKFILL}" = "1" ]; then
  echo "[start] RUN_BACKFILL=1 -> python backfill_scores.py (aplicando)"
  python backfill_scores.py || echo "[start] backfill fallo; continuo arrancando"
fi

# Reprocesado puntual de evaluaciones de CV completadas (mismo patron que el
# backfill de arriba). NO es idempotente: cada ejecucion vuelve a llamar al LLM
# y a recalcular, asi que hay que RETIRAR estas variables de Render en cuanto
# termine, o se repetiria en cada cold-start/redeploy.
#
#   REPROCESS_REFERENCE_APPLICATION_ID=<uuid>  -> obligatoria; una candidatura
#     cualquiera del lote (fija tenant + vacante). Sin REPROCESS_APPLY, solo
#     lista el lote encontrado (dry-run) en los logs.
#   REPROCESS_APPLY=1                          -> aplica de verdad.
#   REPROCESS_EXPECTED_COUNT=<n>                -> obligatoria junto con
#     REPROCESS_APPLY; debe coincidir exactamente con el numero encontrado, si
#     no el script aborta sin tocar nada.
if [ -n "${REPROCESS_REFERENCE_APPLICATION_ID}" ]; then
  if [ "${REPROCESS_APPLY}" = "1" ]; then
    echo "[start] REPROCESS_APPLY=1 -> reprocesando lote (ref=${REPROCESS_REFERENCE_APPLICATION_ID}, esperado=${REPROCESS_EXPECTED_COUNT})"
    python scripts/reprocess_completed_cv_evaluations.py \
      --reference-application-id "${REPROCESS_REFERENCE_APPLICATION_ID}" \
      --expected-count "${REPROCESS_EXPECTED_COUNT:-0}" \
      --apply || echo "[start] reprocesado fallo; continuo arrancando"
  else
    echo "[start] REPROCESS_REFERENCE_APPLICATION_ID definido sin REPROCESS_APPLY -> dry-run"
    python scripts/reprocess_completed_cv_evaluations.py \
      --reference-application-id "${REPROCESS_REFERENCE_APPLICATION_ID}" || echo "[start] dry-run fallo; continuo arrancando"
  fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
