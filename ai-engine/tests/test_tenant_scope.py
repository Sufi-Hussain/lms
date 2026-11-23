import httpx
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.session import TutorSession


def test_session_is_scoped_by_school(monkeypatch):
    monkeypatch.setattr("app.core.security.settings.service_token", "tenant-test")

    async def authorize_student(**kwargs):
        return None

    async def missing_session(**kwargs):
        request = httpx.Request("GET", "http://frappe/api/method/get_tutor_session")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr("app.api.v1.sessions.frappe_client.authorize_student", authorize_student)
    monkeypatch.setattr("app.api.v1.sessions.frappe_client.get_tutor_session", missing_session)
    with TestClient(app) as client:
        db = SessionLocal()
        row = TutorSession(
            id="tenant-check-session",
            student_id="student-a",
            school_id="school-a",
            course_id="course-a",
            subject="physics",
            chapter="motion",
            topic="speed",
            context={},
            history=[],
        )
        db.merge(row)
        db.commit()
        db.close()
        headers = {"Authorization": "Bearer tenant-test"}
        params = {"school_id": "school-a", "student_id": "student-a"}
        assert client.get("/api/v1/sessions/tenant-check-session", params=params, headers=headers).status_code == 200
        params["school_id"] = "school-b"
        assert client.get("/api/v1/sessions/tenant-check-session", params=params, headers=headers).status_code == 404
