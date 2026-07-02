--
-- PostgreSQL database dump
--

\restrict 2FVwqoc7hxFPUBYXmIDCBn7LgZkYJE3wAmNUjCcr0cXj8a65TVFRiJSH4QJzPgL

-- Dumped from database version 18.4 (Debian 18.4-1.pgdg12+1)
-- Dumped by pg_dump version 18.4 (Debian 18.4-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: ai_eval_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.ai_eval_status_enum AS ENUM (
    'PENDING',
    'SUCCESS',
    'FAILED'
);


--
-- Name: answer_type_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.answer_type_enum AS ENUM (
    'TEXT',
    'BOOLEAN',
    'NUMBER'
);


--
-- Name: application_origin_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.application_origin_enum AS ENUM (
    'INBOUND_TELEGRAM',
    'INBOUND_WHATSAPP',
    'RECRUITER_UPLOAD'
);


--
-- Name: application_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.application_status_enum AS ENUM (
    'DRAFT',
    'IN_PROGRESS',
    'PENDING_AI',
    'SCORING',
    'REVIEW',
    'INTERVIEW',
    'SHORTLIST',
    'REJECTED',
    'NEEDS_HUMAN',
    'CLOSED',
    'WAITING_CANDIDATE_REPLY',
    'BLOCKED_NO_OPT_IN'
);


--
-- Name: classification_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.classification_enum AS ENUM (
    'REJECT',
    'REVIEW',
    'INTERVIEW',
    'SHORTLIST'
);


--
-- Name: cv_parse_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.cv_parse_status_enum AS ENUM (
    'PENDING',
    'PARSED',
    'OCR_FALLBACK',
    'FAILED',
    'UNSUPPORTED'
);


--
-- Name: platform_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.platform_enum AS ENUM (
    'TELEGRAM',
    'WHATSAPP'
);


--
-- Name: scoring_operator_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.scoring_operator_enum AS ENUM (
    'EQUALS',
    'CONTAINS',
    'GTE'
);


--
-- Name: source_scope_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.source_scope_enum AS ENUM (
    'ANSWER',
    'CANDIDATE',
    'AI'
);


--
-- Name: state_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.state_enum AS ENUM (
    'WELCOME',
    'SELECT_VACANCY',
    'CAPTURE_NAME',
    'VACANCY_QA_MODE',
    'ASK_TENANT_QUESTIONS',
    'REQUEST_CV',
    'ASK_VACANCY_QUESTIONS',
    'SCORING',
    'CONFIRM_AND_CLOSE',
    'ESCALATE_HUMAN',
    'WAITING_CANDIDATE_REPLY'
);


--
-- Name: storage_backend_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.storage_backend_enum AS ENUM (
    'DB_BLOB',
    'LOCAL_FS',
    'S3'
);


--
-- Name: vacancy_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.vacancy_status_enum AS ENUM (
    'DRAFT',
    'ACTIVE',
    'ARCHIVED'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ai_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_evaluations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    application_id uuid NOT NULL,
    cv_document_id uuid NOT NULL,
    llm_provider text DEFAULT 'apifreellm'::text NOT NULL,
    model_name text DEFAULT 'apifreellm'::text NOT NULL,
    status public.ai_eval_status_enum DEFAULT 'PENDING'::public.ai_eval_status_enum NOT NULL,
    raw_response text,
    parsed_json jsonb,
    candidate_profile jsonb,
    experience_summary jsonb,
    skills jsonb,
    red_flags jsonb,
    cv_score_0_10 numeric(4,2),
    recommendation text,
    error_message text,
    attempts integer DEFAULT 0 NOT NULL,
    latency_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: answers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.answers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    application_id uuid NOT NULL,
    vacancy_question_id uuid,
    tenant_question_id uuid,
    field_key text NOT NULL,
    answer_text text,
    answer_number numeric(12,2),
    answer_boolean boolean,
    raw_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_valid boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_answers_exactly_one_question_ref CHECK ((((vacancy_question_id IS NOT NULL) AND (tenant_question_id IS NULL)) OR ((vacancy_question_id IS NULL) AND (tenant_question_id IS NOT NULL))))
);


--
-- Name: applications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.applications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    vacancy_id uuid NOT NULL,
    status public.application_status_enum DEFAULT 'DRAFT'::public.application_status_enum NOT NULL,
    score_rules numeric(8,2) DEFAULT 0 NOT NULL,
    score_cv numeric(4,2),
    score_total numeric(8,2),
    classification public.classification_enum,
    is_disqualified boolean DEFAULT false NOT NULL,
    disqualification_reason text,
    submitted_at timestamp with time zone,
    reviewed_at timestamp with time zone,
    closed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    origin public.application_origin_enum DEFAULT 'INBOUND_TELEGRAM'::public.application_origin_enum NOT NULL,
    preferred_platform public.platform_enum
);


