from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = BASE_DIR / "storage"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Private Knowledge RAG"
    api_prefix: str = "/api"
    database_url: str = f"sqlite:///{(STORAGE_DIR / 'app.db').as_posix()}"
    raw_storage_path: Path = STORAGE_DIR / "raw"
    image_storage_path: Path = STORAGE_DIR / "images"
    qdrant_path: Path = STORAGE_DIR / "qdrant"
    dashscope_api_key: str = Field(default="")
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_native_base_url: str = "https://dashscope.aliyuncs.com"
    dingtalk_mcp_url: str = ""
    embedding_model: str = "tongyi-embedding-vision-flash-2026-03-06"
    embedding_dimension: int | None = 768
    chat_model: str = "qwen3.6-flash"
    vision_chat_model: str = "qwen3.6-flash"
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "document_chunks"
    qdrant_timeout_seconds: float = 30.0
    chunk_size: int = 800
    chunk_overlap: int = 100
    min_chunk_size: int = 120
    max_chunk_size: int = 800
    embedding_batch_size: int = 10
    top_k: int = 4
    vector_top_k: int = 12
    keyword_top_k: int = 12
    image_top_k: int = 5
    rerank_top_n: int = 8
    rerank_score_threshold: float = 0.5
    similarity_threshold: float = 0.55
    max_context_chars: int = 4000
    enable_thinking: bool = True
    allowed_extensions: tuple[str, ...] = ("pdf", "docx", "md", "txt")
    index_worker_count: int = 2
    request_timeout_seconds: float = 60.0
    keyword_index_path: Path = STORAGE_DIR / "keyword_index.json"
    enable_retrieval_debug: bool = False


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.raw_storage_path.mkdir(parents=True, exist_ok=True)
    settings.image_storage_path.mkdir(parents=True, exist_ok=True)
    settings.qdrant_path.mkdir(parents=True, exist_ok=True)
    settings.keyword_index_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
