from fastapi import APIRouter
from pydantic import BaseModel
from urllib.parse import urlparse

from app.core.config import BASE_DIR, get_settings


router = APIRouter(prefix="/config", tags=["config"])


class ApiKeyStatus(BaseModel):
    configured: bool
    preview: str = ""


class ApiKeyUpdate(BaseModel):
    dashscope_api_key: str


class McpConfigStatus(BaseModel):
    configured: bool
    preview: str = ""


class McpConfigUpdate(BaseModel):
    dingtalk_mcp_url: str


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


@router.get("/mcp", response_model=McpConfigStatus)
def get_mcp_config_status() -> McpConfigStatus:
    url = get_settings().dingtalk_mcp_url
    return McpConfigStatus(configured=bool(url), preview=_mask_url(url))


@router.put("/mcp", response_model=McpConfigStatus)
def update_mcp_config(payload: McpConfigUpdate) -> McpConfigStatus:
    url = payload.dingtalk_mcp_url.strip()
    _write_env_value("DINGTALK_MCP_URL", url)
    _reset_runtime_state()
    return McpConfigStatus(configured=bool(url), preview=_mask_url(url))


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _mask_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/..."
    return "已配置"


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
