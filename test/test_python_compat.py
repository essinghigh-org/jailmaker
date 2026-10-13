"""Host-independent regression checks across supported TrueNAS Python versions."""

import io
import subprocess
import sys
import unittest
from pathlib import Path

from jlmkr import KeyValueParser

ROOT = Path(__file__).resolve().parents[1]


class KeyValueParserCompatibilityTests(unittest.TestCase):
    def test_default_configuration(self):
        parser = KeyValueParser()
        parser.read_default_string("startup=0\n# ignored\nseccomp=1\n")
        self.assertEqual(parser.get("DEFAULT", "startup"), "0")
        self.assertEqual(parser.get("DEFAULT", "seccomp"), "1")

    def test_preserves_comments_and_multiline_values(self):
        source = (
            "# Top-level comment\n"
            "startup=1\n"
            "# Preserve this note\n"
            "systemd_nspawn_user_args=--boot\n"
            "    --keep-unit\n"
            "\n"
            "# Trailing comment\n"
        )
        parser = KeyValueParser()
        parser.read_file(io.StringIO(source), source="test config")
        self.assertEqual(parser.my_get("startup"), "1")
        self.assertEqual(
            parser.my_get("systemd_nspawn_user_args"),
            "--boot\n--keep-unit",
        )

        out = io.StringIO()
        parser.write(out)
        rendered = out.getvalue()
        self.assertIn("# Top-level comment", rendered)
        self.assertIn("# Preserve this note", rendered)
        self.assertIn("# Trailing comment", rendered)
        self.assertLess(rendered.index("# Preserve this note"), rendered.index("systemd_nspawn_user_args"))
        self.assertIn("--keep-unit", rendered)

        reread = KeyValueParser()
        reread.read_file(io.StringIO(rendered))
        self.assertEqual(
            reread.my_get("systemd_nspawn_user_args"),
            parser.my_get("systemd_nspawn_user_args"),
        )

    def test_boolean_setter(self):
        parser = KeyValueParser()
        parser.read_file(io.StringIO("startup=0\n"))
        parser.my_set("startup", True)
        self.assertTrue(parser.my_getboolean("startup"))
        parser.my_set("startup", False)
        self.assertFalse(parser.my_getboolean("startup"))


class CommandLineCompatibilityTests(unittest.TestCase):
    def test_module_imports_without_deprecation_warnings(self):
        # Running the CLI requires a root-owned script. Importing is safe on
        # ordinary CI runners and catches warnings during module initialisation.
        result = subprocess.run(
            [sys.executable, "-W", "error::DeprecationWarning", "-c", "import jlmkr"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr) 


if __name__ == "__main__":
    unittest.main()
