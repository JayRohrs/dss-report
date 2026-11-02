"""The brief report: only what is still unapproved, fast to read, on a phone first and a desktop second.

For each place that is NOT approved it gives one short line: "Ready to approve" when the export flags nothing
else, or a LIKELY reason in plain accounting words ("Needs to balance: Over/Short -$23.50"). The wording is in
data/reason_terms.toml and can be changed by the owner. The export cannot say why a day is unfinished, so
reasons are always labelled "Likely" and never stated as the cause, and nothing here approves anything.

If every place is approved the report says so. A place whose status cannot be told (no row, a blank or unclear
status such as "In Progress", a file older than today, conflicting rows, no approval column) is listed
separately as "Could not tell"; it is never counted as approved and never hidden.

The page is one self-contained HTML file (no scripts, no images, no web fonts). It has its own print styles, so
"Print" / "Save as PDF" from any browser gives a clean black-on-white copy.
"""

import re
import textwrap
import tomllib
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Dict, List, Tuple

from .paths import app_dir
from .render import date_label
from .report import LocationResult, MultiReport, Report
from .rules import CASH, CONFLICT, ISSUE, LABELS, NO_DATA, UNAPPROVED

APPROVED, UNAPPROVED_STATE, UNTOLD = "approved", "unapproved", "could not tell"
NOTHING = "Nothing outstanding to approve."
SAMPLE_NOTE = "Sample report: every name and number in it is invented."
_LIMIT = re.compile(r"\s*\(limit [^)]*\)")

# Used when a wording file is missing or broken; the shipped data/reason_terms.toml carries the same words.
_DEFAULT_UNTOLD = {
    "no_data": "No data for this day",
    "conflict": "The file has two rows for this day that disagree",
    "stale": "The file is not from today, so approval cannot be told",
    "unclear_status": "Status is '{value}', which is not treated as approved or not",
    "no_column": "No approval column in this file",
}
_DEFAULT_TERMS = {"ready": "Ready to approve", "reasons": {}, "untold": dict(_DEFAULT_UNTOLD)}


def load_terms(shipped: Path = None, user: Path = None) -> Dict:
    shipped = shipped or Path(__file__).resolve().parent / "data" / "reason_terms.toml"
    user = user or app_dir() / "reason_terms.toml"
    out = {"ready": _DEFAULT_TERMS["ready"], "reasons": {}, "untold": dict(_DEFAULT_UNTOLD)}
    for path in (shipped, user):
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue                                   # a broken wording file never stops the report
        if isinstance(raw.get("ready"), str) and raw["ready"].strip():
            out["ready"] = raw["ready"].strip()
        for table in ("reasons", "untold"):
            values = raw.get(table)
            for k, v in (values.items() if isinstance(values, dict) else ()):
                if isinstance(v, str) and v.strip():
                    out[table][k] = v.strip()
    return out


@dataclass
class Row:
    place: str
    state: str                  # APPROVED / UNAPPROVED_STATE / UNTOLD
    reasons: List[str]          # likely reasons (unapproved) or why it could not be told
    day: str = ""
    instance: str = ""          # which R365 connection it came from ("" when there is only one)

    @property
    def ready(self) -> bool:
        return self.state == UNAPPROVED_STATE and not self.reasons


def _untold_text(f, terms: Dict) -> str:
    """Plain words for why a day could not be told. Wording lives in reason_terms.toml ([untold])."""
    words = terms["untold"]
    if f.rule == NO_DATA:
        return words["no_data"]
    if f.rule == CONFLICT:
        return words["conflict"]
    if f.text.startswith("Approval status cannot be established"):
        return words["stale"]
    m = re.search(r"'([^']+)'", f.text)
    if "not treated as approved or not approved" in f.text and m:
        return words["unclear_status"].replace("{value}", m.group(1))
    return _LIMIT.sub("", f.text)


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