--
-- Name: candidates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.candidates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    phone_e164 text NOT NULL,
    full_name text,
    email text,
    location_text text,
    telegram_chat_id bigint,
    telegram_user_id bigint,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    whatsapp_wa_id text,
    whatsapp_from text,
    whatsapp_profile_name text,
    whatsapp_opt_in_status text DEFAULT 'unknown'::text NOT NULL,
    whatsapp_opt_in_at timestamp with time zone,
    last_inbound_whatsapp_at timestamp with time zone
);


--
-- Name: vacancies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vacancies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    code text NOT NULL,
    title text NOT NULL,
    description text NOT NULL,
    responsibilities text[] DEFAULT '{}'::text[] NOT NULL,
    mandatory_requirements text[] DEFAULT '{}'::text[] NOT NULL,
    desirable_requirements text[] DEFAULT '{}'::text[] NOT NULL,
    salary_text text,
    schedule_text text,
    location_text text,
    benefits text[] DEFAULT '{}'::text[] NOT NULL,
    faq_context jsonb DEFAULT '{"items": []}'::jsonb NOT NULL,
    cv_max_score integer DEFAULT 40 NOT NULL,
    classification_thresholds jsonb DEFAULT '{"review": 35, "interview": 60, "shortlist": 75}'::jsonb NOT NULL,
    status public.vacancy_status_enum DEFAULT 'DRAFT'::public.vacancy_status_enum NOT NULL,
    opens_at timestamp with time zone,
    closes_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: application_ranking_view; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.application_ranking_view AS
 SELECT a.id AS application_id,
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
   FROM ((public.applications a
     JOIN public.candidates c ON ((c.id = a.candidate_id)))
     JOIN public.vacancies v ON ((v.id = a.vacancy_id)));


--
-- Name: conversation_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    platform public.platform_enum DEFAULT 'TELEGRAM'::public.platform_enum NOT NULL,
    platform_chat_id text NOT NULL,
    platform_user_id text,
    candidate_id uuid,
    application_id uuid,
    current_state public.state_enum DEFAULT 'WELCOME'::public.state_enum NOT NULL,
    state_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    last_incoming_event_id text,
    last_bot_message_id text,
    invalid_input_count integer DEFAULT 0 NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    last_user_message_at timestamp with time zone,
    last_bot_message_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cv_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cv_documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    application_id uuid NOT NULL,
    version integer NOT NULL,
    original_filename text NOT NULL,
    mime_type text NOT NULL,
    extension text NOT NULL,
    size_bytes integer NOT NULL,
    sha256 text NOT NULL,
    source_file_id text,
    source_file_unique_id text,
    storage_backend public.storage_backend_enum DEFAULT 'DB_BLOB'::public.storage_backend_enum NOT NULL,
    storage_key text NOT NULL,
    content bytea,
    extracted_text text,
    parse_status public.cv_parse_status_enum DEFAULT 'PENDING'::public.cv_parse_status_enum NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source_platform public.platform_enum,
    source_metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT cv_documents_size_bytes_check CHECK (((size_bytes > 0) AND (size_bytes <= 20971520))),
    CONSTRAINT cv_documents_version_check CHECK ((version > 0))
);


--
-- Name: cv_import_job_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cv_import_job_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    candidate_id uuid,
    application_id uuid,
    original_filename text NOT NULL,
    mime_type text,
    size_bytes integer,
    status text DEFAULT 'created'::text NOT NULL,
    outbound_status text,
    extraction_status text,
    detected_phone_e164 text,
    phone_confidence numeric(4,2),
    phone_candidates_json jsonb,
    extracted_preview text,
    candidate_reused boolean DEFAULT false NOT NULL,
    application_reused boolean DEFAULT false NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    raw_content bytea
);


