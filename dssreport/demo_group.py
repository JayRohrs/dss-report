"""Demo mode: an invented 12-place restaurant group on two R365 instances, with realistic mess, run through the
REAL reader and the REAL brief.

Everything here is made up ("Sample Pier Grill", 12.50). The only things that are not the real program are the two
export files, which this module writes into a temp folder. Each "mess" case is something that really happens with
R365 lists, and each is meant to show the same behaviour: the report says what it can tell, and writes
"Could not tell" for the rest instead of guessing.

  East  - classic layout (a CSV with ApprovalStatus and Over/Short)
  West  - newer ("beta") layout (a CSV that says "In Progress" and has no count column)
"""

import os
import textwrap
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import dss_export_sample as S
from .brief import brief_html, brief_text
from .config import Config
from .dss_export_source import DssExportSource, store_export
from .report import Section, build_multi_report, build_report, window
from .settings import Instance

GROUP = "Sample Hospitality Group"
TITLE = "Daily Sales Summary: what is still unapproved"

EAST_NAME, WEST_NAME = "Sample Group East", "Sample Group West"
EAST: List[Tuple[str, str]] = [
    ("Sample Pier Grill", "101"), ("Sample Hill Bistro", "102"), ("Sample Dock Cafe", "103"),
    ("Sample Park Diner", "104"), ("Sample Mill Tavern", "105"), ("Sample Bay Oyster Bar", "106"),
    ("Sample Cedar Steakhouse", "107")]
WEST: List[Tuple[str, str]] = [
    ("Sample Lake Pizzeria", "201"), ("Sample Ridge Taproom", "202"), ("Sample Orchard Kitchen", "203"),
    ("Sample Canal Noodle House", "204"), ("Sample Summit Grill", "205")]

# The mess, one entry per case. `where` is the place the case shows up on; used by the story and the tests.
MESS: List[Dict[str, str]] = [
    {"key": "unapproved_short",
     "title": "A day that needs to balance",
     "where": "Sample Hill Bistro",
     "shows": "Not approved, and the cash is off by -23.50 as R365 gives it. Listed first, as a likely reason, "
              "not a proven one."},
    {"key": "ready",
     "title": "A day that looks ready",
     "where": "Sample Park Diner",
     "shows": "Not approved, and nothing else in the file is flagged, so it says 'Ready to approve'. "
              "Nothing is approved by the program."},
    {"key": "duplicate",
     "title": "Two rows that disagree",
     "where": "Sample Bay Oyster Bar",
     "shows": "The file has the same place and day twice, once Approved and once Unapproved. The report does "
              "not pick one: 'Could not tell'."},
    {"key": "missing_row",
     "title": "A row that is missing",
     "where": "Sample Cedar Steakhouse",
     "shows": "This place has rows for earlier days but none for the last day. A missing row is never read as "
              "approved: 'Could not tell'."},
    {"key": "in_progress",
     "title": "A new word, 'In Progress'",
     "where": "Sample Lake Pizzeria",
     "shows": "The newer list says 'In Progress'. Nobody has confirmed it means 'not approved', so the report "
              "does not decide: 'Could not tell', and it says which word it saw."},
    {"key": "no_data",
     "title": "A place with no data at all",
     "where": "Sample Canal Noodle House",
     "shows": "The place is on the list to watch but the file has nothing for it. Shown as 'Could not tell', "
              "never as clear."},
    {"key": "renamed_heading",
     "title": "A column heading R365 renamed",
     "where": WEST_NAME,
     "shows": "The newer file calls the cash column 'Cash Gap' instead of 'Over/Short'. The report names the "
              "heading it did not recognise and says the cash check could not run. One line in the heading list "
              "fixes it; no code change."},
    {"key": "stale",
     "title": "A file that is not from today",
     "where": EAST_NAME,
     "shows": "If the downloaded list is from yesterday, today's approval status cannot be known. Every place "
              "on it becomes 'Could not tell' and the report says why. See brief-old-file.html."},
]

CASH_GAP_HEADING = "Cash Gap"


@dataclass
class DemoResult:
    out_dir: Path
    html_path: Path
    text_path: Path
    old_file_path: Path
    export_paths: Dict[str, Path]
    report: object
    today: date

    @property
    def last_day(self) -> date:
        return self.today - timedelta(days=1)


