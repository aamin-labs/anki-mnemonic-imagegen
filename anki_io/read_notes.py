#!/usr/bin/env python3
"""
Read notes from the Anki collection and print them as JSON to stdout.

Run with Anki's own Python:
  "/path/to/AnkiProgramFiles/.venv/bin/python3.13" read_notes.py \
      --col "/path/to/collection.anki2" \
      --query 'deck:"US Presidents"' \
      --fields "Front,Back,Mnemonic"
"""
import argparse
import json
import sys

from anki.collection import Collection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--col", required=True, help="Path to collection.anki2")
    parser.add_argument("--query", required=True, help="Anki search query")
    parser.add_argument("--fields", required=True, help="Comma-separated field names to include")
    args = parser.parse_args()

    field_names = [f.strip() for f in args.fields.split(",")]

    col = Collection(args.col)
    try:
        note_ids = col.find_notes(args.query)

        notes_out = {}
        notetypes_out = {}

        nt_cache = {}
        for nid in note_ids:
            note = col.get_note(nid)
            mid = str(note.mid)

            if mid not in nt_cache:
                nt = col.models.get(note.mid)
                nt_cache[mid] = {
                    "name": nt["name"],
                    "field_names": [f["name"] for f in nt["flds"]],
                }
            nt_info = nt_cache[mid]

            note_dict = dict(note.items())
            note_fields = {fn: note_dict.get(fn, "") for fn in field_names}

            notes_out[str(nid)] = {
                "mid": note.mid,
                "notetype_name": nt_info["name"],
                "fields": note_fields,
            }

        notetypes_out = nt_cache

        json.dump({"notes": notes_out, "notetypes": notetypes_out}, sys.stdout)
    finally:
        col.close()


if __name__ == "__main__":
    main()
