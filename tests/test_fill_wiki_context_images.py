import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fill_wiki_context_images.py"
spec = importlib.util.spec_from_file_location("fill_wiki_context_images", SCRIPT)
wiki = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wiki
spec.loader.exec_module(wiki)


class FillWikiContextImagesTests(unittest.TestCase):
    def test_find_wiki_image_uses_exact_page_before_search(self):
        calls = []
        exact = wiki.WikiImage(
            "Battle of Hastings", "https://x/thumb.jpg", "https://x/page"
        )

        def fake_thumb(title, size):
            calls.append(("thumb", title, size))
            return exact

        with (
            patch.object(wiki, "wiki_thumb_info", fake_thumb),
            patch.object(
                wiki,
                "wiki_search_top_title",
                side_effect=AssertionError("should not search"),
            ),
        ):
            self.assertEqual(wiki.find_wiki_image("Battle of Hastings", 260), exact)

        self.assertEqual(calls, [("thumb", "Battle of Hastings", 260)])

    def test_find_wiki_image_falls_back_to_top_search_result(self):
        result = wiki.WikiImage(
            "Treaty of Versailles", "https://x/thumb.webp", "https://x/page"
        )

        def fake_thumb(title, size):
            if title == "messy wording":
                return None
            if title == "Treaty of Versailles":
                return result
            raise AssertionError(title)

        with (
            patch.object(wiki, "wiki_thumb_info", fake_thumb),
            patch.object(
                wiki,
                "wiki_search_top_title",
                return_value="Treaty of Versailles",
            ),
        ):
            self.assertEqual(wiki.find_wiki_image("messy wording", 260), result)

    def test_lookup_candidates_prefers_bold_terms_over_context(self):
        fields = {
            "Question": "Why did <b>Normandy landings</b> succeed despite German defenses?",
            "Answer": "<b>Operation Fortitude</b> fooled Hitler.",
            "Context": "D-Day",
        }

        self.assertEqual(
            wiki.lookup_candidates(fields, {}, "")[:3],
            ["Normandy landings", "Operation Fortitude", "German"],
        )
        self.assertEqual(wiki.lookup_candidates(fields, {}, "")[-1], "D-Day")

    def test_lookup_candidates_title_map_overrides_any_matching_field_value(self):
        fields = {
            "Question": "What shaped Churchill's resistance?",
            "Answer": "Failed 1942 Dieppe Raid and WWI trench-slaughter memory.",
            "Context": "D-Day",
        }

        candidates = wiki.lookup_candidates(fields, {"D-Day": "Normandy landings"}, "")

        self.assertEqual(candidates[0], "Normandy landings")

    def test_image_extension_defaults_to_jpg_when_url_has_no_known_suffix(self):
        self.assertEqual(
            wiki.image_extension("https://upload.wikimedia.org/thumb/foo"), ".jpg"
        )
        self.assertEqual(
            wiki.image_extension("https://upload.wikimedia.org/foo.png?width=260"),
            ".png",
        )


if __name__ == "__main__":
    unittest.main()
