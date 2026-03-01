## Anki Database Workflow — Key Learnings

### 🔴 Critical: Back up the collection before any destructive script

Before running any script that uses `col.models.change()`, removes notetypes, deletes notes/cards, or otherwise makes irreversible structural changes, always add this backup step at the top of the script:

```python
import shutil, time, os

COL_PATH   = "/Users/aamin/Library/Application Support/Anki2/Abu/collection.anki2"
BACKUP_PATH = COL_PATH + f".backup_{time.strftime('%Y%m%d_%H%M%S')}"

shutil.copy2(COL_PATH, BACKUP_PATH)
print(f"✓ Backup saved to: {BACKUP_PATH}")
```

If something goes wrong the user can restore by copying the backup file back:
```bash
cp "/Users/aamin/Library/Application Support/Anki2/Abu/collection.anki2.backup_YYYYMMDD_HHMMSS" \
   "/Users/aamin/Library/Application Support/Anki2/Abu/collection.anki2"
```

**Destructive operations that always require a backup first:**
- `col.models.change()` — migrates notes between notetypes; wrong fmap/cmap silently deletes cards
- `col.models.remove()` — deletes a notetype and all its cards
- `col.remove_notes()` — deletes notes permanently
- Any bulk update touching hundreds of notes

**Non-destructive operations (no backup needed):**
- Adding fields or templates to an existing notetype
- Updating note field content
- `col.after_note_updates()` / card generation
- `col.tags.clear_unused_tags()`

---

### 🔴 Critical: `col.models.change()` — correct signature and gotchas

This is the most dangerous API call. Use it carefully:

```python
# CORRECT — first arg is the CURRENT notetype of the notes, third is target
col.models.change(src_nt, note_ids, new_nt, fmap, cmap)

# WRONG — passing new_nt as first arg means no cards match → all deleted silently
col.models.change(new_nt, note_ids, new_nt, fmap, cmap)  # ← BUG
```

- `fmap` maps old field ordinals → new field ordinals (dict). Fields not in fmap are dropped.
- `cmap` maps old template ordinals → new template ordinals (dict). `None` values = delete that card type (and all review history for it).
- If template names don't match between source and target notetype, all values in cmap will be `None` → all existing cards deleted.
- **Always print fmap and cmap before calling**, so you can verify they look right.
- **Always back up first** — there is no undo.

**Safer alternative:** Instead of migrating notes to a new notetype, add a template directly to the existing shared notetype and gate it with `{{#FieldName}}` so it only generates cards for notes where that field is non-empty. Zero migration risk.

---

### 🔴 Critical: Sync to AnkiWeb before any database changes

Before running any script that modifies the collection, always ask the user to:
1. Open Anki
2. Sync to AnkiWeb (Sync button, or Cmd+Y) to push any review progress from other devices
3. Close Anki
4. Then run the script

Skipping this will cause any card progress made on other devices (iPhone, iPad, etc.) since the last sync to be overwritten by the backup or pre-script state of the collection. After the script runs and Anki is reopened, the user should sync again immediately to push the changes back up to AnkiWeb.

---

### 🔴 Critical: Never modify the Anki database from the Linux VM directly

Every attempt to copy, modify with Python's `sqlite3`, and copy back the Anki collection resulted in a `DatabaseCorrupt (code 11)` error. The root cause is a **SQLite version mismatch**: the Linux VM runs an older system SQLite, while Anki 25.9 embeds a newer Rust-compiled SQLite via `rusqlite`. Files written by the older version are rejected by Anki's backend.

**Do not do this:**
```python
import sqlite3
conn = sqlite3.connect("/path/to/collection.anki2")
# modify...
conn.close()
# copy back — WILL CORRUPT
```

**Do not do this either** (pip-installed anki = wrong version):
```python
pip install anki   # installs 25.2.7, but user has Anki 25.9 — incompatible
from anki.collection import Collection
```

---

