"""The brief report: Place | Complete? | Flag. Made-up data only."""

import re
import unittest
from datetime import timedelta

from dssreport import dss_export_sample as S
from dssreport.brief import NO, UNK, YES, rows_for
from dssreport.report import MultiReport, Report
from dssreport.runner import run_report

from .test_dss_export_integration import NOW, TODAY, Env, inst


def flat(text):
    import html
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))


class BriefReport(Env):
    def one(self, data=None, **kw):
        a = inst()
        self.connect(a)
        self.give(a, data=data, **kw)
        return run_report("r365", self.home / "out", style="brief")

    def test_one_row_per_place_with_complete_yes_no_unknown(self):
        res = self.one()
        rows = {r.place: r for r in rows_for(res.report)}
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows["Sample Hill Bistro"].complete, NO)         # Unapproved
        self.assertEqual(rows["Sample Pier Grill"].complete, YES)
        self.assertEqual(rows["Sample Dock Cafe"].complete, YES)
        self.assertEqual(rows["Sample Park Diner"].complete, UNK)         # no row for the day
        self.assertEqual([r.place for r in rows_for(res.report)][0], "Sample Hill Bistro")   # not complete first

    def test_the_flag_states_the_number_and_never_a_cause(self):
        res = self.one()
        text = flat(res.html_path.read_text(encoding="utf-8")) + res.text_path.read_text(encoding="utf-8")
        self.assertIn("Over/Short is -$23.50 as R365 gives it", text)
        for banned in ("because", "blocking", "blocked", "reason", "caused", "short (limit", " is short"):
            self.assertNotIn(banned, text.lower().replace("does not say why a day is unfinished", ""))

    def test_the_brief_is_short_and_the_long_report_is_still_kept(self):
        res = self.one()
        brief = res.html_path.read_text(encoding="utf-8")
        full = (res.html_path.parent / "report-full.html").read_text(encoding="utf-8")
        self.assertLess(len(brief), len(full))
        for gone in ("How this was decided", "Nothing to review", "Needs a look"):
            self.assertNotIn(gone, brief)
        self.assertIn("<th>Place</th><th>Complete?</th><th>Flag</th>", brief)
        self.assertTrue((res.html_path.parent / "email-full.txt").exists())
        self.assertTrue(res.text_path.read_text(encoding="utf-8").startswith("Subject:"))
        self.assertEqual(brief.count("<tr>"), 5)                            # header + four places

    def test_a_stale_file_makes_everything_unknown_with_one_plain_flag(self):
        res = self.one(mtime=(NOW - timedelta(days=1, hours=2)).timestamp())
        rows = rows_for(res.report)
        self.assertEqual({r.complete for r in rows}, {UNK, })               # Hill Bistro's Unapproved is not trusted either
        text = res.text_path.read_text(encoding="utf-8")
        self.assertIn("Approval unknown: the file is not from today", text)
        self.assertIn("not from today", flat(res.html_path.read_text(encoding="utf-8")))

    def test_in_progress_is_unknown_and_says_what_the_file_said(self):
        res = self.one(data=S.csv_bytes("beta", TODAY))
        rows = {r.place: r for r in rows_for(res.report)}
        self.assertEqual(rows["Sample Dock Cafe"].complete, UNK)
        self.assertIn("Status is 'In Progress', which is not treated as approved or not", rows["Sample Dock Cafe"].flags[0])

    def test_conflicting_rows_are_unknown(self):
        d = f"{TODAY - timedelta(days=1):%m/%d/%Y}"
        data = ("Approval Status,Location,Date,Over/Short\r\n"
                f"Approved,Sample Pier Grill,{d},1.00\r\nUnapproved,Sample Pier Grill,{d},1.00\r\n").encode()
        rows = rows_for(self.one(data=data).report)
        self.assertEqual(rows[0].complete, UNK)
        self.assertIn("Conflict", rows[0].flags[0])

    def test_no_approval_column_means_unknown_not_yes(self):
        data = f"Location,Date,Over/Short\r\nSample Pier Grill,{TODAY - timedelta(days=1):%m/%d/%Y},0\r\n".encode()
        res = self.one(data=data)
        self.assertEqual([r.complete for r in rows_for(res.report)], [UNK])
        self.assertIn("Not checked", flat(res.html_path.read_text(encoding="utf-8")))

    def test_two_connections_each_get_their_own_brief_table(self):
        a, b = inst("Sample Group A"), inst("Sample Group B")
        self.connect(a, b)
        self.give(a)
        self.give(b, data=S.csv_bytes("beta", TODAY), name="b.csv")
        res = run_report("r365", self.home / "out2")
        self.assertIsInstance(res.report, MultiReport)
        html = res.html_path.read_text(encoding="utf-8")
        self.assertEqual(html.count("<th>Complete?</th>"), 2)
        self.assertLess(html.index("Sample Group A"), html.index("Sample Group B"))
        self.assertIn("SAMPLE GROUP A", res.text_path.read_text(encoding="utf-8"))

    def test_a_connection_with_no_file_still_shows_its_reason(self):
        a, b = inst("Sample Group A"), inst("Sample Group B")
        self.connect(a, b)
        self.give(a)
        res = run_report("r365", self.home / "out3")
        self.assertIn("No DSS export file has been chosen", res.html_path.read_text(encoding="utf-8"))
        self.assertIn("No DSS export file has been chosen", res.text_path.read_text(encoding="utf-8"))

    def test_demo_data_works_and_style_full_keeps_the_old_layout(self):
        res = run_report("demo", self.home / "d1")
        self.assertIn("Place / Complete? / Flag", res.text_path.read_text(encoding="utf-8"))
        res = run_report("demo", self.home / "d2", style="full")
        self.assertIn("NEEDS A LOOK", res.text_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
