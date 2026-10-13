"""Reading an R365 Daily Sales Summary (DSS) list EXPORT file: CSV, TSV or Excel (.xlsx).

The user downloads the file from R365 themselves and picks it here. This module only READS bytes it is
handed. It never opens the source file for writing, makes no network call, needs no credentials, never runs
anything from the file (Excel formulas and macros are ignored: stored values only), and never logs row
contents. Headings are matched by NAME, not position (docs/EXPORT_SOURCE.md); anything missing or odd is
reported in plain words and shown as UNKNOWN, never guessed.
"""

import csv
import io
import json
import re
import tomllib
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .errors import InputError
from .model import DayRecord
from .paths import app_dir

MAX_FILE_BYTES = 20 * 1024 * 1024          # a DSS list is small; anything bigger is not one
MAX_XML_PART_BYTES = 60 * 1024 * 1024      # one decompressed spreadsheet part
MAX_UNZIPPED_BYTES = 150 * 1024 * 1024     # all parts together (zip-bomb guard)
MAX_ROWS = 200_000
MAX_COLUMNS = 200
HEADER_SCAN_ROWS = 40
ALLOWED_EXTENSIONS = (".csv", ".tsv", ".txt", ".xlsx")
ALIAS_FORMAT = 1

FIELDS = ("location", "location_number", "business_date", "approval_status", "over_short", "net_sales", "deposit")
REQUIRED = ("location", "business_date")
FIELD_WORDS = {"location": "Location", "location_number": "Location Number", "business_date": "Date",
               "approval_status": "Approval Status", "over_short": "Over/Short", "net_sales": "Net Sales",
               "deposit": "Total Deposit"}

# what R365's status words are taken to mean. Only these two are ever turned into a yes/no by default.
BUILT_IN_APPROVAL = {"approved": True, "unapproved": False}
KNOWN_WORD_MEANING = {
    "in progress": "R365 shows the entry as still being worked on",
    "completed": "the entry is marked complete but the file does not say it was approved",
}
# the only extra meanings an owner may give a word (per connection, after checking against a known case)
OVERRIDE_VALUES = {"approved": True, "unapproved": False, "not approved": False}


class ExportError(InputError):
    """The export file could not be read. The message is plain words and never contains row contents."""


# ------------------------------------------------------------------------------------------ headings

def norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


@dataclass
class Aliases:
    fields: Dict[str, List[str]]          # field -> normalised aliases in priority order

    def match(self, headers: List[str]) -> Tuple[Dict[str, int], List[str]]:
        """field -> column index (best alias, then leftmost), plus plain notes about ambiguous columns."""
        normed = [norm(h) for h in headers]
        found, notes = {}, []
        for f in FIELDS:
            for alias in self.fields.get(f, []):
                cols = [i for i, n in enumerate(normed) if n == alias]
                if cols:
                    found[f] = cols[0]
                    if len(cols) > 1:
                        notes.append(f"Two columns look like {FIELD_WORDS[f]}; the first was used.")
                    break
        # one column cannot be two different fields
        seen: Dict[int, str] = {}
        for f in list(found):
            if found[f] in seen:
                del found[f]
            else:
                seen[found[f]] = f
        return found, notes


def _alias_lists(raw: dict, where: str) -> Dict[str, List[str]]:
    if raw.get("version", ALIAS_FORMAT) != ALIAS_FORMAT:
        raise ExportError(f"The heading list {where} is format {raw.get('version')}, but this program reads "
                          f"format {ALIAS_FORMAT}.")
    out = {}
    for f, words in raw.get("fields", {}).items():
        if f not in FIELDS or not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise ExportError(f"The heading list {where} has a problem in '{f}'. Each field needs a list of words.")
        out[f] = [norm(w) for w in words if norm(w)]
    return out


def shipped_alias_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "dss_export_aliases.toml"


def user_alias_path() -> Path:
    return app_dir() / "dss_export_aliases.toml"


