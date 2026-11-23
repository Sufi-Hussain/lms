from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models.session import TutorSession


def test_session_is_scoped_by_school(monkeypatch):
    monkeypatch.setattr("app.core.security.settings.service_token", "tenant-test")
    with TestClient(app) as client:
        db = SessionLocal()
        row = TutorSession(id="tenant-check-session", student_id="student-a", school_id="school-a", course_id="course-a", subject="physics", chapter="motion", topic="speed", context={}, history=[])
        db.merge(row)
        db.commit()
        db.close()
        headers = {"Authorization": "Bearer tenant-test"}
        assert client.get("/api/v1/sessions/tenant-check-session", params={"school_id":"school-a"}, headers=headers).status_code == 200
        assert client.get("/api/v1/sessions/tenant-check-session", params={"school_id":"school-b"}, headers=headers).status_code == 404
