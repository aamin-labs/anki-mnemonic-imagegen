import re

import anthropic

from .base import EnhancementWorkflow, WorkflowError

_MODEL = "claude-haiku-4-5-20251001"

_HTML_TAG_RE = re.compile(r"<(b|br|ul|li|/b|/ul|/li)\b", re.IGNORECASE)

_SYSTEM = """\
You are an HTML formatter for Anki flashcard fields. Apply minimal, semantic HTML to the given text using only these three rules:

1. <b>bold</b> — wrap key terms, concept names, proper nouns, and important phrases
2. <br> — insert a line break between logically distinct parts of a multi-part answer
3. <ul><li>…</li></ul> — use bullet lists ONLY when there are 3 or more clearly enumerable items

Rules:
- Return ONLY the formatted text, nothing else — no explanations, no markdown, no code fences
- Preserve all original wording exactly; do not add, remove, or reorder content
- Do not use any HTML tags other than <b>, </b>, <br>, <ul>, <li>, </li>, </ul>
- If the text needs no formatting, return it unchanged\
"""


class FormatFieldsWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "format_fields"
    INPUT_FIELDS = ["Answer", "Explanation"]
    OUTPUT_FIELDS = ["Answer", "Explanation"]
    REQUIRED_ENV_KEYS = ["ANTHROPIC_API_KEY"]
    DEFAULT_ADD_TAG = "fields-formatted"
    DEFAULT_REMOVE_TAG = ""

    def __init__(self, config: dict):
        super().__init__(config)
        self._client = anthropic.Anthropic(api_key=config["anthropic_api_key"])

    def should_skip(self, note_id: str, fields: dict[str, str]) -> tuple[bool, str]:
        """Skip if all non-empty output fields already have HTML tags."""
        skip, reason = super().should_skip(note_id, fields)
        if skip:
            return skip, reason
        tagged = []
        for field in self._output_fields:
            val = fields.get(field, "").strip()
            if val and _HTML_TAG_RE.search(val):
                tagged.append(field)
        non_empty = [f for f in self._output_fields if fields.get(f, "").strip()]
        if non_empty and len(tagged) == len(non_empty):
            return True, "fields already contain HTML formatting"
        return False, ""

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        output = {}
        for field in self._output_fields:
            val = fields.get(field, "").strip()
            if not val:
                continue
            if _HTML_TAG_RE.search(val):
                output[field] = val  # already formatted, pass through unchanged
                continue
            try:
                msg = self._client.messages.create(
                    model=_MODEL,
                    max_tokens=1024,
                    system=_SYSTEM,
                    messages=[{"role": "user", "content": val}],
                )
            except anthropic.APIError as e:
                raise WorkflowError(f"Claude API error on field '{field}': {e}")
            output[field] = msg.content[0].text.strip()

        if not output:
            raise WorkflowError("All input fields are empty")

        return output
