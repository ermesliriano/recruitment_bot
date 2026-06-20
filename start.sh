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

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
