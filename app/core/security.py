# app/core/security.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer = HTTPBearer()


def require_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> None:
    if credentials.credentials != settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de administrador inválido",
        )