def rows_for(report: Report, terms: Dict = None, instance: str = "") -> List[Row]:
    terms = terms or load_terms()
    approval_checked = LABELS[UNAPPROVED] not in report.needs_mapping and not _approval_off(report)
    # If the file cannot say what the cash difference is, an unapproved day must not look "ready".
    cash_unchecked = LABELS[CASH] in report.needs_mapping
    rows = []
    for res in list(report.attention) + list(report.clear):
        rows.append(_row(res, report, approval_checked, cash_unchecked, terms, instance))
    order = {UNAPPROVED_STATE: 0, UNTOLD: 1, APPROVED: 2}
    rows.sort(key=lambda r: (order[r.state], r.ready, r.place.lower()))     # flagged ones before "ready" ones
    return rows


def _row(res: LocationResult, report: Report, approval_checked: bool, cash_unchecked: bool, terms: Dict,
         instance: str = "") -> Row:
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
            untold.append(tag + _untold_text(f, terms))
        elif f.kind == ISSUE:
            reasons.append(tag + _reason(f.rule, f.text, terms))
        # a blank value elsewhere ("cash over/short is blank") is not a reason; it is left out of the brief
    if unapproved:
        if not reasons and cash_unchecked:
            reasons.append(terms["reasons"].get("cash_unchecked", "Cash difference not checked: this file has no "
                                                                  "Over/Short column"))
        return Row(res.name, UNAPPROVED_STATE, reasons, instance=instance)
    if untold or not approval_checked:
        return Row(res.name, UNTOLD, untold or [terms["untold"]["no_column"]], instance=instance)
    return Row(res.name, APPROVED, [], instance=instance)


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


# Notes that change how far the answer can be trusted. They are lifted out of the small print into a box near
# the top. Everything else about a file stays in "About the files" at the bottom.
_IMPORTANT = ("Partial list", "This file is dated", "This file does not say when",
              "Headings this program did not recognise")
_IMPORTANT_ANYWHERE = ("had rows that disagree", "could not be read as a number", "were set aside")


def _important(note: str) -> bool:
    if note.startswith(_IMPORTANT) or any(w in note for w in _IMPORTANT_ANYWHERE):
        return True
    return note.startswith("This file has no") and "not needed by any check" not in note


# ------------------------------------------------------------------------------------------ the view model

@dataclass
class Part:
    """One R365 connection as the brief sees it."""
    name: str
    rows: List[Row]
    notes: List[str]


def _parts(report, terms: Dict) -> Tuple[List[Part], list]:
    if isinstance(report, MultiReport):
        return ([Part(s.name, rows_for(s.report, terms, s.name), _notes(s.report)) for s in report.ok_sections],
                list(report.failed_sections))
    return [Part("", rows_for(report, terms), _notes(report))], []


def _all_rows(parts: List[Part]) -> List[Row]:
    return [r for p in parts for r in p.rows]


def _tally(rows: List[Row]) -> Dict[str, int]:
    bad = [r for r in rows if r.state == UNAPPROVED_STATE]
    return {"flagged": sum(1 for r in bad if not r.ready), "ready": sum(1 for r in bad if r.ready),
            "untold": sum(1 for r in rows if r.state == UNTOLD),
            "approved": sum(1 for r in rows if r.state == APPROVED), "total": len(rows)}


def _headline(rows: List[Row], failed: int) -> Tuple[str, bool]:
    line, clean = counts(rows)
    if failed:
        n = f"{failed} connection{'' if failed == 1 else 's'}"
        if clean:
            line = "Nothing outstanding to approve at the connections that answered"
        line = f"{line.rstrip('.')}. {n} could not be reached, so {'its' if failed == 1 else 'their'} places are not checked."
        clean = False
    return line, clean


def _problems(rows: List[Row]) -> List[Row]:
    """Not approved: places with something flagged first, then the ready ones."""
    return sorted((r for r in rows if r.state == UNAPPROVED_STATE),
                  key=lambda r: (r.ready, r.place.lower(), r.instance.lower()))


def _untold_groups(rows: List[Row]) -> List[Tuple[str, str, List[Row]]]:
    """Could-not-tell rows. Three or more places on one connection with the same reason (a stale file makes
    every place say the same thing) are shown as one entry instead of a wall of repeats."""
    untold = sorted((r for r in rows if r.state == UNTOLD), key=lambda r: (r.instance.lower(), r.place.lower()))
    by_key: Dict[Tuple[str, str], List[Row]] = {}
    for r in untold:
        by_key.setdefault((r.instance, "; ".join(r.reasons)), []).append(r)
    out, seen = [], set()
    for r in untold:
        key = (r.instance, "; ".join(r.reasons))
        if key in seen:
            continue
        group = by_key[key]
        if len(group) >= 3:
            seen.add(key)
            out.append((key[0], key[1], group))
        else:
            out.append((key[0], key[1], [r]))
    return out


