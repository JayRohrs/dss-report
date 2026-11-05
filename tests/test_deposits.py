"""The deposit matcher. Made-up data only (dssreport/deposits_sample.py)."""

import html as htmllib
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from dssreport import deposits as D
from dssreport import deposits_run as R
from dssreport import deposits_sample as S
from dssreport.credstore import InMemoryStoreForTests
from dssreport.errors import DssError
from dssreport.settings import Settings, save_settings
from dssreport.settings_server import SettingsApp, SettingsServer

A = D.Assumptions()
W = D.load_wording()


def exp(place, day, amount, os=None, number=""):
    return D.Expected(place, date(2026, 3, day), None if amount is None else Decimal(amount),
                      None if os is None else Decimal(os), number)


def bank(*rows):
    out = [D.BankLine(0, date(2026, 3, d), Decimal(a), t, r) for d, t, a, r in rows]
    for i, l in enumerate(out):
        l.idx = i
    return out


def kinds(res):
    return {(i.place, i.day.day): (i.status, i.kind) for i in res.items}


class Cases(unittest.TestCase):
    def run_match(self, expected, lines):
        return D.match(expected, lines, A, W)

    def test_exact_match_with_reasons_and_name(self):
        r = self.run_match([exp("Sample A", 10, "100.00")], bank((10, "SAMPLE A DEPOSIT", "100.00", "1"), (12, "x", "1.00", "2")))
        i = r.items[0]
        self.assertEqual((i.status, i.kind, i.score), (D.MATCHED, "exact", 100))
        self.assertTrue(any("equals the DSS deposit exactly" in x for x in i.reasons))
        self.assertIn("names the place", i.explanation)

    def test_exact_without_name_is_matched_but_says_it_rests_on_amount_and_date(self):
        r = self.run_match([exp("Sample A", 10, "100.00")], bank((11, "COUNTER DEPOSIT", "100.00", "1")))
        self.assertEqual(r.items[0].status, D.MATCHED)
        self.assertLess(r.items[0].score, 100)
        self.assertIn("amount and date alone", r.items[0].explanation)

    def test_outside_the_window_is_not_matched(self):
        r = self.run_match([exp("Sample A", 10, "100.00")], bank((20, "SAMPLE A", "100.00", "1"), (11, "z", "1.00", "2")))
        self.assertNotEqual(r.items[0].status, D.MATCHED)

    def test_split_deposit(self):
        r = self.run_match([exp("Sample A", 10, "1200.00")], bank((11, "SAMPLE A", "700.00", "1"), (11, "SAMPLE A", "500.00", "2")))
        self.assertEqual(kinds(r)[("Sample A", 10)], (D.LOOK, "split"))
        self.assertEqual(len(r.items[0].lines), 2)

    def test_two_days_in_one_deposit_over_a_weekend(self):
        r = self.run_match([exp("Sample A", 13, "2000.00"), exp("Sample A", 14, "1500.00")], bank((16, "SAMPLE A", "3500.00", "1")))
        self.assertEqual(set(kinds(r).values()), {(D.LOOK, "two_days")})
        self.assertIn("weekend", r.items[0].explanation)

    def test_near_miss_is_shown_never_matched_and_links_over_short_without_guessing_the_sign(self):
        r = self.run_match([exp("Sample A", 10, "1000.00", "-5.00")], bank((11, "SAMPLE A", "995.00", "1")))
        i = r.items[0]
        self.assertEqual((i.status, i.kind), (D.LOOK, "near_miss"))
        self.assertIn("Over/Short", i.explanation)
        self.assertIn("not confirmed", i.explanation)

    def test_over_short_wording_follows_a_sign_the_owner_set(self):
        a = D.Assumptions(over_short_sign="negative_is_over")
        r = D.match([exp("Sample A", 10, "1000.00", "-5.00")], bank((11, "SAMPLE A", "995.00", "1")), a, W)
        self.assertIn("5.00 over", r.items[0].explanation)

    def test_swapped_digits_look_like_a_typo(self):
        r = self.run_match([exp("Sample A", 10, "1234.56")], bank((11, "SAMPLE A", "1243.56", "1")))
        self.assertEqual(r.items[0].kind, "typo")
        self.assertEqual(r.items[0].status, D.LOOK)

    def test_missing_deposit(self):
        r = self.run_match([exp("Sample A", 10, "100.00")], bank((12, "OTHER", "9.00", "1"), (16, "z", "1.00", "2")))
        self.assertEqual(kinds(r)[("Sample A", 10)], (D.LOOK, "missing"))

    def test_bank_file_ending_early_is_cannot_tell_not_missing(self):
        r = self.run_match([exp("Sample A", 10, "100.00")], bank((11, "OTHER", "9.00", "1")))
        self.assertEqual(kinds(r)[("Sample A", 10)], (D.UNKNOWN, "bank_ends"))

    def test_duplicate_line_is_never_counted_twice_or_matched(self):
        lines, _, _ = D.read_bank(b"Date,Description,Amount,Reference\n03/11/2026,SAMPLE A,100.00,9\n03/11/2026,SAMPLE A,100.00,9\n03/15/2026,z,1.00,3\n", "b.csv", A)
        r = self.run_match([exp("Sample A", 10, "100.00")], lines)
        self.assertEqual(kinds(r)[("Sample A", 10)], (D.LOOK, "duplicate"))
        self.assertIn("2 times", r.items[0].explanation)

    def test_distinct_references_are_two_real_lines(self):
        lines, _, _ = D.read_bank(b"Date,Description,Amount,Reference\n03/11/2026,SAMPLE A,100.00,8\n03/11/2026,SAMPLE A,100.00,9\n", "b.csv", A)
        self.assertEqual(len(lines), 2)

    def test_same_amount_two_places_and_nothing_names_either_is_not_guessed(self):
        r = self.run_match([exp("Sample A", 10, "500.00"), exp("Sample B", 10, "500.00")], bank((11, "DEPOSIT", "500.00", "1"), (14, "z", "1.00", "2")))
        self.assertEqual(set(kinds(r).values()), {(D.LOOK, "ambiguous")})

    def test_same_amount_two_places_resolved_by_the_bank_text(self):
        r = self.run_match([exp("Sample A", 10, "500.00", number="101"), exp("Sample B", 10, "500.00", number="102")],
                           bank((11, "STORE 101", "500.00", "1"), (11, "STORE 102", "500.00", "2")))
        self.assertEqual(set(kinds(r).values()), {(D.MATCHED, "exact")})

    def test_unreadable_or_blank_expected_amount_is_cannot_tell(self):
        r = self.run_match([exp("Sample A", 10, None)], bank((11, "x", "1.00", "1")))
        self.assertEqual(r.items[0].status, D.UNKNOWN)

    def test_zero_deposit_is_counted_not_listed(self):
        r = self.run_match([exp("Sample A", 10, "0.00")], bank((11, "x", "1.00", "1")))
        self.assertEqual((len(r.items), r.nothing_expected), (0, 1))

    def test_unclaimed_bank_line_is_listed(self):
        r = self.run_match([exp("Sample A", 10, "100.00")], bank((11, "SAMPLE A", "100.00", "1"), (11, "MISC", "7.00", "2"), (15, "z", "1.00", "3")))
        self.assertEqual([r.lines[i].text for i in r.unclaimed], ["MISC"])


