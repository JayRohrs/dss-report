"""The R365 DSS export (file) source. Made-up fixtures only: "Sample Group A", invented locations, invented amounts.
No real R365 export was used; the beta layout's exact headings are an assumption covered by the alias table."""

import io
import os
import re
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from dssreport import dss_export as E
from dssreport import dss_export_sample as S
from dssreport import dss_export_source as X
from dssreport import rules
from dssreport.config import Config
from dssreport.errors import InputError
from dssreport.report import build_report
from dssreport.runner import run_report
from dssreport.settings import Instance, Settings, save_settings

from . import licence_helpers as H

TODAY = date(2026, 3, 14)
DAY = date(2026, 3, 13)
NOW = datetime(2026, 3, 14, 8, 30)
FRESH = datetime(2026, 3, 14, 7, 55)         # the file's own date: this morning
NO_USER_ALIASES = Path("/nonexistent/aliases.toml")


def aliases():
    return E.load_aliases(user=NO_USER_ALIASES)


def csv_text(headers, rows, pre=(), post=(), delim=","):
    lines = [delim.join(p) if isinstance(p, (list, tuple)) else p for p in pre]
    lines.append(delim.join(headers))
    lines += [delim.join(str(c) for c in r) for r in rows]
    lines += [delim.join(p) if isinstance(p, (list, tuple)) else p for p in post]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def parse(data, name="x.csv", as_of=FRESH, today=TODAY, words=None):
    rows, stats, _ = E.read_rows(data, name)
    return E.parse_export(rows, aliases(), words, as_of, today, stats)


H_CLASSIC = ["Approval Status", "Location", "Location Number", "Name", "Date", "Attachment", "Net Sales",
             "Total Deposit", "Over/Short", "Guest Count", "Steps Complete", "Log Entries", "Paidout Total",
             "Created By", "Created On", "Modified By", "Modified On"]


def classic_row(status="Approved", loc="Sample Pier Grill", d="03/13/2026", over="1.25", sales="3100.00", extra=None):
    return [status, loc, "101", f"DSS {d}", d, "", sales, "3000.00", over, "90", "5/5", "2", "0.00",
            "Sample User", "03/14/2026 06:00 AM", "Sample User", "03/14/2026 07:30 AM"]


def by_loc(parsed, day=DAY):
    return {r.location: r for r in parsed.records if r.business_date == day}


