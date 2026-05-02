from abc import ABC, abstractmethod


class WorkflowError(Exception):
    """Marks a note as failed without aborting the run."""


class EnhancementWorkflow(ABC):
    WORKFLOW_NAME: str
    DESCRIPTION: str = ""
    DEFAULT_FILTER: str = ""
    INPUT_FIELDS: list[str]
    OUTPUT_FIELDS: list[str]
    REQUIRED_ENV_KEYS: list[str] = []
    WRITES_FIELDS: bool = True
    DEFAULT_ADD_TAG = ""
    DEFAULT_REMOVE_TAG = ""

    def __init__(self, config: dict):
        self.config = config
        self._input_fields: list[str] = config.get("input_fields", self.INPUT_FIELDS)
        self._output_fields: list[str] = config.get("output_fields", self.OUTPUT_FIELDS)

    @abstractmethod
    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        """Process one note. Returns {field_name: new_value} to write back."""

    def should_skip(self, note_id: str, fields: dict[str, str]) -> tuple[bool, str]:
        """Skip suspended cards, or if any output field is already non-empty."""
        if fields.get("__suspended__"):
            return True, "card is suspended"
        for field in self._output_fields:
            if fields.get(field, "").strip():
                return True, f"{field} already filled"
        return False, ""

    def teardown(self) -> None:
        pass
