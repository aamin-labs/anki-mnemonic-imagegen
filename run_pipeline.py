#!/usr/bin/env python3
"""Anki Card Enhancement Pipeline — main CLI entrypoint."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ── constants ─────────────────────────────────────────────────────────────────

ANKI_IO_DIR = Path(__file__).parent / "anki_io"
STATE_DIR = Path(__file__).parent / "state"

_ANKI2_ROOT = Path.home() / "Library" / "Application Support" / "Anki2"
_ANKI_PYTHON_DEFAULT = str(
    Path.home()
    / "Library"
    / "Application Support"
    / "AnkiProgramFiles"
    / ".venv"
    / "bin"
    / "python3.13"
)

# ── workflow registry ──────────────────────────────────────────────────────────

from workflows.base import WorkflowError
from workflows.mnemonic_image import MnemonicImageWorkflow

WORKFLOWS = {
    "mnemonic_image": MnemonicImageWorkflow,
    # "research_enrichment": ResearchEnrichmentWorkflow,  # future
    # "rewrite_qa": RewriteQAWorkflow,                    # future
}

# ── helpers ───────────────────────────────────────────────────────────────────


def resolve_anki_paths() -> tuple[str, str]:
    """Resolve collection path and media dir from ANKI_PROFILE env or auto-detect."""
    if not _ANKI2_ROOT.exists():
        print(f"ERROR: Anki2 directory not found: {_ANKI2_ROOT}")
        print("Is Anki installed? Set ANKI_PROFILE= in .env for a custom location.")
        sys.exit(1)

    profile = os.environ.get("ANKI_PROFILE", "").strip()
    if profile:
        profile_dir = _ANKI2_ROOT / profile
    else:
        candidates = [
            d for d in sorted(_ANKI2_ROOT.iterdir())
            if d.is_dir() and d.name != "addons21"
        ]
        if not candidates:
            print(f"ERROR: No Anki profiles found in {_ANKI2_ROOT}")
            print("Set ANKI_PROFILE=<your-profile-name> in .env")
            sys.exit(1)
        profile_dir = candidates[0]
        print(f"Auto-detected Anki profile: {profile_dir.name}")

    col_path = str(profile_dir / "collection.anki2")
    media_dir = str(profile_dir / "collection.media")

    if not Path(col_path).exists():
        print(f"ERROR: Collection not found: {col_path}")
        available = [
            d.name for d in sorted(_ANKI2_ROOT.iterdir())
            if d.is_dir() and d.name != "addons21"
        ]
        print(f"  Available profiles: {', '.join(available) or '(none found)'}")
        print("  Fix: set ANKI_PROFILE=<profile-name> in .env")
        sys.exit(1)

    return col_path, media_dir


def check_anki_not_running():
    result = subprocess.run(["pgrep", "-x", "Anki"], capture_output=True)
    if result.returncode == 0:
        print("ERROR: Anki is running. Please close it before running the pipeline.")
        sys.exit(1)


def run_anki_script(anki_python: str, script_name: str, extra_args: list[str]) -> str:
    """Run an anki_io script via Anki's bundled Python. Returns stdout."""
    cmd = [anki_python, str(ANKI_IO_DIR / script_name)] + extra_args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR in {script_name}:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def read_notes(anki_python: str, col_path: str, query: str, fields: list[str]) -> dict:
    raw = run_anki_script(anki_python, "read_notes.py", [
        "--col", col_path,
        "--query", query,
        "--fields", ",".join(fields),
    ])
    return json.loads(raw)


def write_notes(anki_python: str, col_path: str, state_path: Path):
    out = run_anki_script(anki_python, "write_notes.py", [
        "--col", col_path, "--state", str(state_path),
    ])
    if out.strip():
        print(out.rstrip())


def add_field(anki_python: str, col_path: str, notetype_id: int, field_name: str):
    out = run_anki_script(anki_python, "add_field.py", [
        "--col", col_path,
        "--notetype-id", str(notetype_id),
        "--field-name", field_name,
    ])
    if out.strip():
        print(out.rstrip())


