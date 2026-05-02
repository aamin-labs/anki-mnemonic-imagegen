import anthropic

from .base import EnhancementWorkflow, WorkflowError

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = (
    "You are a concise historical summariser. "
    "Given an Anki flashcard about a British Prime Minister, "
    "write exactly one sentence — no more — capturing the single most significant "
    "highlight or legacy of their tenure. "
    "Be specific and factual. Do not include their name at the start of the sentence. "
    "Output only the sentence, nothing else."
)


class HighlightWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "highlight"
    DESCRIPTION = "One-sentence highlight per card"
    INPUT_FIELDS = ["PM", "Other"]
    OUTPUT_FIELDS = ["Highlight"]
    REQUIRED_ENV_KEYS = ["ANTHROPIC_API_KEY"]
    DEFAULT_ADD_TAG = ""
    DEFAULT_REMOVE_TAG = ""

    def __init__(self, config: dict):
        super().__init__(config)
        self._client = anthropic.Anthropic(api_key=config["anthropic_api_key"])

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        parts = []
        for field in self._input_fields:
            val = fields.get(field, "").strip()
            if val:
                parts.append(f"{field}: {val}")

        if not parts:
            raise WorkflowError("All input fields are empty")

        user_msg = "\n".join(parts)

        try:
            msg = self._client.messages.create(
                model=_MODEL,
                max_tokens=256,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
        except anthropic.APIError as e:
            raise WorkflowError(f"Claude API error: {e}")

        highlight = msg.content[0].text.strip()
        return {"Highlight": highlight}
