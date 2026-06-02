import json
from collections.abc import Generator
from pathlib import Path

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.chat_log import ChatLog
from app.prompts.qa import FALLBACK_ANSWER, build_messages
from app.schemas.chat import ChatResponse, Citation, RetrievedChunk
from app.services.dashscope_provider import ProviderError, get_dashscope_provider
from app.services.retrieval import RetrievalResult, get_retrieval_service


class ChatService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = get_dashscope_provider()
        self.retriever = get_retrieval_service()

    def answer(self, question: str, *, top_k: int | None = None, similarity_threshold: float | None = None) -> ChatResponse:
        result = self.retriever.retrieve(question, top_k=top_k, similarity_threshold=similarity_threshold)
        if not result.contexts:
            response = self._fallback_response(result)
            self._log_chat(question, response)
            return response

        prompt_contexts = [self._to_prompt_context(index, item) for index, item in enumerate(result.contexts, start=1)]
        messages = build_messages(question, prompt_contexts)
        image_items = self._image_prompt_items(result.contexts)
        if image_items:
            answer = self.provider.complete_multimodal_chat(messages, image_items)
        else:
            answer = self.provider.complete_chat(messages)
        response = self._build_response(answer, result)
        self._log_chat(question, response)
        return response

    def stream_answer(
        self,
        question: str,
        *,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
    ) -> Generator[str, None, None]:
        try:
            result = self.retriever.retrieve(question, top_k=top_k, similarity_threshold=similarity_threshold)
            if not result.contexts:
                fallback = self._fallback_response(result)
                self._log_chat(question, fallback)
                yield self._sse_event("token", {"content": fallback.answer})
                yield self._sse_event("meta", fallback.model_dump())
                yield self._sse_event("done", {"ok": True})
                return

            prompt_contexts = [self._to_prompt_context(index, item) for index, item in enumerate(result.contexts, start=1)]
            messages = build_messages(question, prompt_contexts)
            image_items = self._image_prompt_items(result.contexts)
            if image_items:
                accumulated: list[str] = []
                for token in self.provider.stream_multimodal_chat(messages, image_items):
                    accumulated.append(token)
                    yield self._sse_event("token", {"content": token})

                response = self._build_response(self._strip_think_blocks("".join(accumulated)).strip(), result)
                self._log_chat(question, response)
                yield self._sse_event("meta", response.model_dump())
                yield self._sse_event("done", {"ok": True})
                return
            accumulated: list[str] = []
            for token in self.provider.stream_chat(messages):
                accumulated.append(token)
                yield self._sse_event("token", {"content": token})

            response = self._build_response(self._strip_think_blocks("".join(accumulated)).strip(), result)
            self._log_chat(question, response)
            yield self._sse_event("meta", response.model_dump())
            yield self._sse_event("done", {"ok": True})
        except ProviderError as exc:
            yield self._sse_event("app-error", {"message": str(exc)})
        except Exception as exc:
            yield self._sse_event("app-error", {"message": str(exc)})

    def _build_response(self, answer: str, result: RetrievalResult) -> ChatResponse:
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
        return ChatResponse(
            answer=answer or FALLBACK_ANSWER,
            confidence=result.confidence,
            citations=citations,
            retrieved_chunks=retrieved_chunks,
            fallback_reason=result.fallback_reason,
            retrieval_debug=self._debug_payload(result),
        )

    def _fallback_response(self, result: RetrievalResult) -> ChatResponse:
        return ChatResponse(
            answer=FALLBACK_ANSWER,
            confidence=result.confidence,
            citations=[],
            retrieved_chunks=[],
            fallback_reason=result.fallback_reason or FALLBACK_ANSWER,
            retrieval_debug=self._debug_payload(result),
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

    def _log_chat(self, question: str, response: ChatResponse) -> None:
        with SessionLocal() as session:
            log = ChatLog(
                question=question,
                answer=response.answer,
                confidence=response.confidence,
                fallback_reason=response.fallback_reason,
                retrieved_chunk_ids=json.dumps([item.chunk_id for item in response.citations], ensure_ascii=False),
            )
            session.add(log)
            session.commit()

    @staticmethod
    def _to_prompt_context(index: int, item) -> dict:
        content = item.content
        if item.image_path:
            content = (
                f"{content}\n"
                f"说明：本条证据包含图片，图片会随本次请求一并提供。"
                f"请读取该图片中的流程、节点、箭头、判断条件和文字内容。"
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


_chat_service: ChatService | None = None


def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
