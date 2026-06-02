import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.schemas.document import DocumentChunk, DocumentDetail, DocumentSummary, UploadResponse, UrlUploadRequest
from app.services.dingtalk_mcp import DingtalkMCPError, fetch_dingtalk_document_export, is_dingtalk_document_url
from app.services.keyword_store import get_keyword_store
from app.services.task_manager import get_task_manager
from app.services.vector_store import get_vector_store


router = APIRouter(prefix="/documents", tags=["documents"])

MAX_LINK_BYTES = 25 * 1024 * 1024
INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
SUPPORTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/markdown": "md",
    "text/plain": "txt",
    "text/html": "txt",
    "application/xhtml+xml": "txt",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if tag in {"p", "div", "section", "article", "header", "footer", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if text:
            self._parts.append(text)

    def text(self) -> str:
        lines = [line.strip() for line in "".join(self._parts).splitlines()]
        return "\n".join(line for line in lines if line)


class _HTMLTitleExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._title_parts: list[str] = []
        self.meta_title: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attr_map = {str(key).lower(): str(value) for key, value in attrs if value is not None}
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "meta":
            prop = (attr_map.get("property") or attr_map.get("name") or "").lower()
            if prop in {"og:title", "twitter:title"} and attr_map.get("content"):
                self.meta_title = attr_map["content"].strip()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    def title(self) -> str | None:
        title = self.meta_title or "".join(self._title_parts)
        title = " ".join(title.split())
        return title or None


def _document_summary(db: Session, document: Document) -> DocumentSummary:
    chunk_count = db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == document.id)) or 0
    return DocumentSummary(
        id=document.id,
        filename=document.filename,
        file_type=document.file_type,
        status=document.status,
        error_message=document.error_message,
        source_url=document.source_url,
        chunk_count=chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _chunk_block_types(chunk: Chunk) -> list[str]:
    return [item for item in (chunk.block_types or "").split(",") if item]


def _chunk_image_url(chunk: Chunk) -> str | None:
    if not chunk.image_path:
        return None
    return f"/storage/images/{chunk.document_id}/{Path(chunk.image_path).name}"


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower().lstrip(".")
    if suffix not in settings.allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    document_id = str(uuid4())
    storage_name = f"{document_id}_{Path(file.filename or 'document').name}"
    storage_path = settings.raw_storage_path / storage_name
    with storage_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    document = Document(
        id=document_id,
        filename=file.filename or storage_name,
        file_type=suffix,
        storage_path=str(storage_path),
        status=DocumentStatus.uploaded,
    )
    db.add(document)
    db.commit()

    get_task_manager().submit_index(document.id)
    return UploadResponse(
        document_id=document.id,
        status=DocumentStatus.uploaded,
        message="Document uploaded. Indexing started in the background.",
    )


@router.post("/upload-url", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def upload_document_url(
    request: UrlUploadRequest,
    db: Session = Depends(get_db),
) -> UploadResponse:
    settings = get_settings()
    url = str(request.url)
    filename, file_type, content = _download_link_document(url, request.title)
    if file_type not in settings.allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported link content type.")

    document_id = str(uuid4())
    storage_name = f"{document_id}_{filename}"
    storage_path = settings.raw_storage_path / storage_name
    storage_path.write_bytes(content)

    document = Document(
        id=document_id,
        filename=filename,
        file_type=file_type,
        storage_path=str(storage_path),
        source_url=url,
        status=DocumentStatus.uploaded,
    )
    db.add(document)
    db.commit()

    get_task_manager().submit_index(document.id)
    return UploadResponse(
        document_id=document.id,
        status=DocumentStatus.uploaded,
        message="Link imported. Indexing started in the background.",
    )


@router.get("", response_model=list[DocumentSummary])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentSummary]:
    documents = db.scalars(select(Document).order_by(Document.created_at.desc())).all()
    return [_document_summary(db, item) for item in documents]


def _download_link_document(url: str, title: str | None) -> tuple[str, str, bytes]:
    if is_dingtalk_document_url(url):
        try:
            exported = fetch_dingtalk_document_export(url)
        except DingtalkMCPError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filename = _safe_link_filename(url, title or exported.title, "docx")
        return filename, "docx", exported.content

    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=400, detail=f"Link returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch link: {exc}") from exc

    content = response.content
    if len(content) > MAX_LINK_BYTES:
        raise HTTPException(status_code=400, detail="Link content is too large.")

    content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    file_type = _guess_link_file_type(url, content_type)
    response_filename = _filename_from_response(response)
    filename = _safe_link_filename(url, title or response_filename, file_type)

    if content_type in {"text/html", "application/xhtml+xml"} or file_type == "html":
        html_text = response.text
        html_title = _extract_html_title(html_text)
        filename = _safe_link_filename(url, title or html_title or response_filename, "txt")
        extractor = _HTMLTextExtractor()
        extractor.feed(html_text)
        text = extractor.text()
        if not text:
            raise HTTPException(status_code=400, detail="No readable text found in link.")
        return filename.rsplit(".", 1)[0] + ".txt", "txt", text.encode("utf-8")

    if file_type in {"txt", "md"}:
        text = response.text
        return filename, file_type, text.encode("utf-8")

    return filename, file_type, content


