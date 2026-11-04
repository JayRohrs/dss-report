"""Careless-mistake checks for the packaging files. Real proof is running the installer on Windows."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"


class PackagingFiles(unittest.TestCase):
    def test_cmd_files_have_windows_line_endings(self):
        for p in [PKG / "build_windows.cmd", *(PKG / "shortcuts").glob("*.cmd")]:
            raw = p.read_bytes()
            self.assertIn(b"\r\n", raw, p.name)
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), p.name)

    def test_installer_schedule_tick_is_off_by_default_and_needs_no_admin(self):
        iss = (PKG / "installer.iss").read_text()
        self.assertRegex(iss, r'Name: "dailyon";[^\n]*Flags: unchecked')
        self.assertIn("PrivilegesRequired=lowest", iss)
        run = re.search(r"\[Run\](.*?)(\n\[|\Z)", iss, re.S).group(1)
        self.assertEqual(len(re.findall(r"Filename:", run)), 1)
        self.assertIn("Tasks: dailyon", run)                    # only if ticked
        self.assertIn("schedule off", iss)                      # uninstall removes the task

    def test_installer_never_turns_on_email_drafts(self):
        text = (PKG / "installer.iss").read_text().lower()
        self.assertNotIn("draft on", text)

    def test_every_shortcut_the_installer_names_exists(self):
        iss = (PKG / "installer.iss").read_text()
        names = re.findall(r'\{app\}\\shortcuts\\([^"]+\.cmd)"', iss)
        self.assertEqual(len(names), 5)
        for name in names:
            self.assertTrue((PKG / "shortcuts" / name).exists(), name)

    def test_build_uses_pinned_open_tools(self):
        self.assertRegex((PKG / "requirements-build.txt").read_text(), r"(?m)^pyinstaller==\d+\.\d+\.\d+$")
        build = (PKG / "build_windows.cmd").read_text()
        self.assertIn("python -m PyInstaller", build)
        self.assertIn("iscc", build)

    def test_spec_bundles_the_data_the_program_reads(self):
        spec = (PKG / "dss-report.spec").read_text()
        self.assertIn("dssreport/data", spec)
        self.assertIn("rules.toml", spec)
        self.assertTrue((ROOT / "dssreport" / "data" / "reason_terms.toml").exists())

    def test_docs_exist_and_list_scopes(self):
        for name in ("BUILD_WINDOWS.md", "GRAPH_PERMISSIONS.md", "INSTALL_WINDOWS_OWNER.md"):
            self.assertTrue((ROOT / "docs" / name).exists(), name)
        g = (ROOT / "docs" / "GRAPH_PERMISSIONS.md").read_text()
        self.assertIn("Mail.ReadWrite", g)
        self.assertIn("offline_access", g)
        self.assertRegex(g, r"Mail\.Send[^\n]*Never requested")


if __name__ == "__main__":
    unittest.main()
