"""The brief report: one row per place, "Complete?" and a short flag. Nothing else.

"Complete?" means one thing only: the DSS is approved. It is never worked out from anything else.
  Yes      the export says Approved (and the file is fresh enough to say so)
  No       the export says Unapproved
  Unknown  no row, a blank or unclear status (for example "In Progress"), a stale file, or conflicting rows
The flag lists what the export shows (a cash difference, missing data). It says what is there, not why a DSS
is unfinished: the export cannot give a reason, so none is claimed.
"""

import re
import textwrap
from dataclasses import dataclass
from html import escape
from typing import List

from .render import CSS, date_label, multi_subject
from .report import LocationResult, MultiReport, Report
from .rules import CONFLICT, ISSUE, LABELS, NO_DATA, UNAPPROVED

YES, NO, UNK = "Yes", "No", "Unknown"
_ORDER = {NO: 0, UNK: 1, YES: 2}


@dataclass
class Row:
    place: str
    complete: str
    flags: List[str]


def _short(text: str) -> str:
    if text.startswith("Approval status cannot be established: the file is dated"):
        return "Approval unknown: the file is not from today"
    if "not treated as approved or not approved" in text:
        m = re.search(r"'([^']+)'", text)
        return f"Status is '{m.group(1)}', which is not treated as approved or not" if m else text
    return text


def rows_for(report: Report) -> List[Row]:
    approval_checked = LABELS[UNAPPROVED] not in report.needs_mapping and not _approval_off(report)
    out = []
    for res in list(report.attention) + list(report.clear):
        out.append(_row(res, report, approval_checked))
    out.sort(key=lambda r: (_ORDER[r.complete], r.place.lower()))
    return out


def _approval_off(report: Report) -> bool:
    return any(n.startswith(LABELS[UNAPPROVED]) and ("switched off" in n or "NOT IN YOUR LICENCE" in n)
               for n in report.rules_note)


def _row(res: LocationResult, report: Report, approval_checked: bool) -> Row:
    multi = report.multi_day
    flags: List[str] = []
    saw_no = saw_unknown = False
    for f in sorted(res.findings, key=lambda f: (f.business_date, f.kind != ISSUE, f.rule)):
        if f.rule == UNAPPROVED and f.kind == ISSUE:
            saw_no = True
            if multi:
                flags.append(f"{f.business_date.isoformat()}: not approved")
            continue
        if f.rule in (UNAPPROVED, NO_DATA, CONFLICT):
            saw_unknown = True
        text = _short(f.text) if f.kind == ISSUE else f"UNKNOWN: {_short(f.text)}"
        flags.append(f"{f.business_date.isoformat()}: {text}" if multi else text)
    if saw_no:
        complete = NO
    elif saw_unknown or not approval_checked:
        complete = UNK
    else:
        complete = YES
    return Row(res.name, complete, flags)


def counts(rows: List[Row]) -> str:
    n = {k: sum(1 for r in rows if r.complete == k) for k in (YES, NO, UNK)}
    return f"{len(rows)} places: {n[YES]} complete, {n[NO]} not complete, {n[UNK]} unknown."


def _notes(report: Report) -> List[str]:
    notes = []
    if report.source_line:
        notes.append(report.source_line)
    notes += report.source_warnings
    if report.needs_mapping:
        notes.append("Not checked: " + ", ".join(report.needs_mapping) + ".")
    return notes


def _table(rows: List[Row], e=escape) -> List[str]:
    if not rows:
        return ['<p class="empty">No places were found in the data (UNKNOWN).</p>']
    out = ['<table><thead><tr><th>Place</th><th>Complete?</th><th>Flag</th></tr></thead><tbody>']
    for r in rows:
        cls = {"Yes": "", "No": "review", "Unknown": "unknown"}[r.complete]
        badge = f'<span class="badge {cls}">{e(r.complete)}</span>' if cls else e(r.complete)
        flag = "<ul>" + "".join(f"<li>{e(t)}</li>" for t in r.flags) + "</ul>" if r.flags else "-"
        out.append(f'<tr><td class="loc" data-label="Place">{e(r.place)}</td>'
                   f'<td data-label="Complete?">{badge}</td><td data-label="Flag">{flag}</td></tr>')
    return out + ['</tbody></table>']