def friendly_date(dates: List[date]) -> str:
    if not dates:
        return ""
    first = dates[0]
    one = f"{first:%A} {first.day} {first:%B %Y}"
    if len(dates) == 1:
        return one
    last = dates[-1]
    return f"{first.day} {first:%b} to {last.day} {last:%b %Y} ({len(dates)} days)"


# ------------------------------------------------------------------------------------------ the HTML page

CSS = """
:root{--bg:#f1f4f7;--card:#ffffff;--fg:#17202a;--muted:#4b5a69;--line:#ccd4dc;
--bad:#8a1c1c;--badbg:#fdecec;--unk:#6b4a00;--unkbg:#fff4d6;--ok:#14532d;--okbg:#e7f6ec}
@media (prefers-color-scheme:dark){:root{--bg:#12161b;--card:#1b2229;--fg:#eef1f4;--muted:#b3bdc7;--line:#38444f;
--bad:#ffb4b4;--badbg:#3b1b1b;--unk:#ffd88a;--unkbg:#3a2f12;--ok:#9fe3b6;--okbg:#14301e}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:18px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
main{max-width:1040px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.45rem;line-height:1.25;margin:0 0 4px}
h2{font-size:1.2rem;line-height:1.3;margin:28px 0 4px}
h2 .count{display:inline-block;min-width:1.7em;text-align:center;font-size:.9rem;padding:0 8px;border-radius:99px;
border:1px solid var(--line);background:var(--card);color:var(--muted);margin-left:6px;vertical-align:2px}
.date{color:var(--muted);margin:0 0 14px;font-size:1rem}
.sample{display:inline-block;margin:0 0 10px;padding:3px 10px;border:2px dashed var(--unk);border-radius:6px;
background:var(--unkbg);color:var(--unk);font-size:.9rem;font-weight:700}
.summary{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:0 0 16px}
.summary.clear{background:var(--okbg);border-color:var(--ok);color:var(--ok)}
.headline{font-size:1.2rem;font-weight:700;line-height:1.35;margin:0}
.tiles{list-style:none;display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:0;margin:14px 0 0}
.tile{border:1px solid var(--line);border-radius:10px;padding:8px 4px;text-align:center;background:var(--bg)}
.tile b{display:block;font-size:1.7rem;line-height:1.15}
.tile span{display:block;font-size:.8rem;line-height:1.25;color:var(--muted)}
.tile.flag{border-color:var(--bad)}.tile.flag b{color:var(--bad)}
.tile.untold{border-color:var(--unk);border-style:dashed}.tile.untold b{color:var(--unk)}
.tile.ready b,.tile.done b{color:var(--ok)}
.warn,.down{border-left:6px solid var(--unk);background:var(--unkbg);color:var(--fg);padding:10px 14px;margin:0 0 12px;
border-radius:6px}
.down{border-color:var(--bad);background:var(--badbg);font-weight:600}
.warn ul{margin:6px 0 0;padding-left:1.1em}
.sub{color:var(--muted);font-size:1rem;margin:0 0 12px}
.cards{list-style:none;margin:0;padding:0;display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(min(100%,310px),1fr))}
.card{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--bad);border-radius:10px;padding:12px 14px;
break-inside:avoid;min-width:0}
.card.ready{border-left-color:var(--ok)}
.card.untold{border-left-color:var(--unk)}
.card.wide{grid-column:1/-1}
.place{font-weight:700;font-size:1.1rem;line-height:1.3;overflow-wrap:anywhere}
.where{color:var(--muted);font-size:.9rem;margin:0 0 6px}
.badge{display:inline-block;font-weight:700;font-size:.95rem;padding:1px 10px;border-radius:6px;border:2px solid;white-space:nowrap}
.badge.review{color:var(--bad);background:var(--badbg);border-color:var(--bad)}
.badge.ok{color:var(--ok);background:var(--okbg);border-color:var(--ok)}
.badge.unknown{color:var(--unk);background:var(--unkbg);border-color:var(--unk);border-style:dashed}
.label{color:var(--muted);font-size:.85rem;margin:8px 0 0;text-transform:uppercase;letter-spacing:.04em}
.why{margin:2px 0 0;padding-left:1.1em}
.why li{margin:2px 0;overflow-wrap:anywhere}
.names{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:6px}
.names li{border:1px solid var(--line);border-radius:6px;padding:0 8px;font-size:.95rem;background:var(--bg)}
.conns{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.conns>li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.conns strong{display:block}
.conns span{color:var(--muted);font-size:1rem}
.files p{margin:0 0 8px;font-size:1rem;color:var(--muted)}
.files strong{color:var(--fg)}
footer{margin-top:32px;color:var(--muted);font-size:.95rem;border-top:1px solid var(--line);padding-top:12px}
footer p{margin:0 0 6px}
@media (min-width:720px){main{padding:32px 24px 64px}h1{font-size:1.7rem}.headline{font-size:1.35rem}
.tile b{font-size:2rem}.tile span{font-size:.95rem}}
@media print{
:root{--bg:#fff;--card:#fff;--fg:#000;--muted:#333;--line:#888;--bad:#600;--badbg:#fff;--unk:#4a3300;--unkbg:#fff;
--ok:#063;--okbg:#fff}
@page{margin:14mm}
body{background:#fff;color:#000;font-size:11pt;line-height:1.4}
main{max-width:none;padding:0}
.summary,.card,.conns>li,.tile{box-shadow:none;background:#fff}
.summary.clear{background:#fff;color:#000;border-color:#000}
.cards{grid-template-columns:repeat(2,1fr)}
h2{break-after:avoid}
.warn,.down,.summary,.conns>li{break-inside:avoid}
}
"""


