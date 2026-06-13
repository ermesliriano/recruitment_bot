-- 007: impedir candidaturas duplicadas por (tenant, candidato, vacante).
--
-- Contexto: ni el flujo inbound ni el outbound impedían que un mismo candidato
-- (único por teléfono) generara varias `applications` para la misma vacante.
-- Esta migración (1) limpia los duplicados ya existentes y (2) añade un índice
-- único que impide nuevos duplicados a nivel de base de datos.
--
-- Seguridad del borrado: las hijas de `applications` caen por ON DELETE CASCADE
-- (answers, cv_documents, ai_evaluations) y las sesiones quedan con
-- application_id = NULL (ON DELETE SET NULL). Si algún duplicado de origen
-- outbound estuviera referenciado por tablas de import/outbound con FK RESTRICT,
-- el DELETE fallaría: en ese caso, revisar esos duplicados manualmente.

BEGIN;

-- 1) Conservar una sola candidatura por (tenant, candidato, vacante):
--    se prioriza la que tenga puntuación (evaluada), luego la de mayor
--    puntuación, y por último la más reciente. Se borran las demás.
WITH ranked AS (
  SELECT
    id,
    ROW_NUMBER() OVER (
      PARTITION BY tenant_id, candidate_id, vacancy_id
      ORDER BY
        (score_total IS NOT NULL) DESC,
        score_total DESC NULLS LAST,
        created_at DESC
    ) AS rn
  FROM applications
)
DELETE FROM applications a
USING ranked r
WHERE a.id = r.id
  AND r.rn > 1;

-- 2) Índice único: un candidato, una candidatura por vacante.
CREATE UNIQUE INDEX IF NOT EXISTS uq_application_candidate_vacancy
  ON applications (tenant_id, candidate_id, vacancy_id);

COMMIT;

-- Comprobación posterior (no debería devolver filas):
-- SELECT tenant_id, candidate_id, vacancy_id, COUNT(*)
-- FROM applications
-- GROUP BY tenant_id, candidate_id, vacancy_id
-- HAVING COUNT(*) > 1;