--
-- Name: cv_import_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cv_import_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    vacancy_id uuid NOT NULL,
    requested_by text,
    total_files integer DEFAULT 0 NOT NULL,
    processed_files integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'created'::text NOT NULL,
    summary_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: outbound_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbound_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    candidate_id uuid,
    application_id uuid,
    conversation_session_id uuid,
    channel public.platform_enum NOT NULL,
    provider text DEFAULT 'internal'::text NOT NULL,
    to_address text NOT NULL,
    template_sid text,
    content_text text,
    content_variables jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    provider_message_sid text,
    error_code text,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    sent_at timestamp with time zone,
    delivered_at timestamp with time zone
);


--
-- Name: questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.questions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    code text NOT NULL,
    prompt_text text NOT NULL,
    answer_type public.answer_type_enum NOT NULL,
    default_validation jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scoring_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scoring_rules (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    vacancy_id uuid NOT NULL,
    name text NOT NULL,
    source_scope public.source_scope_enum DEFAULT 'ANSWER'::public.source_scope_enum NOT NULL,
    field_key text NOT NULL,
    operator public.scoring_operator_enum NOT NULL,
    expected_text text,
    expected_number numeric(12,2),
    expected_boolean boolean,
    points integer DEFAULT 0 NOT NULL,
    is_disqualifier boolean DEFAULT false NOT NULL,
    stop_on_match boolean DEFAULT false NOT NULL,
    priority integer DEFAULT 100 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: system_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid,
    level text NOT NULL,
    source text NOT NULL,
    event text NOT NULL,
    message text,
    payload jsonb,
    traceback text,
    application_id uuid,
    conversation_session_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tenant_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_questions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    question_id uuid NOT NULL,
    question_order integer NOT NULL,
    field_key text NOT NULL,
    prompt_override text,
    validation jsonb DEFAULT '{}'::jsonb NOT NULL,
    display_condition jsonb DEFAULT '{}'::jsonb NOT NULL,
    required boolean DEFAULT true NOT NULL,
    ask_before_cv boolean DEFAULT true NOT NULL,
    include_in_cv_score boolean DEFAULT true NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tenant_questions_question_order_check CHECK ((question_order > 0))
);


--
-- Name: tenants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug text NOT NULL,
    name text NOT NULL,
    timezone text DEFAULT 'Europe/Madrid'::text NOT NULL,
    locale text DEFAULT 'es'::text NOT NULL,
    hr_email text,
    telegram_bot_token text,
    telegram_webhook_secret text,
    settings_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    whatsapp_enabled boolean DEFAULT false NOT NULL,
    whatsapp_use_env_credentials boolean DEFAULT true NOT NULL,
    whatsapp_messaging_service_sid text,
    whatsapp_sender_address text,
    whatsapp_initial_template_sid text,
    whatsapp_initial_template_language text DEFAULT 'es'::text NOT NULL,
    whatsapp_assume_opt_in boolean DEFAULT false NOT NULL
);


--
-- Name: vacancy_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vacancy_questions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    vacancy_id uuid NOT NULL,
    question_id uuid NOT NULL,
    question_order integer NOT NULL,
    field_key text NOT NULL,
    prompt_override text,
    validation jsonb DEFAULT '{}'::jsonb NOT NULL,
    required boolean DEFAULT true NOT NULL,
    scoring_enabled boolean DEFAULT true NOT NULL,
    max_points integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vacancy_questions_question_order_check CHECK ((question_order > 0))
);


--
-- Name: ai_evaluations ai_evaluations_cv_document_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_evaluations
    ADD CONSTRAINT ai_evaluations_cv_document_id_key UNIQUE (cv_document_id);


--
-- Name: ai_evaluations ai_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_evaluations
    ADD CONSTRAINT ai_evaluations_pkey PRIMARY KEY (id);


--
-- Name: answers answers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answers
    ADD CONSTRAINT answers_pkey PRIMARY KEY (id);


--
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (id);


--
-- Name: candidates candidates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT candidates_pkey PRIMARY KEY (id);