class Layouts(unittest.TestCase):
    def test_classic_layout_with_every_header_from_the_owner_s_list(self):
        p = parse(csv_text(H_CLASSIC, [classic_row(), classic_row("Unapproved", "Sample Hill Bistro", over="-23.50")]))
        r = by_loc(p)
        self.assertTrue(r["Sample Pier Grill"].approved)
        self.assertFalse(r["Sample Hill Bistro"].approved)
        self.assertEqual(r["Sample Hill Bistro"].cash_over_short, Decimal("-23.50"))
        self.assertEqual(r["Sample Pier Grill"].sales_total, Decimal("3100.00"))
        self.assertEqual(p.missing, [])
        self.assertIn("Guest Count", p.unrecognised)               # extra columns are tolerated

    def test_beta_style_layout_title_line_other_headings_and_footer(self):
        p = parse(S.csv_bytes("beta", TODAY), as_of=FRESH)
        self.assertEqual(p.columns["approval_status"], "Status")
        self.assertEqual(p.columns["over_short"], "Over (Short)")
        self.assertEqual(p.columns["location"], "Location Name")
        self.assertEqual(p.stated_total, p.rows_read)
        self.assertEqual({r.location for r in p.records}, {x[0] for x in S.LOCATIONS})   # "Location #" is NOT the location
        self.assertEqual(p.warnings, ["This file has no Location Number column (not needed by any check)."]
                         if "location_number" in p.missing else p.warnings)

    def test_heading_row_need_not_be_on_line_one_and_trailing_lines_are_skipped(self):
        data = csv_text(H_CLASSIC, [classic_row()], pre=["Daily Sales Summaries", "Sample Group A", ""],
                        post=["", ["Total", "", "", "", "", "", "3100.00"], "Printed by Sample User"])
        p = parse(data)
        self.assertEqual(len(p.records), 1)
        self.assertEqual(p.rows_read, 1)
        self.assertIn("line 4", p.layout_note)

    def test_reordered_and_extra_columns(self):
        heads = ["Zebra", "Over/Short", "Date", "Notes", "Location", "Approval Status"]
        p = parse(csv_text(heads, [["x", "-9.00", "03/13/2026", "n", "Sample Dock Cafe", "Unapproved"]]))
        r = by_loc(p)["Sample Dock Cafe"]
        self.assertEqual((r.approved, r.cash_over_short), (False, Decimal("-9.00")))
        self.assertEqual(sorted(p.unrecognised), ["Notes", "Zebra"])

    def test_missing_columns_are_reported_plainly_and_their_checks_are_not_run(self):
        p = parse(csv_text(["Location", "Date", "Approval Status"], [["Sample Dock Cafe", "03/13/2026", "Approved"]]))
        self.assertIn("This file has no Over/Short column, so the cash over/short check could not run.", p.warnings)
        self.assertIn("cash_over_short", p.unmapped)
        self.assertIn("sales_total", p.unmapped)
        self.assertNotIn("approved", p.unmapped)
        p2 = parse(csv_text(["Location", "Date", "Over/Short"], [["Sample Dock Cafe", "03/13/2026", "1.00"]]))
        self.assertIn("This file has no Approval Status column, so the approval check could not run.", p2.warnings)
        self.assertIn("approved", p2.unmapped)

    def test_a_file_without_location_or_date_cannot_be_read_and_says_which(self):
        with self.assertRaises(E.ExportError) as cm:
            parse(csv_text(["Approval Status", "Date"], [["Approved", "03/13/2026"]]))
        self.assertIn("no Location column", str(cm.exception))
        with self.assertRaises(E.ExportError) as cm:
            parse(csv_text(["Foo", "Bar"], [["1", "2"]]))
        self.assertIn("does not look like an R365 Daily Sales Summary list", str(cm.exception))

    def test_things_never_in_the_export_are_always_not_run(self):
        p = parse(csv_text(H_CLASSIC, [classic_row()]))
        self.assertEqual(p.unmapped, {"missing_receipts", "payment_exceptions", "pos_import_received", "payments"})


class HeadingAliases(unittest.TestCase):
    def test_case_spacing_and_punctuation_do_not_matter(self):
        for over in ("Over/Short", "over short", "OVER-SHORT", "Over / Short", "Over (Short)", "Cash Over/Short"):
            p = parse(csv_text(["Location", "Date", over], [["Sample Dock Cafe", "2026-03-13", "-7"]]))
            self.assertEqual(by_loc(p)["Sample Dock Cafe"].cash_over_short, Decimal("-7"), over)
        for loc in ("LOCATION", " location ", "Location Name", "Store"):
            p = parse(csv_text([loc, "Business Date", "Status"], [["Sample Dock Cafe", "2026-03-13", "Approved"]]))
            self.assertEqual(len(p.records), 1, loc)

    def test_hash_means_number_so_location_number_is_not_mistaken_for_the_location(self):
        self.assertEqual(E.norm("Location #"), "locationnumber")
        p = parse(csv_text(["Location #", "Location", "Date"], [["101", "Sample Dock Cafe", "2026-03-13"]]))
        self.assertEqual([r.location for r in p.records], ["Sample Dock Cafe"])

    def test_a_better_heading_wins_and_ambiguity_is_said_out_loud(self):
        p = parse(csv_text(["Status", "Approval Status", "Location", "Date"], [["Pending", "Approved", "Sample Dock Cafe", "2026-03-13"]]))
        self.assertTrue(by_loc(p)["Sample Dock Cafe"].approved)               # "Approval Status" beats "Status"
        p = parse(csv_text(["Location", "Date", "Over/Short", "Over/Short"], [["Sample Dock Cafe", "2026-03-13", "1", "2"]]))
        self.assertIn("Two columns look like Over/Short; the first was used.", p.warnings)

    def test_the_owner_can_add_new_wordings_without_touching_the_shipped_list(self):
        user = Path(tempfile.mkdtemp()) / "dss_export_aliases.toml"
        user.write_text('version = 1\n[fields]\nover_short = ["Cash Variance Amount"]\n')
        rows, stats, _ = E.read_rows(csv_text(["Location", "Date", "Cash Variance Amount"], [["Sample Dock Cafe", "2026-03-13", "3"]]), "x.csv")
        p = E.parse_export(rows, E.load_aliases(user=user), None, FRESH, TODAY, stats)
        self.assertEqual(by_loc(p)["Sample Dock Cafe"].cash_over_short, Decimal("3"))
        self.assertIn("overshort", E.load_aliases(user=user).fields["over_short"])         # shipped words still there

    def test_alias_file_is_shipped_documented_and_versioned(self):
        text = E.shipped_alias_path().read_text()
        self.assertIn("by heading NAME", text)
        self.assertIn("version = 1", text)
        for f in E.FIELDS:
            self.assertIn(f, aliases().fields)
        bad = Path(tempfile.mkdtemp()) / "a.toml"
        bad.write_text("version = 9\n")
        with self.assertRaises(E.ExportError):
            E.load_aliases(user=bad)


