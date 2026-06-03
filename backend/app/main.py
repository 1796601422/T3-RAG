from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.prd import router as prd_router
from app.api.runtime_config import router as config_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.models import ChatLog, Chunk, Document  # noqa: F401


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.mount("/storage/images", StaticFiles(directory=settings.image_storage_path), name="images")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_chunk_columns()
    _ensure_document_columns()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _ensure_chunk_columns() -> None:
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(chunks)")).mappings().all()
        existing = {row["name"] for row in rows}
        if "block_types" not in existing:
            connection.execute(text("ALTER TABLE chunks ADD COLUMN block_types VARCHAR(255) NOT NULL DEFAULT ''"))
        if "image_path" not in existing:
            connection.execute(text("ALTER TABLE chunks ADD COLUMN image_path TEXT"))


def _ensure_document_columns() -> None:
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(documents)")).mappings().all()
        existing = {row["name"] for row in rows}
        if "source_url" not in existing:
            connection.execute(text("ALTER TABLE documents ADD COLUMN source_url TEXT"))


app.include_router(documents_router, prefix=settings.api_prefix)
app.include_router(chat_router, prefix=settings.api_prefix)
app.include_router(prd_router, prefix=settings.api_prefix)
app.include_router(config_router, prefix=settings.api_prefix)
