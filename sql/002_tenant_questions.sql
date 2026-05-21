-- sql/002_tenant_questions.sql
-- Añade estado ASK_TENANT_QUESTIONS al enum, crea tabla tenant_questions
-- y amplía answers para admitir tanto vacancy_question_id como tenant_question_id.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typname = 'state_enum'
          AND e.enumlabel = 'ASK_TENANT_QUESTIONS'
    ) THEN
        ALTER TYPE state_enum ADD VALUE 'ASK_TENANT_QUESTIONS';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS tenant_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    question_order INT NOT NULL CHECK (question_order > 0),
    field_key TEXT NOT NULL,
    prompt_override TEXT,
    validation JSONB NOT NULL DEFAULT '{}'::jsonb,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    ask_before_cv BOOLEAN NOT NULL DEFAULT TRUE,
    include_in_cv_score BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_questions_tenant_order
    ON tenant_questions (tenant_id, question_order);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tq_active_order
    ON tenant_questions (tenant_id, question_order)
    WHERE is_active = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tq_active_field_key
    ON tenant_questions (tenant_id, field_key)
    WHERE is_active = TRUE;

-- Ampliar answers: añadir columna tenant_question_id y hacer vacancy_question_id nullable.
ALTER TABLE answers
    ADD COLUMN IF NOT EXISTS tenant_question_id UUID NULL REFERENCES tenant_questions(id) ON DELETE CASCADE;

ALTER TABLE answers
    ALTER COLUMN vacancy_question_id DROP NOT NULL;

-- Eliminar el UNIQUE original (application_id, vacancy_question_id) que ya no aplica globalmente.
ALTER TABLE answers
    DROP CONSTRAINT IF EXISTS answers_application_id_vacancy_question_id_key;

-- Eliminar constraint de exclusividad anterior si existe.
ALTER TABLE answers
    DROP CONSTRAINT IF EXISTS ck_answers_exactly_one_question_ref;

-- Nueva constraint: exactamente una de las dos referencias debe estar informada.
ALTER TABLE answers
    ADD CONSTRAINT ck_answers_exactly_one_question_ref
    CHECK (
        (vacancy_question_id IS NOT NULL AND tenant_question_id IS NULL)
        OR
        (vacancy_question_id IS NULL AND tenant_question_id IS NOT NULL)
    );

-- Índices únicos parciales para cada tipo de referencia.
CREATE UNIQUE INDEX IF NOT EXISTS uq_answers_application_vacancy_question
    ON answers (application_id, vacancy_question_id)
    WHERE vacancy_question_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_answers_application_tenant_question
    ON answers (application_id, tenant_question_id)
    WHERE tenant_question_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_answers_app_tenant_question
    ON answers (application_id, tenant_question_id);
