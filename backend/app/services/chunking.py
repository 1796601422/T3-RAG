from dataclasses import dataclass
import uuid

from app.services.document_parser import ParsedSection


SENTENCE_BOUNDARIES = [
    "\n\n",
    "\n",
    "\u3002",
    "\uff01",
    "\uff1f",
    "\uff1b",
    ".",
    "!",
    "?",
    ";",
    ",",
    "\uff0c",
    " ",
]

TEXT_BLOCK_TYPES = {"paragraph", "list"}
STANDALONE_BLOCK_TYPES = {"table", "image"}


@dataclass(slots=True)
class ChunkPayload:
    chunk_id: str
    chroma_id: str
    content: str
    embedding_text: str
    document_id: str
    filename: str
    page_no: int | None
    section_title: str | None
    start_offset: int
    end_offset: int
    section_level: int
    block_types: list[str]
    source_order_start: int
    source_order_end: int
    image_path: str | None = None


def split_sections_into_chunks(
    *,
    document_id: str,
    filename: str,
    sections: list[ParsedSection],
    chunk_size: int,
    chunk_overlap: int,
    min_chunk_size: int = 120,
    max_chunk_size: int | None = None,
) -> list[ChunkPayload]:
    del min_chunk_size
    ordered_sections = [section for section in sections if section.text]
    offsets = _build_section_offsets(ordered_sections)
    chunks: list[ChunkPayload] = []
    text_group: list[ParsedSection] = []
    max_chunk_size = max_chunk_size or chunk_size

    def flush_text_group() -> None:
        nonlocal text_group
        if not text_group:
            return
        _append_group_chunks(
            chunks=chunks,
            group=text_group,
            document_id=document_id,
            filename=filename,
            section_offsets=offsets,
            target_chunk_size=chunk_size,
            max_chunk_size=max_chunk_size,
            chunk_overlap=chunk_overlap,
        )
        text_group = []

    for section in ordered_sections:
        if section.block_type == "heading":
            flush_text_group()
            continue

        if section.block_type in STANDALONE_BLOCK_TYPES:
            flush_text_group()
            _append_group_chunks(
                chunks=chunks,
                group=[section],
                document_id=document_id,
                filename=filename,
                section_offsets=offsets,
                target_chunk_size=chunk_size,
                max_chunk_size=max_chunk_size,
                chunk_overlap=chunk_overlap,
            )
            continue

        if section.block_type not in TEXT_BLOCK_TYPES:
            flush_text_group()
            _append_group_chunks(
                chunks=chunks,
                group=[section],
                document_id=document_id,
                filename=filename,
                section_offsets=offsets,
                target_chunk_size=chunk_size,
                max_chunk_size=max_chunk_size,
                chunk_overlap=chunk_overlap,
            )
            continue

        candidate = text_group + [section]
        if text_group and _group_text_length(candidate) > max_chunk_size:
            flush_text_group()
            text_group = [section]
            continue
        text_group = candidate

    flush_text_group()
    return chunks


def _append_group_chunks(
    *,
    chunks: list[ChunkPayload],
    group: list[ParsedSection],
    document_id: str,
    filename: str,
    section_offsets: dict[int, tuple[int, int]],
    target_chunk_size: int,
    max_chunk_size: int,
    chunk_overlap: int,
) -> None:
    group = [section for section in group if section.block_type != "heading"]
    if not group:
        return
    combined = "\n\n".join(section.text for section in group).strip()
    if len(combined) <= max_chunk_size:
        _append_chunk(
            chunks=chunks,
            document_id=document_id,
            filename=filename,
            group=group,
            content=combined,
            start_offset=section_offsets[id(group[0])][0],
            end_offset=section_offsets[id(group[-1])][1],
        )
        return

    spans = _split_text_with_boundaries(combined, target_chunk_size, chunk_overlap)
    group_start_offset = section_offsets[id(group[0])][0]
    for start, end, content in spans:
        _append_chunk(
            chunks=chunks,
            document_id=document_id,
            filename=filename,
            group=group,
            content=content,
            start_offset=group_start_offset + start,
            end_offset=group_start_offset + end,
        )


def _append_chunk(
    *,
    chunks: list[ChunkPayload],
    document_id: str,
    filename: str,
    group: list[ParsedSection],
    content: str,
    start_offset: int,
    end_offset: int,
) -> None:
    chunk_number = len(chunks) + 1
    chunk_id = f"{document_id}_{chunk_number:04d}"
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
    page_numbers = [section.page_no for section in group if section.page_no is not None]
    section_titles = [section.section_title for section in group if section.section_title]
    display_content = _with_document_context_prefix(filename, group, content)
    chunks.append(
        ChunkPayload(
            chunk_id=chunk_id,
            chroma_id=point_id,
            content=display_content,
            embedding_text=display_content,
            document_id=document_id,
            filename=filename,
            page_no=page_numbers[0] if page_numbers else None,
            section_title=section_titles[-1] if section_titles else None,
            start_offset=start_offset,
            end_offset=end_offset,
            section_level=min(section.section_level for section in group),
            block_types=list(dict.fromkeys(section.block_type for section in group)),
            source_order_start=min(section.source_order for section in group),
            source_order_end=max(section.source_order for section in group),
            image_path=next((section.image_path for section in group if section.image_path), None),
        )
    )


def _build_section_offsets(sections: list[ParsedSection]) -> dict[int, tuple[int, int]]:
    offsets: dict[int, tuple[int, int]] = {}
    current_offset = 0
    for section in sections:
        start = current_offset
        end = start + len(section.text)
        offsets[id(section)] = (start, end)
        current_offset = end + 2
    return offsets


def _group_text_length(group: list[ParsedSection]) -> int:
    return len("\n\n".join(section.text for section in group))


def _split_text_with_boundaries(text: str, chunk_size: int, chunk_overlap: int) -> list[tuple[int, int, str]]:
    normalized = text.strip()
    if not normalized:
        return []

    spans: list[tuple[int, int, str]] = []
    start = 0
    length = len(normalized)
    chunk_size = max(1, chunk_size)

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            boundary = _find_boundary(normalized, start, end)
            if boundary > start:
                end = boundary
        chunk_text = normalized[start:end].strip()
        if chunk_text:
            spans.append((start, start + len(chunk_text), chunk_text))
        if end >= length:
            break
        start = max(end - chunk_overlap, start + 1)

    return spans


def _find_boundary(text: str, start: int, end: int) -> int:
    search_floor = start + int((end - start) * 0.6)
    best = -1
    best_sep_len = 0
    for separator in SENTENCE_BOUNDARIES:
        index = text.rfind(separator, search_floor, end)
        if index > best:
            best = index
            best_sep_len = len(separator)
    if best == -1:
        return end
    return best + best_sep_len


def _heading_path_prefix(group: list[ParsedSection]) -> str:
    paths = [section.heading_path for section in group if section.heading_path]
    if not paths:
        return ""
    path = max(paths, key=len)
    return f"\u6807\u9898\u8def\u5f84\uff1a{' > '.join(path)}"


def _document_title(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].strip()
    return stem or filename.strip() or "\u672a\u547d\u540d\u6587\u6863"


def _with_document_context_prefix(filename: str, group: list[ParsedSection], content: str) -> str:
    prefixes = [f"\u6587\u6863\u6807\u9898\uff1a{_document_title(filename)}"]
    heading_prefix = _heading_path_prefix(group)
    if heading_prefix:
        prefixes.append(heading_prefix)
    body = content.strip()
    if body.startswith(prefixes[0]):
        return body
    return "\n".join([*prefixes, "", body]).strip()
