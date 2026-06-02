from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl

from app.models.document import DocumentStatus


class UploadResponse(BaseModel):
    document_id: str
    status: DocumentStatus
    message: str


class UrlUploadRequest(BaseModel):
    url: HttpUrl
    title: str | None = None


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    status: DocumentStatus
    error_message: str | None = None
    source_url: str | None = None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    storage_path: str


class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    page_no: int | None = None
    section_title: str | None = None
    block_types: list[str] = []
    image_url: str | None = None
    start_offset: int
    end_offset: int
    created_at: datetime
