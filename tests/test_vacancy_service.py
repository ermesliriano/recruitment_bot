# tests/test_vacancy_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uuid import uuid4

from app.core.db import Base
from app.services.vacancy_service import VacancyService
from app.schemas.vacancy import VacancyCreate

# SQLite en memoria para tests (no requiere PostgreSQL)
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


def _vacancy_payload(**overrides) -> VacancyCreate:
    return VacancyCreate(
        code=overrides.get("code", "TST-001"),
        tenant_id=overrides.get("tenant_id", uuid4()),
        title=overrides.get("title", "Vacante de Prueba"),
        description="Descripción de prueba",
        mandatory_requirements=["Req1"],
        desirable_requirements=[],
        salary_text="0",
        schedule_text="9-5",
        location_text="Remoto",
        benefits=[],
        faq_context={"items": []},
        cv_score_factor=5.0,
        classification_thresholds={"review": 10, "interview": 20, "shortlist": 30},
    )


def test_create_vacancy(db):
    svc = VacancyService(db)
    vacancy = svc.create_vacancy(_vacancy_payload())
    assert vacancy.id is not None
    assert vacancy.code == "TST-001"
    assert vacancy.status.value == "draft"


def test_list_vacancies(db):
    svc = VacancyService(db)
    tenant_id = uuid4()
    svc.create_vacancy(_vacancy_payload(code="TST-002", tenant_id=tenant_id))
    svc.create_vacancy(_vacancy_payload(code="TST-003", tenant_id=tenant_id))
    results = svc.list_vacancies(tenant_id=str(tenant_id))
    assert len(results) == 2


def test_get_vacancy_not_found(db):
    svc = VacancyService(db)
    with pytest.raises(ValueError, match="no encontrada"):
        svc.get_vacancy(str(uuid4()))
