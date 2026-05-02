# app/routers/questions.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.db import get_db
from app.core.security import require_admin_token
from app.schemas.question import QuestionCreate, QuestionOut
from app.services.question_service import QuestionService

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.get("/", response_model=List[QuestionOut])
def list_questions(tenant_id: str | None = None, db: Session = Depends(get_db)):
    return QuestionService(db).list_questions(tenant_id)


@router.post("/", response_model=QuestionOut, dependencies=[Depends(require_admin_token)])
def create_question(data: QuestionCreate, db: Session = Depends(get_db)):
    return QuestionService(db).create_question(data)


@router.delete("/{question_id}", response_model=QuestionOut, dependencies=[Depends(require_admin_token)])
def deactivate_question(question_id: str, db: Session = Depends(get_db)):
    try:
        return QuestionService(db).deactivate_question(question_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
