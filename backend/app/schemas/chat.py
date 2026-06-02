from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    similarity_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_no: int | None = None
    section_title: str | None = None
    excerpt: str
    score: float
    block_types: list[str] = []
    image_url: str | None = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_no: int | None = None
    section_title: str | None = None
    content: str
    score: float
    block_types: list[str] = []
    image_url: str | None = None


class ChatResponse(BaseModel):
    answer: str
    confidence: float
    citations: list[Citation]
    retrieved_chunks: list[RetrievedChunk]
    fallback_reason: str | None = None
    retrieval_debug: dict | None = None


class ChunkDetail(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_no: int | None = None
    section_title: str | None = None
    start_offset: int
    end_offset: int
    content: str
    block_types: list[str] = []
    image_url: str | None = None
