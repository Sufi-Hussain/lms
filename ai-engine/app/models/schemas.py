from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    student_id: str = Field(min_length=1, max_length=140)
    school_id: str = Field(min_length=1, max_length=140)
    course_id: str = Field(min_length=1, max_length=140)
    subject: str = Field(min_length=1, max_length=80)
    chapter: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=200)
    language: str = Field(default="en", min_length=2, max_length=24)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=4000)


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question_id: str = Field(min_length=1, max_length=140)
    answer: str = Field(min_length=1, max_length=4000)


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=500)


class Interaction(BaseModel):
    question_id: str = Field(min_length=1, max_length=140)
    type: Literal["short_answer", "numerical", "mcq", "assertion_reason", "fill_in_blank"]
    answer_type: Literal["short_text", "number", "choice"]
    question: str = Field(min_length=1, max_length=1200)
    options: list[QuestionOption] = Field(default_factory=list, max_length=6)
    hint_available: bool = True


class TeacherMessage(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    language: str = Field(min_length=2, max_length=24)
    format: Literal["plain_text", "markdown"] = "plain_text"


class VisualResource(BaseModel):
    type: Literal["youtube", "diagram", "animation", "simulation"]
    resource_id: str = Field(min_length=1, max_length=140)
    title: str = Field(min_length=1, max_length=300)
    video_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{11}$")
    start_time: int = Field(default=0, ge=0)
    duration: int | None = Field(default=None, ge=0)
    language: str | None = Field(default=None, max_length=24)


class MasteryUpdate(BaseModel):
    concept_id: str
    status: Literal["needs_review", "developing", "mastered"]
    score: float = Field(ge=0, le=1)
    correct: bool | None = None
    correct_streak: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)


class TutorResponse(BaseModel):
    session_id: str
    state: Literal[
        "INTRODUCTION",
        "EXPLANATION",
        "EXAMPLE",
        "VISUAL_LEARNING",
        "INTERACTIVE_QUESTION",
        "WAITING_FOR_RESPONSE",
        "EVALUATION",
        "REMEDIATION",
        "PRACTICE",
        "SUMMARY",
        "COMPLETED",
    ]
    teacher_message: TeacherMessage
    visual: VisualResource | None = None
    interaction: Interaction | None = None
    wait_for_student: bool = False
    mastery_update: MasteryUpdate | None = None
    correct: bool | None = None
    next_action: Literal["WAIT_FOR_ANSWER", "CONTINUE_LESSON", "COMPLETE"]
    completed: bool = False
    sync_status: Literal["synced", "pending"] = "synced"


class SessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    school_id: str
    course_id: str
    subject: str
    chapter: str
    topic: str
    state: str
    history: list[dict]
    attempts: int
    correct_attempts: int
    completed: bool
    created_at: datetime
    updated_at: datetime


class LearningProfile(BaseModel):
    student_id: str
    school_id: str
    concepts: list[dict] = Field(default_factory=list)
    recommended_next_lesson: dict | None = None
