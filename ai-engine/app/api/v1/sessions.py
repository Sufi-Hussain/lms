import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import enforce_rate_limit
from app.core.security import require_service_token
from app.integrations.frappe_client import FrappeClient
from app.models.outbox import TutorOutboxEvent
from app.models.schemas import AnswerInput, MessageInput, SessionCreate, SessionView, TutorResponse
from app.models.session import TutorSession
from app.services.orchestrator import InactiveQuestionError, TutorOrchestrator
from app.services.outbox import deliver_items

router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_service_token), Depends(enforce_rate_limit)],
    tags=["tutor sessions"],
)
frappe_client = FrappeClient()
orchestrator = TutorOrchestrator(frappe_client)


def _validate_message_length(value: str) -> None:
    if len(value) > settings.max_message_chars:
        raise HTTPException(
            status_code=413,
            detail={"code": "message_too_long", "message": "The message exceeds the configured length limit"},
        )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _session_snapshot(session: TutorSession) -> dict:
    return {
        "session_id": session.id,
        "school_id": session.school_id,
        "student_id": session.student_id,
        "course_id": session.course_id,
        "subject": session.subject,
        "chapter": session.chapter,
        "topic": session.topic,
        "state": session.state,
        "history": session.history[-200:],
        "attempts": session.attempts,
        "correct_attempts": session.correct_attempts,
        "completed": session.completed,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "context": session.context,
    }


def _progress_event(session: TutorSession, event_type: str, response: TutorResponse) -> dict:
    mastery = response.mastery_update
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": session.updated_at.isoformat(),
        "concept_id": str(session.context.get("concept_id", session.topic)),
        "correct": response.correct,
        "attempts": mastery.attempts if mastery else session.attempts,
        "correct_attempts": session.correct_attempts,
        "correct_streak": mastery.correct_streak if mastery else int(session.context.get("correct_streak", 0)),
        "score": mastery.score if mastery else 0.0,
        "mastery_status": mastery.status if mastery else "developing",
        "completed": session.completed,
        "session_state": session.state,
    }


async def _queue_and_sync(
    db: Session, session: TutorSession, event_type: str, response: TutorResponse
) -> TutorResponse:
    session.updated_at = datetime.now(timezone.utc)
    snapshot_payload = {
        "school_id": session.school_id,
        "student_id": session.student_id,
        "course_id": session.course_id,
        "session_id": session.id,
        "snapshot": _session_snapshot(session),
    }
    event_payload = {
        "school_id": session.school_id,
        "student_id": session.student_id,
        "course_id": session.course_id,
        "session_id": session.id,
        "event": _progress_event(session, event_type, response),
    }
    items = [
        TutorOutboxEvent(
            id=str(uuid.uuid4()),
            kind="session_snapshot",
            payload=snapshot_payload,
        ),
        TutorOutboxEvent(
            id=str(uuid.uuid4()),
            kind="progress_event",
            payload=event_payload,
        ),
    ]
    db.add_all(items)
    db.commit()
    delivered = await deliver_items(db, items)
    response.sync_status = "synced" if delivered else "pending"
    return response


async def _load_owned_session(
    db: Session,
    session_id: str,
    school_id: str,
    student_id: str,
    *,
    for_update: bool = False,
) -> TutorSession:
    statement = select(TutorSession).where(
        TutorSession.id == session_id,
        TutorSession.school_id == school_id,
        TutorSession.student_id == student_id,
    )
    if for_update:
        statement = statement.with_for_update()
    session = db.scalar(statement)
    if not session:
        try:
            snapshot = await frappe_client.get_tutor_session(
                student_id=student_id,
                school_id=school_id,
                session_id=session_id,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403, 404}:
                raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Session not found"}) from exc
            raise HTTPException(status_code=502, detail={"code": "lms_unavailable", "message": "The LMS could not restore this session"}) from exc
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail={"code": "lms_unavailable", "message": "The LMS could not restore this session"}) from exc
        context = snapshot.get("context")
        history = snapshot.get("history")
        if (
            snapshot.get("session_id") != session_id
            or snapshot.get("student_id") != student_id
            or snapshot.get("school_id") != school_id
            or not isinstance(context, dict)
            or not isinstance(history, list)
        ):
            raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Session not found"})
        active_question = context.get("active_question")
        session = TutorSession(
            id=session_id,
            student_id=student_id,
            school_id=school_id,
            course_id=snapshot["course_id"],
            subject=snapshot["subject"],
            chapter=snapshot["chapter"],
            topic=snapshot["topic"],
            state=snapshot["state"],
            history=history,
            context=context,
            current_question_id=active_question.get("question_id") if isinstance(active_question, dict) else None,
            attempts=snapshot["attempts"],
            correct_attempts=snapshot["correct_attempts"],
            completed=snapshot["completed"],
            created_at=_parse_datetime(snapshot["created_at"]),
            updated_at=_parse_datetime(snapshot["updated_at"]),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    try:
        await frappe_client.authorize_student(
            student_id=student_id,
            school_id=school_id,
            course_id=session.course_id,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403, 404}:
            raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Session not found"}) from exc
        raise HTTPException(status_code=502, detail={"code": "lms_unavailable", "message": "The LMS could not authorize this session"}) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail={"code": "lms_unavailable", "message": "The LMS could not authorize this session"}) from exc
    return session


