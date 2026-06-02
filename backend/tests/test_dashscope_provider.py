from app.services.dashscope_provider import DashScopeProvider


def test_stream_delta_parsing_skips_empty_choices(monkeypatch) -> None:
    provider = DashScopeProvider()

    def fake_stream(*args, **kwargs):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def raise_for_status(self):
                return None

            def iter_lines(self):
                return iter(
                    [
                        'data: {"choices":[{"delta":{"content":"hello"}}]}',
                        'data: {"choices":[]}',
                        'data: {"choices":[{"delta":{"content":" world"}}]}',
                        "data: [DONE]",
                    ]
                )

        return Response()

    monkeypatch.setattr("app.services.dashscope_provider.httpx.stream", fake_stream)
    provider.settings.dashscope_api_key = "test-key"

    assert list(provider.stream_chat([{"role": "user", "content": "hi"}])) == [
        "hello",
        " world",
    ]


def test_multimodal_text_embedding_payload(monkeypatch) -> None:
    provider = DashScopeProvider()
    provider.settings.dashscope_api_key = "test-key"
    provider.settings.embedding_model = "tongyi-embedding-vision-flash-2026-03-06"
    provider.settings.embedding_dimension = 768
    captured = {}

    def fake_post_url(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {
            "output": {
                "embeddings": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            }
        }

    monkeypatch.setattr(provider, "_post_url", fake_post_url)

    embeddings = provider.embed_texts(["first", "second"])

    assert "multimodal-embedding" in captured["url"]
    assert captured["payload"]["model"] == "tongyi-embedding-vision-flash-2026-03-06"
    assert captured["payload"]["parameters"] == {"dimension": 768}
    assert captured["payload"]["input"]["contents"] == [{"text": "first"}, {"text": "second"}]
    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]


def test_multimodal_image_embedding_payload(monkeypatch, tmp_path) -> None:
    provider = DashScopeProvider()
    provider.settings.dashscope_api_key = "test-key"
    provider.settings.embedding_model = "tongyi-embedding-vision-flash-2026-03-06"
    provider.settings.embedding_dimension = 768
    image_path = tmp_path / "flow.png"
    image_path.write_bytes(b"fake-image")
    captured = {}

    def fake_post_url(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"output": {"embeddings": [{"index": 0, "embedding": [0.1, 0.2]}]}}

    monkeypatch.setattr(provider, "_post_url", fake_post_url)

    embeddings = provider.embed_image_paths([str(image_path)])

    assert "multimodal-embedding" in captured["url"]
    assert captured["payload"]["input"]["contents"][0]["image"].startswith("data:image/png;base64,")
    assert embeddings == [[0.1, 0.2]]


def test_multimodal_chat_payload_includes_images(monkeypatch, tmp_path) -> None:
    provider = DashScopeProvider()
    provider.settings.dashscope_api_key = "test-key"
    provider.settings.vision_chat_model = "qwen3.6-flash"
    image_path = tmp_path / "flow.png"
    image_path.write_bytes(b"fake-image")
    captured = {}

    def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "answer"}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    answer = provider.complete_multimodal_chat(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "question"}],
        [("[1] flow", str(image_path))],
    )

    user_content = captured["payload"]["messages"][-1]["content"]
    assert answer == "answer"
    assert captured["path"] == "/chat/completions"
    assert captured["payload"]["model"] == "qwen3.6-flash"
    assert user_content[0] == {"type": "text", "text": "question"}
    assert user_content[1] == {"type": "text", "text": "图片证据：[1] flow"}
    assert user_content[2]["type"] == "image_url"
    assert user_content[2]["image_url"]["url"].startswith("data:image/png;base64,")