--
-- Name: candidates candidates_tenant_id_phone_e164_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT candidates_tenant_id_phone_e164_key UNIQUE (tenant_id, phone_e164);


--
-- Name: conversation_sessions conversation_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_sessions
    ADD CONSTRAINT conversation_sessions_pkey PRIMARY KEY (id);


--
-- Name: cv_documents cv_documents_application_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_documents
    ADD CONSTRAINT cv_documents_application_id_version_key UNIQUE (application_id, version);


--
-- Name: cv_documents cv_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_documents
    ADD CONSTRAINT cv_documents_pkey PRIMARY KEY (id);


--
-- Name: cv_import_job_items cv_import_job_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_import_job_items
    ADD CONSTRAINT cv_import_job_items_pkey PRIMARY KEY (id);


--
-- Name: cv_import_jobs cv_import_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_import_jobs
    ADD CONSTRAINT cv_import_jobs_pkey PRIMARY KEY (id);


--
-- Name: outbound_messages outbound_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbound_messages
    ADD CONSTRAINT outbound_messages_pkey PRIMARY KEY (id);


--
-- Name: questions questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT questions_pkey PRIMARY KEY (id);


--
-- Name: questions questions_tenant_id_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT questions_tenant_id_code_key UNIQUE (tenant_id, code);


--
-- Name: scoring_rules scoring_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoring_rules
    ADD CONSTRAINT scoring_rules_pkey PRIMARY KEY (id);


--
-- Name: system_logs system_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_logs
    ADD CONSTRAINT system_logs_pkey PRIMARY KEY (id);


--
-- Name: tenant_questions tenant_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_questions
    ADD CONSTRAINT tenant_questions_pkey PRIMARY KEY (id);


--
-- Name: tenants tenants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);


--
-- Name: tenants tenants_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_slug_key UNIQUE (slug);


--
-- Name: vacancies vacancies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vacancies
    ADD CONSTRAINT vacancies_pkey PRIMARY KEY (id);


--
-- Name: vacancies vacancies_tenant_id_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vacancies
    ADD CONSTRAINT vacancies_tenant_id_code_key UNIQUE (tenant_id, code);


--
-- Name: vacancy_questions vacancy_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vacancy_questions
    ADD CONSTRAINT vacancy_questions_pkey PRIMARY KEY (id);


--
-- Name: idx_ai_evaluations_application; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ai_evaluations_application ON public.ai_evaluations USING btree (application_id, status);


--
-- Name: idx_answers_app_field_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_answers_app_field_key ON public.answers USING btree (application_id, field_key);


--
-- Name: idx_answers_app_tenant_question; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_answers_app_tenant_question ON public.answers USING btree (application_id, tenant_question_id);


--
-- Name: idx_applications_candidate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_applications_candidate ON public.applications USING btree (tenant_id, candidate_id);


--
-- Name: idx_applications_vacancy_ranking; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_applications_vacancy_ranking ON public.applications USING btree (tenant_id, vacancy_id, score_total DESC NULLS LAST);


--
-- Name: idx_candidates_tenant_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidates_tenant_phone ON public.candidates USING btree (tenant_id, phone_e164);


--
-- Name: idx_candidates_tg_chat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidates_tg_chat ON public.candidates USING btree (tenant_id, telegram_chat_id);


--
-- Name: idx_candidates_wa_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candidates_wa_id ON public.candidates USING btree (tenant_id, whatsapp_wa_id);


--
-- Name: idx_conversation_payload_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_payload_gin ON public.conversation_sessions USING gin (state_payload);


--
-- Name: idx_conversation_platform_chat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_platform_chat ON public.conversation_sessions USING btree (tenant_id, platform, platform_chat_id);


--
-- Name: idx_conversation_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_state ON public.conversation_sessions USING btree (tenant_id, current_state);


--
-- Name: idx_cv_documents_application; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cv_documents_application ON public.cv_documents USING btree (application_id, version DESC);


--
-- Name: idx_cv_import_job_items_job; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cv_import_job_items_job ON public.cv_import_job_items USING btree (job_id, created_at);


--
-- Name: idx_cv_import_job_items_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cv_import_job_items_status ON public.cv_import_job_items USING btree (tenant_id, status);


