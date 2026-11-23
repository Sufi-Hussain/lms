import re


_EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{6,}\d)(?!\w)")


def redact_student_text(value: str) -> str:
    """Mask common contact details before text reaches a model or persistent history."""
    without_emails = _EMAIL_PATTERN.sub("[email redacted]", value)
    return _PHONE_PATTERN.sub("[phone redacted]", without_emails)
