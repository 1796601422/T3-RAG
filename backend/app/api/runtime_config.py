from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import BASE_DIR, get_settings


router = APIRouter(prefix="/config", tags=["config"])


class ApiKeyStatus(BaseModel):
    configured: bool
    preview: str = ""


class ApiKeyUpdate(BaseModel):
    dashscope_api_key: str


@router.get("/key", response_model=ApiKeyStatus)
def get_api_key_status() -> ApiKeyStatus:
    key = get_settings().dashscope_api_key
    return ApiKeyStatus(configured=bool(key), preview=_mask_key(key))


@router.put("/key", response_model=ApiKeyStatus)
def update_api_key(payload: ApiKeyUpdate) -> ApiKeyStatus:
    key = payload.dashscope_api_key.strip()
    _write_env_value("DASHSCOPE_API_KEY", key)
    _reset_runtime_state()
    return ApiKeyStatus(configured=bool(key), preview=_mask_key(key))


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _write_env_value(target_key: str, target_value: str) -> None:
    env_path = BASE_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    next_lines: list[str] = []
    found = False

    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            next_lines.append(line)
            continue
        key, _value = line.split("=", 1)
        if key.strip() == target_key:
            next_lines.append(f"{target_key}={target_value}")
            found = True
        else:
            next_lines.append(line)

    if not found:
        next_lines.append(f"{target_key}={target_value}")

    env_path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")


def _reset_runtime_state() -> None:
    get_settings.cache_clear()

    from app.services import chat_service, dashscope_provider, indexing, retrieval

    dashscope_provider._provider = None
    chat_service._chat_service = None
    retrieval._retrieval_service = None
    indexing._indexing_service = None
