--sql/schema.sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

 CREATE TYPE platform_enum AS ENUM ('TELEGRAM', 'WHATSAPP');
CREATE TYPE vacancy_status_enum AS ENUM ('DRAFT', 'ACTIVE', 'ARCHIVED');
CREATE TYPE answer_type_enum AS ENUM ('TEXT', 'BOOLEAN', 'NUMBER');
CREATE TYPE scoring_operator_enum AS ENUM ('EQUALS', 'CONTAINS', 'GTE');
CREATE TYPE source_scope_enum AS ENUM ('ANSWER', 'CANDIDATE', 'AI');
CREATE TYPE application_status_enum AS ENUM (
  'DRAFT', 'IN_PROGRESS', 'PENDING_AI', 'SCORING',
  'REVIEW', 'INTERVIEW', 'SHORTLIST',
  'REJECTED', 'NEEDS_HUMAN', 'CLOSED'
);
CREATE TYPE classification_enum AS ENUM ('REJECT', 'REVIEW', 'INTERVIEW', 'SHORTLIST');
CREATE TYPE state_enum AS ENUM (
  'WELCOME',
  'SELECT_VACANCY',
  'CAPTURE_NAME',
  'VACANCY_QA_MODE',
  'REQUEST_CV',
  'ASK_VACANCY_QUESTIONS',
  'SCORING',
  'CONFIRM_AND_CLOSE',
  'ESCALATE_HUMAN'
);
CREATE TYPE cv_parse_status_enum AS ENUM ('PENDING', 'PARSED', 'OCR_FALLBACK', 'FAILED', 'UNSUPPORTED');
CREATE TYPE ai_eval_status_enum AS ENUM ('PENDING', 'SUCCESS', 'FAILED');
CREATE TYPE storage_backend_enum AS ENUM ('DB_BLOB', 'LOCAL_FS', 'S3');

CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'Europe/Madrid',
  locale TEXT NOT NULL DEFAULT 'es',
  hr_email TEXT,
  telegram_bot_token TEXT,
  telegram_webhook_secret TEXT,
  settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vacancies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  responsibilities TEXT[] NOT NULL DEFAULT '{}'::text[],
  mandatory_requirements TEXT[] NOT NULL DEFAULT '{}'::text[],
  desirable_requirements TEXT[] NOT NULL DEFAULT '{}'::text[],
  salary_text TEXT,
  schedule_text TEXT,
  location_text TEXT,
  benefits TEXT[] NOT NULL DEFAULT '{}'::text[],
  faq_context JSONB NOT NULL DEFAULT '{"items":[]}'::jsonb,
  cv_score_factor NUMERIC(6,2) NOT NULL DEFAULT 6.00,
  classification_thresholds JSONB NOT NULL DEFAULT '{"review":35,"interview":60,"shortlist":75}'::jsonb,
  status vacancy_status_enum NOT NULL DEFAULT 'DRAFT',
  opens_at TIMESTAMPTZ,
  closes_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code)
);

CREATE TABLE questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  answer_type answer_type_enum NOT NULL,
  default_validation JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code)
);

CREATE TABLE vacancy_questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  vacancy_id UUID NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
  question_id UUID NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
  question_order INT NOT NULL CHECK (question_order > 0),
  field_key TEXT NOT NULL,
  prompt_override TEXT,
  validation JSONB NOT NULL DEFAULT '{}'::jsonb,
  required BOOLEAN NOT NULL DEFAULT TRUE,
  scoring_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (vacancy_id, question_order),
  UNIQUE (vacancy_id, field_key)
);

CREATE TABLE scoring_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  vacancy_id UUID NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  source_scope source_scope_enum NOT NULL DEFAULT 'ANSWER',
  field_key TEXT NOT NULL,
  operator scoring_operator_enum NOT NULL,
  expected_text TEXT,
  expected_number NUMERIC(12,2),
  expected_boolean BOOLEAN,
  points INT NOT NULL DEFAULT 0,
  is_disqualifier BOOLEAN NOT NULL DEFAULT FALSE,
  stop_on_match BOOLEAN NOT NULL DEFAULT FALSE,
  priority INT NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  phone_e164 TEXT NOT NULL,
  full_name TEXT,
  email TEXT,
  location_text TEXT,
  telegram_chat_id BIGINT,
  telegram_user_id BIGINT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, phone_e164)
);

