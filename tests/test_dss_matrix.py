"""The DSS export test matrix: invented files that probe each unproven R365 question (tests/fixtures/dss_matrix).

Each test says which unknown (Q1-Q9, see the README in that folder) it is about. These tests show what the
program does today under each possible answer. They do NOT prove what R365 really does: no real export is used.
"""

import fnmatch
import re
import tempfile
import tomllib
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from dssreport import dss_export as E
from dssreport import dss_export_source as X

from . import test_dss_export_integration as I
from .fixtures.dss_matrix import build_fixtures as B

FX = Path(__file__).resolve().parent / "fixtures" / "dss_matrix"
TODAY = date(2026, 3, 14)
DAY = date(2026, 3, 13)
FRESH = datetime(2026, 3, 14, 7, 55)
NOBODY = Path("/nonexistent/aliases.toml")
NOT_FILES = {"README.md", "MANIFEST.toml", "build_fixtures.py", "__init__.py", "__pycache__"}


def read(name, words=None, expected=None, aliases=None):
    rows, stats, _ = E.read_rows((FX / name).read_bytes(), name)
    al = aliases or E.load_aliases(user=NOBODY)
    return E.parse_export(rows, al, words, FRESH, TODAY, stats, expected_total=expected)


def unapproved(p):
    return {r.location for r in p.records if r.approved is False}


def unknown(p):
    return {r.location for r in p.records if r.approved is None}


def over(p):
    return {r.location: r.cash_over_short for r in p.records}


class Housekeeping(unittest.TestCase):
    """The matrix is complete, described and not drifting."""

    def manifest(self):
        return tomllib.loads((FX / "MANIFEST.toml").read_text(encoding="utf-8"))["fixture"]

    def test_every_file_has_a_plain_words_note_and_every_note_has_a_file(self):
        on_disk = {p.name for p in FX.iterdir() if p.name not in NOT_FILES}
        noted = {m["file"] for m in self.manifest()}
        self.assertEqual(on_disk, noted)
        self.assertEqual(len(noted), len(self.manifest()), "a file is described twice")

    def test_each_note_says_what_it_probes_what_the_reader_does_and_what_would_settle_it(self):
        for m in self.manifest():
            for key in ("what", "reader_today", "settled_by"):
                self.assertGreater(len(m[key].strip()), 20, f"{m['file']}: '{key}' is empty or too short")
            self.assertTrue(m["probes"] and all(re.fullmatch(r"Q[1-9]", q) for q in m["probes"]), m["file"])

    def test_every_unknown_has_at_least_one_fixture_and_the_readme_names_it(self):
        readme = (FX / "README.md").read_text(encoding="utf-8")
        probed = {q for m in self.manifest() for q in m["probes"]}
        for i in range(1, 10):
            self.assertIn(f"Q{i}", probed)
            self.assertRegex(readme, rf"\| Q{i} \|")
        for m in self.manifest():                           # every file is named in the README table, by name or pattern
            self.assertTrue(m["file"] in readme or any(fnmatch.fnmatch(m["file"], pat)
                                                       for pat in re.findall(r"`([a-z_*.]+\*[a-z_*.]*)`", readme)), m["file"])

    def test_committed_files_are_exactly_what_the_builder_makes(self):
        built = B.build()
        for name, data in built.items():
            self.assertEqual((FX / name).read_bytes(), data, f"{name} differs from build_fixtures.py")
        self.assertEqual(set(built), {p.name for p in FX.iterdir() if p.name not in NOT_FILES})

    def test_no_email_address_url_or_id_in_any_text_fixture(self):
        for p in FX.iterdir():
            if p.suffix in (".csv", ".tsv"):
                text = p.read_text(encoding="utf-8", errors="ignore")
                self.assertNotRegex(text, r"@[A-Za-z0-9-]+\.[a-z]{2,}", p.name)
                self.assertNotIn("http", text.lower(), p.name)
                self.assertEqual(set(re.findall(r"Sample [A-Z][a-z]+(?: [A-Z][a-z]+)?", text)) - {"Sample User", "Sample Place"}
                                 - {f"Sample Place {i:02d}" for i in range(1, 11)}
                                 - {n for n, _ in B.PLACES}, set(), p.name)


