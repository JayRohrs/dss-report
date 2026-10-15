"""Nothing real in the repository: no app/tenant IDs, no real-looking addresses, no private mapping."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__"}
TEXT = {".py", ".md", ".toml", ".cmd", ".pyw", ".json", ".csv", ".txt", ".html", ""}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
FAKE_DOMAINS = ("example.invalid", "company.example", "your-company.example", "example.com", "example.org")


def files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.parts) & SKIP_DIRS) and p.suffix.lower() in TEXT:
            yield p


class Hygiene(unittest.TestCase):
    def test_only_obviously_fake_email_addresses(self):
        for p in files():
            for m in EMAIL.finditer(p.read_text(errors="ignore")):
                self.assertTrue(m.group(1).lower().endswith(FAKE_DOMAINS), f"{p}: {m.group(0)}")

    def test_no_guid_shaped_ids_anywhere(self):
        for p in files():
            self.assertIsNone(GUID.search(p.read_text(errors="ignore")), f"{p} contains a GUID-shaped id")

    def test_shipped_mapping_template_is_empty(self):
        import tomllib
        raw = tomllib.loads((ROOT / "r365_mapping.example.toml").read_text())
        for section in ("source", "fields"):
            for key, value in raw[section].items():
                if key != "date_literal":
                    self.assertEqual(value, "", f"{section}.{key} must ship empty")
        for key, value in raw["values"].items():
            self.assertEqual(value, [], key)
        self.assertEqual(raw["payments"], {})

    def test_no_private_mapping_or_settings_files_in_the_repo(self):
        for name in ("r365_mapping.toml", "settings.json", "state.json"):
            self.assertFalse((ROOT / name).exists(), name)
        ignore = (ROOT / ".gitignore").read_text()
        for name in ("r365_mapping.toml", "settings.json", "state.json"):
            self.assertIn(name, ignore)

    def test_settings_have_no_default_app_id_tenant_or_address(self):
        from dssreport.settings import Settings
        s = Settings()
        self.assertEqual((s.graph_client_id, s.email_to, s.instances), ("", "", []))
        self.assertEqual(s.graph_tenant, "organizations")   # a Microsoft keyword, not a tenant


if __name__ == "__main__":
    unittest.main()
