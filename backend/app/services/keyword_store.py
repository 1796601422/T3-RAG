import json
import math
import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.chunking import ChunkPayload


@dataclass(slots=True)
class KeywordHit:
    chunk_id: str
    score: float
    matched_terms: list[str]


class KeywordStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._index_cache: dict | None = None

    def replace_document(self, document_id: str, chunks: list[ChunkPayload]) -> None:
        index = self._load_index()
        docs = [item for item in index["documents"] if item["document_id"] != document_id]
        docs.extend(self._build_entries(chunks))
        self._save_index({"documents": docs})

    def delete_document(self, document_id: str) -> None:
        index = self._load_index()
        docs = [item for item in index["documents"] if item["document_id"] != document_id]
        self._save_index({"documents": docs})

    def search(self, question: str, limit: int) -> list[KeywordHit]:
        if limit <= 0:
            return []
        query_terms = self._tokenize(question)
        if not query_terms:
            return []
        index = self._load_index()
        documents: list[dict] = index["documents"]
        if not documents:
            return []

        doc_count = len(documents)
        average_length = sum(item["token_count"] for item in documents) / max(doc_count, 1)
        doc_frequencies: dict[str, int] = {}
        for document in documents:
            for token in document["term_freqs"]:
                doc_frequencies[token] = doc_frequencies.get(token, 0) + 1

        results: list[KeywordHit] = []
        unique_terms = list(dict.fromkeys(query_terms))
        for document in documents:
            score = 0.0
            matched_terms: list[str] = []
            freqs = document["term_freqs"]
            for term in unique_terms:
                freq = freqs.get(term, 0)
                if not freq:
                    continue
                matched_terms.append(term)
                idf = math.log(1 + (doc_count - doc_frequencies.get(term, 0) + 0.5) / (doc_frequencies.get(term, 0) + 0.5))
                k1 = 1.5
                b = 0.75
                numerator = freq * (k1 + 1)
                denominator = freq + k1 * (1 - b + b * document["token_count"] / max(average_length, 1))
                score += idf * numerator / denominator
            if score > 0:
                results.append(
                    KeywordHit(
                        chunk_id=document["chunk_id"],
                        score=round(score, 4),
                        matched_terms=matched_terms,
                    )
                )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    def _build_entries(self, chunks: list[ChunkPayload]) -> list[dict]:
        entries: list[dict] = []
        for chunk in chunks:
            tokens = self._tokenize(chunk.embedding_text)
            if not tokens:
                continue
            freqs: dict[str, int] = {}
            for token in tokens:
                freqs[token] = freqs.get(token, 0) + 1
            entries.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "term_freqs": freqs,
                    "token_count": len(tokens),
                }
            )
        return entries

    def _load_index(self) -> dict:
        if self._index_cache is not None:
            return self._index_cache
        path = self.settings.keyword_index_path
        if not path.exists():
            self._index_cache = {"documents": []}
            return self._index_cache
        try:
            self._index_cache = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            self._index_cache = {"documents": []}
        self._index_cache.setdefault("documents", [])
        return self._index_cache

    def _save_index(self, data: dict) -> None:
        self.settings.keyword_index_path.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
        self._index_cache = data

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens: list[str] = []
        for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", text.lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", part):
                if len(part) == 1:
                    tokens.append(part)
                    continue
                tokens.append(part)
                tokens.extend(part[index : index + 2] for index in range(len(part) - 1))
                continue
            tokens.append(part)
        return tokens


_keyword_store: KeywordStore | None = None


def get_keyword_store() -> KeywordStore:
    global _keyword_store
    if _keyword_store is None:
        _keyword_store = KeywordStore()
    return _keyword_store
