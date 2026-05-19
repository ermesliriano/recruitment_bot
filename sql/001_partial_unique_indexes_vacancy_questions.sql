-- =============================================================================
-- Migración 001: Índices únicos parciales en vacancy_questions
-- =============================================================================
-- Problema: las constraints UNIQUE globales en (vacancy_id, question_order) y
-- (vacancy_id, field_key) impiden reutilizar esos valores cuando una pregunta
-- ha sido eliminada con soft-delete (is_active = false), provocando un
-- IntegrityError 500 en lugar de un error claro al crear una nueva pregunta.
--
-- Solución: reemplazar ambas constraints globales por índices únicos parciales
-- que solo aplican a las filas activas (is_active = true).
--
-- Cómo ejecutar:
--   psql -d <nombre_base_datos> -f 001_partial_unique_indexes_vacancy_questions.sql
-- =============================================================================

BEGIN;

-- 1. Eliminar las constraints UNIQUE globales
--    (PostgreSQL las nombra automáticamente con este patrón)
ALTER TABLE vacancy_questions
    DROP CONSTRAINT IF EXISTS vacancy_questions_vacancy_id_question_order_key;

ALTER TABLE vacancy_questions
    DROP CONSTRAINT IF EXISTS vacancy_questions_vacancy_id_field_key_key;

-- 2. Eliminar el índice de rendimiento antiguo sobre question_order
--    (queda obsoleto; el nuevo índice parcial lo sustituye)
DROP INDEX IF EXISTS idx_vacancy_questions_vacancy_order;

-- 3. Crear índices únicos parciales — solo aplican a filas activas
CREATE UNIQUE INDEX IF NOT EXISTS uq_vq_active_order
    ON vacancy_questions (vacancy_id, question_order)
    WHERE is_active = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_vq_active_field_key
    ON vacancy_questions (vacancy_id, field_key)
    WHERE is_active = true;

COMMIT;