--
-- Name: idx_cv_import_jobs_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cv_import_jobs_tenant ON public.cv_import_jobs USING btree (tenant_id, created_at DESC);


--
-- Name: idx_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_logs_created_at ON public.system_logs USING btree (created_at DESC);


--
-- Name: idx_logs_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_logs_level ON public.system_logs USING btree (level);


--
-- Name: idx_logs_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_logs_tenant ON public.system_logs USING btree (tenant_id);


--
-- Name: idx_outbound_messages_app; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outbound_messages_app ON public.outbound_messages USING btree (application_id, created_at DESC);


--
-- Name: idx_outbound_messages_provider_sid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outbound_messages_provider_sid ON public.outbound_messages USING btree (provider_message_sid);


--
-- Name: idx_outbound_messages_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outbound_messages_status ON public.outbound_messages USING btree (tenant_id, status);


--
-- Name: idx_questions_tenant_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_questions_tenant_active ON public.questions USING btree (tenant_id, is_active);


--
-- Name: idx_scoring_rules_vacancy_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scoring_rules_vacancy_priority ON public.scoring_rules USING btree (vacancy_id, priority, is_active);


--
-- Name: idx_tenant_questions_tenant_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_questions_tenant_order ON public.tenant_questions USING btree (tenant_id, question_order);


--
-- Name: idx_vacancies_faq_context_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vacancies_faq_context_gin ON public.vacancies USING gin (faq_context);


--
-- Name: idx_vacancies_tenant_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vacancies_tenant_status ON public.vacancies USING btree (tenant_id, status, opens_at, closes_at);


--
-- Name: idx_vacancy_questions_vacancy_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vacancy_questions_vacancy_order ON public.vacancy_questions USING btree (vacancy_id, question_order);


--
-- Name: uq_active_conversation_session; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_active_conversation_session ON public.conversation_sessions USING btree (tenant_id, platform, platform_chat_id) WHERE (is_active = true);


--
-- Name: uq_answers_application_tenant_question; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_answers_application_tenant_question ON public.answers USING btree (application_id, tenant_question_id) WHERE (tenant_question_id IS NOT NULL);


--
-- Name: uq_answers_application_vacancy_question; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_answers_application_vacancy_question ON public.answers USING btree (application_id, vacancy_question_id) WHERE (vacancy_question_id IS NOT NULL);


--
-- Name: uq_application_candidate_vacancy; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_application_candidate_vacancy ON public.applications USING btree (tenant_id, candidate_id, vacancy_id);


--
-- Name: uq_candidates_tg_user; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_candidates_tg_user ON public.candidates USING btree (tenant_id, telegram_user_id) WHERE (telegram_user_id IS NOT NULL);


--
-- Name: uq_tq_active_field_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_tq_active_field_key ON public.tenant_questions USING btree (tenant_id, field_key) WHERE (is_active = true);


--
-- Name: uq_tq_active_order; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_tq_active_order ON public.tenant_questions USING btree (tenant_id, question_order) WHERE (is_active = true);


--
-- Name: uq_vq_active_field_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_vq_active_field_key ON public.vacancy_questions USING btree (vacancy_id, field_key) WHERE (is_active = true);


--
-- Name: uq_vq_active_order; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_vq_active_order ON public.vacancy_questions USING btree (vacancy_id, question_order) WHERE (is_active = true);


--
-- Name: ai_evaluations ai_evaluations_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_evaluations
    ADD CONSTRAINT ai_evaluations_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE;


--
-- Name: ai_evaluations ai_evaluations_cv_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_evaluations
    ADD CONSTRAINT ai_evaluations_cv_document_id_fkey FOREIGN KEY (cv_document_id) REFERENCES public.cv_documents(id) ON DELETE CASCADE;


--
-- Name: ai_evaluations ai_evaluations_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_evaluations
    ADD CONSTRAINT ai_evaluations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: answers answers_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answers
    ADD CONSTRAINT answers_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE;


--
-- Name: answers answers_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answers
    ADD CONSTRAINT answers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: answers answers_tenant_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answers
    ADD CONSTRAINT answers_tenant_question_id_fkey FOREIGN KEY (tenant_question_id) REFERENCES public.tenant_questions(id) ON DELETE CASCADE;