class CommaSafety(unittest.TestCase):
    def test_a_decimal_comma_in_the_bank_file_is_not_guessed_by_default(self):
        lines, bad, _ = D.read_bank(S.bank_comma_csv().encode(), "b.csv", A)
        self.assertEqual(lines, [])
        self.assertTrue(bad)

    def test_it_is_read_only_when_the_owner_says_the_bank_writes_that_way(self):
        lines, bad, _ = D.read_bank(S.bank_comma_csv().encode(), "b.csv", D.Assumptions(bank_decimal_comma=True))
        self.assertEqual((len(lines), bad), (11, []))
        self.assertIn(Decimal("2910.00"), [l.amount for l in lines])

    def test_a_lone_point_is_refused_not_turned_into_thousands(self):
        a = D.Assumptions(bank_decimal_comma=True)
        self.assertEqual(D._bank_amount("700.00", a), (None, True))
        self.assertEqual(D._bank_amount("1.234,50", a), (Decimal("1234.50"), False))

    def test_thousands_comma_still_reads_by_default(self):
        self.assertEqual(D._bank_amount("1,234.50", A), (Decimal("1234.50"), False))
        self.assertEqual(D._bank_amount("23,50", A), (None, True))

    def test_the_dss_list_comma_amount_is_cannot_tell(self):
        ex, notes = D.read_expected(S.dss_csv().encode(), "d.csv")
        row = next(e for e in ex if e.place == "Sample Lake Deli" and e.day.day == 11)
        self.assertIsNone(row.amount)
        self.assertTrue(any("comma" in n for n in notes))


