# app/core/security.py
"""
Autenticación y autorización.

Modos de acceso aceptados (cabecera Authorization: Bearer <token>):
  1. ADMIN_TOKEN legado (variable de entorno): rol superadmin. Se mantiene para
     compatibilidad con integraciones (cron de importaciones programadas, etc.).
  2. Token de usuario firmado (HMAC-SHA256, sin dependencias externas), emitido
     por POST /auth/login con caducidad. Payload: uid, role, tid (tenant), exp.

Reglas de autorización por rol:
  - superadmin: sin restricciones.
  - company: solo endpoints cuyo tenant_id (en path o query) coincida con el
    suyo. Endpoints sin tenant_id (mantenimiento, gestión de empresas/usuarios)
    quedan reservados a superadmin.

Contraseñas: PBKDF2-SHA256 (stdlib) con salt aleatorio por usuario.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer = HTTPBearer()

PBKDF2_ITERATIONS = 260_000
TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 dias


# ── Contraseñas ───────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = (stored or "").split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


# ── Tokens de usuario ─────────────────────────────────────────────────────────

def _signing_secret() -> bytes:
    return (settings.auth_secret or settings.admin_token or "").encode()


def _sign(raw: bytes) -> str:
    return hmac.new(_signing_secret(), raw, hashlib.sha256).hexdigest()


def issue_user_token(*, user_id: str, role: str, tenant_id: str | None) -> str:
    payload = {
        "uid": str(user_id),
        "role": role,
        "tid": str(tenant_id) if tenant_id else None,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{raw.decode()}.{_sign(raw)}"


def verify_user_token(token: str) -> dict | None:
    """Devuelve el payload si el token es válido y no ha caducado; si no, None."""
    try:
        raw_b64, signature = token.rsplit(".", 1)
        raw = raw_b64.encode()
        if not hmac.compare_digest(_sign(raw), signature):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        if payload.get("role") not in ("superadmin", "company"):
            return None
        return payload
    except Exception:
        return None


# ── Principal y dependencias ──────────────────────────────────────────────────

@dataclass
class AuthPrincipal:
    role: str  # "superadmin" | "company"
    user_id: str | None = None
    tenant_id: str | None = None
    is_service_token: bool = False  # ADMIN_TOKEN legado


def require_admin_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> AuthPrincipal:
    token = credentials.credentials

    # 1) Token de servicio legado → superadmin (integraciones/cron).
    if settings.admin_token and hmac.compare_digest(token, settings.admin_token):
        return AuthPrincipal(role="superadmin", is_service_token=True)

    # 2) Token de usuario firmado.
    payload = verify_user_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o caducado",
        )

    principal = AuthPrincipal(
        role=payload["role"],
        user_id=payload.get("uid"),
        tenant_id=payload.get("tid"),
    )

    if principal.role == "superadmin":
        return principal

    # Rol company: el endpoint debe referirse a SU empresa.
    scoped_tenant = request.path_params.get("tenant_id") or request.query_params.get("tenant_id")
    if not scoped_tenant or str(scoped_tenant).strip().lower() != str(principal.tenant_id or "").lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos sobre esta empresa.",
        )
    return principal


def require_superadmin(
    principal: AuthPrincipal = Depends(require_admin_token),
) -> AuthPrincipal:
    if principal.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta operación requiere rol de administrador general.",
        )
    return principal
