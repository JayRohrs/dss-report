"""The Windows installer can't run on this (non-Windows) test machine. These checks only catch
careless mistakes; the real proof is running it on Windows (see the PR notes)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class InstallerFiles(unittest.TestCase):
    def test_batch_files_use_windows_line_endings(self):
        for name in ("install-windows.cmd", "uninstall-windows.cmd"):
            raw = (ROOT / name).read_bytes()
            self.assertIn(b"\r\n", raw, name)
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), f"{name} has bare LF line endings")

    def test_installer_downloads_nothing_itself_and_needs_no_admin(self):
        text = (ROOT / "install-windows.cmd").read_text().lower()
        for bad in ("invoke-webrequest", "curl ", "bitsadmin", "downloadfile", "runas", "-verb"):
            self.assertNotIn(bad, text)
        self.assertIn("winget install", text)       # the only way it gets Python
        self.assertIn("--scope user", text)
        self.assertIn("%localappdata%", text)       # per-user, no admin rights

    def test_every_goto_and_call_label_exists(self):
        import re
        for name in ("install-windows.cmd",):
            text = (ROOT / name).read_text()
            labels = set(re.findall(r"^:(\w+)", text, re.M))
            used = set(re.findall(r"(?:goto|call)\s+:(\w+)", text, re.I))
            self.assertLessEqual(used, labels, name)

    def test_launcher_runs_a_command_without_a_console_dependency(self):
        out = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, str(ROOT / "launcher.pyw"), "demo-data", "--out", out],
                           capture_output=True, text=True, cwd=tempfile.mkdtemp())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((Path(out) / "dss_demo.csv").exists())


if __name__ == "__main__":
    unittest.main()