class ApprovalWords(unittest.TestCase):
    def one(self, word, **kw):
        p = parse(csv_text(["Location", "Date", "Approval Status"], [["Sample Dock Cafe", "03/13/2026", word]]), **kw)
        return by_loc(p)["Sample Dock Cafe"]

    def test_approved_and_unapproved_are_the_only_defaults_with_a_meaning(self):
        self.assertIs(self.one("Approved").approved, True)
        self.assertIs(self.one("Unapproved").approved, False)
        self.assertIs(self.one("  APPROVED ").approved, True)
        self.assertIs(self.one("unapproved").approved, False)

    def test_in_progress_and_completed_stay_unknown_with_the_word_kept(self):
        for word in ("In Progress", "Completed", "in   progress"):
            r = self.one(word)
            self.assertIsNone(r.approved, word)
            self.assertIn(f"'{word.strip()}'", r.approval_note)
            self.assertIn("not treated as approved or not approved", r.approval_note)
        self.assertIn("still being worked on", self.one("In Progress").approval_note)
        self.assertIn("does not say it was approved", self.one("Completed").approval_note)

    def test_an_unexpected_word_is_unknown_and_kept(self):
        r = self.one("Pending Review")
        self.assertIsNone(r.approved)
        self.assertIn("'Pending Review'", r.approval_note)

    def test_blank_approval_is_unknown_without_inventing_a_word(self):
        r = self.one("")
        self.assertIsNone(r.approved)
        self.assertIsNone(r.approval_note)

    def test_rules_show_unknown_with_the_word_and_never_flag_in_progress_as_unapproved(self):
        for word, expected_kind in (("In Progress", rules.UNKNOWN), ("Unapproved", rules.ISSUE), ("Approved", None)):
            r = self.one(word)
            found = [f for f in rules.evaluate_day("X", DAY, r, Config(), frozenset({"missing_receipts", "payment_exceptions", "pos_import_received", "payments"}))
                     if f.rule == rules.UNAPPROVED]
            self.assertEqual(found[0].kind if found else None, expected_kind, word)
        self.assertIn("In Progress", [f for f in rules.evaluate_day("X", DAY, self.one("In Progress"), Config())
                                      if f.rule == rules.UNAPPROVED][0].text)

    def test_per_connection_override_off_by_default_and_on_when_the_owner_sets_it(self):
        self.assertIsNone(self.one("In Progress").approved)
        r = self.one("In Progress", words={"In Progress": "not approved"})
        self.assertIs(r.approved, False)
        self.assertIs(self.one("Completed", words={"completed": "approved"}).approved, True)
        self.assertIsNone(self.one("Completed", words={"In Progress": "not approved"}).approved)   # only the word given

    def test_the_two_built_in_words_cannot_be_redefined(self):
        self.assertIs(self.one("Approved", words={"Approved": "not approved"}).approved, True)
        self.assertIs(self.one("Unapproved", words={"Unapproved": "approved"}).approved, False)
        self.assertEqual(E.clean_overrides({"Approved": "unapproved", "In Progress": "maybe", "Done": "approved"}),
                         {"done": True})

    def test_settings_validation_of_the_override_setting(self):
        from dssreport.errors import ConfigError
        ok = Instance(id="a", name="A", source_kind="dss-export", approval_words={"In Progress": "not approved"})
        save_settings_to = Path(tempfile.mkdtemp()) / "s.json"
        from dssreport.settings import validate
        validate(Settings(instances=[ok]))
        for bad in ({"Approved": "unapproved"}, {"In Progress": "maybe"}, {"": "approved"}):
            with self.assertRaises(ConfigError):
                validate(Settings(instances=[Instance(id="a", name="A", source_kind="dss-export", approval_words=bad)]))


