"""The two real DSS list layouts the owner observed, with invented rows ("Sample ..." names, made-up amounts).
Headings, column order, byte-order mark, date and money formats are as observed; every value is made up."""

import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from dssreport import dss_export as E

TODAY = date(2026, 3, 14)
DAY = date(2026, 3, 13)
FRESH = datetime(2026, 3, 14, 7, 55)

CLASSIC_HEAD = ("ApprovalStatus,Status,Location,LocationNumber,Name,Date,NetSales,TotalDeposit,OverShort,GuestCount,"
                "StepsComplete,CreatedBy,CreatedOn,ModifiedBy,ModifiedOn,DailySalesSummaryId,PaidoutTotal,__count,"
                "NewFileName,Attachment,AttachmentLinkType,FileLink,LogEntries")
BETA_HEAD = "Status,Location,Date,Attachments,Net Sales,Total Labor $,Total Labor Hours,Labor %,Total Deposit,Over/Short,Guest Count"


FAKE_ID = "-".join(["0" * 8, "0000", "4000", "8000", "0" * 12])    # built here so no id-shaped text is in the repo


def classic(rows):
    n = len(rows)
    out = [CLASSIC_HEAD]
    for appr, status, loc, num, over in rows:
        out.append(f'{appr},{status},{loc},{num},"{loc} Friday, 03/13/2026",3/13/2026 12:00:00 AM,3000.0000,2910.0000,'
                   f'{over},90,Yes,,2026-03-14T08:15:00.0000000Z,Sample User,2026-03-14T09:00:00.0000000Z,'
                   f'{FAKE_ID},0.0000,{n},,,,,')
    return ("\r\n".join(out) + "\r\n").encode("utf-8")


def beta(rows):
    out = [BETA_HEAD]
    for status, loc, over in rows:
        out.append(f"{status},{loc},03/13/2026,No,100.0000,0.0000,0.0000000000,0,95.0000,{over},50")
    return ("﻿" + "\r\n".join(out) + "\r\n").encode("utf-8")


def parse(data, words=None, as_of=FRESH, expected=None):
    rows, stats, _ = E.read_rows(data, "x.csv")
    return E.parse_export(rows, E.load_aliases(user=Path("/nonexistent/a.toml")), words, as_of, TODAY, stats,
                          expected_total=expected) if expected is not None else \
        E.parse_export(rows, E.load_aliases(user=Path("/nonexistent/a.toml")), words, as_of, TODAY, stats)


class Classic(unittest.TestCase):
    def setUp(self):
        self.p = parse(classic([("Approved", "Approved", "Sample Pier Grill", 101, "-12.5000"),
                                ("Unapproved", "In Progress", "Sample Hill Bistro", 102, "0.0000")]))
        self.by = {r.location: r for r in self.p.records}

    def test_columns_chosen_by_name(self):
        c = self.p.columns
        self.assertEqual(c["approval_status"], "ApprovalStatus")      # not the plain "Status" column
        self.assertEqual(c["over_short"], "OverShort")
        self.assertEqual(c["location"], "Location")

    def test_row_count_column_is_used_as_the_stated_total(self):
        self.assertEqual(self.p.stated_total, 2)
        self.assertEqual(self.p.total_source, "file")
        self.assertEqual(len(self.p.records), 2)
        self.assertFalse(any("does not say how many" in w for w in self.p.warnings))

    def test_values(self):
        pier = self.by["Sample Pier Grill"]
        self.assertEqual(pier.business_date, DAY)
        self.assertEqual(pier.cash_over_short, Decimal("-12.5"))
        self.assertIs(pier.approved, True)
        self.assertFalse(pier.cash_sign_known)                          # the sign is not proven
        self.assertIs(self.by["Sample Hill Bistro"].approved, False)

    def test_a_short_file_than_stated_is_flagged(self):
        data = classic([("Approved", "Approved", "Sample Pier Grill", 101, "0.0000")]).replace(b",1,,,,,", b",250,,,,,")
        p = parse(data)
        self.assertEqual(p.stated_total, 250)
        self.assertTrue(any("250" in w for w in p.warnings))


class Beta(unittest.TestCase):
    def test_exact_headings_and_byte_order_mark(self):
        p = parse(beta([("In Progress", "Sample Pier Grill", "-23.5000"), ("Approved", "Sample Hill Bistro", "0.0000")]))
        self.assertEqual(p.columns["approval_status"], "Status")
        self.assertEqual(p.columns["over_short"], "Over/Short")
        self.assertEqual(len(p.records), 2)
        self.assertIsNone(p.stated_total)                               # this layout carries no count
        self.assertTrue(any("does not say how many" in w for w in p.warnings))

    def test_in_progress_is_unknown_not_unapproved_and_a_hint_is_given(self):
        p = parse(beta([("In Progress", "Sample Pier Grill", "0.0000")]))
        r = p.records[0]
        self.assertIsNone(r.approved)
        self.assertIn("In Progress", r.approval_note)
        self.assertTrue(any("In Progress" in w for w in p.warnings))

    def test_the_owner_can_say_what_in_progress_means(self):
        p = parse(beta([("In Progress", "Sample Pier Grill", "0.0000")]), words={"In Progress": "not approved"})
        self.assertIs(p.records[0].approved, False)

    def test_typed_expected_total_counts_as_the_total(self):
        p = parse(beta([("Approved", "Sample Pier Grill", "0.0000")]), expected=5)
        self.assertEqual(p.stated_total, 5)
        self.assertEqual(p.total_source, "you")
        self.assertTrue(any("5" in w for w in p.warnings))


if __name__ == "__main__":
    unittest.main()
