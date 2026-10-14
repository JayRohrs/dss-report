"""The brief report: only what is still unapproved, with a likely reason. Made-up data only."""

import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from dssreport import dss_export_sample as S
from dssreport.brief import APPROVED, UNAPPROVED_STATE, UNTOLD, load_terms, rows_for
from dssreport.report import MultiReport
from dssreport.runner import run_report

from .test_dss_export_integration import NOW, TODAY, Env, inst


def flat(text):
    import html
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))


def export(rows, header="ApprovalStatus,Location,Date,Over/Short"):
    d = f"{TODAY - timedelta(days=1):%m/%d/%Y}"
    return (header + "\r\n" + "\r\n".join(f"{r[0]},{r[1]},{d},{r[2]}" for r in rows) + "\r\n").encode()


class Brief(Env):
    def one(self, data=None, **kw):
        a = inst()
        self.connect(a)
        self.give(a, data=data, **kw)
        return run_report("r365", self.home / "out", style="brief")

    def test_only_unapproved_places_are_listed_with_a_likely_reason(self):
        res = self.one()
        text = res.text_path.read_text(encoding="utf-8")
        self.assertIn("Sample Hill Bistro", text)
        self.assertIn("Needs to balance: Over/Short -$23.50", text)
        self.assertNotIn("Sample Pier Grill", text)                       # approved: not listed at all
        self.assertNotIn("Sample Dock Cafe", text)
        self.assertIn("Sample Park Diner: No data for this day", text)    # could not tell, said plainly
        self.assertIn("1 unapproved (0 ready to approve, 1 with something flagged). 1 could not be told.", text)

    def test_an_unapproved_day_with_nothing_else_flagged_is_ready_to_approve(self):
        data = export([("Unapproved", "Sample Pier Grill", "0.50"), ("Approved", "Sample Hill Bistro", "-40.00")])
        res = self.one(data=data)
        rows = {r.place: r for r in rows_for(res.report)}
        self.assertEqual(rows["Sample Pier Grill"].state, UNAPPROVED_STATE)
        self.assertTrue(rows["Sample Pier Grill"].ready)
        self.assertEqual(rows["Sample Hill Bistro"].state, APPROVED)        # a cash difference on an approved day: not listed
        text = res.text_path.read_text(encoding="utf-8")
        self.assertIn("Ready to approve", text)
        self.assertNotIn("Hill Bistro", text)

    def test_when_everything_is_approved_it_says_nothing_is_outstanding(self):
        res = self.one(data=export([("Approved", "Sample Pier Grill", "0"), ("Approved", "Sample Hill Bistro", "40.00")]))
        html, text = res.html_path.read_text(encoding="utf-8"), res.text_path.read_text(encoding="utf-8")
        self.assertIn("Nothing outstanding to approve.", html)
        self.assertIn("Nothing outstanding to approve.", text)
        self.assertIn("nothing outstanding to approve", text.splitlines()[0])
        self.assertNotIn("<table", html)

    def test_reasons_are_labelled_likely_and_never_a_cause(self):
        res = self.one()
        html = res.html_path.read_text(encoding="utf-8")
        self.assertIn("Likely reason", html)
        low = (flat(html) + res.text_path.read_text(encoding="utf-8")).lower()
        for banned in ("because", "blocking", "caused by", "cash is $", "is short"):
            self.assertNotIn(banned, low)

    def test_a_stale_file_is_could_not_tell_not_unapproved(self):
        res = self.one(mtime=(NOW - timedelta(days=1, hours=2)).timestamp())
        rows = rows_for(res.report)
        self.assertEqual({r.state for r in rows}, {UNTOLD})
        text = res.text_path.read_text(encoding="utf-8")
        self.assertIn("not from today", text)
        self.assertNotIn("Nothing outstanding", text)

    def test_in_progress_and_conflicts_and_no_approval_column_could_not_tell(self):
        rows = {r.place: r for r in rows_for(self.one(data=S.csv_bytes("beta", TODAY)).report)}
        self.assertEqual(rows["Sample Dock Cafe"].state, UNTOLD)
        self.assertIn("'In Progress'", rows["Sample Dock Cafe"].reasons[0])
        d = export([("Approved", "Sample Pier Grill", "1.00"), ("Unapproved", "Sample Pier Grill", "1.00")])
        self.assertEqual(rows_for(self.one(data=d).report)[0].state, UNTOLD)
        d = f"Location,Date,Over/Short\r\nSample Pier Grill,{TODAY - timedelta(days=1):%m/%d/%Y},0\r\n".encode()
        self.assertEqual(rows_for(self.one(data=d).report)[0].state, UNTOLD)

    def test_the_wording_can_be_changed_by_the_owner_without_an_update(self):
        user = Path(tempfile.mkdtemp()) / "reason_terms.toml"
        user.write_text('ready = "OK to approve"\n[reasons]\ncash_variance = "Off by {value}"\n', encoding="utf-8")
        terms = load_terms(user=user)
        self.assertEqual(terms["ready"], "OK to approve")
        self.assertEqual(terms["reasons"]["cash_variance"], "Off by {value}")
        self.assertIn("POS import", terms["reasons"]["missing_pos_import"])    # the rest still come from the shipped list
        user.write_text("not [valid toml", encoding="utf-8")
        self.assertEqual(load_terms(user=user)["ready"], "Ready to approve")    # a broken file never stops the report

    def test_two_connections_each_get_their_own_answer(self):
        a, b = inst("Sample Group A"), inst("Sample Group B")
        self.connect(a, b)
        self.give(a)
        self.give(b, data=export([("Approved", "Sample Pier Grill", "0")]), name="b.csv")
        res = run_report("r365", self.home / "out2")
        self.assertIsInstance(res.report, MultiReport)
        html = flat(res.html_path.read_text(encoding="utf-8"))
        self.assertLess(html.index("Sample Group A"), html.index("Sample Group B"))
        self.assertIn("Nothing outstanding to approve.", html.split("Sample Group B")[1])
        self.assertNotIn("Nothing outstanding", html.split("Sample Group B")[0])
        self.assertTrue(res.text_path.read_text(encoding="utf-8").startswith("Subject:"))

    def test_a_connection_with_no_file_still_shows_its_reason(self):
        a, b = inst("Sample Group A"), inst("Sample Group B")
        self.connect(a, b)
        self.give(a)
        res = run_report("r365", self.home / "out3")
        self.assertIn("No DSS export file has been chosen", res.html_path.read_text(encoding="utf-8"))
        self.assertIn("No DSS export file has been chosen", res.text_path.read_text(encoding="utf-8"))

    def test_the_brief_is_short_and_the_long_report_is_kept(self):
        res = self.one()
        brief = res.html_path.read_text(encoding="utf-8")
        full = (res.html_path.parent / "report-full.html").read_text(encoding="utf-8")
        self.assertLess(len(brief), len(full))
        self.assertNotIn("How this was decided", brief)
        self.assertTrue((res.html_path.parent / "email-full.txt").exists())
        res = run_report("demo", self.home / "d2", style="full")
        self.assertIn("NEEDS A LOOK", res.text_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
