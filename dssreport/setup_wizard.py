"""The guided first-run setup: five short screens in the local settings page.

  1. Add your R365 (name, web-address start, where the Daily Sales Summary list file or folder is, which layout)
  2. Pick your locations (from the places actually found in that file)
  3. Choose when the report builds, and whether to prepare an email (off unless ticked)
  4. Look at the report (made-up demo, or your own file)
  5. Done: what happens next and how to undo

Rules it keeps: it only reads the list file you point at (never changes it, never signs in anywhere, never asks
for a password), it saves only the settings the page already knows (no new secret), and every route goes
through the settings server's token / Host / Origin check and its content-security policy (it uses no
scripts at all). Plain words throughout; every error says what to do.
"""

import re
import shutil
import sys
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Dict, List, Optional

from . import dss_export_source as ds
from . import licence as lic
from . import paths
from .dss_export import ExportError, read_rows
from .dss_inspect import header_row, layout_of
from .errors import ConfigError, DssError
from .settings import Instance, load_settings, save_settings, unique_id
from .state import load_state, save_state

STEPS = [("connection", "Your R365"), ("locations", "Locations"), ("schedule", "When"),
         ("preview", "Look at it"), ("done", "Done")]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_LOCATIONS_SHOWN = 500
LAYOUT_WORDS = {"classic": "classic list", "beta": "newer (beta) list", "": "not told"}

WIZ_CSS = """
.stepbar{display:flex;flex-wrap:wrap;gap:6px 10px;list-style:none;padding:0;margin:0 0 10px;font-size:.95rem}
.stepbar li{padding:4px 10px;border-radius:99px;border:2px solid var(--line);color:var(--muted)}
.stepbar li.now{border-color:var(--accent);color:var(--fg);font-weight:800}
.stepbar li.past{color:var(--ok);border-color:var(--ok)}
.next{border:2px solid var(--accent);border-radius:10px;padding:12px 14px;margin:0 0 16px;font-weight:600}
.stick{position:sticky;bottom:0;background:var(--bg);padding:12px 0;border-top:2px solid var(--line);margin-top:18px}
.btn,button.big{display:inline-block;font:inherit;font-weight:700;min-height:52px;padding:12px 20px;border-radius:10px;
border:2px solid var(--accent);background:var(--bg);color:var(--accent);text-decoration:none;cursor:pointer;
margin:6px 10px 0 0;text-align:center}
.btn.primary,button.big.primary{background:var(--accent);color:var(--bg)}
.pick{display:flex;gap:14px;align-items:center;padding:10px 4px;font-weight:600;min-height:52px;
border-bottom:1px solid var(--line)}
.pick input{width:30px;height:30px;flex:none}
.hint a{color:var(--accent)}
input[type=file]{width:100%;font:inherit;padding:10px}
@media (max-width:520px){.btn,button.big{display:block;width:100%;margin-right:0}}
"""

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


class NotFound(Exception):
    pass


def default_folder() -> str:
    """Where a downloaded list usually lands. Only offered if that folder exists."""
    d = Path.home() / "Downloads"
    return str(d) if d.is_dir() else ""


def clean_subdomain(text: str) -> str:
    """'https://samplegrill.restaurant365.net/x' or 'SampleGrill.restaurant365.net' -> 'samplegrill'."""
    t = (text or "").strip().lower()
    t = re.sub(r"^[a-z]+://", "", t).split("/")[0].split("?")[0].split(":")[0]
    t = t.split(".")[0]
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", t):
        raise ConfigError("Type just the first part of your R365 web address, the part before .restaurant365.net. "
                          "For example, if you open R365 at samplegrill.restaurant365.net, type samplegrill.")
    return t


def clean_name(text: str, others: List[str]) -> str:
    name = re.sub(r"\s+", " ", (text or "").strip())
    if not name:
        raise ConfigError("Give this connection a name, for example the name of the restaurant group.")
    if len(name) > 60:
        raise ConfigError("That name is too long. Use 60 letters or fewer.")
    if name.lower() in {o.lower() for o in others}:
        raise ConfigError(f"You already have a connection called '{name}'. Use a different name, or go back to Settings.")
    return name


