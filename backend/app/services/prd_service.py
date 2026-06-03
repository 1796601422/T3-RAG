import json
import re
from collections.abc import Generator
from pathlib import Path

from app.core.config import get_settings
from app.prompts.prd import build_prd_messages
from app.schemas.chat import Citation, RetrievedChunk
from app.schemas.prd import PrdResponse
from app.services.conversation_memory import ConversationMemory, get_prd_memory
from app.services.dashscope_provider import ProviderError, get_dashscope_provider
from app.services.retrieval import RetrievalResult, get_retrieval_service


class PrdService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = get_dashscope_provider()
        self.retriever = get_retrieval_service()
        self.memory: ConversationMemory = get_prd_memory()

    def generate(
        self,
        session_id: str,
        requirement: str,
        *,
        use_rag: bool = True,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        source_context: str | None = None,
    ) -> PrdResponse:
        memory_version = self.memory.version(session_id)
        history = self.memory.get(session_id)
        result = self._retrieve(requirement, use_rag=use_rag, top_k=top_k, similarity_threshold=similarity_threshold)
        messages = self._build_messages(requirement, history, result, rag_enabled=use_rag, source_context=source_context)
        image_items = self._image_prompt_items(result.contexts)
        if image_items:
            answer = self.provider.complete_multimodal_chat(messages, image_items, temperature=0.35)
        else:
            answer = self.provider.complete_chat(messages, temperature=0.35)
        answer = self._strip_think_blocks(answer).strip()
        response = self._build_response(answer, result, rag_enabled=use_rag)
        self.memory.append_turn_if_version(session_id, memory_version, requirement, response.answer)
        return response

    def stream_generate(
        self,
        session_id: str,
        requirement: str,
        *,
        use_rag: bool = True,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        source_context: str | None = None,
    ) -> Generator[str, None, None]:
        try:
            memory_version = self.memory.version(session_id)
            history = self.memory.get(session_id)
            result = self._retrieve(
                requirement,
                use_rag=use_rag,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
            )
            messages = self._build_messages(
                requirement,
                history,
                result,
                rag_enabled=use_rag,
                source_context=source_context,
            )
            image_items = self._image_prompt_items(result.contexts)
            accumulated: list[str] = []
            stream = (
                self.provider.stream_multimodal_chat(
                    messages,
                    image_items,
                    temperature=0.35,
                    enable_thinking=False,
                )
                if image_items
                else self.provider.stream_chat(messages, temperature=0.35, enable_thinking=False)
            )
            for token in stream:
                accumulated.append(token)
                yield self._sse_event("token", {"content": token})

            answer = self._strip_think_blocks("".join(accumulated)).strip()
            response = self._build_response(answer, result, rag_enabled=use_rag)
            self.memory.append_turn_if_version(session_id, memory_version, requirement, response.answer)
            yield self._sse_event("meta", response.model_dump())
            yield self._sse_event("done", {"ok": True})
        except ProviderError as exc:
            yield self._sse_event("app-error", {"message": str(exc)})
        except Exception as exc:
            yield self._sse_event("app-error", {"message": str(exc)})

    def _retrieve(
        self,
        requirement: str,
        *,
        use_rag: bool,
        top_k: int | None,
        similarity_threshold: float | None,
    ) -> RetrievalResult:
        if not use_rag:
            return RetrievalResult([], 0.0, None)
        return self.retriever.retrieve(
            requirement,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

    def _build_messages(
        self,
        requirement: str,
        history: list[dict],
        result: RetrievalResult,
        *,
        rag_enabled: bool,
        source_context: str | None = None,
    ) -> list[dict]:
        prompt_contexts = [self._to_prompt_context(index, item) for index, item in enumerate(result.contexts, start=1)]
        return build_prd_messages(
            requirement,
            prompt_contexts,
            history,
            rag_enabled=rag_enabled,
            source_context=source_context,
        )

    def _build_response(self, answer: str, result: RetrievalResult, *, rag_enabled: bool) -> PrdResponse:
        citations = [
            Citation(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                filename=item.filename,
                page_no=item.page_no,
                section_title=item.section_title,
                excerpt=item.content[:220],
                score=item.score,
                block_types=item.block_types,
                image_url=self._image_url(item),
            )
            for item in result.contexts
        ]
        retrieved_chunks = [
            RetrievedChunk(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                filename=item.filename,
                page_no=item.page_no,
                section_title=item.section_title,
                content=item.content,
                score=item.score,
                block_types=item.block_types,
                image_url=self._image_url(item),
            )
            for item in result.contexts
        ]
        rejected_chunks = [
            RetrievedChunk(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                filename=item.filename,
                page_no=item.page_no,
                section_title=item.section_title,
                content=item.content,
                score=item.score,
                block_types=item.block_types,
                image_url=self._image_url(item),
            )
            for item in result.rejected_contexts
        ]
        return PrdResponse(
            answer=answer,
            prd=answer,
            rag_enabled=rag_enabled,
            confidence=result.confidence if rag_enabled else 0.0,
            citations=citations,
            retrieved_chunks=retrieved_chunks,
            rejected_chunks=rejected_chunks,
            open_questions=self._extract_open_questions(answer),
            retrieval_debug=self._debug_payload(result) if rag_enabled else None,
            fallback_reason=result.fallback_reason,
        )

    def _debug_payload(self, result: RetrievalResult) -> dict | None:
        if not self.settings.enable_retrieval_debug:
            return None
        return {
            "vector_hits": result.debug.vector_hits,
            "keyword_hits": result.debug.keyword_hits,
            "image_hits": result.debug.image_hits,
            "rerank_strategy": result.debug.rerank_strategy,
        }

    @staticmethod
    def _to_prompt_context(index: int, item) -> dict:
        content = item.content
        if item.image_path:
            content = (
                f"{content}\n"
                "说明：本条证据包含图片，图片会随本次请求一起提供。"
                "请读取图片中的流程、节点、箭头、判断条件和文字内容。"
            )
        return {
            "citation_id": index,
            "filename": item.filename,
            "page_no": item.page_no,
            "section_title": item.section_title,
            "content": content,
            "retrieval_note": item.retrieval_note,
        }

    @staticmethod
    def _image_prompt_items(contexts: list) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for index, item in enumerate(contexts, start=1):
            if item.image_path:
                label_parts = [f"[{index}]"]
                if item.section_title:
                    label_parts.append(item.section_title)
                label_parts.append(Path(item.image_path).name)
                items.append((" | ".join(label_parts), item.image_path))
        return items

    @staticmethod
    def _image_url(item) -> str | None:
        if not item.image_path:
            return None
        return f"/storage/images/{item.document_id}/{Path(item.image_path).name}"

    @staticmethod
    def _extract_open_questions(answer: str) -> list[str]:
        match = re.search(r"##\s*12[.、]?\s*风险与待确认项(?P<body>.*?)(?:\n##\s*13[.、]?|\Z)", answer, re.S)
        if not match:
            return []
        questions: list[str] = []
        for raw_line in match.group("body").splitlines():
            line = raw_line.strip().lstrip("-*0123456789.、) ").strip()
            if line and ("确认" in line or "待定" in line or "需" in line):
                questions.append(line)
        return questions[:10]

    @staticmethod
    def _sse_event(event: str, payload: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _strip_think_blocks(text: str) -> str:
        while "<think>" in text and "</think>" in text:
            before, rest = text.split("<think>", 1)
            _thinking, after = rest.split("</think>", 1)
            text = before + after
        if "<think>" in text:
            text = text.split("<think>", 1)[0]
        return text


_prd_service: PrdService | None = None


def get_prd_service() -> PrdService:
    global _prd_service
    if _prd_service is None:
        _prd_service = PrdService()
    return _prd_service
