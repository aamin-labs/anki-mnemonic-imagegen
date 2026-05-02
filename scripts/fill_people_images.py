#!/usr/bin/env python3
"""Fill an Anki image field with small Wikipedia/Wikimedia thumbnails for people cards.

Must be run with Anki's bundled Python because it writes to collection.anki2.

Examples:
  Dry run on a deck:
    /Users/aamin/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13 \
      scripts/fill_people_images.py \
      --query 'deck:"1. 🎖️ Active::1.40 📜 History" flag:3' \
      --dry-run

  Real run with title overrides for page-name mismatches:
    /Users/aamin/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13 \
      scripts/fill_people_images.py \
      --query 'deck:"1. 🎖️ Active::1.40 📜 History" flag:3' \
      --title-map data/british_monarch_titles.json
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from anki.collection import Collection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import backup_collection, ensure_anki_closed, resolve_anki_paths


USER_AGENT = "anki-enrich/1.0 (Abu local script; Wikipedia thumbnail fetcher)"
DEFAULT_THUMB_SIZE = 220


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Anki search query")
    parser.add_argument("--anki-profile", default="Abu", help="Anki profile name (default: Abu)")
    parser.add_argument("--name-field", default="Question", help="Field containing the person's name")
    parser.add_argument("--image-field", default="Image", help="Field to populate with <img src=...>")
    parser.add_argument("--source-field", default="Source", help="Field to populate with the Wikipedia page URL")
    parser.add_argument(
        "--title-map",
        help="Optional JSON file mapping note names to exact Wikipedia page titles",
    )
    parser.add_argument(
        "--thumb-size",
        type=int,
        default=DEFAULT_THUMB_SIZE,
        help=f"Thumbnail width in px (default: {DEFAULT_THUMB_SIZE})",
    )
    parser.add_argument(
        "--filename-prefix",
        default="person_image",
        help="Media filename prefix (default: person_image)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite notes that already have an image",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview matches and Wikipedia titles without writing anything",
    )
    return parser.parse_args()


def load_title_map(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit("--title-map must point to a JSON object of {note_name: wikipedia_title}")
    return {str(k).strip(): str(v).strip() for k, v in data.items()}


def http_get_bytes(url: str, retries: int = 5) -> bytes:
    delay = 2
    last_error = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=60) as resp:
                return resp.read()
        except HTTPError as e:
            last_error = e
            if e.code != 429 or attempt == retries - 1:
                raise
            print(f"  rate limited; sleeping {delay}s and retrying...")
            time.sleep(delay)
            delay *= 2
    raise last_error


def wiki_thumb_info(title: str, thumb_size: int) -> tuple[str, str, str]:
    params = urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "pageimages|info",
            "titles": title,
            "pithumbsize": str(thumb_size),
            "inprop": "url",
            "redirects": "1",
        }
    )
    req = Request(f"https://en.wikipedia.org/w/api.php?{params}", headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    page = next(iter(data["query"]["pages"].values()))
    thumb = page.get("thumbnail", {}).get("source")
    fullurl = page.get("fullurl")
    resolved_title = page.get("title", title)
    if not thumb:
        raise RuntimeError(f"No thumbnail found for Wikipedia page: {resolved_title}")
    if not fullurl:
        fullurl = f"https://en.wikipedia.org/wiki/{resolved_title.replace(' ', '_')}"
    return resolved_title, thumb, fullurl


def image_extension(url: str) -> str:
    base = url.split("?", 1)[0].lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if base.endswith(ext):
            return ext
    return ".jpg"


def main() -> None:
    args = parse_args()
    try:
        ensure_anki_closed()
        anki_paths = resolve_anki_paths(args.anki_profile, require_media=True)
    except RuntimeError as e:
        raise SystemExit(str(e))
    col_path = anki_paths.collection
    media_dir = anki_paths.media_dir
    title_map = load_title_map(args.title_map)

    col = Collection(str(col_path))
    try:
        note_ids = col.find_notes(args.query)
        print(f"Found {len(note_ids)} matching notes")
        if not note_ids:
            return

        sample_note = col.get_note(note_ids[0])
        available_fields = set(dict(sample_note.items()).keys())
        for field in (args.name_field, args.image_field, args.source_field):
            if field not in available_fields:
                raise SystemExit(f"Field '{field}' not found on matched notes. Available: {sorted(available_fields)}")

        planned: list[tuple[int, str, str, str]] = []
        skipped_existing = 0

        for nid in note_ids:
            note = col.get_note(nid)
            name = note[args.name_field].strip()
            if not name:
                print(f"- Skip note {nid}: empty {args.name_field}")
                continue
            if note[args.image_field].strip() and not args.overwrite:
                skipped_existing += 1
                print(f"- Skip {name}: {args.image_field} already filled")
                continue

            wiki_title = title_map.get(name, name)
            resolved_title, thumb_url, source_url = wiki_thumb_info(wiki_title, args.thumb_size)
            planned.append((nid, name, thumb_url, source_url))
            print(f"• {name} -> {resolved_title}")

        print(f"\nPlanned updates: {len(planned)}")
        if skipped_existing:
            print(f"Skipped existing images: {skipped_existing}")

        if args.dry_run:
            print("Dry run only — no changes written.")
            return

        backup_path = backup_collection(col_path)
        print(f"✓ Backup saved to: {backup_path}")

        updated_nids: list[int] = []
        for nid, name, thumb_url, source_url in planned:
            note = col.get_note(nid)
            ext = image_extension(thumb_url)
            filename = f"{args.filename_prefix}_{nid}{ext}"
            (media_dir / filename).write_bytes(http_get_bytes(thumb_url))

            note[args.image_field] = f'<img src="{html.escape(filename, quote=True)}">'
            note[args.source_field] = source_url
            col.update_note(note)
            updated_nids.append(nid)
            print(f"✓ {name} -> {filename}")
            time.sleep(1)

        if updated_nids:
            col.after_note_updates(updated_nids, mark_modified=True, generate_cards=False)

        print(f"\nDone. Updated {len(updated_nids)} notes.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