def _guess_link_file_type(url: str, content_type: str) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower().lstrip(".")
    if suffix in {"pdf", "docx", "md", "txt", "html", "htm"}:
        return "txt" if suffix in {"html", "htm"} else suffix
    return SUPPORTED_CONTENT_TYPES.get(content_type, "")


def _extract_html_title(html_text: str) -> str | None:
    extractor = _HTMLTitleExtractor()
    extractor.feed(html_text)
    return extractor.title()


def _filename_from_response(response: httpx.Response) -> str | None:
    value = response.headers.get("content-disposition")
    if value:
        message = httpx.Headers({"content-disposition": value})
        filename = message.get("content-disposition")
        if filename:
            for part in filename.split(";"):
                key, _, item = part.strip().partition("=")
                if key.lower() in {"filename", "filename*"} and item:
                    return unquote(item.strip().strip('"').removeprefix("UTF-8''")).strip() or None
    return None


def _safe_link_filename(url: str, title: str | None, file_type: str) -> str:
    parsed_name = Path(unquote(urlparse(url).path)).name
    stem = (title or parsed_name.rsplit(".", 1)[0] or "link-document").strip()
    suffix = Path(stem).suffix.lower().lstrip(".")
    if suffix == file_type:
        stem = Path(stem).stem
    safe_stem = "".join(
        "_" if char in INVALID_FILENAME_CHARS or ord(char) < 32 else char
        for char in stem
    )
    safe_stem = safe_stem.strip("._") or "link-document"
    return f"{safe_stem[:120]}.{file_type or 'txt'}"


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentDetail:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    summary = _document_summary(db, document)
    return DocumentDetail(**summary.model_dump(), storage_path=document.storage_path)


@router.get("/{document_id}/chunks", response_model=list[DocumentChunk])
def list_document_chunks(document_id: str, db: Session = Depends(get_db)) -> list[DocumentChunk]:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    chunks = db.scalars(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.start_offset.asc(), Chunk.id.asc())
    ).all()
    return [
        DocumentChunk(
            chunk_id=chunk.id,
            content=chunk.content,
            page_no=chunk.page_no,
            section_title=chunk.section_title,
            block_types=_chunk_block_types(chunk),
            image_url=_chunk_image_url(chunk),
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            created_at=chunk.created_at,
        )
        for chunk in chunks
    ]


@router.post("/{document_id}/reindex", response_model=UploadResponse)
def reindex_document(document_id: str, db: Session = Depends(get_db)) -> UploadResponse:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    task_manager = get_task_manager()
    if task_manager.is_running(document_id):
        return UploadResponse(
            document_id=document_id,
            status=document.status,
            message="Indexing is already running for this document.",
        )

    document.status = DocumentStatus.uploaded
    document.error_message = None
    db.add(document)
    db.commit()

    submitted = task_manager.submit_index(document_id)
    if not submitted:
        return UploadResponse(
            document_id=document_id,
            status=document.status,
            message="Indexing is already running for this document.",
        )

    return UploadResponse(
        document_id=document_id,
        status=document.status,
        message="Reindex started.",
    )


@router.post("/{document_id}/refresh-link", response_model=UploadResponse)
def refresh_link_document(document_id: str, db: Session = Depends(get_db)) -> UploadResponse:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not document.source_url:
        raise HTTPException(status_code=400, detail="This document was not imported from a link.")

    task_manager = get_task_manager()
    if task_manager.is_running(document_id):
        return UploadResponse(
            document_id=document_id,
            status=document.status,
            message="Indexing is already running for this document.",
        )

    settings = get_settings()
    filename, file_type, content = _download_link_document(document.source_url, Path(document.filename).stem)
    if file_type not in settings.allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported link content type.")

    old_storage_path = Path(document.storage_path)
    storage_path = settings.raw_storage_path / f"{document.id}_{filename}"
    storage_path.write_bytes(content)
    if old_storage_path != storage_path and old_storage_path.exists():
        old_storage_path.unlink()

    document.filename = filename
    document.file_type = file_type
    document.storage_path = str(storage_path)
    document.status = DocumentStatus.uploaded
    document.error_message = None
    db.add(document)
    db.commit()

    submitted = task_manager.submit_index(document.id)
    if not submitted:
        return UploadResponse(
            document_id=document.id,
            status=document.status,
            message="Indexing is already running for this document.",
        )

    return UploadResponse(
        document_id=document.id,
        status=document.status,
        message="Link refreshed. Indexing started in the background.",
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: Session = Depends(get_db)) -> Response:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    if get_task_manager().is_running(document_id):
        raise HTTPException(
            status_code=409,
            detail="Document is being indexed. Please wait until indexing finishes.",
        )

    get_vector_store().delete_document(document_id)
    get_keyword_store().delete_document(document_id)
    db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    db.delete(document)
    db.commit()

    storage_path = Path(document.storage_path)
    if storage_path.exists():
        storage_path.unlink()
    image_path = get_settings().image_storage_path / document.id
    if image_path.exists():
        shutil.rmtree(image_path)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
