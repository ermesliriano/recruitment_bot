# app/routers/auth.py
"""
Autenticación de usuarios del panel.

- GET  /auth/bootstrap-status : ¿hace falta crear el primer superadmin?
- POST /auth/bootstrap        : crea el PRIMER superadmin (solo con tabla vacía).
- POST /auth/login            : email + contraseña → token firmado + perfil.
- GET  /auth/me               : perfil del usuario del token (restaurar sesión).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import (
    hash_password,
    issue_user_token,
    verify_password,
    verify_user_token,
)
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Auth"])
_bearer = HTTPBearer()


class BootstrapIn(BaseModel):
    email: str
    password: str
    full_name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


def _user_payload(db: Session, user: User) -> dict:
    tenant_name = None
    if user.tenant_id:
        tenant_name = db.execute(
            select(Tenant.name).where(Tenant.id == user.tenant_id)
        ).scalar_one_or_none()
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "tenant_name": tenant_name,
    }


@router.get("/bootstrap-status")
def bootstrap_status(db: Session = Depends(get_db)):
    total = db.execute(select(func.count()).select_from(User)).scalar_one()
    return {"needs_bootstrap": total == 0}


@router.post("/bootstrap")
def bootstrap(payload: BootstrapIn, db: Session = Depends(get_db)):
    total = db.execute(select(func.count()).select_from(User)).scalar_one()
    if total > 0:
        raise HTTPException(
            status_code=403,
            detail="Ya existen usuarios: el administrador inicial solo puede crearse con la tabla vacía.",
        )

    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Email no válido.")
    if len(payload.password or "") < 8:
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 8 caracteres.")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role="superadmin",
        full_name=(payload.full_name or "").strip() or None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = issue_user_token(user_id=str(user.id), role=user.role, tenant_id=None)
    return {"token": token, "user": _user_payload(db, user)}


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas.")

    token = issue_user_token(
        user_id=str(user.id),
        role=user.role,
        tenant_id=str(user.tenant_id) if user.tenant_id else None,
    )
    return {"token": token, "user": _user_payload(db, user)}


@router.get("/me")
def me(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
):
    payload = verify_user_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token inválido o caducado")

    user = db.execute(select(User).where(User.id == payload["uid"])).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuario no disponible")

    return {"user": _user_payload(db, user)}
