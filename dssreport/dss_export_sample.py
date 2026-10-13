"""Made-up sample DSS list exports, so a person can try the "DSS export file" source without R365.

Everything here is invented: "Sample Group A", invented restaurants, invented amounts. Two layouts are made:
  classic - the headings of R365's classic DSS list export
  beta    - a guess at the newer list (different heading words, a title line, a "Total Records" footer),
            covered by the heading-alias table; one real beta file is needed to confirm it
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

CLASSIC_HEADERS = ["Approval Status", "Location", "Location Number", "Name", "Date", "Attachment", "Net Sales",
                   "Total Deposit", "Over/Short", "Guest Count", "Steps Complete", "Log Entries", "Paidout Total",
                   "Created By", "Created On", "Modified By", "Modified On"]
BETA_HEADERS = ["Status", "Location Name", "Location #", "DSS Name", "Business Date", "Attachments", "Net Sales",
                "Deposit Total", "Over (Short)", "Guests", "Steps Completed", "Log Entry Count", "Paid Outs",
                "Created By", "Created", "Modified By", "Last Modified"]


@dataclass
class Formula:
    """An Excel formula cell: text plus the value Excel last stored for it (the program never calculates)."""
    text: str
    cached: object = None


def sample_rows(layout: str = "classic", today: Optional[date] = None, days: int = 14) -> List[List[object]]:
    """Rows (list of cell values) for a made-up list ending on the business day before `today`.

    Planted for the last business day: one entry Approved, one Unapproved with a $23.50 shortage, one In Progress
    (approval unknown), and one location with no row at all. Earlier days: mostly Approved, one Completed,
    one overage.
    """
    today = today or date.today()
    last = today - timedelta(days=1)
    beta = layout == "beta"
    rows: List[List[object]] = []
    for offset in range(days):
        day = last - timedelta(days=days - 1 - offset)
        for i, (loc, num) in enumerate(LOCATIONS):
            status, over = "Approved", [1.25, -0.5, 0.0, 2.0][(offset + i) % 4]
            if day == last:
                if loc == "Sample Park Diner":
                    continue                                    # no row for the last day
                status, over = {"Sample Pier Grill": ("Approved", 1.25), "Sample Hill Bistro": ("Unapproved", -23.5),
                                "Sample Dock Cafe": ("In Progress", 0.0)}[loc]
            elif day == last - timedelta(days=3) and loc == "Sample Hill Bistro":
                over = 12.0
            elif day == last - timedelta(days=4) and loc == "Sample Dock Cafe":
                status = "Completed"
            sales = round(3000 + 400 * i + 17 * offset, 2)
            made = datetime(day.year, day.month, day.day, 6, 0) + timedelta(days=1)
            rows.append([status, loc, num, f"DSS {day.isoformat()}", day, "", sales, round(sales * 0.97, 2), over,
                         90 + offset + i, "5/5" if status != "In Progress" else "3/5", 2 + i, 0.0,
                         "Sample User", made, "Sample User", made + timedelta(hours=1, minutes=30)])
    return rows


def _fmt(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%m/%d/%Y %I:%M %p")
    if isinstance(value, date):
        return value.strftime("%m/%d/%Y")
    if isinstance(value, float):
        return f"{value:.2f}"
    return "" if value is None else str(value)


def table(layout: str = "classic", today: Optional[date] = None, days: int = 14) -> List[List[object]]:
    """Heading rows + data rows (+ the classic list's shape, or the beta list's title line and footer)."""
    data = sample_rows(layout, today, days)
    if layout == "beta":
        return ([["Daily Sales Summaries"], ["Sample Group A"], [], BETA_HEADERS] + data + [[], [f"Total Records: {len(data)}"]])
    return [CLASSIC_HEADERS] + data


def csv_bytes(layout="classic", today=None, delimiter=",", days: int = 14) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    for row in table(layout, today, days):
        w.writerow([_fmt(c) for c in row])
    return out.getvalue().encode("utf-8")


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
