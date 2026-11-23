from typing import Protocol


class LanguageModel(Protocol):
    async def explain(
        self, *, objective: str, student_input: str | None, difficulty: str, language: str
    ) -> str: ...

    async def generate_question(
        self,
        *,
        objective: str,
        difficulty: str,
        language: str,
        previous_questions: list[str],
    ) -> dict: ...

    async def evaluate_answer(
        self,
        *,
        question: str,
        expected_answer: str,
        rubric: str,
        student_answer: str,
        language: str,
    ) -> dict: ...
