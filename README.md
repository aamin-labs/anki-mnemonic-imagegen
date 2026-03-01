# anki-mnemonic-imagegen

A CLI pipeline that bulk-enhances Anki cards with AI-generated content. Currently supports generating visual mnemonic images via an AI text model (prompt design) and an AI image model.

Designed to be extensible — adding a new workflow is a single file plus a registry entry.

## Installation

```bash
git clone https://github.com/aamin-labs/anki-mnemonic-imagegen
cd anki-enrich
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys
```

## Configuration

Copy `.env.example` to `.env` and fill in:

| Key | Required | Description |
|---|---|---|
| `MINIMAX_API_KEY` | Yes | API key from [minimax.io](https://www.minimax.io) |
| `ANKI_PROFILE` | No | Anki profile name (auto-detects the first profile if unset) |

To find your Anki profile name: `ls ~/Library/Application\ Support/Anki2/`

## Usage

**Make sure Anki is closed before running**, then sync to AnkiWeb first to avoid losing review progress.

```bash
# Dry run — no API calls, shows which notes would be processed
python3 run_pipeline.py --query 'tag:need-image' --workflow mnemonic_image --dry-run

# Test on a single card before committing to a full run
python3 run_pipeline.py --query 'deck:"My Deck"' --workflow mnemonic_image --limit 1

# Run on a tag (uses Front/Back fields by default)
python3 run_pipeline.py --query 'tag:need-image' --workflow mnemonic_image

# Use custom input fields for a different deck
python3 run_pipeline.py --query 'deck:"My Deck"' --workflow mnemonic_image --input-fields Name,Highlight

# Resume a crashed run — retries only failed notes
python3 run_pipeline.py --resume state/mnemonic_image_20260301_120000.json
```

### CLI flags

| Flag | Description |
|---|---|
| `--query QUERY` | Anki search query (standard Anki search syntax) |
| `--resume FILE` | Resume a previous run; retries only failed notes |
| `--workflow NAME` | Workflow to run (default: `mnemonic_image`) |
| `--dry-run` | No API calls or writes; useful for previewing matches |
| `--limit N` | Process at most N notes; useful for testing |
| `--input-fields A,B` | Override default input fields (comma-separated) |
| `--write-batch-size N` | Write to Anki every N notes (default: 10) |

After running, open Anki and sync to AnkiWeb to push the changes to your other devices.

## How it works

1. Reads matching notes from your Anki collection via Anki's own Python runtime
2. Sends the card's question/answer to a text model to design a visual mnemonic and image prompt
3. Passes the image prompt to an image model to generate a PNG
4. Saves the image to Anki's media folder and writes the `<img>` tag back to the note
5. State is saved after each note — interrupted runs can be resumed with `--resume`

## Architecture

Two Python environments are kept strictly separate:

- **Project venv** — handles all API calls
- **Anki's bundled Python** (`AnkiProgramFiles/.venv/bin/python3.13`) — the only process that touches `collection.anki2`

This separation avoids SQLite version mismatches that corrupt the Anki database.

## Troubleshooting

**`ERROR: MINIMAX_API_KEY not set`**
Copy `.env.example` to `.env` and add your API key from [minimax.io](https://www.minimax.io).

**`ERROR: No Anki profiles found`**
Run `ls ~/Library/Application\ Support/Anki2/` to see your profile names, then set `ANKI_PROFILE=<name>` in `.env`.

**`ERROR: Collection not found`**
Your `ANKI_PROFILE` value doesn't match a directory in `~/Library/Application Support/Anki2/`. Check the spelling.

**`ERROR: Anki is running`**
Close Anki before running the pipeline. Anki holds a write lock on the collection file.

**`API key is invalid`**
Check that `MINIMAX_API_KEY` in `.env` is correct. Generate a new key at [minimax.io](https://www.minimax.io) if needed.

**`Could not parse image prompt from response`**
The text model didn't follow the expected output format. This is rare; re-running with `--resume` will retry the failed note.

**Notes processed but images not showing in Anki**
Make sure you sync after the run (Cmd+Y). Also check that the `Mnemonic` field exists on your notetype and the card template references it with `{{Mnemonic}}`.

## Creating Custom Workflows

1. Create `workflows/my_workflow.py` subclassing `EnhancementWorkflow`:

```python
from .base import EnhancementWorkflow, WorkflowError

class MyWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "my_workflow"
    INPUT_FIELDS = ["Front", "Back"]   # fields to read from Anki
    OUTPUT_FIELDS = ["MyField"]        # fields to write back

    def __init__(self, config: dict):
        super().__init__(config)
        # initialize API clients, load prompts, etc.

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        # return {field_name: value} to write back
        return {"MyField": "generated content"}
```

2. Register it in `run_pipeline.py`:

```python
from workflows.my_workflow import MyWorkflow

WORKFLOWS = {
    "mnemonic_image": MnemonicImageWorkflow,
    "my_workflow": MyWorkflow,
}
```

3. Run it: `python3 run_pipeline.py --query '...' --workflow my_workflow`

`should_skip()` is inherited and skips notes where any output field is already filled. Override it for custom skip logic.

## Requirements

- Python 3.11+
- Anki 25.x installed (uses its bundled Python for database access)

## License

MIT
>>>>>>> e44d68e (Initial commit — anki-enrich pipeline)
