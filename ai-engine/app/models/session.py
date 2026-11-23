from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class TutorSession(Base):
    __tablename__ = "tutor_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(140), index=True)
    school_id: Mapped[str] = mapped_column(String(140), index=True)
    course_id: Mapped[str] = mapped_column(String(140))
    subject: Mapped[str] = mapped_column(String(80))
    chapter: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(40), default="INTRODUCTION")
    history: Mapped[list] = mapped_column(JSON, default=list)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    current_question_id: Mapped[str | None] = mapped_column(String(140), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    correct_attempts: Mapped[int] = mapped_column(default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
