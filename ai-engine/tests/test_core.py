import pytest
from app.assessment.answer_evaluator import evaluate
from app.resources.youtube_catalog import select_resource
from app.teaching.strategies import difficulty_for
from app.models.schemas import TutorResponse


def test_answer_evaluation_is_case_and_space_insensitive():
    assert evaluate("  GRAVITATION ", "gravitation")[0] is True
    assert evaluate("magnetism", "gravitation")[0] is False


def test_unapproved_video_is_never_selected():
    resources = [{"resource_id": "unapproved", "resource_type": "youtube", "youtube_video_id": "dQw4w9WgXcQ", "embedding_allowed": False}]
    assert select_resource(resources, subject="physics", topic="gravity") is None


def test_approved_video_requires_catalogue_id_and_valid_video_id():
    resource = {"resource_id": "lesson-1", "resource_type": "youtube", "youtube_video_id": "dQw4w9WgXcQ", "embedding_allowed": True, "subject": "physics", "topic": "gravity", "start_time": 15}
    result = select_resource([resource], subject="physics", topic="gravity")
    assert result is not None
    assert result["resource_id"] == "lesson-1"
    assert result["start_time"] == 15


def test_difficulty_increases_with_performance():
    assert difficulty_for(0, 0) == "grade-appropriate"
    assert difficulty_for(4, 4) == "challenging"


def test_response_protocol_rejects_invalid_states():
    with pytest.raises(Exception):
        TutorResponse.model_validate({"session_id": "x", "state": "random", "teacher_message": {"text": "Hi"}, "wait_for_student": True, "next_action": "WAIT"})
