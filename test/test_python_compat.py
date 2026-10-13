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

    def test_user_defined_comment_key_survives_round_trip(self):
        source = "__jlmkr_comment_0 = keep\n# note\n__jlmkr_comment_1 = retain\n"
        parser = KeyValueParser()
        parser.read_file(io.StringIO(source))
        out = io.StringIO()
        parser.write(out)
        self.assertIn("__jlmkr_comment_0=keep", out.getvalue())
        self.assertIn("__jlmkr_comment_1=retain", out.getvalue())
        self.assertIn("# note", out.getvalue())
        reread = KeyValueParser()
        reread.read_file(io.StringIO(out.getvalue()))
        self.assertEqual(reread.my_get("__jlmkr_comment_0"), "keep")
        self.assertEqual(reread.my_get("__jlmkr_comment_1"), "retain")

    def test_comment_key_collision_across_reads(self):
        parser = KeyValueParser()
        parser.read_file(io.StringIO("__jlmkr_comment_0=keep\n"))
        parser.read_file(io.StringIO("# note\n"))
        out = io.StringIO()
        parser.write(out)
        reread = KeyValueParser()
        reread.read_file(io.StringIO(out.getvalue()))
        self.assertEqual(reread.my_get("__jlmkr_comment_0"), "keep")
        self.assertIn("# note", out.getvalue())

    def test_comments_inside_multiline_script(self):
        source = (
            "initial_setup=#!/bin/sh\n"
            "    # Must remain in the script\n"
            "    echo ready\n"
        )
        parser = KeyValueParser()
        parser.read_file(io.StringIO(source))
        self.assertIn("# Must remain in the script", parser.my_get("initial_setup"))
        output = io.StringIO()
        parser.write(output)
        reread = KeyValueParser()
        reread.read_file(io.StringIO(output.getvalue()))
        self.assertEqual(reread.my_get("initial_setup"), parser.my_get("initial_setup"))

    def test_templates_round_trip(self):
        for path in (ROOT / "templates").glob("*/config"):
            with self.subTest(template=path.parent.name):
                source = path.read_text()
                keys = [line.split("=", 1)[0] for line in source.splitlines()
                        if line and not line[0].isspace() and not line.startswith("#") and "=" in line]
                first = KeyValueParser()
                first.read_file(io.StringIO(source))
                output = io.StringIO()
                first.write(output)
                second = KeyValueParser()
                second.read_file(io.StringIO(output.getvalue()))
                for key in keys:
                    self.assertEqual(first.my_get(key), second.my_get(key))

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
            [sys.executable, "-W", "error::DeprecationWarning", "-W", "error::PendingDeprecationWarning", "-c", "import jlmkr"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr) 


if __name__ == "__main__":
    unittest.main()