def save_state(state_path: Path, state: dict):
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _fmt_duration(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    return f"{m}m {s:02d}s"


# ── main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Anki Card Enhancement Pipeline — bulk-enhance cards with AI-generated content.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--query",
        help="Anki search query to select notes (e.g. 'deck:\"US Presidents\"')",
    )
    group.add_argument(
        "--resume",
        metavar="STATE_FILE",
        help="Resume a previous run from its state file; retries only failed notes",
    )
    parser.add_argument(
        "--workflow",
        choices=list(WORKFLOWS.keys()),
        default="mnemonic_image",
        help="Enhancement workflow to run (default: mnemonic_image)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip all API calls and writes; shows which notes would be processed",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Process at most N notes; useful for testing on a single card before a full run",
    )
    parser.add_argument(
        "--anki-python",
        default=_ANKI_PYTHON_DEFAULT,
        help="Path to Anki's bundled Python (default: auto-detected on macOS)",
    )
    parser.add_argument(
        "--write-batch-size",
        type=int,
        default=10,
        help="Write results to the Anki collection every N processed notes (default: 10)",
    )
    parser.add_argument(
        "--input-fields",
        help="Comma-separated input field names, e.g. 'Name,Highlight' (overrides workflow default)",
    )
    args = parser.parse_args()

    load_dotenv()

    col_path, media_dir = resolve_anki_paths()
    check_anki_not_running()

    WorkflowClass = WORKFLOWS[args.workflow]
    print(f"Workflow: {args.workflow}")

    note_fields_cache: dict[str, dict[str, str]] = {}

    # ── validate API keys early ───────────────────────────────────────────────
    if not args.dry_run:
        if not os.environ.get("MINIMAX_API_KEY"):
            print("ERROR: MINIMAX_API_KEY not set. Copy .env.example to .env and fill it in.")
            sys.exit(1)

    # ── load or create state ──────────────────────────────────────────────────
    if args.resume:
        state_path = Path(args.resume)
        with open(state_path) as f:
            state = json.load(f)
        input_fields = state.get("input_fields", WorkflowClass.INPUT_FIELDS)
        pending_nids = [nid for nid, v in state["notes"].items() if v["status"] == "pending"]
        print(f"Resuming {state_path} — {len(pending_nids)} pending notes")
        if pending_nids:
            all_fields = list(dict.fromkeys(input_fields + WorkflowClass.OUTPUT_FIELDS))
            anki_data = read_notes(args.anki_python, col_path, state["query"], all_fields)
            note_fields_cache = {nid: info["fields"] for nid, info in anki_data["notes"].items()}
    else:
        input_fields = (
            [f.strip() for f in args.input_fields.split(",")]
            if args.input_fields
            else WorkflowClass.INPUT_FIELDS
        )
        all_fields = list(dict.fromkeys(input_fields + WorkflowClass.OUTPUT_FIELDS))
        print(f"Querying: {args.query}")
        anki_data = read_notes(args.anki_python, col_path, args.query, all_fields)
        notes_data = anki_data["notes"]
        notetypes = anki_data["notetypes"]
        print(f"Found {len(notes_data)} notes")

        if not notes_data:
            print("No notes matched that query. Check your search syntax and try again.")
            sys.exit(0)

        if not args.dry_run:
            missing = [
                (mid_str, nt_info["name"], field)
                for mid_str, nt_info in notetypes.items()
                for field in WorkflowClass.OUTPUT_FIELDS
                if field not in nt_info["field_names"]
            ]
            if missing:
                print("\nMissing output fields:")
                for _, nt_name, field in missing:
                    print(f"  '{field}' in notetype '{nt_name}'")
                ans = input("Add all missing fields? [y/N] ")
                if ans.strip().lower() != "y":
                    print("Aborting.")
                    sys.exit(1)
                for mid_str, _, field in missing:
                    add_field(args.anki_python, col_path, int(mid_str), field)

        STATE_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        state_path = STATE_DIR / f"{args.workflow}_{ts}.json"
        state = {
            "workflow": args.workflow,
            "query": args.query,
            "anki_python": args.anki_python,
            "input_fields": input_fields,
            "created_at": datetime.now().isoformat(),
            "notes": {nid: {"status": "pending"} for nid in notes_data},
        }
        save_state(state_path, state)
        pending_nids = list(notes_data.keys())
        note_fields_cache = {nid: info["fields"] for nid, info in notes_data.items()}
        print(f"State file: {state_path.resolve()}")

    if args.limit:
        pending_nids = pending_nids[:args.limit]
        print(f"Limiting to {args.limit} note(s)")

    if not pending_nids:
        print("No pending notes. Exiting.")
        return

    # ── instantiate workflow ──────────────────────────────────────────────────
    if not args.dry_run:
        try:
            workflow = WorkflowClass({
                "minimax_api_key": os.environ.get("MINIMAX_API_KEY", ""),
                "media_dir": media_dir,
                "input_fields": input_fields,
            })
        except RuntimeError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    else:
        workflow = None

    # ── main loop ─────────────────────────────────────────────────────────────
    counts = {"processed": 0, "failed": 0, "skipped": 0}
    processed_since_write = 0
    total = len(pending_nids)
    start_time = time.time()

    for i, nid in enumerate(pending_nids, 1):
        fields = note_fields_cache.get(nid, {})
        print(f"[{i}/{total}] {nid}", end=" — ", flush=True)

        if args.dry_run:
            print("dry-run")
            state["notes"][nid] = {"status": "skipped", "reason": "dry-run"}
            counts["skipped"] += 1
            continue

        skip, reason = workflow.should_skip(nid, fields)
        if skip:
            print(f"skip ({reason})")
            state["notes"][nid] = {"status": "skipped", "reason": reason}
            counts["skipped"] += 1
            save_state(state_path, state)
            continue

        try:
            output = workflow.process_note(nid, fields)
            state["notes"][nid] = {"status": "processed", "output": output}
            counts["processed"] += 1
            processed_since_write += 1

            elapsed = time.time() - start_time
            avg = elapsed / counts["processed"]
            remaining = total - i
            eta_str = f", ETA: ~{_fmt_duration(avg * remaining)}" if remaining > 0 else ""
            print(f"✓ {list(output.keys())}  (elapsed: {_fmt_duration(elapsed)}{eta_str})")
        except WorkflowError as e:
            state["notes"][nid] = {"status": "failed", "error": str(e)}
            counts["failed"] += 1
            print(f"✗ {e}")
        except Exception as e:
            state["notes"][nid] = {"status": "failed", "error": f"Unexpected: {e}"}
            counts["failed"] += 1
            print(f"✗ Unexpected error: {e}")

        save_state(state_path, state)

        if processed_since_write >= args.write_batch_size:
            write_notes(args.anki_python, col_path, state_path)
            processed_since_write = 0

    # flush remainder
    if processed_since_write > 0 and not args.dry_run:
        write_notes(args.anki_python, col_path, state_path)

    if workflow:
        workflow.teardown()

    # ── summary ───────────────────────────────────────────────────────────────
    total_elapsed = time.time() - start_time
    print(f"\n{'─' * 40}")
    print(
        f"Done. Processed: {counts['processed']}  "
        f"Failed: {counts['failed']}  "
        f"Skipped: {counts['skipped']}  "
        f"({_fmt_duration(total_elapsed)})"
    )

    if counts["processed"] > 0:
        print("\nNext steps:")
        print("  1. Open Anki and sync (Cmd+Y)")
        print("  2. Check a few cards to verify the output")

    if counts["failed"]:
        print(f"\nRetry failures:")
        print(f"  python3 run_pipeline.py --resume {state_path}")


if __name__ == "__main__":
    main()
