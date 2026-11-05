"""Builds the invented DSS export files in this folder. Run it only to regenerate them:

    python tests/fixtures/dss_matrix/build_fixtures.py

Everything is made up ("Sample ..." places, invented amounts, no ids). The output is the same every time, and a
test fails if the committed files drift from what this script produces. See README.md and MANIFEST.toml.
"""

import csv
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent.parent))

from dssreport.dss_export_sample import BETA_HEADERS, CLASSIC_HEADERS, xlsx_bytes   # noqa: E402


def _xlsx_unix(rows):
    """xlsx_bytes, but with the zip 'version made by' high byte set to 3 (Unix), as in the committed
    fixtures. zipfile writes 0 (MS-DOS) on Windows, which made the byte-for-byte check fail there."""
    data = bytearray(xlsx_bytes(rows))
    sig = b"PK\x01\x02"  # central directory file header
    i = data.find(sig)
    while i != -1:
        data[i + 5] = 3
        i = data.find(sig, i + 4)
    return bytes(data)

PLACES = [("Sample Pier Grill", "101"), ("Sample Hill Bistro", "102"), ("Sample Dock Cafe", "103"),
          ("Sample Park Diner", "104"), ("Sample Mill Tavern", "105")]
DAY = (2026, 3, 13)


def classic_row(approval, loc, num, day, over, count, status=None, net="3000.0000"):
    y, m, d = day
    status = status or ("Approved" if approval == "Approved" else "In Progress")
    return [approval, status, loc, num, f"{loc} {m:02d}/{d:02d}/{y}", f"{m}/{d}/{y} 12:00:00 AM", net, "2910.0000",
            over, "90", "Yes" if approval == "Approved" else "No", "", "2026-03-14T08:15:00.0000000Z", "Sample User",
            "2026-03-14T09:00:00.0000000Z", "", "0.0000", str(count), "", "", "", "", ""]


def beta_row(status, loc, day, over, net="3000.0000", date_text=None):
    y, m, d = day
    return [status, loc, date_text or f"{m:02d}/{d:02d}/{y}", "No", net, "0.0000", "0.0000000000", "0", "2910.0000",
            over, "50"]


def to_csv(rows, delimiter=",", eol="\r\n", bom=False) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, delimiter=delimiter, lineterminator=eol)
    for r in rows:
        w.writerow(r)
    data = out.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


def classic_table(rows, count=None):
    """Heading row + one classic row per tuple; every row repeats __count (the number of rows unless told)."""
    n = len(rows) if count is None else count
    return [CLASSIC_HEADERS] + [classic_row(*r, n) for r in rows]


# ----------------------------------------------------------------------------------------- the pair (Q2, Q7)
# (approval word, place, number, day, over/short)
PAIR_CLASSIC = [("Approved", PLACES[0][0], "101", DAY, "1.2500"), ("Unapproved", PLACES[1][0], "102", DAY, "-23.5000"),
                ("Approved", PLACES[2][0], "103", DAY, "0.0000"), ("Unapproved", PLACES[3][0], "104", DAY, "0.0000"),
                ("Approved", PLACES[4][0], "105", DAY, "12.0000")]


def pair_beta(words):
    return [BETA_HEADERS] + [beta_row(w, p[1], DAY, p[4]) for w, p in zip(words, PAIR_CLASSIC)]


# ----------------------------------------------------------------------------------------- long lists (Q5)
def long_rows(n_places, n_days, newest_first=True):
    out = []
    for dd in range(n_days):
        day = (2026, 3, 13 - dd) if dd < 13 else (2026, 2, 28 - (dd - 13)) if dd < 41 else None
        for i in range(n_places):
            out.append((day, f"Sample Place {i + 1:02d}", str(200 + i), dd, i))
    if not newest_first:
        out.reverse()
    return out


