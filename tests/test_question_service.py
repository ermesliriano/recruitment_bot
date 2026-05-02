# tests/test_question_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uuid import uuid4

from app.core.db import Base
from app.services.question_service import QuestionService
from app.schemas.question import QuestionCreate
from app.enums import AnswerType

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine)


@pytest.fixture(scope="module", autouse=True)
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def test_create_question(db):
    svc = QuestionService(db)
    q = svc.create_question(QuestionCreate(
        tenant_id=uuid4(),
        code="Q-001",
        prompt_text="¿Tienes experiencia en Python?",
        answer_type=AnswerType.BOOLEAN,
        default_validation={"true_values": ["si"], "false_values": ["no"]},
    ))
    assert q.id is not None
    assert q.code == "Q-001"
    assert q.is_active is True


def test_list_questions(db):
    svc = QuestionService(db)
    tenant_id = uuid4()
    svc.create_question(QuestionCreate(
        tenant_id=tenant_id, code="Q-002",
        prompt_text="¿Años de experiencia?", answer_type=AnswerType.NUMBER,
    ))
    results = svc.list_questions(tenant_id=str(tenant_id))
    assert len(results) == 1


def test_deactivate_question(db):
    svc = QuestionService(db)
    q = svc.create_question(QuestionCreate(
        tenant_id=uuid4(), code="Q-DEL",
        prompt_text="¿Borrar?", answer_type=AnswerType.TEXT,
    ))
    deactivated = svc.deactivate_question(str(q.id))
    assert deactivated.is_active is False
