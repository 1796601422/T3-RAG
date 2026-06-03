from app.services.dashscope_provider import DashScopeProvider


def test_stream_chat_allows_call_level_thinking_override(monkeypatch) -> None:
    provider = DashScopeProvider.__new__(DashScopeProvider)
    provider.settings = type(
        "Settings",
        (),
        {
            "chat_model": "chat",
            "vision_chat_model": "vision",
            "enable_thinking": True,
        },
    )()
    captured = {}

    def fake_stream(payload):
        captured.update(payload)
        yield "ok"

    monkeypatch.setattr(provider, "_stream_completion", fake_stream)

    assert list(provider.stream_chat([], enable_thinking=False)) == ["ok"]
    assert captured["enable_thinking"] is False


def test_stream_chat_keeps_global_thinking_default(monkeypatch) -> None:
    provider = DashScopeProvider.__new__(DashScopeProvider)
    provider.settings = type(
        "Settings",
        (),
        {
            "chat_model": "chat",
            "vision_chat_model": "vision",
            "enable_thinking": True,
        },
    )()
    captured = {}

    def fake_stream(payload):
        captured.update(payload)
        yield "ok"

    monkeypatch.setattr(provider, "_stream_completion", fake_stream)

    assert list(provider.stream_chat([])) == ["ok"]
    assert captured["enable_thinking"] is True