### ✅ Correct approach: Script using Anki's own bundled Python

Write a self-contained Python script, save it to the user's filesystem, and have them run it once from Terminal using Anki's own Python. This uses the exact same library version the app itself uses, so the database is always written correctly.

**Anki's Python path (for this user):**
```
/Users/aamin/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13
```

**Template for the Terminal command to give the user:**
```bash
"/Users/aamin/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13" \
    ~/Library/your_script.py
```

**Script pattern:**
```python
from anki.collection import Collection

col = Collection("/Users/aamin/Library/Application Support/Anki2/Abu/collection.anki2")

# Add fields
nt = col.models.get(note.mid)
col.models.add_field(nt, col.models.new_field("New Field"))
col.models.save(nt)

# Update notes
note = col.get_note(nid)
note['New Field'] = "value"
col.update_note(note)

# Add templates
tmpl = col.models.new_template("Template Name")
tmpl['qfmt'] = "question HTML"
tmpl['afmt'] = "answer HTML"
col.models.add_template(nt, tmpl)
col.models.save(nt)

# Generate cards for new templates
col.after_note_updates(list(note_ids), mark_modified=False, generate_cards=True)

col.close()  # critical — flushes and closes WAL cleanly
```

---

### Anki 25.9 database structure (schema version 18)

This is the newer Anki schema — fields and templates are in their own tables, not JSON in `col`.

| Table | Purpose |
|---|---|
| `decks` | Deck list (id, name) |
| `notetypes` | Note type definitions; CSS stored in `config` protobuf (field 3) |
| `fields` | Field definitions per notetype (ntid, ord, name, config) |
| `templates` | Card templates per notetype; qfmt/afmt encoded as protobuf |
| `notes` | Note content; `flds` column, fields separated by `\x1f` |
| `cards` | One row per card (nid, did, ord = template index) |

**`notetypes.config` protobuf fields** (from `notetypes_pb2.Notetype.Config`):
- Field 3 = CSS string

**`templates.config` protobuf fields** (from `notetypes_pb2.Notetype.Template.Config`):
- `q_format` — question template HTML
- `a_format` — answer template HTML

**Access CSS via the legacy API:** `nt['css'] = "..."`

---

### Anki collection file locations (Abu's profile)

```
Collection DB:  ~/Library/Application Support/Anki2/Abu/collection.anki2
Backup made:    ~/Library/Application Support/Anki2/Abu/collection.anki2.backup_before_presidents
Script:         ~/Library/enrich_presidents.py
```

---

### `unicase` collation

Anki registers a custom `unicase` collation for case-insensitive Unicode string sorting. If using Python's `sqlite3` directly (read-only / diagnostic purposes only), register it first:

```python
def unicase(s1, s2):
    return (s1.lower() > s2.lower()) - (s1.lower() < s2.lower())
conn.create_collation("unicase", unicase)
```

Without this, any query touching an index that uses `unicase` will throw `OperationalError`.

---

### Always ensure Anki is closed before running scripts

Anki holds a write lock on `collection.anki2`. Running any script against the live file while Anki is open will either fail or produce inconsistent results. Always ask the user to close Anki first and confirm before proceeding.

---

### Card template design pattern used in this session

Cards use self-contained front and back templates (no `{{FrontSide}}`), with a `.card-wrapper` div applying the Editorial Minimal dark theme. Structure per card type:

```html
<!-- Front -->
<div class="card-wrapper">
  <div class="context">CONTEXT LABEL</div>
  <div class="question">QUESTION</div>
</div>

<!-- Back -->
<div class="card-wrapper">
  <div class="context">CONTEXT LABEL</div>
  <div class="question">QUESTION</div>
  <div class="divider"></div>
  <div class="answer">ANSWER</div>
  <div class="meta">metadata</div>
  <div class="explanation">supplementary italic text</div>
</div>
```

CSS is set via `nt['css']` and stored in the notetype's protobuf config.
