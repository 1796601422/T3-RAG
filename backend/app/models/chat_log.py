import json
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_chunk_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    def set_retrieved_chunk_ids(self, chunk_ids: list[str]) -> None:
        self.retrieved_chunk_ids = json.dumps(chunk_ids, ensure_ascii=False)

