"""Copy into <your_app>/<your_app>/ai_integration.py after installing the proposed DocTypes."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import frappe
import requests
from frappe import _
from frappe.utils import get_datetime


SERVICE_ROLE = "AI Engine Service"
ALLOWED_EVENT_FIELDS = {
    "event_id",
    "event_type",
    "occurred_at",
    "concept_id",
    "correct",
    "attempts",
    "correct_attempts",
    "correct_streak",
    "score",
    "mastery_status",
    "completed",
    "session_state",
}
SESSION_FIELDS = {
    "session_id",
    "school_id",
    "student_id",
    "course_id",
    "subject",
    "chapter",
    "topic",
    "state",
    "history",
    "attempts",
    "correct_attempts",
    "completed",
    "created_at",
    "updated_at",
    "context",
}


def _require_service():
    if frappe.session.user == "Guest" or not frappe.has_role(SERVICE_ROLE):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _validate_text(value, label, maximum=140):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        frappe.throw(_("Invalid {0}").format(label), frappe.ValidationError)
    return value.strip()


def _validate_session_id(value):
    try:
        return str(uuid.UUID(_validate_text(value, "session", 36)))
    except (ValueError, AttributeError, TypeError):
        frappe.throw(_("Invalid session identifier"), frappe.ValidationError)


def _parse_event_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp timezone is required")
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (AttributeError, TypeError, ValueError):
        frappe.throw(_("Invalid assessment timestamp"), frappe.ValidationError)


def _validate_student_course(student_id: str, school_id: str, course_id: str):
    student_id = _validate_text(student_id, "student")
    school_id = _validate_text(school_id, "school")
    course_id = _validate_text(course_id, "course")
    access_name = frappe.db.get_value(
        "AI Student School Access",
        {"student": student_id, "school_id": school_id, "course": course_id, "enabled": 1},
        "name",
    )
    if not access_name:
        frappe.throw(_("Student is not enrolled in this school's course"), frappe.PermissionError)
    if not frappe.db.exists(
        "LMS Enrollment", {"member": student_id, "course": course_id, "member_type": "Student"}
    ):
        frappe.throw(_("Student is not enrolled in this course"), frappe.PermissionError)
    return access_name


def _authorized_access(student_id: str, school_id: str, course_id: str):
    _require_service()
    return _validate_student_course(student_id, school_id, course_id)


def _require_student():
    student_id = frappe.session.user
    if student_id == "Guest" or not frappe.has_role("LMS Student"):
        frappe.throw(_("Sign in with a student account to use the AI tutor"), frappe.PermissionError)
    return _validate_text(student_id, "student")


def _resolve_student_school(student_id: str, course_id: str, school_id: str | None = None) -> str:
    course_id = _validate_text(course_id, "course")
    filters = {"student": student_id, "course": course_id, "enabled": 1}
    if school_id:
        filters["school_id"] = _validate_text(school_id, "school")
    schools = frappe.get_all(
        "AI Student School Access",
        filters=filters,
        fields=["school_id"],
        limit_page_length=2,
    )
    if not schools:
        frappe.throw(_("Student is not enrolled in this school's course"), frappe.PermissionError)
    if len(schools) > 1:
        frappe.throw(_("Choose an authorized school context for this course"), frappe.ValidationError)
    school_id = _validate_text(schools[0].school_id, "school")
    _validate_student_course(student_id, school_id, course_id)
    return school_id


def _call_engine(method: str, path: str, *, payload: dict | None = None, params: dict | None = None):
    base_url = (frappe.conf.get("ai_engine_url") or "http://ai-engine:8001").rstrip("/")
    token = frappe.conf.get("ai_engine_service_token")
    if not token:
        frappe.throw(_("AI tutor integration is not configured"), frappe.ValidationError)
    try:
        response = requests.request(
            method,
            f"{base_url}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            json=payload,
            params=params,
            timeout=(3, 25),
        )
    except requests.Timeout as exc:
        frappe.log_error("AI Engine request timed out", "AI Engine Integration")
        frappe.throw(_("The AI tutor is temporarily unavailable"), frappe.ValidationError)
    except requests.RequestException as exc:
        frappe.log_error(f"AI Engine request failed ({type(exc).__name__})", "AI Engine Integration")
        frappe.throw(_("The AI tutor is temporarily unavailable"), frappe.ValidationError)
    if response.status_code >= 400:
        frappe.log_error(f"AI Engine returned HTTP {response.status_code}", "AI Engine Integration")
        if response.status_code == 409:
            frappe.throw(_("This lesson has changed. Resume it before submitting another answer"), frappe.ValidationError)
        if response.status_code in {401, 403, 404}:
            frappe.throw(_("This lesson is not available for your account"), frappe.PermissionError)
        frappe.throw(_("The AI tutor could not complete this request"), frappe.ValidationError)
    try:
        result = response.json()
    except ValueError as exc:
        frappe.log_error("AI Engine returned invalid JSON", "AI Engine Integration")
        frappe.throw(_("The AI tutor returned an invalid response"), frappe.ValidationError)
    if not isinstance(result, dict):
        frappe.throw(_("The AI tutor returned an invalid response"), frappe.ValidationError)
    return result


@frappe.whitelist(methods=["POST"])
def get_tutor_context(
    student_id: str,
    school_id: str,
    course_id: str,
    subject: str,
    chapter: str,
    topic: str,
    language: str = "en",
):
    _authorized_access(student_id, school_id, course_id)
    subject = _validate_text(subject, "subject", 80)
    chapter = _validate_text(chapter, "chapter", 140)
    topic = _validate_text(topic, "topic", 200)
    language = _validate_text(language, "language", 24)

    concept_name = frappe.db.get_value(
        "AI Curriculum Concept",
        {"course": course_id, "chapter": chapter, "topic": topic, "subject": subject, "enabled": 1},
        "name",
    )
    if not concept_name:
        frappe.throw(_("No published curriculum concept matches this lesson"), frappe.DoesNotExistError)
    concept = frappe.get_doc("AI Curriculum Concept", concept_name)
    resources = frappe.get_all(
        "AI Educational Resource",
        filters={"concept": concept.name, "enabled": 1, "embedding_allowed": 1},
        fields=[
            "name",
            "resource_id",
            "resource_type",
            "title",
            "subject",
            "board",
            "class_level",
            "chapter",
            "topic",
            "youtube_video_id",
            "start_time",
            "duration",
            "language",
            "embedding_allowed",
        ],
        limit_page_length=100,
    )
    return {
        "concept_id": concept.name,
        "board": concept.board,
        "class_level": concept.class_level,
        "subject": concept.subject,
        "learning_objective": concept.learning_objective,
        "resources": resources,
    }


def _validate_snapshot(snapshot, student_id, school_id, course_id, session_id):
    if not isinstance(snapshot, dict) or set(snapshot) != SESSION_FIELDS:
        frappe.throw(_("Invalid session snapshot"), frappe.ValidationError)
    if (
        snapshot["student_id"] != student_id
        or snapshot["school_id"] != school_id
        or snapshot["course_id"] != course_id
        or snapshot["session_id"] != session_id
    ):
        frappe.throw(_("Session scope mismatch"), frappe.PermissionError)
    if len(json.dumps(snapshot, ensure_ascii=False)) > 160000:
        frappe.throw(_("Session snapshot is too large"), frappe.ValidationError)
    if not isinstance(snapshot["history"], list) or len(snapshot["history"]) > 200:
        frappe.throw(_("Invalid session history"), frappe.ValidationError)
    if not isinstance(snapshot["context"], dict):
        frappe.throw(_("Invalid session context"), frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def authorize_tutor_student(student_id: str, school_id: str, course_id: str):
    _authorized_access(student_id, school_id, course_id)
    return {"authorized": True}


@frappe.whitelist(methods=["POST"])
def save_tutor_session(
    school_id: str,
    student_id: str,
    course_id: str,
    session_id: str,
    snapshot: dict,
):
    _authorized_access(student_id, school_id, course_id)
    session_id = _validate_session_id(session_id)
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid session JSON"), frappe.ValidationError)
    _validate_snapshot(snapshot, student_id, school_id, course_id, session_id)
    snapshot_time = get_datetime(snapshot["updated_at"])
    existing = frappe.db.get_value(
        "AI Tutor Session",
        {"session_id": session_id},
        ["name", "school_id", "student", "course"],
        as_dict=True,
    )
    if existing and (
        existing.school_id != school_id
        or existing.student != student_id
        or existing.course != course_id
    ):
        frappe.throw(_("Session scope mismatch"), frappe.PermissionError)
    values = {
        "school_id": school_id,
        "student": student_id,
        "course": course_id,
        "subject": snapshot["subject"],
        "chapter": snapshot["chapter"],
        "topic": snapshot["topic"],
        "state": snapshot["state"],
        "completed": int(bool(snapshot["completed"])),
        "snapshot_updated_at": snapshot_time,
        "session_json": json.dumps(snapshot, ensure_ascii=False),
    }
    if existing:
        doc = frappe.get_doc("AI Tutor Session", existing.name)
        if get_datetime(doc.snapshot_updated_at) >= snapshot_time:
            return {"saved": True, "duplicate": True, "session_id": session_id}
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": "AI Tutor Session", "session_id": session_id, **values})
        doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"saved": True, "duplicate": False, "session_id": session_id}


@frappe.whitelist(methods=["GET"])
def get_tutor_session(
    school_id: str,
    student_id: str,
    session_id: str,
):
    _require_service()
    school_id = _validate_text(school_id, "school")
    student_id = _validate_text(student_id, "student")
    session_id = _validate_session_id(session_id)
    row = frappe.db.get_value(
        "AI Tutor Session",
        {"session_id": session_id, "school_id": school_id, "student": student_id},
        ["session_json", "course"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Session not found"), frappe.DoesNotExistError)
    _authorized_access(student_id, school_id, row.course)
    snapshot = json.loads(row.session_json)
    if snapshot.get("session_id") != session_id or snapshot.get("course_id") != row.course:
        frappe.throw(_("Invalid session record"), frappe.ValidationError)
    return snapshot


def _update_profile(school_id: str, student_id: str, course_id: str, session_id: str, event: dict):
    if event["event_type"] != "assessment":
        return
    attempts = event.get("attempts")
    correct_attempts = event.get("correct_attempts")
    correct_streak = event.get("correct_streak")
    if (
        type(attempts) is not int
        or type(correct_attempts) is not int
        or type(correct_streak) is not int
        or attempts < 1
        or correct_attempts < 0
        or correct_attempts > attempts
        or correct_streak < 0
        or type(event.get("correct")) is not bool
        or type(event.get("completed")) is not bool
        or event.get("mastery_status") not in {"needs_review", "developing", "mastered"}
        or type(event.get("score")) not in {int, float}
        or not 0 <= event["score"] <= 1
        or not isinstance(event.get("occurred_at"), str)
    ):
        frappe.throw(_("Invalid assessment progress"), frappe.ValidationError)
    event_time = _parse_event_time(event["occurred_at"])


    profile_key = hashlib.sha256(f"{school_id}\0{student_id}".encode()).hexdigest()
    profile_name = frappe.db.get_value("AI Student Learning Profile", {"profile_key": profile_key}, "name")
    if profile_name:
        profile = frappe.get_doc("AI Student Learning Profile", profile_name)
        profile_data = json.loads(profile.profile_json or "{}")
    else:
        profile = frappe.new_doc("AI Student Learning Profile")
        profile.profile_key = profile_key
        profile.student = student_id
        profile.school_id = school_id
        profile_data = {"concepts": [], "recommended_next_lesson": None}

    concepts = profile_data.setdefault("concepts", [])
    concept_id = _validate_text(event.get("concept_id"), "concept", 140)
    concept = next((item for item in concepts if item.get("concept_id") == concept_id), None)
    if concept is None:
        concept = {"concept_id": concept_id, "attempts": 0, "correct_attempts": 0, "sessions": {}}
        concepts.append(concept)

    session_progress = concept.setdefault("sessions", {})
    previous = session_progress.get(session_id, {"attempts": 0, "correct_attempts": 0})
    attempt_delta = max(0, attempts - previous["attempts"])
    correct_delta = max(0, correct_attempts - previous["correct_attempts"])
    concept["attempts"] = max(0, concept.get("attempts", 0) + attempt_delta)
    concept["correct_attempts"] = max(0, concept.get("correct_attempts", 0) + correct_delta)
    session_progress[session_id] = {
        "attempts": max(attempts, previous["attempts"]),
        "correct_attempts": max(correct_attempts, previous["correct_attempts"]),
        "completed": bool(event["completed"] or previous.get("completed", False)),
    }
    latest_event_time = _parse_event_time(concept["latest_event_at"]) if concept.get("latest_event_at") else None
    if latest_event_time is None or event_time >= latest_event_time:
        concept.update(
            {
                "course_id": course_id,
                "correct_streak": correct_streak,
                "status": event["mastery_status"],
                "latest_event_at": event["occurred_at"],
            }
        )
    concept["score"] = round(concept["correct_attempts"] / max(concept["attempts"], 1), 4)

    progress_by_concept = {item.get("concept_id"): item for item in concepts}
    curriculum = frappe.get_all(
        "AI Curriculum Concept",
        filters={"course": course_id, "enabled": 1},
        fields=["name", "board", "class_level", "subject", "chapter", "topic", "sequence"],
        order_by="sequence asc",
        limit_page_length=500,
    )
    recommended = next(
        (
            {
                "concept_id": item.name,
                "course_id": course_id,
                "board": item.board,
                "class_level": item.class_level,
                "subject": item.subject,
                "chapter": item.chapter,
                "topic": item.topic,
            }
            for item in curriculum
            if progress_by_concept.get(item.name, {}).get("status") != "mastered"
        ),
        None,
    )
    profile_data["concepts"] = concepts
    profile_data["recommended_next_lesson"] = recommended
    profile.profile_json = json.dumps(profile_data, ensure_ascii=False)
    profile.save(ignore_permissions=True) if profile_name else profile.insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def save_tutor_event(
    school_id: str,
    student_id: str,
    course_id: str,
    session_id: str,
    event: dict,
):
    _authorized_access(student_id, school_id, course_id)
    session_id = _validate_session_id(session_id)
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid event JSON"), frappe.ValidationError)
    if (
        not isinstance(event, dict)
        or set(event) - ALLOWED_EVENT_FIELDS
        or len(json.dumps(event, ensure_ascii=False)) > 4000
        or not event.get("event_id")
        or event.get("event_type") not in {"session_started", "lesson_message", "assessment", "hint", "session_resumed"}
    ):
        frappe.throw(_("Invalid or oversized event"), frappe.ValidationError)
    event["event_id"] = _validate_text(event["event_id"], "event id", 140)

    existing = frappe.db.get_value(
        "AI Tutor Event",
        {"event_id": event["event_id"]},
        ["name", "school_id", "student", "session_id"],
        as_dict=True,
    )
    if existing:
        if (
            existing.school_id != school_id
            or existing.student != student_id
            or existing.session_id != session_id
        ):
            frappe.throw(_("Event scope mismatch"), frappe.PermissionError)
        return {"saved": True, "event_id": existing.name, "duplicate": True}
    if not frappe.db.exists(
        "AI Tutor Session",
        {"session_id": session_id, "school_id": school_id, "student": student_id, "course": course_id},
    ):
        frappe.throw(_("Session not found"), frappe.DoesNotExistError)

    row = frappe.get_doc(
        {
            "doctype": "AI Tutor Event",
            "event_id": event["event_id"],
            "school_id": school_id,
            "student": student_id,
            "course": course_id,
            "session_id": session_id,
            "event_type": event["event_type"],
            "concept_id": event.get("concept_id", ""),
            "event_json": json.dumps(event, ensure_ascii=False),
        }
    )
    row.insert(ignore_permissions=True)
    _update_profile(school_id, student_id, course_id, session_id, event)
    frappe.db.commit()
    return {"saved": True, "event_id": row.name, "duplicate": False}


@frappe.whitelist(methods=["GET"])
def get_learning_profile(student_id: str, school_id: str):
    _require_service()
    student_id = _validate_text(student_id, "student")
    school_id = _validate_text(school_id, "school")
    accesses = frappe.get_all(
        "AI Student School Access",
        filters={"student": student_id, "school_id": school_id, "enabled": 1},
        fields=["course"],
        limit_page_length=100,
    )
    enrolled = any(
        frappe.db.exists(
            "LMS Enrollment", {"member": student_id, "course": item.course, "member_type": "Student"}
        )
        for item in accesses
    )
    if not enrolled:
        frappe.throw(_("Student is not linked to this school"), frappe.PermissionError)
    profile_key = hashlib.sha256(f"{school_id}\0{student_id}".encode()).hexdigest()
    row = frappe.db.get_value(
        "AI Student Learning Profile", {"profile_key": profile_key}, "profile_json"
    )
    profile = json.loads(row) if row else {"concepts": [], "recommended_next_lesson": None}
    profile["concepts"] = [
        {key: value for key, value in concept.items() if key != "sessions"}
        for concept in profile.get("concepts", [])
    ]
    return profile


def _student_session_scope(session_id: str, course_id: str, school_id: str | None):
    student_id = _require_student()
    session_id = _validate_session_id(session_id)
    course_id = _validate_text(course_id, "course", 140)
    school_id = _resolve_student_school(student_id, course_id, school_id)
    return student_id, school_id, course_id, session_id


@frappe.whitelist(methods=["POST"])
def start_tutor_lesson(
    course_id: str,
    subject: str,
    chapter: str,
    topic: str,
    school_id: str | None = None,
    language: str = "en",
):
    student_id = _require_student()
    school_id = _resolve_student_school(student_id, course_id, school_id)
    payload = {
        "student_id": student_id,
        "school_id": school_id,
        "course_id": _validate_text(course_id, "course", 140),
        "subject": _validate_text(subject, "subject", 80),
        "chapter": _validate_text(chapter, "chapter", 140),
        "topic": _validate_text(topic, "topic", 200),
        "language": _validate_text(language, "language", 24),
    }
    return _call_engine("POST", "/api/v1/sessions", payload=payload)


@frappe.whitelist(methods=["POST"])
def submit_tutor_answer(
    session_id: str,
    course_id: str,
    question_id: str,
    answer: str,
    school_id: str | None = None,
):
    student_id, school_id, _, session_id = _student_session_scope(session_id, course_id, school_id)
    return _call_engine(
        "POST",
        f"/api/v1/sessions/{session_id}/answer",
        payload={
            "question_id": _validate_text(question_id, "question", 140),
            "answer": _validate_text(answer, "answer", 4000),
        },
        params={"student_id": student_id, "school_id": school_id},
    )


@frappe.whitelist(methods=["POST"])
def send_tutor_message(
    session_id: str,
    course_id: str,
    text: str,
    school_id: str | None = None,
):
    student_id, school_id, _, session_id = _student_session_scope(session_id, course_id, school_id)
    return _call_engine(
        "POST",
        f"/api/v1/sessions/{session_id}/message",
        payload={"text": _validate_text(text, "message", 4000)},
        params={"student_id": student_id, "school_id": school_id},
    )


@frappe.whitelist(methods=["POST"])
def request_tutor_hint(session_id: str, course_id: str, school_id: str | None = None):
    student_id, school_id, _, session_id = _student_session_scope(session_id, course_id, school_id)
    return _call_engine(
        "POST",
        f"/api/v1/sessions/{session_id}/hint",
        params={"student_id": student_id, "school_id": school_id},
    )


@frappe.whitelist(methods=["POST"])
def resume_tutor_lesson(session_id: str, course_id: str, school_id: str | None = None):
    student_id, school_id, _, session_id = _student_session_scope(session_id, course_id, school_id)
    return _call_engine(
        "POST",
        f"/api/v1/sessions/{session_id}/resume",
        params={"student_id": student_id, "school_id": school_id},
    )


@frappe.whitelist(methods=["GET"])
def get_student_tutor_session(session_id: str, course_id: str, school_id: str | None = None):
    student_id, school_id, _, session_id = _student_session_scope(session_id, course_id, school_id)
    return _call_engine(
        "GET",
        f"/api/v1/sessions/{session_id}",
        params={"student_id": student_id, "school_id": school_id},
    )


@frappe.whitelist(methods=["GET"])
def get_student_learning_profile(school_id: str | None = None):
    student_id = _require_student()
    filters = {"student": student_id, "enabled": 1}
    if school_id:
        filters["school_id"] = _validate_text(school_id, "school")
    accesses = frappe.get_all(
        "AI Student School Access",
        filters=filters,
        fields=["school_id", "course"],
        limit_page_length=100,
    )
    enrolled_schools = {
        item.school_id
        for item in accesses
        if frappe.db.exists(
            "LMS Enrollment", {"member": student_id, "course": item.course, "member_type": "Student"}
        )
    }
    if not enrolled_schools:
        frappe.throw(_("No authorized school profile is available"), frappe.PermissionError)
    if len(enrolled_schools) > 1:
        frappe.throw(_("Choose an authorized school context"), frappe.ValidationError)
    selected_school = next(iter(enrolled_schools))
    return _call_engine(
        "GET",
        f"/api/v1/students/{quote(student_id, safe='')}/learning-profile",
        params={"school_id": selected_school},
    )
