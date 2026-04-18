import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_addon.py"


class BuildAddonPackageTests(unittest.TestCase):
    def test_build_script_creates_clean_zip_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["python3", str(BUILD_SCRIPT), "--output-dir", tmpdir],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)

            zip_path = Path(result.stdout.strip())
            self.assertTrue(zip_path.exists(), msg=result.stdout)

            with zipfile.ZipFile(zip_path) as zf:
                names = set(zf.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("__init__.py", names)
                self.assertIn("export.py", names)
                self.assertIn("README.md", names)
                self.assertNotIn("__pycache__/__init__.cpython-314.pyc", names)

                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["package"], "copy_note_fields_markdown")
                self.assertEqual(manifest["name"], "Copy Note Fields as Markdown")


if __name__ == "__main__":
    unittest.main()