def load_aliases(shipped: Optional[Path] = None, user: Optional[Path] = None) -> Aliases:
    """The shipped heading list, plus any words the user added in their own file (added, never replaced)."""
    shipped = Path(shipped) if shipped else shipped_alias_path()
    user = Path(user) if user else user_alias_path()
    try:
        merged = _alias_lists(tomllib.loads(shipped.read_text(encoding="utf-8")), shipped.name)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExportError(f"The built-in heading list could not be read ({type(exc).__name__}).")
    if user.exists():
        try:
            extra = _alias_lists(tomllib.loads(user.read_text(encoding="utf-8")), user.name)
        except (OSError, tomllib.TOMLDecodeError):
            raise ExportError(f"Your own heading list ({user.name}) could not be read. Fix it or remove it.")
        for f, words in extra.items():
            merged[f] = merged.get(f, []) + [w for w in words if w not in merged.get(f, [])]
    return Aliases(merged)


# ------------------------------------------------------------------------------------------ file -> rows

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def read_csv_rows(data: bytes, delimiter: Optional[str] = None) -> List[List[str]]:
    text = _decode(data)
    if delimiter is None:
        lines = [ln for ln in text.splitlines()[:30] if ln.strip()]
        best = max((",", "\t", ";", "|"), key=lambda d: max((ln.count(d) for ln in lines), default=0))
        delimiter = best if max((ln.count(best) for ln in lines), default=0) else ","
    rows = []
    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            rows.append([c for c in row[:MAX_COLUMNS]])
            if len(rows) > MAX_ROWS:
                raise ExportError("This file has far more rows than a DSS list should, so it was refused.")
    except csv.Error:
        raise ExportError("This file could not be read as a table (it is not a normal CSV/TSV file).")
    return rows


_DATE_BUILTIN = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


def _is_date_format(code: str) -> bool:
    cleaned = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code).lower()
    if "general" in cleaned:
        return False
    return bool(re.search(r"[ymdhs]", cleaned)) and not re.search(r"[0#?]", cleaned)


def _no_dtd(data: bytes, what: str) -> None:
    """Spreadsheet XML never needs a DOCTYPE. Refusing it rules out entity-expansion tricks."""
    if re.search(rb"<!doctype|<!entity", data, re.I):
        raise ExportError(f"This Excel file contains unsupported content ({what}), so it was refused.")


def _member(zf: zipfile.ZipFile, name: str, limit: int = MAX_XML_PART_BYTES) -> Optional[bytes]:
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit:
        raise ExportError("This Excel file has a part far bigger than a DSS list should have, so it was refused.")
    with zf.open(info) as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise ExportError("This Excel file has a part far bigger than a DSS list should have, so it was refused.")
    return data


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Za-z]+", ref or "")
    n = 0
    for ch in (letters.group(0).upper() if letters else "A"):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _serial_to_text(serial: float, date1904: bool) -> str:
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    dt = base + timedelta(days=serial)
    if abs(serial - round(serial)) < 1e-9:
        return dt.date().isoformat()
    return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class SheetStats:
    formulas: int = 0
    formulas_without_value: int = 0
    errors: int = 0
    sheet_name: str = ""


