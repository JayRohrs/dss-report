"""Phase 2 rule behaviour: approval off by default, optional payments check, needs mapping."""

import unittest
from datetime import date
from decimal import Decimal

from dssreport import rules
from dssreport.config import Config
from dssreport.render import render_html, render_text
from dssreport.report import build_report

from .helpers import demo_report, planted, rec


class ApprovalOffByDefault(unittest.TestCase):
    def test_default_config_has_approval_and_payments_checks_off(self):
        cfg = Config()
        self.assertFalse(cfg.unapproved_enabled)
        self.assertFalse(cfg.payments_enabled)

    def test_unapproved_entry_is_not_flagged_when_off(self):
        f = rules.evaluate_day("X", date(2026, 1, 5), rec(approved=False), Config())
        self.assertEqual(f, [])

    def test_report_says_approval_is_switched_off(self):
        r = build_report([rec(approved=False)], Config())
        self.assertIn("Approval: switched off", r.rules_note)


class PaymentsTotal(unittest.TestCase):
    cfg = Config(payments_enabled=True)

    def test_fires_on_planted_mismatch(self):
        loc, day = planted("payments_dont_add_up")
        r = demo_report(day, cfg=self.cfg)
        found = [f for x in r.attention if x.name == loc for f in x.findings]
        self.assertEqual([f.rule for f in found], [rules.PAYMENTS_TOTAL])
        self.assertIn("add up to", found[0].text)

    def test_quiet_when_off_by_default(self):
        loc, day = planted("payments_dont_add_up")
        r = demo_report(day, cfg=Config())
        self.assertEqual([x.name for x in r.attention], [])

    def test_matching_payments_are_fine_within_tolerance(self):
        ok = rec(sales_total=Decimal("100.00"), payments={"cash": Decimal("60"), "card": Decimal("40.01")})
        self.assertEqual(rules.evaluate_day("X", date(2026, 1, 5), ok, self.cfg), [])
        bad = rec(sales_total=Decimal("100.00"), payments={"cash": Decimal("60"), "card": Decimal("40.02")})
        self.assertEqual([f.rule for f in rules.evaluate_day("X", date(2026, 1, 5), bad, self.cfg)],
                         [rules.PAYMENTS_TOTAL])

    def test_blank_payment_is_unknown_not_a_match(self):
        r = rec(sales_total=Decimal("100"), payments={"cash": Decimal("100"), "card": None})
        f = rules.evaluate_day("X", date(2026, 1, 5), r, self.cfg)
        self.assertEqual([(x.rule, x.kind) for x in f], [(rules.PAYMENTS_TOTAL, rules.UNKNOWN)])


class NeedsMapping(unittest.TestCase):
    cfg = Config(unapproved_enabled=True, payments_enabled=True)
    unmapped = frozenset({"approved", "cash_over_short", "payments"})

    def test_rule_with_unmapped_field_is_skipped_not_unknown_per_row(self):
        f = rules.evaluate_day("X", date(2026, 1, 5), rec(approved=None, cash_over_short=None),
                               self.cfg, self.unmapped)
        self.assertEqual(f, [])

    def test_status_values(self):
        self.assertEqual(rules.rule_status(self.cfg, rules.UNAPPROVED, self.unmapped), rules.NEEDS_MAPPING)
        self.assertEqual(rules.rule_status(self.cfg, rules.POS_IMPORT, self.unmapped), rules.ON)
        self.assertEqual(rules.rule_status(Config(), rules.UNAPPROVED, self.unmapped), rules.OFF)

    def test_report_shows_needs_mapping_and_never_claims_full_all_clear(self):
        r = build_report([rec()], self.cfg, unmapped=self.unmapped)
        self.assertEqual(set(r.needs_mapping), {"Approval", "Cash over/short", "Payments add up to sales"})
        self.assertNotIn("Nothing to review: all", r.headline)
        self.assertIn("needs mapping", r.headline)
        for text in (render_html(r), render_text(r)):
            self.assertIn("needs mapping", text.lower())
            self.assertIn("Cash over/short", text)

    def test_disabled_rule_is_not_listed_as_needing_mapping(self):
        r = build_report([rec()], Config(), unmapped=self.unmapped)
        self.assertNotIn("Approval", r.needs_mapping)


class IncludeList(unittest.TestCase):
    def test_include_restricts_and_unknown_if_silent(self):
        recs = [rec(location="A"), rec(location="B")]
        r = build_report(recs, Config(include=["A", "C"]))
        self.assertEqual([x.name for x in r.clear], ["A"])
        self.assertEqual([(x.name, x.status) for x in r.attention], [("C", "UNKNOWN")])


class DuplicateMessage(unittest.TestCase):
    def test_message_names_location_day_and_fix(self):
        import tempfile
        from pathlib import Path
        from dssreport.adapters import build_adapter
        from dssreport.errors import InputError
        p = Path(tempfile.mkdtemp()) / "a.csv"
        p.write_text("location,business_date,sales_total\nDemo A,2026-01-05,1\nDemo A,2026-01-05,2\n")
        with self.assertRaises(InputError) as cm:
            build_adapter(str(p)).load()
        msg = str(cm.exception)
        for needle in ("Demo A", "2026-01-05", "line 2", "line 3", "Delete one"):
            self.assertIn(needle, msg)


class DemoShowsUnknownByDefault(unittest.TestCase):
    def test_default_demo_report_has_no_data_day_and_blank_cash(self):
        from dssreport.adapters.demo import generate
        r = build_report(generate(), Config())  # defaults, latest day
        text = " ".join(f.text for x in r.attention for f in x.findings)
        self.assertIn("No data for this day", text)
        self.assertIn("Cash over/short is blank", text)
        self.assertIn("UNKNOWN", r.headline)


if __name__ == "__main__":
    unittest.main()
