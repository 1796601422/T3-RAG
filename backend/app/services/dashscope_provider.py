import json
import base64
import mimetypes
from collections.abc import Generator
from pathlib import Path

import httpx

from app.core.config import get_settings


class ProviderError(RuntimeError):
    pass


class DashScopeProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def _headers(self) -> dict[str, str]:
        if not self.settings.dashscope_api_key:
            raise ProviderError("Missing DASHSCOPE_API_KEY in environment.")
        return {
            "Authorization": f"Bearer {self.settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self._uses_multimodal_embedding:
            return self._embed_multimodal_texts(texts)
        payload = {"model": self.settings.embedding_model, "input": texts}
        response = self._post("/embeddings", payload)
        data = response.get("data")
        if not isinstance(data, list):
            raise ProviderError("Embedding response missing data payload.")
        return [item["embedding"] for item in data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_image_paths(self, image_paths: list[str]) -> list[list[float]]:
        if not image_paths:
            return []
        contents = [{"image": self._image_to_data_url(Path(image_path))} for image_path in image_paths]
        return self._embed_multimodal_contents(contents)

    @property
    def _uses_multimodal_embedding(self) -> bool:
        return self.settings.embedding_model.startswith("tongyi-embedding-vision")

    def _embed_multimodal_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed_multimodal_contents([{"text": text} for text in texts])

    def _embed_multimodal_contents(self, contents: list[dict]) -> list[list[float]]:
        payload = {"model": self.settings.embedding_model, "input": {"contents": contents}}
        if self.settings.embedding_dimension:
            payload["parameters"] = {"dimension": self.settings.embedding_dimension}
        url = (
            f"{self.settings.dashscope_native_base_url.rstrip('/')}"
            "/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
        )
        response = self._post_url(url, payload)
        embeddings = response.get("output", {}).get("embeddings")
        if not isinstance(embeddings, list):
            raise ProviderError("Multimodal embedding response missing output.embeddings payload.")
        embeddings.sort(key=lambda item: int(item.get("index", 0)))
        return [item["embedding"] for item in embeddings]

    @staticmethod
    def _image_to_data_url(image_path: Path) -> str:
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def complete_chat(self, messages: list[dict], temperature: float = 0.1) -> str:
        payload = {
            "model": self.settings.chat_model,
            "messages": messages,
            "temperature": temperature,
        }
        response = self._post("/chat/completions", payload)
        return self._extract_chat_content(response)

    def complete_multimodal_chat(
        self,
        messages: list[dict],
        image_items: list[tuple[str, str]],
        temperature: float = 0.1,
    ) -> str:
        payload = {
            "model": self.settings.vision_chat_model,
            "messages": self._with_image_content(messages, image_items),
            "temperature": temperature,
        }
        response = self._post("/chat/completions", payload)
        return self._extract_chat_content(response)

    @staticmethod
    def _extract_chat_content(response: dict) -> str:
        try:
            return response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Chat completion response is malformed.") from exc

    def _with_image_content(self, messages: list[dict], image_items: list[tuple[str, str]]) -> list[dict]:
        converted = [dict(message) for message in messages]
        if not converted or not image_items:
            return converted
        user_message = converted[-1]
        text = str(user_message.get("content", ""))
        content: list[dict] = [{"type": "text", "text": text}]
        for label, image_path in image_items:
            content.append({"type": "text", "text": f"图片证据：{label}"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._image_to_data_url(Path(image_path))},
                }
            )
        user_message["content"] = content
        converted[-1] = user_message
        return converted

    def rerank_chunks(self, question: str, candidates: list) -> list[dict]:
        candidate_lines = []
        for index, candidate in enumerate(candidates, start=1):
            location = [f"chunk_id={candidate.chunk_id}", f"文件={candidate.filename}"]
            if candidate.page_no is not None:
                location.append(f"页码={candidate.page_no}")
            if candidate.section_title:
                location.append(f"标题={candidate.section_title}")
            candidate_lines.append(
                f"[{index}] {' | '.join(location)}\n{candidate.content[:700]}"
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是检索重排器。请仅根据问题判断候选片段与问题的相关性，"
                    "返回 JSON 数组。每个元素必须包含 chunk_id、score、evidence。"
                    "score 范围 0 到 1，保留 3 位小数。只输出 JSON，不要输出额外文本。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题：{question}\n\n候选片段：\n{chr(10).join(candidate_lines)}\n\n"
                    "请按相关性从高到低返回最多 8 条结果。"
                ),
            },
        ]
        content = self.complete_chat(messages, temperature=0.0)
        parsed = self._extract_json_array(content)
        results: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict) or "chunk_id" not in item:
                continue
            score = min(1.0, max(0.0, float(item.get("score", 0.0))))
            results.append(
                {
                    "chunk_id": str(item["chunk_id"]),
                    "score": round(score, 4),
                    "evidence": str(item.get("evidence", "")).strip(),
                }
            )
        if not results:
            raise ValueError("Empty rerank response.")
        results.sort(key=lambda item: item["score"], reverse=True)
        return results

    def stream_chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
    ) -> Generator[str, None, None]:
        payload = {
            "model": self.settings.chat_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "enable_thinking": self.settings.enable_thinking,
        }
        yield from self._stream_completion(payload)

    def stream_multimodal_chat(
        self,
        messages: list[dict],
        image_items: list[tuple[str, str]],
        temperature: float = 0.1,
    ) -> Generator[str, None, None]:
        payload = {
            "model": self.settings.vision_chat_model,
            "messages": self._with_image_content(messages, image_items),
            "temperature": temperature,
            "stream": True,
            "enable_thinking": self.settings.enable_thinking,
        }
        yield from self._stream_completion(payload)

    def _stream_completion(self, payload: dict) -> Generator[str, None, None]:
        url = f"{self.settings.dashscope_base_url.rstrip('/')}/chat/completions"
        with httpx.stream(
            "POST",
            url,
            headers=self._headers,
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        ) as response:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProviderError(self._format_error(exc.response)) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(str(exc)) from exc

            thinking_open = False
            for line in response.iter_lines():
                if not line:
                    continue
                raw = line[6:].strip() if line.startswith("data: ") else line.strip()
                if raw == "[DONE]":
                    break
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                choices = payload.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {}) or {}
                reasoning_content = delta.get("reasoning_content")
                if reasoning_content:
                    if not thinking_open:
                        thinking_open = True
                        yield "<think>\n"
                    yield reasoning_content
                content = delta.get("content")
                if content:
                    if thinking_open:
                        thinking_open = False
                        yield "\n</think>\n\n"
                    yield content
            if thinking_open:
                yield "\n</think>\n\n"

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.settings.dashscope_base_url.rstrip('/')}{path}"
        return self._post_url(url, payload)

    def _post_url(self, url: str, payload: dict) -> dict:
        with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
            try:
                response = client.post(url, headers=self._headers, json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProviderError(self._format_error(exc.response)) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(str(exc)) from exc
        return response.json()

    @staticmethod
    def _extract_json_array(content: str) -> list:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("JSON array not found in rerank response.")
        return json.loads(stripped[start : end + 1])

    @staticmethod
    def _format_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            message = data.get("error", {}).get("message") or data.get("message")
            if message:
                return f"DashScope request failed: {message}"
        except ValueError:
            pass
        return f"DashScope request failed with status {response.status_code}."


_provider: DashScopeProvider | None = None


def get_dashscope_provider() -> DashScopeProvider:
    global _provider
    if _provider is None:
        _provider = DashScopeProvider()
    return _provider
