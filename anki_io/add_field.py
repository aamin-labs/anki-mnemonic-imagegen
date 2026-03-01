#!/usr/bin/env python3
"""
Add a field to an existing notetype (non-destructive — no backup required).

Run with Anki's own Python:
  "/path/to/AnkiProgramFiles/.venv/bin/python3.13" add_field.py \
      --col "/path/to/collection.anki2" \
      --notetype-id 12345 \
      --field-name "Mnemonic"
"""
import argparse

from anki.collection import Collection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--col", required=True, help="Path to collection.anki2")
    parser.add_argument("--notetype-id", required=True, type=int)
    parser.add_argument("--field-name", required=True)
    args = parser.parse_args()

    col = Collection(args.col)
    try:
        nt = col.models.get(args.notetype_id)
        if nt is None:
            print(f"ERROR: notetype {args.notetype_id} not found", flush=True)
            return

        existing = [f["name"] for f in nt["flds"]]
        if args.field_name in existing:
            print(f"Field '{args.field_name}' already exists on '{nt['name']}'", flush=True)
            return

        col.models.add_field(nt, col.models.new_field(args.field_name))
        col.models.save(nt)
        print(f"✓ Added field '{args.field_name}' to '{nt['name']}'", flush=True)
    finally:
        col.close()


if __name__ == "__main__":
    main()
