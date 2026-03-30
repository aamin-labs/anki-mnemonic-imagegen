#!/usr/bin/env python3
"""
Write processed notes back to the Anki collection.

Run with Anki's own Python:
  "/path/to/AnkiProgramFiles/.venv/bin/python3.13" write_notes.py \
      --col "/path/to/collection.anki2" \
      --state "/path/to/state.json"

Only writes notes with status "processed".
"""
import argparse
import json

from anki.collection import Collection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--col", required=True, help="Path to collection.anki2")
    parser.add_argument("--state", required=True, help="Path to pipeline state JSON file")
    parser.add_argument("--remove-tag", metavar="TAG", help="Remove this tag from processed notes")
    parser.add_argument("--add-tag", metavar="TAG", help="Add this tag to processed notes")
    args = parser.parse_args()

    with open(args.state) as f:
        state = json.load(f)

    col = Collection(args.col)
    try:
        updated_nids = []

        for nid_str, entry in state["notes"].items():
            if entry["status"] != "processed":
                continue

            nid = int(nid_str)
            note = col.get_note(nid)
            for field, value in entry["output"].items():
                if field.startswith("__"):
                    continue
                note[field] = value
            if args.remove_tag:
                note.remove_tag(args.remove_tag)
            if args.add_tag:
                note.add_tag(args.add_tag)
            col.update_note(note)
            updated_nids.append(nid)

        if updated_nids:
            col.after_note_updates(updated_nids, mark_modified=True, generate_cards=False)
            col.tags.clear_unused_tags()
            tag_msg = ""
            if args.remove_tag:
                tag_msg += f", removed tag '{args.remove_tag}'"
            if args.add_tag:
                tag_msg += f", added tag '{args.add_tag}'"
            print(f"✓ Wrote {len(updated_nids)} notes{tag_msg}", flush=True)
        else:
            print("No processed notes to write.", flush=True)
    finally:
        col.close()


if __name__ == "__main__":
    main()