CREATE TABLE applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  candidate_id UUID NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  vacancy_id UUID NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
  status application_status_enum NOT NULL DEFAULT 'DRAFT',
  score_rules NUMERIC(8,2) NOT NULL DEFAULT 0,
  score_cv NUMERIC(4,2),
  score_total NUMERIC(8,2),
  classification classification_enum,
  is_disqualified BOOLEAN NOT NULL DEFAULT FALSE,
  disqualification_reason TEXT,
  submitted_at TIMESTAMPTZ,
  reviewed_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE answers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  vacancy_question_id UUID NOT NULL REFERENCES vacancy_questions(id) ON DELETE CASCADE,
  field_key TEXT NOT NULL,
  answer_text TEXT,
  answer_number NUMERIC(12,2),
  answer_boolean BOOLEAN,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_valid BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (application_id, vacancy_question_id)
);

CREATE TABLE cv_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  version INT NOT NULL CHECK (version > 0),
  original_filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  extension TEXT NOT NULL,
  size_bytes INT NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 20971520),
  sha256 TEXT NOT NULL,
  telegram_file_id TEXT,
  telegram_file_unique_id TEXT,
  storage_backend storage_backend_enum NOT NULL DEFAULT 'DB_BLOB',
  storage_key TEXT NOT NULL,
  content BYTEA,
  extracted_text TEXT,
  parse_status cv_parse_status_enum NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (application_id, version)
);

CREATE TABLE ai_evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  cv_document_id UUID NOT NULL REFERENCES cv_documents(id) ON DELETE CASCADE,
  llm_provider TEXT NOT NULL DEFAULT 'apifreellm',
  model_name TEXT NOT NULL DEFAULT 'apifreellm',
  status ai_eval_status_enum NOT NULL DEFAULT 'PENDING',
  raw_response TEXT,
  parsed_json JSONB,
  candidate_profile JSONB,
  experience_summary JSONB,
  skills JSONB,
  red_flags JSONB,
  cv_score_0_10 NUMERIC(4,2),
  recommendation TEXT,
  error_message TEXT,
  attempts INT NOT NULL DEFAULT 0,
  latency_ms INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (cv_document_id)
);

CREATE TABLE conversation_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  platform platform_enum NOT NULL DEFAULT 'TELEGRAM',
  platform_chat_id BIGINT NOT NULL,
  platform_user_id BIGINT,
  candidate_id UUID REFERENCES candidates(id) ON DELETE SET NULL,
  application_id UUID REFERENCES applications(id) ON DELETE SET NULL,
  current_state state_enum NOT NULL DEFAULT 'WELCOME',
  state_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_incoming_update_id BIGINT,
  last_bot_message_id BIGINT,
  invalid_input_count INT NOT NULL DEFAULT 0,
  version INT NOT NULL DEFAULT 1,
  last_user_message_at TIMESTAMPTZ,
  last_bot_message_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_vacancies_tenant_status ON vacancies (tenant_id, status, opens_at, closes_at);
CREATE INDEX idx_vacancies_faq_context_gin ON vacancies USING GIN (faq_context);

CREATE INDEX idx_questions_tenant_active ON questions (tenant_id, is_active);
CREATE INDEX idx_vacancy_questions_vacancy_order ON vacancy_questions (vacancy_id, question_order);
CREATE INDEX idx_scoring_rules_vacancy_priority ON scoring_rules (vacancy_id, priority, is_active);

CREATE INDEX idx_candidates_tenant_phone ON candidates (tenant_id, phone_e164);
CREATE INDEX idx_candidates_tg_chat ON candidates (tenant_id, telegram_chat_id);
CREATE UNIQUE INDEX uq_candidates_tg_user ON candidates (tenant_id, telegram_user_id) WHERE telegram_user_id IS NOT NULL;

CREATE INDEX idx_applications_vacancy_ranking ON applications (tenant_id, vacancy_id, score_total DESC NULLS LAST);
CREATE INDEX idx_applications_candidate ON applications (tenant_id, candidate_id);

CREATE INDEX idx_answers_app_field_key ON answers (application_id, field_key);
CREATE INDEX idx_cv_documents_application ON cv_documents (application_id, version DESC);
CREATE INDEX idx_ai_evaluations_application ON ai_evaluations (application_id, status);

CREATE UNIQUE INDEX uq_active_conversation_session
  ON conversation_sessions (tenant_id, platform, platform_chat_id)
  WHERE is_active = TRUE;

CREATE INDEX idx_conversation_state ON conversation_sessions (tenant_id, current_state);
CREATE INDEX idx_conversation_payload_gin ON conversation_sessions USING GIN (state_payload);

CREATE VIEW application_ranking_view AS
SELECT
  a.id AS application_id,
  a.tenant_id,
  c.full_name AS nombre,
  c.phone_e164 AS telefono,
  v.title AS vacante,
  a.score_rules,
  a.score_cv,
  a.score_total,
  a.classification AS estado,
  a.status,
  a.created_at
FROM applications a
JOIN candidates c ON c.id = a.candidate_id
JOIN vacancies v ON v.id = a.vacancy_id;
