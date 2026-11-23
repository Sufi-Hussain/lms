import asyncio

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.assessment.answer_evaluator import evaluate_deterministically, validate_model_assessment
from app.assessment.question_generator import validate_generated_question
from app.core.database import Base
from app.core.privacy import redact_student_text
from app.core.security import require_service_token
from app.models.outbox import TutorOutboxEvent
from app.models.schemas import SessionCreate, VisualResource
from app.models.session import TutorSession
from app.resources.youtube_catalog import select_resource
from app.services import orchestrator as orchestrator_module
from app.services.orchestrator import InactiveQuestionError, TutorOrchestrator
from app.ai.providers.mock import MockProvider


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


class FakeFrappe:
    async def get_lesson_context(self, payload):
        return {
            "concept_id": "concept-gravity",
            "board": "CBSE",
            "class_level": 8,
            "subject": payload["subject"],
            "learning_objective": "Explain how gravity pulls objects toward Earth.",
            "resources": [],
        }


@pytest.fixture
def tutor(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "get_provider", lambda: MockProvider())
    return TutorOrchestrator(FakeFrappe())


def lesson_request():
    return SessionCreate(
        student_id="student-1",
        school_id="school-1",
        course_id="course-1",
        subject="Physics",
        chapter="Gravity",
        topic="Gravitational force",
        language="en",
    )


def test_session_start_answer_and_mastery(db, tutor):
    response = asyncio.run(tutor.start(db, lesson_request()))
    session = db.get(TutorSession, response.session_id)
    assert response.wait_for_student is True
    assert response.interaction is not None
    assert response.interaction.question_id == session.current_question_id
    db.commit()

    for expected_attempt in range(1, 4):
        question = session.context["active_question"]
        response = asyncio.run(
            tutor.answer(db, session, question["question_id"], question["expected_answer"])
        )
        db.commit()
        assert response.mastery_update.attempts == expected_attempt

    assert response.completed is True
    assert response.state == "COMPLETED"
    assert response.next_action == "COMPLETE"
    assert session.correct_attempts == 3
    with pytest.raises(InactiveQuestionError):
        asyncio.run(tutor.answer(db, session, "stale-question", "answer"))


def test_session_resumes_active_question(db, tutor):
    initial = asyncio.run(tutor.start(db, lesson_request()))
    session = db.get(TutorSession, initial.session_id)
    db.commit()

    resumed = asyncio.run(tutor.resume(db, session))
    assert resumed.state == "INTERACTIVE_QUESTION"
    assert resumed.interaction.question_id == initial.interaction.question_id
    assert resumed.wait_for_student is True


def test_llm_provider_failure_does_not_create_partial_session(db, tutor):
    class BrokenProvider:
        async def explain(self, **kwargs):
            raise RuntimeError("provider unavailable")

    tutor.provider = BrokenProvider()
    with pytest.raises(RuntimeError):
        asyncio.run(tutor.start(db, lesson_request()))
    assert db.query(TutorSession).count() == 0


def test_invalid_model_assessment_is_rejected():
    with pytest.raises(ValueError):
        validate_model_assessment({"correct": "yes", "feedback": "Try again"})


def test_student_pii_is_redacted_before_history_and_provider(db, tutor):
    initial = asyncio.run(tutor.start(db, lesson_request()))
    session = db.get(TutorSession, initial.session_id)
    message = "My email is learner@example.com and my phone is +1 555 234 9876"

    asyncio.run(tutor.message(db, session, message))

    stored = session.history[-2]["text"]
    assert "learner@example.com" not in stored
    assert "555 234 9876" not in stored
    assert "[email redacted]" in stored
    assert "[phone redacted]" in stored


def test_stale_question_is_rejected(db, tutor):
    initial = asyncio.run(tutor.start(db, lesson_request()))
    session = db.get(TutorSession, initial.session_id)
    session.current_question_id = "another-question"

    with pytest.raises(InactiveQuestionError):
        asyncio.run(tutor.answer(db, session, initial.interaction.question_id, "answer"))


def test_choice_and_numerical_answers_are_deterministic():
    mcq = {
        "question_type": "assertion_reason",
        "expected_answer": "B",
        "options": [{"id": "A", "text": "Incorrect"}, {"id": "B", "text": "Correct"}],
    }
    numerical = {"question_type": "numerical", "expected_answer": "9.8", "tolerance": 0.05}

    assert evaluate_deterministically("Correct", mcq) is True
    assert evaluate_deterministically("9.81 m/s²", numerical) is True
    assert evaluate_deterministically("10", numerical) is False


def test_generated_choice_question_requires_known_option():
    question = {
        "question": "Which force attracts objects toward Earth?",
        "expected_answer": "B",
        "hint": "Think about the force that keeps us on the ground.",
        "explanation": "Gravity attracts objects with mass.",
        "question_type": "assertion_reason",
        "options": [{"id": "A", "text": "Friction"}, {"id": "B", "text": "Gravity"}],
        "tolerance": 0,
    }

    validated = validate_generated_question(question)
    assert validated["expected_answer"] == "B"
    with pytest.raises(ValueError):
        validate_generated_question({**question, "expected_answer": "C"})


def test_only_approved_catalogued_youtube_resources_are_selected():
    candidates = [
        {
            "resource_id": "unapproved",
            "resource_type": "youtube",
            "title": "Unapproved video",
            "youtube_video_id": "abcdefghijk",
            "subject": "Physics",
            "topic": "Gravity",
            "embedding_allowed": 0,
        },
        {
            "resource_id": "approved",
            "resource_type": "youtube",
            "title": "Approved video",
            "youtube_video_id": "abcdefghijk",
            "subject": "Physics",
            "topic": "Gravity",
            "embedding_allowed": 1,
        },
    ]

    selected = select_resource(candidates, subject="physics", topic="gravity")
    assert selected["resource_id"] == "approved"
    assert selected["video_id"] == "abcdefghijk"
    assert VisualResource.model_validate(selected).type == "youtube"
    assert select_resource(candidates[:1], subject="physics", topic="gravity") is None


def test_invalid_service_auth_is_rejected(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "service_token", "secret-value")
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_service_token("secret-value"))
    assert error.value.status_code == 401

    asyncio.run(require_service_token("Bearer secret-value"))


def test_outbox_keeps_failed_sync_for_retry(db, monkeypatch):
    from app.services import outbox as outbox_module

    class OfflineFrappe:
        async def save_tutor_session(self, payload):
            raise httpx.ConnectError("offline")

    item = TutorOutboxEvent(
        id="outbox-1",
        kind="session_snapshot",
        payload={},
    )
    db.add(item)
    db.commit()
    monkeypatch.setattr(outbox_module, "frappe_client", OfflineFrappe())

    delivered = asyncio.run(outbox_module.deliver_one(db, item))

    assert delivered is False
    assert item.delivered_at is None
    assert item.attempts == 1
    assert item.next_attempt_at is not None


def test_privacy_redaction_masks_common_contact_details():
    safe = redact_student_text("Reach me at student@example.org or +44 20 1234 5678")
    assert "student@example.org" not in safe
    assert "20 1234 5678" not in safe
