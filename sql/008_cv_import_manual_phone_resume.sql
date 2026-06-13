BEGIN;

-- Conserva el binario original del CV únicamente para los ítems de importación
-- cuyo teléfono no pudo detectarse automáticamente, de modo que el reclutador
-- pueda introducir el número manualmente y reanudar el procesado sin re-subir
-- el fichero. Tras un reprocesado correcto el contenido se vuelve a poner a NULL.
ALTER TABLE cv_import_job_items
    ADD COLUMN IF NOT EXISTS raw_content BYTEA NULL;

COMMIT;
