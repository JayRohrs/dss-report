"""The brief report: only what is still unapproved, fast to read.

For each place that is NOT approved it gives one short line: "Ready to approve" when the export flags nothing
else, or a LIKELY reason in plain accounting words ("Needs to balance: Over/Short -$23.50"). The wording is in
data/reason_terms.toml and can be changed by the owner. The export cannot say why a day is unfinished, so
reasons are always labelled "Likely" and never stated as the cause, and nothing here approves anything.

If every place is approved the report says so. A place whose status cannot be told (no row, a blank or unclear
status such as "In Progress", a file older than today, conflicting rows, no approval column) is listed
separately as "Could not tell"; it is never counted as approved and never hidden.
"""

import re
import textwrap
import tomllib
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Dict, List, Tuple

from .paths import app_dir
from .render import CSS, date_label
from .report import LocationResult, MultiReport, Report
from .rules import CONFLICT, ISSUE, LABELS, NO_DATA, UNAPPROVED

APPROVED, UNAPPROVED_STATE, UNTOLD = "approved", "unapproved", "could not tell"
NOTHING = "Nothing outstanding to approve."
_LIMIT = re.compile(r"\s*\(limit [^)]*\)")

_DEFAULT_TERMS = {"ready": "Ready to approve", "reasons": {}}


def load_terms(shipped: Path = None, user: Path = None) -> Dict:
    shipped = shipped or Path(__file__).resolve().parent / "data" / "reason_terms.toml"
    user = user or app_dir() / "reason_terms.toml"
    out = {"ready": _DEFAULT_TERMS["ready"], "reasons": {}}
    for path, strict in ((shipped, False), (user, False)):
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue                                   # a broken wording file never stops the report
        if isinstance(raw.get("ready"), str) and raw["ready"].strip():
            out["ready"] = raw["ready"].strip()
        for k, v in (raw.get("reasons") or {}).items():
            if isinstance(v, str) and v.strip():
                out["reasons"][k] = v.strip()
    return out


@dataclass
class Row:
    place: str
    state: str                  # APPROVED / UNAPPROVED_STATE / UNTOLD
    reasons: List[str]          # likely reasons (unapproved) or why it could not be told
    day: str = ""

    @property
    def ready(self) -> bool:
        return self.state == UNAPPROVED_STATE and not self.reasons


def _short(text: str) -> str:
    if text.startswith("Approval status cannot be established: the file is dated"):
        return "File is not from today, so approval cannot be told"
    if "not treated as approved or not approved" in text:
        m = re.search(r"'([^']+)'", text)
        return f"Status is '{m.group(1)}', which is not treated as approved or not" if m else text
    return text


def _reason(rule: str, text: str, terms: Dict) -> str:
    tmpl = terms["reasons"].get(rule)
    text = _LIMIT.sub("", text)
    if not tmpl:
        return text
    if "{value}" not in tmpl:
        return tmpl
    value = text
    m = re.search(r"(?:Over/Short|Cash) is (-?\$[\d,.]+(?: short| over)?)", text)
    if rule == "cash_variance" and m:
        value = m.group(1)
    return tmpl.replace("{value}", value)


def _approval_off(report: Report) -> bool:
    return any(n.startswith(LABELS[UNAPPROVED]) and ("switched off" in n or "NOT IN YOUR LICENCE" in n)
               for n in report.rules_note)


def rows_for(report: Report, terms: Dict = None) -> List[Row]:
    terms = terms or load_terms()
    approval_checked = LABELS[UNAPPROVED] not in report.needs_mapping and not _approval_off(report)
    rows = []
    for res in list(report.attention) + list(report.clear):
        rows.append(_row(res, report, approval_checked, terms))
    order = {UNAPPROVED_STATE: 0, UNTOLD: 1, APPROVED: 2}
    rows.sort(key=lambda r: (order[r.state], r.ready, r.place.lower()))     # flagged ones before "ready" ones
    return rows


