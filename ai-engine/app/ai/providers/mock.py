class MockProvider:
    async def explain(self, *, objective: str, student_input: str | None, difficulty: str, language: str) -> str:
        if student_input:
            return f"Thanks for sharing your thinking. Let's connect it back to the learning objective: **{objective}**. Consider the key idea and try explaining it in a different way."
        return f"Let's learn about **{objective}**. We will build the idea step by step, then check your understanding with a question."

    async def generate_question(self, *, objective: str, difficulty: str, language: str, previous_questions: list[str]) -> dict:
        prompts = [
            "In your own words, what is the key idea in this lesson?",
            "How would you explain the main idea of this lesson to a classmate?",
            "What is the most important idea you learned here?",
            "Can you summarize the central idea of this lesson?",
        ]
        index = len(previous_questions) % len(prompts)
        return {
            "question": prompts[index],
            "expected_answer": objective,
            "hint": "Look back at the lesson objective and describe its main idea.",
            "explanation": f"The lesson objective is: {objective}",
            "question_type": "short_answer",
        }

    async def evaluate_answer(self, *, question: str, expected_answer: str, rubric: str, student_answer: str, language: str) -> dict:
        from app.assessment.answer_evaluator import exact_mock_evaluation

        correct = exact_mock_evaluation(student_answer, expected_answer)
        return {
            "correct": correct,
            "feedback": rubric if correct else "Not quite yet. Review the key idea and try again.",
        }