def _head(title: str, dates, sample: bool) -> List[str]:
    e = escape
    out = ['<!DOCTYPE html>', '<html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<meta name="color-scheme" content="light dark">',
           f'<title>{e(title)} - {e(date_label(dates))}</title>',
           f'<style>{CSS}</style></head><body><main>']
    if sample:
        out.append(f'<p class="sample">{e(SAMPLE_NOTE)}</p>')
    out += [f'<h1>{e(title)}</h1>', f'<p class="date">{e(friendly_date(dates))}</p>']
    return out


def _banner(m) -> List[str]:
    e, out = escape, []
    if getattr(m, "late_note", ""):
        out.append(f'<p class="warn">{e(m.late_note)}</p>')
    if getattr(m, "licence_notice", "") or getattr(m, "licence_problem", False):
        out.append(f'<p class="warn">{e(m.licence_notice or m.licence_line)}</p>')
    return out


def _tiles(t: Dict[str, int]) -> str:
    def tile(cls, n, label):
        return f'<li class="tile {cls}"><b>{n}</b><span>{label}</span></li>'
    return ('<ul class="tiles">' + tile("flag", t["flagged"], "Needs a look") + tile("ready", t["ready"], "Ready to approve")
            + tile("untold", t["untold"], "Could not tell") + tile("done", t["approved"], "Approved") + '</ul>')


def _problem_card(r: Row, terms: Dict, e=escape) -> str:
    where = f'<p class="where">{e(r.instance)}</p>' if r.instance else ""
    if r.ready:
        return (f'<li class="card ready"><div class="place">{e(r.place)}</div>{where}'
                f'<span class="badge ok">{e(terms["ready"])}</span>'
                '<p class="label">Not approved yet</p><p style="margin:2px 0 0">Nothing else in the export is flagged.</p></li>')
    items = "".join(f"<li>{e(t)}</li>" for t in r.reasons)
    return (f'<li class="card"><div class="place">{e(r.place)}</div>{where}'
            '<span class="badge review">Unapproved</span>'
            f'<p class="label">Likely reason</p><ul class="why">{items}</ul></li>')


