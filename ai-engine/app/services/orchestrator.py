import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_provider
from app.assessment.answer_evaluator import (
    evaluate_deterministically,
    validate_model_assessment,
)
from app.assessment.question_generator import validate_generated_question
from app.models.schemas import (
    Interaction,
    MasteryUpdate,
    QuestionOption,
    SessionCreate,
    TeacherMessage,
    TutorResponse,
    VisualResource,
)
from app.models.session import TutorSession
from app.core.privacy import redact_student_text
from app.resources.youtube_catalog import select_resource
from app.teaching.strategies import STRATEGIES, difficulty_for


class InactiveQuestionError(ValueError):
    pass


def deterministic_feedback(correct: bool, language: str) -> str:
    messages = {
        "en": ("That is correct. Let’s build on that idea.", "Not quite yet. Use the hint to review the key idea, then try again."),
        "hi": ("सही है। अब इस विचार पर आगे बढ़ते हैं।", "अभी सही नहीं है। संकेत देखें और फिर से प्रयास करें।"),
        "es": ("Correcto. Sigamos desarrollando esa idea.", "Aún no. Revisa la pista y vuelve a intentarlo."),
    }
    pair = messages.get(language.split("-")[0].lower(), messages["en"])
    return pair[0 if correct else 1]


class TutorOrchestrator:
    def __init__(self, frappe_client):
        self.frappe = frappe_client
        self.provider = get_provider()

    async def start(self, db: Session, data: SessionCreate) -> TutorResponse:
        context = await self.frappe.get_lesson_context(data.model_dump())
        objective = self._objective(context)
        language = data.language
        difficulty = "foundation"
        approach = STRATEGIES["INTRODUCTION"]
        teacher_message = await self.provider.explain(
            objective=f"{objective}\nTeaching approach: {approach}",
            student_input=None,
            difficulty=difficulty,
            language=language,
        )
        question = await self._generate_question(
            objective=objective,
            difficulty=difficulty,
            language=language,
            previous_questions=[],
        )
        visual_resource = select_resource(
            context.get("resources", []),
            subject=data.subject,
            topic=data.topic,
            language=language,
            class_level=context.get("class_level"),
            concept_id=context.get("concept_id"),
        )
        context = {
            **{key: value for key, value in context.items() if key != "resources"},
            "language": language,
            "visual_resource": visual_resource,
            "active_question": question,
            "previous_questions": [question["question"]],
            "correct_streak": 0,
            "hint_count": 0,
        }
        session = TutorSession(
            id=str(uuid.uuid4()),
            student_id=data.student_id,
            school_id=data.school_id,
            course_id=data.course_id,
            subject=data.subject,
            chapter=data.chapter,
            topic=data.topic,
            state="INTERACTIVE_QUESTION",
            context=context,
            history=[{"role": "teacher", "text": teacher_message}],
            current_question_id=question["question_id"],
        )
        db.add(session)
        db.flush()
        db.refresh(session)
        return self._response(session, teacher_message)

    async def message(self, db: Session, session: TutorSession, text: str) -> TutorResponse:
        self._ensure_active(session)
        objective = self._objective(session.context)
        approach = STRATEGIES.get(session.state, STRATEGIES["PRACTICE"])
        safe_text = redact_student_text(text)
        teacher_message = await self.provider.explain(
            objective=f"{objective}\nTeaching approach: {approach}",
            student_input=safe_text,
            difficulty=difficulty_for(session.attempts, session.correct_attempts),
            language=session.context.get("language", "en"),
        )
        question = await self._generate_question(
            objective=objective,
            difficulty=difficulty_for(session.attempts, session.correct_attempts),
            language=session.context.get("language", "en"),
            previous_questions=session.context.get("previous_questions", []),
        )
        self._set_active_question(session, question)
        self._append_history(session, teacher_message, student_text=safe_text)
        session.state = "INTERACTIVE_QUESTION"
        return self._response(session, teacher_message)

    async def answer(self, db: Session, session: TutorSession, question_id: str, answer: str) -> TutorResponse:
        self._ensure_active(session)
        question = session.context.get("active_question")
        if not question or session.current_question_id != question_id or question.get("question_id") != question_id:
            raise InactiveQuestionError("The question is no longer active")

        safe_answer = redact_student_text(answer)
        session.attempts += 1
        deterministic_result = evaluate_deterministically(safe_answer, question)
        if deterministic_result is None:
            raw_assessment = await self.provider.evaluate_answer(
                question=question["question"],
                expected_answer=question["expected_answer"],
                rubric=question["explanation"],
                student_answer=safe_answer,
                language=session.context.get("language", "en"),
            )
            assessment = validate_model_assessment(raw_assessment)
            correct = assessment.correct
            teacher_message = assessment.feedback
        else:
            correct = deterministic_result
            teacher_message = deterministic_feedback(
                correct, session.context.get("language", "en")
            )

        context = dict(session.context)
        streak = int(context.get("correct_streak", 0)) + 1 if correct else 0
        context["correct_streak"] = streak
        score = session.correct_attempts / session.attempts if session.attempts else 0.0
        mastered = streak >= 3 and score >= 0.8
        if correct:
            session.correct_attempts += 1
            score = session.correct_attempts / session.attempts
            mastered = streak >= 3 and score >= 0.8

        session.context = context
        self._append_history(session, teacher_message, student_text=safe_answer)
        session.state = "COMPLETED" if mastered else ("PRACTICE" if correct else "REMEDIATION")
        if mastered:
            session.completed = True
            session.current_question_id = None
            context["active_question"] = None
            session.context = context
            return self._response(
                session,
                teacher_message,
                correct=True,
                mastery=self._mastery(session, score, correct=True, streak=streak),
                next_action="COMPLETE",
            )

        if correct:
            next_question = await self._generate_question(
                objective=self._objective(context),
                difficulty=difficulty_for(session.attempts, session.correct_attempts),
                language=context.get("language", "en"),
                previous_questions=context.get("previous_questions", []),
            )
            context["active_question"] = next_question
            context["previous_questions"] = [
                *context.get("previous_questions", []), next_question["question"]
            ][-20:]
            session.context = context
            session.current_question_id = next_question["question_id"]
        else:
            session.current_question_id = question_id
        return self._response(
            session,
            teacher_message,
            correct=correct,
            mastery=self._mastery(session, score, correct=correct, streak=streak),
        )

    def hint(self, db: Session, session: TutorSession) -> TutorResponse:
        self._ensure_active(session)
        question = session.context.get("active_question")
        if not question:
            raise InactiveQuestionError("There is no active question")
        context = dict(session.context)
        context["hint_count"] = int(context.get("hint_count", 0)) + 1
        session.context = context
        teacher_message = question["hint"]
        self._append_history(session, teacher_message)
        return self._response(session, teacher_message)

    async def resume(self, db: Session, session: TutorSession) -> TutorResponse:
        if session.completed:
            score = session.correct_attempts / session.attempts if session.attempts else 0.0
            message = "You have completed this lesson. Your progress is saved."
            return self._response(
                session,
                message,
                mastery=self._mastery(session, score, correct=None, streak=int(session.context.get("correct_streak", 0))),
                next_action="COMPLETE",
            )
        if not session.context.get("active_question"):
            question = await self._generate_question(
                objective=self._objective(session.context),
                difficulty=difficulty_for(session.attempts, session.correct_attempts),
                language=session.context.get("language", "en"),
                previous_questions=session.context.get("previous_questions", []),
            )
            self._set_active_question(session, question)
        session.state = "INTERACTIVE_QUESTION"
        return self._response(session, "Your lesson is ready to continue.")

    async def _generate_question(
        self, *, objective: str, difficulty: str, language: str, previous_questions: list[str]
    ) -> dict:
        raw = await self.provider.generate_question(
            objective=objective,
            difficulty=difficulty,
            language=language,
            previous_questions=previous_questions,
        )
        question = validate_generated_question(raw)
        question["question_id"] = str(uuid.uuid4())
        return question

    @staticmethod
    def _objective(context: dict) -> str:
        objective = context.get("learning_objective")
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("The LMS returned no published learning objective")
        return objective.strip()[:4000]

    @staticmethod
    def _ensure_active(session: TutorSession) -> None:
        if session.completed:
            raise InactiveQuestionError("This session has been completed")

    @staticmethod
    def _set_active_question(session: TutorSession, question: dict) -> None:
        context = dict(session.context)
        context["active_question"] = question
        previous = context.get("previous_questions", [])
        context["previous_questions"] = [*previous, question["question"]][-20:]
        session.context = context
        session.current_question_id = question["question_id"]

    @staticmethod
    def _append_history(
        session: TutorSession, teacher_message: str, *, student_text: str | None = None
    ) -> None:
        additions = []
        if student_text is not None:
            additions.append({"role": "student", "text": student_text[:4000]})
        additions.append({"role": "teacher", "text": teacher_message[:4000]})
        session.history = [*session.history, *additions][-200:]

    @staticmethod
    def _mastery(
        session: TutorSession, score: float, *, correct: bool | None, streak: int
    ) -> MasteryUpdate:
        return MasteryUpdate(
            concept_id=str(session.context.get("concept_id", session.topic)),
            status="mastered" if session.completed else ("needs_review" if score < 0.5 else "developing"),
            score=max(0.0, min(1.0, score)),
            correct=correct,
            correct_streak=streak,
            attempts=session.attempts,
        )

    @staticmethod
    def _response(
        session: TutorSession,
        teacher_message: str,
        *,
        correct: bool | None = None,
        mastery: MasteryUpdate | None = None,
        next_action: str | None = None,
    ) -> TutorResponse:
        question = session.context.get("active_question")
        interaction = None
        if question and not session.completed:
            question_type = question.get("question_type", "short_answer")
            answer_type = {
                "short_answer": "short_text",
                "fill_in_blank": "short_text",
                "numerical": "number",
                "mcq": "choice",
                "assertion_reason": "choice",
            }[question_type]
            interaction = Interaction(
                question_id=question["question_id"],
                type=question_type,
                answer_type=answer_type,
                question=question["question"],
                options=[QuestionOption.model_validate(option) for option in question.get("options", [])],
            )
        selected_resource = session.context.get("visual_resource")
        visual = VisualResource.model_validate(selected_resource) if selected_resource else None
        action = next_action or ("WAIT_FOR_ANSWER" if interaction else "CONTINUE_LESSON")
        return TutorResponse(
            session_id=session.id,
            state=session.state,
            teacher_message=TeacherMessage(
                text=teacher_message[:5000],
                language=session.context.get("language", "en"),
                format="plain_text",
            ),
            visual=visual,
            interaction=interaction,
            wait_for_student=interaction is not None,
            mastery_update=mastery,
            correct=correct,
            next_action=action,
            completed=session.completed,
        )
