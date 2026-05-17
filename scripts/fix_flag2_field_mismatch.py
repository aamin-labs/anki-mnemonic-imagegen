#!/usr/bin/env python3
r"""Fix field-shifted aBasic notes marked with red flag (flag:2).

The bad import pattern is:
  Hint    <- real answer
  Answer  <- topic/context label
  Context <- explanation/detail

The corrected pattern is:
  Hint        <- empty
  Answer      <- old Hint
  Context     <- old Answer
  Explanation <- old Context

Run with Anki's bundled Python:
  /Users/aamin/Library/Application\ Support/AnkiProgramFiles/.venv/bin/python3.13 \
    scripts/fix_flag2_field_mismatch.py --dry-run

Then run without --dry-run to write changes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from anki.collection import Collection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import backup_collection, ensure_anki_closed, resolve_anki_paths


REQUIRED_FIELDS = ("Question", "Hint", "Answer", "Context", "Explanation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default='flag:2 note:"aBasic (opt rev)"', help="Anki search query")
    parser.add_argument("--anki-profile", default="Abu", help="Anki profile name (default: Abu)")
    parser.add_argument("--collection", help="Explicit collection.anki2 path; useful for testing on a copy")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--keep-flag", action="store_true", help="Do not clear flag:2 after writing")
    return parser.parse_args()


def short(value: str, limit: int = 100) -> str:
    value = value.replace("\n", "\\n")
    return value if len(value) <= limit else value[: limit - 1] + "..."


def main() -> None:
    args = parse_args()

    if args.collection:
        col_path = Path(args.collection).expanduser()
    else:
        try:
            ensure_anki_closed()
            col_path = resolve_anki_paths(args.anki_profile).collection
        except RuntimeError as e:
            raise SystemExit(str(e))

    col = Collection(str(col_path))
    try:
        note_ids = list(col.find_notes(args.query))
        print(f"Found {len(note_ids)} matching note(s)")
        if not note_ids:
            return

        planned: list[tuple[int, str, str, str]] = []
        skipped = 0

        for nid in note_ids:
            note = col.get_note(nid)
            fields = dict(note.items())
            missing = [field for field in REQUIRED_FIELDS if field not in fields]
            if missing:
                print(f"[nid {nid}] SKIP: missing fields {missing}")
                skipped += 1
                continue

            old_hint = fields["Hint"].strip()
            old_answer = fields["Answer"].strip()
            old_context = fields["Context"].strip()

            if not old_hint or not old_answer:
                print(f"[nid {nid}] SKIP: expected old Hint and old Answer to be non-empty")
                skipped += 1
                continue

            planned.append((nid, old_hint, old_answer, old_context))
            print(f"\n[nid {nid}]")
            print(f"  Answer      <- Hint    : {short(old_hint)!r}")
            print(f"  Context     <- Answer  : {short(old_answer)!r}")
            print(f"  Explanation <- Context : {short(old_context)!r}")
            print("  Hint        <- ''")

        if args.dry_run:
            print(f"\nDry run only. Would update {len(planned)} note(s), skipped {skipped}.")
            return

        if not planned:
            print(f"\nNo writable changes planned. Skipped {skipped}.")
            return

        backup_path = backup_collection(col_path)
        print(f"\nBackup saved to: {backup_path}")

        updated_nids: list[int] = []
        for nid, new_answer, new_context, new_explanation in planned:
            note = col.get_note(nid)
            note["Hint"] = ""
            note["Answer"] = new_answer
            note["Context"] = new_context
            note["Explanation"] = new_explanation
            col.update_note(note)
            updated_nids.append(nid)

        col.after_note_updates(updated_nids, mark_modified=True, generate_cards=False)

        if not args.keep_flag:
            card_ids = list(col.find_cards(args.query))
            if card_ids:
                col.set_user_flag_for_cards(flag=0, cids=card_ids)

        print(f"Done. Updated {len(updated_nids)} note(s), skipped {skipped}.")
        if not args.keep_flag:
            print("Cleared flag:2 from matching cards.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
