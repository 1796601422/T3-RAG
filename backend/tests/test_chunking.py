import uuid

from app.services.chunking import split_sections_into_chunks
from app.services.document_parser import ParsedSection


def test_split_sections_into_chunks_merges_heading_with_body() -> None:
    sections = [
        ParsedSection(
            text="1. Background",
            page_no=3,
            section_title="1. Background",
            section_level=1,
            block_type="heading",
            source_order=1,
        ),
        ParsedSection(
            text="First paragraph. " * 20,
            page_no=3,
            section_title="1. Background",
            section_level=1,
            block_type="paragraph",
            source_order=2,
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
    assert "Background" in chunks[0].content
    assert "heading" in chunks[0].block_types
    assert chunks[0].start_offset == 0
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
        ),
        ParsedSection(
            text="| Item | Price |\n| --- | --- |\n| Basic | 10 |\n| Pro | 20 |",
            page_no=2,
            section_title="Costs",
            section_level=1,
            block_type="table",
            source_order=2,
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
    assert "table" in chunks[0].block_types
    assert "| Basic | 10 |" in chunks[0].content


def test_split_sections_into_chunks_keeps_same_type_until_max_size() -> None:
    sections = [
        ParsedSection(
            text="Usage",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="heading",
            source_order=1,
        ),
        ParsedSection(
            text="A" * 80,
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="paragraph",
            source_order=2,
        ),
        ParsedSection(
            text="B" * 80,
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="paragraph",
            source_order=3,
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


def test_split_sections_into_chunks_splits_when_block_type_changes() -> None:
    sections = [
        ParsedSection(
            text="Usage",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="heading",
            source_order=1,
        ),
        ParsedSection(
            text="Paragraph detail. " * 8,
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="paragraph",
            source_order=2,
        ),
        ParsedSection(
            text="1. First step",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="list",
            source_order=3,
        ),
        ParsedSection(
            text="2. Second step",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="list",
            source_order=4,
        ),
        ParsedSection(
            text="| Field | Meaning |\n| --- | --- |\n| A | B |",
            page_no=None,
            section_title="Usage",
            section_level=1,
            block_type="table",
            source_order=5,
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

    assert len(chunks) == 3
    assert chunks[0].block_types == ["heading", "paragraph"]
    assert chunks[1].block_types == ["list"]
    assert chunks[2].block_types == ["table"]
    assert "1. First step" in chunks[1].content
    assert "2. Second step" in chunks[1].content


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
        document_id="doc-4",
        filename="demo.md",
        sections=sections,
        chunk_size=160,
        chunk_overlap=20,
        min_chunk_size=20,
        max_chunk_size=260,
    )

    assert chunks[0].section_title == "Product > RPA > 3.1 Fish Usage"
    assert chunks[0].content.startswith("标题路径：Product > RPA > 3.1 Fish Usage")