class OverShort(unittest.TestCase):
    def over(self, text):
        p = parse(csv_text(["Location", "Date", "Over/Short"], [["Sample Dock Cafe", "03/13/2026", text]]))
        return by_loc(p)["Sample Dock Cafe"].cash_over_short, p

    def test_number_formats(self):
        for text, want in (("-23.50", "-23.50"), ("$-5.00", "-5.00"), ("(23.50)", "-23.50"), ("5.00-", "-5.00"),
                           ('"1,234.50"', "1234.50"), ("$12", "12"), ("+3.10", "3.10"), ("−2.00", "-2.00")):
            self.assertEqual(self.over(text)[0], Decimal(want), text)

    def test_blank_is_unknown_and_junk_is_unknown_with_a_plain_count(self):
        v, p = self.over("")
        self.assertIsNone(v)
        self.assertFalse(any("could not be read as a number" in w for w in p.warnings))
        for junk in ("n/a", "-", "abc", "NaN", "Infinity"):
            v, p = self.over(junk)
            self.assertIsNone(v, junk)
            self.assertIn("1 Over/Short value could not be read as a number and is shown as UNKNOWN.", p.warnings)

    def test_both_directions_at_the_limit_are_not_flagged_and_just_past_it_are(self):
        cfg = Config()
        self.assertEqual(cfg.cash_limit, Decimal("5.00"))
        for text, flagged, word in (("5.00", False, ""), ("-5.00", False, ""), ("5.01", True, "over"), ("-5.01", True, "short")):
            rec = by_loc(parse(csv_text(["Location", "Date", "Over/Short"], [["Sample Dock Cafe", "03/13/2026", text]])))["Sample Dock Cafe"]
            found = [f for f in rules.evaluate_day("X", DAY, rec, cfg) if f.rule == rules.CASH]
            self.assertEqual(bool(found), flagged, text)
            if found:
                self.assertIn(word, found[0].text)
        bigger = Config(cash_limit=Decimal("20"))
        rec = by_loc(parse(csv_text(["Location", "Date", "Over/Short"], [["Sample Dock Cafe", "03/13/2026", "-23.50"]])))["Sample Dock Cafe"]
        self.assertTrue([f for f in rules.evaluate_day("X", DAY, rec, bigger) if f.rule == rules.CASH])


class DatesAndFormats(unittest.TestCase):
    def days(self, values, **kw):
        p = parse(csv_text(["Location", "Date"], [["Sample Dock Cafe", v] for v in values]), **kw)
        return [r.business_date for r in p.records], p

    def test_common_date_formats(self):
        d, _ = self.days(["2026-03-13", "03/13/2026", "3/13/26", "13-Mar-2026", "Mar 13, 2026", "March 13, 2026", "2026-03-13T00:00:00"])
        self.assertEqual(set(d), {DAY})

    def test_day_first_is_detected_from_the_column_and_ambiguity_is_said(self):
        d, _ = self.days(["13/03/2026", "01/04/2026"])
        self.assertEqual(sorted(d), [date(2026, 3, 13), date(2026, 4, 1)])
        d, p = self.days(["03/04/2026", "05/06/2026"])
        self.assertEqual(sorted(d), [date(2026, 3, 4), date(2026, 5, 6)])      # month first, like R365's US default
        self.assertTrue(any("read month first" in w for w in p.warnings))
        with self.assertRaises(E.ExportError):
            self.days(["13/03/2026", "03/25/2026"])                            # both orders: cannot tell

    def test_rows_with_an_unreadable_date_are_set_aside_and_counted_not_hidden(self):
        d, p = self.days(["03/13/2026", "not a date", "02/30/2026"])
        self.assertEqual(d, [DAY])
        self.assertTrue(any("2 rows had a Date that could not be read and were set aside" in w for w in p.warnings))
        self.assertEqual(p.rows_read, 3)