--
-- Name: answers answers_vacancy_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answers
    ADD CONSTRAINT answers_vacancy_question_id_fkey FOREIGN KEY (vacancy_question_id) REFERENCES public.vacancy_questions(id) ON DELETE CASCADE;


--
-- Name: applications applications_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: applications applications_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: applications applications_vacancy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_vacancy_id_fkey FOREIGN KEY (vacancy_id) REFERENCES public.vacancies(id) ON DELETE CASCADE;


--
-- Name: candidates candidates_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT candidates_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: conversation_sessions conversation_sessions_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_sessions
    ADD CONSTRAINT conversation_sessions_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE SET NULL;


--
-- Name: conversation_sessions conversation_sessions_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_sessions
    ADD CONSTRAINT conversation_sessions_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE SET NULL;


--
-- Name: conversation_sessions conversation_sessions_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_sessions
    ADD CONSTRAINT conversation_sessions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: cv_documents cv_documents_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_documents
    ADD CONSTRAINT cv_documents_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE;


--
-- Name: cv_documents cv_documents_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_documents
    ADD CONSTRAINT cv_documents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: cv_import_job_items cv_import_job_items_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_import_job_items
    ADD CONSTRAINT cv_import_job_items_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE SET NULL;


--
-- Name: cv_import_job_items cv_import_job_items_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_import_job_items
    ADD CONSTRAINT cv_import_job_items_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE SET NULL;


--
-- Name: cv_import_job_items cv_import_job_items_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_import_job_items
    ADD CONSTRAINT cv_import_job_items_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.cv_import_jobs(id) ON DELETE CASCADE;


--
-- Name: cv_import_job_items cv_import_job_items_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_import_job_items
    ADD CONSTRAINT cv_import_job_items_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: cv_import_jobs cv_import_jobs_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_import_jobs
    ADD CONSTRAINT cv_import_jobs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: cv_import_jobs cv_import_jobs_vacancy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cv_import_jobs
    ADD CONSTRAINT cv_import_jobs_vacancy_id_fkey FOREIGN KEY (vacancy_id) REFERENCES public.vacancies(id) ON DELETE CASCADE;


--
-- Name: outbound_messages outbound_messages_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbound_messages
    ADD CONSTRAINT outbound_messages_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE SET NULL;


--
-- Name: outbound_messages outbound_messages_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbound_messages
    ADD CONSTRAINT outbound_messages_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE SET NULL;


--
-- Name: outbound_messages outbound_messages_conversation_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbound_messages
    ADD CONSTRAINT outbound_messages_conversation_session_id_fkey FOREIGN KEY (conversation_session_id) REFERENCES public.conversation_sessions(id) ON DELETE SET NULL;


--
-- Name: outbound_messages outbound_messages_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbound_messages
    ADD CONSTRAINT outbound_messages_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: questions questions_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT questions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: scoring_rules scoring_rules_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoring_rules
    ADD CONSTRAINT scoring_rules_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: scoring_rules scoring_rules_vacancy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoring_rules
    ADD CONSTRAINT scoring_rules_vacancy_id_fkey FOREIGN KEY (vacancy_id) REFERENCES public.vacancies(id) ON DELETE CASCADE;


--
-- Name: tenant_questions tenant_questions_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_questions
    ADD CONSTRAINT tenant_questions_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE RESTRICT;


--
-- Name: tenant_questions tenant_questions_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_questions
    ADD CONSTRAINT tenant_questions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: vacancies vacancies_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vacancies
    ADD CONSTRAINT vacancies_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: vacancy_questions vacancy_questions_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vacancy_questions
    ADD CONSTRAINT vacancy_questions_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE RESTRICT;


--
-- Name: vacancy_questions vacancy_questions_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vacancy_questions
    ADD CONSTRAINT vacancy_questions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: vacancy_questions vacancy_questions_vacancy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vacancy_questions
    ADD CONSTRAINT vacancy_questions_vacancy_id_fkey FOREIGN KEY (vacancy_id) REFERENCES public.vacancies(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict 2FVwqoc7hxFPUBYXmIDCBn7LgZkYJE3wAmNUjCcr0cXj8a65TVFRiJSH4QJzPgL

