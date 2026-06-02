import re


HEADER_FOOTER_PATTERNS = [
    r"^\s*\d+\s*$",
    r"^\s*第\s*\d+\s*页\s*$",
]


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]

    cleaned_lines: list[str] = []
    previous = None
    for line in lines:
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        if any(re.match(pattern, line) for pattern in HEADER_FOOTER_PATTERNS):
            continue
        normalized = re.sub(r"\s+", " ", line)
        if normalized != previous:
            cleaned_lines.append(normalized)
            previous = normalized

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()
