import json
import re

import anthropic

from .base import EnhancementWorkflow, WorkflowError

_MODEL = "claude-haiku-4-5-20251001"

_HTML_TAG_RE = re.compile(r"<(b|br|ul|li|u|/b|/ul|/li|/u)\b", re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_BOLD_RE = re.compile(r"</?b>", re.IGNORECASE)
_UNDERLINE_RE = re.compile(r"</?u>", re.IGNORECASE)

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

_QUESTION_ANSWER_SYSTEM = """\
You format Anki flashcard Question and Answer fields for visual scanning.

Return ONLY a JSON object with exactly these string keys: "Question", "Answer".

Formatting goal:
- In the Question, bold the 1 or 2 key term(s) the learner should focus on.
- In the Answer, bold the 1 or 2 term(s) that must be present for the answer to count as correct.
- In the Answer only, underline 1 or 2 precision-critical terms that show depth, specificity, or conceptual clarity.

Rules:
- Preserve the original wording exactly. Do not add, remove, rewrite, explain, or reorder content.
- Add only <b>, </b>, <u>, and </u> tags.
- Preserve any existing HTML tags already present in the fields.
- Do not bold or underline whole sentences unless the field is only a sentence fragment and no shorter term works.
- Prefer one term over two when one term carries the concept.
- Avoid overlapping tags unless the same term is both must-have and precision-critical.
- If a field is empty, return it as an empty string.\
"""


def _strip_emphasis_tags(value: str) -> str:
    value = _BOLD_RE.sub("", value)
    return _UNDERLINE_RE.sub("", value)


def _count_tag(value: str, tag: str) -> int:
    return len(re.findall(rf"<{tag}>", value, flags=re.IGNORECASE))


def _validate_question_answer_output(output: dict[str, str]) -> list[str]:
    errors = []
    question_bolds = _count_tag(output["Question"], "b")
    question_underlines = _count_tag(output["Question"], "u")
    answer_bolds = _count_tag(output["Answer"], "b")
    answer_underlines = _count_tag(output["Answer"], "u")

    if question_bolds > 2:
        errors.append(f"Question has {question_bolds} bold spans; use at most 2")
    if question_underlines:
        errors.append("Question must not contain underline tags")
    if answer_bolds > 2:
        errors.append(f"Answer has {answer_bolds} bold spans; use at most 2")
    if answer_underlines > 2:
        errors.append(f"Answer has {answer_underlines} underline spans; use at most 2")
    return errors


class FormatFieldsWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "format_fields"
    DESCRIPTION = "Minimal HTML formatting for existing fields"
    DEFAULT_FILTER = "-tag:fields-formatted -is:suspended"
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
        if fields.get("__suspended__"):
            return True, "card is suspended"
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

    def _process_question_answer(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        question = _strip_emphasis_tags(fields.get("Question", ""))
        answer = _strip_emphasis_tags(fields.get("Answer", ""))

        if not question.strip() and not answer.strip():
            raise WorkflowError("Question and Answer are empty")

        payload = json.dumps(
            {"Question": question, "Answer": answer},
            ensure_ascii=False,
        )
        last_errors = []
        messages = [{"role": "user", "content": payload}]
        for _ in range(2):
            try:
                msg = self._client.messages.create(
                    model=_MODEL,
                    max_tokens=2048,
                    system=_QUESTION_ANSWER_SYSTEM,
                    messages=messages,
                )
            except anthropic.APIError as e:
                raise WorkflowError(f"Claude API error: {e}")

            text = msg.content[0].text.strip()
            match = _JSON_OBJECT_RE.search(text)
            if not match:
                last_errors = ["Formatter returned non-JSON output"]
            else:
                try:
                    output = json.loads(match.group(0))
                except json.JSONDecodeError as e:
                    last_errors = [f"Formatter returned invalid JSON: {e}"]
                else:
                    missing = [
                        field
                        for field in self._output_fields
                        if field not in output or not isinstance(output[field], str)
                    ]
                    if missing:
                        last_errors = [f"Formatter omitted string field(s): {', '.join(missing)}"]
                    else:
                        output = {field: output[field].strip() for field in self._output_fields}
                        last_errors = _validate_question_answer_output(output)
                        if not last_errors:
                            return output

            messages.extend(
                [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": "Fix only these validation errors and return the JSON again: "
                        + "; ".join(last_errors),
                    },
                ]
            )

        raise WorkflowError("; ".join(last_errors))


class FormatQuestionAnswerWorkflow(FormatFieldsWorkflow):
    WORKFLOW_NAME = "format_qa_fields"
    DESCRIPTION = "Visual scanning markup for Question and Answer fields"
    DEFAULT_FILTER = "-tag:fields-formatted -is:suspended"
    INPUT_FIELDS = ["Question", "Answer"]
    OUTPUT_FIELDS = ["Question", "Answer"]

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        return self._process_question_answer(note_id, fields)
