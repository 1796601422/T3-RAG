from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pathlib import Path
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.chunk import Chunk
from app.models.document import Document
from app.schemas.chat import ChatRequest, ChatResponse, ChunkDetail
from app.services.chat_service import get_chat_service
from app.services.dashscope_provider import ProviderError


router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        return get_chat_service().answer(
            request.question,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/chat/stream")
def stream_chat(
    question: str = Query(..., min_length=1, max_length=4000),
    top_k: int | None = Query(default=None, ge=1, le=20),
    similarity_threshold: float | None = Query(default=None, ge=-1.0, le=1.0),
) -> StreamingResponse:
    generator = get_chat_service().stream_answer(
        question,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/chunks/{chunk_id}", response_model=ChunkDetail)
def get_chunk(chunk_id: str, db: Session = Depends(get_db)) -> ChunkDetail:
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found.")
    document = db.get(Document, chunk.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return ChunkDetail(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        filename=document.filename,
        page_no=chunk.page_no,
        section_title=chunk.section_title,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        content=chunk.content,
        block_types=[item for item in (chunk.block_types or "").split(",") if item],
        image_url=f"/storage/images/{chunk.document_id}/{Path(chunk.image_path).name}" if chunk.image_path else None,
    )
