"""Made-up sample DSS list exports, so a person can try the "DSS export file" source without R365.

Everything here is invented: "Sample Group A", invented restaurants, invented amounts. Two layouts are made:
  classic - the exact heading row of R365's classic DSS list export (CSV), with its __count column
  beta    - the exact heading row of the newer ("beta") list export (CSV), with a byte-order mark and no count column
The Excel and TSV samples hold the same tables; whether R365 offers those formats is unknown (the owner's
tested export was CSV), so they only prove the reader copes with them.
Also a tiny, dependency-free .xlsx writer (used for the Excel sample and by the tests).
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence

LOCATIONS = [("Sample Pier Grill", "101"), ("Sample Hill Bistro", "102"), ("Sample Dock Cafe", "103"),
             ("Sample Park Diner", "104")]

# The exact heading rows of two real exports, as observed by the owner's testing (CSV files):
#   classic: UTF-8 without a BOM, comma, CRLF, heading on line 1, a __count column repeated on every row, no footer
#   newer:   UTF-8 WITH a BOM, comma, CRLF, heading on line 1, no count column, no footer
CLASSIC_HEADERS = ["ApprovalStatus", "Status", "Location", "LocationNumber", "Name", "Date", "NetSales", "TotalDeposit",
                   "OverShort", "GuestCount", "StepsComplete", "CreatedBy", "CreatedOn", "ModifiedBy", "ModifiedOn",
                   "DailySalesSummaryId", "PaidoutTotal", "__count", "NewFileName", "Attachment", "AttachmentLinkType",
                   "FileLink", "LogEntries"]
BETA_HEADERS = ["Status", "Location", "Date", "Attachments", "Net Sales", "Total Labor $", "Total Labor Hours",
                "Labor %", "Total Deposit", "Over/Short", "Guest Count"]


@dataclass
class Formula:
    """An Excel formula cell: text plus the value Excel last stored for it (the program never calculates)."""
    text: str
    cached: object = None


def _day_plan(offset: int, i: int, loc: str, day: date, last: date):
    """(approved?, over/short) for one invented location and day. Planted for the last business day: one
    approved, one unapproved (an over/short of -23.50) and one more unapproved/in-progress case; one location has
    no row at all. Earlier days: approved, small amounts, one +12.00."""
    over = [1.25, -0.5, 0.0, 2.0][(offset + i) % 4]
    approved = True
    if day == last:
        approved, over = {"Sample Pier Grill": (True, 1.25), "Sample Hill Bistro": (False, -23.5),
                          "Sample Dock Cafe": (True, 0.0)}[loc]
    elif day == last - timedelta(days=3) and loc == "Sample Hill Bistro":
        over = 12.0
    return approved, over


def sample_rows(layout: str = "classic", today: Optional[date] = None, days: int = 14) -> List[List[str]]:
    """Data rows as the strings a CSV holds, in the observed formats, for a made-up list ending on the business day
    before `today`. In the newer layout 'Unapproved' does not exist: a not-approved entry is 'In Progress'."""
    today = today or date.today()
    last = today - timedelta(days=1)
    beta = layout == "beta"
    plan = []
    for offset in range(days):
        day = last - timedelta(days=days - 1 - offset)
        for i, (loc, num) in enumerate(LOCATIONS):
            if day == last and loc == "Sample Park Diner":
                continue                                          # no row for the last day
            plan.append((offset, i, loc, num, day) + _day_plan(offset, i, loc, day, last))
    rows: List[List[str]] = []
    for n, (offset, i, loc, num, day, approved, over) in enumerate(plan, start=1):
        sales = round(3000 + 400 * i + 17 * offset, 2)
        deposit = round(sales * 0.97, 2)
        guests = 90 + offset + i
        if beta:
            status = "Approved" if approved else "In Progress"
            if day == last and loc == "Sample Dock Cafe":
                status = "In Progress"                           # the newer list's not-yet-approved word
            rows.append([status, loc, day.strftime("%m/%d/%Y"), "No", f"{sales:.4f}", "0.0000", "0.0000000000", "0",
                         f"{deposit:.4f}", f"{over:.4f}", str(guests)])
        else:
            made = datetime(day.year, day.month, day.day, 8, 15) + timedelta(days=1)
            stamp = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S") + ".0000000Z"
            rows.append(["Approved" if approved else "Unapproved", "Approved" if approved else "In Progress", loc, num,
                         f"{loc} {day.strftime('%A')}, {day.strftime('%m/%d/%Y')}",
                         f"{day.month}/{day.day}/{day.year} 12:00:00 AM", f"{sales:.4f}", f"{deposit:.4f}",
                         f"{over:.4f}", str(guests), "Yes" if approved else "No", "", stamp(made), "Sample User",
                         stamp(made + timedelta(minutes=45)), f"{n:08d}-0000-4000-8000-{n:012d}", "0.0000",
                         str(len(plan)), "", "", "", "", ""])
    return rows


def table(layout: str = "classic", today: Optional[date] = None, days: int = 14) -> List[List[str]]:
    """Heading row + data rows exactly as the real CSVs have them (no title lines, no footer)."""
    return [BETA_HEADERS if layout == "beta" else CLASSIC_HEADERS] + sample_rows(layout, today, days)


def csv_bytes(layout="classic", today=None, delimiter=",", days: int = 14) -> bytes:
    """The sample as a CSV file: CRLF line ends; the newer layout starts with a UTF-8 byte-order mark."""
    out = io.StringIO()
    w = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    for row in table(layout, today, days):
        w.writerow(row)
    data = out.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if layout == "beta" else data


# ------------------------------------------------------------------------------------------ tiny .xlsx writer

def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _serial(dt) -> float:
    base = datetime(1899, 12, 30)
    d = dt if isinstance(dt, datetime) else datetime(dt.year, dt.month, dt.day)
    delta = d - base
    return delta.days + delta.seconds / 86400


def xlsx_bytes(rows: Sequence[Sequence[object]], sheet_name: str = "Sheet1", extra_files: Optional[dict] = None) -> bytes:
    """Cells: str -> text, int/float -> number, date -> date, datetime -> date+time, Formula -> formula with
    its stored value, None -> empty. Fixed timestamps so the same input always gives the same bytes."""
    cells = []
    for r, row in enumerate(rows, start=1):
        parts = []
        for c, v in enumerate(row):
            ref = f"{_col(c)}{r}"
            if v is None or v == "":
                continue
            if isinstance(v, Formula):
                cached = v.cached
                if cached is None:
                    parts.append(f'<c r="{ref}"><f>{_esc(v.text.lstrip("="))}</f></c>')
                elif isinstance(cached, str):
                    parts.append(f'<c r="{ref}" t="str"><f>{_esc(v.text.lstrip("="))}</f><v>{_esc(cached)}</v></c>')
                else:
                    parts.append(f'<c r="{ref}"><f>{_esc(v.text.lstrip("="))}</f><v>{cached}</v></c>')
            elif isinstance(v, datetime):
                parts.append(f'<c r="{ref}" s="2"><v>{_serial(v)}</v></c>')
            elif isinstance(v, date):
                parts.append(f'<c r="{ref}" s="1"><v>{_serial(v)}</v></c>')
            elif isinstance(v, bool):
                parts.append(f'<c r="{ref}" t="b"><v>{int(v)}</v></c>')
            elif isinstance(v, (int, float)):
                parts.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                parts.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_esc(str(v))}</t></is></c>')
        cells.append(f'<row r="{r}">{"".join(parts)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{ns}" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{_esc(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": f'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{ns}">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
            '<xf numFmtId="22" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{ns}"><sheetData>{"".join(cells)}</sheetData></worksheet>',
    }
    files.update(extra_files or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text if isinstance(text, bytes) else text.encode("utf-8"))
    return buf.getvalue()


def write_samples(out_dir, today: Optional[date] = None) -> List[Path]:
    """Write the sample files for trying the program. Dates are relative to `today` so the 'last business
    day' is yesterday and the files are fresh when you pick them."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in (("sample-dss-classic.csv", csv_bytes("classic", today)),
                       ("sample-dss-classic.tsv", csv_bytes("classic", today, "\t")),
                       ("sample-dss-classic.xlsx", xlsx_bytes(table("classic", today))),
                       ("sample-dss-beta-style.csv", csv_bytes("beta", today)),
                       ("sample-dss-beta-style.xlsx", xlsx_bytes(table("beta", today)))):
        (out / name).write_bytes(data)
        written.append(out / name)
    return written