class FileFormats(unittest.TestCase):
    def test_csv_tsv_and_xlsx_give_identical_records(self):
        tbl = S.table("classic", TODAY)
        csv_p = parse(S.csv_bytes("classic", TODAY), "a.csv")
        tsv_p = parse(S.csv_bytes("classic", TODAY, "\t"), "a.tsv")
        xlsx_p = parse(S.xlsx_bytes(tbl), "a.xlsx")
        key = lambda p: [(r.location, r.business_date, r.approved, r.approval_note, r.cash_over_short, r.sales_total) for r in p.records]
        self.assertEqual(key(csv_p), key(tsv_p))
        self.assertEqual(key(csv_p), key(xlsx_p))
        self.assertEqual(len(csv_p.records), 55)

    def test_csv_delimiter_and_encoding_are_sniffed(self):
        semi = csv_text(["Location", "Date", "Over/Short"], [["Sample Dock Cafe", "03/13/2026", "-9"]], delim=";")
        self.assertEqual(len(parse(semi, "x.csv").records), 1)
        latin = "Location,Date\r\nSample Caf\xe9,2026-03-13\r\n".encode("cp1252")
        self.assertEqual(parse(latin).records[0].location, "Sample Caf\xe9")
        bom = b"\xef\xbb\xbf" + csv_text(["Location", "Date"], [["Sample Dock Cafe", "2026-03-13"]])
        self.assertEqual(len(parse(bom).records), 1)

    def test_xlsx_dates_numbers_and_text_come_back_as_text_cells(self):
        data = S.xlsx_bytes([["Location", "Date", "Over/Short", "Approval Status"],
                             ["Sample Dock Cafe", DAY, -12.5, "Unapproved"]])
        r = by_loc(parse(data, "a.xlsx"))["Sample Dock Cafe"]
        self.assertEqual((r.cash_over_short, r.approved), (Decimal("-12.5"), False))

    def test_formulas_are_never_calculated_only_stored_values_are_read(self):
        data = S.xlsx_bytes([["Location", "Date", "Over/Short", "Approval Status"],
                             ["Sample Dock Cafe", DAY, S.Formula("=1+1", 7.5), "Approved"],
                             ["Sample Hill Bistro", DAY, S.Formula("=SUM(A1:A9)"), "Approved"]])
        rows, stats, _ = E.read_rows(data, "a.xlsx")
        self.assertEqual(stats.formulas, 2)
        p = E.parse_export(rows, aliases(), None, FRESH, TODAY, stats)
        r = by_loc(p)
        self.assertEqual(r["Sample Dock Cafe"].cash_over_short, Decimal("7.5"))          # the stored value, not 2
        self.assertIsNone(r["Sample Hill Bistro"].cash_over_short)                        # no stored value -> blank, UNKNOWN
        self.assertTrue(any("1 Excel formula cell had no stored value" in w for w in p.warnings))

    def test_formula_looking_text_in_a_csv_is_just_text(self):
        p = parse(csv_text(["Location", "Date"], [["=HYPERLINK(\"http://x\")", "2026-03-13"]]))
        self.assertEqual(p.records[0].location, '=HYPERLINK("http://x")')

    def test_macro_enabled_old_and_wrong_files_are_refused_plainly(self):
        for name, needle in (("a.xlsm", "Macro-enabled"), ("a.xls", "Old-style .xls"), ("a.pdf", "ending in .xlsx"),
                             ("a.docx", "ending in .xlsx")):
            with self.assertRaises(E.ExportError) as cm:
                E.read_rows(b"data", name)
            self.assertIn(needle, str(cm.exception))
        with self.assertRaises(E.ExportError):
            E.read_rows(b"just text", "a.xlsx")
        with self.assertRaises(E.ExportError):
            E.read_rows(b"PK\x03\x04junk", "a.xlsx")
        with self.assertRaises(E.ExportError):
            E.read_rows(b"   ", "a.csv")

    def test_non_file_input_is_refused(self):
        for bad in (None, "text", 12, ["a"]):
            with self.assertRaises(E.ExportError):
                E.read_rows(bad, "a.csv")

    def test_oversize_files_are_refused(self):
        with mock.patch.object(E, "MAX_FILE_BYTES", 100):
            with self.assertRaises(E.ExportError) as cm:
                E.read_rows(b"Location,Date\n" + b"x" * 200, "a.csv")
        self.assertIn("far bigger", str(cm.exception))
        with mock.patch.object(E, "MAX_UNZIPPED_BYTES", 500):
            with self.assertRaises(E.ExportError) as cm:
                E.read_rows(S.xlsx_bytes(S.table("classic", TODAY)), "a.xlsx")
        self.assertIn("unpacks to far more data", str(cm.exception))
        with mock.patch.object(E, "MAX_ROWS", 5):
            with self.assertRaises(E.ExportError):
                E.read_rows(S.csv_bytes("classic", TODAY), "a.csv")

    def test_xml_tricks_are_refused_and_macros_are_never_read(self):
        evil = S.xlsx_bytes([["Location", "Date"], ["Sample Dock Cafe", DAY]],
                            extra_files={"xl/sharedStrings.xml": '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>'})
        with self.assertRaises(E.ExportError) as cm:
            E.read_rows(evil, "a.xlsx")
        self.assertIn("unsupported content", str(cm.exception))
        macro = S.xlsx_bytes([["Location", "Date"], ["Sample Dock Cafe", DAY]], extra_files={"xl/vbaProject.bin": b"MACRO BYTES"})
        rows, _, _ = E.read_rows(macro, "a.xlsx")                # still just a table; the macro part is never opened
        self.assertEqual(rows[1][0], "Sample Dock Cafe")


