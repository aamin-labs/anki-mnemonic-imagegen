from anki.utils import strip_html_media


def build_markdown_from_note(note) -> str:
    blocks: list[str] = []

    for field_name, raw_value in note.items():
        cleaned_value = strip_html_media(raw_value).strip()
        if not cleaned_value:
            continue
        blocks.append(f"## {field_name}\n\n{cleaned_value}")

    if not blocks:
        return ""

    return "\n\n".join(blocks) + "\n"
