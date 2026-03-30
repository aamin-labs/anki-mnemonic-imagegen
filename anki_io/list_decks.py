#!/usr/bin/env python3
"""
List all decks in the Anki collection and print them as JSON to stdout.

Run with Anki's own Python:
  "/path/to/AnkiProgramFiles/.venv/bin/python3.13" list_decks.py \
      --col "/path/to/collection.anki2"
"""
import argparse
import json
import sys

from anki.collection import Collection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--col", required=True, help="Path to collection.anki2")
    args = parser.parse_args()

    col = Collection(args.col)
    try:
        decks = sorted(
            [d.name for d in col.decks.all_names_and_ids() if d.name != "Default"],
            key=str.lower,
        )
        json.dump({"decks": decks}, sys.stdout)
    finally:
        col.close()


if __name__ == "__main__":
    main()
