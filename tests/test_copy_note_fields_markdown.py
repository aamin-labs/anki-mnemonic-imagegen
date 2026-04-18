import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "addons" / "copy_note_fields_markdown" / "export.py"


def load_export_module():
    anki_module = types.ModuleType("anki")
    utils_module = types.ModuleType("anki.utils")

    def strip_html_media(value: str) -> str:
        value = re.sub(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>', r"\1", value)
        value = re.sub(r"\[sound:([^\]]+)\]", r"\1", value)
        value = value.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        value = re.sub(r"</?(div|p)[^>]*>", "\n", value)
        value = re.sub(r"<[^>]+>", "", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value

    utils_module.strip_html_media = strip_html_media
    anki_module.utils = utils_module
    sys.modules["anki"] = anki_module
    sys.modules["anki.utils"] = utils_module

    spec = importlib.util.spec_from_file_location("copy_note_fields_markdown_export", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DummyNote:
    def __init__(self, fields):
        self._fields = fields

    def items(self):
        return list(self._fields)


class BuildMarkdownFromNoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_export_module()

    def test_preserves_field_order_and_skips_empty_fields(self):
        note = DummyNote(
            [
                ("Front", "Paris"),
                ("Back", "<b>France</b>"),
                ("Extra", "   "),
            ]
        )

        markdown = self.module.build_markdown_from_note(note)

        self.assertEqual(markdown, "## Front\n\nParis\n\n## Back\n\nFrance\n")

    def test_keeps_plain_media_filenames_in_output(self):
        note = DummyNote(
            [
                ("Media", '<img src="map.png"> [sound:ping.mp3]'),
            ]
        )

        markdown = self.module.build_markdown_from_note(note)

        self.assertEqual(markdown, "## Media\n\nmap.png ping.mp3\n")

    def test_returns_empty_string_when_all_fields_clean_to_empty(self):
        note = DummyNote(
            [
                ("Front", "   "),
                ("Back", "<div><br></div>"),
            ]
        )

        markdown = self.module.build_markdown_from_note(note)

        self.assertEqual(markdown, "")


if __name__ == "__main__":
    unittest.main()
