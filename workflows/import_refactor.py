import json
import re
from pathlib import Path

import anthropic

from .base import EnhancementWorkflow, WorkflowError

_MODEL = "claude-haiku-4-5-20251001"
_SKILL_PATH = Path.home() / ".agents" / "skills" / "anki-refactor" / "SKILL.md"
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_REQUIRED_KEYS = ["Question", "Answer", "Explanation", "Reverse Answer"]

_SYSTEM = """\
You refactor Anki card fields by following the provided anki-refactor skill document.
Return ONLY one JSON object with exactly these string keys:
"Question", "Answer", "Explanation", "Reverse Answer".
Do not include markdown, commentary, or code fences.
Preserve useful content. Do not invent facts. If a field should not change, return its original value.
"""


def _load_skill_rules() -> str:
    if not _SKILL_PATH.exists():
        raise RuntimeError(f"Anki refactor skill not found: {_SKILL_PATH}")
    return _SKILL_PATH.read_text()


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
        if not clean["Answer"]:
            raise WorkflowError("Refactor output has empty Answer")
        return clean