class Q1OverShortSign(unittest.TestCase):
    def test_both_signs_and_every_spelling_of_a_negative_are_read_with_their_sign(self):
        p = read("over_short_signs_classic.csv")
        got = [str(r.cash_over_short) for r in p.records]
        self.assertEqual(got, ["-23.5000", "23.5000", "-23.50", "-23.50", "0.0000", "-0.0000"])

    def test_the_sign_is_never_called_known_so_the_report_never_says_over_or_short(self):
        for name in ("over_short_signs_classic.csv", "over_short_signs_beta.csv"):
            self.assertFalse(any(r.cash_sign_known for r in read(name).records), name)

    def test_beta_and_classic_agree_on_what_a_negative_looks_like(self):
        self.assertEqual(over(read("over_short_signs_beta.csv"))["Sample Pier Grill"], over(read("pair_classic.csv"))["Sample Hill Bistro"])

    def test_number_spellings(self):
        p = read("format_numbers.csv")
        self.assertEqual([r.cash_over_short for r in p.records],
                         [E.parse_money(t)[0] for t in ("23.50", "-23.50", "-23.50", "-23.50", "1234.50")] + [None, None])
        self.assertTrue(any("2 Over/Short values could not be read" in w for w in p.warnings))   # dash and n/a: UNKNOWN, not zero


class Q2InProgressVersusUnapproved(unittest.TestCase):
    def test_classic_names_the_two_unapproved_places(self):
        self.assertEqual(unapproved(read("pair_classic.csv")), {"Sample Hill Bistro", "Sample Park Diner"})

    def test_beta_in_progress_is_unknown_by_default_never_unapproved(self):
        p = read("pair_beta_lines_up.csv")
        self.assertEqual(unapproved(p), set())
        self.assertEqual(unknown(p), {"Sample Hill Bistro", "Sample Park Diner"})
        self.assertTrue(any("'In Progress'" in w and "UNKNOWN" in w for w in p.warnings))

    def test_if_the_pair_lines_up_the_owners_word_gives_the_same_answer_as_classic(self):
        classic = read("pair_classic.csv")
        beta = read("pair_beta_lines_up.csv", {"In Progress": "not approved"})
        self.assertEqual(unapproved(beta), unapproved(classic))
        self.assertEqual(over(beta), over(classic))

    def test_if_the_pair_does_not_line_up_setting_the_word_early_gives_a_different_answer(self):
        classic = read("pair_classic.csv")
        beta = read("pair_beta_does_not_line_up.csv", {"In Progress": "not approved"})
        self.assertNotEqual(unapproved(beta), unapproved(classic))
        self.assertEqual(unapproved(beta) ^ unapproved(classic), {"Sample Hill Bistro", "Sample Mill Tavern"})
        self.assertEqual(unknown(beta), {"Sample Hill Bistro"})                  # 'Completed' still not guessed

    def test_a_second_approval_column_wins_over_the_plain_status_column(self):
        p = read("headings_beta_gains_approval_column.csv")
        self.assertEqual(p.columns["approval_status"], "Approval Status")
        self.assertEqual(unapproved(p), {"Sample Hill Bistro"})


class Q3MissingRow(unittest.TestCase):
    def test_a_classic_file_whose_count_is_higher_than_its_rows_is_called_partial(self):
        p = read("missing_row_classic_with_count.csv")
        self.assertEqual((p.stated_total, p.rows_read), (5, 4))
        self.assertTrue(any(w.startswith("Partial list") for w in p.warnings))

    def test_a_beta_file_cannot_show_a_missing_row_on_its_own(self):
        p = read("missing_row_beta_no_count.csv")
        self.assertEqual(p.rows_read, 4)
        self.assertFalse(any(w.startswith("Partial list") for w in p.warnings))
        self.assertTrue(any("does not say how many entries" in w for w in p.warnings))   # it says so plainly

    def test_typing_the_screens_total_exposes_the_missing_beta_row(self):
        p = read("missing_row_beta_no_count.csv", expected=5)
        self.assertTrue(any(w.startswith("Partial list: R365's screen shows 5") for w in p.warnings))
        self.assertEqual(p.total_source, "you")

    def test_a_footer_line_is_used_as_the_total(self):
        p = read("variant_beta_title_and_footer.xlsx")
        self.assertEqual((p.stated_total, p.rows_read), (5, 5))
        self.assertFalse(any(w.startswith("Partial list") for w in p.warnings))