def long_classic(total, shown):
    allrows = long_rows(10, total // 10)
    rows = []
    for day, loc, num, dd, i in allrows[:shown]:
        appr = "Unapproved" if (dd == 0 and i in (2, 6)) else "Approved"
        rows.append(classic_row(appr, loc, num, day, f"{((dd + i) % 5) * 0.25:.4f}", total))
    return [CLASSIC_HEADERS] + rows


def long_beta(shown):
    rows = []
    for day, loc, num, dd, i in long_rows(10, 25)[:shown]:
        rows.append(beta_row("In Progress" if (dd == 0 and i in (2, 6)) else "Approved", loc, day,
                             f"{((dd + i) % 5) * 0.25:.4f}"))
    return [BETA_HEADERS] + rows


# ----------------------------------------------------------------------------------------- the files
def build() -> dict:
    f = {}
    f["pair_classic.csv"] = to_csv(classic_table(PAIR_CLASSIC))
    f["pair_beta_lines_up.csv"] = to_csv(pair_beta(["Approved", "In Progress", "Approved", "In Progress", "Approved"]),
                                         bom=True)
    f["pair_beta_does_not_line_up.csv"] = to_csv(pair_beta(["Approved", "Completed", "Approved", "In Progress",
                                                            "In Progress"]), bom=True)

    # Over/Short with both signs, and the spellings of a negative (Q1)
    signs = [("-23.5000", (2026, 3, 8)), ("23.5000", (2026, 3, 9)), ("(23.50)", (2026, 3, 10)),
             ("23.50-", (2026, 3, 11)), ("0.0000", (2026, 3, 12)), ("-0.0000", (2026, 3, 13))]
    f["over_short_signs_classic.csv"] = to_csv(classic_table(
        [("Unapproved", PLACES[0][0], "101", day, ov) for ov, day in signs]))
    f["over_short_signs_beta.csv"] = to_csv(
        [BETA_HEADERS, beta_row("In Progress", PLACES[0][0], DAY, "-23.5000"),
         beta_row("In Progress", PLACES[1][0], DAY, "23.5000"), beta_row("Approved", PLACES[2][0], DAY, "-23.5000")],
        bom=True)

    # renamed and new headings (Q6, Q9)
    f["headings_renamed_known.csv"] = to_csv(
        [["DSS Status", "Location Name", "Business Date", "Total Net Sales", "Cash Over/Short"],
         ["Unapproved", PLACES[1][0], "03/13/2026", "3000.0000", "-23.5000"],
         ["Approved", PLACES[0][0], "03/13/2026", "3000.0000", "0.0000"]], bom=True)
    f["headings_renamed_unknown.csv"] = to_csv(
        [["Approval", "Site", "Day", "Sales", "Cash Variance Amount"],
         ["Unapproved", PLACES[1][0], "03/13/2026", "3000.0000", "-23.5000"]], bom=True)
    extra = ["POS Import Status", "Missing Receipts", "Payment Exceptions", "Balanced", "Approved By", "Approved On"]
    f["headings_new_columns_beta.csv"] = to_csv(
        [BETA_HEADERS + extra,
         beta_row("In Progress", PLACES[1][0], DAY, "-23.5000") + ["Not received", "2", "1", "No", "", ""],
         beta_row("Approved", PLACES[0][0], DAY, "0.0000") + ["Received", "0", "0", "Yes", "Sample User", "03/14/2026"]],
        bom=True)
    f["headings_beta_gains_approval_column.csv"] = to_csv(
        [["Status", "Approval Status"] + BETA_HEADERS[1:],
         ["In Progress", "Unapproved"] + beta_row("x", PLACES[1][0], DAY, "-23.5000")[1:],
         ["Completed", "Approved"] + beta_row("x", PLACES[0][0], DAY, "0.0000")[1:]], bom=True)

    # a missing row (Q3)
    f["missing_row_classic_with_count.csv"] = to_csv(classic_table(
        [r for r in PAIR_CLASSIC if r[1] != PLACES[3][0]], count=5))
    f["missing_row_beta_no_count.csv"] = to_csv(
        [BETA_HEADERS] + [beta_row(w, p[1], DAY, p[4]) for w, p in
                          zip(["Approved", "In Progress", "Approved", "In Progress", "Approved"], PAIR_CLASSIC)
                          if p[1] != PLACES[3][0]], bom=True)

    # long lists (Q5)
    f["long_classic_300_complete.csv"] = to_csv(long_classic(300, 300))
    f["long_classic_250_of_400.csv"] = to_csv(long_classic(400, 250))
    f["long_beta_250_no_count.csv"] = to_csv(long_beta(250), bom=True)

    # byte-order mark, line ends, dates, numbers (Q8)
    f["format_classic_with_bom.csv"] = to_csv(classic_table(PAIR_CLASSIC[:2]), bom=True)
    f["format_beta_no_bom_lf.csv"] = to_csv(pair_beta(["Approved", "In Progress", "Approved", "In Progress",
                                                       "Approved"]), eol="\n")
    f["format_dates_iso.csv"] = to_csv(
        [BETA_HEADERS, beta_row("Approved", PLACES[0][0], DAY, "0.0000", date_text="2026-03-13"),
         beta_row("In Progress", PLACES[1][0], DAY, "-23.5000", date_text="2026-03-13")], bom=True)
    f["format_dates_day_first.csv"] = to_csv(
        [BETA_HEADERS, beta_row("Approved", PLACES[0][0], DAY, "0.0000", date_text="13/03/2026"),
         beta_row("In Progress", PLACES[1][0], DAY, "-23.5000", date_text="13/03/2026")], bom=True)
    f["format_dates_ambiguous.csv"] = to_csv(
        [BETA_HEADERS, beta_row("Approved", PLACES[0][0], DAY, "0.0000", date_text="03/04/2026"),
         beta_row("In Progress", PLACES[1][0], DAY, "-23.5000", date_text="03/04/2026")], bom=True)
    f["format_dates_words.csv"] = to_csv(
        [BETA_HEADERS, beta_row("Approved", PLACES[0][0], DAY, "0.0000", date_text="Mar 13, 2026"),
         beta_row("In Progress", PLACES[1][0], DAY, "-23.5000", date_text="13 March 2026")], bom=True)
    num = ["$23.50", "(23.50)", "23.50-", "−23.50", "1,234.50", "-", "n/a"]
    f["format_numbers.csv"] = to_csv(
        [BETA_HEADERS] + [beta_row("In Progress", PLACES[0][0], (2026, 3, 7 + i), v) for i, v in enumerate(num)],
        bom=True)
    f["format_semicolon_comma_decimal.csv"] = to_csv(
        [BETA_HEADERS] + [beta_row("In Progress", PLACES[0][0], DAY, "-23,50", net="3000,00")], delimiter=";", bom=True)

    # Excel and tab-separated variants (Q4)
    classic = classic_table(PAIR_CLASSIC)
    f["variant_classic.tsv"] = to_csv(classic, delimiter="\t")
    f["variant_beta.tsv"] = to_csv(pair_beta(["Approved", "In Progress", "Approved", "In Progress", "Approved"]),
                                   delimiter="\t", bom=True)
    from datetime import date
    typed = [classic[0]] + [r[:5] + [date(*DAY)] + [float(r[6]), float(r[7]), float(r[8])] + [90, r[10]] + r[11:]
                            for r in classic[1:]]
    f["variant_classic_typed_cells.xlsx"] = _xlsx_unix(typed)
    f["variant_beta_text_cells.xlsx"] = _xlsx_unix(pair_beta(["Approved", "In Progress", "Approved", "In Progress",
                                                              "Approved"]))
    f["variant_beta_title_and_footer.xlsx"] = _xlsx_unix(
        [["Daily Sales Summary", "", ""], ["Sample Group A", "", ""], [""]] +
        pair_beta(["Approved", "In Progress", "Approved", "In Progress", "Approved"]) + [["Total Records: 5"]])
    return f


def main():
    for name, data in build().items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(build())} files to {HERE}")


if __name__ == "__main__":
    main()
