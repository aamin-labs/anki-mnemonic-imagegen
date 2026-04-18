from aqt import gui_hooks
from aqt.qt import QAction, QGuiApplication
from aqt.utils import tooltip

from .export import build_markdown_from_note

ACTION_TEXT = "Copy note fields as Markdown"
MODE_SELECTION_MESSAGE = "Switch to Cards mode and select exactly one card."
NO_FIELDS_MESSAGE = "No non-empty note fields to copy."
SUCCESS_MESSAGE = "Copied note fields as Markdown."


def copy_selected_note_fields(browser) -> None:
    if browser.table.is_notes_mode():
        tooltip(MODE_SELECTION_MESSAGE)
        return

    card = browser.table.get_single_selected_card()
    if not card:
        tooltip(MODE_SELECTION_MESSAGE)
        return

    markdown = build_markdown_from_note(card.note())
    if not markdown:
        tooltip(NO_FIELDS_MESSAGE)
        return

    QGuiApplication.clipboard().setText(markdown)
    tooltip(SUCCESS_MESSAGE)


def add_browser_action(browser, menu) -> None:
    action = QAction(ACTION_TEXT, browser)
    action.triggered.connect(lambda _checked=False, b=browser: copy_selected_note_fields(b))
    menu.addAction(action)


def install_browser_action() -> None:
    gui_hooks.browser_will_show_context_menu.append(add_browser_action)


install_browser_action()
