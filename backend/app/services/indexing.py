from collections.abc import Sequence
from pathlib import Path
import uuid

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.chunking import ChunkPayload, split_sections_into_chunks
from app.services.dashscope_provider import get_dashscope_provider
from app.services.document_parser import DocumentParser
from app.services.keyword_store import get_keyword_store
from app.services.vector_store import get_vector_store


class IndexingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.parser = DocumentParser()
        self.provider = get_dashscope_provider()
        self.vector_store = get_vector_store()
        self.keyword_store = get_keyword_store()

    def index_document(self, document_id: str) -> None:
        with SessionLocal() as session:
            document = session.get(Document, document_id)
            if document is None:
                return

            try:
                self._update_status(session, document, DocumentStatus.parsing)
                sections = self.parser.parse(Path(document.storage_path), document.file_type, document_id=document.id)
                if not sections:
                    raise ValueError("文档中未提取到可用文本。")

                self._update_status(session, document, DocumentStatus.chunking)
                chunk_payloads = split_sections_into_chunks(
                    document_id=document.id,
                    filename=document.filename,
                    sections=sections,
                    chunk_size=self.settings.chunk_size,
                    chunk_overlap=self.settings.chunk_overlap,
                    min_chunk_size=self.settings.min_chunk_size,
                    max_chunk_size=self.settings.max_chunk_size,
                )
                if not chunk_payloads:
                    raise ValueError("文档切片后没有可索引内容。")

                self._purge_existing_chunks(session, document.id)
                self._update_status(session, document, DocumentStatus.embedding)

                vector_ids, embeddings, vector_documents, vector_metadatas = self._build_vector_records(chunk_payloads)
                self.vector_store.upsert_chunks(
                    ids=vector_ids,
                    embeddings=embeddings,
                    documents=vector_documents,
                    metadatas=vector_metadatas,
                )
                self.keyword_store.replace_document(document.id, chunk_payloads)

                session.add_all(
                    [
                        Chunk(
                            id=chunk.chunk_id,
                            chroma_id=chunk.chroma_id,
                            document_id=chunk.document_id,
                            content=chunk.content,
                            page_no=chunk.page_no,
                            section_title=chunk.section_title,
                            start_offset=chunk.start_offset,
                            end_offset=chunk.end_offset,
                            block_types=",".join(chunk.block_types),
                            image_path=chunk.image_path,
                        )
                        for chunk in chunk_payloads
                    ]
                )
                document.status = DocumentStatus.ready
                document.error_message = None
                session.add(document)
                session.commit()
            except Exception as exc:
                session.rollback()
                failing_document = session.get(Document, document_id)
                if failing_document is None:
                    return
                failing_document.status = DocumentStatus.failed
                failing_document.error_message = str(exc)
                session.add(failing_document)
                session.commit()

    def _update_status(self, session, document: Document, status: DocumentStatus) -> None:
        document.status = status
        document.error_message = None
        session.add(document)
        session.commit()

    def _purge_existing_chunks(self, session, document_id: str) -> None:
        self.vector_store.delete_document(document_id)
        self.keyword_store.delete_document(document_id)
        session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        session.commit()

    def _build_vector_records(
        self,
        chunks: Sequence[ChunkPayload],
    ) -> tuple[list[str], list[list[float]], list[str], list[dict]]:
        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        batch_size = min(self.settings.embedding_batch_size, 10)
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            text_indexes: list[int] = []
            text_inputs: list[str] = []
            image_indexes: list[int] = []
            image_inputs: list[str] = []
            batch_embeddings: list[list[float] | None] = [None] * len(batch)
            for index, chunk in enumerate(batch):
                if chunk.image_path:
                    image_indexes.append(index)
                    image_inputs.append(chunk.image_path)
                    text_indexes.append(index)
                    text_inputs.append(chunk.embedding_text)
                else:
                    text_indexes.append(index)
                    text_inputs.append(chunk.embedding_text)
            for index, embedding in zip(text_indexes, self.provider.embed_texts(text_inputs), strict=False):
                chunk = batch[index]
                variant = "image_text" if chunk.image_path else "text"
                ids.append(self._variant_point_id(chunk, variant))
                embeddings.append(embedding)
                documents.append(chunk.content)
                metadatas.append({**self._chunk_metadata(chunk), "vector_variant": variant})
                if not chunk.image_path:
                    batch_embeddings[index] = embedding
            for index, embedding in zip(image_indexes, self.provider.embed_image_paths(image_inputs), strict=False):
                chunk = batch[index]
                ids.append(self._variant_point_id(chunk, "image_visual"))
                embeddings.append(embedding)
                documents.append(chunk.content)
                metadatas.append({**self._chunk_metadata(chunk), "vector_variant": "image_visual"})
                batch_embeddings[index] = embedding
        return ids, embeddings, documents, metadatas

    @staticmethod
    def _chunk_metadata(chunk: ChunkPayload) -> dict:
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "filename": chunk.filename,
            "page_no": chunk.page_no or 0,
            "section_title": chunk.section_title or "",
            "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset,
            "section_level": chunk.section_level,
            "block_types": chunk.block_types,
            "image_path": chunk.image_path or "",
            "source_order_start": chunk.source_order_start,
            "source_order_end": chunk.source_order_end,
        }

    @staticmethod
    def _variant_point_id(chunk: ChunkPayload, variant: str) -> str:
        if variant in {"text", "image_visual"}:
            return chunk.chroma_id
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.chunk_id}:{variant}"))


_indexing_service: IndexingService | None = None


def get_indexing_service() -> IndexingService:
    global _indexing_service
    if _indexing_service is None:
        _indexing_service = IndexingService()
    return _indexing_service
