import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class GeneratedOption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=500)


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=8, max_length=1200)
    expected_answer: str = Field(min_length=1, max_length=1200)
    hint: str = Field(min_length=1, max_length=600)
    explanation: str = Field(min_length=1, max_length=1600)
    question_type: Literal["short_answer", "numerical", "mcq", "assertion_reason", "fill_in_blank"] = "short_answer"
    options: list[GeneratedOption] = Field(default_factory=list, max_length=6)
    tolerance: float = Field(default=0, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_question_shape(self):
        if self.question_type in {"mcq", "assertion_reason"}:
            ids = [option.id.casefold() for option in self.options]
            if len(self.options) < 2 or len(ids) != len(set(ids)):
                raise ValueError("Choice questions need at least two uniquely identified options")
            if self.expected_answer.casefold() not in ids:
                raise ValueError("Choice question expected_answer must reference an option id")
        elif self.options:
            raise ValueError("Options are only valid for choice questions")
        if self.question_type == "numerical":
            try:
                number = float(self.expected_answer.replace(",", ""))
            except ValueError as exc:
                raise ValueError("Numerical expected_answer must be numeric") from exc
            if not math.isfinite(number):
                raise ValueError("Numerical expected_answer must be finite")
        if not math.isfinite(self.tolerance):
            raise ValueError("Question tolerance must be finite")
        return self


def validate_generated_question(raw: str | dict) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        question = GeneratedQuestion.model_validate(value)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ValueError("The teaching provider returned an invalid question") from exc
    return question.model_dump()
