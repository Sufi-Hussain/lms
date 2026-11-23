import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError


class ModelAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    correct: StrictBool
    feedback: str = Field(min_length=1, max_length=2000)


def normalize(answer: str) -> str:
    return " ".join(answer.casefold().strip().split()).rstrip(".?!")


def evaluate_deterministically(answer: str, question: dict) -> bool | None:
    question_type = question.get("question_type", "short_answer")
    expected = str(question.get("expected_answer", ""))
    if question_type in {"mcq", "assertion_reason"}:
        normalized = normalize(answer)
        if normalized == normalize(expected):
            return True
        option = next((item for item in question.get("options", []) if normalized in {normalize(item["id"]), normalize(item["text"])}), None)
        return option is not None and normalize(option["id"]) == normalize(expected)
    if question_type == "numerical":
        expected_match = re.search(r"[-+]?(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", expected)
        answer_match = re.search(r"[-+]?(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", answer)
        if not expected_match or not answer_match:
            return False
        try:
            target = float(expected_match.group().replace(",", ""))
            actual = float(answer_match.group().replace(",", ""))
            return math.isfinite(actual) and math.isclose(actual, target, rel_tol=0, abs_tol=float(question.get("tolerance", 0)))
        except (ValueError, OverflowError):
            return False
    return None


def exact_mock_evaluation(answer: str, expected: str) -> bool:
    return normalize(answer) == normalize(expected)


def validate_model_assessment(raw: str | dict) -> ModelAssessment:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return ModelAssessment.model_validate(value)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ValueError("The teaching provider returned an invalid assessment") from exc
