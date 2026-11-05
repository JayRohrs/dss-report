"""The Deposit matcher screen: one page in the same local settings-page style. No script, no network.

Top: three counts (matched / needs a look / cannot tell). Below: one row per place with its explanation in a
sentence or two and three actions: Looks right, Flag, Draft a note. A drafted note is text to copy (or a
Microsoft 365 DRAFT); nothing is ever sent from here.
"""

from html import escape
from typing import Dict, Optional

from . import deposits as D

PAGE_CSS = """
body{font-size:16px;line-height:1.45}
main{max-width:1080px}
h1{font-size:1.4rem}
button,a.btn{font-size:.9rem;padding:6px 12px;border-width:1px;border-radius:6px;margin:3px 6px 3px 0;min-height:0}
a.btn{display:inline-block;font-weight:700;text-decoration:none;border:1px solid var(--accent);color:var(--accent)}
.tiles{display:flex;gap:12px;margin:10px 0}
.tile{flex:1;border:2px solid var(--line);border-radius:8px;padding:8px 14px;background:var(--card)}
.tile b{font-size:1.8rem;display:block;line-height:1.1}
.tile.matched{border-color:var(--ok)}.tile.look{border-color:#a15c00}.tile.unknown{border-color:var(--muted)}
.bar{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:10px 0;background:var(--card)}
.bar form{display:inline}
.bar input[type=file]{font:inherit;max-width:260px}
details.assume{border:1px solid var(--line);border-radius:8px;padding:6px 12px;margin:10px 0;background:var(--card)}
details.assume summary{font-weight:700;cursor:pointer}
details.assume li{margin:3px 0}
h2{font-size:1.1rem;margin:18px 0 6px}
.dep{display:grid;grid-template-columns:210px 1fr 270px;gap:10px;border-top:1px solid var(--line);padding:9px 2px}
.dep .who span{color:var(--muted);font-size:.9rem}
.chip{display:inline-block;font-weight:700;font-size:.8rem;border-radius:10px;padding:1px 9px;margin-right:6px;border:1px solid var(--line)}
.chip.matched{color:var(--ok);background:var(--okbg)}.chip.look{color:#7a4500;background:#fff1d6}
.chip.unknown{color:var(--muted);background:var(--card)}.chip.mark{color:var(--ok);background:var(--okbg)}
.chip.flag{color:var(--bad);background:var(--badbg)}
@media (prefers-color-scheme:dark){.chip.look{background:#3a2c10;color:#ffd699}}
.dep ul{margin:4px 0 4px 18px;padding:0}
.note{grid-column:1/-1;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px}
.note textarea{min-height:11em;font-size:.95rem}
.small{color:var(--muted);font-size:.9rem}
@media (max-width:820px){.dep{grid-template-columns:1fr}.tiles{flex-wrap:wrap}}
"""


def _sentence_status(item: D.Item) -> str:
    return {D.MATCHED: "Matched", D.LOOK: "Needs a look", D.UNKNOWN: "Cannot tell"}[item.status]


def _row(item: D.Item, res: D.DepositResult, marks: dict, token: str, note_key: str, note_html: str) -> str:
    e = escape
    mk = marks.get(item.key, {}).get("mark", "")
    chips = f'<span class="chip {item.status}">{_sentence_status(item)}</span>'
    if mk:
        chips += f'<span class="chip {"mark" if mk == "ok" else "flag"}">{"You: looks right" if mk == "ok" else "You: flagged"}</span>'
    why = "".join(f"<li>{e(r)}</li>" for r in item.reasons)
    lines = [res.lines[i] for i in item.lines if i in res.lines]
    if lines:
        why += "".join(f'<li>Bank line: {e(D.money(l.amount))} on {e(D._day(l.day))}, "{e(l.text or "no text")}"</li>' for l in lines)
    score = f" (score {item.score} of 100)" if item.lines else ""
    form = (f'<form method="post" action="/deposits"><input type="hidden" name="t" value="{e(token)}">'
            f'<input type="hidden" name="key" value="{e(item.key)}">'
            '<button type="submit" name="do" value="ok">Looks right</button>'
            '<button type="submit" name="do" value="flag">Flag</button>'
            '<button type="submit" name="do" value="note">Draft a note</button>'
            + ('<button type="submit" name="do" value="clear" title="Remove your mark">Undo</button>' if mk else "") + "</form>")
    extra = f'<div class="note">{note_html}</div>' if note_key == item.key else ""
    return (f'<article class="dep {item.status}"><div class="who"><b>{e(item.place)}</b><br>'
            f'<span>{e(D._day(item.day))} &middot; expects {e(D.money(item.expected))}</span></div>'
            f'<div>{chips}{e(item.explanation)}<details><summary class="small">Why{e(score)}</summary><ul>{why}</ul></details></div>'
            f'<div>{form}</div>{extra}</article>')


