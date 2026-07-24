-- 011_users.sql
-- Sistema de usuarios y roles.
--
--  - superadmin: acceso total, todas las empresas, crear empresas y usuarios.
--  - company: acceso restringido a su propia empresa (tenant_id obligatorio).
--
-- El primer superadmin se crea via POST /auth/bootstrap (solo funciona cuando
-- la tabla esta vacia). Aplicar manualmente en Render antes de desplegar.

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('superadmin', 'company')),
    tenant_id UUID REFERENCES tenants(id),
    full_name VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT company_requires_tenant
        CHECK (role <> 'company' OR tenant_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users (tenant_id);
