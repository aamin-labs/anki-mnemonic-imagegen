#!/usr/bin/env python3
r"""Fill Anki Image fields with small Wikipedia/Wikimedia context images.

Default queue: purple-flagged, non-suspended cards (`flag:6 -is:suspended`).
Must be run with Anki's bundled Python because it writes to collection.anki2.

Dry run:
  /Users/aamin/Library/Application\ Support/AnkiProgramFiles/.venv/bin/python3.13 \
    scripts/fill_wiki_context_images.py --dry-run

Real run:
  /Users/aamin/Library/Application\ Support/AnkiProgramFiles/.venv/bin/python3.13 \
    scripts/fill_wiki_context_images.py
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import backup_collection, ensure_anki_closed, resolve_anki_paths


USER_AGENT = "anki-enrich/1.0 (Abu local script; Wikipedia context image fetcher)"
DEFAULT_QUERY = "flag:6 -is:suspended"
DEFAULT_THUMB_SIZE = 260
DEFAULT_SUCCESS_TAG = "wiki-image-added"


@dataclass(frozen=True)
class WikiImage:
    title: str
    thumb_url: str
    source_url: str


@dataclass(frozen=True)
class PlannedUpdate:
    nid: int
    lookup_title: str
    wiki_image: WikiImage


@dataclass
class Counts:
    updated: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True)
class NotePlanResult:
    update: PlannedUpdate | None = None
    skipped: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=f"Anki search query (default: {DEFAULT_QUERY!r})",
    )
    parser.add_argument(
        "--anki-profile", default="Abu", help="Anki profile name (default: Abu)"
    )
    parser.add_argument(
        "--title-field",
        default="",
        help="Optional single field to use as the Wikipedia title/search text; by default candidates are derived from Question/Answer/Context",
    )
    parser.add_argument(
        "--image-field", default="Image", help="Field to populate with <img src=...>"
    )
    parser.add_argument(
        "--source-field",
        default="Source",
        help="Existing field to populate with the Wikipedia page URL",
    )
    parser.add_argument(
        "--title-map",
        help="Optional JSON file mapping field values to exact Wikipedia page titles",
    )
    parser.add_argument(
        "--thumb-size",
        type=int,
        default=DEFAULT_THUMB_SIZE,
        help=f"Thumbnail width in px (default: {DEFAULT_THUMB_SIZE})",
    )
    parser.add_argument(
        "--filename-prefix",
        default="wiki_context",
        help="Media filename prefix (default: wiki_context)",
    )
    parser.add_argument(
        "--success-tag",
        default=DEFAULT_SUCCESS_TAG,
        help=f"Tag to add after success (default: {DEFAULT_SUCCESS_TAG})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite notes that already have an image",
    )
    parser.add_argument(
        "--keep-flag",
        action="store_true",
        help="Do not clear flag:6 after successful writes",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
    )
    parser.add_argument(
        "--notify", action="store_true", help="Show a macOS completion notification"
    )
    return parser.parse_args()


def load_title_map(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(
            "--title-map must point to a JSON object of {field_value: wikipedia_title}"
        )
    return {str(k).strip(): str(v).strip() for k, v in data.items()}


def http_get_json(params: dict[str, str], timeout: int = 30) -> dict:
    query = urlencode(params)
    req = Request(
        f"https://en.wikipedia.org/w/api.php?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def http_get_bytes(url: str, retries: int = 5) -> bytes:
    delay = 2
    last_error: Exception | None = None
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
    raise RuntimeError(last_error)


def wiki_thumb_info(title: str, thumb_size: int) -> WikiImage | None:
    data = http_get_json(
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
    page = next(iter(data.get("query", {}).get("pages", {}).values()), {})
    if "missing" in page:
        return None

    thumb = page.get("thumbnail", {}).get("source")
    if not thumb:
        return None

    resolved_title = page.get("title", title)
    source_url = (
        page.get("fullurl")
        or f"https://en.wikipedia.org/wiki/{resolved_title.replace(' ', '_')}"
    )
    return WikiImage(resolved_title, thumb, source_url)


def wiki_search_top_title(query: str) -> str | None:
    data = http_get_json(
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": "1",
        }
    )
    hits = data.get("query", {}).get("search", [])
    if not hits:
        return None
    return hits[0].get("title")


def find_wiki_image(title: str, thumb_size: int) -> WikiImage | None:
    image = wiki_thumb_info(title, thumb_size)
    if image:
        return image

    search_title = wiki_search_top_title(title)
    if not search_title or search_title == title:
        return None
    return wiki_thumb_info(search_title, thumb_size)


def strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def bold_terms(value: str) -> list[str]:
    return [
        strip_html(match).strip(" —-:;,.?'")
        for match in re.findall(r"<b>(.*?)</b>", value, flags=re.I | re.S)
    ]


def proper_noun_phrases(value: str) -> list[str]:
    text = strip_html(value)
    # Naive on purpose: catches card-specific anchors like "Dieppe Raid", "Churchill", "German command".
    # Ceiling: no semantic ranking. Upgrade path: LLM/entity linker if this becomes noisy.
    pattern = r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:[ -](?:[A-Z][a-z]+|[A-Z]{2,}))*\b"
    stop = {"What", "Why", "Who", "When", "Where", "How", "No", "Yes", "Misconception"}
    return [term for term in re.findall(pattern, text) if term not in stop]


def unique_nonempty(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = strip_html(value).strip(" —-:;,.?'")
        lowered = cleaned.lower()
        if (
            cleaned
            and lowered not in seen
            and not any(lowered in old or old in lowered for old in seen)
        ):
            seen.add(lowered)
            result.append(cleaned)
    return result


def lookup_candidates(
    fields: dict[str, str], title_map: dict[str, str], title_field: str = ""
) -> list[str]:
    mapped = []
    for value in fields.values():
        stripped = strip_html(value)
        if stripped in title_map:
            mapped.append(title_map[stripped])

    if title_field:
        return unique_nonempty(
            mapped
            + [
                title_map.get(
                    strip_html(fields.get(title_field, "")), fields.get(title_field, "")
                )
            ]
        )

    question = fields.get("Question", "")
    answer = fields.get("Answer", "")
    context = fields.get("Context", "")
    return unique_nonempty(
        mapped
        + bold_terms(question)
        + bold_terms(answer)
        + proper_noun_phrases(question)
        + proper_noun_phrases(answer)
        + [context]
    )


class WikiLookupCache:
    def __init__(self, delay_seconds: float = 1.0):
        self.delay_seconds = delay_seconds
        self._cache: dict[tuple[str, int], WikiImage | None] = {}
        self._last_request_at = 0.0

    def find(self, title: str, thumb_size: int) -> WikiImage | None:
        key = (title, thumb_size)
        if key in self._cache:
            return self._cache[key]

        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        image = find_wiki_image(title, thumb_size)
        self._last_request_at = time.monotonic()
        self._cache[key] = image
        return image


def image_extension(url: str) -> str:
    base = url.split("?", 1)[0].lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if base.endswith(ext):
            return ext
    return ".jpg"


def notify(summary: str) -> None:
    script = f'display notification "{summary.replace(chr(34), chr(39))}" with title "Anki Wikipedia Images"'
    subprocess.run(
        ["osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def plan_note(
    note,
    args: argparse.Namespace,
    title_map: dict[str, str],
    lookup_cache: WikiLookupCache,
) -> NotePlanResult:
    fields = dict(note.items())
    missing = [args.image_field] if args.image_field not in fields else []
    if args.title_field and args.title_field not in fields:
        missing.append(args.title_field)
    if missing:
        print(f"[nid {note.id}] SKIP: missing required field(s): {missing}")
        return NotePlanResult(skipped=True)

    if fields[args.image_field].strip() and not args.overwrite:
        print(f"[nid {note.id}] SKIP: {args.image_field} already filled")
        return NotePlanResult(skipped=True)

    candidates = lookup_candidates(fields, title_map, args.title_field)
    if not candidates:
        print(f"[nid {note.id}] SKIP: no lookup candidates found")
        return NotePlanResult(skipped=True)

    errors = []
    for lookup_title in candidates:
        try:
            wiki_image = lookup_cache.find(lookup_title, args.thumb_size)
        except Exception as e:
            errors.append(f"{lookup_title!r}: {e}")
            continue
        if wiki_image:
            if lookup_title != candidates[0]:
                print(f"[nid {note.id}] fallback matched {lookup_title!r}")
            return NotePlanResult(
                update=PlannedUpdate(note.id, lookup_title, wiki_image)
            )

    if errors:
        print(f"[nid {note.id}] FAIL: Wikipedia lookup failed: {'; '.join(errors)}")
    else:
        print(
            f"[nid {note.id}] FAIL: no Wikipedia thumbnail found for candidates {candidates!r}"
        )
    return NotePlanResult()


def flagged_card_ids_for_note(col: Any, nid: int) -> list[int]:
    return list(col.find_cards(f"nid:{nid} flag:6"))


def main() -> None:
    args = parse_args()
    counts = Counts()
    try:
        ensure_anki_closed()
        from anki.collection import Collection

        anki_paths = resolve_anki_paths(args.anki_profile, require_media=True)
        title_map = load_title_map(args.title_map)
        lookup_cache = WikiLookupCache()

        col = Collection(str(anki_paths.collection))
        try:
            note_ids = list(col.find_notes(args.query))
            print(f"Found {len(note_ids)} matching note(s)")
            if not note_ids:
                return

            planned: list[PlannedUpdate] = []
            source_field_missing = False

            for nid in note_ids:
                note = col.get_note(nid)
                if args.source_field not in dict(note.items()):
                    source_field_missing = True
                result = plan_note(note, args, title_map, lookup_cache)
                if result.skipped:
                    counts.skipped += 1
                elif result.update:
                    planned.append(result.update)
                    print(
                        f"[nid {nid}] {result.update.lookup_title!r} -> {result.update.wiki_image.title!r}"
                    )
                else:
                    counts.failed += 1

            print(f"\nPlanned updates: {len(planned)}")
            if counts.skipped:
                print(f"Skipped: {counts.skipped}")
            if counts.failed:
                print(f"Failed lookups: {counts.failed}")
            if source_field_missing:
                print(
                    f"Warning: some notes lack {args.source_field!r}; source URL will be skipped for those notes."
                )

            if args.dry_run:
                print("Dry run only — no changes written.")
                return

            if not planned:
                print("No writable changes planned.")
                return

            backup_path = backup_collection(anki_paths.collection)
            print(f"\n✓ Backup saved to: {backup_path}")

            updated_nids: list[int] = []
            flag_card_ids: list[int] = []
            for update in planned:
                note = col.get_note(update.nid)
                ext = image_extension(update.wiki_image.thumb_url)
                filename = f"{args.filename_prefix}_{update.nid}{ext}"
                (anki_paths.media_dir / filename).write_bytes(
                    http_get_bytes(update.wiki_image.thumb_url)
                )

                note[args.image_field] = (
                    f'<img src="{html.escape(filename, quote=True)}">'
                )
                if args.source_field in dict(note.items()):
                    note[args.source_field] = update.wiki_image.source_url
                if args.success_tag:
                    note.add_tag(args.success_tag)
                col.update_note(note)
                updated_nids.append(update.nid)
                flag_card_ids.extend(flagged_card_ids_for_note(col, update.nid))
                counts.updated += 1
                print(f"✓ {update.lookup_title} -> {filename}")
                time.sleep(1)

            if updated_nids:
                col.after_note_updates(
                    updated_nids, mark_modified=True, generate_cards=False
                )
                if flag_card_ids and not args.keep_flag:
                    col.set_user_flag_for_cards(flag=0, cids=flag_card_ids)
                col.tags.clear_unused_tags()

            print(
                f"\nDone. Updated {counts.updated}, skipped {counts.skipped}, failed {counts.failed}."
            )
            if not args.keep_flag:
                print(f"Cleared flag:6 from {len(set(flag_card_ids))} card(s).")
            if args.success_tag:
                print(f"Added tag: {args.success_tag}")
        finally:
            col.close()
    finally:
        if args.notify:
            notify(
                f"{counts.updated} updated, {counts.skipped} skipped, {counts.failed} failed"
            )


if __name__ == "__main__":
    main()