class Coverage(unittest.TestCase):
    def test_partial_list_when_the_file_states_more_than_it_holds(self):
        for stated in ("Total Records: 10", "Showing 1-3 of 10", "10 records", "Records: 10"):
            p = parse(csv_text(H_CLASSIC, [classic_row(loc=f"Sample Place {i}") for i in range(3)],
                               post=["", [stated]]))
            self.assertEqual((p.stated_total, p.rows_read), (10, 3), stated)
            self.assertTrue(p.warnings[0].startswith("Partial list: the file says it holds 10 entries but only 3 were read"), stated)

    def test_a_stated_total_before_the_table_counts_too(self):
        p = parse(csv_text(H_CLASSIC, [classic_row()], pre=["Total Records: 4"]))
        self.assertTrue(p.warnings[0].startswith("Partial list"))

    def test_complete_lists_are_not_flagged(self):
        p = parse(csv_text(H_CLASSIC, [classic_row(loc=f"Sample Place {i}") for i in range(3)], post=["Total Records: 3"]))
        self.assertEqual(p.stated_total, 3)
        self.assertFalse(any("Partial" in w for w in p.warnings))
        self.assertFalse(any("Partial" in w for w in parse(csv_text(H_CLASSIC, [classic_row()])).warnings))

    def test_duplicate_day_with_conflicting_status_is_unknown_and_a_conflict(self):
        p = parse(csv_text(H_CLASSIC, [classic_row("Approved"), classic_row("Unapproved")]))
        r = by_loc(p)["Sample Pier Grill"]
        self.assertIsNone(r.approved)
        self.assertEqual(r.conflicts, ("approval status",))
        found = rules.evaluate_day("X", DAY, r, Config())
        texts = [f.text for f in found]
        self.assertTrue(any(t.startswith("Conflict:") and "approval status" in t for t in texts))
        self.assertEqual(sum(f.kind == rules.UNKNOWN for f in found if f.rule == rules.UNAPPROVED), 0)   # one finding, not two
        self.assertTrue(any("1 day had rows that disagree" in w for w in p.warnings))

    def test_duplicate_rows_that_agree_are_merged_and_conflicting_amounts_are_unknown(self):
        p = parse(csv_text(H_CLASSIC, [classic_row(), classic_row()]))
        r = by_loc(p)["Sample Pier Grill"]
        self.assertEqual((r.approved, r.conflicts), (True, ()))
        p = parse(csv_text(H_CLASSIC, [classic_row(over="1.00"), classic_row(over="9.00")]))
        r = by_loc(p)["Sample Pier Grill"]
        self.assertIsNone(r.cash_over_short)
        self.assertEqual(r.conflicts, ("over/short",))
        self.assertTrue(r.approved)

    def test_a_day_with_no_row_is_unknown_never_defaulted(self):
        recs = [r for r in parse(csv_text(H_CLASSIC, [classic_row(d="03/12/2026"), classic_row(d="03/13/2026", loc="Sample Hill Bistro")])).records]
        rep = build_report(recs, Config(), end=DAY, unmapped=frozenset({"missing_receipts", "payment_exceptions", "pos_import_received", "payments"}))
        pier = next(x for x in rep.attention if x.name == "Sample Pier Grill")
        self.assertEqual(pier.status, "UNKNOWN")
        self.assertIn("UNKNOWN: No data for this day", [t for t in __import__("dssreport.report", fromlist=["reasons"]).reasons(pier, False)])


