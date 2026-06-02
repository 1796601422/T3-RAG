from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import get_settings


class VectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        if self.settings.qdrant_url:
            self._client = QdrantClient(
                url=self.settings.qdrant_url,
                api_key=self.settings.qdrant_api_key or None,
                timeout=self.settings.qdrant_timeout_seconds,
            )
        else:
            self._client = QdrantClient(path=str(self.settings.qdrant_path))
        self._collection_name = self.settings.qdrant_collection

    def upsert_chunks(
        self,
        *,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        if not embeddings:
            return
        self._ensure_collection(vector_size=len(embeddings[0]))
        points = [
            models.PointStruct(
                id=point_id,
                vector=embedding,
                payload={"content": document, **metadata},
            )
            for point_id, embedding, document, metadata in zip(
                ids,
                embeddings,
                documents,
                metadatas,
                strict=False,
            )
        ]
        self._client.upsert(collection_name=self._collection_name, wait=True, points=points)

    def query(self, *, query_embedding: list[float], top_k: int) -> dict:
        if not self._collection_exists():
            return {"points": []}
        response = self._client.query_points(
            collection_name=self._collection_name,
            query=query_embedding,
            limit=top_k,
            with_payload=True,
        )
        return {"points": response.points}

    def query_by_block_type(self, *, query_embedding: list[float], top_k: int, block_type: str) -> dict:
        if not self._collection_exists():
            return {"points": []}
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="block_types",
                    match=models.MatchAny(any=[block_type]),
                )
            ]
        )
        response = self._client.query_points(
            collection_name=self._collection_name,
            query=query_embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        return {"points": response.points}

    def get_by_chunk_ids(self, chunk_ids: list[str]) -> dict[str, dict]:
        if not chunk_ids or not self._collection_exists():
            return {}
        scroll_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="chunk_id",
                    match=models.MatchAny(any=chunk_ids),
                )
            ]
        )
        response = self._client.scroll(
            collection_name=self._collection_name,
            scroll_filter=scroll_filter,
            limit=len(chunk_ids),
            with_payload=True,
            with_vectors=False,
        )
        points = response[0] if isinstance(response, tuple) else response.points
        payloads: dict[str, dict] = {}
        for point in points:
            payload = point.payload or {}
            chunk_id = payload.get("chunk_id")
            if chunk_id:
                payloads[str(chunk_id)] = payload
        return payloads

    def delete_ids(self, point_ids: list[str]) -> None:
        if not point_ids or not self._collection_exists():
            return
        self._client.delete(
            collection_name=self._collection_name,
            points_selector=models.PointIdsList(points=point_ids),
            wait=True,
        )

    def delete_document(self, document_id: str) -> None:
        if not self._collection_exists():
            return
        self._client.delete(
            collection_name=self._collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def _ensure_collection(self, *, vector_size: int) -> None:
        if self._collection_exists():
            return
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    def _collection_exists(self) -> bool:
        if hasattr(self._client, "collection_exists"):
            return bool(self._client.collection_exists(self._collection_name))
        try:
            self._client.get_collection(self._collection_name)
            return True
        except Exception:
            return False


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
