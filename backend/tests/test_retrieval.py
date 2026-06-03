from types import SimpleNamespace

from app.services.retrieval import RetrievalDebug, RetrievalService, RetrievedContext


def make_rule_service() -> RetrievalService:
    service = RetrievalService.__new__(RetrievalService)
    service.keyword_store = SimpleNamespace(_tokenize=lambda text: str(text).lower().split())
    return service


def test_retrieval_rule_rerank_prefers_lexically_relevant_chunk() -> None:
    service = make_rule_service()
    candidates = [
        RetrievedContext(
            chunk_id="chunk-a",
            document_id="doc-1",
            filename="a.txt",
            page_no=None,
            section_title=None,
            content="dust storm transport path in north china",
            score=0.4,
            start_offset=0,
            end_offset=20,
            retrieval_note="vector retrieval hit",
            vector_score=0.4,
            keyword_score=0.9,
        ),
        RetrievedContext(
            chunk_id="chunk-b",
            document_id="doc-1",
            filename="b.txt",
            page_no=None,
            section_title=None,
            content="unrelated agriculture content",
            score=0.7,
            start_offset=0,
            end_offset=20,
            retrieval_note="vector retrieval hit",
            vector_score=0.7,
            keyword_score=0.0,
        ),
    ]

    reranked = service._rule_rerank("dust storm path", candidates)
    reranked.sort(key=lambda item: item.rerank_score or 0.0, reverse=True)

    assert reranked[0].chunk_id == "chunk-a"
    assert reranked[0].score == 0.575


def test_retrieval_dedupes_duplicate_neighbors() -> None:
    service = RetrievalService.__new__(RetrievalService)
    contexts = [
        RetrievedContext(
            chunk_id="chunk-a",
            document_id="doc-1",
            filename="a.txt",
            page_no=None,
            section_title=None,
            content="same content" * 30,
            score=0.8,
            start_offset=0,
            end_offset=20,
            rerank_score=0.8,
        ),
        RetrievedContext(
            chunk_id="chunk-b",
            document_id="doc-1",
            filename="a.txt",
            page_no=None,
            section_title=None,
            content="same content" * 30,
            score=0.7,
            start_offset=21,
            end_offset=40,
            rerank_score=0.7,
        ),
    ]

    deduped = service._dedupe_neighbors(contexts)

    assert len(deduped) == 1


def test_retrieval_rule_rerank_uses_raw_image_score_for_images() -> None:
    service = make_rule_service()
    candidates = [
        RetrievedContext(
            chunk_id="image-a",
            document_id="doc-1",
            filename="a.docx",
            page_no=None,
            section_title="Flow",
            content="图片块\n所属标题：扬言伤害流程图",
            score=1.0,
            start_offset=0,
            end_offset=20,
            image_score=1.0,
            block_types=["image"],
            image_path="flow.png",
        ),
        RetrievedContext(
            chunk_id="text-a",
            document_id="doc-1",
            filename="a.docx",
            page_no=None,
            section_title="Flow",
            content="some text",
            score=0.7,
            start_offset=0,
            end_offset=20,
            vector_score=0.7,
            keyword_score=0.0,
            block_types=["paragraph"],
        ),
    ]

    reranked = service._rule_rerank("扬言伤害流程", candidates)
    reranked.sort(key=lambda item: item.rerank_score or 0.0, reverse=True)

    assert reranked[0].chunk_id == "image-a"
    assert reranked[0].score > reranked[1].score
    assert reranked[0].score < 0.8


