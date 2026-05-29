#!/usr/bin/env python3
"""Anki Card Enhancement Pipeline — main CLI entrypoint."""

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ── constants ─────────────────────────────────────────────────────────────────

from anki_backends import DirectAnkiBackend
from common import PROJECT_DIR, _ANKI_PYTHON_DEFAULT, ensure_anki_closed, resolve_anki_paths

STATE_DIR = PROJECT_DIR / "state"

# ── workflow registry ──────────────────────────────────────────────────────────

from workflows import WORKFLOWS
from workflows.base import WorkflowError

# ── helpers ───────────────────────────────────────────────────────────────────


def _resolve_tag(cli_value: str | None, workflow, kind: str) -> str:
    """Return the tag to use: CLI value if explicitly set, else workflow default, else ''."""
    if cli_value is not None:
        return cli_value  # explicit '' disables the default
    attr = "DEFAULT_ADD_TAG" if kind == "add" else "DEFAULT_REMOVE_TAG"
    return getattr(workflow, attr, "") if workflow else ""


def save_state(state_path: Path, state: dict):
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _fmt_duration(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    return f"{m}m {s:02d}s"


def _read_notes(backend: DirectAnkiBackend, query: str, fields: list[str]) -> dict:
    try:
        return backend.read_notes(query, fields)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def _write_notes(
    backend: DirectAnkiBackend,
    state_path: Path,
    *,
    remove_tag: str = "",
    add_tag: str = "",
) -> None:
    try:
        out = backend.write_notes(state_path, remove_tag=remove_tag, add_tag=add_tag)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    if out.strip():
        print(out.rstrip())


def _add_field(backend: DirectAnkiBackend, notetype_id: int, field_name: str) -> None:
    try:
        out = backend.add_field(notetype_id, field_name)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    if out.strip():
        print(out.rstrip())


# ── verify ────────────────────────────────────────────────────────────────────


def _run_verify(state_file: str, backend: DirectAnkiBackend):
    """Re-read processed notes from Anki and confirm output fields are non-empty."""
    state_path = Path(state_file)
    with open(state_path) as f:
        state = json.load(f)

    output_fields = state.get("output_fields", [])
    if not output_fields:
        print("State file has no output fields to verify.")
        return

    processed = {nid: entry for nid, entry in state["notes"].items() if entry["status"] == "processed"}
    if not processed:
        print("No processed notes in state file.")
        return

    print(f"Verifying {len(processed)} processed note(s) — fields: {output_fields}")
    anki_data = _read_notes(backend, state["query"], output_fields)
    note_fields = {nid: info["fields"] for nid, info in anki_data["notes"].items()}

    ok = failed = 0
    for nid in processed:
        fields = note_fields.get(nid, {})
        missing = [f for f in output_fields if not fields.get(f, "").strip()]
        if missing:
            print(f"  MISSING  {nid}  ({', '.join(missing)} empty in Anki)")
            failed += 1
        else:
            ok += 1

    print(f"\n{'─' * 40}")
    print(f"Verified: {ok} OK   {failed} missing")
    if failed:
        print(f"\nTo retry missing notes, run:")
        print(f"  python3 run_pipeline.py --resume {state_path.resolve()}")


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
    group.add_argument(
        "--verify",
        metavar="STATE_FILE",
        help="Re-read processed notes from Anki and confirm output fields were written",
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
    parser.add_argument(
        "--output-fields",
        help="Comma-separated output field names, e.g. 'Image,Encoding' (overrides workflow default)",
    )
    parser.add_argument(
        "--list-fields",
        action="store_true",
        help="Print field names for notes matched by --query and exit",
    )
    parser.add_argument(
        "--yes-add-fields",
        action="store_true",
        help="Auto-confirm adding missing output fields to the notetype (non-interactive)",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Skip notes with output fields already filled, without prompting",
    )
    parser.add_argument(
        "--prompt-file",
        metavar="FILENAME",
        help="Prompt template filename inside prompts/ (e.g. prompt-pm-mnemonic.md); overrides workflow default",
    )
    parser.add_argument(
        "--remove-tag",
        metavar="TAG",
        default=None,
        help="Remove this tag from successfully processed notes (pass '' to disable workflow default)",
    )
    parser.add_argument(
        "--add-tag",
        metavar="TAG",
        default=None,
        help="Add this tag to successfully processed notes (pass '' to disable workflow default)",
    )
    args = parser.parse_args()

    load_dotenv()

    try:
        anki_paths = resolve_anki_paths(os.environ.get("ANKI_PROFILE", "").strip() or None)
        ensure_anki_closed()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    backend = DirectAnkiBackend(args.anki_python, anki_paths.collection)
    media_dir = str(anki_paths.media_dir)

    if args.verify:
        _run_verify(args.verify, backend)
        return

    if args.list_fields:
        if not args.query:
            print("ERROR: --list-fields requires --query")
            sys.exit(1)
        print(f"Querying: {args.query}")
        anki_data = _read_notes(backend, args.query, ["Front"])
        if not anki_data["notes"]:
            print("No notes matched that query.")
            sys.exit(0)
        print(f"Found {len(anki_data['notes'])} notes\n")
        for mid, nt_info in anki_data["notetypes"].items():
            print(f"Notetype: {nt_info['name']}")
            print(f"Fields:   {', '.join(nt_info['field_names'])}")
        sys.exit(0)

    WorkflowClass = WORKFLOWS[args.workflow]
    print(f"Workflow: {args.workflow}")
    if WorkflowClass.DESCRIPTION:
        print(f"Description: {WorkflowClass.DESCRIPTION}")

    note_fields_cache: dict[str, dict[str, str]] = {}

    # ── validate API keys early ───────────────────────────────────────────────
    if not args.dry_run:
        missing_keys = [k for k in WorkflowClass.REQUIRED_ENV_KEYS if not os.environ.get(k)]
        if missing_keys:
            print(f"ERROR: {', '.join(missing_keys)} not set. Copy .env.example to .env and fill it in.")
            sys.exit(1)

    # ── load or create state ──────────────────────────────────────────────────
    if args.resume:
        state_path = Path(args.resume)
        with open(state_path) as f:
            state = json.load(f)
        input_fields = state.get("input_fields", WorkflowClass.INPUT_FIELDS)
        output_fields = state.get("output_fields", WorkflowClass.OUTPUT_FIELDS)
        pending_nids = [nid for nid, v in state["notes"].items() if v["status"] == "pending"]
        print(f"Resuming {state_path} — {len(pending_nids)} pending notes")
        if pending_nids:
            all_fields = list(dict.fromkeys(input_fields + output_fields))
            anki_data = _read_notes(backend, state["query"], all_fields)
            note_fields_cache = {nid: info["fields"] for nid, info in anki_data["notes"].items()}
    else:
        input_fields = (
            [f.strip() for f in args.input_fields.split(",")]
            if args.input_fields
            else WorkflowClass.INPUT_FIELDS
        )
        output_fields = (
            [f.strip() for f in args.output_fields.split(",")]
            if args.output_fields
            else WorkflowClass.OUTPUT_FIELDS
        )
        if not WorkflowClass.WRITES_FIELDS:
            output_fields = []
        all_fields = list(dict.fromkeys(input_fields + output_fields))
        print(f"Querying: {args.query}")
        anki_data = _read_notes(backend, args.query, all_fields)
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
                for field in output_fields
                if field not in nt_info["field_names"]
            ]
            if missing:
                print("\nMissing output fields:")
                for _, nt_name, field in missing:
                    print(f"  '{field}' in notetype '{nt_name}'")
                ans = "y" if args.yes_add_fields else input("Add all missing fields? [y/N] ")
                if ans.strip().lower() != "y":
                    print("Aborting.")
                    sys.exit(1)
                for mid_str, _, field in missing:
                    _add_field(backend, int(mid_str), field)

        STATE_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        state_path = STATE_DIR / f"{args.workflow}_{ts}.json"
        state = {
            "workflow": args.workflow,
            "query": args.query,
            "anki_python": args.anki_python,
            "input_fields": input_fields,
            "output_fields": output_fields,
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
                "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
                "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
                "media_dir": media_dir,
                "input_fields": input_fields,
                "output_fields": output_fields,
                "prompt_file": args.prompt_file,
                "query": args.query or state.get("query", ""),
            })
        except RuntimeError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    else:
        workflow = None

    # ── overwrite confirmation ────────────────────────────────────────────────
    force_overwrite = False
    if not args.dry_run:
        skip_results = [
            (nid, workflow.should_skip(nid, note_fields_cache.get(nid, {})))
            for nid in pending_nids
        ]
        prefilled = [nid for nid, (skip, _) in skip_results if skip]
        if prefilled:
            reason_counts = Counter(reason for _, (skip, reason) in skip_results if skip)
            reason_summary = ", ".join(f"{count} {reason}" for reason, count in reason_counts.items())
            print(f"\n{len(prefilled)} of {len(pending_nids)} note(s) will be skipped ({reason_summary}).")
            if args.no_overwrite:
                print("Existing values will be skipped.")
            else:
                ans = input("Overwrite existing values? [y/N] ").strip().lower()
                if ans == "y":
                    force_overwrite = True
                    print("Overwriting existing values.")
                else:
                    print("Existing values will be skipped.")

    # ── main loop ─────────────────────────────────────────────────────────────
    write_remove_tag = _resolve_tag(args.remove_tag, workflow, "remove")
    write_add_tag = _resolve_tag(args.add_tag, workflow, "add")
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
        if skip and not force_overwrite:
            print(f"skip ({reason})")
            state["notes"][nid] = {"status": "skipped", "reason": reason}
            counts["skipped"] += 1
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
            _write_notes(backend, state_path, remove_tag=write_remove_tag, add_tag=write_add_tag)
            processed_since_write = 0

    save_state(state_path, state)

    # flush remainder
    if processed_since_write > 0 and not args.dry_run:
        _write_notes(backend, state_path, remove_tag=write_remove_tag, add_tag=write_add_tag)

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
        print(f"\nRetry failures with:")
        print(f"  python3 run_pipeline.py --resume {state_path.resolve()}")

    if output_fields:
        print(f"\nVerify writes with:")
        print(f"  python3 run_pipeline.py --verify {state_path.resolve()}")


if __name__ == "__main__":
    main()
