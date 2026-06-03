from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.chat import Citation, RetrievedChunk


class PrdRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    requirement: str = Field(min_length=1, max_length=8000)
    use_rag: bool = True
    top_k: int | None = Field(default=None, ge=1, le=20)
    similarity_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    mode: Literal["full_prd"] = "full_prd"


class PrdResponse(BaseModel):
    answer: str
    prd: str
    mode: Literal["full_prd"] = "full_prd"
    rag_enabled: bool
    confidence: float
    citations: list[Citation]
    retrieved_chunks: list[RetrievedChunk]
    rejected_chunks: list[RetrievedChunk] = []
    open_questions: list[str] = []
    retrieval_debug: dict | None = None
    fallback_reason: str | None = None
