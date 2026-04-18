# Copy Note Fields as Markdown

A tiny Browser add-on for Anki that copies the selected card's note fields to the system clipboard as Markdown.

## What it does

- Adds a Browser context-menu action: **Copy note fields as Markdown**
- Works in **Cards** mode only
- Requires **exactly one selected card**
- Copies the selected card's **note fields** in field order
- Skips fields that are empty after cleanup
- Strips HTML while keeping media filenames as plain text where possible
- Does **not** write to your collection

## Output shape

```md
## Front

Question text

## Back

Answer text
```

Field headings come from the note's real field names, so decks with `Text`, `Extra`, `Sentence`, etc. will use those names instead.

## Install

### From a packaged zip

In Anki:
1. Go to **Tools → Add-ons → Install from file...**
2. Select the packaged `.ankiaddon` or `.zip`
3. Restart Anki

### From source during development

Copy this folder into your Anki `addons21` folder:

```text
copy_note_fields_markdown/
```

Then restart Anki.

## Use

1. Open Anki Browser
2. Switch to **Cards** mode
3. Select exactly one card
4. Right-click
5. Choose **Copy note fields as Markdown**

## Notes

- Sibling cards from the same note will copy the same fields. That's expected.
- Cloze fields are copied from the underlying note fields, not rendered card HTML.
- This add-on is intentionally minimal. No settings, no batch export, no toolbar button.
