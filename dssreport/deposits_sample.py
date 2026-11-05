"""Made-up files to try the deposit matcher: a DSS list and a bank statement (CSV, OFX and a decimal-comma CSV).

Every place, number and amount here is invented. Dates are fixed (March 2026), so the files never go stale and
the same cases always come out the same way:

  Sample Pier Grill     Tue 10   exact match, bank text names the place
  Sample Hill Bistro    Tue 10   exact match, found by the place number in the bank text
  Sample Hill Bistro    Wed 11   the same bank line twice in the file (duplicate)
  Sample Park Cafe      Tue 10   split deposit (two lines)
  Sample Dock Kitchen   Fri 13 + Sat 14   one deposit covering two days, posted Monday
  Sample Mill Tavern    Tue 10   near miss ($5.00 short), equal to the Over/Short figure
  Sample Lake Deli      Tue 10   swapped digits (1,234.56 expected, 1,243.56 in the bank)
  Sample Lake Deli      Wed 11   deposit written with a decimal comma in the DSS list (not read, not guessed)
  Sample Row Diner      Tue 10   no deposit at all
  Sample Pier Grill / Sample Park Cafe   Thu 12   same amount, one bank line that names neither
  Sample Pier Grill     Fri 13   exact match that posted on Monday (weekend timing)
  Sample Pier Grill     Sun 15   bank file ends before the deposit could have posted
"""

import csv
import io
from decimal import Decimal
from pathlib import Path
from typing import List

# place, number, day-of-March, deposit text as written in the DSS list, over/short
DSS_ROWS = [
    ("Sample Pier Grill", "101", 10, "2910.00", "0.00"),
    ("Sample Hill Bistro", "102", 10, "1840.50", "0.00"),
    ("Sample Hill Bistro", "102", 11, "625.00", "0.00"),
    ("Sample Park Cafe", "103", 10, "1200.00", "0.00"),
    ("Sample Dock Kitchen", "104", 13, "2000.00", "0.00"),
    ("Sample Dock Kitchen", "104", 14, "1500.00", "0.00"),
    ("Sample Mill Tavern", "105", 10, "1000.00", "-5.00"),
    ("Sample Lake Deli", "106", 10, "1234.56", "0.00"),
    ("Sample Lake Deli", "106", 11, "1234,50", "0.00"),
    ("Sample Row Diner", "107", 10, "800.00", "0.00"),
    ("Sample Pier Grill", "101", 12, "500.00", "0.00"),
    ("Sample Park Cafe", "103", 12, "500.00", "0.00"),
    ("Sample Pier Grill", "101", 15, "3100.00", "0.00"),
    ("Sample Pier Grill", "101", 9, "0.00", "0.00"),
    ("Sample Pier Grill", "101", 13, "700.00", "0.00"),
]

# day-of-March, bank text, amount, reference
BANK_ROWS = [
    (9, "OPENING NOTE", "0.00", ""),
    (11, "SAMPLE PIER GRILL DEPOSIT", "2910.00", "P1"),
    (10, "COUNTER DEPOSIT STORE 102", "1840.50", "P2"),
    (12, "COUNTER DEPOSIT STORE 102", "625.00", "P3"),
    (12, "COUNTER DEPOSIT STORE 102", "625.00", "P3"),
    (11, "SAMPLE PARK CAFE DEPOSIT", "700.00", "P4"),
    (11, "SAMPLE PARK CAFE DEPOSIT", "500.00", "P5"),
    (16, "SAMPLE DOCK KITCHEN DEPOSIT", "3500.00", "P6"),
    (11, "SAMPLE MILL TAVERN DEPOSIT", "995.00", "P7"),
    (12, "SAMPLE LAKE DELI DEPOSIT", "1243.56", "P8"),
    (13, "COUNTER DEPOSIT", "500.00", "P9"),
    (11, "MISC CREDIT ADJUSTMENT", "77.77", "P10"),
    (12, "CARD PAYMENT SENT", "-420.00", "P11"),
    (16, "OVERNIGHT SWEEP", "0.00", ""),
    (16, "SAMPLE PIER GRILL DEPOSIT", "700.00", "P12"),
]


def _date(d: int) -> str:
    return f"03/{d:02d}/2026"


def dss_csv() -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Location", "Location Number", "Date", "Net Sales", "Total Deposit", "Over/Short", "Approval Status"])
    for place, num, day, dep, osv in DSS_ROWS:
        w.writerow([place, num, _date(day), "3000.00", dep, osv, "Unapproved"])
    return out.getvalue()


def bank_csv() -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Date", "Description", "Amount", "Reference"])
    for day, text, amt, ref in BANK_ROWS:
        w.writerow([_date(day), text, amt, ref])
    return out.getvalue()


def bank_comma_csv() -> str:
    """The same statement written the way some banks do: semicolons between columns and a comma for cents."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n", delimiter=";")
    w.writerow(["Date", "Description", "Amount", "Reference"])
    for day, text, amt, ref in BANK_ROWS:
        w.writerow([_date(day), text, amt.replace(".", ","), ref])
    return out.getvalue()


def bank_ofx() -> str:
    lines: List[str] = ["OFXHEADER:100", "DATA:OFXSGML", "VERSION:102", "", "<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>",
                        "<BANKTRANLIST>"]
    for n, (day, text, amt, ref) in enumerate(BANK_ROWS):
        lines += ["<STMTTRN>", f"<TRNTYPE>{'CREDIT' if Decimal(amt) >= 0 else 'DEBIT'}",
                  f"<DTPOSTED>202603{day:02d}120000[0:GMT]", f"<TRNAMT>{amt}", f"<FITID>{ref or 'X' + str(n)}",
                  f"<NAME>{text}", "</STMTTRN>"]
    lines += ["</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"]
    return "\n".join(lines) + "\n"


FILES = {"dss_expected.csv": dss_csv, "bank_statement.csv": bank_csv, "bank_statement.ofx": bank_ofx,
         "bank_statement_decimal_comma.csv": bank_comma_csv}


def write_samples(out_dir) -> List[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, make in FILES.items():
        p = out / name
        p.write_bytes(make().encode("utf-8"))
        paths.append(p)
    return paths
