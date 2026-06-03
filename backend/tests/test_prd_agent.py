from types import SimpleNamespace

from app.prompts.prd import SYSTEM_PROMPT, build_prd_messages, load_prd_skill
from app.services.conversation_memory import ConversationMemory
from app.services.prd_service import PrdService
from app.services.retrieval import RetrievalDebug, RetrievalResult, RetrievedContext


class FakeProvider:
    def __init__(self) -> None:
        self.messages = None

    def complete_chat(self, messages, temperature=0.1):
        self.messages = messages
        return "# PRD: Test\n\n## 12. Risks and Open Questions\n- Need to confirm rollout scope\n\n## 13. References\nNone"


class FakeRetriever:
    def __init__(self, result: RetrievalResult) -> None:
        self.result = result
        self.calls = []

    def retrieve(self, question, *, top_k=None, similarity_threshold=None):
        self.calls.append(
            {
                "question": question,
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
            }
        )
        return self.result


def make_context() -> RetrievedContext:
    return RetrievedContext(
        chunk_id="chunk-1",
        document_id="doc-1",
        filename="demo.md",
        page_no=1,
        section_title="Rules",
        content="Historical PRDs require ownership judgment before compensation.",
        score=0.9,
        start_offset=0,
        end_offset=20,
        retrieval_note="vector retrieval hit",
        block_types=["paragraph"],
    )


def make_service(retrieval_result: RetrievalResult) -> tuple[PrdService, FakeRetriever, FakeProvider]:
    service = PrdService.__new__(PrdService)
    provider = FakeProvider()
    retriever = FakeRetriever(retrieval_result)
    service.settings = SimpleNamespace(enable_retrieval_debug=False)
    service.provider = provider
    service.retriever = retriever
    service.memory = ConversationMemory(max_turns=10)
    return service, retriever, provider


def test_prd_prompt_uses_simple_system_prompt_and_installed_skill() -> None:
    messages = build_prd_messages(
        "Create a driver cancellation compensation PRD",
        [
            {
                "filename": "demo.md",
                "page_no": 2,
                "section_title": "Compensation rules",
                "content": "Cancellation requires ownership judgment.",
                "retrieval_note": "vector retrieval hit",
            }
        ],
        [{"role": "user", "content": "Only for reservation orders"}],
        rag_enabled=True,
    )

    content = messages[1]["content"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "具备丰富的产品知识" in SYSTEM_PROMPT
    assert "使用相同语言回复用户" in SYSTEM_PROMPT
    assert "全部改写为用户使用的语言" in SYSTEM_PROMPT
    assert "Create a driver cancellation compensation PRD" in content
    assert "Only for reservation orders" in content
    assert "Cancellation requires ownership judgment" in content
    assert "已启用历史资料检索" in content
    assert "PRD 写作 skill" in content
    assert "不要照搬 skill 中的英文标题" in content
    assert "最终回复必须与用户当前需求使用同一种语言" in content
    assert "问题陈述" in content
    assert "用户故事" in content
    assert "实现决策" in content
    assert "write-a-prd" in load_prd_skill()


def test_conversation_memory_keeps_last_10_turns() -> None:
    memory = ConversationMemory(max_turns=10)

    for index in range(12):
        memory.append_turn("session-a", f"user {index}", f"assistant {index}")

    history = memory.get("session-a")
    assert len(history) == 20
    assert history[0]["content"] == "user 2"
    assert history[-1]["content"] == "assistant 11"


def test_conversation_memory_rejects_append_after_clear() -> None:
    memory = ConversationMemory(max_turns=10)
    version = memory.version("session-a")

    memory.clear("session-a")
    appended = memory.append_turn_if_version("session-a", version, "user", "assistant")

    assert appended is False
    assert memory.get("session-a") == []


def test_prd_generate_with_rag_calls_retriever_and_returns_citations() -> None:
    result = RetrievalResult([make_context()], 0.88, None, RetrievalDebug(vector_hits=1))
    service, retriever, provider = make_service(result)

    response = service.generate("session-a", "write compensation rules", use_rag=True, top_k=5)

    assert retriever.calls == [{"question": "write compensation rules", "top_k": 5, "similarity_threshold": None}]
    assert response.rag_enabled is True
    assert response.citations[0].chunk_id == "chunk-1"
    assert response.retrieved_chunks[0].content.startswith("Historical PRDs")
    assert provider.messages is not None


def test_prd_generate_without_rag_skips_retriever() -> None:
    result = RetrievalResult([make_context()], 0.88, None)
    service, retriever, provider = make_service(result)

    response = service.generate("session-a", "write compensation rules", use_rag=False)

    assert retriever.calls == []
    assert response.rag_enabled is False
    assert response.citations == []
    assert response.retrieved_chunks == []
    assert "未启用历史资料检索" in provider.messages[1]["content"]