def day_words(days: List[int]) -> str:
    if days == [0, 1, 2, 3, 4]:
        return "Monday to Friday"
    return ", ".join(WEEKDAYS[d] for d in sorted(days))


class Wizard:
    def __init__(self, app, css: str = ""):
        self.app = app                  # the SettingsApp (used only to set up the Windows schedule)
        self.css = css

    # ------------------------------------------------------------------ page shell
    def _page(self, token: str, step: int, title: str, nextline: str, body: str, messages=(), problem: str = "",
              inst: Optional[Instance] = None) -> str:
        e = escape
        bar = "".join(f'<li class="{"now" if i == step else "past" if i < step else ""}">{i + 1}. {e(t)}</li>'
                      for i, (_, t) in enumerate(STEPS))
        out = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
               '<meta name="viewport" content="width=device-width, initial-scale=1">',
               f'<title>Set up the morning report</title><style>{self.css}{WIZ_CSS}</style></head><body><main>',
               f'<p class="hint">Step {step + 1} of {len(STEPS)}</p><ol class="stepbar">{bar}</ol>',
               f'<h1>{e(title)}</h1>',
               f'<p class="next"><strong>Your next step:</strong> {e(nextline)}</p>']
        for m in messages:
            out.append(f'<p class="msg ok">{e(m)}</p>')
        if problem:
            out.append(f'<p class="msg bad">{e(problem)}</p>')
        out.append(body)
        out.append(f'<p class="hint">Nothing here asks for a password, and nothing is changed in R365. '
                   f'<a href="/?t={e(token)}">Open all settings instead</a></p></main></body></html>')
        return "\n".join(out)

    @staticmethod
    def _hidden(token: str, inst: Optional[Instance]) -> str:
        e = escape
        return (f'<input type="hidden" name="t" value="{e(token)}">'
                + (f'<input type="hidden" name="inst" value="{e(inst.id)}">' if inst else ""))

    def _back(self, token: str, step: int, inst: Optional[Instance]) -> str:
        if step <= 0:
            return ""
        q = f"?t={escape(token)}" + (f"&amp;inst={escape(inst.id)}" if inst else "")
        return f'<a class="btn" href="/setup/{STEPS[step - 1][0]}{q}">Back</a>'

    def _inst(self, f: Dict[str, str], must: bool = True) -> Optional[Instance]:
        iid = (f.get("inst") or "").strip()
        if not iid:
            if must:
                raise ConfigError("Start at the first screen: add your R365 first.")
            return None
        inst = load_settings().instance(iid) if _ID.fullmatch(iid) else None
        if inst is None or inst.source_kind != ds.KIND:
            raise ConfigError("That connection was not found. Start again from the first screen.")
        return inst

    # ------------------------------------------------------------------ routing
    def get(self, path: str, query: Dict[str, List[str]], token: str) -> str:
        f = {k: v[0] for k, v in query.items() if v}
        step = path.rstrip("/").split("/")[-1] if path.rstrip("/") != "/setup" else "connection"
        if step not in {n for n, _ in STEPS} | {"undo"}:
            raise NotFound(path)
        try:
            if step == "connection":
                return self.step_connection(token, f)
            if step == "preview" and not f.get("inst"):
                return self.step_preview(token, None)      # the demo needs no connection and no licence
            inst = self._inst(f)
            if step == "locations":
                return self.step_locations(token, inst)
            if step == "schedule":
                return self.step_schedule(token, inst)
            if step == "preview":
                return self.step_preview(token, inst)
            if step == "done":
                return self.step_done(token, inst)
            if step == "undo":
                return self.step_undo_confirm(token, inst)
        except DssError as exc:
            return self.step_connection(token, {}, problem=str(exc))
        raise NotFound(path)

    def post(self, path: str, f: Dict[str, str], files: Dict[str, bytes], filename: str, token: str) -> str:
        step = path.rstrip("/").split("/")[-1]
        if step not in ("connection", "locations", "schedule", "preview", "undo"):
            raise NotFound(path)
        try:
            if step == "connection":
                return self.save_connection(token, f, files.get("list"), filename)
            if step == "preview" and not f.get("inst"):
                return self.run_preview(token, None, f)
            inst = self._inst(f)
            if step == "locations":
                return self.save_locations(token, inst, f)
            if step == "schedule":
                return self.save_schedule(token, inst, f)
            if step == "preview":
                return self.run_preview(token, inst, f)
            if step == "undo":
                return self.undo(token, inst)
        except DssError as exc:
            return self._redo(token, step, f, str(exc))
        raise NotFound(path)

    def _redo(self, token: str, step: str, f: Dict[str, str], problem: str) -> str:
        """Show the same screen again with the person's answers kept and a message that says what to do."""
        try:
            inst = self._inst(f, must=False)
            if step == "connection":
                return self.step_connection(token, f, problem=problem)
            if step == "locations" and inst:
                return self.step_locations(token, inst, problem=problem)
            if step == "schedule" and inst:
                return self.step_schedule(token, inst, f, problem=problem)
            if step == "preview":
                return self.step_preview(token, inst, problem=problem)
        except DssError:
            pass
        return self.step_connection(token, {}, problem=problem)

    # ------------------------------------------------------------------ 1. connection
    def step_connection(self, token: str, f: Dict[str, str], problem: str = "", messages=()) -> str:
        e = escape
        inst = None
        if f.get("inst"):
            try:
                inst = self._inst(f)
            except DssError:
                inst = None
        name = f.get("name", inst.name if inst else "")
        sub = f.get("subdomain", inst.subdomain if inst else "")
        where = f.get("where", inst.source_path if inst else default_folder())
        layout = f.get("layout", (inst.layout if inst else "") or "detect")
        radio = "".join(
            f'<label class="pick"><input type="radio" name="layout" value="{v}"{" checked" if layout == v else ""}>'
            f'<span>{e(t)}<span class="hint" style="display:block;font-weight:400">{e(h)}</span></span></label>'
            for v, t, h in (("detect", "Not sure, find out for me (recommended)",
                             "The program looks at the column names in your file and tells you which list it is."),
                            ("classic", "The classic list", "The older Daily Sales Summary list in R365."),
                            ("beta", "The newer (beta) list", "The newer list, which has labor columns.")))
        body = (f'<form method="post" action="/setup/connection" enctype="multipart/form-data">{self._hidden(token, inst)}'
                '<div class="row"><label for="name">Name for this restaurant group</label>'
                f'<input type="text" id="name" name="name" value="{e(name)}" maxlength="60" autocomplete="off" '
                'placeholder="for example: Sample Pier Grill group">'
                '<p class="hint">Only used to label the report.</p></div>'
                '<div class="row"><label for="subdomain">Start of your R365 web address</label>'
                f'<input type="text" id="subdomain" name="subdomain" value="{e(sub)}" autocomplete="off" '
                'placeholder="for example: samplegrill">'
                '<p class="hint">If you open R365 at samplegrill.restaurant365.net, type samplegrill. '
                'It is kept as a label; the program never goes to that address.</p></div>'
                '<div class="row"><label for="where">Where is the Daily Sales Summary list you downloaded?</label>'
                f'<input type="text" id="where" name="where" value="{e(where)}" autocomplete="off" '
                'placeholder="a file, or the folder you download it into">'
                '<p class="hint">Type a folder (such as your Downloads folder) and the program uses the newest list in it '
                'each morning. Or type one file. Tip: in File Explorer, hold Shift, right-click the file or folder, '
                'choose Copy as path, and paste it here.</p></div>'
                '<div class="row"><label for="list">Or choose the file here</label>'
                '<input type="file" id="list" name="list" accept=".xlsx,.csv,.tsv,.txt">'
                '<p class="hint">If you choose a file here, it is used instead of the location above, one time only. '
                'A copy is kept in the program\'s own folder; your file is never changed.</p></div>'
                '<div class="row"><label>Which layout is it?</label>' + radio + '</div>'
                '<div class="stick"><button class="big primary" type="submit">Next: pick your locations</button></div>'
                '</form>'
                f'<form method="post" action="/setup/preview">{self._hidden(token, None)}'
                '<p class="hint">Not ready to connect? <button class="big" type="submit" name="source" value="demo">'
                'Just look at a demo report first</button></p></form>')
        return self._page(token, 0, "Let's set up your morning report",
                          "Fill in these four things, then press the blue button. It takes about three minutes.",
                          body, messages, problem, inst)

    def save_connection(self, token: str, f: Dict[str, str], upload: Optional[bytes], filename: str) -> str:
        s = load_settings()
        editing = self._inst(f, must=False)
        others = [i.name for i in s.instances if not editing or i.id != editing.id]
        name = clean_name(f.get("name", ""), others)
        sub = clean_subdomain(f.get("subdomain", ""))
        choice = f.get("layout", "detect")
        if choice not in ("detect", "classic", "beta"):
            raise ConfigError("Choose one of the three layout answers.")
        if editing is None:
            reason = lic.current_status().can_add_connection(len(s.enabled_instances))
            if reason:
                raise ConfigError(reason + " You can still look at the demo report from the first screen.")

        # find the list file: a chosen file wins over the typed location
        where = (f.get("where") or "").strip().strip('"')
        data: bytes = b""
        if upload:
            name_in = ds.safe_name(filename)
            try:
                rows, _, _ = read_rows(upload, name_in)
            except ExportError:
                raise
            head = header_row(rows)
            if head is None:
                raise ExportError("That file does not look like a Daily Sales Summary list (no Location and Date "
                                  "headings were found). Download the list again from R365 and choose that file.")
            data, mtime, src_name, where = upload, None, name_in, ""
        else:
            path, head = ds.find_dss_file(where)
            data, mtime, src_name = path.read_bytes(), path.stat().st_mtime, path.name

        # which layout: a clear mismatch is stopped, an unclear file keeps the person's answer
        seen = layout_of(head)
        notes: List[str] = []
        if choice == "detect":
            layout = "" if seen == "unknown" else seen
            notes.append(f"This looks like the {LAYOUT_WORDS[seen]}." if seen != "unknown" else
                         "I could not tell which list this is from its column names. That is fine: the file is read by "
                         "column name either way.")
        else:
            if seen not in ("unknown", choice):
                raise ConfigError(f"You said this is the {LAYOUT_WORDS[choice]}, but the columns look like the "
                                  f"{LAYOUT_WORDS[seen]}. Choose 'Not sure, find out for me', or choose the right file.")
            layout = choice
            if seen == "unknown":
                notes.append("The column names do not show which list this is, so I kept your answer.")

        iid = editing.id if editing else unique_id(name, {i.id for i in s.instances})
        inst = editing or Instance(id=iid, name=name, enabled=True, source_kind=ds.KIND)
        inst.name, inst.subdomain, inst.source_path, inst.layout, inst.enabled = name, sub, where, layout, True
        had_copy = ds.export_dir(iid).exists()
        meta = ds.store_export(inst, src_name, data, mtime)          # proves the file reads; keeps a copy
        try:
            if editing is None:
                s.instances.append(inst)
            save_settings(s)
        except DssError:
            if not had_copy:
                shutil.rmtree(ds.export_dir(iid), ignore_errors=True)
            raise
        msgs = [f"Saved '{name}'.", f"Read {meta['original_name']}: {meta['rows']} rows."] + notes
        return self.step_locations(token, inst, messages=msgs)

    # ------------------------------------------------------------------ 2. locations
    def _found_locations(self, inst: Instance) -> List[str]:
        src = ds.DssExportSource(inst, None)
        src.load()
        names = sorted({r.location for r in src.parsed.records}, key=str.lower)
        if not names:
            raise ExportError("The file has no places with a readable date. Go back and choose the list again.")
        return names

    def step_locations(self, token: str, inst: Instance, messages=(), problem: str = "") -> str:
        e = escape
        names = self._found_locations(inst)
        hidden = set(inst.hidden)
        shown = names[:MAX_LOCATIONS_SHOWN]
        rows = "".join(
            f'<label class="pick"><input type="hidden" name="locname_{j}" value="{e(n)}">'
            f'<input type="checkbox" name="loc_{j}" value="1"{"" if n in hidden else " checked"}><span>{e(n)}</span></label>'
            for j, n in enumerate(shown))
        more = (f'<p class="hint">{len(names) - len(shown)} more places are in the file and stay shown. Hide them later in Settings.</p>'
                if len(names) > len(shown) else "")
        body = (f'<form method="post" action="/setup/locations">{self._hidden(token, inst)}'
                f'<p class="hint">These {len(names)} place{"s" if len(names) != 1 else ""} were found in your file. '
                'Tick the ones that belong in the report. Untick any that have closed or that you do not look after; '
                'they go on a hide list and are left out.</p>' + rows + more +
                f'<div class="stick"><button class="big primary" type="submit">Next: choose when it builds</button>'
                f'{self._back(token, 1, inst)}</div></form>')
        return self._page(token, 1, "Which locations?",
                          "Untick any place you do not want, then press the blue button.", body, messages, problem, inst)

    def save_locations(self, token: str, inst: Instance, f: Dict[str, str]) -> str:
        names = self._found_locations(inst)
        keep, posted = set(), {}
        for k, v in f.items():
            if k.startswith("locname_") and k[8:].isdigit():
                posted[k[8:]] = v
        for j, n in posted.items():
            if f"loc_{j}" in f and n in names:
                keep.add(n)
        unposted = [n for n in names if n not in posted.values()]       # beyond the list shown: stay shown
        keep |= set(unposted)
        if not keep:
            raise ConfigError("Keep at least one place ticked, or the report would be empty.")
        s = load_settings()
        cur = s.instance(inst.id)
        cur.hidden = [n for n in names if n not in keep]
        save_settings(s)
        word = f"{len(cur.hidden)} hidden" if cur.hidden else "none hidden"
        return self.step_schedule(token, cur, messages=[f"Saved. {len(keep)} place{'s' if len(keep) != 1 else ''} will be in the report ({word})."])

    # ------------------------------------------------------------------ 3. when + email
    def step_schedule(self, token: str, inst: Instance, f: Optional[Dict[str, str]] = None, messages=(),
                      problem: str = "") -> str:
        e = escape
        s = load_settings()
        f = f or {}
        can_auto = lic.current_status().has(lic.F_SCHEDULE)
        mode = f.get("mode") or ("auto" if s.schedule_enabled else "manual")   # nothing runs by itself unless asked
        time = f.get("schedule_time", s.schedule_time)
        days = [int(k[2:]) for k in f if k.startswith("wd") and k[2:].isdigit()] if f else s.schedule_weekdays
        email_on = ("email_enabled" in f) if f else s.email_enabled
        email_to = f.get("email_to", s.email_to)
        mode_radio = "".join(
            f'<label class="pick"><input type="radio" name="mode" value="{v}"{" checked" if mode == v else ""}>'
            f'<span>{e(t)}<span class="hint" style="display:block;font-weight:400">{e(h)}</span></span></label>'
            for v, t, h in (("auto", "Build it for me each morning",
                             "Uses this computer's task schedule. The computer must be on at that time."
                             + ("" if can_auto else " Your licence does not include this yet."))
                            , ("manual", "Only when I press Run now",
                               "Nothing runs by itself. You open the report whenever you want it.")))
        day_boxes = "".join(
            f'<label class="pick"><input type="checkbox" name="wd{i}" value="1"{" checked" if i in days else ""}>'
            f'<span>{n}</span></label>' for i, n in enumerate(WEEKDAYS))
        body = (f'<form method="post" action="/setup/schedule">{self._hidden(token, inst)}'
                '<div class="row"><label>When should the report be built?</label>' + mode_radio + '</div>'
                '<div class="row"><label for="schedule_time">At what time?</label>'
                f'<input type="time" id="schedule_time" name="schedule_time" value="{e(time)}">'
                '<p class="hint">Your computer\'s clock. Only used if you chose the first answer.</p></div>'
                '<div class="row"><label>On which days?</label>' + day_boxes + '</div>'
                '<div class="row"><label>Email</label>'
                '<label class="pick"><input type="checkbox" name="email_enabled" value="1"'
                f'{" checked" if email_on else ""}><span>Also prepare an email with the report'
                '<span class="hint" style="display:block;font-weight:400">Off unless you tick it. It makes a '
                'draft in your own Microsoft 365 mailbox for you to read and send. Nothing is sent by itself.</span></span></label>'
                f'<label for="email_to">Who should it go to?</label>'
                f'<input type="text" id="email_to" name="email_to" value="{e(email_to)}" autocomplete="off" '
                'placeholder="you@your-company.example">'
                '<p class="hint">One address. Only needed if you ticked the box.</p></div>'
                f'<div class="stick"><button class="big primary" type="submit">Next: look at the report</button>'
                f'{self._back(token, 2, inst)}</div></form>')
        return self._page(token, 2, "When should it be built?",
                          "Choose when, decide about email (it is off), then press the blue button.",
                          body, messages, problem, inst)

    def save_schedule(self, token: str, inst: Instance, f: Dict[str, str]) -> str:
        status = lic.current_status()
        old = load_settings()
        s = load_settings()
        mode = f.get("mode", "manual")
        if mode not in ("auto", "manual"):
            raise ConfigError("Choose when the report should be built.")
        before = {"schedule_enabled": old.schedule_enabled, "schedule_time": old.schedule_time,
                  "schedule_weekdays": list(old.schedule_weekdays), "email_enabled": old.email_enabled,
                  "email_to": old.email_to, "email_send_auto": old.email_send_auto}
        if mode == "auto":
            days = sorted(int(k[2:]) for k in f if k.startswith("wd") and k[2:].isdigit())
            if not days:
                raise ConfigError("Tick at least one day, or choose 'Only when I press Run now'.")
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", (f.get("schedule_time") or "").strip()):
                raise ConfigError("Type the time like 07:00 (a 24-hour clock), or use the time box.")
            if not old.schedule_enabled:
                try:
                    status.require(lic.F_SCHEDULE)
                except DssError as exc:
                    raise ConfigError(f"{exc} You can choose 'Only when I press Run now' instead.")
            s.schedule_enabled, s.schedule_time, s.schedule_weekdays = True, f["schedule_time"].strip(), days
        else:
            s.schedule_enabled = False
        s.email_enabled = "email_enabled" in f
        to = (f.get("email_to") or "").strip()
        if s.email_enabled:
            if not to:
                raise ConfigError("To prepare an email, type who it should go to, or untick the email box.")
            if not old.email_enabled:
                try:
                    status.require(lic.F_EMAIL)
                except DssError as exc:
                    raise ConfigError(f"{exc} Untick the email box to carry on without it.")
            s.email_to = to
        else:
            s.email_send_auto = False
            if to:
                s.email_to = to
        try:
            save_settings(s)                                    # all the format checks live there
        except ConfigError as exc:
            raise ConfigError(f"{exc} Fix that and press the blue button again.")
        st = load_state()
        st.setdefault("setup_undo", {}).setdefault(inst.id, before)
        save_state(st)
        msgs = ["Saved. Email is " + ("on (a draft only)." if s.email_enabled else "off.")]
        if (s.schedule_enabled, s.schedule_time, s.schedule_weekdays) != (
                old.schedule_enabled, old.schedule_time, old.schedule_weekdays):
            msgs.append(self.app._apply_schedule(s))
        return self.step_preview(token, inst, messages=msgs)

    # ------------------------------------------------------------------ 4. preview
    def step_preview(self, token: str, inst: Optional[Instance], messages=(), problem: str = "") -> str:
        e = escape
        mine = (f'<button class="big primary" type="submit" name="source" value="file">Show it with my file</button>'
                if inst else "")
        body = (f'<form method="post" action="/setup/preview">{self._hidden(token, inst)}'
                '<p class="hint">This builds the short report and shows it on screen. Nothing is emailed, saved as '
                'today\'s report, or changed in R365. A place under "Could not tell" means the file did not give a '
                'clear answer for it; the program never guesses.</p>'
                '<div class="stick">' + mine +
                '<button class="big' + ("" if inst else " primary") + '" type="submit" name="source" value="demo">'
                'Show the demo (made-up places)</button>' + self._back(token, 3, inst) + '</div></form>')
        return self._page(token, 3, "Take a look",
                          "Press the blue button to see your report." if inst else "Press the button to see the demo.",
                          body, messages, problem, inst)

    def run_preview(self, token: str, inst: Optional[Instance], f: Dict[str, str]) -> str:
        from .runner import run_report
        source = f.get("source", "demo")
        if source not in ("demo", "file") or (source == "file" and inst is None):
            raise ConfigError("Choose 'Show the demo' or 'Show it with my file'.")
        root = paths.app_dir() / "setup-preview"
        if source == "demo":
            result = run_report("demo", root / "demo")
            lead = "This is the demo: made-up places and made-up numbers."
        else:
            day = date.today() - timedelta(days=1)
            result = run_report("r365", root / "file", end=day, only_instance=inst.id)
            lead = (f"This is your file, read for {day.isoformat()} (yesterday), the same way the morning run reads it.")
        html = result.html_path.read_text(encoding="utf-8")
        e = escape
        q = f"?t={e(token)}" + (f"&amp;inst={e(inst.id)}" if inst else "")
        other = ""
        if inst:
            other_val, other_word = ("demo", "Show the demo instead") if source == "file" else ("file", "Show my file instead")
            other = (f'<form method="post" action="/setup/preview" style="display:inline">{self._hidden(token, inst)}'
                     f'<button class="big" type="submit" name="source" value="{other_val}">{other_word}</button></form>')
        notes = "".join(f'<p class="hint">{e(n)}</p>' for n in result.notes)
        if inst:
            bar = ('<section class="viewbar"><p class="viewlead">Step 4 of 5: look it over. Nothing has been emailed.</p>'
                   f'<p class="next"><strong>Your next step:</strong> If it looks right, press the blue button. {e(lead)}</p>'
                   f'{notes}<a class="btn primary" href="/setup/done{q}">It looks right: finish</a>{other}'
                   f' <a class="btn" href="/setup/schedule{q}">Back</a></section>')
        else:
            bar = ('<section class="viewbar"><p class="viewlead">This is a demo. Nothing has been emailed.</p>'
                   f'<p class="next"><strong>Your next step:</strong> Press the blue button to set up your own R365. {e(lead)}</p>'
                   f'{notes}<a class="btn primary" href="/setup/connection?t={e(token)}">Now set up my own R365</a></section>')
        css = WIZ_CSS + ".viewbar{border:2px solid var(--line);border-radius:10px;padding:12px 16px;margin:0 0 20px;background:var(--card)}.viewbar .viewlead{font-weight:700;margin:0 0 8px}.viewbar .next{border:2px solid #0b5cad}"
        css += ".viewbar .btn.primary{background:#0b5cad;color:#fff;border-color:#0b5cad}.viewbar .btn,.viewbar button.big{color:#0b5cad;border-color:#0b5cad;background:#fff}"
        return html.replace("<main>", "<main>" + bar, 1).replace("</style>", css + "</style>", 1)

    # ------------------------------------------------------------------ 5. done, and undo
    def step_done(self, token: str, inst: Instance) -> str:
        e = escape
        s = load_settings()
        shown = "all"
        try:
            names = self._found_locations(inst)
            shown = f"{len(names) - len(inst.hidden)} of {len(names)} found"
        except DssError:
            pass
        reads = inst.source_path or "the file you chose (a copy is kept in the program's folder)"
        if s.schedule_enabled:
            when = f"every {day_words(s.schedule_weekdays)} at {s.schedule_time}"
        else:
            when = "only when you ask for it"
        facts = [("Name", inst.name), ("R365 address starts with", inst.subdomain or "not given"),
                 ("Reads", reads), ("Layout", LAYOUT_WORDS.get(inst.layout, "not told")),
                 ("Locations in the report", shown + (f" ({len(inst.hidden)} hidden)" if inst.hidden else "")),
                 ("Report is built", when),
                 ("Email", f"a draft for {s.email_to}" if s.email_enabled else "off")]
        table = '<table class="facts">' + "".join(
            f'<tr><th scope="row">{e(a)}:</th><td>{e(b)}</td></tr>' for a, b in facts) + '</table>'
        nxt = []
        if s.schedule_enabled:
            nxt.append(f"{when.capitalize()}, this computer builds the short report from the newest list file it finds"
                       f"{' in ' + inst.source_path if inst.source_path else ''}. The computer must be on; if it was off, "
                       "the report is built when it next starts and marked late.")
            if sys.platform != "win32":
                nxt.append("This computer is not Windows, so the automatic run was saved but NOT set up here (it uses "
                           "Windows Task Scheduler). Nothing will run by itself on this computer.")
        else:
            nxt.append("Nothing runs by itself. To get the report, use the Run now shortcut, or open Settings and use "
                       "'Check DSS export now'.")
        if inst.source_path:
            nxt.append("Before then, download a fresh Daily Sales Summary list from R365 into that location. If there is "
                       "no new file, the report says the file is old and shows approval as 'Could not tell'.")
        else:
            nxt.append("You chose a file here, so it is a one-time copy. Choose a fresh file each morning in Settings, or "
                       "go back to step 1 and type a folder so the newest list is found for you.")
        nxt.append("An email draft is prepared each time. Sign in to Microsoft 365 in Settings (section 6) first, or the email "
                   "step will tell you it could not be made. Nothing is sent without you." if s.email_enabled
                   else "No email is sent or prepared.")
        nxt.append("The program only reads. Nothing is approved or changed in R365.")
        undo = ("<ul><li>Press the button below to undo everything this guide did: the connection and its saved copy are "
                "removed and the schedule and email go back to how they were. Your downloaded file is never touched.</li>"
                f'<li>Or change single things in <a href="/?t={e(token)}">Settings</a>: untick "Use this connection", '
                'tick "Remove this connection", or untick "Run the report automatically".</li></ul>')
        body = (table + '<h2>What happens next</h2><ul>' + "".join(f"<li>{e(x)}</li>" for x in nxt) + '</ul>'
                '<h2>How to undo it</h2>' + undo +
                f'<div class="stick"><a class="btn primary" href="/?t={e(token)}">Finish: open Settings</a> '
                f'<a class="btn" href="/setup/undo?t={e(token)}&amp;inst={e(inst.id)}">Undo this setup</a>'
                f'{self._back(token, 4, inst)}</div>')
        return self._page(token, 4, "You are all set",
                          "Nothing else is needed. You can close this tab.", body, (), "", inst)

    def step_undo_confirm(self, token: str, inst: Instance) -> str:
        e = escape
        body = (f'<form method="post" action="/setup/undo">{self._hidden(token, inst)}'
                f'<p>This removes the connection <strong>{e(inst.name)}</strong> and the copy of the list the program kept, '
                'and puts the schedule and email back how they were before this guide. Your own downloaded file and R365 '
                'are not touched.</p>'
                '<div class="stick"><button class="big primary" type="submit">Yes, undo it</button>'
                f'<a class="btn" href="/setup/done?t={e(token)}&amp;inst={e(inst.id)}">No, keep it</a></div></form>')
        return self._page(token, 4, "Undo the setup?", "Press 'Yes, undo it', or 'No, keep it'.", body, (), "", inst)

    def undo(self, token: str, inst: Instance) -> str:
        s = load_settings()
        st = load_state()
        before = st.get("setup_undo", {}).get(inst.id)
        s.instances = [i for i in s.instances if i.id != inst.id]
        old = (s.schedule_enabled, s.schedule_time, list(s.schedule_weekdays))
        if before:
            for k, v in before.items():
                setattr(s, k, v)
        save_settings(s)
        d = ds.export_dir(inst.id)
        if d.parent == paths.app_dir() / "exports":
            shutil.rmtree(d, ignore_errors=True)
        st.get("setup_undo", {}).pop(inst.id, None)
        st.get("seen_by_instance", {}).pop(inst.id, None)
        save_state(st)
        msgs = [f"Undone. '{inst.name}' and its saved copy were removed."]
        if (s.schedule_enabled, s.schedule_time, s.schedule_weekdays) != old:
            msgs.append(self.app._apply_schedule(s))
        return self.step_connection(token, {}, messages=msgs)
