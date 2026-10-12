"""Writes the self-contained HTML page and the plain-text email body."""

import textwrap
from html import escape

from .report import NEEDS_REVIEW, MultiReport, Report, date_label, reasons

SOURCE_NOTE = {
    "model": "Summary sentence written by a local model and checked against the numbers.",
    "template": "Standard summary sentence (the local model was unavailable or disagreed with the numbers).",
}

CSS = """
:root{--bg:#fff;--fg:#1b1f23;--muted:#4a5560;--line:#c9d1d9;--card:#f4f6f8;
--bad:#8a1c1c;--badbg:#fdecec;--unk:#6b4a00;--unkbg:#fff4d6;--ok:#14532d;--okbg:#e7f6ec}
@media (prefers-color-scheme:dark){:root{--bg:#14181c;--fg:#eef1f4;--muted:#b3bdc7;--line:#3a444e;
--card:#1e242a;--bad:#ffb4b4;--badbg:#3b1b1b;--unk:#ffd88a;--unkbg:#3a2f12;--ok:#9fe3b6;--okbg:#14301e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:19px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
main{max-width:960px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:1.5rem;margin:0 0 4px}
h2{font-size:1.3rem;margin:32px 0 12px}
.date{color:var(--muted);margin:0 0 16px}
.headline{font-size:1.35rem;font-weight:700;line-height:1.4;background:var(--card);
border:2px solid var(--line);border-radius:10px;padding:16px;margin:0 0 12px}
.summary{margin:0 0 8px}
.warn{border-left:6px solid var(--unk);background:var(--unkbg);color:var(--fg);padding:10px 14px;margin:0 0 12px;border-radius:6px}
.note{color:var(--muted);font-size:1rem;margin:0 0 8px}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid var(--line)}
th{font-size:1rem;color:var(--muted)}
td.loc{font-weight:700}
.badge{display:inline-block;font-weight:700;font-size:1rem;padding:2px 10px;border-radius:6px;border:2px solid;white-space:nowrap}
.badge.review{color:var(--bad);background:var(--badbg);border-color:var(--bad)}
.badge.unknown{color:var(--unk);background:var(--unkbg);border-color:var(--unk);border-style:dashed}
ul{margin:0;padding-left:1.2em}
li{margin:2px 0}
.clear li{list-style:none;margin:6px 0;padding:10px 12px;background:var(--okbg);color:var(--ok);
border-radius:8px;font-weight:700}
.empty{color:var(--muted)}
.inst{font-size:1.4rem;border-top:3px solid var(--line);padding-top:16px;margin-top:36px}
.subhead{font-weight:700;margin:0 0 8px}
h3{font-size:1.15rem;margin:20px 0 8px}
.down{border-left:6px solid var(--bad);background:var(--badbg);padding:10px 14px;margin:0 0 12px;border-radius:6px;font-weight:600}
footer{margin-top:36px;color:var(--muted);font-size:1rem;border-top:1px solid var(--line);padding-top:12px}
footer ul{padding-left:1.2em}
@media (max-width:640px){
body{font-size:19px}
table,thead,tbody,tr,td{display:block;width:100%}
thead{position:absolute;left:-9999px}
tr{border:2px solid var(--line);border-radius:10px;margin:0 0 14px;padding:4px 0;background:var(--card)}
td{border:0;padding:6px 14px}
td[data-label]::before{content:attr(data-label);display:block;font-size:1rem;color:var(--muted)}
}
"""


