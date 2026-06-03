from dataclasses import dataclass, field

from app.core.config import get_settings
from app.prompts.qa import FALLBACK_ANSWER
from app.services.dashscope_provider import get_dashscope_provider
from app.services.keyword_store import get_keyword_store
from app.services.vector_store import get_vector_store


VECTOR_CANDIDATE_TOP_K = 8
KEYWORD_CANDIDATE_TOP_K = 8
IMAGE_CANDIDATE_TOP_K = 4
VECTOR_KEEP_THRESHOLD = 0.85
IMAGE_KEEP_THRESHOLD = 0.82
FINAL_SCORE_KEEP_THRESHOLD = 0.6


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
    lexical_score: float | None = None
    title_score: float | None = None
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
    rejected_contexts: list[RetrievedContext] = field(default_factory=list)


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
        filtered = [item for item in reranked if self._should_keep(item)]
        rejected = [item for item in reranked if not self._should_keep(item)][:5]
        if not filtered:
            return RetrievalResult([], 0.0, FALLBACK_ANSWER, debug, rejected)

        deduped = self._dedupe_neighbors(filtered)
        trimmed = self._trim_contexts(deduped[:final_top_k])
        if not trimmed:
            return RetrievalResult([], 0.0, FALLBACK_ANSWER, debug, rejected)

        return RetrievalResult(
            contexts=trimmed,
            confidence=self._calculate_confidence(trimmed),
            fallback_reason=None,
            debug=debug,
            rejected_contexts=rejected,
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
            top_k=VECTOR_CANDIDATE_TOP_K,
            excluded_vector_variants=["image_visual"],
        ).get("points", [])
        debug.vector_hits = len(vector_points)
        for point in vector_points:
            metadata = point.payload or {}
            if metadata.get("vector_variant") == "image_visual":
                continue
            score = round(float(point.score), 4)
            if score < similarity_threshold:
                continue
            chunk_id = str(metadata["chunk_id"])
            if chunk_id in merged:
                candidate = merged[chunk_id]
                if score > (candidate.vector_score or 0.0):
                    candidate.vector_score = score
                    candidate.score = max(candidate.score, score)
                candidate.retrieval_note = self._append_note(
                    candidate.retrieval_note,
                    f"vector retrieval hit variant={metadata.get('vector_variant', 'unknown')} score={score:.4f}",
                )
                continue
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
                retrieval_note=f"vector retrieval hit variant={metadata.get('vector_variant', 'unknown')}",
                vector_score=score,
                block_types=list(metadata.get("block_types") or []),
                image_path=metadata.get("image_path") or None,
            )

        image_points = self.vector_store.query_by_block_type(
            query_embedding=query_embedding,
            top_k=IMAGE_CANDIDATE_TOP_K,
            block_type="image",
            vector_variant="image_visual",
        ).get("points", [])
        debug.image_hits = len(image_points)
        for point in image_points:
            metadata = point.payload or {}
            if metadata.get("vector_variant") != "image_visual":
                continue
            chunk_id = str(metadata["chunk_id"])
            raw_score = round(float(point.score), 4)
            if raw_score < similarity_threshold:
                continue
            if chunk_id in merged:
                candidate = merged[chunk_id]
                candidate.image_score = max(candidate.image_score or 0.0, raw_score)
                candidate.score = max(candidate.score, raw_score)
                candidate.retrieval_note = self._append_note(
                    candidate.retrieval_note,
                    f"image visual hit score={raw_score:.4f}",
                )
                continue
            merged[chunk_id] = RetrievedContext(
                chunk_id=chunk_id,
                document_id=metadata["document_id"],
                filename=metadata["filename"],
                page_no=metadata.get("page_no") or None,
                section_title=metadata.get("section_title") or None,
                content=metadata.get("content", ""),
                score=raw_score,
                start_offset=int(metadata.get("start_offset", 0)),
                end_offset=int(metadata.get("end_offset", 0)),
                retrieval_note=f"image visual hit score={raw_score:.4f}",
                image_score=raw_score,
                block_types=list(metadata.get("block_types") or []),
                image_path=metadata.get("image_path") or None,
            )

        keyword_hits = self.keyword_store.search(question, KEYWORD_CANDIDATE_TOP_K)
        debug.keyword_hits = len(keyword_hits)
        keyword_max = max((item.score for item in keyword_hits), default=0.0)
        missing_chunk_ids = [item.chunk_id for item in keyword_hits if item.chunk_id not in merged]
        chunk_lookup = self.vector_store.get_by_chunk_ids(missing_chunk_ids)
        for hit in keyword_hits:
            normalized_score = round(hit.score / keyword_max, 4) if keyword_max else 0.0
            if hit.chunk_id in merged:
                candidate = merged[hit.chunk_id]
                candidate.keyword_score = max(candidate.keyword_score or 0.0, normalized_score)
                candidate.retrieval_note = self._append_note(
                    candidate.retrieval_note,
                    f"keyword hits: {', '.join(hit.matched_terms[:4])}",
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

        return list(merged.values())

    def _rerank(
        self,
        question: str,
        candidates: list[RetrievedContext],
    ) -> list[RetrievedContext]:
        results = self._rule_rerank(question, candidates)
        results.sort(key=lambda item: item.rerank_score or 0.0, reverse=True)
        return results

    def _rule_rerank(self, question: str, candidates: list[RetrievedContext]) -> list[RetrievedContext]:
        question_terms = set(self.keyword_store._tokenize(question))
        for candidate in candidates:
            content_terms = set(self.keyword_store._tokenize(candidate.content))
            overlap = len(question_terms & content_terms)
            lexical = overlap / max(len(question_terms), 1)
            title_score = self._title_score(question_terms, candidate)
            vector_score = candidate.vector_score or 0.0
            keyword_score = candidate.keyword_score or 0.0
            image_score = candidate.image_score or 0.0
            title_weight = 0.30 if self._is_visual_or_table_block(candidate) else 0.10
            score = min(
                1.0,
                0.50 * max(vector_score, image_score)
                + 0.25 * keyword_score
                + 0.15 * lexical
                + title_weight * title_score
            )
            candidate.lexical_score = round(lexical, 4)
            candidate.title_score = round(title_score, 4)
            candidate.rerank_score = round(score, 4)
            candidate.score = candidate.rerank_score
            candidate.retrieval_note = (
                f"rule rerank: vector={vector_score:.4f}, "
                f"keyword={keyword_score:.4f}, image={image_score:.4f}, "
                f"lexical={lexical:.4f}, title={title_score:.4f}, "
                f"title_weight={title_weight:.2f}"
            )
        return candidates

    def _should_keep(self, candidate: RetrievedContext) -> bool:
        return (
            (candidate.vector_score or 0.0) >= VECTOR_KEEP_THRESHOLD
            or (candidate.image_score or 0.0) >= IMAGE_KEEP_THRESHOLD
            or (candidate.rerank_score or 0.0) >= FINAL_SCORE_KEEP_THRESHOLD
        )

    def _title_score(self, question_terms: set[str], candidate: RetrievedContext) -> float:
        if not question_terms:
            return 0.0
        title_text = " ".join(
            item
            for item in (
                candidate.filename,
                candidate.section_title or "",
            )
            if item
        )
        title_terms = set(self.keyword_store._tokenize(title_text))
        if not title_terms:
            return 0.0
        return min(1.0, len(question_terms & title_terms) / max(len(question_terms), 1))

    @staticmethod
    def _is_visual_or_table_block(candidate: RetrievedContext) -> bool:
        return bool({"image", "table"} & set(candidate.block_types))

    @staticmethod
    def _append_note(existing: str | None, note: str) -> str:
        if not existing:
            return note
        return f"{existing}; {note}"

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
