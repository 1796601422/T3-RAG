from dataclasses import dataclass, field

from app.core.config import get_settings
from app.prompts.qa import FALLBACK_ANSWER
from app.services.dashscope_provider import get_dashscope_provider
from app.services.keyword_store import get_keyword_store
from app.services.vector_store import get_vector_store


@dataclass(slots=True)
class RetrievedContext:
    chunk_id: str
    document_id: str
    filename: str
    page_no: int | None
    section_title: str | None
    content: str
    score: float
    start_offset: int
    end_offset: int
    retrieval_note: str | None = None
    vector_score: float | None = None
    keyword_score: float | None = None
    image_score: float | None = None
    rerank_score: float | None = None
    block_types: list[str] = field(default_factory=list)
    image_path: str | None = None


@dataclass(slots=True)
class RetrievalDebug:
    vector_hits: int = 0
    keyword_hits: int = 0
    image_hits: int = 0
    rerank_strategy: str = "rule_formula"


@dataclass(slots=True)
class RetrievalResult:
    contexts: list[RetrievedContext]
    confidence: float
    fallback_reason: str | None
    debug: RetrievalDebug = field(default_factory=RetrievalDebug)


class RetrievalService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = get_dashscope_provider()
        self.vector_store = get_vector_store()
        self.keyword_store = get_keyword_store()

    def retrieve(
        self,
        question: str,
        *,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
    ) -> RetrievalResult:
        final_top_k = top_k if top_k is not None else self.settings.top_k
        similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.settings.similarity_threshold
        )
        debug = RetrievalDebug()
        candidates = self._merge_candidates(
            question,
            similarity_threshold=similarity_threshold,
            debug=debug,
        )
        if not candidates:
            return RetrievalResult([], 0.0, FALLBACK_ANSWER, debug)

        reranked = self._rerank(question, candidates)
        filtered = [
            item
            for item in reranked
            if (item.rerank_score or 0.0) >= self.settings.rerank_score_threshold
        ]
        if not filtered:
            return RetrievalResult([], 0.0, FALLBACK_ANSWER, debug)

        deduped = self._dedupe_neighbors(filtered)
        trimmed = self._trim_contexts(deduped[:final_top_k])
        if not trimmed:
            return RetrievalResult([], 0.0, FALLBACK_ANSWER, debug)

        return RetrievalResult(
            contexts=trimmed,
            confidence=self._calculate_confidence(trimmed),
            fallback_reason=None,
            debug=debug,
        )

    def _merge_candidates(
        self,
        question: str,
        *,
        similarity_threshold: float,
        debug: RetrievalDebug,
    ) -> list[RetrievedContext]:
        merged: dict[str, RetrievedContext] = {}
        query_embedding = self.provider.embed_query(question)
        vector_points = self.vector_store.query(
            query_embedding=query_embedding,
            top_k=self.settings.vector_top_k,
        ).get("points", [])
        debug.vector_hits = len(vector_points)
        for point in vector_points:
            metadata = point.payload or {}
            score = round(float(point.score), 4)
            if score < similarity_threshold:
                continue
            chunk_id = str(metadata["chunk_id"])
            merged[chunk_id] = RetrievedContext(
                chunk_id=chunk_id,
                document_id=metadata["document_id"],
                filename=metadata["filename"],
                page_no=metadata.get("page_no") or None,
                section_title=metadata.get("section_title") or None,
                content=metadata.get("content", ""),
                score=score,
                start_offset=int(metadata.get("start_offset", 0)),
                end_offset=int(metadata.get("end_offset", 0)),
                retrieval_note="vector retrieval hit",
                vector_score=score,
                block_types=list(metadata.get("block_types") or []),
                image_path=metadata.get("image_path") or None,
            )

        image_points = self.vector_store.query_by_block_type(
            query_embedding=query_embedding,
            top_k=self.settings.image_top_k,
            block_type="image",
        ).get("points", [])
        debug.image_hits = len(image_points)
        image_max = max((float(point.score) for point in image_points), default=0.0)
        for point in image_points:
            metadata = point.payload or {}
            chunk_id = str(metadata["chunk_id"])
            raw_score = round(float(point.score), 4)
            normalized_score = round(raw_score / image_max, 4) if image_max else 0.0
            if chunk_id in merged:
                candidate = merged[chunk_id]
                candidate.image_score = normalized_score
                candidate.retrieval_note = (
                    f"{candidate.retrieval_note}; image vector hit raw={raw_score:.4f}"
                )
                continue
            merged[chunk_id] = RetrievedContext(
                chunk_id=chunk_id,
                document_id=metadata["document_id"],
                filename=metadata["filename"],
                page_no=metadata.get("page_no") or None,
                section_title=metadata.get("section_title") or None,
                content=metadata.get("content", ""),
                score=normalized_score,
                start_offset=int(metadata.get("start_offset", 0)),
                end_offset=int(metadata.get("end_offset", 0)),
                retrieval_note=f"image vector hit raw={raw_score:.4f}, normalized={normalized_score:.4f}",
                image_score=normalized_score,
                block_types=list(metadata.get("block_types") or []),
                image_path=metadata.get("image_path") or None,
            )

        keyword_hits = self.keyword_store.search(question, self.settings.keyword_top_k)
        debug.keyword_hits = len(keyword_hits)
        keyword_max = max((item.score for item in keyword_hits), default=0.0)
        missing_chunk_ids = [item.chunk_id for item in keyword_hits if item.chunk_id not in merged]
        chunk_lookup = self.vector_store.get_by_chunk_ids(missing_chunk_ids)
        for hit in keyword_hits:
            normalized_score = round(hit.score / keyword_max, 4) if keyword_max else 0.0
            if hit.chunk_id in merged:
                candidate = merged[hit.chunk_id]
                candidate.keyword_score = normalized_score
                candidate.retrieval_note = (
                    f"{candidate.retrieval_note}; keyword hits: {', '.join(hit.matched_terms[:4])}"
                )
                continue
            metadata = chunk_lookup.get(hit.chunk_id)
            if not metadata:
                continue
            merged[hit.chunk_id] = RetrievedContext(
                chunk_id=hit.chunk_id,
                document_id=metadata["document_id"],
                filename=metadata["filename"],
                page_no=metadata.get("page_no") or None,
                section_title=metadata.get("section_title") or None,
                content=metadata.get("content", ""),
                score=normalized_score,
                start_offset=int(metadata.get("start_offset", 0)),
                end_offset=int(metadata.get("end_offset", 0)),
                retrieval_note=f"keyword hits: {', '.join(hit.matched_terms[:4])}",
                keyword_score=normalized_score,
                block_types=list(metadata.get("block_types") or []),
                image_path=metadata.get("image_path") or None,
            )

        candidates = list(merged.values())
        candidates.sort(
            key=lambda item: (
                (item.vector_score or 0.0)
                + (item.keyword_score or 0.0)
                + (item.image_score or 0.0)
            ),
            reverse=True,
        )
        return candidates[: max(self.settings.rerank_top_n, self.settings.top_k, self.settings.image_top_k)]

    def _rerank(
        self,
        question: str,
        candidates: list[RetrievedContext],
    ) -> list[RetrievedContext]:
        results = self._rule_rerank(question, candidates[: self.settings.rerank_top_n])
        results.sort(key=lambda item: item.rerank_score or 0.0, reverse=True)
        return results

    def _rule_rerank(self, question: str, candidates: list[RetrievedContext]) -> list[RetrievedContext]:
        question_terms = set(self.keyword_store._tokenize(question))
        for candidate in candidates:
            content_terms = set(self.keyword_store._tokenize(candidate.content))
            overlap = len(question_terms & content_terms)
            lexical = overlap / max(len(question_terms), 1)
            vector_score = candidate.vector_score or 0.0
            keyword_score = candidate.keyword_score or 0.0
            image_score = candidate.image_score or 0.0
            if "image" in candidate.block_types:
                score = 0.80 * image_score + 0.20 * lexical
            else:
                score = (
                    0.65 * vector_score
                    + 0.25 * keyword_score
                    + 0.10 * lexical
                )
            candidate.rerank_score = round(score, 4)
            candidate.score = candidate.rerank_score
            candidate.retrieval_note = (
                f"rule rerank: vector={vector_score:.4f}, "
                f"keyword={keyword_score:.4f}, image={image_score:.4f}, lexical={lexical:.4f}"
            )
        return candidates

    def _dedupe_neighbors(self, contexts: list[RetrievedContext]) -> list[RetrievedContext]:
        deduped: list[RetrievedContext] = []
        seen_signatures: set[tuple[str, str]] = set()
        for context in contexts:
            signature = (context.document_id, context.content[:180])
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped.append(context)
        return deduped

    def _trim_contexts(self, contexts: list[RetrievedContext]) -> list[RetrievedContext]:
        total = 0
        trimmed: list[RetrievedContext] = []
        for context in contexts:
            if total + len(context.content) > self.settings.max_context_chars and trimmed:
                break
            trimmed.append(context)
            total += len(context.content)
        return trimmed

    @staticmethod
    def _calculate_confidence(contexts: list[RetrievedContext]) -> float:
        rerank_average = sum(item.rerank_score or 0.0 for item in contexts) / len(contexts)
        coverage = min(1.0, len(contexts) / 3)
        return round(0.8 * rerank_average + 0.2 * coverage, 4)


_retrieval_service: RetrievalService | None = None


def get_retrieval_service() -> RetrievalService:
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service
