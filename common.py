"""Shared path constants used by both run_pipeline.py and tui.py."""
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
ANKI_IO_DIR = PROJECT_DIR / "anki_io"
_ANKI_PYTHON_DEFAULT = str(
    Path.home()
    / "Library"
    / "Application Support"
    / "AnkiProgramFiles"
    / ".venv"
    / "bin"
    / "python3.13"
)
