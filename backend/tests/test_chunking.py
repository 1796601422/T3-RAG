import uuid

from app.services.chunking import split_sections_into_chunks
from app.services.document_parser import ParsedSection


def test_split_sections_into_chunks_uses_heading_as_context_not_body() -> None:
    sections = [
        ParsedSection(
            text="1. Background",
            page_no=3,
            section_title="1. Background",
            section_level=1,
            block_type="heading",
            source_order=1,
            heading_path=("1. Background",),
        ),
        ParsedSection(
            text="First paragraph. " * 20,
            page_no=3,
            section_title="1. Background",
            section_level=1,
            block_type="paragraph",
            source_order=2,
            heading_path=("1. Background",),
        ),
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-1",
        filename="demo.pdf",
        sections=sections,
        chunk_size=160,
        chunk_overlap=20,
        min_chunk_size=40,
        max_chunk_size=260,
    )

    assert len(chunks) >= 1
    assert chunks[0].section_title == "1. Background"
    assert chunks[0].content.startswith("文档标题：demo")
    assert chunks[0].embedding_text.startswith("文档标题：demo")
    assert "标题路径：1. Background" in chunks[0].content
    assert "heading" not in chunks[0].block_types
    assert chunks[0].block_types == ["paragraph"]
    assert chunks[0].start_offset > 0
    for chunk in chunks:
        assert str(uuid.UUID(chunk.chroma_id)) == chunk.chroma_id


def test_split_sections_into_chunks_splits_long_sections_with_overlap() -> None:
    sections = [
        ParsedSection(
            text="Sentence one. Sentence two. Sentence three. " * 20,
            page_no=1,
            section_title="Overview",
            section_level=1,
            block_type="paragraph",
            source_order=1,
            heading_path=("Overview",),
        )
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-2",
        filename="demo.txt",
        sections=sections,
        chunk_size=120,
        chunk_overlap=25,
        min_chunk_size=60,
        max_chunk_size=120,
    )

    assert len(chunks) > 1
    assert all(chunk.section_level == 1 for chunk in chunks)
    assert chunks[1].start_offset < chunks[0].end_offset


def test_split_sections_into_chunks_preserves_table_block_type() -> None:
    sections = [
        ParsedSection(
            text="Costs",
            page_no=2,
            section_title="Costs",
            section_level=1,
            block_type="heading",
            source_order=1,
            heading_path=("Costs",),
        ),
        ParsedSection(
            text="| Item | Price |\n| --- | --- |\n| Basic | 10 |\n| Pro | 20 |",
            page_no=2,
            section_title="Costs",
            section_level=1,
            block_type="table",
            source_order=2,
            heading_path=("Costs",),
        ),
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-3",
        filename="demo.docx",
        sections=sections,
        chunk_size=160,
        chunk_overlap=20,
        min_chunk_size=20,
        max_chunk_size=260,
    )

    assert len(chunks) == 1
    assert chunks[0].block_types == ["table"]
    assert "heading" not in chunks[0].block_types
    assert "标题路径：Costs" in chunks[0].content
    assert "| Basic | 10 |" in chunks[0].content


def test_split_sections_into_chunks_keeps_text_blocks_until_max_size() -> None:
    sections = [
        ParsedSection(
            text="Usage",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="heading",
            source_order=1,
            heading_path=("Usage",),
        ),
        ParsedSection(
            text="A" * 80,
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="paragraph",
            source_order=2,
            heading_path=("Usage",),
        ),
        ParsedSection(
            text="B" * 80,
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="paragraph",
            source_order=3,
            heading_path=("Usage",),
        ),
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-4",
        filename="demo.docx",
        sections=sections,
        chunk_size=200,
        chunk_overlap=20,
        min_chunk_size=60,
        max_chunk_size=220,
    )

    assert len(chunks) == 1
    assert "A" * 80 in chunks[0].content
    assert "B" * 80 in chunks[0].content


def test_split_sections_into_chunks_combines_paragraph_and_list_before_table() -> None:
    sections = [
        ParsedSection(
            text="Usage",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="heading",
            source_order=1,
            heading_path=("Usage",),
        ),
        ParsedSection(
            text="Paragraph detail. " * 8,
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="paragraph",
            source_order=2,
            heading_path=("Usage",),
        ),
        ParsedSection(
            text="1. First step",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="list",
            source_order=3,
            heading_path=("Usage",),
        ),
        ParsedSection(
            text="2. Second step",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="list",
            source_order=4,
            heading_path=("Usage",),
        ),
        ParsedSection(
            text="| Field | Meaning |\n| --- | --- |\n| A | B |",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="table",
            source_order=5,
            heading_path=("Usage",),
        ),
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-5",
        filename="demo.docx",
        sections=sections,
        chunk_size=260,
        chunk_overlap=20,
        min_chunk_size=20,
        max_chunk_size=260,
    )

    assert len(chunks) == 2
    assert chunks[0].block_types == ["paragraph", "list"]
    assert chunks[1].block_types == ["table"]
    assert "1. First step" in chunks[0].content
    assert "2. Second step" in chunks[0].content


