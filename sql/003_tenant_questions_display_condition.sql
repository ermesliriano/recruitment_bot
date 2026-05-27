-- sql/003_tenant_questions_display_condition.sql
-- Añade columna display_condition a tenant_questions para soporte de branching condicional.

ALTER TABLE tenant_questions
    ADD COLUMN IF NOT EXISTS display_condition JSONB NOT NULL DEFAULT '{}'::jsonb;
