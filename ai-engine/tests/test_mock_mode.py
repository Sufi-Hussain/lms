import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.api.v1 import profiles, sessions
from app.core.config import settings
from app.core.database import Base, get_db
from app.integrations.client import create_frappe_client
from app.integrations.mock_frappe_client import MockFrappeClient
from app.main import app
from app.services import outbox
from app.services.orchestrator import TutorOrchestrator


def test_mock_mode_runs_a_complete_tenant_scoped_api_session(monkeypatch):
    monkeypatch.setattr(settings, "frappe_mode", "mock")
    monkeypatch.setattr(settings, "frappe_url", "")
    monkeypatch.setattr(settings, "frappe_api_key", "")
    monkeypatch.setattr(settings, "frappe_api_secret", "")
    monkeypatch.setattr(settings, "service_token", "mock-local-test-token")
    mock_lms = create_frappe_client()
    assert isinstance(mock_lms, MockFrappeClient)

    monkeypatch.setattr(sessions, "frappe_client", mock_lms)
    monkeypatch.setattr(sessions, "orchestrator", TutorOrchestrator(mock_lms))
    monkeypatch.setattr(profiles, "frappe_client", mock_lms)
    monkeypatch.setattr(outbox, "frappe_client", mock_lms)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    headers = {"Authorization": "Bearer mock-local-test-token"}
    request = {
        "student_id": "learner-1",
        "school_id": "school-1",
        "course_id": "science-1",
        "subject": "Science",
        "chapter": "Forces",
        "topic": "Gravity",
        "language": "en",
    }

    try:
        with TestClient(app) as client:
            started = client.post("/api/v1/sessions", json=request, headers=headers)
            assert started.status_code == 201
            start_payload = started.json()
            assert start_payload["sync_status"] == "synced"
            assert start_payload["interaction"]["question_id"]

            hint = client.post(
                f"/api/v1/sessions/{start_payload['session_id']}/hint",
                params={"school_id": "school-1", "student_id": "learner-1"},
                headers=headers,
            )
            assert hint.status_code == 200
            assert hint.json()["interaction"]["question_id"] == start_payload["interaction"]["question_id"]

            resumed = client.post(
                f"/api/v1/sessions/{start_payload['session_id']}/resume",
                params={"school_id": "school-1", "student_id": "learner-1"},
                headers=headers,
            )
            assert resumed.status_code == 200
            assert resumed.json()["interaction"]["question_id"] == start_payload["interaction"]["question_id"]

            snapshot = asyncio.run(
                mock_lms.get_tutor_session(
                    student_id="learner-1",
                    school_id="school-1",
                    session_id=start_payload["session_id"],
                )
            )
            active_question = snapshot["context"]["active_question"]
            answer = client.post(
                f"/api/v1/sessions/{start_payload['session_id']}/answer",
                params={"school_id": "school-1", "student_id": "learner-1"},
                json={
                    "question_id": active_question["question_id"],
                    "answer": active_question["expected_answer"],
                },
                headers=headers,
            )
            assert answer.status_code == 200
            assert answer.json()["correct"] is True
            assert answer.json()["sync_status"] == "synced"

            cross_school_session = client.get(
                f"/api/v1/sessions/{start_payload['session_id']}",
                params={"school_id": "school-2", "student_id": "learner-1"},
                headers=headers,
            )
            assert cross_school_session.status_code == 404

            profile = client.get(
                "/api/v1/students/learner-1/learning-profile",
                params={"school_id": "school-1"},
                headers=headers,
            )
            assert profile.status_code == 200
            assert profile.json()["concepts"][0]["attempts"] == 1
            assert profile.json()["concepts"][0]["score"] == 1.0

            other_school = client.get(
                "/api/v1/students/learner-1/learning-profile",
                params={"school_id": "school-2"},
                headers=headers,
            )
            assert other_school.status_code == 200
            assert other_school.json()["concepts"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
