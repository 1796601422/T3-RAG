import json
import time
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from app.core.config import get_settings


class DingtalkMCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class DingtalkDocumentExport:
    content: bytes
    title: str | None = None


def is_dingtalk_document_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("alidocs.dingtalk.com") or host.endswith("dingtalk.com")


def fetch_dingtalk_document_docx(url: str) -> bytes:
    return fetch_dingtalk_document_export(url).content


def fetch_dingtalk_document_export(url: str) -> DingtalkDocumentExport:
    settings = get_settings()
    if not settings.dingtalk_mcp_url:
        raise DingtalkMCPError("DINGTALK_MCP_URL is not configured.")

    client = _MCPClient(settings.dingtalk_mcp_url)
    submit_result = client.call_tool(
        "submit_export_job",
        {
            "nodeId": url,
            "exportFormat": "docx",
        },
    )
    title = _find_title(submit_result)
    job_id = _find_first_value(submit_result, {"jobId", "job_id", "taskId", "task_id"})
    if not job_id:
        raise DingtalkMCPError("DingTalk MCP export response missing jobId.")

    download_info: dict | None = None
    for _attempt in range(30):
        query_result = client.call_tool("query_export_job", {"jobId": str(job_id)})
        title = title or _find_title(query_result)
        if _is_export_finished(query_result):
            download_info = query_result
            break
        time.sleep(2)
    if download_info is None:
        raise DingtalkMCPError("DingTalk document export timed out.")

    title = title or _find_title(download_info)
    download_url = _find_download_url(download_info)
    if not download_url:
        raise DingtalkMCPError("DingTalk MCP export response missing download URL.")
    title = title or _filename_from_url(download_url)

    headers = _find_headers(download_info)
    try:
        response = httpx.get(download_url, headers=headers, timeout=60.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DingtalkMCPError(f"DingTalk exported file download failed: {exc}") from exc
    if not response.content:
        raise DingtalkMCPError("DingTalk exported DOCX is empty.")
    title = title or _filename_from_content_disposition(response.headers.get("content-disposition"))
    return DingtalkDocumentExport(content=response.content, title=title)


class _MCPClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self._next_id = 1
        self._headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

    def call_tool(self, name: str, arguments: dict) -> dict:
        self._initialize()
        return self._request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "private-rag", "version": "0.1.0"},
            },
        )

    def _request(self, method: str, params: dict) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        self._next_id += 1
        try:
            response = httpx.post(
                self.url,
                headers=self._headers,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DingtalkMCPError(f"DingTalk MCP request failed: {exc}") from exc

        data = _parse_mcp_response(response.text)
        if "error" in data:
            message = data["error"].get("message") if isinstance(data["error"], dict) else str(data["error"])
            raise DingtalkMCPError(f"DingTalk MCP error: {message}")
        result = data.get("result")
        if not isinstance(result, dict):
            raise DingtalkMCPError("DingTalk MCP response missing result.")
        return result


def _parse_mcp_response(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("data:"):
        for line in stripped.splitlines():
            if line.startswith("data:"):
                stripped = line.removeprefix("data:").strip()
                break
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise DingtalkMCPError("DingTalk MCP returned an invalid JSON response.") from exc
    if not isinstance(data, dict):
        raise DingtalkMCPError("DingTalk MCP returned an invalid response shape.")
    return data


def _extract_text(result: dict) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        if parts:
            return "\n".join(parts)

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("content", "markdown", "text"):
            value = structured.get(key)
            if isinstance(value, str):
                return value

    if isinstance(result.get("text"), str):
        return result["text"]
    return ""


def _is_export_finished(result: dict) -> bool:
    status = str(_find_first_value(result, {"status", "state", "jobStatus"}) or "").lower()
    if status in {"success", "succeeded", "finished", "completed", "done"}:
        return True
    if status in {"failed", "fail", "error", "canceled", "cancelled"}:
        raise DingtalkMCPError(f"DingTalk document export failed: {status}")
    return bool(_find_download_url(result))


def _find_download_url(value) -> str | None:
    if isinstance(value, dict):
        for key in ("downloadUrl", "download_url", "url", "fileUrl", "resourceUrl"):
            item = value.get(key)
            if isinstance(item, str) and item.startswith("http"):
                return item
            if isinstance(item, list):
                for child in item:
                    if isinstance(child, str) and child.startswith("http"):
                        return child
        for child in value.values():
            found = _find_download_url(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_download_url(child)
            if found:
                return found
    if isinstance(value, str) and value.startswith("http"):
        return value
    text = _extract_text(value) if isinstance(value, dict) else ""
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return _find_download_url(parsed)
    return None


def _find_headers(value) -> dict[str, str]:
    if isinstance(value, dict):
        headers = value.get("headers")
        if isinstance(headers, dict):
            return {str(key): str(item) for key, item in headers.items()}
        for child in value.values():
            found = _find_headers(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_headers(child)
            if found:
                return found
    text = _extract_text(value) if isinstance(value, dict) else ""
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return _find_headers(parsed)
    return {}


def _find_title(value) -> str | None:
    title = _find_first_value(
        value,
        {
            "title",
            "name",
            "fileName",
            "file_name",
            "documentName",
            "document_name",
            "docTitle",
            "doc_title",
            "nodeName",
            "node_name",
        },
    )
    if isinstance(title, str):
        title = title.strip()
        return title or None
    return None


def _filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    message = Message()
    message["content-disposition"] = value
    filename = message.get_filename()
    if filename:
        return filename.strip() or None
    return None


def _filename_from_url(value: str) -> str | None:
    parsed = urlparse(value)
    filename = Path(unquote(parsed.path)).name.strip()
    return filename or None


def _find_first_value(value, keys: set[str]) -> object | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and item not in (None, ""):
                return item
        text = _extract_text(value)
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                found = _find_first_value(parsed, keys)
                if found is not None:
                    return found
        for item in value.values():
            found = _find_first_value(item, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_value(item, keys)
            if found is not None:
                return found
    return None