@router.post("/sessions", response_model=TutorResponse, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    try:
        response = await orchestrator.start(db, payload)
        session = db.get(TutorSession, response.session_id)
        return await _queue_and_sync(db, session, "session_started", response)
    except httpx.HTTPStatusError as exc:
        db.rollback()
        status_code = 403 if exc.response.status_code in {401, 403} else 404 if exc.response.status_code == 404 else 503
        code = "enrollment_required" if status_code == 403 else "lesson_unavailable"
        raise HTTPException(status_code=status_code, detail={"code": code, "message": "The lesson could not be prepared"}) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "lesson_unavailable", "message": "The lesson could not be prepared. Check LMS curriculum and model configuration."},
        ) from exc


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(
    session_id: str,
    school_id: str = Query(min_length=1, max_length=140),
    student_id: str = Query(min_length=1, max_length=140),
    db: Session = Depends(get_db),
):
    return await _load_owned_session(db, session_id, school_id, student_id)


@router.post("/sessions/{session_id}/message", response_model=TutorResponse)
async def message(
    session_id: str,
    payload: MessageInput,
    school_id: str = Query(min_length=1, max_length=140),
    student_id: str = Query(min_length=1, max_length=140),
    db: Session = Depends(get_db),
):
    _validate_message_length(payload.text)
    session = await _load_owned_session(db, session_id, school_id, student_id, for_update=True)
    try:
        response = await orchestrator.message(db, session, payload.text)
        return await _queue_and_sync(db, session, "lesson_message", response)
    except InactiveQuestionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "session_completed", "message": str(exc)}) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail={"code": "tutor_unavailable", "message": "The tutor could not respond right now"}) from exc


@router.post("/sessions/{session_id}/answer", response_model=TutorResponse)
async def answer(
    session_id: str,
    payload: AnswerInput,
    school_id: str = Query(min_length=1, max_length=140),
    student_id: str = Query(min_length=1, max_length=140),
    db: Session = Depends(get_db),
):
    _validate_message_length(payload.answer)
    session = await _load_owned_session(db, session_id, school_id, student_id, for_update=True)
    try:
        response = await orchestrator.answer(db, session, payload.question_id, payload.answer)
        return await _queue_and_sync(db, session, "assessment", response)
    except InactiveQuestionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "stale_question", "message": str(exc)}) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail={"code": "assessment_unavailable", "message": "The answer could not be evaluated right now"}) from exc


@router.post("/sessions/{session_id}/hint", response_model=TutorResponse)
async def hint(
    session_id: str,
    school_id: str = Query(min_length=1, max_length=140),
    student_id: str = Query(min_length=1, max_length=140),
    db: Session = Depends(get_db),
):
    session = await _load_owned_session(db, session_id, school_id, student_id, for_update=True)
    try:
        response = orchestrator.hint(db, session)
        return await _queue_and_sync(db, session, "hint", response)
    except InactiveQuestionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "session_completed", "message": str(exc)}) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail={"code": "progress_sync_failed", "message": "The hint could not be saved"}) from exc


@router.post("/sessions/{session_id}/resume", response_model=TutorResponse)
async def resume(
    session_id: str,
    school_id: str = Query(min_length=1, max_length=140),
    student_id: str = Query(min_length=1, max_length=140),
    db: Session = Depends(get_db),
):
    session = await _load_owned_session(db, session_id, school_id, student_id, for_update=True)
    try:
        response = await orchestrator.resume(db, session)
        return await _queue_and_sync(db, session, "session_resumed", response)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail={"code": "tutor_unavailable", "message": "The lesson could not be resumed right now"}) from exc
