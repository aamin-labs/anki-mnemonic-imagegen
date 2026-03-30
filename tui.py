#!/usr/bin/env python3
"""Textual TUI for anki-enrich — guided deck selection → workflow → run."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    ProgressBar,
    RichLog,
)

from common import ANKI_IO_DIR, PROJECT_DIR, _ANKI_PYTHON_DEFAULT
from workflows import WORKFLOWS

# ── constants ──────────────────────────────────────────────────────────────────

load_dotenv(PROJECT_DIR / ".env")
ANKI_PYTHON = os.environ.get("ANKI_PYTHON", _ANKI_PYTHON_DEFAULT)

# Only workflow-TUI-specific metadata lives here; all other attributes come from
# the workflow classes themselves (REQUIRED_ENV_KEYS, INPUT_FIELDS, OUTPUT_FIELDS).
_WORKFLOW_INFO: dict[str, dict] = {
    "highlight": {
        "description": "One-sentence highlight per card (Claude only)",
        "default_filter": "",
    },
    "mnemonic_image": {
        "description": "Visual mnemonic image (Claude + Imagen)",
        "default_filter": "tag:need-image",
    },
}

# Per-deck field name cache so ConfigScreen doesn't re-query on back/forward navigation.
_fields_cache: dict[str, list[str]] = {}

# ── helpers ───────────────────────────────────────────────────────────────────


def get_col_path() -> str:
    """Resolve collection.anki2 path using ANKI_PROFILE env or auto-detection."""
    anki2_root = Path.home() / "Library" / "Application Support" / "Anki2"
    profile = os.environ.get("ANKI_PROFILE", "").strip()
    if profile:
        return str(anki2_root / profile / "collection.anki2")
    try:
        candidates = sorted(
            d for d in anki2_root.iterdir()
            if d.is_dir() and d.name != "addons21"
        )
        if candidates:
            return str(candidates[0] / "collection.anki2")
    except FileNotFoundError:
        pass
    return ""


# ── dataclass ─────────────────────────────────────────────────────────────────


@dataclass
class RunConfig:
    deck_name: str
    workflow: str
    input_fields: list[str]
    dry_run: bool
    limit: int | None
    yes_add_fields: bool
    filter_query: str = ""


# ── custom list items ─────────────────────────────────────────────────────────


class DeckItem(ListItem):
    def __init__(self, deck_name: str) -> None:
        super().__init__(Label(deck_name))
        self.deck_name = deck_name


class WorkflowItem(ListItem):
    def __init__(self, workflow_id: str, description: str) -> None:
        super().__init__(Label(f"[b]{workflow_id}[/b]  –  {description}"))
        self.workflow_id = workflow_id


# ── modal ─────────────────────────────────────────────────────────────────────


class AnkiRunningModal(ModalScreen[None]):
    BINDINGS = [Binding("enter", "dismiss_modal", "OK")]

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Label("Anki is running", id="modal-title")
            yield Label("Close Anki first, then press Enter to retry.")
            yield Button("OK", variant="primary", id="ok-btn")

    @on(Button.Pressed, "#ok-btn")
    def dismiss_modal(self) -> None:
        self.dismiss()


# ── Screen 1: DeckSelectScreen ────────────────────────────────────────────────


class DeckSelectScreen(Screen):
    BINDINGS = [Binding("q", "quit_app", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield LoadingIndicator(id="loading")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Select Deck"
        self.fetch_decks()

    @work(exclusive=True)
    async def fetch_decks(self) -> None:
        col_path = get_col_path()
        if not col_path:
            self.query_one("#loading").remove()
            await self.mount(Label("ERROR: Could not find Anki collection.", id="error-label"))
            return

        proc = await asyncio.create_subprocess_exec(
            ANKI_PYTHON,
            str(ANKI_IO_DIR / "list_decks.py"),
            "--col", col_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        self.query_one("#loading").remove()

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            await self.mount(Label(f"ERROR: {err or 'Failed to load decks'}", id="error-label"))
            return

        decks = json.loads(stdout)["decks"]
        lv = ListView(*[DeckItem(d) for d in decks], id="deck-list")
        await self.mount(lv)
        lv.focus()

    @on(ListView.Selected, "#deck-list")
    def deck_selected(self, event: ListView.Selected) -> None:
        assert isinstance(event.item, DeckItem)
        self.app.push_screen(WorkflowSelectScreen(event.item.deck_name))


# ── Screen 2: WorkflowSelectScreen ───────────────────────────────────────────


class WorkflowSelectScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, deck_name: str) -> None:
        super().__init__()
        self._deck_name = deck_name

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield ListView(
            *[WorkflowItem(wid, _WORKFLOW_INFO[wid]["description"]) for wid in WORKFLOWS],
            id="workflow-list",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"Workflow — {self._deck_name}"
        self.query_one("#workflow-list").focus()

    @on(ListView.Selected, "#workflow-list")
    def workflow_selected(self, event: ListView.Selected) -> None:
        assert isinstance(event.item, WorkflowItem)
        self.app.push_screen(ConfigScreen(self._deck_name, event.item.workflow_id))

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ── Screen 3: ConfigScreen ────────────────────────────────────────────────────


class ConfigScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("ctrl+r", "run", "Run"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, deck_name: str, workflow_id: str) -> None:
        super().__init__()
        self._deck_name = deck_name
        self._workflow_id = workflow_id
        self._workflow_class = WORKFLOWS[workflow_id]
        self._info = _WORKFLOW_INFO[workflow_id]

    def compose(self) -> ComposeResult:
        wf = self._workflow_class
        missing_keys = [k for k in wf.REQUIRED_ENV_KEYS if not os.environ.get(k)]

        yield Header(show_clock=False)
        with VerticalScroll(id="config-scroll"):
            yield Label(f"[b]Deck:[/b]      {self._deck_name}", classes="config-row")
            yield Label(f"[b]Workflow:[/b]  {self._workflow_id}", classes="config-row")
            yield Label("", classes="divider")
            yield Label("Filter (appended to deck query):", classes="config-label")
            yield Input(
                value=self._info["default_filter"],
                placeholder="e.g. tag:need-image",
                id="filter-input",
            )
            yield Label("", classes="divider")

            yield Label("Input fields (comma-separated):", classes="config-label")
            yield Input(
                value=",".join(wf.INPUT_FIELDS),
                placeholder="e.g. Front,Back",
                id="input-fields",
            )
            yield Label("", id="available-fields-label", classes="hint")

            yield Label("", classes="divider")
            yield Label(
                f"Output fields: {', '.join(wf.OUTPUT_FIELDS)}",
                classes="config-label",
            )

            if missing_keys:
                yield Label(
                    f"Missing env keys: {', '.join(missing_keys)}  (set in .env)",
                    id="missing-keys-warn",
                    classes="warn",
                )

            yield Label("", classes="divider")
            yield Checkbox("Dry run", id="dry-run-cb")
            yield Label("Limit (blank = all notes):", classes="config-label")
            yield Input(placeholder="e.g. 5", id="limit-input")

            yield Button("Run", variant="success", id="run-btn")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"{self._workflow_id} — {self._deck_name}"
        self.fetch_fields()

    @work(exclusive=True)
    async def fetch_fields(self) -> None:
        if self._deck_name in _fields_cache:
            self.query_one("#available-fields-label", Label).update(
                f"Available: {', '.join(_fields_cache[self._deck_name])}"
            )
            return

        col_path = get_col_path()
        if not col_path:
            return

        proc = await asyncio.create_subprocess_exec(
            ANKI_PYTHON,
            str(ANKI_IO_DIR / "read_notes.py"),
            "--col", col_path,
            "--query", f'deck:"{self._deck_name}"',
            "--fields", "Front",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return

        all_fields: list[str] = []
        for nt_info in data.get("notetypes", {}).values():
            for fn in nt_info.get("field_names", []):
                if fn not in all_fields:
                    all_fields.append(fn)

        if all_fields:
            _fields_cache[self._deck_name] = all_fields
            self.query_one("#available-fields-label", Label).update(
                f"Available: {', '.join(all_fields)}"
            )

    @on(Button.Pressed, "#run-btn")
    def run_pressed(self) -> None:
        self.action_run()

    def action_run(self) -> None:
        input_fields_raw = self.query_one("#input-fields", Input).value.strip()
        input_fields = [f.strip() for f in input_fields_raw.split(",") if f.strip()]
        if not input_fields:
            return

        dry_run = self.query_one("#dry-run-cb", Checkbox).value
        limit_str = self.query_one("#limit-input", Input).value.strip()
        limit = int(limit_str) if limit_str.isdigit() else None
        filter_query = self.query_one("#filter-input", Input).value.strip()

        config = RunConfig(
            deck_name=self._deck_name,
            workflow=self._workflow_id,
            input_fields=input_fields,
            dry_run=dry_run,
            limit=limit,
            yes_add_fields=True,
            filter_query=filter_query,
        )
        self.app.push_screen(RunScreen(config))

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ── Screen 4: RunScreen ───────────────────────────────────────────────────────


class RunScreen(Screen):
    BINDINGS = [Binding("q", "quit_app", "Quit")]

    def __init__(self, config: RunConfig) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield RichLog(id="run-log", highlight=True, markup=True, wrap=True)
        yield ProgressBar(id="run-progress", show_eta=False)
        yield Label("", id="status-label")
        yield Footer()

    def on_mount(self) -> None:
        cfg = self._config
        self.sub_title = f"{cfg.workflow} — {cfg.deck_name}"
        self.launch_pipeline()

    @work(exclusive=True)
    async def launch_pipeline(self) -> None:
        log = self.query_one("#run-log", RichLog)
        progress = self.query_one("#run-progress", ProgressBar)
        status = self.query_one("#status-label", Label)

        # Check if Anki is running
        pgrep = await asyncio.create_subprocess_exec(
            "pgrep", "-x", "Anki",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await pgrep.wait()
        if pgrep.returncode == 0:
            await self.app.push_screen_wait(AnkiRunningModal())
            pgrep2 = await asyncio.create_subprocess_exec(
                "pgrep", "-x", "Anki",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await pgrep2.wait()
            if pgrep2.returncode == 0:
                status.update("[red]Cancelled: Anki is still running.[/red]")
                return

        cfg = self._config
        cmd = [
            sys.executable, str(PROJECT_DIR / "run_pipeline.py"),
            "--query", f'deck:"{cfg.deck_name}" {cfg.filter_query}'.strip(),
            "--workflow", cfg.workflow,
            "--input-fields", ",".join(cfg.input_fields),
            "--no-overwrite",
        ]
        if cfg.dry_run:
            cmd.append("--dry-run")
        if cfg.limit is not None:
            cmd += ["--limit", str(cfg.limit)]
        if cfg.yes_add_fields:
            cmd.append("--yes-add-fields")

        log.write(f"[dim]$ {' '.join(cmd)}[/dim]\n")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_DIR),
        )

        total: int | None = None

        assert proc.stdout is not None
        async for line in proc.stdout:
            text = line.decode(errors="replace").rstrip()
            log.write(text)

            m = re.search(r"\[(\d+)/(\d+)\]", text)
            if m:
                current, total_found = int(m.group(1)), int(m.group(2))
                if total is None:
                    total = total_found
                    progress.update(total=total)
                progress.update(progress=current)

        await proc.wait()
        rc = proc.returncode

        if total is None:
            progress.update(total=1, progress=1)

        if rc == 0:
            status.update("[green]Done[/green]")
        else:
            status.update(f"[red]Exited with code {rc}[/red]")


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
Screen {
    background: #1c1c1c;
}

Header {
    background: #2a2a2a;
    color: #e0e0e0;
}

Footer {
    background: #2a2a2a;
}

ListView {
    background: #1c1c1c;
    border: solid #333333;
    margin: 1 2;
}

ListItem {
    background: #1c1c1c;
    color: #e0e0e0;
    padding: 0 1;
}

ListItem:hover {
    background: #2d2d2d;
}

ListItem.--highlight {
    background: #3a3a3a;
    color: #ffffff;
}

LoadingIndicator {
    margin: 4 2;
}

#config-scroll {
    margin: 1 2;
}

.config-row {
    margin: 0 0 1 0;
    color: #cccccc;
}

.config-label {
    margin: 1 0 0 0;
    color: #aaaaaa;
}

.divider {
    margin: 1 0;
}

.hint {
    color: #666666;
}

.warn {
    color: #ffaa00;
    margin: 1 0;
}

Input {
    background: #2a2a2a;
    border: solid #444444;
    color: #e0e0e0;
    margin: 0 0 1 0;
}

Checkbox {
    margin: 1 0;
    color: #e0e0e0;
}

Button#run-btn {
    margin: 2 0 1 0;
}

#run-log {
    margin: 1 2;
    border: solid #333333;
    height: 1fr;
}

ProgressBar {
    margin: 0 2;
}

#status-label {
    margin: 0 2 1 2;
    height: 1;
}

#error-label {
    color: #ff5555;
    margin: 2;
}

AnkiRunningModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.7);
}

#modal-container {
    background: #2a2a2a;
    border: solid #ffaa00;
    padding: 2 4;
    width: 56;
    height: auto;
}

#modal-title {
    color: #ffaa00;
    text-style: bold;
    margin-bottom: 1;
}
"""


# ── App ───────────────────────────────────────────────────────────────────────


class AnkiEnrichApp(App):
    TITLE = "anki-enrich"
    CSS = _CSS

    def action_quit_app(self) -> None:
        self.exit()

    def on_mount(self) -> None:
        self.push_screen(DeckSelectScreen())


if __name__ == "__main__":
    AnkiEnrichApp().run()