def test_image_visual_hits_use_raw_threshold_without_query_normalization() -> None:
    service = RetrievalService.__new__(RetrievalService)
    service.settings = SimpleNamespace(
        vector_top_k=0,
        image_top_k=2,
        keyword_top_k=0,
        rerank_top_n=8,
        top_k=4,
    )
    service.provider = SimpleNamespace(embed_query=lambda _question: [0.1, 0.2])
    service.keyword_store = SimpleNamespace(search=lambda _question, _top_k: [])
    low_image_point = SimpleNamespace(
        score=0.54,
        payload={
            "chunk_id": "image-low",
            "document_id": "doc-1",
            "filename": "demo.docx",
            "page_no": 1,
            "section_title": "Flow",
            "content": "image block\nheading: Flow",
            "start_offset": 0,
            "end_offset": 20,
            "block_types": ["image"],
            "image_path": "flow.png",
            "vector_variant": "image_visual",
        },
    )
    high_image_point = SimpleNamespace(
        score=0.7,
        payload={
            "chunk_id": "image-high",
            "document_id": "doc-1",
            "filename": "demo.docx",
            "page_no": 1,
            "section_title": "Flow",
            "content": "image block\nheading: Flow",
            "start_offset": 0,
            "end_offset": 20,
            "block_types": ["image"],
            "image_path": "flow.png",
            "vector_variant": "image_visual",
        },
    )
    service.vector_store = SimpleNamespace(
        query=lambda **_kwargs: {"points": []},
        query_by_block_type=lambda **_kwargs: {"points": [high_image_point, low_image_point]},
        get_by_chunk_ids=lambda _chunk_ids: {},
    )

    candidates = service._merge_candidates("unrelated", similarity_threshold=0.55, debug=RetrievalDebug())

    assert [item.chunk_id for item in candidates] == ["image-high"]
    assert candidates[0].image_score == 0.7


def test_merge_candidates_separates_text_and_image_visual_vector_queries() -> None:
    service = RetrievalService.__new__(RetrievalService)
    service.settings = SimpleNamespace(
        vector_top_k=12,
        image_top_k=5,
        keyword_top_k=0,
        rerank_top_n=8,
        top_k=4,
    )
    service.provider = SimpleNamespace(embed_query=lambda _question: [0.1, 0.2])
    service.keyword_store = SimpleNamespace(search=lambda _question, _top_k: [])
    calls = {}

    def query(**kwargs):
        calls["query"] = kwargs
        return {"points": []}

    def query_by_block_type(**kwargs):
        calls["query_by_block_type"] = kwargs
        return {"points": []}

    service.vector_store = SimpleNamespace(
        query=query,
        query_by_block_type=query_by_block_type,
        get_by_chunk_ids=lambda _chunk_ids: {},
    )

    service._merge_candidates("anything", similarity_threshold=0.55, debug=RetrievalDebug())

    assert calls["query"]["excluded_vector_variants"] == ["image_visual"]
    assert calls["query"]["top_k"] == 8
    assert calls["query_by_block_type"]["block_type"] == "image"
    assert calls["query_by_block_type"]["vector_variant"] == "image_visual"
    assert calls["query_by_block_type"]["top_k"] == 4


def test_merge_candidates_does_not_truncate_before_final_rerank() -> None:
    service = RetrievalService.__new__(RetrievalService)
    service.settings = SimpleNamespace()
    service.provider = SimpleNamespace(embed_query=lambda _question: [0.1, 0.2])
    service.keyword_store = SimpleNamespace(search=lambda _question, _top_k: [])

    vector_points = [
        SimpleNamespace(
            score=0.9 - index * 0.01,
            payload={
                "chunk_id": f"vector-{index}",
                "document_id": "doc-1",
                "filename": "demo.docx",
                "page_no": 1,
                "section_title": "Flow",
                "content": "flow content",
                "start_offset": 0,
                "end_offset": 20,
                "block_types": ["paragraph"],
                "image_path": "",
                "vector_variant": "text",
            },
        )
        for index in range(8)
    ]
    image_points = [
        SimpleNamespace(
            score=0.82 + index * 0.01,
            payload={
                "chunk_id": f"image-{index}",
                "document_id": "doc-1",
                "filename": "demo.docx",
                "page_no": 1,
                "section_title": "Flow",
                "content": "image flow content",
                "start_offset": 0,
                "end_offset": 20,
                "block_types": ["image"],
                "image_path": "flow.png",
                "vector_variant": "image_visual",
            },
        )
        for index in range(4)
    ]
    service.vector_store = SimpleNamespace(
        query=lambda **_kwargs: {"points": vector_points},
        query_by_block_type=lambda **_kwargs: {"points": image_points},
        get_by_chunk_ids=lambda _chunk_ids: {},
    )

    candidates = service._merge_candidates("flow", similarity_threshold=0.55, debug=RetrievalDebug())

    assert len(candidates) == 12
    assert {item.chunk_id for item in candidates} == {
        *(f"vector-{index}" for index in range(8)),
        *(f"image-{index}" for index in range(4)),
    }