def render(chk, marks: dict, token: str, messages=(), problem: str = "", note_key: str = "", note_html: str = "",
           watch_bank: str = "", watch_dss: str = "", last_error: str = "", css: str = "",
           assumptions: Optional[list] = None) -> str:
    e = escape
    out = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<title>Deposit matcher</title><style>{css}{PAGE_CSS}</style></head><body><main>',
           '<h1>Deposit matcher</h1>',
           '<p class="lead">Lines up what each place should have deposited with your bank file, and says why in plain words. '
           'It reads two files, changes nothing and sends nothing.</p>']
    for m in messages:
        out.append(f'<p class="msg ok">{e(m)}</p>')
    if problem:
        out.append(f'<p class="msg bad">{e(problem)}</p>')
    if last_error:
        out.append(f'<p class="msg bad">The last automatic check could not finish: {e(last_error)}</p>')
    out.append(f'<div class="bar"><form method="post" action="/deposits" enctype="multipart/form-data">'
               f'<input type="hidden" name="t" value="{e(token)}">'
               '<label class="small" style="display:inline">Bank file (.csv or .ofx) <input type="file" name="bank" accept=".csv,.ofx,.qfx,.txt"></label> '
               '<label class="small" style="display:inline">DSS list (optional) <input type="file" name="dss" accept=".csv,.tsv,.txt,.xlsx"></label> '
               '<button class="primary" type="submit" name="do" value="upload">Check these files</button></form> '
               f'<form method="post" action="/deposits"><input type="hidden" name="t" value="{e(token)}">'
               f'<button type="submit" name="do" value="watched"{"" if watch_bank else " disabled"}>Check the watched bank file now</button></form> '
               f'<a class="btn" href="/?t={e(token)}">Settings</a>'
               + (f'<div class="small">Watching: {e(watch_bank)}. A new bank file there is checked by the daily schedule with no clicks.</div>'
                  if watch_bank else
                  '<div class="small">Nothing is watched yet. In Settings, section 9, give a bank file or folder and the daily schedule will check each new bank export for you.</div>')
               + '</div>')
    if chk is None:
        out.append('<div class="card"><h3>No bank file checked yet</h3><p>Choose a bank export above, or set a folder to watch in Settings. '
                   'To see how it works first, try the made-up sample files (no real data).</p>'
                   f'<form method="post" action="/deposits"><input type="hidden" name="t" value="{e(token)}">'
                   '<button type="submit" name="do" value="sample">Try the made-up sample files</button></form></div>')
        if assumptions:
            out.append(_assumptions(assumptions))
        out.append("</main></body></html>")
        return "\n".join(out)
    r = chk.result
    reviewed_ok = sum(1 for i in r.items if marks.get(i.key, {}).get("mark") == "ok")
    flagged = sum(1 for i in r.items if marks.get(i.key, {}).get("mark") == "flag")
    out.append(f'<p class="small">Bank file: <b>{e(chk.bank_name)}</b> ({e(D._day(r.bank_first)) if r.bank_first else "no dates"}'
               f' to {e(D._day(r.bank_last)) if r.bank_last else "no dates"}) &middot; DSS list: <b>{e(chk.dss_name)}</b> &middot; checked {e(chk.at)}</p>')
    out.append('<div class="tiles">'
               f'<div class="tile matched"><b>{r.count(D.MATCHED)}</b>Matched</div>'
               f'<div class="tile look"><b>{r.count(D.LOOK)}</b>Needs a look</div>'
               f'<div class="tile unknown"><b>{r.count(D.UNKNOWN)}</b>Cannot tell</div></div>')
    if reviewed_ok or flagged:
        out.append(f'<p class="small">You marked {reviewed_ok} as looks right and {flagged} as flagged.</p>')
    if r.notes:
        out.append(f'<p class="small">{e(" ".join(r.notes))}</p>')
    if assumptions:
        out.append(_assumptions(assumptions))
    for status, title in ((D.LOOK, "Needs a look"), (D.UNKNOWN, "Cannot tell")):
        rows = [i for i in r.items if i.status == status]
        if rows:
            out.append(f"<h2>{title} ({len(rows)})</h2>")
            out += [_row(i, r, marks, token, note_key, note_html) for i in rows]
    matched = [i for i in r.items if i.status == D.MATCHED]
    if matched:
        out.append(f'<details><summary><b>Matched ({len(matched)})</b> &mdash; amount, date and place agree</summary>')
        out += [_row(i, r, marks, token, note_key, note_html) for i in matched]
        out.append("</details>")
    if not r.items:
        out.append('<p>No deposits to compare: none of the DSS days fall inside the dates of this bank file.</p>')
    if r.unclaimed:
        out.append(f"<h2>Bank lines no place claimed ({len(r.unclaimed)})</h2><ul>"
                   + "".join(f'<li>{e(D.money(r.lines[i].amount))} on {e(D._day(r.lines[i].day))}, "{e(r.lines[i].text or "no text")}"</li>'
                             for i in r.unclaimed) + "</ul>")
    if r.unreadable:
        out.append("<h2>Bank lines that could not be read</h2><ul>" + "".join(f"<li>{e(u)}</li>" for u in r.unreadable) + "</ul>")
    out.append("</main></body></html>")
    return "\n".join(out)


def _assumptions(lines) -> str:
    items = "".join(f"<li><b>{escape(a)}:</b> {escape(b)}</li>" for a, b in lines)
    return ('<details class="assume"><summary>Assumed, not confirmed: the Over/Short sign, the R365 deposit field and your bank\'s file format. Click to see all.</summary><ul>' + items +
            '</ul><p class="small">These are guesses written down, not facts. They can be changed in deposit_matcher.toml '
            'in your DssReport folder.</p></details>')