def _row(res: LocationResult, report: Report, approval_checked: bool, terms: Dict) -> Row:
    multi = report.multi_day
    reasons: List[str] = []
    untold: List[str] = []
    unapproved = False
    for f in sorted(res.findings, key=lambda f: (f.business_date, f.kind != ISSUE, f.rule)):
        tag = f"{f.business_date.isoformat()}: " if multi else ""
        if f.rule == UNAPPROVED and f.kind == ISSUE:
            unapproved = True
            if multi:
                reasons.append(f"{tag}not approved")
            continue
        if f.rule in (UNAPPROVED, NO_DATA, CONFLICT):
            untold.append(tag + _short(f.text))
        elif f.kind == ISSUE:
            reasons.append(tag + _reason(f.rule, f.text, terms))
        # a blank value elsewhere ("cash over/short is blank") is not a reason; it is left out of the brief
    if unapproved:
        return Row(res.name, UNAPPROVED_STATE, reasons)
    if untold or not approval_checked:
        return Row(res.name, UNTOLD, untold or ["No approval column in this file"])
    return Row(res.name, APPROVED, [])


def counts(rows: List[Row]) -> Tuple[str, bool]:
    bad = [r for r in rows if r.state == UNAPPROVED_STATE]
    untold = [r for r in rows if r.state == UNTOLD]
    if not rows:
        return "No places were found in the data, so nothing could be checked.", False
    if not bad and not untold:
        return NOTHING, True
    parts = []
    if bad:
        ready = sum(1 for r in bad if r.ready)
        parts.append(f"{len(bad)} unapproved ({ready} ready to approve, {len(bad) - ready} with something flagged).")
    else:
        parts.append("No place shows as unapproved.")
    if untold:
        parts.append(f"{len(untold)} could not be told.")
    return " ".join(parts), False


def _notes(report: Report) -> List[str]:
    notes = []
    if report.source_line:
        notes.append(report.source_line)
    notes += report.source_warnings
    return notes


def _line(r: Row, terms: Dict) -> str:
    return "; ".join(r.reasons) if r.reasons else terms["ready"]


def _table(rows: List[Row], terms: Dict, e=escape) -> List[str]:
    bad = [r for r in rows if r.state == UNAPPROVED_STATE]
    untold = [r for r in rows if r.state == UNTOLD]
    out = []
    if bad:
        out.append('<table><thead><tr><th>Place</th><th>Not approved</th><th>Likely reason</th></tr></thead><tbody>')
        for r in bad:
            cls = "unknown" if r.ready else "review"
            items = "<ul>" + "".join(f"<li>{e(t)}</li>" for t in r.reasons) + "</ul>" if r.reasons else \
                f'<span class="badge ok">{e(terms["ready"])}</span>'
            out.append(f'<tr><td class="loc" data-label="Place">{e(r.place)}</td>'
                       f'<td data-label="Status"><span class="badge {cls if not r.ready else "unknown"}">Unapproved</span></td>'
                       f'<td data-label="Likely reason">{items}</td></tr>')
        out.append('</tbody></table>')
    if untold:
        out.append('<p class="subhead">Could not tell</p><ul>' + "".join(
            f'<li><strong>{e(r.place)}</strong>: {e("; ".join(r.reasons))}</li>' for r in untold) + '</ul>')
    return out


def _head(title: str, dates, extra: List[str]) -> List[str]:
    e = escape
    return ['<!DOCTYPE html>', '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f'<title>{e(title)} - {e(date_label(dates))}</title>',
            f'<style>{CSS}.badge.ok{{color:var(--ok);background:var(--okbg);border-color:var(--ok)}}</style>'
            '</head><body><main>',
            f'<h1>{e(title)}</h1>', f'<p class="date">{e(date_label(dates))}</p>'] + extra


def _banner(m) -> List[str]:
    e, out = escape, []
    if getattr(m, "late_note", ""):
        out.append(f'<p class="warn">{e(m.late_note)}</p>')
    if m.licence_notice or m.licence_problem:
        out.append(f'<p class="warn">{e(m.licence_notice or m.licence_line)}</p>')
    return out


_FOOT = ('<footer><p>Reasons are likely ones taken from the export, not proven causes. '
         'Made by a computer program; nothing was approved or sent anywhere.</p></footer></main></body></html>\n')


