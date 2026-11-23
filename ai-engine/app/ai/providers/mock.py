class MockProvider:
    async def explain(self, *, objective: str, student_input: str | None, difficulty: str, language: str) -> str:
        locale = language.split("-")[0].lower()
        if locale == "hi":
            if student_input:
                return f"अपनी सोच साझा करने के लिए धन्यवाद। आइए इसे सीखने के उद्देश्य से जोड़ें: **{objective}**।"
            return f"आइए **{objective}** को चरण-दर-चरण समझते हैं और फिर आपकी समझ जाँचेंगे।"
        if locale == "es":
            if student_input:
                return f"Gracias por compartir tu idea. Conectémosla con el objetivo: **{objective}**."
            return f"Aprendamos **{objective}** paso a paso y después comprobaremos tu comprensión."
        if student_input:
            return f"Thanks for sharing your thinking. Let's connect it back to the learning objective: **{objective}**. Consider the key idea and try explaining it in a different way."
        return f"Let's learn about **{objective}**. We will build the idea step by step, then check your understanding with a question."

    async def generate_question(self, *, objective: str, difficulty: str, language: str, previous_questions: list[str]) -> dict:
        locale = language.split("-")[0].lower()
        prompts_by_language = {
            "en": [
                "In your own words, what is the key idea in this lesson?",
                "How would you explain the main idea of this lesson to a classmate?",
                "What is the most important idea you learned here?",
                "Can you summarize the central idea of this lesson?",
            ],
            "hi": [
                "इस पाठ का मुख्य विचार अपने शब्दों में क्या है?",
                "आप इस पाठ का विचार अपने सहपाठी को कैसे समझाएँगे?",
                "आपने इस पाठ में सबसे महत्वपूर्ण क्या सीखा?",
                "इस पाठ के मुख्य विचार का सार बताइए।",
            ],
            "es": [
                "¿Cuál es la idea principal de esta lección, en tus propias palabras?",
                "¿Cómo explicarías esta idea a un compañero?",
                "¿Qué es lo más importante que aprendiste?",
                "¿Puedes resumir la idea central de la lección?",
            ],
        }
        prompts = prompts_by_language.get(locale, prompts_by_language["en"])
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
        locale = language.split("-")[0].lower()
        feedback = {
            "en": (rubric, "Not quite yet. Review the key idea and try again."),
            "hi": ("सही उत्तर। मुख्य विचार को याद रखें।", "अभी सही नहीं है। मुख्य विचार दोबारा देखें और फिर प्रयास करें।"),
            "es": ("Respuesta correcta. Recuerda la idea principal.", "Aún no. Revisa la idea principal e inténtalo de nuevo."),
        }.get(locale, (rubric, "Not quite yet. Review the key idea and try again."))
        return {"correct": correct, "feedback": feedback[0 if correct else 1]}
