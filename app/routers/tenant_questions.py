# app/routers/tenant_questions.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_admin_token
from app.schemas.tenant_question import (
    TenantQuestionCreate,
    TenantQuestionOut,
    TenantQuestionUpdate,
)
from app.services.tenant_question_service import TenantQuestionService

router = APIRouter(
    prefix="/tenants/{tenant_id}/screening-questions",
    tags=["Tenant screening questions"],
)


@router.get("", response_model=list[TenantQuestionOut])
def list_tenant_questions(tenant_id: str, db: Session = Depends(get_db)):
    return TenantQuestionService(db).list_questions(tenant_id)


@router.post("", response_model=TenantQuestionOut, dependencies=[Depends(require_admin_token)])
def create_tenant_question(
    tenant_id: str,
    data: TenantQuestionCreate,
    db: Session = Depends(get_db),
):
    return TenantQuestionService(db).create_question(tenant_id, data)


@router.patch("/{tq_id}", response_model=TenantQuestionOut, dependencies=[Depends(require_admin_token)])
def update_tenant_question(
    tenant_id: str,
    tq_id: str,
    data: TenantQuestionUpdate,
    db: Session = Depends(get_db),
):
    try:
        return TenantQuestionService(db).update_question(tenant_id, tq_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{tq_id}", status_code=204, dependencies=[Depends(require_admin_token)])
def delete_tenant_question(
    tenant_id: str,
    tq_id: str,
    db: Session = Depends(get_db),
):
    try:
        TenantQuestionService(db).delete_question(tenant_id, tq_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
