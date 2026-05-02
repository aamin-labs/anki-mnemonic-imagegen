"""Direct Anki collection backend using Anki's bundled Python."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from common import ANKI_IO_DIR


class DirectAnkiBackend:
    """Run small Anki IO scripts against collection.anki2 via Anki's Python."""

    def __init__(self, anki_python: str, collection_path: str | Path):
        self.anki_python = anki_python
        self.collection_path = Path(collection_path)

    def list_decks(self) -> list[str]:
        raw = self._run_script("list_decks.py", [])
        return json.loads(raw)["decks"]

    def read_notes(self, query: str, fields: list[str]) -> dict:
        raw = self._run_script(
            "read_notes.py",
            [
                "--query",
                query,
                "--fields",
                ",".join(fields),
            ],
        )
        return json.loads(raw)

    def write_notes(
        self,
        state_path: str | Path,
        *,
        remove_tag: str = "",
        add_tag: str = "",
    ) -> str:
        args = ["--state", str(state_path)]
        if remove_tag:
            args += ["--remove-tag", remove_tag]
        if add_tag:
            args += ["--add-tag", add_tag]
        return self._run_script("write_notes.py", args)

    def add_field(self, notetype_id: int, field_name: str) -> str:
        return self._run_script(
            "add_field.py",
            [
                "--notetype-id",
                str(notetype_id),
                "--field-name",
                field_name,
            ],
        )

    def _run_script(self, script_name: str, extra_args: list[str]) -> str:
        cmd = [
            self.anki_python,
            str(ANKI_IO_DIR / script_name),
            "--col",
            str(self.collection_path),
            *extra_args,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ERROR in {script_name}:\n{result.stderr}")
        return result.stdout
