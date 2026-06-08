-- sql/006_fix_application_origin_enum_case.sql
-- Alinea application_origin_enum a la convencion de MAYUSCULAS del resto de enums.
--
-- Causa: SQLAlchemy (SAEnum sin values_callable) persiste el NOMBRE del miembro
-- del enum de Python, no su value. Todos los tipos enum de la base usan
-- etiquetas en mayusculas (DRAFT, TELEGRAM, ...) para casar con ese nombre,
-- pero application_origin_enum se creo en 004 en minusculas
-- ('inbound_telegram', ...). Por eso INSERT de Application con
-- origin = ApplicationOrigin.INBOUND_TELEGRAM enviaba "INBOUND_TELEGRAM" y
-- Postgres lo rechazaba con "invalid input value for enum", bloqueando el
-- flujo justo despues de seleccionar la vacante.
--
-- Las tablas estan truncadas en el entorno de pruebas, por lo que no hay datos
-- que convertir. RENAME VALUE es seguro dentro de transaccion (a diferencia de
-- ADD VALUE en versiones antiguas de PostgreSQL).

BEGIN;

ALTER TABLE applications ALTER COLUMN origin DROP DEFAULT;

ALTER TYPE application_origin_enum RENAME VALUE 'inbound_telegram' TO 'INBOUND_TELEGRAM';
ALTER TYPE application_origin_enum RENAME VALUE 'inbound_whatsapp' TO 'INBOUND_WHATSAPP';
ALTER TYPE application_origin_enum RENAME VALUE 'recruiter_upload' TO 'RECRUITER_UPLOAD';

ALTER TABLE applications ALTER COLUMN origin SET DEFAULT 'INBOUND_TELEGRAM';

COMMIT;