def render_html(report) -> str:
    if isinstance(report, MultiReport):
        return _render_multi_html(report)
    e = escape
    out = ['<!DOCTYPE html>', '<html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<title>{e(report.title)} - {e(date_label(report.dates))}</title>',
           f'<style>{CSS}</style></head><body><main>',
           f'<h1>{e(report.title)}</h1>',
           f'<p class="date">{e(date_label(report.dates))}</p>',
           f'<p class="headline">{e(report.headline)}</p>']
    if report.late_note:
        out.append(f'<p class="warn">{e(report.late_note)}</p>')
    if report.licence_notice or report.licence_problem:
        out.append(f'<p class="warn">{e(report.licence_notice or report.licence_line)}</p>')
    if report.needs_mapping:
        out.append('<p class="warn">Not checked (needs mapping): ' + e(", ".join(report.needs_mapping))
                   + '. These checks were skipped because the data source has no confirmed field for them.</p>')
    if report.summary_sentence:
        out.append(f'<p class="summary">{e(report.summary_sentence)}</p>')
        out.append(f'<p class="note">{e(SOURCE_NOTE[report.summary_source])}</p>')

    out.append('<h2>Needs a look</h2>')
    if report.attention:
        out.append('<table><thead><tr><th>Location</th><th>Status</th><th>Why</th></tr></thead><tbody>')
        for r in report.attention:
            cls = "review" if r.status == NEEDS_REVIEW else "unknown"
            items = "".join(f"<li>{e(t)}</li>" for t in reasons(r, report.multi_day))
            out.append(f'<tr><td class="loc" data-label="Location">{e(r.name)}</td>'
                       f'<td data-label="Status"><span class="badge {cls}">{e(r.status)}</span></td>'
                       f'<td data-label="Why"><ul>{items}</ul></td></tr>')
        out.append('</tbody></table>')
    else:
        out.append('<p class="empty">No location needs a look.</p>')

    out.append('<h2>Nothing to review</h2>')
    if report.clear:
        out.append('<ul class="clear">' + "".join(f"<li>{e(r.name)}</li>" for r in report.clear) + '</ul>')
    else:
        out.append('<p class="empty">None.</p>')

    out.append('<footer><p>How this was decided (edit rules.toml to change):</p><ul>'
               + "".join(f"<li>{e(t)}</li>" for t in report.rules_note) + '</ul>')
    if report.scope_note:
        out.append(f'<p>{e(report.scope_note)}</p>')
    if report.licence_line and (not report.licence_problem or report.licence_notice):
        out.append(f'<p>{e(report.licence_line)}</p>')
    out.append(f'<p>Data source: {e(report.source_name)}. Made by a computer program from the '
               'figures above, not from anyone\'s judgement. Nothing was sent anywhere.</p></footer>')
    out.append('</main></body></html>')
    return "\n".join(out) + "\n"


def render_text(report) -> str:
    if isinstance(report, MultiReport):
        return _render_multi_text(report)
    wrap = lambda s, ind="": textwrap.fill(s, 76, initial_indent=ind, subsequent_indent=ind + "  ")
    lines = [f"Subject: {report.title} - {date_label(report.dates)}: "
             + (f"{len(report.attention)} of {report.total} locations need a look"
                if report.attention else
                ("nothing to review" if report.total else "no data (UNKNOWN)")),
             "", wrap(report.headline)]
    if report.late_note:
        lines += ["", wrap("LATE: " + report.late_note.removeprefix("Late: "))]
    if report.licence_notice or report.licence_problem:
        lines += ["", wrap(report.licence_notice or report.licence_line)]
    if report.needs_mapping:
        lines += ["", wrap("NOT CHECKED (needs mapping): " + ", ".join(report.needs_mapping) + ".")]
    if report.summary_sentence:
        lines += ["", wrap(report.summary_sentence)]
    lines += ["", "NEEDS A LOOK", "------------"]
    if report.attention:
        for r in report.attention:
            lines.append(f"* {r.name} [{r.status}]")
            lines += [wrap(t, "    - ") for t in reasons(r, report.multi_day)]
    else:
        lines.append("No location needs a look.")
    lines += ["", "NOTHING TO REVIEW", "-----------------"]
    lines += [f"* {r.name}" for r in report.clear] or ["None."]
    lines += ["", "How this was decided:"] + [wrap(t, "  - ") for t in report.rules_note]
    if report.scope_note:
        lines += ["", wrap(report.scope_note)]
    if report.licence_line and (not report.licence_problem or report.licence_notice):
        lines += ["", wrap(report.licence_line)]
    lines += ["", f"Data source: {report.source_name}. Made by a computer program; nothing was sent anywhere."]
    return "\n".join(lines) + "\n"


def _table_html(report: Report, e=escape, level="h3") -> list:
    out = [f'<{level}>Needs a look</{level}>']
    if report.attention:
        out.append('<table><thead><tr><th>Location</th><th>Status</th><th>Why</th></tr></thead><tbody>')
        for r in report.attention:
            cls = "review" if r.status == NEEDS_REVIEW else "unknown"
            items = "".join(f"<li>{e(t)}</li>" for t in reasons(r, report.multi_day))
            out.append(f'<tr><td class="loc" data-label="Location">{e(r.name)}</td>'
                       f'<td data-label="Status"><span class="badge {cls}">{e(r.status)}</span></td>'
                       f'<td data-label="Why"><ul>{items}</ul></td></tr>')
        out.append('</tbody></table>')
    else:
        out.append('<p class="empty">No location needs a look.</p>')
    out.append(f'<{level}>Nothing to review</{level}>')
    if report.clear:
        out.append('<ul class="clear">' + "".join(f"<li>{e(r.name)}</li>" for r in report.clear) + '</ul>')
    else:
        out.append('<p class="empty">None.</p>')
    return out