def _untold_card(instance: str, reason: str, group: List[Row], e=escape) -> str:
    where = f'<p class="where">{e(instance)}</p>' if instance else ""
    if len(group) == 1:
        return (f'<li class="card untold"><div class="place">{e(group[0].place)}</div>{where}'
                f'<span class="badge unknown">Could not tell</span><p style="margin:6px 0 0">{e(reason)}</p></li>')
    names = "".join(f"<li>{e(r.place)}</li>" for r in group)
    head = f"{len(group)} places" + (f" on {e(instance)}" if instance else "")
    return (f'<li class="card untold wide"><div class="place">{head}</div>'
            f'<span class="badge unknown">Could not tell</span><p style="margin:6px 0 0">{e(reason)}</p>'
            f'<ul class="names">{names}</ul></li>')


def brief_html(report, terms: Dict = None, sample: bool = False) -> str:
    terms, e = terms or load_terms(), escape
    parts, failed = _parts(report, terms)
    rows = _all_rows(parts)
    headline, clean = _headline(rows, len(failed))
    out = _head(report.title, report.dates, sample)
    t = _tally(rows)
    out.append(f'<section class="summary{" clear" if clean else ""}" aria-label="Summary">'
               f'<p class="headline">{e(headline)}</p>' + ("" if clean or not rows else _tiles(t)) + '</section>')
    out += _banner(report)
    out += [f'<p class="down">{e(s.name)}: {e(s.error)}</p>' for s in failed]
    heads = [(p.name, n) for p in parts for n in p.notes if _important(n)]
    if heads and len(parts) == 1:
        out.append('<div class="warn"><strong>Worth knowing</strong><ul>' + "".join(
            f'<li>{e(n)}</li>' for _, n in heads) + '</ul></div>')
    elif heads:
        out.append(f'<p class="warn"><strong>Worth knowing:</strong> {len(heads)} note{"" if len(heads) == 1 else "s"} '
                   'about the files, under "By connection".</p>')

    problems = _problems(rows)
    if problems:
        out.append(f'<h2>Not approved yet<span class="count">{len(problems)}</span></h2>'
                   '<p class="sub">Places with something flagged come first. These are likely reasons taken from '
                   'the export, not proven causes.</p>')
        out.append('<ul class="cards">' + "".join(_problem_card(r, terms) for r in problems) + '</ul>')
    groups = _untold_groups(rows)
    if groups:
        n = sum(len(g[2]) for g in groups)
        out.append(f'<h2>Could not tell<span class="count">{n}</span></h2>'
                   '<p class="sub">The report will not guess. None of these is counted as approved. '
                   'Check them in R365.</p>')
        out.append('<ul class="cards">' + "".join(_untold_card(*g) for g in groups) + '</ul>')

    if len(parts) > 1:
        out.append('<h2>By connection</h2><ul class="conns">')
        for p in parts:
            pt = _tally(p.rows)
            notes = [n for n in p.notes if _important(n)]
            out.append(f'<li><strong>{e(p.name)}</strong><span>{e(counts(p.rows)[0])} '
                       f'{pt["approved"]} of {pt["total"]} places approved.</span>'
                       + ('<ul class="why">' + "".join(f"<li>{e(n)}</li>" for n in notes) + '</ul>' if notes else "")
                       + '</li>')
        out.append('</ul>')
    elif parts and parts[0].name == "" and rows:
        out.append(f'<p class="sub" style="margin-top:20px">{t["approved"]} of {t["total"]} places approved.</p>')

    small = [(p.name, n) for p in parts for n in p.notes if not _important(n)]
    if small:
        out.append('<h2>About the files</h2><div class="files">' + "".join(
            f'<p>{("<strong>" + e(name) + "</strong>: ") if name else ""}{e(n)}</p>' for name, n in small) + '</div>')

    out.append('<footer><p>"Ready to approve" means the export flags nothing else. The export has no POS import, '
               'receipt or payment columns, so those were not checked.</p>'
               '<p>Over/Short is shown as R365 gives it; which sign means short is not confirmed.</p>'
               f'<p>Made by a computer program. Nothing was approved or sent anywhere.'
               f'{" " + e(SAMPLE_NOTE) if sample else ""}</p></footer></main></body></html>\n')
    return "\n".join(out)


# ------------------------------------------------------------------------------------------ the email text