def _head(title: str, dates, extra: List[str]) -> List[str]:
    e = escape
    return ['<!DOCTYPE html>', '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f'<title>{e(title)} - {e(date_label(dates))}</title>',
            f'<style>{CSS}</style></head><body><main>',
            f'<h1>{e(title)}</h1>', f'<p class="date">{e(date_label(dates))}</p>'] + extra


def _banner(m) -> List[str]:
    e, out = escape, []
    if getattr(m, "late_note", ""):
        out.append(f'<p class="warn">{e(m.late_note)}</p>')
    if m.licence_notice or m.licence_problem:
        out.append(f'<p class="warn">{e(m.licence_notice or m.licence_line)}</p>')
    return out


def _foot() -> str:
    return ('<footer><p>Complete means the export says Approved. It does not say why a day is unfinished. '
            'Made by a computer program; nothing was sent anywhere.</p></footer></main></body></html>\n')


def brief_html(report) -> str:
    e = escape
    if isinstance(report, MultiReport):
        out = _head(report.title, report.dates, _banner(report))
        for s in report.failed_sections:
            out.append(f'<p class="down">{e(s.name)}: {e(s.error)}</p>')
        for s in report.ok_sections:
            rows = rows_for(s.report)
            out.append(f'<h2 class="inst">{e(s.name)}</h2><p class="subhead">{e(counts(rows))}</p>')
            out += [f'<p class="note">{e(n)}</p>' for n in _notes(s.report)]
            out += _table(rows)
        return "\n".join(out + [_foot()])
    rows = rows_for(report)
    out = _head(report.title, report.dates, [f'<p class="headline">{e(counts(rows))}</p>'] + _banner(report))
    out += [f'<p class="note">{e(n)}</p>' for n in _notes(report)]
    return "\n".join(out + _table(rows) + [_foot()])


def _text_table(rows: List[Row], wrap) -> List[str]:
    if not rows:
        return ["No places were found in the data (UNKNOWN)."]
    width = max(len(r.place) for r in rows)
    lines = []
    for r in rows:
        first = f"{r.place.ljust(width)}  {r.complete.ljust(7)}  "
        flags = r.flags or ["-"]
        pad = " " * len(first)
        lines.append(textwrap.fill(flags[0], 100, initial_indent=first, subsequent_indent=pad))
        lines += [textwrap.fill(t, 100, initial_indent=pad, subsequent_indent=pad) for t in flags[1:]]
    return lines


def brief_text(report) -> str:
    wrap = lambda s: textwrap.fill(s, 76)
    if isinstance(report, MultiReport):
        lines = [f"Subject: {multi_subject(report)}", ""]
        for s in report.failed_sections:
            lines += [wrap(f"{s.name.upper()}: {s.error}"), ""]
        if report.late_note:
            lines += [wrap("LATE: " + report.late_note.removeprefix("Late: ")), ""]
        for s in report.ok_sections:
            rows = rows_for(s.report)
            lines += [s.name.upper(), "=" * len(s.name), counts(rows)]
            lines += [wrap(n) for n in _notes(s.report)] + [""]
            lines += ["Place / Complete? / Flag"] + _text_table(rows, wrap) + [""]
        lines.append("Complete means the export says Approved. Nothing was sent anywhere.")
        return "\n".join(lines) + "\n"
    rows = rows_for(report)
    n_bad = sum(1 for r in rows if r.complete != YES)
    subject = (f"{report.title} - {date_label(report.dates)}: "
               + (f"{n_bad} of {len(rows)} places not confirmed complete" if rows else "no data (UNKNOWN)"))
    lines = [f"Subject: {subject}", "", counts(rows)]
    if report.late_note:
        lines += ["", wrap("LATE: " + report.late_note.removeprefix("Late: "))]
    if report.licence_notice or report.licence_problem:
        lines += ["", wrap(report.licence_notice or report.licence_line)]
    lines += [""] + [wrap(n) for n in _notes(report)] + ["", "Place / Complete? / Flag"] + _text_table(rows, wrap)
    lines += ["", "Complete means the export says Approved. Nothing was sent anywhere."]
    return "\n".join(lines) + "\n"