def test_split_sections_into_chunks_includes_parent_heading_path() -> None:
    sections = [
        ParsedSection(
            text="3.1 Fish Usage",
            page_no=None,
            section_title="Product > RPA > 3.1 Fish Usage",
            section_level=3,
            block_type="heading",
            source_order=1,
            heading_path=("Product", "RPA", "3.1 Fish Usage"),
        ),
        ParsedSection(
            text="Bind the fish account before running the robot.",
            page_no=None,
            section_title="Product > RPA > 3.1 Fish Usage",
            section_level=3,
            block_type="paragraph",
            source_order=2,
            heading_path=("Product", "RPA", "3.1 Fish Usage"),
        ),
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-6",
        filename="demo.md",
        sections=sections,
        chunk_size=160,
        chunk_overlap=20,
        min_chunk_size=20,
        max_chunk_size=260,
    )

    assert chunks[0].section_title == "Product > RPA > 3.1 Fish Usage"
    assert chunks[0].content.startswith("文档标题：demo")
    assert "标题路径：Product > RPA > 3.1 Fish Usage" in chunks[0].content
    assert chunks[0].embedding_text == chunks[0].content
    assert chunks[0].block_types == ["paragraph"]


def test_split_sections_into_chunks_adds_document_title_to_every_chunk() -> None:
    sections = [
        ParsedSection(
            text="Overview",
            page_no=None,
            section_title="Overview",
            section_level=1,
            block_type="heading",
            source_order=1,
            heading_path=("Overview",),
        ),
        ParsedSection(
            text="Driver cancellation compensation rules. " * 12,
            page_no=None,
            section_title="Overview",
            section_level=1,
            block_type="paragraph",
            source_order=2,
            heading_path=("Overview",),
        ),
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-title",
        filename="【0304】交通事故场景自动化2.0-支持事故人伤.docx",
        sections=sections,
        chunk_size=120,
        chunk_overlap=20,
        min_chunk_size=20,
        max_chunk_size=120,
    )

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.content.startswith("文档标题：【0304】交通事故场景自动化2.0-支持事故人伤")
        assert chunk.embedding_text.startswith("文档标题：【0304】交通事故场景自动化2.0-支持事故人伤")


def test_split_sections_into_chunks_drops_heading_only_sections() -> None:
    sections = [
        ParsedSection(
            text="Only Heading",
            page_no=None,
            section_title="Only Heading",
            section_level=1,
            block_type="heading",
            source_order=1,
            heading_path=("Only Heading",),
        )
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-heading",
        filename="demo.docx",
        sections=sections,
        chunk_size=120,
        chunk_overlap=20,
        min_chunk_size=20,
        max_chunk_size=120,
    )

    assert chunks == []


def test_split_sections_into_chunks_flushes_text_on_new_heading() -> None:
    sections = [
        ParsedSection(
            text="A",
            page_no=None,
            section_title="A",
            section_level=1,
            block_type="heading",
            source_order=1,
            heading_path=("A",),
        ),
        ParsedSection(
            text="Alpha body.",
            page_no=None,
            section_title="A",
            section_level=1,
            block_type="paragraph",
            source_order=2,
            heading_path=("A",),
        ),
        ParsedSection(
            text="B",
            page_no=None,
            section_title="B",
            section_level=1,
            block_type="heading",
            source_order=3,
            heading_path=("B",),
        ),
        ParsedSection(
            text="Beta body.",
            page_no=None,
            section_title="B",
            section_level=1,
            block_type="paragraph",
            source_order=4,
            heading_path=("B",),
        ),
    ]

    chunks = split_sections_into_chunks(
        document_id="doc-boundary",
        filename="demo.docx",
        sections=sections,
        chunk_size=200,
        chunk_overlap=20,
        min_chunk_size=20,
        max_chunk_size=200,
    )

    assert len(chunks) == 2
    assert "Alpha body." in chunks[0].content
    assert "Beta body." not in chunks[0].content
    assert "Beta body." in chunks[1].content
    assert "标题路径：A" in chunks[0].content
    assert "标题路径：B" in chunks[1].content
