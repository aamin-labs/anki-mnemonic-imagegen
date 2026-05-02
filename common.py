"""Shared Anki and project helpers."""
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import time

PROJECT_DIR = Path(__file__).parent
ANKI_IO_DIR = PROJECT_DIR / "anki_io"
ANKI2_ROOT = Path.home() / "Library" / "Application Support" / "Anki2"
_ANKI_PYTHON_DEFAULT = str(
    Path.home()
    / "Library"
    / "Application Support"
    / "AnkiProgramFiles"
    / ".venv"
    / "bin"
    / "python3.13"
)


@dataclass(frozen=True)
class AnkiPaths:
    profile_dir: Path
    collection: Path
    media_dir: Path


def resolve_anki_paths(profile: str | None = None, *, require_media: bool = False) -> AnkiPaths:
    """Resolve collection and media paths from an explicit profile or first local profile."""
    if not ANKI2_ROOT.exists():
        raise RuntimeError(
            f"Anki2 directory not found: {ANKI2_ROOT}\n"
            "Is Anki installed? Set ANKI_PROFILE= in .env for a custom location."
        )

    if profile:
        profile_dir = ANKI2_ROOT / profile
    else:
        candidates = [
            d for d in sorted(ANKI2_ROOT.iterdir())
            if d.is_dir() and d.name != "addons21"
        ]
        if not candidates:
            raise RuntimeError(f"No Anki profiles found in {ANKI2_ROOT}")
        profile_dir = candidates[0]

    paths = AnkiPaths(
        profile_dir=profile_dir,
        collection=profile_dir / "collection.anki2",
        media_dir=profile_dir / "collection.media",
    )
    if not paths.collection.exists():
        raise RuntimeError(f"Collection not found: {paths.collection}")
    if require_media and not paths.media_dir.exists():
        raise RuntimeError(f"Media directory not found: {paths.media_dir}")
    return paths


def ensure_anki_closed() -> None:
    result = subprocess.run(["pgrep", "-x", "Anki"], capture_output=True)
    if result.returncode == 0:
        raise RuntimeError("Anki is running. Close it first.")


def backup_collection(col_path: Path) -> Path:
    backup_path = Path(str(col_path) + f".backup_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(col_path, backup_path)
    return backup_path