class SampleData(unittest.TestCase):
    def setUp(self):
        self.ex, self.notes = D.read_expected(S.dss_csv().encode(), "d.csv")

    def result(self, text, name):
        lines, bad, bn = D.read_bank(text.encode(), name, A)
        return D.match(self.ex, lines, A, W)

    def test_every_planted_case_comes_out_as_planned(self):
        want = {("Sample Pier Grill", 10): "exact", ("Sample Hill Bistro", 10): "exact", ("Sample Pier Grill", 13): "exact",
                ("Sample Hill Bistro", 11): "duplicate", ("Sample Park Cafe", 10): "split",
                ("Sample Dock Kitchen", 13): "two_days", ("Sample Dock Kitchen", 14): "two_days",
                ("Sample Mill Tavern", 10): "near_miss", ("Sample Lake Deli", 10): "typo", ("Sample Lake Deli", 11): "no_amount",
                ("Sample Row Diner", 10): "missing", ("Sample Park Cafe", 12): "ambiguous", ("Sample Pier Grill", 12): "ambiguous",
                ("Sample Pier Grill", 15): "bank_ends"}
        r = self.result(S.bank_csv(), "b.csv")
        self.assertEqual({k: v[1] for k, v in kinds(r).items()}, want)
        self.assertEqual((r.count(D.MATCHED), r.count(D.LOOK), r.count(D.UNKNOWN)), (3, 9, 2))
        weekend = next(i for i in r.items if (i.place, i.day.day) == ("Sample Pier Grill", 13))
        self.assertIn("next business day", weekend.explanation)

    def test_ofx_and_csv_give_the_same_answers(self):
        a = {k: v for k, v in kinds(self.result(S.bank_csv(), "b.csv")).items()}
        b = {k: v for k, v in kinds(self.result(S.bank_ofx(), "b.ofx")).items()}
        self.assertEqual(a, b)

    def test_files_in_the_repo_examples_match_the_generator(self):
        root = Path(__file__).resolve().parent.parent / "examples" / "deposits"
        for name, make in S.FILES.items():
            self.assertEqual((root / name).read_bytes().decode(), make(), name)

    def test_bad_files_get_plain_errors(self):
        with self.assertRaises(DssError):
            D.read_bank(b"nothing useful here\n", "b.csv", A)
        with self.assertRaises(DssError):
            D.read_bank(b"x", "b.pdf", A)
        with self.assertRaises(DssError):
            D.read_expected(b"Location,Date\nSample A,03/10/2026\n", "d.csv")

    def test_wording_comes_from_reason_terms_and_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as t:
            u = Path(t) / "reason_terms.toml"
            u.write_text('[deposits]\nmissing = "Nothing arrived for {day}."\n')
            self.assertEqual(D.load_wording(user=u)["missing"], "Nothing arrived for {day}.")
        self.assertIn("{amount}", W["matched"])