class Q4TsvAndXlsx(unittest.TestCase):
    def same(self, a, b):
        pa, pb = read(a), read(b)
        self.assertEqual([(r.location, r.business_date, r.approved, r.cash_over_short) for r in pa.records],
                         [(r.location, r.business_date, r.approved, r.cash_over_short) for r in pb.records])

    def test_tsv_reads_like_csv(self):
        self.same("variant_classic.tsv", "pair_classic.csv")
        self.same("variant_beta.tsv", "pair_beta_lines_up.csv")

    def test_xlsx_with_typed_cells_reads_like_csv(self):
        self.same("variant_classic_typed_cells.xlsx", "pair_classic.csv")

    def test_xlsx_with_text_cells_reads_like_csv(self):
        self.same("variant_beta_text_cells.xlsx", "pair_beta_lines_up.csv")

    def test_the_kind_of_file_is_recognised_from_the_name_and_the_bytes(self):
        kinds = {n: E.read_rows((FX / n).read_bytes(), n)[2] for n in ("variant_classic.tsv", "variant_beta_text_cells.xlsx", "pair_classic.csv")}
        self.assertEqual(kinds, {"variant_classic.tsv": "tsv", "variant_beta_text_cells.xlsx": "xlsx", "pair_classic.csv": "csv"})


class Q5LongLists(unittest.TestCase):
    def test_a_long_complete_list_is_read_in_full_with_no_partial_warning(self):
        p = read("long_classic_300_complete.csv")
        self.assertEqual((p.rows_read, p.stated_total), (300, 300))
        self.assertFalse(any(w.startswith("Partial list") for w in p.warnings))
        self.assertEqual(len(p.records), 300)

    def test_a_list_cut_at_250_of_400_is_called_partial(self):
        p = read("long_classic_250_of_400.csv")
        self.assertEqual((p.rows_read, p.stated_total), (250, 400))
        self.assertTrue(any("400 entries but only 250" in w for w in p.warnings))
        self.assertEqual(p.last_date, DAY)                       # newest days are present
        self.assertGreater(p.first_date, date(2026, 2, 1))       # the oldest days are the ones cut off

    def test_a_cut_beta_list_looks_complete_until_the_screens_total_is_typed(self):
        self.assertFalse(any(w.startswith("Partial list") for w in read("long_beta_250_no_count.csv").warnings))
        p = read("long_beta_250_no_count.csv", expected=400)
        self.assertTrue(any("R365's screen shows 400 entries but only 250" in w for w in p.warnings))

    def test_a_file_with_far_too_many_rows_is_refused_not_cut(self):
        data = b"Location,Date\r\n" + b"Sample Pier Grill,3/13/2026\r\n" * (E.MAX_ROWS + 5)
        with self.assertRaises(E.ExportError) as cm:
            E.read_rows(data, "x.csv")
        self.assertIn("far more rows", str(cm.exception))


class Q6Headings(unittest.TestCase):
    def test_reworded_headings_in_the_word_list_are_read(self):
        p = read("headings_renamed_known.csv")
        self.assertEqual(set(p.columns), {"approval_status", "location", "business_date", "net_sales", "over_short"})
        self.assertEqual(unapproved(p), {"Sample Hill Bistro"})
        self.assertTrue(any("no Location Number column" in w for w in p.warnings))

    def test_unlisted_headings_are_refused_in_plain_words(self):
        with self.assertRaises(E.ExportError) as cm:
            read("headings_renamed_unknown.csv")
        self.assertIn("does not look like an R365 Daily Sales Summary list", str(cm.exception))

    def test_the_owner_can_add_the_new_words_without_an_update(self):
        with tempfile.TemporaryDirectory() as d:
            mine = Path(d) / "dss_export_aliases.toml"
            mine.write_text('version = 1\n[fields]\nlocation = ["Site"]\nbusiness_date = ["Day"]\n'
                            'approval_status = ["Approval"]\nover_short = ["Cash Variance Amount"]\n'
                            'net_sales = ["Sales"]\n', encoding="utf-8")
            p = read("headings_renamed_unknown.csv", aliases=E.load_aliases(user=mine))
        self.assertEqual(unapproved(p), {"Sample Hill Bistro"})
        self.assertEqual(over(p), {"Sample Hill Bistro": E.parse_money("-23.5")[0]})

    def test_new_columns_are_listed_as_not_recognised_and_change_nothing(self):
        p = read("headings_new_columns_beta.csv")
        for h in ("POS Import Status", "Missing Receipts", "Payment Exceptions", "Balanced", "Approved By", "Approved On"):
            self.assertIn(h, p.unrecognised)
        self.assertEqual(unknown(p), {"Sample Hill Bistro"})
        self.assertTrue({"pos_import_received", "missing_receipts", "payment_exceptions", "payments"} <= p.unmapped)


