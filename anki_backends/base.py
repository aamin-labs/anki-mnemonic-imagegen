from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AnkiBackend(Protocol):
    def list_decks(self) -> list[str]:
        ...

    def read_notes(self, query: str, fields: list[str]) -> dict:
        ...

    def write_notes(
        self,
        state_path: str | Path,
        *,
        remove_tag: str = "",
        add_tag: str = "",
    ) -> str:
        ...

    def add_field(self, notetype_id: int, field_name: str) -> str:
        ...