def read_xlsx_rows(data: bytes) -> Tuple[List[List[str]], SheetStats]:
    """Stored cell values of the first sheet that has any. Formulas are never evaluated, macros never touched."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExportError("This file is not a valid Excel (.xlsx) file.")
    with zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES:
            raise ExportError("This Excel file unpacks to far more data than a DSS list should, so it was refused.")
        if "[Content_Types].xml" not in zf.namelist() or "xl/workbook.xml" not in zf.namelist():
            raise ExportError("This file is not a valid Excel (.xlsx) file.")
        wb = _member(zf, "xl/workbook.xml")
        _no_dtd(wb, "workbook")
        wb_root = ET.fromstring(wb)
        date1904 = any(_local(e.tag) == "workbookPr" and e.get("date1904") in ("1", "true") for e in wb_root.iter())
        sheets = [(e.get("name", ""), e.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"))
                  for e in wb_root.iter() if _local(e.tag) == "sheet"]
        targets = {}
        rels = _member(zf, "xl/_rels/workbook.xml.rels")
        if rels:
            _no_dtd(rels, "relationships")
            for r in ET.fromstring(rels):
                t = r.get("Target", "")
                targets[r.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
        shared: List[str] = []
        sst = _member(zf, "xl/sharedStrings.xml")
        if sst:
            _no_dtd(sst, "shared strings")
            for si in ET.fromstring(sst):
                if _local(si.tag) != "si":
                    continue
                parts = []
                for ch in si:
                    n = _local(ch.tag)
                    if n == "t":
                        parts.append(ch.text or "")
                    elif n == "r":
                        parts += [(t.text or "") for t in ch if _local(t.tag) == "t"]
                shared.append("".join(parts))
        date_styles: Set[int] = set()
        sty = _member(zf, "xl/styles.xml")
        if sty:
            _no_dtd(sty, "styles")
            sroot = ET.fromstring(sty)
            custom = {int(e.get("numFmtId")): e.get("formatCode", "") for e in sroot.iter()
                      if _local(e.tag) == "numFmt" and (e.get("numFmtId") or "").isdigit()}
            for xroot in sroot:
                if _local(xroot.tag) == "cellXfs":
                    for idx, xf in enumerate(x for x in xroot if _local(x.tag) == "xf"):
                        fid = int(xf.get("numFmtId", "0") or 0)
                        if fid in _DATE_BUILTIN or (fid in custom and _is_date_format(custom[fid])):
                            date_styles.add(idx)
        stats = SheetStats()
        for name, rid in sheets or [("", None)]:
            path = targets.get(rid) or "xl/worksheets/sheet1.xml"
            xml = _member(zf, path)
            if xml is None:
                continue
            _no_dtd(xml, "sheet")
            rows = _sheet_rows(xml, shared, date_styles, date1904, stats)
            if any(any(c.strip() for c in r) for r in rows):
                stats.sheet_name = name
                return rows, stats
        return [], stats


def _sheet_rows(xml: bytes, shared: List[str], date_styles: Set[int], date1904: bool, stats: SheetStats):
    rows: List[List[str]] = []
    expected = 1
    for _, el in ET.iterparse(io.BytesIO(xml), events=("end",)):
        if _local(el.tag) != "row":
            continue
        r_attr = el.get("r")
        if r_attr and r_attr.isdigit():
            while expected < int(r_attr):
                rows.append([])
                expected += 1
        cells: List[str] = []
        for c in el:
            if _local(c.tag) != "c":
                continue
            idx = min(_col_index(c.get("r", "")), MAX_COLUMNS - 1)
            while len(cells) <= idx:
                cells.append("")
            kind = c.get("t", "n")
            v = next((x for x in c if _local(x.tag) == "v"), None)
            has_f = any(_local(x.tag) == "f" for x in c)
            if has_f:
                stats.formulas += 1
                if v is None or v.text is None:
                    stats.formulas_without_value += 1
            text = ""
            if kind == "inlineStr":
                text = "".join((t.text or "") for t in c.iter() if _local(t.tag) == "t")
            elif v is None or v.text is None:
                text = ""
            elif kind == "s":
                try:
                    text = shared[int(v.text)]
                except (ValueError, IndexError):
                    text = ""
            elif kind == "b":
                text = "TRUE" if v.text.strip() == "1" else "FALSE"
            elif kind == "e":
                stats.errors += 1
            elif kind in ("str", "d"):
                text = v.text
            else:
                try:
                    num = float(v.text)
                except ValueError:
                    num = None
                if num is None:
                    text = v.text
                elif int(c.get("s", "0") or 0) in date_styles:
                    text = _serial_to_text(num, date1904)
                else:
                    text = str(int(num)) if num == int(num) and abs(num) < 1e15 else repr(num)
            cells[idx] = text
        rows.append(cells)
        expected += 1
        el.clear()
        if len(rows) > MAX_ROWS:
            raise ExportError("This file has far more rows than a DSS list should, so it was refused.")
    return rows


def read_rows(data: bytes, filename: str) -> Tuple[List[List[str]], SheetStats, str]:
    """Bytes + the name they came with -> table rows. Refuses anything that is not a plain table file."""
    if not isinstance(data, (bytes, bytearray)):
        raise ExportError("That is not a file.")
    if len(data) > MAX_FILE_BYTES:
        raise ExportError(f"This file is {len(data) // (1024 * 1024)} MB, far bigger than a DSS list should be, so it was refused.")
    if not data.strip():
        raise ExportError("This file is empty.")
    ext = Path(filename or "").suffix.lower()
    if ext == ".xls":
        raise ExportError("Old-style .xls files are not supported. In R365 download the Excel (.xlsx) file, or "
                          "open this one in Excel and Save As .xlsx or .csv.")
    if ext == ".xlsm":
        raise ExportError("Macro-enabled Excel files are not accepted. Save the file as a normal .xlsx or .csv.")
    if ext not in ALLOWED_EXTENSIONS:
        raise ExportError("Choose an export file ending in .xlsx, .csv or .tsv.")
    is_zip = data[:4] == b"PK\x03\x04"
    if ext == ".xlsx" or is_zip:
        if not is_zip:
            raise ExportError("This file says it is Excel (.xlsx) but is not a valid Excel file.")
        rows, stats = read_xlsx_rows(bytes(data))
        return rows, stats, "xlsx"
    delim = "\t" if ext == ".tsv" else None
    return read_csv_rows(bytes(data), delim), SheetStats(), ("tsv" if ext == ".tsv" else "csv")


# ------------------------------------------------------------------------------------------ cell values

def parse_money(text: str) -> Tuple[Optional[Decimal], bool]:
    """(value, unreadable). Blank is (None, False). Text that is not a number is (None, True): never guessed."""
    t = (text or "").strip().replace("−", "-").replace(" ", " ")
    if not t:
        return None, False
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    t = t.replace("$", "").replace(",", "").replace(" ", "")
    if t.endswith("-"):
        neg, t = True, t[:-1]
    if t.startswith("+"):
        t = t[1:]
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None, True
    if not d.is_finite():
        return None, True
    return (-d if neg else d), False


_SLASH = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(?:[ T].*)?$")
_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$")
_WORDY = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%b-%y", "%b %d %Y", "%B %d %Y")


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str, order: str) -> Optional[date]:
    t = (text or "").strip()
    if not t:
        return None
    m = _ISO.match(t)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _SLASH.match(t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        return _safe_date(y, b, a) if order == "dmy" else _safe_date(y, a, b)
    core = re.split(r"\s+\d{1,2}:\d{2}", t)[0].strip()
    for fmt in _WORDY:
        try:
            return datetime.strptime(core, fmt).date()
        except ValueError:
            continue
    return None


def detect_date_order(values: List[str]) -> Tuple[str, Optional[str]]:
    """'mdy' (R365's US default) or 'dmy', judged from the whole column, plus a plain warning if it was a guess."""
    first_big = second_big = ambiguous = False
    for v in values:
        m = _SLASH.match(v or "")
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            first_big = True
        elif b > 12 and a <= 12:
            second_big = True
        elif a <= 12 and b <= 12 and a != b:
            ambiguous = True
    if first_big and second_big:
        raise ExportError("The dates in this file mix day-first and month-first, so they cannot be read safely.")
    if first_big:
        return "dmy", None
    if second_big:
        return "mdy", None
    if ambiguous:
        return "mdy", ("Dates like 03/04/2026 could be month/day or day/month. They were read month first (as R365 "
                       "does in the US). Check one day against R365.")
    return "mdy", None


# ------------------------------------------------------------------------------------------ parsing

@dataclass
class ParsedExport:
    records: List[DayRecord]
    columns: Dict[str, str]                  # field -> heading as written in the file
    unrecognised: List[str]                  # headings this program did not recognise (names only)
    missing: List[str]                       # fields with no column
    warnings: List[str]
    stated_total: Optional[int]
    rows_read: int
    unmapped: Set[str]
    last_date: Optional[date] = None
    first_date: Optional[date] = None
    layout_note: str = ""


_COUNT_PATTERNS = (
    re.compile(r"showing\s+\d+\s*(?:-|to|–)?\s*\d*\s*of\s+(\d+)", re.I),
    re.compile(r"(?:total\s+)?(?:records?|rows?|items?|entries|results)\s*(?:found|returned)?\s*[:=]?\s*(\d+)\b", re.I),
    re.compile(r"\b(\d+)\s+(?:records?|rows?|items?|entries|results)\b", re.I),
    re.compile(r"\btotal\s*[:=]\s*(\d+)\s*$", re.I),
)
_TOTAL_LABEL = re.compile(r"^\s*(?:grand\s+)?totals?\b|^\s*sum\b|^\s*count\b", re.I)


def _stated_count(line: str) -> Optional[int]:
    for pat in _COUNT_PATTERNS:
        m = pat.search(line)
        if m:
            return int(m.group(1))
    return None


def _canon_word(word: str) -> str:
    return re.sub(r"\s+", " ", word.strip().lower())


def clean_overrides(words: Dict[str, str]) -> Dict[str, bool]:
    """Owner's per-connection word meanings -> {canonical word: approved?}. 'approved'/'unapproved' themselves
    cannot be redefined."""
    out = {}
    for w, meaning in (words or {}).items():
        cw, m = _canon_word(w), _canon_word(meaning)
        if cw in BUILT_IN_APPROVAL or cw == "not approved" or not cw:
            continue
        if m in OVERRIDE_VALUES:
            out[cw] = OVERRIDE_VALUES[m]
    return out


def parse_export(rows: List[List[str]], aliases: Aliases, approval_words: Optional[Dict[str, str]] = None,
                 as_of: Optional[datetime] = None, today: Optional[date] = None, stats: Optional[SheetStats] = None
                 ) -> ParsedExport:
    today = today or date.today()
    overrides = clean_overrides(approval_words or {})
    warnings: List[str] = []

    # ---- find the heading row (it need not be on line 1)
    header_idx, cols, notes = None, {}, []
    best = (0, None, {}, [])
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        found, n = aliases.match(row)
        if all(f in found for f in REQUIRED):
            header_idx, cols, notes = i, found, n
            break
        if len(found) > best[0]:
            best = (len(found), i, found, row)
    if header_idx is None:
        if best[0] >= 1 and best[1] is not None:
            missing = [FIELD_WORDS[f] for f in REQUIRED if f not in best[2]]
            raise ExportError("This file has no " + " or ".join(f"{m} column" for m in missing) +
                              ", so it cannot be read. Download the Daily Sales Summary list again from R365.")
        raise ExportError("This does not look like an R365 Daily Sales Summary list: no heading row with "
                          f"Location and Date was found in the first {HEADER_SCAN_ROWS} lines.")
    header = rows[header_idx]
    columns = {f: header[i] for f, i in cols.items()}
    recognised = set(cols.values())
    unrecognised = [h for i, h in enumerate(header) if i not in recognised and h.strip()]
    missing = [f for f in FIELDS if f not in cols]
    warnings += notes
    layout_note = f"The heading row was on line {header_idx + 1}." if header_idx else ""

    def cell(row, f):
        i = cols.get(f)
        return row[i].strip() if i is not None and i < len(row) else ""

    # ---- stated item counts anywhere outside the table (a line above it, or a footer)
    stated: List[int] = []
    for row in rows[:header_idx]:
        line = " ".join(c for c in row if c.strip())
        n = _stated_count(line) if line else None
        if n is not None:
            stated.append(n)

    # ---- classify the lines after the heading row
    data_rows, set_aside_date, set_aside_loc = [], 0, 0
    for row in rows[header_idx + 1:]:
        if not any(c.strip() for c in row):
            continue
        loc, dt = cell(row, "location"), cell(row, "business_date")
        if not loc and not dt:
            line = " ".join(c for c in row if c.strip())
            n = _stated_count(line)
            if n is not None:
                stated.append(n)
            continue
        if loc and not dt and _TOTAL_LABEL.match(loc):
            n = _stated_count(" ".join(c for c in row if c.strip()))
            if n is not None:
                stated.append(n)
            continue
        if not loc:
            set_aside_loc += 1
            continue
        data_rows.append(row)

    order, date_warn = detect_date_order([cell(r, "business_date") for r in data_rows])
    if date_warn:
        warnings.append(date_warn)

    # ---- read each data row
    bad_over = bad_sales = 0
    by_day: Dict[Tuple[str, date], List[dict]] = {}
    for row in data_rows:
        d = parse_date(cell(row, "business_date"), order)
        if d is None:
            set_aside_date += 1
            continue
        over, bad = parse_money(cell(row, "over_short")) if "over_short" in cols else (None, False)
        bad_over += bad
        sales, bad2 = parse_money(cell(row, "net_sales")) if "net_sales" in cols else (None, False)
        bad_sales += bad2
        loc = re.sub(r"\s+", " ", cell(row, "location"))
        by_day.setdefault((loc, d), []).append(
            {"word": cell(row, "approval_status"), "over": over, "sales": sales})
    rows_read = len(data_rows)

    stale = as_of is None or as_of.date() < today
    if stale:
        if as_of is None:
            warnings.insert(0, "This file does not say when it was downloaded, so it cannot establish today's "
                               "approval status. Approval is shown as UNKNOWN.")
        else:
            warnings.insert(0, f"This file is dated {as_of.date().isoformat()}. A file older than today cannot "
                               "establish today's approval status, so approval is shown as UNKNOWN. Download a "
                               "fresh list from R365 and check again.")

    records: List[DayRecord] = []
    conflict_days = 0
    for (loc, d), group in sorted(by_day.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1])):
        conflicts: List[str] = []
        # approval
        words = [g["word"] for g in group if g["word"].strip()]
        distinct = {_canon_word(w) for w in words}
        approved, note = None, None
        if "approval_status" in cols:
            if len(distinct) > 1:
                conflicts.append("approval status")
            elif len(distinct) == 1:
                word = words[0].strip()
                cw = _canon_word(word)
                verdict = BUILT_IN_APPROVAL.get(cw, overrides.get(cw))
                if stale:
                    when = ("the file does not say when it was downloaded" if as_of is None
                            else f"the file is dated {as_of.date().isoformat()}, older than today")
                    note = f"Approval is UNKNOWN: {when} (it said '{word}')."
                elif verdict is None:
                    meaning = KNOWN_WORD_MEANING.get(cw)
                    note = (f"Approval is UNKNOWN: the file says '{word}'"
                            + (f" ({meaning})" if meaning else "")
                            + ", which is not treated as approved or not approved.")
                else:
                    approved = verdict
        # over/short and net sales: rows must agree
        def merged(key, label):
            vals = [g[key] for g in group]
            if len({v for v in vals}) > 1:
                conflicts.append(label)
                return None
            return vals[0]
        over = merged("over", "over/short") if "over_short" in cols else None
        sales = merged("sales", "net sales") if "net_sales" in cols else None
        if conflicts:
            conflict_days += 1
        records.append(DayRecord(
            location=loc, business_date=d, sales_total=sales, payments={}, cash_over_short=over,
            missing_receipts=None, payment_exceptions=None, approved=approved, pos_import_received=None,
            approval_note=note, conflicts=tuple(conflicts)))

    # ---- plain statements about the file
    for f in missing:
        why = {"over_short": ", so the cash over/short check could not run",
               "approval_status": ", so the approval check could not run",
               "net_sales": ", so the sales-total check could not run",
               "location_number": " (not needed by any check)", "deposit": " (not needed by any check)"}.get(f, "")
        warnings.append(f"This file has no {FIELD_WORDS[f]} column{why}.")
    total = max(stated) if stated else None
    if total is not None and rows_read < total:
        warnings.insert(0, f"Partial list: the file says it holds {total} entries but only {rows_read} were read. "
                           "Days or locations may be missing from it.")
    if set_aside_date:
        warnings.append(f"{set_aside_date} row{'s' if set_aside_date != 1 else ''} had a Date that could not be "
                        "read and were set aside (not counted as any day).")
    if set_aside_loc:
        warnings.append(f"{set_aside_loc} row{'s' if set_aside_loc != 1 else ''} had a date but no Location and "
                        "were set aside.")
    if bad_over:
        warnings.append(f"{bad_over} Over/Short value{'s' if bad_over != 1 else ''} could not be read as a number "
                        "and are shown as UNKNOWN.")
    if bad_sales:
        warnings.append(f"{bad_sales} Net Sales value{'s' if bad_sales != 1 else ''} could not be read as a number.")
    if conflict_days:
        warnings.append(f"{conflict_days} day{'s' if conflict_days != 1 else ''} had rows that disagree with each "
                        "other. Those are shown as UNKNOWN and marked as a conflict.")
    if stats and stats.formulas_without_value:
        warnings.append(f"{stats.formulas_without_value} Excel formula cell{'s' if stats.formulas_without_value != 1 else ''} "
                        "had no stored value and were read as blank (formulas are never calculated here).")
    if stats and stats.errors:
        warnings.append(f"{stats.errors} Excel error cell{'s' if stats.errors != 1 else ''} were read as blank.")

    unmapped = {"missing_receipts", "payment_exceptions", "pos_import_received", "payments"}
    if "over_short" not in cols:
        unmapped.add("cash_over_short")
    if "approval_status" not in cols:
        unmapped.add("approved")
    if "net_sales" not in cols:
        unmapped.add("sales_total")
    dates = [d for (_, d) in by_day]
    return ParsedExport(records, columns, unrecognised, missing, warnings, total, rows_read, unmapped,
                        max(dates) if dates else None, min(dates) if dates else None, layout_note)
