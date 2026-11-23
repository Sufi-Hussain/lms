STRATEGIES = {
    "INTRODUCTION": "Briefly introduce the idea, explain it in simple language, and include one relevant real-world example. Keep it concise and do not ask a question; the application will ask one next.",
    "EXPLANATION": "Explain one step at a time in simple language.",
    "EXAMPLE": "Give one worked, age-appropriate example.",
    "REMEDIATION": "Address the likely misconception gently and use a different analogy.",
    "PRACTICE": "Guide the learner with a hint before revealing a solution.",
    "SUMMARY": "Ask the learner to restate the key idea (Feynman technique).",
}

def difficulty_for(attempts: int, correct: int) -> str:
    if attempts >= 3 and correct / attempts >= 0.75:
        return "challenging"
    if attempts and correct / attempts < 0.5:
        return "foundational"
    return "grade-appropriate"
