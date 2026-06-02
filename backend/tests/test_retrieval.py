from app.services.retrieval import RetrievalDebug, RetrievalService, RetrievedContext


def test_retrieval_rule_rerank_prefers_lexically_relevant_chunk() -> None:
    service = RetrievalService()
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
    assert reranked[0].score == 0.585


def test_retrieval_dedupes_duplicate_neighbors() -> None:
    service = RetrievalService()
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


def test_retrieval_rule_rerank_uses_normalized_image_score_for_images() -> None:
    service = RetrievalService()
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