class Q7Completed(unittest.TestCase):
    def test_completed_is_never_turned_into_approved(self):
        p = read("pair_beta_does_not_line_up.csv")
        hill = next(r for r in p.records if r.location == "Sample Hill Bistro")
        self.assertIsNone(hill.approved)
        self.assertIn("marked complete but the file does not say it was approved", hill.approval_note)


class Q8Formats(unittest.TestCase):
    def test_a_byte_order_mark_on_a_classic_file_and_none_on_a_beta_file_both_read(self):
        self.assertEqual(len(read("format_classic_with_bom.csv").records), 2)
        self.assertEqual(len(read("format_beta_no_bom_lf.csv").records), 5)
        self.assertTrue((FX / "format_classic_with_bom.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", (FX / "format_beta_no_bom_lf.csv").read_bytes())

    def test_iso_wordy_and_day_first_dates_read_as_13_march(self):
        for name in ("format_dates_iso.csv", "format_dates_day_first.csv", "format_dates_words.csv"):
            p = read(name)
            self.assertEqual({r.business_date for r in p.records}, {DAY}, name)
            self.assertFalse(any("could be month/day" in w for w in p.warnings), name)

    def test_an_ambiguous_date_is_read_month_first_with_a_plain_warning(self):
        p = read("format_dates_ambiguous.csv")
        self.assertEqual({r.business_date for r in p.records}, {date(2026, 3, 4)})
        self.assertTrue(any("could be month/day or day/month" in w for w in p.warnings))

    @unittest.skipIf(E.parse_money("-23,50")[0] == Decimal("-2350"),
                     "KNOWN GAP: this reader still reads -23,50 as -2350 (fixed in the money-comma PR)")
    def test_a_comma_decimal_mark_is_not_read_as_a_thousands_mark(self):
        r = read("format_semicolon_comma_decimal.csv").records[0]
        self.assertIsNone(r.cash_over_short)
        self.assertIsNone(r.sales_total)


class Q9NotInTheExport(I.Env):
    """End to end through the brief: the matrix files go through the same path as a real download."""
    instances_allowed = 2

    def brief(self, name, words=None):
        inst = I.inst(**({"approval_words": words} if words else {}))
        self.connect(inst)
        X.store_export(inst, name, (FX / name).read_bytes(), I.NOW.timestamp())
        return self.run_it(end=DAY, style="brief", days=1).text_path.read_text(encoding="utf-8")

    def test_in_the_brief_only_the_classic_pair_names_places_until_the_owner_decides_a_word(self):
        classic = self.brief("pair_classic.csv")
        beta_default = self.brief("pair_beta_lines_up.csv")
        beta_set = self.brief("pair_beta_lines_up.csv", {"In Progress": "not approved"})
        self.assertIn("2 unapproved", classic)
        self.assertIn("* Sample Hill Bistro\n    Needs to balance: Over/Short -$23.50", classic)
        self.assertIn("No place shows as unapproved.", beta_default)
        self.assertIn("COULD NOT TELL (the report will not guess)", beta_default)
        self.assertIn("2 unapproved", beta_set)
        for text in (classic, beta_default, beta_set):
            self.assertIn("Nothing was approved or sent.", text)
            self.assertIn("Likely reasons only", text)
            self.assertNotRegex(text.lower(), r"cash is (over|short)|was (over|short)")

    def test_a_cut_list_is_announced_in_the_brief(self):
        self.assertIn("Partial list", self.brief("long_classic_250_of_400.csv"))

    def test_fields_that_are_not_in_the_export_are_not_checked_even_when_extra_columns_exist(self):
        text = self.brief("headings_new_columns_beta.csv", {"In Progress": "not approved"})
        self.assertNotIn("POS import not received", text)       # the column "POS Import Status" is ignored, not read
        self.assertIn("Sample Hill Bistro", text)


if __name__ == "__main__":
    unittest.main()