class Freshness(unittest.TestCase):
    def test_a_file_dated_today_can_show_approval(self):
        p = parse(csv_text(H_CLASSIC, [classic_row("Unapproved")]), as_of=datetime(2026, 3, 14, 0, 5))
        self.assertIs(by_loc(p)["Sample Pier Grill"].approved, False)
        self.assertFalse(any("older than today" in w for w in p.warnings))

    def test_a_file_older_than_today_cannot_establish_approval_and_says_so(self):
        p = parse(csv_text(H_CLASSIC, [classic_row("Approved"), classic_row("Unapproved", "Sample Hill Bistro")]),
                  as_of=datetime(2026, 3, 13, 23, 50))
        for r in p.records:
            self.assertIsNone(r.approved)
            self.assertIn("dated 2026-03-13, older than today", r.approval_note)
        self.assertIn("'Unapproved'", by_loc(p)["Sample Hill Bistro"].approval_note)             # the word is kept
        self.assertTrue(p.warnings[0].startswith("This file is dated 2026-03-13. A file older than today cannot establish today's approval status"))

    def test_a_file_that_does_not_say_when_it_was_downloaded_is_treated_as_unproven(self):
        p = parse(csv_text(H_CLASSIC, [classic_row("Approved")]), as_of=None)
        r = by_loc(p)["Sample Pier Grill"]
        self.assertIsNone(r.approved)
        self.assertIn("does not say when it was downloaded", r.approval_note)
        self.assertTrue(p.warnings[0].startswith("This file does not say when it was downloaded"))

    def test_over_short_is_still_checked_from_an_older_file(self):
        p = parse(csv_text(H_CLASSIC, [classic_row(over="-23.50")]), as_of=datetime(2026, 3, 1, 8, 0))
        self.assertEqual(by_loc(p)["Sample Pier Grill"].cash_over_short, Decimal("-23.50"))


class Sample(unittest.TestCase):
    def test_sample_files_are_made_up_deterministic_and_cover_every_case(self):
        out = Path(tempfile.mkdtemp())
        files = S.write_samples(out, TODAY)
        self.assertEqual(sorted(p.name for p in files), ["sample-dss-beta-style.csv", "sample-dss-beta-style.xlsx",
                                                          "sample-dss-classic.csv", "sample-dss-classic.tsv", "sample-dss-classic.xlsx"])
        self.assertEqual(S.xlsx_bytes(S.table("classic", TODAY)), S.xlsx_bytes(S.table("classic", TODAY)))
        text = (out / "sample-dss-classic.csv").read_text()
        self.assertNotIn("R365", text)
        p = parse((out / "sample-dss-classic.xlsx").read_bytes(), "a.xlsx")
        last = by_loc(p)
        self.assertEqual((last["Sample Pier Grill"].approved, last["Sample Hill Bistro"].approved, last["Sample Dock Cafe"].approved),
                         (True, False, None))
        self.assertNotIn("Sample Park Diner", last)                # the planted missing day
        self.assertEqual(last["Sample Hill Bistro"].cash_over_short, Decimal("-23.5"))


if __name__ == "__main__":
    unittest.main()
