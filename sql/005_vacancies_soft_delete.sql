-- sql/005_vacancies_soft_delete.sql
-- Añade la columna deleted_at usada por el patrón soft-delete de vacancies.
-- El modelo ORM (app/models/vacancy.py) y VacancyService dependen de ella:
--   - list_vacancies / get_vacancy filtran WHERE deleted_at IS NULL
--   - delete_vacancy marca deleted_at en lugar de borrar la fila
--   - create_vacancy hace db.refresh(), que selecciona todas las columnas
-- Sin esta columna, cualquier consulta ORM sobre vacancies falla con
-- "column vacancies.deleted_at does not exist" (HTTP 500).

BEGIN;

ALTER TABLE vacancies
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

-- Índice parcial opcional: acelera el filtrado de vacantes vivas por tenant.
CREATE INDEX IF NOT EXISTS idx_vacancies_tenant_not_deleted
    ON vacancies (tenant_id)
    WHERE deleted_at IS NULL;

COMMIT;
