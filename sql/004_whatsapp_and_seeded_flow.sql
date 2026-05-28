BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typname = 'application_status_enum'
          AND e.enumlabel = 'WAITING_CANDIDATE_REPLY'
    ) THEN
        ALTER TYPE application_status_enum ADD VALUE 'WAITING_CANDIDATE_REPLY';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typname = 'application_status_enum'
          AND e.enumlabel = 'BLOCKED_NO_OPT_IN'
    ) THEN
        ALTER TYPE application_status_enum ADD VALUE 'BLOCKED_NO_OPT_IN';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typname = 'state_enum'
          AND e.enumlabel = 'WAITING_CANDIDATE_REPLY'
    ) THEN
        ALTER TYPE state_enum ADD VALUE 'WAITING_CANDIDATE_REPLY';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'application_origin_enum') THEN
        CREATE TYPE application_origin_enum AS ENUM (
            'INBOUND_TELEGRAM',
            'INBOUND_WHATSAPP',
            'RECRUITER_UPLOAD'
        );
    END IF;
END $$;

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS whatsapp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS whatsapp_use_env_credentials BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS whatsapp_messaging_service_sid TEXT NULL,
    ADD COLUMN IF NOT EXISTS whatsapp_sender_address TEXT NULL,
    ADD COLUMN IF NOT EXISTS whatsapp_initial_template_sid TEXT NULL,
    ADD COLUMN IF NOT EXISTS whatsapp_initial_template_language TEXT NOT NULL DEFAULT 'es',
    ADD COLUMN IF NOT EXISTS whatsapp_assume_opt_in BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS whatsapp_wa_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS whatsapp_from TEXT NULL,
    ADD COLUMN IF NOT EXISTS whatsapp_profile_name TEXT NULL,
    ADD COLUMN IF NOT EXISTS whatsapp_opt_in_status TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS whatsapp_opt_in_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS last_inbound_whatsapp_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_candidates_wa_id ON candidates (tenant_id, whatsapp_wa_id);

ALTER TABLE applications
    ADD COLUMN IF NOT EXISTS origin application_origin_enum NOT NULL DEFAULT 'INBOUND_TELEGRAM',
    ADD COLUMN IF NOT EXISTS preferred_platform platform_enum NULL;

ALTER TABLE cv_documents
    RENAME COLUMN telegram_file_id TO source_file_id;

ALTER TABLE cv_documents
    RENAME COLUMN telegram_file_unique_id TO source_file_unique_id;

ALTER TABLE cv_documents
    ADD COLUMN IF NOT EXISTS source_platform platform_enum NULL,
    ADD COLUMN IF NOT EXISTS source_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE cv_documents
SET source_platform = 'TELEGRAM'
WHERE source_platform IS NULL AND source_file_id IS NOT NULL;

DROP INDEX IF EXISTS uq_active_conversation_session;
DROP INDEX IF EXISTS idx_conversation_state;

ALTER TABLE conversation_sessions
    ALTER COLUMN platform_chat_id TYPE TEXT USING platform_chat_id::text,
    ALTER COLUMN platform_user_id TYPE TEXT USING platform_user_id::text,
    ALTER COLUMN last_bot_message_id TYPE TEXT USING last_bot_message_id::text;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'conversation_sessions'
          AND column_name = 'last_incoming_update_id'
    ) THEN
        ALTER TABLE conversation_sessions RENAME COLUMN last_incoming_update_id TO last_incoming_event_id;
    END IF;
END $$;

ALTER TABLE conversation_sessions
    ALTER COLUMN last_incoming_event_id TYPE TEXT USING last_incoming_event_id::text;

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_conversation_session
  ON conversation_sessions (tenant_id, platform, platform_chat_id)
  WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_conversation_state ON conversation_sessions (tenant_id, current_state);
CREATE INDEX IF NOT EXISTS idx_conversation_platform_chat ON conversation_sessions (tenant_id, platform, platform_chat_id);

CREATE TABLE IF NOT EXISTS outbound_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    candidate_id UUID NULL REFERENCES candidates(id) ON DELETE SET NULL,
    application_id UUID NULL REFERENCES applications(id) ON DELETE SET NULL,
    conversation_session_id UUID NULL REFERENCES conversation_sessions(id) ON DELETE SET NULL,
    channel platform_enum NOT NULL,
    provider TEXT NOT NULL DEFAULT 'internal',
    to_address TEXT NOT NULL,
    template_sid TEXT NULL,
    content_text TEXT NULL,
    content_variables JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    provider_message_sid TEXT NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ NULL,
    delivered_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_outbound_messages_app ON outbound_messages (application_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_status ON outbound_messages (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_provider_sid ON outbound_messages (provider_message_sid);

CREATE TABLE IF NOT EXISTS cv_import_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    vacancy_id UUID NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    requested_by TEXT NULL,
    total_files INT NOT NULL DEFAULT 0,
    processed_files INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'created',
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_cv_import_jobs_tenant ON cv_import_jobs (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cv_import_job_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES cv_import_jobs(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    candidate_id UUID NULL REFERENCES candidates(id) ON DELETE SET NULL,
    application_id UUID NULL REFERENCES applications(id) ON DELETE SET NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NULL,
    size_bytes INT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    outbound_status TEXT NULL,
    extraction_status TEXT NULL,
    detected_phone_e164 TEXT NULL,
    phone_confidence NUMERIC(4,2) NULL,
    phone_candidates_json JSONB NULL,
    extracted_preview TEXT NULL,
    candidate_reused BOOLEAN NOT NULL DEFAULT FALSE,
    application_reused BOOLEAN NOT NULL DEFAULT FALSE,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cv_import_job_items_job ON cv_import_job_items (job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_cv_import_job_items_status ON cv_import_job_items (tenant_id, status);

COMMIT;