def _subject_what(rows: List[Row], clean: bool, failed: int, has_parts: bool) -> str:
    bad = sum(1 for r in rows if r.state == UNAPPROVED_STATE)
    untold = sum(1 for r in rows if r.state == UNTOLD)
    if not has_parts:
        return "no data (UNKNOWN)"
    if clean:
        what = "nothing outstanding to approve"
    elif bad:
        what = f"{bad} unapproved"
        if untold:
            what += f", {untold} could not be told"
    elif untold:
        what = f"{untold} could not be told"
    else:
        what = "no place shows as unapproved" if rows else "no data (UNKNOWN)"
    if failed:
        what += f", {failed} connection{'' if failed == 1 else 's'} could not connect"
    return what


def _text_problem(r: Row, terms: Dict) -> List[str]:
    where = f" ({r.instance})" if r.instance else ""
    lines = [textwrap.fill(f"* {r.place}{where}", 76, subsequent_indent="    ")]
    lines += [textwrap.fill(t, 100, initial_indent="    ", subsequent_indent="    ") for t in (r.reasons or [terms["ready"]])]
    return lines


def _text_untold(instance: str, reason: str, group: List[Row]) -> str:
    who = ", ".join(r.place for r in group)
    if len(group) == 1:
        where = f" ({instance})" if instance else ""
        return textwrap.fill(f"{who}{where}: {reason}", 76, initial_indent="  - ", subsequent_indent="    ")
    where = f" on {instance}" if instance else ""
    return textwrap.fill(f"{len(group)} places{where}: {reason}. {who}.", 76, initial_indent="  - ",
                         subsequent_indent="    ")


def brief_text(report, terms: Dict = None, sample: bool = False) -> str:
    terms = terms or load_terms()
    wrap = lambda s: textwrap.fill(s, 76)
    parts, failed = _parts(report, terms)
    rows = _all_rows(parts)
    headline, clean = _headline(rows, len(failed))
    lines = [f"Subject: {report.title} - {date_label(report.dates)}: "
             f"{_subject_what(rows, clean and not failed, len(failed), bool(parts))}", ""]
    if sample:
        lines += [SAMPLE_NOTE, ""]
    lines.append(headline)
    for s in failed:
        lines += ["", wrap(f"{s.name.upper()}: {s.error}")]
    if getattr(report, "late_note", ""):
        lines += ["", wrap("LATE: " + report.late_note.removeprefix("Late: "))]
    if getattr(report, "licence_notice", "") or getattr(report, "licence_problem", False):
        lines += ["", wrap(report.licence_notice or report.licence_line)]
    heads = [(p.name, n) for p in parts for n in p.notes if _important(n)]
    if heads and len(parts) == 1:
        lines += ["", "WORTH KNOWING"]
        lines += [textwrap.fill(n, 76, initial_indent="  - ", subsequent_indent="    ") for _, n in heads]
    elif heads:
        lines += ["", wrap(f"WORTH KNOWING: {len(heads)} note{'' if len(heads) == 1 else 's'} about the files, under "
                           "BY CONNECTION.")]
    problems = _problems(rows)
    if problems:
        lines += ["", "NOT APPROVED YET (flagged first; likely reasons only)"]
        for r in problems:
            lines += _text_problem(r, terms)
    groups = _untold_groups(rows)
    if groups:
        lines += ["", "COULD NOT TELL (the report will not guess)"]
        lines += [_text_untold(*g) for g in groups]
    if len(parts) > 1:
        lines += ["", "BY CONNECTION"]
        for p in parts:
            pt = _tally(p.rows)
            lines.append(wrap(f"{p.name}: {counts(p.rows)[0]} {pt['approved']} of {pt['total']} places approved."))
            lines += [textwrap.fill(n, 76, initial_indent="  - ", subsequent_indent="    ") for n in p.notes if _important(n)]
    small = [(p.name, n) for p in parts for n in p.notes if not _important(n)]
    if small:
        lines += ["", "ABOUT THE FILES"]
        lines += [textwrap.fill(f"{name + ': ' if name else ''}{n}", 76, initial_indent="  - ", subsequent_indent="    ")
                  for name, n in small]
    lines += ["", "Likely reasons only, taken from the export. Nothing was approved or sent."]
    return "\n".join(lines) + "\n"