# ------------------------------------------------------------------------------------------ the invented files

def _over(loc: str, offset: int, day: date, last: date) -> float:
    """Small, in-limit differences on most days; the planted ones on the last day."""
    if day == last:
        return {"Sample Hill Bistro": -23.5, "Sample Mill Tavern": 0.0, "Sample Dock Cafe": 0.0}.get(loc, 1.25)
    return [1.25, -0.5, 0.0, 2.0, 0.75][(offset + len(loc)) % 5]


def _status(loc: str, day: date, last: date, beta: bool) -> str:
    if day != last:
        return "Approved"
    if beta:
        return {"Sample Lake Pizzeria": "In Progress", "Sample Orchard Kitchen": "Approved"}.get(loc, "Approved")
    return {"Sample Hill Bistro": "Unapproved", "Sample Park Diner": "Unapproved",
            "Sample Bay Oyster Bar": "Unapproved"}.get(loc, "Approved")


def _rows(layout: str, places: List[Tuple[str, str]], today: date, days: int = 7) -> List[List[str]]:
    last = today - timedelta(days=1)
    beta = layout == "beta"
    plan = []
    for offset in range(days):
        day = last - timedelta(days=days - 1 - offset)
        for i, (loc, num) in enumerate(places):
            if loc == "Sample Canal Noodle House":
                continue                                           # no data at all for this place
            if day == last and loc == "Sample Cedar Steakhouse":
                continue                                           # the missing row
            plan.append((offset, i, loc, num, day))
            if day == last and loc == "Sample Bay Oyster Bar":
                plan.append((offset, i, loc, num, day))            # the conflicting duplicate
    rows, seen_dupe = [], set()
    for n, (offset, i, loc, num, day) in enumerate(plan, start=1):
        status = _status(loc, day, last, beta)
        over = _over(loc, offset, day, last)
        if loc == "Sample Bay Oyster Bar" and day == last:
            second = (loc, day) in seen_dupe
            seen_dupe.add((loc, day))
            status, over = ("Approved", 0.0) if second else ("Unapproved", -8.0)
        sales = round(3100 + 310 * i + 19 * offset, 2)
        deposit, guests = round(sales * 0.97, 2), 90 + offset + 3 * i
        if beta:
            rows.append([status, loc, day.strftime("%m/%d/%Y"), "No", f"{sales:.4f}", "0.0000", "0.0000000000", "0",
                         f"{deposit:.4f}", f"{over:.4f}", str(guests)])
        else:
            made = datetime(day.year, day.month, day.day, 8, 15) + timedelta(days=1)
            stamp = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S") + ".0000000Z"
            ok = status == "Approved"
            rows.append([status, "Approved" if ok else "In Progress", loc, num,
                         f"{loc} {day.strftime('%A')}, {day.strftime('%m/%d/%Y')}",
                         f"{day.month}/{day.day}/{day.year} 12:00:00 AM", f"{sales:.4f}", f"{deposit:.4f}",
                         f"{over:.4f}", str(guests), "Yes" if ok else "No", "", stamp(made), "Sample User",
                         stamp(made + timedelta(minutes=45)),
                         f"{n:08d}-0000-4000-8000-{n:012d}",       # built at run time: no id is stored in the repo
                         "0.0000", str(len(plan)), "", "", "", "", ""])
    return rows


def export_bytes(layout: str, today: Optional[date] = None, renamed: bool = True) -> bytes:
    """The invented list for one layout as a CSV in the observed format (classic: no BOM; beta: with a BOM)."""
    import csv
    import io
    today = today or date.today()
    places = EAST if layout == "classic" else WEST
    headers = list(S.CLASSIC_HEADERS if layout == "classic" else S.BETA_HEADERS)
    if layout == "beta" and renamed:
        headers[headers.index("Over/Short")] = CASH_GAP_HEADING
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(headers)
    w.writerows(_rows(layout, places, today))
    data = out.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if layout == "beta" else data


