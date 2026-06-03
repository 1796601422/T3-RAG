from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.schemas.prd import PrdRequest, PrdResponse
from app.services.conversation_memory import get_prd_memory
from app.services.dashscope_provider import ProviderError
from app.services.prd_service import get_prd_service


router = APIRouter(tags=["prd"])


@router.post("/prd/generate", response_model=PrdResponse)
def generate_prd(request: PrdRequest) -> PrdResponse:
    try:
        return get_prd_service().generate(
            request.session_id,
            request.requirement,
            use_rag=request.use_rag,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/prd/sessions/{session_id}/memory")
def clear_prd_memory(session_id: str) -> dict[str, bool]:
    get_prd_memory().clear(session_id)
    return {"ok": True}


@router.get("/prd/stream")
def stream_prd(
    session_id: str = Query(..., min_length=1, max_length=120),
    requirement: str = Query(..., min_length=1, max_length=8000),
    use_rag: bool = Query(default=True),
    top_k: int | None = Query(default=None, ge=1, le=20),
    similarity_threshold: float | None = Query(default=None, ge=-1.0, le=1.0),
    mode: str = Query(default="full_prd"),
) -> StreamingResponse:
    if mode != "full_prd":
        raise HTTPException(status_code=422, detail="Only full_prd mode is supported.")
    generator = get_prd_service().stream_generate(
        session_id,
        requirement,
        use_rag=use_rag,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )
    return StreamingResponse(generator, media_type="text/event-stream")
