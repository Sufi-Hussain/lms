from app.ai.providers.http import request_json
from app.core.config import settings


class FrappeClient:
    def __init__(self):
        self.base = settings.frappe_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not settings.frappe_api_key or not settings.frappe_api_secret:
            raise RuntimeError("Frappe API credentials are not configured")
        return {
            "Authorization": f"token {settings.frappe_api_key}:{settings.frappe_api_secret}",
            "Accept": "application/json",
        }

    async def get_lesson_context(self, payload: dict) -> dict:
        if not self.base:
            raise RuntimeError("Frappe LMS integration is not configured")
        response = await request_json(
            "POST",
            f"{self.base}/api/method/lms.ai_integration.get_tutor_context",
            headers=self._headers(),
            payload=payload,
        )
        result = response.get("message")
        if not isinstance(result, dict) or not result.get("learning_objective"):
            raise ValueError("Frappe returned invalid curriculum context")
        return result

    async def save_event(self, payload: dict) -> None:
        if not self.base:
            raise RuntimeError("Frappe LMS integration is not configured")
        await request_json(
            "POST",
            f"{self.base}/api/method/lms.ai_integration.save_tutor_event",
            headers=self._headers(),
            payload=payload,
        )

    async def authorize_student(self, *, student_id: str, school_id: str, course_id: str) -> None:
        if not self.base:
            raise RuntimeError("Frappe LMS integration is not configured")
        response = await request_json(
            "POST",
            f"{self.base}/api/method/lms.ai_integration.authorize_tutor_student",
            headers=self._headers(),
            payload={"student_id": student_id, "school_id": school_id, "course_id": course_id},
        )
        if response.get("message", {}).get("authorized") is not True:
            raise ValueError("Frappe did not authorize this student")

    async def save_tutor_session(self, payload: dict) -> None:
        if not self.base:
            raise RuntimeError("Frappe LMS integration is not configured")
        await request_json(
            "POST",
            f"{self.base}/api/method/lms.ai_integration.save_tutor_session",
            headers=self._headers(),
            payload=payload,
        )

    async def get_tutor_session(
        self, *, student_id: str, school_id: str, session_id: str
    ) -> dict:
        if not self.base:
            raise RuntimeError("Frappe LMS integration is not configured")
        response = await request_json(
            "GET",
            f"{self.base}/api/method/lms.ai_integration.get_tutor_session",
            headers=self._headers(),
            params={
                "student_id": student_id,
                "school_id": school_id,
                "session_id": session_id,
            },
        )
        result = response.get("message")
        if not isinstance(result, dict):
            raise ValueError("Frappe returned an invalid tutor session")
        return result

    async def get_learning_profile(self, student_id: str, school_id: str) -> dict:
        if not self.base:
            raise RuntimeError("Frappe LMS integration is not configured")
        response = await request_json(
            "GET",
            f"{self.base}/api/method/lms.ai_integration.get_learning_profile",
            headers=self._headers(),
            params={"student_id": student_id, "school_id": school_id},
        )
        result = response.get("message")
        if not isinstance(result, dict):
            raise ValueError("Frappe returned an invalid learning profile")
        return result
