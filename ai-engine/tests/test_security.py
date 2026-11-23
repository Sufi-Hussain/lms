from fastapi.testclient import TestClient
from app.main import app


def test_health_is_public():
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_api_requires_service_bearer_token(monkeypatch):
    monkeypatch.setattr("app.core.security.settings.service_token", "test-secret")
    with TestClient(app) as client:
        params = {"school_id": "school-a", "student_id": "student-a"}
        assert client.get("/api/v1/sessions/not-a-session", params=params).status_code == 401
        assert client.get(
            "/api/v1/sessions/not-a-session",
            params=params,
            headers={"Authorization": "Bearer test-secret"},
        ).status_code == 502


def test_frappe_adapter_failure_is_not_silently_ignored(monkeypatch):
    from app.integrations.frappe_client import FrappeClient
    import httpx
    async def fail(_client, _payload):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(FrappeClient, "get_lesson_context", fail)
    monkeypatch.setattr("app.core.security.settings.service_token", "test-secret")
    with TestClient(app) as client:
        response = client.post("/api/v1/sessions", json={"student_id":"s1","school_id":"school-a","course_id":"c1","subject":"physics","chapter":"gravity","topic":"falling","language":"en"}, headers={"Authorization":"Bearer test-secret"})
        assert response.status_code == 503
