from abc import ABC, abstractmethod


class WorkflowError(Exception):
    """Marks a note as failed without aborting the run."""


class EnhancementWorkflow(ABC):
    WORKFLOW_NAME: str
    INPUT_FIELDS: list[str]
    OUTPUT_FIELDS: list[str]

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        """Process one note. Returns {field_name: new_value} to write back."""

    def should_skip(self, note_id: str, fields: dict[str, str]) -> tuple[bool, str]:
        """Skip if any OUTPUT_FIELD is already non-empty."""
        for field in self.OUTPUT_FIELDS:
            if fields.get(field, "").strip():
                return True, f"{field} already filled"
        return False, ""

    def teardown(self) -> None:
        pass