def test_high_confidence_vector_candidate_is_kept_even_when_final_score_is_low() -> None:
    service = make_rule_service()
    candidate = RetrievedContext(
        chunk_id="vector-high",
        document_id="doc-1",
        filename="demo.docx",
        page_no=None,
        section_title=None,
        content="unrelated content",
        score=0.86,
        start_offset=0,
        end_offset=20,
        vector_score=0.86,
    )

    service._rule_rerank("dust storm path", [candidate])

    assert candidate.rerank_score < 0.6
    assert service._should_keep(candidate) is True


def test_visual_and_table_blocks_get_extra_title_weight_with_score_cap() -> None:
    service = make_rule_service()
    text_candidate = RetrievedContext(
        chunk_id="text",
        document_id="doc-1",
        filename="demo.docx",
        page_no=None,
        section_title="traffic accident flow",
        content="unrelated body",
        score=0.4,
        start_offset=0,
        end_offset=20,
        vector_score=0.4,
        block_types=["paragraph"],
    )
    table_candidate = RetrievedContext(
        chunk_id="table",
        document_id="doc-1",
        filename="demo.docx",
        page_no=None,
        section_title="traffic accident flow",
        content="unrelated body",
        score=0.4,
        start_offset=0,
        end_offset=20,
        vector_score=0.4,
        block_types=["table"],
    )
    image_candidate = RetrievedContext(
        chunk_id="image",
        document_id="doc-1",
        filename="demo.docx",
        page_no=None,
        section_title="traffic accident flow",
        content="traffic accident flow",
        score=0.95,
        start_offset=0,
        end_offset=20,
        image_score=0.95,
        keyword_score=1.0,
        block_types=["image"],
    )

    service._rule_rerank("traffic accident flow", [text_candidate, table_candidate, image_candidate])

    assert text_candidate.rerank_score == 0.3
    assert table_candidate.rerank_score == 0.5
    assert image_candidate.rerank_score == 1.0
    assert "title_weight=0.10" in text_candidate.retrieval_note
    assert "title_weight=0.30" in table_candidate.retrieval_note
    assert "title_weight=0.30" in image_candidate.retrieval_note


def test_retrieve_returns_top_five_rejected_candidates_sorted_by_score() -> None:
    service = RetrievalService.__new__(RetrievalService)
    service.settings = SimpleNamespace(
        similarity_threshold=0.55,
        top_k=4,
        max_context_chars=4000,
    )
    accepted = RetrievedContext(
        chunk_id="accepted",
        document_id="doc-1",
        filename="demo.docx",
        page_no=None,
        section_title=None,
        content="accepted content",
        score=0.61,
        start_offset=0,
        end_offset=20,
        rerank_score=0.61,
    )
    rejected = [
        RetrievedContext(
            chunk_id=f"rejected-{index}",
            document_id="doc-1",
            filename="demo.docx",
            page_no=None,
            section_title=None,
            content=f"rejected content {index}",
            score=score,
            start_offset=0,
            end_offset=20,
            rerank_score=score,
        )
        for index, score in enumerate([0.59, 0.12, 0.58, 0.41, 0.57, 0.56, 0.55], start=1)
    ]
    candidates = [accepted, *rejected]
    service._merge_candidates = lambda _question, *, similarity_threshold, debug: candidates
    service._rerank = lambda _question, items: sorted(items, key=lambda item: item.rerank_score or 0.0, reverse=True)

    result = service.retrieve("flow")

    assert [item.chunk_id for item in result.contexts] == ["accepted"]
    assert [item.chunk_id for item in result.rejected_contexts] == [
        "rejected-1",
        "rejected-3",
        "rejected-5",
        "rejected-6",
        "rejected-7",
    ]
