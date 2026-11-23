import copy
import hashlib
import threading
from datetime import datetime

import httpx


class MockFrappeClient:
    """Local-only LMS adapter for exercising the service without Frappe."""

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: dict[tuple[str, str, str], dict] = {}
        self._events: dict[str, dict] = {}
        self._profiles: dict[tuple[str, str], dict[str, dict]] = {}
        self._concepts: dict[tuple[str, str, str], dict] = {}

    async def get_lesson_context(self, payload: dict) -> dict:
        scope = (
            payload["school_id"],
            payload["student_id"],
            payload["course_id"],
        )
        concept_scope = (*scope, payload["subject"], payload["chapter"], payload["topic"])
        digest = hashlib.sha256("\0".join(concept_scope).encode()).hexdigest()[:20]
        concept_id = f"mock-{digest}"
        details = {
            "concept_id": concept_id,
            "course_id": payload["course_id"],
            "board": "Demo",
            "class_level": 6,
            "subject": payload["subject"],
            "chapter": payload["chapter"],
            "topic": payload["topic"],
        }
        with self._lock:
            self._concepts[(payload["school_id"], payload["student_id"], concept_id)] = details
        return {
            **details,
            "learning_objective": (
                f"Explain {payload['topic']} in {payload['chapter']} and give one "
                f"example related to {payload['subject']}."
            ),
            "resources": [],
        }

    async def authorize_student(self, *, student_id: str, school_id: str, course_id: str) -> None:
        if not student_id.strip() or not school_id.strip() or not course_id.strip():
            raise ValueError("Student, school, and course identifiers are required")

    async def save_tutor_session(self, payload: dict) -> None:
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("Invalid mock session snapshot")
        scope = (payload.get("school_id"), payload.get("student_id"), payload.get("session_id"))
        if (
            snapshot.get("school_id") != scope[0]
            or snapshot.get("student_id") != scope[1]
            or snapshot.get("session_id") != scope[2]
            or snapshot.get("course_id") != payload.get("course_id")
        ):
            raise ValueError("Mock session scope mismatch")
        with self._lock:
            existing = self._sessions.get(scope)
            if existing and _parse_time(existing["updated_at"]) >= _parse_time(snapshot["updated_at"]):
                return
            self._sessions[scope] = copy.deepcopy(snapshot)

    async def get_tutor_session(self, *, student_id: str, school_id: str, session_id: str) -> dict:
        scope = (school_id, student_id, session_id)
        with self._lock:
            snapshot = self._sessions.get(scope)
            if snapshot is None:
                request = httpx.Request("GET", "http://mock/api/tutor-session")
                response = httpx.Response(404, request=request)
                raise httpx.HTTPStatusError("Mock session not found", request=request, response=response)
            return copy.deepcopy(snapshot)

    async def save_event(self, payload: dict) -> None:
        event = payload.get("event")
        if not isinstance(event, dict) or not event.get("event_id"):
            raise ValueError("Invalid mock progress event")
        scope = (payload.get("school_id"), payload.get("student_id"), payload.get("session_id"))
        with self._lock:
            previous = self._events.get(event["event_id"])
            if previous:
                if previous["scope"] != scope:
                    raise ValueError("Mock progress event scope mismatch")
                return
            if scope not in self._sessions:
                raise ValueError("Mock session not found")
            self._events[event["event_id"]] = {"scope": scope, "event": copy.deepcopy(event)}
            if event.get("event_type") != "assessment":
                return

            profile_key = (scope[0], scope[1])
            concept_id = event["concept_id"]
            concepts = self._profiles.setdefault(profile_key, {})
            concept = concepts.setdefault(
                concept_id,
                {"concept_id": concept_id, "attempts": 0, "correct_attempts": 0, "sessions": {}},
            )
            progress = concept["sessions"].setdefault(
                scope[2], {"attempts": 0, "correct_attempts": 0, "completed": False}
            )
            attempts = int(event["attempts"])
            correct_attempts = int(event["correct_attempts"])
            concept["attempts"] += max(0, attempts - progress["attempts"])
            concept["correct_attempts"] += max(0, correct_attempts - progress["correct_attempts"])
            progress.update(
                {
                    "attempts": max(attempts, progress["attempts"]),
                    "correct_attempts": max(correct_attempts, progress["correct_attempts"]),
                    "completed": bool(event["completed"] or progress["completed"]),
                }
            )
            concept.update(
                {
                    "course_id": payload["course_id"],
                    "correct_streak": int(event["correct_streak"]),
                    "status": event["mastery_status"],
                    "latest_event_at": event["occurred_at"],
                    "score": round(concept["correct_attempts"] / max(concept["attempts"], 1), 4),
                }
            )

    async def get_learning_profile(self, student_id: str, school_id: str) -> dict:
        with self._lock:
            concepts = self._profiles.get((school_id, student_id), {})
            public_concepts = [
                {key: value for key, value in concept.items() if key != "sessions"}
                for concept in concepts.values()
            ]
            next_lesson = None
            for concept in public_concepts:
                if concept.get("status") != "mastered":
                    next_lesson = copy.deepcopy(
                        self._concepts.get((school_id, student_id, concept["concept_id"]))
                    )
                    break
            return {
                "concepts": copy.deepcopy(public_concepts),
                "recommended_next_lesson": next_lesson,
            }


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
