-- 010_conversation_messages.sql
-- Transcripcion completa de conversaciones reclutador-bot <-> candidato.
--
-- Equivalente (mejorado) a la tabla `conversations` de la Suite CesarIA:
-- una fila POR MENSAJE con direccion in/out, en lugar del par
-- incoming_msg/response (que no soporta turnos con varias respuestas).
-- `conversation_sessions` ya cumple el rol del `chats` de la Suite (hilo+estado).

CREATE TABLE IF NOT EXISTS conversation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    candidate_id UUID,
    application_id UUID,
    session_id UUID,
    platform platform_enum NOT NULL,
    -- Clave del hilo: whatsapp:+E164 | chat_id de telegram | direccion de email.
    platform_chat_id VARCHAR(255) NOT NULL,
    direction VARCHAR(3) NOT NULL CHECK (direction IN ('in', 'out')),
    message_text TEXT,
    message_type VARCHAR(30) NOT NULL DEFAULT 'text',
    attachment_filename VARCHAR(255),
    external_id VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_msgs_thread
    ON conversation_messages (tenant_id, platform, platform_chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_conv_msgs_tenant_recent
    ON conversation_messages (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_conv_msgs_candidate
    ON conversation_messages (candidate_id, created_at);
