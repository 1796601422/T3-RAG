from dataclasses import dataclass
from pathlib import Path
import re

import fitz
import pdfplumber
from docx.document import Document as DocxDocumentType
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.config import get_settings
from app.services.text_cleaner import clean_text


CHINESE_NUMERALS = "\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341"
SECTION_PREFIX_PATTERN = rf"^(\u7b2c[{CHINESE_NUMERALS}0-9]+[\u7ae0\u8282\u90e8\u5206\u7bc7]|[{CHINESE_NUMERALS}]+[\u3001\uff0e.]|[0-9]+(?:\.[0-9]+){{1,3}})"
LIST_LINE_PATTERN = rf"^\s*(([-*+]|[0-9]+[.)])\s+|[{CHINESE_NUMERALS}]+[\u3001.]\s*)"


@dataclass(slots=True)
class ParsedSection:
    text: str
    page_no: int | None
    section_title: str | None
    section_level: int
    block_type: str
    source_order: int
    heading_path: tuple[str, ...] = ()
    image_path: str | None = None


class DocumentParser:
    def parse(self, file_path: Path, file_type: str, document_id: str | None = None) -> list[ParsedSection]:
        if file_type == "pdf":
            return self._parse_pdf(file_path, document_id=document_id)
        if file_type == "docx":
            return self._parse_docx(file_path, document_id=document_id)
        if file_type == "md":
            return self._parse_markdown(file_path)
        if file_type == "txt":
            return self._parse_txt(file_path)
        raise ValueError(f"Unsupported file type: {file_type}")

    def _parse_pdf(self, file_path: Path, *, document_id: str | None = None) -> list[ParsedSection]:
        sections: list[ParsedSection] = []
        heading_stack: dict[int, str] = {}
        current_level = 1
        source_order = 0
        tables_by_page = self._extract_pdf_tables(file_path)
        with fitz.open(file_path) as document:
            for page_no, page in enumerate(document, start=1):
                paragraph_buffer: list[str] = []
                list_buffer: list[str] = []
                blocks = [
                    block
                    for block in page.get_text("blocks")
                    if len(block) >= 5 and str(block[4]).strip()
                ]
                blocks.sort(key=lambda item: (round(float(item[1]), 1), round(float(item[0]), 1)))

                def flush_paragraph() -> None:
                    nonlocal source_order
                    if not paragraph_buffer:
                        return
                    text = clean_text("\n".join(paragraph_buffer))
                    paragraph_buffer.clear()
                    if not text:
                        return
                    source_order += 1
                    sections.append(
                        ParsedSection(
                            text=text,
                            page_no=page_no,
                            section_title=self._format_heading_path(heading_stack),
                            section_level=current_level,
                            block_type="paragraph",
                            source_order=source_order,
                            heading_path=self._heading_path(heading_stack),
                        )
                    )

                def flush_list() -> None:
                    nonlocal source_order
                    if not list_buffer:
                        return
                    text = clean_text("\n".join(list_buffer))
                    list_buffer.clear()
                    if not text:
                        return
                    source_order += 1
                    sections.append(
                        ParsedSection(
                            text=text,
                            page_no=page_no,
                            section_title=self._format_heading_path(heading_stack),
                            section_level=current_level,
                            block_type="list",
                            source_order=source_order,
                            heading_path=self._heading_path(heading_stack),
                        )
                    )

                for block in blocks:
                    raw = str(block[4]).strip()
                    for segment in raw.split("\n\n"):
                        text = clean_text(segment)
                        if not text:
                            continue
                        if self._looks_like_heading(text):
                            flush_paragraph()
                            flush_list()
                            current_level = self._infer_heading_level(text)
                            self._update_heading_stack(heading_stack, current_level, text)
                            source_order += 1
                            sections.append(
                                ParsedSection(
                                    text=text,
                                    page_no=page_no,
                                    section_title=self._format_heading_path(heading_stack),
                                    section_level=current_level,
                                    block_type="heading",
                                    source_order=source_order,
                                    heading_path=self._heading_path(heading_stack),
                                )
                            )
                            continue
                        if self._looks_like_list_line(text):
                            flush_paragraph()
                            list_buffer.append(text)
                            continue
                        flush_list()
                        paragraph_buffer.append(text)
                flush_paragraph()
                flush_list()
                for table_text in tables_by_page.get(page_no, []):
                    source_order += 1
                    sections.append(
                        ParsedSection(
                            text=table_text,
                            page_no=page_no,
                            section_title=self._format_heading_path(heading_stack),
                            section_level=current_level,
                            block_type="table",
                            source_order=source_order,
                            heading_path=self._heading_path(heading_stack),
                        )
                    )
                for image_path in self._extract_pdf_page_images(document, page, page_no, file_path, document_id):
                    source_order += 1
                    sections.append(
                        ParsedSection(
                            text=self._image_section_text(image_path, heading_stack),
                            page_no=page_no,
                            section_title=self._format_heading_path(heading_stack),
                            section_level=current_level,
                            block_type="image",
                            source_order=source_order,
                            heading_path=self._heading_path(heading_stack),
                            image_path=str(image_path),
                        )
                    )
        return sections

    def _parse_docx(self, file_path: Path, *, document_id: str | None = None) -> list[ParsedSection]:
        sections: list[ParsedSection] = []
        document = DocxDocument(file_path)
        heading_stack: dict[int, str] = {}
        current_level = 1
        source_order = 0
        buffer: list[str] = []
        list_buffer: list[str] = []

        def flush_buffer() -> None:
            nonlocal source_order
            if not buffer:
                return
            text = clean_text("\n".join(buffer))
            buffer.clear()
            if not text:
                return
            source_order += 1
            sections.append(
                ParsedSection(
                    text=text,
                    page_no=None,
                    section_title=self._format_heading_path(heading_stack),
                    section_level=current_level,
                    block_type="paragraph",
                    source_order=source_order,
                    heading_path=self._heading_path(heading_stack),
                )
            )

        def flush_list() -> None:
            nonlocal source_order
            if not list_buffer:
                return
            text = clean_text("\n".join(list_buffer))
            list_buffer.clear()
            if not text:
                return
            source_order += 1
            sections.append(
                ParsedSection(
                    text=text,
                    page_no=None,
                    section_title=self._format_heading_path(heading_stack),
                    section_level=current_level,
                    block_type="list",
                    source_order=source_order,
                    heading_path=self._heading_path(heading_stack),
                )
            )

        for block in self._iter_docx_blocks(document):
            if isinstance(block, Table):
                flush_buffer()
                flush_list()
                table_text = self._table_to_markdown(
                    [[cell.text for cell in row.cells] for row in block.rows]
                )
                if not table_text:
                    continue
                source_order += 1
                sections.append(
                    ParsedSection(
                        text=table_text,
                        page_no=None,
                        section_title=self._format_heading_path(heading_stack),
                        section_level=current_level,
                        block_type="table",
                        source_order=source_order,
                        heading_path=self._heading_path(heading_stack),
                    )
                )
                continue

            paragraph = block
            image_paths = self._extract_docx_paragraph_images(paragraph, file_path, document_id)
            content = paragraph.text.strip()
            if image_paths:
                flush_buffer()
                flush_list()
                for image_path in image_paths:
                    source_order += 1
                    sections.append(
                        ParsedSection(
                            text=self._image_section_text(image_path, heading_stack),
                            page_no=None,
                            section_title=self._format_heading_path(heading_stack),
                            section_level=current_level,
                            block_type="image",
                            source_order=source_order,
                            heading_path=self._heading_path(heading_stack),
                            image_path=str(image_path),
                        )
                    )
            if not content:
                flush_buffer()
                flush_list()
                continue
            style_name = paragraph.style.name.lower() if paragraph.style and paragraph.style.name else ""
            if style_name.startswith("heading"):
                flush_buffer()
                flush_list()
                current_level = self._extract_heading_level(style_name)
                self._update_heading_stack(heading_stack, current_level, content)
                source_order += 1
                sections.append(
                    ParsedSection(
                        text=content,
                        page_no=None,
                        section_title=self._format_heading_path(heading_stack),
                        section_level=current_level,
                        block_type="heading",
                        source_order=source_order,
                        heading_path=self._heading_path(heading_stack),
                    )
                )
                continue
            if self._looks_like_heading(content):
                flush_buffer()
                flush_list()
                current_level = self._infer_heading_level(content)
                self._update_heading_stack(heading_stack, current_level, content)
                source_order += 1
                sections.append(
                    ParsedSection(
                        text=content,
                        page_no=None,
                        section_title=self._format_heading_path(heading_stack),
                        section_level=current_level,
                        block_type="heading",
                        source_order=source_order,
                        heading_path=self._heading_path(heading_stack),
                    )
                )
                continue
            if self._looks_like_list_style(style_name) or self._looks_like_list_line(content):
                flush_buffer()
                list_buffer.append(content)
                continue
            flush_list()
            buffer.append(content)

        flush_buffer()
        flush_list()
        return sections

    def _parse_markdown(self, file_path: Path) -> list[ParsedSection]:
        raw_text = file_path.read_text(encoding="utf-8")
        sections: list[ParsedSection] = []
        heading_stack: dict[int, str] = {}
        current_level = 1
        source_order = 0
        buffer: list[str] = []
        list_buffer: list[str] = []

        def flush_buffer() -> None:
            nonlocal source_order
            if not buffer:
                return
            text = clean_text("\n".join(buffer))
            buffer.clear()
            if not text:
                return
            source_order += 1
            sections.append(
                ParsedSection(
                    text=text,
                    page_no=None,
                    section_title=self._format_heading_path(heading_stack),
                    section_level=current_level,
                    block_type="paragraph",
                    source_order=source_order,
                    heading_path=self._heading_path(heading_stack),
                )
            )

        def flush_list() -> None:
            nonlocal source_order
            if not list_buffer:
                return
            text = clean_text("\n".join(list_buffer))
            list_buffer.clear()
            if not text:
                return
            source_order += 1
            sections.append(
                ParsedSection(
                    text=text,
                    page_no=None,
                    section_title=self._format_heading_path(heading_stack),
                    section_level=current_level,
                    block_type="list",
                    source_order=source_order,
                    heading_path=self._heading_path(heading_stack),
                )
            )

        for line in raw_text.splitlines():
            stripped = line.strip()
            if not stripped:
                flush_buffer()
                flush_list()
                continue
            if stripped.startswith("#"):
                flush_buffer()
                flush_list()
                current_level = max(1, len(stripped) - len(stripped.lstrip("#")))
                current_heading = stripped.lstrip("#").strip()
                if current_heading:
                    self._update_heading_stack(heading_stack, current_level, current_heading)
                source_order += 1
                sections.append(
                    ParsedSection(
                        text=current_heading or "",
                        page_no=None,
                        section_title=self._format_heading_path(heading_stack),
                        section_level=current_level,
                        block_type="heading",
                        source_order=source_order,
                        heading_path=self._heading_path(heading_stack),
                    )
                )
                continue
            if self._looks_like_list_line(stripped):
                flush_buffer()
                list_buffer.append(stripped)
                continue
            flush_list()
            buffer.append(stripped)

        flush_buffer()
        flush_list()
        return sections

    def _parse_txt(self, file_path: Path) -> list[ParsedSection]:
        text = clean_text(file_path.read_text(encoding="utf-8"))
        sections: list[ParsedSection] = []
        for index, segment in enumerate(text.split("\n\n"), start=1):
            normalized = segment.strip()
            if not normalized:
                continue
            sections.append(
                ParsedSection(
                    text=normalized,
                    page_no=None,
                    section_title=None,
                    section_level=1,
                    block_type="paragraph",
                    source_order=index,
                    heading_path=(),
                )
            )
        return sections

    @staticmethod
    def _looks_like_heading(text: str) -> bool:
        if len(text) > 80 or "\n" in text:
            return False
        return bool(re.match(SECTION_PREFIX_PATTERN, text))

    @staticmethod
    def _infer_heading_level(text: str) -> int:
        match = re.match(r"^([0-9]+(?:\.[0-9]+){0,3})", text)
        if match:
            return match.group(1).count(".") + 1
        if re.match(rf"^\u7b2c[{CHINESE_NUMERALS}0-9]+\u7ae0", text):
            return 1
        if re.match(rf"^\u7b2c[{CHINESE_NUMERALS}0-9]+\u8282", text):
            return 2
        if re.match(rf"^[{CHINESE_NUMERALS}]+[\u3001\uff0e.]", text):
            return 1
        return 1

    @staticmethod
    def _extract_heading_level(style_name: str) -> int:
        match = re.search(r"(\d+)", style_name)
        return max(1, int(match.group(1))) if match else 1

    @staticmethod
    def _looks_like_list_style(style_name: str) -> bool:
        return "list" in style_name or "bullet" in style_name

    @staticmethod
    def _looks_like_list_line(text: str) -> bool:
        return bool(re.match(LIST_LINE_PATTERN, text))

    @staticmethod
    def _extract_pdf_tables(file_path: Path) -> dict[int, list[str]]:
        tables_by_page: dict[int, list[str]] = {}
        with pdfplumber.open(file_path) as document:
            for page_no, page in enumerate(document.pages, start=1):
                table_texts = [
                    table_text
                    for table in page.extract_tables()
                    if (table_text := DocumentParser._table_to_markdown(table))
                ]
                if table_texts:
                    tables_by_page[page_no] = table_texts
        return tables_by_page

    @staticmethod
    def _iter_docx_blocks(document: DocxDocumentType):
        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, document)
            elif child.tag == qn("w:tbl"):
                yield Table(child, document)

    @staticmethod
    def _extract_docx_paragraph_images(
        paragraph: Paragraph,
        file_path: Path,
        document_id: str | None,
    ) -> list[Path]:
        image_paths: list[Path] = []
        for index, drawing in enumerate(paragraph._element.xpath(".//a:blip"), start=1):
            embed_id = drawing.get(qn("r:embed"))
            if not embed_id:
                continue
            part = paragraph.part.related_parts.get(embed_id)
            if part is None:
                continue
            image_paths.append(
                DocumentParser._save_image_bytes(
                    data=part.blob,
                    extension=Path(part.partname).suffix or ".png",
                    file_path=file_path,
                    document_id=document_id,
                    name_hint=f"docx-image-{len(image_paths) + index}",
                )
            )
        return image_paths

    @staticmethod
    def _extract_pdf_page_images(
        document: fitz.Document,
        page: fitz.Page,
        page_no: int,
        file_path: Path,
        document_id: str | None,
    ) -> list[Path]:
        image_paths: list[Path] = []
        seen_xrefs: set[int] = set()
        for image_index, image in enumerate(page.get_images(full=True), start=1):
            xref = int(image[0])
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            extracted = document.extract_image(xref)
            data = extracted.get("image")
            if not data:
                continue
            extension = f".{extracted.get('ext') or 'png'}"
            image_paths.append(
                DocumentParser._save_image_bytes(
                    data=data,
                    extension=extension,
                    file_path=file_path,
                    document_id=document_id,
                    name_hint=f"pdf-page-{page_no}-image-{image_index}",
                )
            )
        return image_paths

    @staticmethod
    def _save_image_bytes(
        *,
        data: bytes,
        extension: str,
        file_path: Path,
        document_id: str | None,
        name_hint: str,
    ) -> Path:
        settings = get_settings()
        image_root = settings.image_storage_path / (document_id or file_path.stem)
        image_root.mkdir(parents=True, exist_ok=True)
        safe_extension = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        target = image_root / f"{name_hint}{safe_extension}"
        suffix = 1
        while target.exists():
            target = image_root / f"{name_hint}-{suffix}{safe_extension}"
            suffix += 1
        target.write_bytes(data)
        return target

    @staticmethod
    def _image_section_text(image_path: Path, heading_stack: dict[int, str]) -> str:
        heading_path = DocumentParser._format_heading_path(heading_stack)
        lines = ["图片块"]
        if heading_path:
            lines.append(f"所属标题：{heading_path}")
        lines.append(f"图片文件：{image_path.name}")
        return "\n".join(lines)

    @staticmethod
    def _table_to_markdown(rows: list[list[str | None]]) -> str:
        cleaned_rows: list[list[str]] = []
        for row in rows:
            cleaned = [DocumentParser._clean_table_cell(cell).replace("|", "\\|") for cell in row]
            if any(cell for cell in cleaned):
                cleaned_rows.append(cleaned)
        if not cleaned_rows:
            return ""

        width = max(len(row) for row in cleaned_rows)
        normalized_rows = [row + [""] * (width - len(row)) for row in cleaned_rows]
        header = normalized_rows[0]
        separator = ["---"] * width
        body = normalized_rows[1:]
        markdown_rows = [header, separator, *body]
        return "\n".join(f"| {' | '.join(row)} |" for row in markdown_rows)

    @staticmethod
    def _clean_table_cell(cell: str | None) -> str:
        text = (cell or "").replace("\u00a0", " ")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _update_heading_stack(heading_stack: dict[int, str], level: int, title: str) -> None:
        for existing_level in list(heading_stack):
            if existing_level >= level:
                del heading_stack[existing_level]
        heading_stack[level] = title

    @staticmethod
    def _heading_path(heading_stack: dict[int, str]) -> tuple[str, ...]:
        return tuple(title for _, title in sorted(heading_stack.items()))

    @staticmethod
    def _format_heading_path(heading_stack: dict[int, str]) -> str | None:
        path = DocumentParser._heading_path(heading_stack)
        return " > ".join(path) if path else None
