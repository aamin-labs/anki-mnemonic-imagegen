# anki-enrich

A CLI pipeline that bulk-enhances Anki cards with AI-generated content. Supports multiple workflows — mnemonic image generation, field formatting, one-line highlights — and is designed to be extensible.

## Installation

```bash
git clone https://github.com/aamin-labs/anki-enrich
cd anki-enrich
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys
```

## Configuration

Copy `.env.example` to `.env` and fill in:

| Key | Required for | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | all workflows | API key from [console.anthropic.com](https://console.anthropic.com) |
| `GEMINI_API_KEY` | `mnemonic_image` | API key from [aistudio.google.com](https://aistudio.google.com) |
| `ANKI_PROFILE` | optional | Anki profile name (auto-detects first profile if unset) |

To find your Anki profile name: `ls ~/Library/Application\ Support/Anki2/`

## Usage

**Make sure Anki is closed before running**, then sync to AnkiWeb first to avoid losing review progress.

```bash
# See what fields a deck has before choosing input fields
.venv/bin/python3 run_pipeline.py --query 'deck:"My Deck"' --workflow format_fields --list-fields

# Dry run — no API calls, shows which notes would be processed
.venv/bin/python3 run_pipeline.py --query 'deck:"My Deck"' --workflow format_fields --dry-run

# Test on a few cards first
.venv/bin/python3 run_pipeline.py --query 'deck:"My Deck"' --workflow format_fields --limit 3

# Run on all new/learning cards in a deck
.venv/bin/python3 run_pipeline.py --query 'deck:"My Deck" (is:new OR is:learn)' --workflow format_fields

# Resume a crashed run — retries only failed notes
.venv/bin/python3 run_pipeline.py --resume state/format_fields_20260301_120000.json
```

After running, open Anki and sync to AnkiWeb (Cmd+Y) to push the changes to your other devices.

## One-off utility scripts

### `scripts/fill_people_images.py`

Fills an image field with small Wikipedia/Wikimedia thumbnails for people cards, and writes the article URL to a source field.

**Dry run first:**
```bash
/Users/aamin/Library/Application\ Support/AnkiProgramFiles/.venv/bin/python3.13 scripts/fill_people_images.py \
  --query 'deck:"1. 🎖️ Active::1.40 📜 History" flag:3' \
  --dry-run
```

**Real run with title overrides** (useful when the note says `Victoria` but Wikipedia's page is `Queen Victoria`):
```bash
/Users/aamin/Library/Application\ Support/AnkiProgramFiles/.venv/bin/python3.13 scripts/fill_people_images.py \
  --query 'deck:"1. 🎖️ Active::1.40 📜 History" flag:3' \
  --title-map data/british_monarch_titles.json
```

**Useful flags:**
- `--name-field Question` — field containing the person's name
- `--image-field Image` — field to populate with `<img src="...">`
- `--source-field Source` — field to populate with the Wikipedia URL
- `--thumb-size 220` — request a smaller thumbnail
- `--overwrite` — replace existing images instead of skipping them

The script auto-backs up `collection.anki2` before writing and refuses to run while Anki is open.

### CLI flags

| Flag | Description |
|---|---|
| `--query QUERY` | Anki search query (standard Anki search syntax) |
| `--workflow NAME` | Workflow to run (see Workflows below) |
| `--resume FILE` | Resume a previous run; retries only failed notes |
| `--verify FILE` | Re-read processed notes from Anki and confirm fields are non-empty |
| `--dry-run` | No API calls or writes; useful for previewing matches |
| `--limit N` | Process at most N notes; useful for testing |
| `--list-fields` | Print available fields for matched notes and exit |
| `--input-fields A,B` | Override workflow's default input fields (comma-separated) |
| `--no-overwrite` | Skip notes where output fields are already filled |
| `--write-batch-size N` | Write to Anki every N notes (default: 10) |
| `--yes-add-fields` | Auto-confirm adding missing output fields to the notetype |

## Workflows

### `format_fields`

Applies minimal HTML formatting to existing card fields using Claude.

**Formatting rules applied:**
- `<b>bold</b>` — key terms, concept names, proper nouns
- `<br>` — line breaks between logically distinct parts of a multi-part answer
- `<ul><li>` — bullet lists for 3+ enumerable items only

**Default fields:** `Answer`, `Explanation` (in-place update — same fields read and written back)

**Tags:** Adds `fields-formatted` to every processed note automatically.

**Skip logic:** Skips suspended cards always. Skips notes already tagged `fields-formatted`. Skips fields that already contain HTML tags (secondary guard for cards formatted outside the pipeline).

**First run:**
```bash
.venv/bin/python3 run_pipeline.py \
  --query 'deck:"My Deck" -is:suspended -note:"Image Occlusion Enhanced"' \
  --workflow format_fields
```

**Subsequent runs** (only unformatted cards):
```bash
.venv/bin/python3 run_pipeline.py \
  --query 'deck:"My Deck" -tag:fields-formatted -is:suspended -note:"Image Occlusion Enhanced"' \
  --workflow format_fields
```

---

### `highlight`

Generates a one-sentence summary of the most significant highlight or legacy for British Prime Minister cards.

**Default fields:** Input: `PM`, `Other` → Output: `Highlight`

```bash
.venv/bin/python3 run_pipeline.py \
  --query 'deck:"1. 🎖️ E and R::1.42 🇬🇧 British Prime Ministers"' \
  --workflow highlight
```

---

### `mnemonic_image`

Generates a visual mnemonic image for a card. Uses Claude to design the mnemonic and Google Imagen to render it.

**Default fields:** Input: `Front`, `Back` → Output: `Mnemonic` (img tag), `Encoding` (one-sentence description)

```bash
.venv/bin/python3 run_pipeline.py \
  --query 'tag:need-image' \
  --workflow mnemonic_image
```

## How it works

1. Reads matching notes from your Anki collection via Anki's own Python runtime
2. For each note, calls the workflow's `process_note()` to generate output
3. State is saved after each note — interrupted runs can be resumed with `--resume`
4. Writes output fields back to Anki in batches

## Architecture

Two Python environments are kept strictly separate:

- **Project venv** — handles all API calls and orchestration
- **Anki's bundled Python** (`AnkiProgramFiles/.venv/bin/python3.13`) — the only process that touches `collection.anki2`

This separation avoids SQLite version mismatches that would corrupt the Anki database.

## Creating Custom Workflows

1. Create `workflows/my_workflow.py` subclassing `EnhancementWorkflow`:

```python
from .base import EnhancementWorkflow, WorkflowError

class MyWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "my_workflow"
    INPUT_FIELDS = ["Front", "Back"]   # fields to read from Anki
    OUTPUT_FIELDS = ["MyField"]        # fields to write back
    REQUIRED_ENV_KEYS = ["ANTHROPIC_API_KEY"]

    def __init__(self, config: dict):
        super().__init__(config)

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        # return {field_name: value} to write back
        return {"MyField": "generated content"}
```

2. Register it in `workflows/__init__.py`:

```python
from .my_workflow import MyWorkflow

WORKFLOWS = {
    ...
    "my_workflow": MyWorkflow,
}
```

3. Run it: `.venv/bin/python3 run_pipeline.py --query '...' --workflow my_workflow`

**Notes:**
- `should_skip()` is inherited and skips notes where any output field is already filled. Override for custom logic.
- Fields prefixed with `__` (e.g. `__suspended__`, `__image_prompt__`) are metadata injected by the pipeline and never written back to Anki.
- Raise `WorkflowError` for recoverable errors — the note is marked failed and the run continues.
- Set `DEFAULT_ADD_TAG` / `DEFAULT_REMOVE_TAG` on your workflow class to automatically apply tags on every successful write. The CLI `--add-tag` / `--remove-tag` flags override these; pass `''` to disable the default.

## Troubleshooting

**`ModuleNotFoundError: No module named 'dotenv'`**
Use `.venv/bin/python3` instead of `python3` to run the pipeline.

**`ERROR: No Anki profiles found`**
Run `ls ~/Library/Application\ Support/Anki2/` to see your profile names, then set `ANKI_PROFILE=<name>` in `.env`.

**`ERROR: Anki is running`**
Close Anki before running the pipeline. Anki holds a write lock on the collection file.

**`Invalid search: is: was given an invalid argument 'learning'`**
Use `is:learn` not `is:learning` in your Anki query.

**Notes processed but changes not showing in Anki**
Make sure you sync after the run (Cmd+Y). Also verify with `--verify state/<file>.json`.

## Requirements

- Python 3.11+
- Anki 25.x installed (uses its bundled Python for database access)

## License

MIT
