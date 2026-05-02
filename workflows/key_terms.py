import json
import re

import anthropic

from .base import EnhancementWorkflow, WorkflowError

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = """\
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

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_BOLD_RE = re.compile(r"</?b>", re.IGNORECASE)
_UNDERLINE_RE = re.compile(r"</?u>", re.IGNORECASE)


def _strip_emphasis_tags(value: str) -> str:
    value = _BOLD_RE.sub("", value)
    return _UNDERLINE_RE.sub("", value)


def _validate_output(output: dict[str, str]) -> list[str]:
    errors = []
    question_bolds = len(re.findall(r"<b>", output["Question"], flags=re.IGNORECASE))
    question_underlines = len(re.findall(r"<u>", output["Question"], flags=re.IGNORECASE))
    answer_bolds = len(re.findall(r"<b>", output["Answer"], flags=re.IGNORECASE))
    answer_underlines = len(re.findall(r"<u>", output["Answer"], flags=re.IGNORECASE))

    if question_bolds > 2:
        errors.append(f"Question has {question_bolds} bold spans; use at most 2")
    if question_underlines:
        errors.append("Question must not contain underline tags")
    if answer_bolds > 2:
        errors.append(f"Answer has {answer_bolds} bold spans; use at most 2")
    if answer_underlines > 2:
        errors.append(f"Answer has {answer_underlines} underline spans; use at most 2")
    return errors


class KeyTermsWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "key_terms"
    INPUT_FIELDS = ["Question", "Answer"]
    OUTPUT_FIELDS = ["Question", "Answer"]
    REQUIRED_ENV_KEYS = ["ANTHROPIC_API_KEY"]
    DEFAULT_ADD_TAG = "key-terms-formatted"
    DEFAULT_REMOVE_TAG = ""

    def __init__(self, config: dict):
        super().__init__(config)
        self._client = anthropic.Anthropic(api_key=config["anthropic_api_key"])

    def should_skip(self, note_id: str, fields: dict[str, str]) -> tuple[bool, str]:
        return False, ""

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
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
                    system=_SYSTEM,
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
                        last_errors = _validate_output(output)
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
