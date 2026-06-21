#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANKI_PYTHON="/Users/aamin/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13"

cd "$REPO_DIR"
"$ANKI_PYTHON" scripts/fill_wiki_context_images.py --notify "$@"