class Base(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict("os.environ", {"DSSREPORT_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.bankdir = self.home / "bank"
        self.bankdir.mkdir()
        S.write_samples(self.home / "samples")
        self.dss = self.home / "samples" / "dss_expected.csv"


class Automation(Base):
    def old_bank(self):
        import os
        p = self.bankdir / "stmt.csv"
        p.write_text(S.bank_csv())
        os.utime(p, (1_700_000_000, 1_700_000_000))        # long finished writing

    def test_a_new_bank_file_is_matched_once_without_clicks(self):
        (self.bankdir / "stmt.csv").write_text(S.bank_csv())
        msg = R.run_watched(str(self.bankdir), str(self.dss))
        self.assertIn("3 matched, 9 need a look, 2 cannot be told", msg)
        self.assertTrue((self.home / "deposits" / "latest-summary.txt").exists())
        self.assertIn("No new bank file", R.run_watched(str(self.bankdir), str(self.dss)))
        (self.bankdir / "stmt2.csv").write_text(S.bank_csv().replace("2910.00", "2911.00"))
        self.assertIn("matched", R.run_watched(str(self.bankdir), str(self.dss)))

    def test_the_newest_file_in_the_folder_is_used(self):
        old = self.bankdir / "old.csv"
        old.write_text("junk")
        new = self.bankdir / "new.ofx"
        new.write_text(S.bank_ofx())
        import os
        os.utime(old, (1, 1))
        self.assertIn("matched", R.run_watched(str(self.bankdir), str(self.dss)))
        self.assertEqual(R.load_latest().bank_name, "new.ofx")

    def test_a_file_still_being_written_waits(self):
        (self.bankdir / "stmt.csv").write_text(S.bank_csv())
        self.assertIn("a moment ago", R.run_watched(str(self.bankdir), str(self.dss), settle_seconds=60))

    def test_a_broken_bank_file_is_a_plain_problem_and_the_schedule_step_never_raises(self):
        (self.bankdir / "stmt.csv").write_text("not a bank file")
        with self.assertRaises(DssError):
            R.run_watched(str(self.bankdir), str(self.dss))
        logged = []
        out = R.scheduled_step(str(self.bankdir), str(self.dss), lambda m, now=None: logged.append(m), settle_seconds=0)
        self.assertIn("could not run", out)
        self.assertTrue(logged)
        self.assertIn("bank", R.last_error())

    def test_nothing_set_means_nothing_done(self):
        self.assertEqual(R.scheduled_step("", "", lambda *a: None), "")

    def test_the_desktop_daily_run_does_the_deposit_step(self):
        from dssreport.desktop import daily
        from dssreport.desktop.settings import DesktopSettings
        self.old_bank()
        s = DesktopSettings(daily_run_enabled=True, deposit_bank_path=str(self.bankdir), deposit_dss_path=str(self.dss))
        runner = mock.Mock(side_effect=DssError("no report today"))
        daily.daily_run(s, datetime(2026, 3, 16, 7, 0), runner=runner)
        self.assertIsNotNone(R.load_latest())

    def test_the_classic_schedule_does_the_deposit_step(self):
        from dssreport import scheduler
        self.old_bank()
        s = Settings(schedule_enabled=True, deposit_bank_path=str(self.bankdir), deposit_dss_path=str(self.dss))
        with mock.patch("dssreport.scheduler.lic.current_status") as cs:
            cs.return_value.has.return_value = True
            scheduler.scheduled_run(s, datetime(2026, 3, 16, 3, 0), runner=mock.Mock())
        self.assertIn("3 matched", (self.home / "deposits" / "latest-summary.txt").read_text())

    def test_settings_keep_the_two_paths(self):
        save_settings(Settings(deposit_bank_path="C:/x/bank", deposit_dss_path=""), self.home / "s.json")
        from dssreport.settings import load_settings
        self.assertEqual(load_settings(self.home / "s.json").deposit_bank_path, "C:/x/bank")


class Screen(Base):
    def setUp(self):
        super().setUp()
        self.drafts = []
        self.app = SettingsApp(InMemoryStoreForTests())
        self.app.draft_mailer_factory = lambda ds: mock.Mock(create_draft=lambda *a, **k: self.drafts.append(a))
        self.server = SettingsServer(self.app)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def get(self, path="/deposits"):
        return htmllib.unescape(urllib.request.urlopen(f"{self.base}{path}?t={self.server.token}").read().decode())

    def post(self, **d):
        d["t"] = self.server.token
        return htmllib.unescape(urllib.request.urlopen(urllib.request.Request(
            self.base + "/deposits", urllib.parse.urlencode(d).encode())).read().decode())

    def test_empty_screen_offers_the_made_up_sample(self):
        h = self.get()
        self.assertIn("No bank file checked yet", h)
        self.assertIn("made-up sample", h)

    def test_screen_renders_summary_rows_actions_and_assumptions(self):
        h = self.post(do="sample")
        for text in ("Matched", "Needs a look (9)", "Cannot tell (2)", "Looks right", "Flag", "Draft a note",
                     "Assumed, not confirmed", "UNKNOWN: whether a positive Over/Short",
                     "Sample Mill Tavern", "Bank lines no place claimed (1)", "Matched (3)"):
            self.assertIn(text, h)
        self.assertEqual(h.count('value="note"'), 14)
        self.assertNotIn("<script", h)

    def test_marks_are_kept_and_can_be_undone(self):
        self.post(do="sample")
        item = next(i for i in R.load_latest().result.items if i.kind == "split")
        h = self.post(do="ok", key=item.key)
        self.assertIn("You: looks right", h)
        self.assertIn("You marked 1 as looks right", h)
        self.assertIn("You: flagged", self.post(do="flag", key=item.key))
        self.assertNotIn("You: flagged", self.post(do="clear", key=item.key))

    def test_draft_a_note_is_text_and_sends_nothing(self):
        self.post(do="sample")
        item = next(i for i in R.load_latest().result.items if i.kind == "near_miss")
        h = self.post(do="note", key=item.key)
        self.assertIn("Deposit check: Sample Mill Tavern", h)
        self.assertIn("<textarea", h)
        self.assertIn("Nothing has been sent", h)
        self.assertEqual(self.drafts, [])

    def test_microsoft_draft_goes_through_the_draft_only_mailer(self):
        self.post(do="sample")
        item = next(i for i in R.load_latest().result.items if i.kind == "near_miss")
        h = self.post(do="draft", key=item.key)
        self.assertIn("fill in the draft address", h)
        from dssreport.desktop import settings as dst
        dst.save(dst.DesktopSettings(draft_email_enabled=True, draft_to="boss@company.example", graph_client_id="abc"))
        h = self.post(do="draft", key=item.key)
        self.assertIn("It was not sent", h)
        self.assertEqual(self.drafts[0][0], "boss@company.example")

    def test_unknown_key_and_missing_file_are_plain_problems(self):
        self.post(do="sample")
        self.assertIn("no longer in the latest check", self.post(do="ok", key="nope"))
        self.assertIn("Choose the bank file first", self.post(do="upload"))

    def test_settings_page_has_the_deposit_section_and_saves_the_paths(self):
        self.assertIn("9. Deposit matcher", self.get("/"))
        _, cfg = self.app.current()
        self.app.apply_form({"deposit_bank_path": ["C:/b"], "deposit_dss_path": [""], "schedule_time": ["07:00"], "wd0": ["1"],
                             "cash_limit": ["5"], "receipts_allowed": ["0"], "exceptions_allowed": ["0"],
                             "payments_tolerance": ["0"], "ai_endpoint": [cfg.ai_endpoint], "ai_model": [cfg.ai_model]})
        self.assertIn("C:/b", self.get("/deposits"))

    def test_page_needs_the_token(self):
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{self.base}/deposits?t=wrong")


if __name__ == "__main__":
    unittest.main()