def write_exports(folder, today: Optional[date] = None) -> Dict[str, Path]:
    """Write the two invented export files (as someone would download them) into `folder`."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = {"east": folder / "sample-east-classic.csv", "west": folder / "sample-west-beta.csv"}
    paths["east"].write_bytes(export_bytes("classic", today))
    paths["west"].write_bytes(export_bytes("beta", today))
    return paths


# ------------------------------------------------------------------------------------------ running the real thing

@contextmanager
def _home(path: Path):
    """Point the program's own folder at a temp folder for the length of the demo, then put it back."""
    old = os.environ.get("DSSREPORT_HOME")
    os.environ["DSSREPORT_HOME"] = str(path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("DSSREPORT_HOME", None)
        else:
            os.environ["DSSREPORT_HOME"] = old


def _instances() -> List[Tuple[Instance, List[Tuple[str, str]], str]]:
    return [(Instance(id="sample-east", name=EAST_NAME, source_kind="dss-export", include=[p for p, _ in EAST]),
             EAST, "east"),
            (Instance(id="sample-west", name=WEST_NAME, source_kind="dss-export", include=[p for p, _ in WEST]),
             WEST, "west")]


def build_report_from(paths: Dict[str, Path], home: Path, today: date, east_file_date: Optional[datetime] = None):
    """Read the two files with the real export reader and build the real multi-connection report."""
    last = today - timedelta(days=1)
    cfg = Config(title=TITLE)
    sections = []
    with _home(home):
        for inst, _, key in _instances():
            data = paths[key].read_bytes()
            when = east_file_date if (key == "east" and east_file_date) else datetime.now()
            store_export(inst, paths[key].name, data, when.timestamp(), now=datetime.now(), today=today)
            icfg = replace(cfg, include=inst.include)
            source = DssExportSource(inst, include=icfg.include, today=today)
            source.set_window(last, last)
            records = source.load()
            report = build_report(records, icfg, end=last, days=1, source_name=source.name,
                                  unmapped=frozenset(source.unmapped), unmapped_why="not in the export file")
            report.source_line = source.source_line
            report.source_warnings = list(source.source_warnings)
            report.needs_mapping_text = source.unmapped_text
            sections.append(Section(inst.name, report=report))
    return build_multi_report(sections, cfg, window([], last, 1), source_name="Sample data (invented)")


def run_demo(out_dir=None, today: Optional[date] = None) -> DemoResult:
    """Build the invented exports, run the real reader and brief, and write the files. Nothing is sent anywhere."""
    today = today or date.today()
    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="dss-demo-"))
    out.mkdir(parents=True, exist_ok=True)
    exports = write_exports(out / "exports", today)
    with tempfile.TemporaryDirectory(prefix="dss-demo-home-") as home:
        report = build_report_from(exports, Path(home), today)
        stale = build_report_from(exports, Path(home), today, east_file_date=datetime.now() - timedelta(days=1))
    html_path, text_path = out / "brief.html", out / "brief-email.txt"
    old_path = out / "brief-old-file.html"
    html_path.write_text(brief_html(report, sample=True), encoding="utf-8")
    text_path.write_text(brief_text(report, sample=True), encoding="utf-8")
    old_path.write_text(brief_html(stale, sample=True), encoding="utf-8")
    return DemoResult(out, html_path, text_path, old_path, exports, report, today)


# ------------------------------------------------------------------------------------------ the story

def story_text() -> str:
    """A short plain-words narration of each mess case and how the report refuses to guess."""
    lines = [
        "THE STORY OF THE DEMO",
        "",
        f"{GROUP} is invented: 12 places on two R365 connections. East uses the classic list layout, West the",
        "newer one. We made the two downloaded files messy the way real ones get, then ran the real program.",
        "",
        "The rule behind everything: the report says what it can tell from the file, and writes 'Could not tell'",
        "for the rest. It never turns a missing, odd or old answer into 'approved'. It never approves anything.",
        "",
    ]
    for n, case in enumerate(MESS, start=1):
        lines.append(f"{n}. {case['title']} ({case['where']})")
        lines.append(textwrap.fill(case["shows"], 100, initial_indent="   ", subsequent_indent="   "))
        lines.append("")
    lines += [textwrap.fill("Why it matters: a report that guesses looks tidier, until a day it guessed wrong goes "
                            "unapproved at month end. This one is a little less tidy on purpose, and every grey "
                            "'Could not tell' is a place you can check in R365 in a minute.", 100), "",
              textwrap.fill("What is NOT shown here: whether 'In Progress' really means 'not approved' (unconfirmed), "
                            "and which way Over/Short is signed (shown exactly as R365 gives it).", 100), ""]
    return "\n".join(lines)
