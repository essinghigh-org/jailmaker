"""Isolated, interactive smoke tests for install.sh without touching real pools."""
import os
import pathlib
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        self.mount = self.base / "mnt"
        self.mount.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()

        # The test copy redirects /mnt while leaving the shipping script intact.
        contents = (ROOT / "install.sh").read_text().replace(
            'destination="/mnt/$dataset"',
            'destination="$JLMKR_TEST_DEST/$dataset"',
        )
        self.installer = self.base / "install.sh"
        self.installer.write_text(contents)

        (bin_dir / "sudo").write_text(
            '#!/bin/sh\n'
            'if [ "$1" = chown ]; then exit 0; fi\n'
            'exec "$@"\n'
        )
        (bin_dir / "getent").write_text(
            '#!/bin/sh\n'
            'printf "%s:x:1000:1000::%s:/bin/bash\\n" "$2" "$MOCK_HOME"\n'
        )
        (bin_dir / "midclt").write_text(
            '#!/bin/sh\n'
            'case "$2" in\n'
            '  pool.query) echo \'[{"name":"data","status":"ONLINE"},'
            '{"name":"nvme","status":"ONLINE"}]\' ;;\n'
            '  pool.dataset.create)\n'
            '    name=$(printf "%s" "$3" | python3 -c '
            '\'import json,sys; print(json.load(sys.stdin)["name"])\')\n'
            '    mkdir -p "$JLMKR_TEST_DEST/$name" ;;\n'
            '  pool.dataset.delete)\n'
            '    rmdir "$JLMKR_TEST_DEST/$3" ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n'
        )
        (bin_dir / "git").write_text(
            '#!/bin/sh\n'
            'for dest; do :; done\n'
            'if [ "${MOCK_GIT_FAIL:-}" = empty ]; then exit 1; fi\n'
            'if [ "${MOCK_GIT_FAIL:-}" = partial ]; then\n'
            '  touch "$dest/partial"; exit 1\n'
            'fi\n'
            'mkdir -p "$dest/completions"\n'
            'touch "$dest/jlmkr.py"\n'
            'cp "$MOCK_SOURCE/completions/jlmkr.bash" "$dest/completions/"\n'
            'cp "$MOCK_SOURCE/completions/jlmkr.zsh" "$dest/completions/"\n'
        )
        for file in bin_dir.iterdir():
            file.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            JLMKR_TEST_DEST=str(self.mount),
            MOCK_HOME=str(self.home),
            MOCK_SOURCE=str(ROOT),
        )

    def run_interactive(self, steps):
        pid, master = pty.fork()
        if pid == 0:
            os.execvpe(
                "bash",
                ["bash", "-c", f"cat {self.installer} | bash -s -- --ref feat/interactive-installer"],
                self.env,
            )
        output = b""
        try:
            for prompt, reply in steps:
                deadline = time.monotonic() + 15
                while prompt.encode() not in output:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.fail(f"Prompt {prompt!r} missing: {output[-800:]!r}")
                    ready, _, _ = select.select([master], [], [], remaining)
                    if ready:
                        try:
                            output += os.read(master, 4096)
                        except OSError:
                            break
                output = b""
                os.write(master, reply)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        output += os.read(master, 4096)
                    except OSError:
                        break
                ended, status = os.waitpid(pid, os.WNOHANG)
                if ended:
                    return os.waitstatus_to_exitcode(status), output.decode(errors="replace")
            ended, status = os.waitpid(pid, os.WNOHANG)
            if ended:
                return os.waitstatus_to_exitcode(status), output.decode(errors="replace")
            self.fail(f"Installer did not exit: {output[-1200:]!r}")
        finally:
            os.close(master)
            # Child will have exited normally unless the test timed out.
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass

    def test_choose_second_pool_and_clone(self):
        code, out = self.run_interactive([
            ("Selected:", b"2\n"),
            ("Dataset name", b"trial\n"),
            ("Continue?", b"\n"),
            ("Set up", b"n\n"),
        ])
        self.assertEqual(code, 0, out)
        self.assertTrue((self.mount / "nvme" / "trial" / "jlmkr.py").exists())
        self.assertIn("Installation complete", out)

    def test_shell_configuration_stays_in_test_home(self):
        code, out = self.run_interactive([
            ("Selected:", b"1\n"),
            ("Dataset name", b"\n"),
            ("Continue?", b"\n"),
            ("Set up", b"y\n"),
        ])
        self.assertEqual(code, 0, out)
        rc = (self.home / ".bashrc").read_text()
        self.assertIn('jlmkr() { sudo -E "$JLMKR_HOME/jlmkr.py" "$@"; }', rc)
        self.assertIn('source "$JLMKR_HOME/completions/jlmkr.bash"', rc)

    def test_failed_clone_removes_only_empty_dataset(self):
        self.env["MOCK_GIT_FAIL"] = "empty"
        code, out = self.run_interactive([
            ("Selected:", b"1\n"),
            ("Dataset name", b"\n"),
            ("Continue?", b"\n"),
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("removed the empty dataset", out)
        self.assertFalse((self.mount / "data" / "jailmaker").exists())

    def test_failed_clone_keeps_nonempty_dataset(self):
        self.env["MOCK_GIT_FAIL"] = "partial"
        code, out = self.run_interactive([
            ("Selected:", b"1\n"),
            ("Dataset name", b"\n"),
            ("Continue?", b"\n"),
        ])
        self.assertNotEqual(code, 0)
        self.assertIn("retained dataset", out)
        self.assertTrue((self.mount / "data" / "jailmaker" / "partial").exists())

    def test_cancel_before_dataset_creation(self):
        code, out = self.run_interactive([
            ("Selected:", b"\x1b[B\n"),
            ("Dataset name", b"\n"),
            ("Continue?", b"n\n"),
        ])
        self.assertEqual(code, 0, out)
        self.assertFalse((self.mount / "nvme" / "jailmaker").exists())


if __name__ == "__main__":
    unittest.main()
