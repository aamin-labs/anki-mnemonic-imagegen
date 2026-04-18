from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = ROOT / "addons" / "copy_note_fields_markdown"
MANIFEST_PATH = ADDON_DIR / "manifest.json"
PACKAGE_FILES = ["__init__.py", "export.py", "manifest.json", "README.md"]


def build_addon(output_dir: Path) -> Path:
    manifest = json.loads(MANIFEST_PATH.read_text())
    version = manifest.get("human_version", "dev").lstrip("v")
    package_name = manifest["package"]
    archive_path = output_dir / f"{package_name}-{version}.ankiaddon"

    output_dir.mkdir(parents=True, exist_ok=True)

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as zf:
        for filename in PACKAGE_FILES:
            path = ADDON_DIR / filename
            if not path.exists():
                raise FileNotFoundError(f"Missing add-on file: {path}")
            zf.write(path, arcname=filename)

    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Anki add-on package.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "dist"),
        help="Directory to write the packaged add-on into.",
    )
    args = parser.parse_args()

    archive_path = build_addon(Path(args.output_dir))
    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
