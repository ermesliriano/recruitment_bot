-- 009_email_channel.sql
-- Canal de correo electronico (Twilio SendGrid), fase 1: outbound desde Cargar CVs.
--
-- Aplicar manualmente en la base de Render (psql). Nota: ALTER TYPE ... ADD VALUE
-- no puede ejecutarse dentro de una transaccion en versiones antiguas de PostgreSQL;
-- en PG 12+ (Render) si esta permitido.

-- 1) Nuevo valor del enum de plataforma (casing en MAYUSCULAS, como el resto).
ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'EMAIL';

-- 2) Canal del lote de importacion de CVs ('whatsapp' | 'email').
ALTER TABLE cv_import_jobs
    ADD COLUMN IF NOT EXISTS channel VARCHAR(16) NOT NULL DEFAULT 'whatsapp';

-- 3) Email detectado en el CV (analogo a detected_phone_e164).
ALTER TABLE cv_import_job_items
    ADD COLUMN IF NOT EXISTS detected_email VARCHAR(255);