def brief_html(report, terms: Dict = None) -> str:
    terms, e = terms or load_terms(), escape
    if isinstance(report, MultiReport):
        out = _head(report.title, report.dates, _banner(report))
        for s in report.failed_sections:
            out.append(f'<p class="down">{e(s.name)}: {e(s.error)}</p>')
        for s in report.ok_sections:
            rows = rows_for(s.report, terms)
            line, clean = counts(rows)
            out.append(f'<h2 class="inst">{e(s.name)}</h2><p class="subhead">{e(line)}</p>')
            out += [f'<p class="note">{e(n)}</p>' for n in _notes(s.report)]
            out += _table(rows, terms)
        return "\n".join(out + [_FOOT])
    rows = rows_for(report, terms)
    line, clean = counts(rows)
    out = _head(report.title, report.dates, [f'<p class="headline">{e(line)}</p>'] + _banner(report))
    out += [f'<p class="note">{e(n)}</p>' for n in _notes(report)]
    return "\n".join(out + _table(rows, terms) + [_FOOT])


def _text_block(rows: List[Row], terms: Dict) -> List[str]:
    lines = []
    bad = [r for r in rows if r.state == UNAPPROVED_STATE]
    untold = [r for r in rows if r.state == UNTOLD]
    width = max([len(r.place) for r in bad + untold] or [0])
    for r in bad:
        first = f"* {r.place.ljust(width)}  "
        pad = " " * len(first)
        parts = r.reasons or [terms["ready"]]
        lines.append(textwrap.fill(parts[0], 100, initial_indent=first, subsequent_indent=pad))
        lines += [textwrap.fill(t, 100, initial_indent=pad, subsequent_indent=pad) for t in parts[1:]]
    if untold:
        lines += ["", "Could not tell:"]
        lines += [textwrap.fill(f"{r.place}: " + "; ".join(r.reasons), 76, initial_indent="  - ",
                                subsequent_indent="    ") for r in untold]
    return lines


def brief_text(report, terms: Dict = None) -> str:
    terms = terms or load_terms()
    wrap = lambda s: textwrap.fill(s, 76)
    if isinstance(report, MultiReport):
        ok = report.ok_sections
        allrows = [r for s in ok for r in rows_for(s.report, terms)]
        bad, failed = sum(1 for r in allrows if r.state == UNAPPROVED_STATE), len(report.failed_sections)
        what = ("no data (UNKNOWN)" if not ok else f"{bad} unapproved" if bad else
                "nothing outstanding to approve" if counts(allrows)[1] else "no place shows as unapproved")
        if failed and ok:
            what += f", {failed} connection{'' if failed == 1 else 's'} could not connect"
        lines = [f"Subject: {report.title} - {date_label(report.dates)}: {what}", ""]
        for s in report.failed_sections:
            lines += [wrap(f"{s.name.upper()}: {s.error}"), ""]
        if report.late_note:
            lines += [wrap("LATE: " + report.late_note.removeprefix("Late: ")), ""]
        for s in report.ok_sections:
            rows = rows_for(s.report, terms)
            lines += [s.name.upper(), "=" * len(s.name), counts(rows)[0]]
            lines += [wrap(n) for n in _notes(s.report)] + [""] + _text_block(rows, terms) + [""]
        lines.append("Likely reasons only, taken from the export. Nothing was approved or sent.")
        return "\n".join(lines) + "\n"
    rows = rows_for(report, terms)
    line, clean = counts(rows)
    bad = sum(1 for r in rows if r.state == UNAPPROVED_STATE)
    subject = f"{report.title} - {date_label(report.dates)}: " + (
        "nothing outstanding to approve" if clean else
        f"{bad} unapproved" if bad else "no place shows as unapproved" if rows else "no data (UNKNOWN)")
    lines = [f"Subject: {subject}", "", line]
    if report.late_note:
        lines += ["", wrap("LATE: " + report.late_note.removeprefix("Late: "))]
    if report.licence_notice or report.licence_problem:
        lines += ["", wrap(report.licence_notice or report.licence_line)]
    lines += [""] + [wrap(n) for n in _notes(report)] + [""] + _text_block(rows, terms)
    lines += ["", "Likely reasons only, taken from the export. Nothing was approved or sent."]
    return "\n".join(lines) + "\n"