def _render_multi_html(m: MultiReport) -> str:
    e = escape
    out = ['<!DOCTYPE html>', '<html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<title>{e(m.title)} - {e(date_label(m.dates))}</title>',
           f'<style>{CSS}</style></head><body><main>',
           f'<h1>{e(m.title)}</h1>',
           f'<p class="date">{e(date_label(m.dates))}</p>',
           f'<p class="headline">{e(m.headline)}</p>']
    if m.late_note:
        out.append(f'<p class="warn">{e(m.late_note)}</p>')
    if m.licence_notice or m.licence_problem:
        out.append(f'<p class="warn">{e(m.licence_notice or m.licence_line)}</p>')
    for s in m.failed_sections:           # a connection that failed is never hidden, and comes first
        out.append(f'<p class="down">{e(s.name)}: {e(s.error)}</p>')
    if m.needs_mapping:
        out.append('<p class="warn">Not checked (needs mapping): ' + e(", ".join(m.needs_mapping))
                   + '. These checks were skipped because a data source has no confirmed field for them.</p>')
    if m.summary_sentence:
        out.append(f'<p class="summary">{e(m.summary_sentence)}</p>')
        out.append(f'<p class="note">{e(SOURCE_NOTE[m.summary_source])}</p>')
    for s in m.ok_sections:
        out.append(f'<h2 class="inst">{e(s.name)}</h2><p class="subhead">{e(s.report.headline)}</p>')
        out += _table_html(s.report)
        if s.report.scope_note:
            out.append(f'<p class="note">{e(s.report.scope_note)}</p>')
    out.append('<footer><p>How this was decided (edit rules.toml to change):</p><ul>'
               + "".join(f"<li>{e(t)}</li>" for t in m.rules_note) + '</ul>')
    if m.licence_line and (not m.licence_problem or m.licence_notice):
        out.append(f'<p>{e(m.licence_line)}</p>')
    out.append(f'<p>Data source: {e(m.source_name)}. Made by a computer program from the '
               'figures above, not from anyone\'s judgement. Nothing was sent anywhere.</p></footer>')
    out.append('</main></body></html>')
    return "\n".join(out) + "\n"


def multi_subject(m: MultiReport) -> str:
    ok = m.ok_sections
    total = sum(s.report.total for s in ok)
    attention = sum(len(s.report.attention) for s in ok)
    failed = len(m.failed_sections)
    if not ok:
        what = "no data (UNKNOWN)"
    elif attention:
        what = f"{attention} of {total} locations need a look"
    else:
        what = "nothing flagged" if failed else "nothing to review"
    if failed and ok:
        what += f", {failed} connection{'' if failed == 1 else 's'} could not connect"
    return f"{m.title} - {date_label(m.dates)}: {what}"


def _render_multi_text(m: MultiReport) -> str:
    wrap = lambda s, ind="": textwrap.fill(s, 76, initial_indent=ind, subsequent_indent=ind + "  ")
    lines = [f"Subject: {multi_subject(m)}", "", wrap(m.headline)]
    if m.late_note:
        lines += ["", wrap("LATE: " + m.late_note.removeprefix("Late: "))]
    if m.licence_notice or m.licence_problem:
        lines += ["", wrap(m.licence_notice or m.licence_line)]
    for s in m.failed_sections:
        lines += ["", wrap(f"{s.name.upper()}: {s.error}")]
    if m.needs_mapping:
        lines += ["", wrap("NOT CHECKED (needs mapping): " + ", ".join(m.needs_mapping) + ".")]
    if m.summary_sentence:
        lines += ["", wrap(m.summary_sentence)]
    for s in m.ok_sections:
        r = s.report
        lines += ["", s.name.upper(), "=" * len(s.name), wrap(r.headline), "", "NEEDS A LOOK", "------------"]
        if r.attention:
            for x in r.attention:
                lines.append(f"* {x.name} [{x.status}]")
                lines += [wrap(t, "    - ") for t in reasons(x, r.multi_day)]
        else:
            lines.append("No location needs a look.")
        lines += ["", "NOTHING TO REVIEW", "-----------------"]
        lines += [f"* {x.name}" for x in r.clear] or ["None."]
    lines += ["", "How this was decided:"] + [wrap(t, "  - ") for t in m.rules_note]
    if m.licence_line and (not m.licence_problem or m.licence_notice):
        lines += ["", wrap(m.licence_line)]
    lines += ["", f"Data source: {m.source_name}. Made by a computer program; nothing was sent anywhere."]
    return "\n".join(lines) + "\n"
