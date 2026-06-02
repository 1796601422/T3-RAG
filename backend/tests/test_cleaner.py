from app.services.text_cleaner import clean_text


def test_clean_text_removes_duplicate_blank_lines() -> None:
    raw = "Title\n\n\nBody first line\n\n\n2\n"
    cleaned = clean_text(raw)
    assert "\n\n\n" not in cleaned
    assert "2" not in cleaned
