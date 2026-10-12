"""Each rule fires on the planted demo exceptions, and missing data is never clean."""

import unittest
from datetime import date
from decimal import Decimal

from dssreport import rules
from dssreport.config import Config
from dssreport.report import NEEDS_REVIEW, UNKNOWN_STATUS, build_report, reasons

from .helpers import CFG, demo_report, planted, rec, result, rules_fired


class PlantedExceptions(unittest.TestCase):
    def test_missing_pos_import(self):
        loc, day = planted("pos_missing_cash_blank")
        r = demo_report(day)
        self.assertIn(rules.POS_IMPORT, rules_fired(r, loc))
        self.assertEqual(result(r, loc).status, NEEDS_REVIEW)

    def test_cash_short_missing_receipts_unapproved(self):
        loc, day = planted("cash_short_receipts_unapproved")
        r = demo_report(day)
        self.assertEqual(rules_fired(r, loc), {rules.CASH, rules.RECEIPTS, rules.UNAPPROVED})
        text = " ".join(reasons(result(r, loc), False))
        self.assertIn("$23.50 short", text)
        self.assertIn("2 receipts missing", text)

    def test_payment_exceptions(self):
        loc, day = planted("payment_exceptions")
        self.assertEqual(rules_fired(demo_report(day), loc), {rules.EXCEPTIONS})

    def test_cash_over(self):
        loc, day = planted("cash_over")
        r = demo_report(day)
        self.assertEqual(rules_fired(r, loc), {rules.CASH})
        self.assertIn("$12.00 over", " ".join(reasons(result(r, loc), False)))

    def test_single_missing_receipt(self):
        loc, day = planted("missing_receipt")
        self.assertEqual(rules_fired(demo_report(day), loc), {rules.RECEIPTS})

    def test_no_data_day(self):
        loc, day = planted("no_row")
        r = demo_report(day)
        res = result(r, loc)
        self.assertEqual(rules_fired(r, loc), {rules.NO_DATA})
        self.assertEqual(res.status, UNKNOWN_STATUS)
        self.assertIn(res, r.attention)

    def test_clean_location_is_nothing_to_review(self):
        loc, day = planted("clean_day")
        r = demo_report(day)
        self.assertIn(loc, [x.name for x in r.clear])
        self.assertEqual(r.headline, "3 of 4 locations need a look for 2026-03-13. "
                                     "1 has nothing to review. 1 location is UNKNOWN because data is missing.")

    def test_quiet_days_have_nothing_flagged(self):
        r = demo_report(date(2026, 3, 1))
        self.assertEqual(r.attention, [])
        self.assertEqual(len(r.clear), 4)


class MissingDataIsNeverClean(unittest.TestCase):
    def test_blank_cash_is_unknown_not_zero(self):
        loc, day = planted("cash_blank")
        r = demo_report(day)
        res = result(r, loc)
        self.assertEqual(res.status, UNKNOWN_STATUS)
        self.assertIn(res, r.attention)
        self.assertIn("UNKNOWN: Cash over/short is blank", reasons(res, False))
        self.assertIn("UNKNOWN", r.headline)

    def test_every_blank_field_is_unknown(self):
        for field in ("sales_total", "cash_over_short", "missing_receipts",
                      "payment_exceptions", "approved", "pos_import_received"):
            findings = rules.evaluate_day("X", date(2026, 1, 5), rec(**{field: None}), CFG)
            self.assertTrue(findings, field)
            self.assertTrue(all(f.kind == rules.UNKNOWN for f in findings), field)

    def test_all_blank_record_is_not_clean(self):
        blank = rec(sales_total=None, cash_over_short=None, missing_receipts=None,
                    payment_exceptions=None, approved=None, pos_import_received=None)
        report = build_report([blank], CFG)
        self.assertEqual(report.clear, [])
        self.assertEqual(report.attention[0].status, UNKNOWN_STATUS)

    def test_complete_good_record_is_clean(self):
        self.assertEqual(rules.evaluate_day("X", date(2026, 1, 5), rec(), CFG), [])

    def test_disabling_a_rule_cannot_hide_no_data(self):
        cfg = Config(pos_enabled=False, cash_enabled=False, receipts_enabled=False,
                     exceptions_enabled=False, unapproved_enabled=False)
        loc, day = planted("no_row")
        r = demo_report(day, cfg=cfg)
        self.assertEqual(rules_fired(r, loc), {rules.NO_DATA})

    def test_expected_location_with_no_records_is_unknown(self):
        cfg = Config(expected=["Never Sent Data Cafe"])
        r = build_report([rec()], cfg)
        res = result(r, "Never Sent Data Cafe")
        self.assertEqual(res.status, UNKNOWN_STATUS)
        self.assertNotIn(res, r.clear)

    def test_date_with_no_data_at_all_is_not_clean(self):
        r = demo_report(date(2026, 4, 1))
        self.assertEqual(r.clear, [])
        self.assertEqual(len(r.attention), 4)
        self.assertNotIn("Nothing to review: all", r.headline)

    def test_no_records_and_no_locations_is_unknown(self):
        r = build_report([], CFG, end=date(2026, 1, 5))
        self.assertIn("UNKNOWN", r.headline)
        self.assertNotIn("Nothing to review", r.headline)

    def test_pos_missing_does_not_hide_other_problems(self):
        f = rules.evaluate_day("X", date(2026, 1, 5),
                               rec(pos_import_received=False, sales_total=None, approved=False), CFG)
        self.assertEqual({x.rule for x in f}, {rules.POS_IMPORT, rules.UNAPPROVED})


class Thresholds(unittest.TestCase):
    def test_cash_limit_is_exceeded_only_above(self):
        at = rules.evaluate_day("X", date(2026, 1, 5), rec(cash_over_short=Decimal("-5.00")), CFG)
        over = rules.evaluate_day("X", date(2026, 1, 5), rec(cash_over_short=Decimal("-5.01")), CFG)
        self.assertEqual(at, [])
        self.assertEqual([f.rule for f in over], [rules.CASH])

    def test_limits_come_from_config(self):
        cfg = Config(cash_limit=Decimal("50"), receipts_allowed=2)
        f = rules.evaluate_day("X", date(2026, 1, 5),
                               rec(cash_over_short=Decimal("-23.50"), missing_receipts=2), cfg)
        self.assertEqual(f, [])

    def test_multi_day_window_reports_each_date(self):
        r = demo_report(date(2026, 3, 13), days=5)  # Mar 9..13
        rules_seen = {(f.business_date.day, f.rule) for x in r.attention for f in x.findings}
        self.assertIn((9, rules.CASH), rules_seen)
        self.assertIn((10, rules.CASH), rules_seen)
        self.assertIn((11, rules.EXCEPTIONS), rules_seen)
        self.assertIn((13, rules.NO_DATA), rules_seen)
        self.assertIn((13, rules.POS_IMPORT), rules_seen)
        self.assertEqual([x.name for x in r.clear], [])
        self.assertIn("Demo Diner West", [x.name for x in r.attention])  # blank cash on Mar 9


if __name__ == "__main__":
    unittest.main()
