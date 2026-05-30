import json
import re
from pathlib import Path

import anthropic

from .base import EnhancementWorkflow, WorkflowError

_MODEL = "claude-haiku-4-5-20251001"
_SKILL_PATH = Path.home() / ".agents" / "skills" / "anki-refactor" / "SKILL.md"
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_REQUIRED_KEYS = ["Question", "Answer", "Explanation", "Reverse Answer"]
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_SYSTEM = """\
You refactor Anki card fields by following the provided anki-refactor skill document.
Return ONLY one JSON object with exactly these string keys:
"Question", "Answer", "Explanation", "Reverse Answer".
Do not include markdown, commentary, or code fences.
Preserve useful content. Do not invent facts. If a field should not change, return its original value.

Critical Reverse Answer rule:
- Reverse Answer is the answer to the reverse card, whose prompt is the original Answer.
- Therefore Reverse Answer must be answer-form wording for the original Question target.
- Do NOT copy or summarize the original Answer into Reverse Answer.
- Example: Question "What is the capital of France?" Answer "Paris" -> Reverse Answer "Capital of France".
- Example: Question "What is index-free adjacency?" Answer "Each node stores..." -> Reverse Answer "index-free adjacency".
"""


def _load_skill_rules() -> str:
    if not _SKILL_PATH.exists():
        raise RuntimeError(f"Anki refactor skill not found: {_SKILL_PATH}")
    return _SKILL_PATH.read_text()


def _plain_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", _HTML_TAG_RE.sub(" ", value)).strip()


def _normalize(value: str) -> str:
    return _plain_text(value).lower().strip(" .?!:;\"'")


def _sentence_case(value: str) -> str:
    if not value:
        return value
    return value[0].upper() + value[1:]


def _reverse_answer_target_from_question(question: str) -> str:
    """Best-effort answer-form target for common reverse-card questions."""
    q = _plain_text(question).rstrip(" ?")

    what_is = re.match(r"(?i)^what\s+(?:is|are|was|were)\s+(.+)$", q)
    if what_is:
        target = what_is.group(1).strip()
        article = re.match(r"(?i)^(?:the|a|an)\s+(.+)$", target)
        if article:
            return _sentence_case(article.group(1).strip())
        return target

    define = re.match(r"(?i)^define\s+(.+)$", q)
    if define:
        return define.group(1).strip()

    meaning = re.match(r"(?i)^what\s+does\s+(.+?)\s+mean$", q)
    if meaning:
        return f"Meaning of {meaning.group(1).strip()}"

    stands_for = re.match(r"(?i)^what\s+does\s+(.+?)\s+stand\s+for$", q)
    if stands_for:
        return f"Expansion of {stands_for.group(1).strip()}"

    return ""


def _finalize_reverse_answer(
    *,
    question: str,
    answer: str,
    existing_reverse: str,
    proposed_reverse: str,
) -> str:
    """Prevent the common failure: Reverse Answer copied from definition text."""
    proposed = proposed_reverse.strip()
    if not proposed:
        return proposed

    hint = _reverse_answer_target_from_question(question)
    if not hint:
        return proposed

    proposed_norm = _normalize(proposed)
    if proposed_norm in {_normalize(answer), _normalize(existing_reverse)}:
        return hint

    proposed_words = proposed_norm.split()
    hint_words = _normalize(hint).split()
    if len(proposed_words) > max(8, len(hint_words) + 6):
        return hint

    return proposed


class ImportRefactorWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "import_refactor"
    DESCRIPTION = "Refactor newly imported aBasic cards using the external anki-refactor skill"
    DEFAULT_FILTER = "tag:import-needs-refactor -is:suspended"
    INPUT_FIELDS = ["Question", "Answer", "Context", "Explanation", "Reverse Answer"]
    OUTPUT_FIELDS = ["Question", "Answer", "Explanation", "Reverse Answer"]
    REQUIRED_ENV_KEYS = ["ANTHROPIC_API_KEY"]
    DEFAULT_ADD_TAG = "import-refactored"
    DEFAULT_REMOVE_TAG = "import-needs-refactor"

    def __init__(self, config: dict):
        super().__init__(config)
        self._client = anthropic.Anthropic(api_key=config["anthropic_api_key"])
        self._skill_rules = _load_skill_rules()

    def should_skip(self, note_id: str, fields: dict[str, str]) -> tuple[bool, str]:
        if fields.get("__suspended__"):
            return True, "card is suspended"
        if not fields.get("Question", "").strip():
            return True, "Question is empty"
        if not fields.get("Answer", "").strip():
            return True, "Answer is empty"
        return False, ""

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        payload = {field: fields.get(field, "") for field in self.INPUT_FIELDS}
        messages = [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "skill_document": self._skill_rules,
                        "note": payload,
                        "reverse_answer_target_hint": _reverse_answer_target_from_question(
                            payload.get("Question", "")
                        ),
                    },
                    ensure_ascii=False,
                ),
            }
        ]

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
            raise WorkflowError("Refactor returned non-JSON output")

        try:
            output = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise WorkflowError(f"Refactor returned invalid JSON: {e}")

        missing = [key for key in _REQUIRED_KEYS if key not in output]
        if missing:
            raise WorkflowError(f"Refactor output missing keys: {', '.join(missing)}")

        clean = {key: str(output.get(key, "")).strip() for key in _REQUIRED_KEYS}
        clean["Reverse Answer"] = _finalize_reverse_answer(
            question=clean["Question"] or payload.get("Question", ""),
            answer=clean["Answer"],
            existing_reverse=payload.get("Reverse Answer", ""),
            proposed_reverse=clean["Reverse Answer"],
        )
        if not clean["Answer"]:
            raise WorkflowError("Refactor output has empty Answer")
        return clean
