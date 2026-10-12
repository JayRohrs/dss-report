import json
import tempfile
import unittest
from pathlib import Path

from dssreport.adapters import build_adapter
from dssreport.adapters.demo import generate, write_demo_files
from dssreport.config import load_config, parse_config
from dssreport.errors import ConfigError, InputError

ROOT = Path(__file__).resolve().parent.parent
HEADER = ("location,business_date,sales_total,pay_cash,cash_over_short,missing_receipts,"
          "payment_exceptions,approved,pos_import_received\n")


class Adapters(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def csv(self, body, name="a.csv"):
        p = self.tmp / name
        p.write_text(HEADER + body, encoding="utf-8")
        return p

    def test_demo_has_4_locations_14_days(self):
        recs = generate()
        self.assertEqual(len({r.location for r in recs}), 4)
        self.assertEqual(len({r.business_date for r in recs}), 14)
        self.assertEqual(len(recs), 4 * 14 - 1)  # one planted no-data day

    def test_csv_and_json_demo_files_round_trip(self):
        write_demo_files(self.tmp)
        self.assertEqual(build_adapter(str(self.tmp / "dss_demo.csv")).load(), generate())
        self.assertEqual(build_adapter(str(self.tmp / "dss_demo.json")).load(), generate())

    def test_committed_example_files_match_generator(self):
        self.assertEqual(build_adapter(str(ROOT / "examples/demo/dss_demo.csv")).load(), generate())

    def test_blank_cells_are_none_not_zero(self):
        p = self.csv("A,2026-01-05,,, , , , ,\n")
        r = build_adapter(str(p)).load()[0]
        self.assertIsNone(r.sales_total)
        self.assertIsNone(r.cash_over_short)
        self.assertIsNone(r.missing_receipts)
        self.assertIsNone(r.approved)
        self.assertIsNone(r.pos_import_received)

    def test_money_with_symbols(self):
        p = self.csv('A,2026-01-05,"$1,200.50",,-3.25,0,0,Yes,No\n')
        r = build_adapter(str(p)).load()[0]
        self.assertEqual(str(r.sales_total), "1200.50")
        self.assertIs(r.approved, True)
        self.assertIs(r.pos_import_received, False)

    def test_bad_values_are_errors_with_location(self):
        for body, needle in [("A,not-a-date,1,,0,0,0,yes,yes\n", "business_date"),
                             ("A,2026-01-05,abc,,0,0,0,yes,yes\n", "sales_total"),
                             ("A,2026-01-05,1,,0,1.5,0,yes,yes\n", "missing_receipts"),
                             ("A,2026-01-05,1,,0,0,0,maybe,yes\n", "approved")]:
            with self.assertRaises(InputError) as cm:
                build_adapter(str(self.csv(body))).load()
            self.assertIn(needle, str(cm.exception))
            self.assertIn("line 2", str(cm.exception))

    def test_duplicate_rows_are_an_error(self):
        p = self.csv("A,2026-01-05,1,,0,0,0,yes,yes\nA,2026-01-05,2,,0,0,0,yes,yes\n")
        with self.assertRaises(InputError):
            build_adapter(str(p)).load()

    def test_unrecognised_column_warns(self):
        p = self.tmp / "b.csv"
        p.write_text("location,business_date,cash_ovr_short\nA,2026-01-05,3\n")
        a = build_adapter(str(p))
        a.load()
        self.assertTrue(any("cash_ovr_short" in w for w in a.warnings))

    def test_json_records(self):
        p = self.tmp / "a.json"
        p.write_text(json.dumps([{"location": "A", "business_date": "2026-01-05",
                                  "payments": {"cash": 5}, "approved": None}]))
        r = build_adapter(str(p)).load()[0]
        self.assertIsNone(r.approved)
        self.assertEqual(str(r.payments["cash"]), "5")

    def test_folder_and_missing_input(self):
        self.csv("A,2026-01-05,1,,0,0,0,yes,yes\n")
        self.assertEqual(len(build_adapter(str(self.tmp)).load()), 1)
        with self.assertRaises(InputError):
            build_adapter(str(self.tmp / "nope.csv")).load()


class Config(unittest.TestCase):
    def test_shipped_rules_file_loads(self):
        cfg = load_config(ROOT / "rules.toml")
        self.assertFalse(cfg.ai_enabled)  # AI is off by default
        self.assertEqual(str(cfg.cash_limit), "5.0")

    def test_typo_is_an_error_not_silently_ignored(self):
        with self.assertRaises(ConfigError):
            parse_config({"rules": {"cash_variance": {"limt": 3}}})
        with self.assertRaises(ConfigError):
            parse_config({"rules": {"cash_varience": {}}})

    def test_bad_types(self):
        for raw in ({"rules": {"cash_variance": {"limit": "lots"}}},
                    {"rules": {"missing_receipts": {"allowed": -1}}},
                    {"rules": {"unapproved_entry": {"enabled": "yes"}}}):
            with self.assertRaises(ConfigError):
                parse_config(raw)


if __name__ == "__main__":
    unittest.main()
