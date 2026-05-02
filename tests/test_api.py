# tests/test_api.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uuid import uuid4

from app.core.db import Base, get_db
from app.core.config import settings
from app.main import app

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app, raise_server_exceptions=False)
AUTH = {"Authorization": f"Bearer {settings.admin_token}"}


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_vacancies_empty():
    resp = client.get("/vacancies/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_vacancy_requires_auth():
    resp = client.post("/vacancies/", json={})
    assert resp.status_code == 403


def test_create_and_list_vacancy():
    tenant_id = str(uuid4())
    payload = {
        "code": "API-001",
        "tenant_id": tenant_id,
        "title": "Vacante API",
        "description": "Descripción API",
        "mandatory_requirements": ["REQ"],
        "desirable_requirements": [],
        "salary_text": "0",
        "schedule_text": "9-5",
        "location_text": "Remoto",
        "benefits": [],
        "faq_context": {"items": []},
        "cv_score_factor": 5.0,
        "classification_thresholds": {"review": 10, "interview": 20, "shortlist": 30},
    }
    resp = client.post("/vacancies/", json=payload, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "API-001"
    assert data["status"] == "draft"

    resp2 = client.get(f"/vacancies/?tenant_id={tenant_id}")
    assert resp2.status_code == 200
    assert any(v["code"] == "API-001" for v in resp2.json())


def test_create_question():
    payload = {
        "tenant_id": str(uuid4()),
        "code": "Q-API-001",
        "prompt_text": "¿Hablas inglés?",
        "answer_type": "boolean",
        "default_validation": {},
    }
    resp = client.post("/questions/", json=payload, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["code"] == "Q-API-001"
