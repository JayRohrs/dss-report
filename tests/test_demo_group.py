"""Demo mode and the rendered brief: layout markers, plain words, nothing real-looking. Made-up data only."""

import contextlib
import io
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from dssreport import demo_group as D
from dssreport.brief import UNAPPROVED_STATE, UNTOLD, rows_for
from dssreport.cli import main

TODAY = date.today()
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class DemoData(unittest.TestCase):
    def test_twelve_invented_places_on_two_layouts(self):
        names = [p for p, _ in D.EAST + D.WEST]
        self.assertEqual(len(names), 12)
        self.assertTrue(all(n.startswith("Sample ") for n in names))
        east, west = D.export_bytes("classic", TODAY), D.export_bytes("beta", TODAY)
        self.assertTrue(east.startswith(b"ApprovalStatus,"))
        self.assertTrue(west.startswith(b"\xef\xbb\xbf"))                  # the newer layout has a byte-order mark
        self.assertIn(D.CASH_GAP_HEADING.encode(), west.split(b"\r\n")[0])   # the renamed heading
        self.assertNotIn(b"Over/Short", west.split(b"\r\n")[0])
        self.assertIn(b"In Progress", west)
        self.assertNotIn(b"Sample Canal Noodle House", west)               # no data at all
        yday = f"{(TODAY - timedelta(days=1)).month}/{(TODAY - timedelta(days=1)).day}/{(TODAY - timedelta(days=1)).year}"
        lines = [l for l in east.decode().split("\r\n") if yday in l]
        self.assertEqual(sum("Sample Bay Oyster Bar" in l for l in lines), 2)   # the conflicting duplicate
        self.assertEqual(sum("Sample Cedar Steakhouse" in l for l in lines), 0)  # the missing row

    def test_the_fake_ids_are_built_at_run_time_not_stored(self):
        self.assertFalse(GUID.search(Path(D.__file__).read_text(encoding="utf-8")))

    def test_every_mess_case_has_a_story_line(self):
        story = D.story_text()
        for case in D.MESS:
            self.assertIn(case["title"], story)
        self.assertIn("Could not tell", story)
        self.assertIn("never approves anything", story)
        self.assertFalse(GUID.search(story))


class DemoRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.res = D.run_demo(cls.tmp.name, TODAY)
        cls.html = cls.res.html_path.read_text(encoding="utf-8")
        cls.text = cls.res.text_path.read_text(encoding="utf-8")
        cls.old = cls.res.old_file_path.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def rows(self):
        return {r.place: r for s in self.res.report.ok_sections for r in rows_for(s.report, instance=s.name)}

    def test_each_mess_case_is_handled_without_guessing(self):
        rows = self.rows()
        self.assertEqual(rows["Sample Hill Bistro"].state, UNAPPROVED_STATE)
        self.assertIn("Needs to balance: Over/Short -$23.50", rows["Sample Hill Bistro"].reasons)
        self.assertTrue(rows["Sample Park Diner"].ready)
        for place in ("Sample Bay Oyster Bar", "Sample Cedar Steakhouse", "Sample Lake Pizzeria",
                      "Sample Canal Noodle House"):
            self.assertEqual(rows[place].state, UNTOLD, place)
        self.assertIn("'In Progress'", rows["Sample Lake Pizzeria"].reasons[0])
        self.assertEqual(len(rows), 12)

    def test_the_renamed_heading_is_named_and_the_cash_check_is_said_not_to_have_run(self):
        import html as h
        page = h.unescape(self.html)
        self.assertIn("'Cash Gap'", page)
        self.assertIn("no Over/Short column", page)

    def test_layout_markers_for_phone_and_desktop(self):
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', self.html)
        for marker in ('class="summary', 'class="tiles"', "Not approved yet", "Could not tell", "By connection",
                       "@media (min-width:720px)", "@media print", "prefers-color-scheme:dark", "break-inside:avoid"):
            self.assertIn(marker, self.html)
        self.assertNotIn("<script", self.html)                            # self-contained: no scripts, images, links out
        self.assertNotIn("<img", self.html)
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        self.assertLess(self.html.index("Not approved yet"), self.html.index("Could not tell<span"))   # problems first
        self.assertLess(self.html.index("Sample Hill Bistro"), self.html.index("Sample Park Diner"))   # flagged before ready

    def test_plain_words_and_no_overclaiming(self):
        low = (re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", "", self.html, flags=re.S)) + self.text).lower()
        for jargon in ("because", "blocking", "caused by", "null", "nan", "traceback", "odata", "guid", "json"):
            self.assertNotRegex(low, r"\b" + jargon + r"\b")
        self.assertIn("likely reason", low)
        self.assertIn("the report will not guess", low)
        self.assertIn("nothing was approved", low)

    def test_the_text_version_matches(self):
        self.assertTrue(self.text.startswith("Subject:"))
        self.assertIn("2 unapproved, 4 could not be told", self.text.splitlines()[0])
        self.assertLess(self.text.index("NOT APPROVED YET"), self.text.index("COULD NOT TELL"))
        self.assertIn("Sample report: every name and number in it is invented.", self.text)

    def test_no_real_looking_names_or_ids_anywhere(self):
        for page in (self.html, self.text, self.old, D.story_text()):
            self.assertFalse(GUID.search(page))
        names = set(re.findall(r"Sample [A-Z][a-z]+(?: [A-Z][a-z]+)*", self.html + self.text))
        known = {p for p, _ in D.EAST + D.WEST} | {D.EAST_NAME, D.WEST_NAME}
        for n in names:
            self.assertTrue(any(n in k or k in n for k in known | {"Sample report"}), n)
        for path in self.res.export_paths.values():
            self.assertFalse(re.search(r"@\w+\.(com|net|org)", path.read_text(encoding="utf-8-sig")))

    def test_an_old_file_turns_every_place_on_it_into_could_not_tell(self):
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", self.old))
        self.assertIn("The file is not from today, so approval cannot be told", flat)
        self.assertIn("5 places on Sample Group East", flat)               # grouped, not five repeats
        self.assertIn("Sample Cedar Steakhouse", flat)                     # the two with their own reasons stay separate
        self.assertNotIn("Sample Hill Bistro: Needs to balance", flat)
        self.assertNotIn("Needs to balance", flat)

    def test_colours_are_readable(self):
        css = self.html.split("<style>")[1].split("</style>")[0]
        light = dict(re.findall(r"--(\w+):(#[0-9a-f]{6})", css.split("@media")[0]))
        dark = dict(re.findall(r"--(\w+):(#[0-9a-f]{6})", css.split("prefers-color-scheme:dark")[1].split("*{")[0]))
        for tokens in (light, dark):
            self.assertGreaterEqual(ratio(tokens["fg"], tokens["bg"]), 7)
            self.assertGreaterEqual(ratio(tokens["muted"], tokens["bg"]), 4.5)
            self.assertGreaterEqual(ratio(tokens["muted"], tokens["card"]), 4.5)
            for fg, bg in (("bad", "badbg"), ("unk", "unkbg"), ("ok", "okbg")):
                self.assertGreaterEqual(ratio(tokens[fg], tokens[bg]), 4.5, fg)
            self.assertGreaterEqual(ratio(tokens["bad"], tokens["bg"]), 4.5)
            self.assertGreaterEqual(ratio(tokens["unk"], tokens["bg"]), 4.5)

    def test_nothing_outstanding_when_every_file_is_clear(self):
        from dssreport.brief import brief_html
        rep = self.res.report
        for s in rep.ok_sections:
            s.report.attention, s.report.clear = [], s.report.attention + s.report.clear
            for r in s.report.clear:
                r.findings = []
        html = brief_html(rep)
        self.assertIn("Nothing outstanding to approve.", html)
        self.assertNotIn("Not approved yet", html)
        self.assertNotIn("Could not tell<span", html)


class DemoCommand(unittest.TestCase):
    def test_story_prints_and_changes_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("webbrowser.open") as opened:
            self.assertEqual(main(["demo", "--story"]), 0)
        self.assertIn("Could not tell", out.getvalue())
        opened.assert_not_called()

    def test_demo_builds_in_a_folder_and_opens_the_result_and_restores_the_environment(self):
        import os
        before = os.environ.get("DSSREPORT_HOME")
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), \
                mock.patch("webbrowser.open") as opened:
            self.assertEqual(main(["demo", "--out", d]), 0)
            self.assertTrue((Path(d) / "brief.html").exists())
            self.assertTrue((Path(d) / "brief-email.txt").exists())
            self.assertTrue((Path(d) / "exports" / "sample-east-classic.csv").exists())
        opened.assert_called_once()
        self.assertEqual(os.environ.get("DSSREPORT_HOME"), before)

    def test_no_open_flag(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), \
                mock.patch("webbrowser.open") as opened:
            main(["demo", "--out", d, "--no-open"])
        opened.assert_not_called()


class HonestyFixes(unittest.TestCase):
    def test_an_unapproved_place_is_not_ready_when_the_file_has_no_cash_column(self):
        from dssreport.brief import brief_text
        from dssreport.config import Config
        from dssreport.dss_export_sample import LOCATIONS  # noqa: F401  (invented names only)
        from dssreport.model import DayRecord
        from dssreport.report import build_report
        from dssreport.rules import CASH, LABELS
        day = TODAY - timedelta(days=1)
        rec = DayRecord(location="Sample Pier Grill", business_date=day, sales_total=None, payments={},
                        cash_over_short=None, missing_receipts=None, payment_exceptions=None, approved=False,
                        pos_import_received=None)
        rep = build_report([rec], Config(), end=day, unmapped=frozenset({"cash_over_short", "missing_receipts",
                                                                          "payment_exceptions", "pos_import_received", "payments"}))
        self.assertIn(LABELS[CASH], rep.needs_mapping)
        row = rows_for(rep)[0]
        self.assertEqual(row.state, UNAPPROVED_STATE)
        self.assertFalse(row.ready)
        self.assertIn("no Over/Short column", brief_text(rep))
