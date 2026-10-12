"""The settings screen: a small web page served only to this computer, opened in the user's browser.

Why a local page: it needs nothing installed beyond Python, works on Windows, and is readable on any screen.
Safety: listens on 127.0.0.1 only; every request needs a random token that exists only in the URL this
program opens; the Host header is checked (against DNS-rebinding); passwords are write-only (they are
never put into a page, a file or a log - they go to the operating system's credential store).
"""

import hmac
import secrets
import sys
import threading
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from datetime import date

from . import __release_date__, paths, scheduler
from .config import Config, dump_rules, parse_config
from .credstore import CredentialStore, CredentialStoreError, default_store, redact
from .errors import DssError
from .graph import GraphClient, deliver_email, scopes_for
from .r365 import Mapping
from .runner import load_rules
from .state import load_state, seen_locations
from . import licence as lic
from .settings import Instance, Settings, load_settings, save_settings, unique_id, validate
from .sources import build_source

IDLE_SECONDS = 30 * 60
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

CSS = """
.card{border:2px solid var(--line);border-radius:10px;padding:4px 14px 12px;margin:14px 0;background:var(--bg)}
.card h3{font-size:1.15rem;margin:10px 0 0}
table.facts{border-collapse:collapse;margin:8px 0}
table.facts th{text-align:left;padding:4px 14px 4px 0;font-weight:600;vertical-align:top}
table.facts td{padding:4px 0}
:root{--bg:#fff;--fg:#1b1f23;--muted:#4a5560;--line:#c9d1d9;--card:#f4f6f8;--accent:#0b5cad;
--ok:#14532d;--okbg:#e7f6ec;--bad:#8a1c1c;--badbg:#fdecec}
@media (prefers-color-scheme:dark){:root{--bg:#14181c;--fg:#eef1f4;--muted:#b3bdc7;--line:#3a444e;
--card:#1e242a;--accent:#7db8f5;--ok:#9fe3b6;--okbg:#14301e;--bad:#ffb4b4;--badbg:#3b1b1b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:19px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:1.5rem;margin:0 0 4px}
.lead{color:var(--muted);margin:0 0 16px}
fieldset{border:2px solid var(--line);border-radius:10px;margin:0 0 20px;padding:12px 16px 16px;background:var(--card)}
legend{font-weight:700;font-size:1.2rem;padding:0 8px}
.row{margin:14px 0}
label{font-weight:600;display:block}
.check{display:flex;gap:12px;align-items:flex-start;font-weight:600}
.check input{width:28px;height:28px;flex:none;margin-top:2px}
input[type=text],input[type=password],input[type=number],input[type=time],textarea{width:100%;font:inherit;
padding:10px;border:2px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
textarea{min-height:5.5em}
.hint{color:var(--muted);font-size:1rem;margin:2px 0 0}
.days{display:flex;flex-wrap:wrap;gap:8px 18px}
.days label{display:flex;gap:8px;align-items:center;font-weight:600}
.days input{width:24px;height:24px}
button{font:inherit;font-weight:700;padding:12px 18px;border-radius:8px;border:2px solid var(--accent);
background:var(--bg);color:var(--accent);cursor:pointer;margin:6px 8px 0 0}
button.primary{background:var(--accent);color:var(--bg)}
.msg{border-radius:8px;padding:12px 14px;margin:0 0 16px;font-weight:600}
.msg.ok{background:var(--okbg);color:var(--ok);border:2px solid var(--ok)}
.msg.bad{background:var(--badbg);color:var(--bad);border:2px solid var(--bad)}
.code{font-size:1.6rem;font-weight:800;letter-spacing:.08em}
.state{font-weight:700}
"""


VIEW_CSS = """
.viewbar{border:2px solid var(--line);border-radius:10px;padding:12px 16px;margin:0 0 20px;background:var(--card)}
.viewlead{font-weight:700;margin:0 0 8px}
.viewbar .msg{border-radius:8px;padding:12px 14px;margin:8px 0;font-weight:600;border:2px solid var(--line)}
.viewbar .msg.ok{background:#e7f6ec;color:#14532d;border-color:#14532d}
.viewbar .msg.bad{background:#fdecec;color:#8a1c1c;border-color:#8a1c1c}
.viewbar button,.viewbar .btn{font:inherit;font-weight:700;padding:12px 18px;border-radius:8px;border:2px solid #0b5cad;
background:var(--bg);color:#0b5cad;cursor:pointer;margin:6px 8px 0 0;display:inline-block;text-decoration:none}
.viewbar button.primary{background:#0b5cad;color:#fff}
.viewbar .hint{color:var(--muted);font-size:1rem;margin:8px 0 0}
"""


def mailto_link(to: str, subject: str, body: str, limit: int = 1800) -> str:
    """A link that opens the phone's (or computer's) own mail app with the text filled in.
    Mail apps limit link length, so a long body is cut at a line break with a pointer to the screen."""
    more = "\n\n(Shortened. See the full report on screen.)"
    lines = body.splitlines()
    for cut in range(len(lines), 0, -1):
        text = "\n".join(lines[:cut]) + ("" if cut == len(lines) else more)
        link = f"mailto:{quote(to, safe='@')}?subject={quote(subject, safe='')}&body={quote(text, safe='')}"
        if len(link) <= limit:
            return link
    return f"mailto:{quote(to, safe='@')}?subject={quote(subject, safe='')}"


def _checkbox(name, checked, label, hint):
    return (f'<div class="row"><label class="check"><input type="checkbox" name="{name}" value="1"'
            f'{" checked" if checked else ""}><span>{escape(label)}'
            f'<span class="hint" style="display:block;font-weight:400">{escape(hint)}</span></span></label></div>')


def _field(name, value, label, hint, kind="text", extra="", placeholder=""):
    ph = f' placeholder="{escape(placeholder)}"' if placeholder else ""
    return (f'<div class="row"><label for="{name}">{escape(label)}</label>'
            f'<input type="{kind}" id="{name}" name="{name}" value="{escape(str(value))}"{ph} {extra}>'
            f'<p class="hint">{escape(hint)}</p></div>')


def _area(name, items, label, hint):
    return (f'<div class="row"><label for="{name}">{escape(label)}</label>'
            f'<textarea id="{name}" name="{name}">{escape(chr(10).join(items))}</textarea>'
            f'<p class="hint">{escape(hint)}</p></div>')


def _is_windows() -> bool:
    return sys.platform == "win32"


class SettingsApp:
    """The state and actions behind the page. Kept apart from HTTP so it is easy to test."""

    def __init__(self, store: Optional[CredentialStore] = None, rules_path=None,
                 graph_factory: Optional[Callable[[CredentialStore], GraphClient]] = None):
        self._store = store
        self.rules_path = paths.resolve_rules_path(rules_path)
        self.graph_factory = graph_factory or (lambda st: GraphClient(st))
        self.device = None

    @property
    def store(self) -> CredentialStore:
        if self._store is None:
            self._store = default_store()
        return self._store

    # ---------------- reading and saving
    def current(self):
        cfg = load_rules(self.rules_path) if self.rules_path.exists() else Config()
        return load_settings(), cfg

    def apply_form(self, f: dict) -> list:
        """Save everything on the page. Returns plain-words messages. Raises DssError if invalid."""
        old_settings, cfg = self.current()
        g = lambda k, d="": f.get(k, [d])[0].strip()
        on = lambda k: k in f

        def number(key, label):
            try:
                return float(g(key).replace(",", "").replace("$", ""))
            except ValueError:
                raise DssError(f"{label} must be a number.")

        def whole(key, label):
            try:
                v = int(g(key))
            except ValueError:
                raise DssError(f"{label} must be a whole number.")
            return v

        status = lic.current_status()
        raw_rules = {
            "locations": {"include": cfg.include, "ignore": cfg.ignore, "expected": cfg.expected},
            "rules": {
                "missing_pos_import": {"enabled": on("rule_pos")},
                "cash_variance": {"enabled": on("rule_cash"), "limit": number("cash_limit", "The cash limit")},
                "missing_receipts": {"enabled": on("rule_receipts"),
                                     "allowed": whole("receipts_allowed", "Missing receipts allowed")},
                "payment_exceptions": {"enabled": on("rule_exceptions"),
                                       "allowed": whole("exceptions_allowed", "Payment exceptions allowed")},
                "unapproved_entry": {"enabled": on("rule_unapproved")},
                "payments_total": {"enabled": on("rule_payments"),
                                   "tolerance": number("payments_tolerance", "The payments tolerance")},
            },
            "report": {"title": cfg.title},
            "ai": {"enabled": on("ai_enabled"), "endpoint": g("ai_endpoint", cfg.ai_endpoint),
                   "model": g("ai_model", cfg.ai_model), "timeout_seconds": cfg.ai_timeout},
        }
        new_cfg = parse_config(raw_rules)   # validates (raises ConfigError, a DssError)
        # switching a licensed feature ON needs the licence to include it (switching off is always allowed)
        if new_cfg.payments_enabled and not cfg.payments_enabled:
            status.require(lic.F_OPTIONAL_RULES)
        if new_cfg.ai_enabled and not cfg.ai_enabled:
            status.require(lic.F_LOCAL_AI)

        msgs = []
        instances, secrets_to_write, secrets_to_delete = self._read_instances(f, old_settings, status, msgs)
        days = sorted(int(k[2:]) for k in f if k.startswith("wd") and k[2:].isdigit())
        s = Settings(
            instances=instances,
            email_enabled=on("email_enabled"), email_to=g("email_to"), email_send_auto=on("email_send_auto"),
            graph_client_id=g("graph_client_id"), graph_tenant=g("graph_tenant", "organizations") or "organizations",
            schedule_enabled=on("schedule_enabled"), schedule_time=g("schedule_time", "07:00"),
            schedule_weekdays=days, schedule_late_after_minutes=old_settings.schedule_late_after_minutes)
        validate(s)
        if s.email_enabled and not old_settings.email_enabled:
            status.require(lic.F_EMAIL)
        if s.schedule_enabled and not old_settings.schedule_enabled:
            status.require(lic.F_SCHEDULE)

        for key, secret in secrets_to_write:
            try:
                self.store.set(key, secret)
            except CredentialStoreError as exc:
                raise DssError(str(exc))
        for key in secrets_to_delete:
            self.store.delete(key)

        self.rules_path.parent.mkdir(parents=True, exist_ok=True)
        self.rules_path.write_text(dump_rules(new_cfg), encoding="utf-8")
        save_settings(s)
        msgs.insert(0, "Settings saved.")

        if (s.schedule_enabled, s.schedule_time, s.schedule_weekdays) != (
                old_settings.schedule_enabled, old_settings.schedule_time, old_settings.schedule_weekdays) \
                or on("schedule_apply"):
            msgs.append(self._apply_schedule(s))
        return msgs

    def _read_instances(self, f: dict, old: Settings, status: "lic.LicenceStatus", msgs: list):
        """Turn the connection boxes on the page into Instance objects, enforcing the licence."""
        g = lambda k, d="": f.get(k, [d])[0].strip()
        on = lambda k: k in f
        result, writes, deletes = [], [], []
        idxs = sorted(int(k[8:]) for k in f if k.startswith("inst_id_") and k[8:].isdigit())
        kept_enabled = 0
        newly_enabled = []
        for i in idxs:
            old_inst = old.instance(g(f"inst_id_{i}"))
            if old_inst is None:
                continue
            if on(f"inst_remove_{i}"):
                deletes.append(old_inst.credential_key)
                msgs.append(f"Connection '{old_inst.name}' removed and its saved password forgotten. "
                            "Its mapping file was left in place.")
                continue
            hidden = []
            for key, vals in f.items():
                if key.startswith(f"locname_{i}_") and f"loc_{i}_{key.split('_')[-1]}" not in f and vals[0].strip():
                    hidden.append(vals[0].strip())
            inst = Instance(
                id=old_inst.id, name=g(f"inst_name_{i}"), base_url=g(f"inst_url_{i}"), username=g(f"inst_user_{i}"),
                enabled=on(f"inst_enabled_{i}"), source_kind=old_inst.source_kind,
                mapping_file=old_inst.mapping_file, credential_key=old_inst.credential_key,
                include=_lines(g(f"inst_include_{i}")), hidden=hidden)
            pw = f.get(f"inst_pw_{i}", [""])[0]
            if pw:
                if not inst.username:
                    raise DssError(f"Fill in the user name for '{inst.name}' before saving its password.")
                writes.append((inst.credential_key, pw))
                msgs.append(f"Password for '{inst.name}' saved in this computer's secure store.")
            if on(f"inst_forget_{i}"):
                deletes.append(inst.credential_key)
                msgs.append(f"Saved password for '{inst.name}' removed.")
            if inst.enabled:
                if old_inst.enabled:
                    kept_enabled += 1
                else:
                    newly_enabled.append(inst)
            result.append(inst)
        # a connection that was not enabled before may only be switched on if the licence has room
        for inst in newly_enabled:
            reason = status.can_add_connection(kept_enabled)
            if reason:
                raise DssError(reason)
            kept_enabled += 1
        new_name = g("new_name")
        if new_name or g("new_url") or g("new_user"):
            if not new_name:
                raise DssError("Give the new connection a name.")
            reason = status.can_add_connection(kept_enabled)
            if reason:
                raise DssError(reason)
            inst = Instance(id=unique_id(new_name, {r.id for r in old.instances} | {r.id for r in result}),
                            name=new_name, base_url=g("new_url"), username=g("new_user"), enabled=True)
            pw = f.get("new_pw", [""])[0]
            if pw:
                writes.append((inst.credential_key, pw))
            result.append(inst)
            msgs.append(f"Connection '{new_name}' added. Fill in its field mapping file (shown below) to "
                        "turn \"needs mapping\" checks on.")
        return result, writes, deletes

    def load_licence(self, raw: bytes) -> str:
        """Check a licence file and, only if its signature is genuine, keep it."""
        try:
            status = lic.install_licence(raw)
        except lic.LicenceError as exc:
            raise DssError(f"That licence file was not loaded. {exc}")
        return f"Licence file loaded. {status.message}"

    def _apply_schedule(self, s: Settings) -> str:
        if not _is_windows():
            return ("Schedule saved, but automatic running is set up through Windows Task Scheduler, "
                    "which is not available on this computer.")
        try:
            return scheduler.install_task(s) if s.schedule_enabled else scheduler.remove_task()
        except DssError as exc:
            return f"The schedule could not be set up: {exc}"

    # ---------------- buttons
    def action(self, name: str) -> list:
        s, _ = self.current()
        if name.startswith("test_r365:"):
            inst = s.instance(name.split(":", 1)[1])
            if inst is None:
                raise DssError("That connection no longer exists.")
            status = lic.current_status()
            if status.instances_allowed == 0:
                raise DssError(status.message)
            return [f"{inst.name}: {build_source(inst, self.store).check_connection()}"]
        if name == "m365_start":
            g = self.graph_factory(self.store)
            self.device = g.start_signin(s.graph_client_id, s.graph_tenant, scopes_for(s))
            return [f"Go to {self.device.verification_uri} and enter the code shown below, "
                    "then come back here and press 'I have signed in'."]
        if name == "m365_finish":
            if not self.device:
                raise DssError("Start the sign-in first.")
            state = self.graph_factory(self.store).finish_signin(s.graph_client_id, s.graph_tenant, self.device)
            if state == "pending":
                return ["Microsoft is still waiting for you to finish signing in. Finish it in the other tab, then press again."]
            self.device = None
            return ["Signed in to Microsoft 365. No password was stored."]
        if name == "m365_signout":
            self.graph_factory(self.store).sign_out()
            self.device = None
            return ["Signed out of Microsoft 365 on this computer."]
        return []

    # ---------------- view the report, then choose whether to email it
    def view_dir(self, folder: Optional[str] = None) -> Path:
        if folder:
            # only a folder that really is one of the saved reports; never an arbitrary path
            if folder in self.report_folders():
                return paths.reports_dir() / folder
            raise DssError("That saved report was not found.")
        d = load_state().get("last_report_dir")
        return Path(d) if d else paths.reports_dir()

    def report_folders(self) -> list:
        root = paths.reports_dir()
        try:
            return sorted((p.name for p in root.iterdir() if p.is_dir() and (p / "report.html").exists()), reverse=True)
        except OSError:
            return []

    def _saved_report(self, folder: Optional[str] = None):
        d = self.view_dir(folder)
        try:
            return (d / "report.html").read_text(encoding="utf-8"), (d / "email.txt").read_text(encoding="utf-8")
        except OSError:
            return None

    def email_report(self, folder: Optional[str] = None) -> str:
        """Create the email in Microsoft 365 for the report on screen (a draft unless 'send automatically' is on)."""
        saved = self._saved_report(folder)
        if not saved:
            raise DssError("There is no report to email yet. Press 'Run now' first.")
        html, text = saved
        lic.current_status().require(lic.F_EMAIL)
        s = load_settings()
        if not s.email_to:
            raise DssError("Fill in who the email should go to (Email section of settings) first.")
        subject = text.splitlines()[0].removeprefix("Subject: ")
        body = "\n".join(text.splitlines()[2:])
        return deliver_email(subject, body, html, s, self.store, self.graph_factory(self.store))

    def render_view(self, token: str, messages=(), problem: str = "", folder: Optional[str] = None) -> str:
        e = escape
        try:
            saved = self._saved_report(folder)
        except DssError as exc:
            saved, problem = None, str(exc)
        s = load_settings()
        tools = ['<section class="viewbar"><p class="viewlead">Look it over first. Nothing has been emailed.</p>']
        for m in messages:
            tools.append(f'<p class="msg ok">{e(m)}</p>')
        if problem:
            tools.append(f'<p class="msg bad">{e(problem)}</p>')
        if saved:
            html, text = saved
            subject = text.splitlines()[0].removeprefix("Subject: ")
            body = "\n".join(text.splitlines()[2:])
            label = ("Send it now through Microsoft 365" if s.email_send_auto
                     else "Create an email draft in Microsoft 365")
            tools.append(f'<form method="post" action="/email"><input type="hidden" name="t" value="{e(token)}">'
                         f'<input type="hidden" name="d" value="{e(folder or "")}">'
                         f'<button class="primary" type="submit">{e(label)}</button>'
                         f' <a class="btn" href="{e(mailto_link(s.email_to, subject, body))}">Open in my mail app</a>'
                         ' <a class="btn" href="/?t=' + e(token) + '">Settings</a></form>')
            older = [f for f in self.report_folders() if f != (folder or Path(load_state().get("last_report_dir", "")).name)]
            if older:
                tools.append('<p class="hint">Earlier reports (always kept, whatever your licence says): ' + " ".join(
                    f'<a href="/report?t={e(token)}&amp;d={e(f)}">{e(f)}</a>' for f in older[:30]) + '</p>')
            tools.append('<p class="hint">Microsoft 365 puts the report page on the email as an attachment. '
                         'A phone\'s mail app opens a new message with the text (it cannot attach the page).</p></section>')
            return html.replace("<main>", "<main>" + "".join(tools), 1).replace("</style>", VIEW_CSS + "</style>", 1)
        tools.append('<h1>No report yet</h1><p>Press the "Run now" shortcut to make one.</p></section>')
        return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<title>View the report</title><style>{CSS}{VIEW_CSS}</style></head><body><main>'
                + "".join(tools) + '</main></body></html>')

    # ---------------- licence and connections sections
    def _licence_html(self, status, s: Settings, token: str) -> list:
        e = escape
        used = len(s.enabled_instances)
        out = ['<fieldset><legend>1. Licence</legend>',
               f'<p class="state">{e(status.message)}</p>']
        if status.notice:
            out.append(f'<p class="msg bad">{e(status.notice)}</p>')
        rows = []
        if status.licence:
            L = status.licence
            rows = [("Customer", L.customer),
                    ("Connections", status.connections_text(used)),
                    ("Licence ends", L.expires.isoformat()), ("Updates until", L.updates_until.isoformat()),
                    ("This version", f"released {__release_date__}, " + (
                        "inside your updates period" if status.updates_covered(date.fromisoformat(__release_date__))
                        else "newer than your updates period (it still runs; ask about renewing)")),
                    ("Includes", ", ".join(lic.FEATURE_WORDS[f] for f in lic.ALL_FEATURES if f in L.features) or "Nothing extra")]
        else:
            rows = [("Connections", f"{used} set up, {status.instances_allowed} allowed")]
        out.append('<table class="facts">' + "".join(
            f'<tr><th scope="row">{e(a)}</th><td>{e(b)}</td></tr>' for a, b in rows) + '</table>')
        out.append('<p class="hint">Demo data always works without a licence. A licence that has run out or is missing '
                   'never hides or deletes a report you already have; it only stops new connections and extras.</p>')
        out.append(f'<form method="post" action="/licence" enctype="multipart/form-data">'
                   f'<input type="hidden" name="t" value="{e(token)}">'
                   '<div class="row"><label for="licence_file">Licence file</label>'
                   '<input type="file" id="licence_file" name="licence" accept=".json,application/json">'
                   '<p class="hint">Choose the licence file you were sent. It is checked right here on this computer; '
                   'nothing is sent anywhere.</p></div>'
                   '<button type="submit">Load licence file</button></form></fieldset>')
        return out

    def _connections_html(self, s: Settings, status) -> list:
        e = escape
        out = ['<fieldset><legend>2. Restaurant365 connections</legend>']
        if not s.instances:
            out.append('<p class="hint">No connection yet. Add one below.</p>')
        state = load_state()
        for i, inst in enumerate(s.instances):
            try:
                pw_saved = bool(self.store.get(inst.credential_key))
            except DssError:
                pw_saved = False
            try:
                unmapped = Mapping.load(inst.mapping_path).unmapped()
                mapped = ("Field mapping: complete." if not unmapped else
                          f"Field mapping: {len(unmapped)} item(s) not filled in, so those checks show \"needs mapping\".")
            except DssError as exc:
                mapped = f"Field mapping problem: {exc}"
            out.append(f'<div class="card"><input type="hidden" name="inst_id_{i}" value="{e(inst.id)}">'
                       f'<h3>{e(inst.name)}</h3>')
            out.append(_checkbox(f"inst_enabled_{i}", inst.enabled, "Connect to this Restaurant365",
                                 "Reads its daily sales summaries, read-only. Nothing is ever changed in R365."))
            out.append(_field(f"inst_name_{i}", inst.name, "Name", "How this connection is called in the report."))
            out.append(_field(f"inst_url_{i}", inst.base_url, "R365 address",
                              "The OData address your R365 contact gave you. It must start with https://.",
                              placeholder="https://your-address-from-R365"))
            out.append(_field(f"inst_user_{i}", inst.username, "User name",
                              "The way R365 writes it: Domain\\Username.", placeholder="DOMAIN\\username"))
            out.append(f'<div class="row"><label for="inst_pw_{i}">Password</label>'
                       f'<input type="password" id="inst_pw_{i}" name="inst_pw_{i}" autocomplete="new-password">'
                       '<p class="hint">Kept only in this computer\'s secure store, never in a file. '
                       f'<span class="state">{"A password is saved." if pw_saved else "No password saved yet."}</span> '
                       'Leave blank to keep the saved one.</p></div>')
            out.append(_checkbox(f"inst_forget_{i}", False, "Forget the saved password", "Tick and Save to remove it from this computer."))
            out.append(f'<button type="submit" name="action" value="test_r365:{e(inst.id)}">Save and test this connection</button>')
            out.append(f'<p class="hint">Field mapping file (private, on this computer, never committed): '
                       f'{e(str(inst.mapping_path))}. <span class="state">{e(mapped)}</span></p>')
            out.append(_area(f"inst_include_{i}", inst.include, "Only these locations (optional)",
                             "One per line, spelled as in R365. A listed location that sends nothing is shown as UNKNOWN. "
                             "A location that is not listed and sends no rows at all is not shown."))
            shown = sorted(set(seen_locations(state, inst.id)) | set(inst.hidden), key=str.lower)
            if shown:
                out.append('<div class="row"><label>Show or hide a location</label>')
                for j, name in enumerate(shown):
                    out.append(f'<label class="check"><input type="hidden" name="locname_{i}_{j}" value="{e(name)}">'
                               f'<input type="checkbox" name="loc_{i}_{j}" value="1"{"" if name in inst.hidden else " checked"}>'
                               f'<span>{e(name)}</span></label>')
                out.append('<p class="hint">Untick a location to leave it out of the report, for example one that has closed. '
                           'This list fills in after the first report that reads rows from this connection.</p></div>')
            else:
                out.append('<p class="hint">After the first report, each location this connection sends appears here '
                           'with a Show/Hide tick.</p>')
            out.append(_checkbox(f"inst_remove_{i}", False, "Remove this connection",
                                 "Tick and Save. Its saved password is forgotten; its mapping file is left alone."))
            out.append('</div>')
        out.append('<div class="card"><h3>Add a connection</h3>')
        reason = status.can_add_connection(len(s.enabled_instances))
        out.append(f'<p class="hint">{e(reason) if reason else "Fill these in and press Save settings."}</p>')
        out.append(_field("new_name", "", "Name", "For example the name of the restaurant group this R365 belongs to.", placeholder="a name for this connection"))
        out.append(_field("new_url", "", "R365 address", "It must start with https://.", placeholder="https://your-address-from-R365"))
        out.append(_field("new_user", "", "User name", "The way R365 writes it: Domain\\Username.", placeholder="DOMAIN\\username"))
        out.append('<div class="row"><label for="new_pw">Password</label><input type="password" id="new_pw" name="new_pw" autocomplete="new-password">'
                   '<p class="hint">Kept only in this computer\'s secure store.</p></div></div>')
        out.append('</fieldset>')
        return out

    # ---------------- page
    def render(self, token: str, messages=(), problem: str = "") -> str:
        s, c = self.current()
        status = lic.current_status()
        store_note = ""
        try:
            g = self.graph_factory(self.store)
            m365 = g.signed_in()
            can_send = "Mail.Send" in g.granted_scopes()
        except DssError:
            m365, can_send = False, False
        e = escape
        out = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
               '<meta name="viewport" content="width=device-width, initial-scale=1">',
               f'<title>DSS report settings</title><style>{CSS}</style></head><body><main>',
               '<h1>Morning report settings</h1>',
               '<p class="lead">Tick what you want, then press Save. Nothing leaves this computer except what you switch on below.</p>']
        for m in messages:
            out.append(f'<p class="msg ok">{e(m)}</p>')
        if problem:
            out.append(f'<p class="msg bad">{e(problem)}</p>')
        if store_note:
            out.append(f'<p class="msg bad">{e(store_note)}</p>')
        if status.notice:
            out.append(f'<p class="msg bad">{e(status.notice)}</p>')
        out += self._licence_html(status, s, token)
        out.append(f'<form method="post" action="/"><input type="hidden" name="t" value="{e(token)}">')

        out += self._connections_html(s, status)

        out.append('<fieldset><legend>3. What counts as a problem</legend>')
        out.append(_checkbox("rule_pos", c.pos_enabled, "POS import missing", "Flag a day where the POS import did not arrive."))
        out.append(_checkbox("rule_cash", c.cash_enabled, "Cash over or short",
                             "Flag cash that is over or short by more than the limit below."))
        out.append(_field("cash_limit", f"{c.cash_limit}", "Cash limit ($)", "Either direction. 5 means more than $5 over or short.", "number", 'step="0.01" min="0"'))
        out.append(_checkbox("rule_receipts", c.receipts_enabled, "Missing receipts", "Flag a day with more missing receipts than allowed."))
        out.append(_field("receipts_allowed", c.receipts_allowed, "Missing receipts allowed", "0 means flag any missing receipt.", "number", 'min="0"'))
        out.append(_checkbox("rule_exceptions", c.exceptions_enabled, "Payment exceptions", "Flag a day with more payment exceptions than allowed."))
        out.append(_field("exceptions_allowed", c.exceptions_allowed, "Payment exceptions allowed", "0 means flag any exception.", "number", 'min="0"'))
        out.append(_checkbox("rule_unapproved", c.unapproved_enabled, "Entry not approved",
                             "Flag an entry that has not been approved. With R365 this shows \"needs mapping\" until an approval field is mapped."))
        out.append(_checkbox("rule_payments", c.payments_enabled, "Payments add up to sales (optional)",
                             "Flag a day where the payment types don't add up to the sales total. Needs mapping for R365."))
        out.append(_field("payments_tolerance", f"{c.payments_tolerance}", "Payments tolerance ($)", "How far apart they may be before it is flagged.", "number", 'step="0.01" min="0"'))
        out.append('<p class="hint">A location with no data, or a blank figure, is always shown as UNKNOWN. That cannot be switched off.</p></fieldset>')

        out.append('<fieldset><legend>4. Email</legend>')
        out.append(_checkbox("email_enabled", s.email_enabled, "Prepare an email each time the report runs",
                             "Puts the report in your own Microsoft 365 mailbox as a draft you can read and send."))
        out.append(_field("email_to", s.email_to, "Send the email to",
                          "Your own Microsoft 365 address (or whoever should get it). One address. You type it here; it is never built in.",
                          placeholder="you@your-company.example"))
        out.append(_checkbox("email_send_auto", s.email_send_auto, "Send automatically",
                             "Off by default. When off, you only get a draft to check and send yourself."))
        out.append(_field("graph_client_id", s.graph_client_id, "Microsoft app ID",
                          "The Application (client) ID of the app your Microsoft 365 administrator registered. You paste it here; it is never built in.",
                          placeholder="paste the Application (client) ID"))
        out.append(_field("graph_tenant", s.graph_tenant, "Microsoft tenant", "Leave as 'organizations' unless your administrator gives you a tenant name.", placeholder="organizations"))
        status = ("Signed in" + (" (allowed to send)" if can_send else " (drafts only)")) if m365 else "Not signed in"
        out.append(f'<p class="hint">Microsoft 365 status: <span class="state">{e(status)}</span>. '
                   'You sign in on Microsoft\'s own page; this program never sees or stores your password.</p>')
        out.append('<button type="submit" name="action" value="m365_start">Save and sign in to Microsoft 365</button>'
                   '<button type="submit" name="action" value="m365_finish">I have signed in</button>'
                   '<button type="submit" name="action" value="m365_signout">Sign out</button>')
        if self.device:
            out.append(f'<p>Your code: <span class="code">{e(self.device.user_code)}</span></p>')
        out.append('</fieldset>')

        out.append('<fieldset><legend>5. Schedule</legend>')
        out.append(_checkbox("schedule_enabled", s.schedule_enabled, "Run the report automatically",
                             "Runs it on your computer at the time below and emails it if email is on."))
        out.append(_field("schedule_time", s.schedule_time, "Time of day", "Your computer's clock, 24-hour.", "time"))
        out.append('<div class="row"><label>Days</label><div class="days">'
                   + "".join(f'<label><input type="checkbox" name="wd{i}" value="1"{" checked" if i in s.schedule_weekdays else ""}>{n}</label>'
                             for i, n in enumerate(WEEKDAYS))
                   + '</div><p class="hint">Weekdays by default. If the computer was off, the report runs once when it next starts and is marked late.</p></div>')
        out.append('</fieldset>')

        out.append('<fieldset><legend>6. Plain-language summary (optional)</legend>')
        out.append(_checkbox("ai_enabled", c.ai_enabled, "Add a one-sentence summary from a model on this computer",
                             "Off by default. The report is complete and correct without it; a summary that disagrees with the numbers is thrown away."))
        out.append(_field("ai_endpoint", c.ai_endpoint, "Model address", "Must be on this computer (localhost)."))
        out.append(_field("ai_model", c.ai_model, "Model name", "The name of the model your local server has."))
        out.append('</fieldset>')

        out.append('<button class="primary" type="submit" name="action" value="save">Save settings</button>'
                   '<button type="submit" name="action" value="quit">Save and close</button></form>')
        out.append(f'<p class="hint">Settings file: {e(str(paths.settings_path()))}<br>Rules file: {e(str(self.rules_path))}</p>')
        out.append('</main></body></html>')
        return "\n".join(out)


def _lines(text: str):
    return [ln.strip() for ln in text.replace("\r", "").split("\n") if ln.strip()]


class _Handler(BaseHTTPRequestHandler):
    server: "SettingsServer"

    def log_message(self, *a):
        pass  # never log requests: they could carry a typed password

    def _ok_request(self, token_from) -> bool:
        port = self.server.server_port
        host_ok = self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")
        origin = self.headers.get("Origin")
        origin_ok = origin is None or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
        token_ok = hmac.compare_digest(token_from or "", self.server.token)
        return host_ok and origin_ok and token_ok

    def _send(self, code, html: str):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        t = parse_qs(u.query).get("t", [""])[0]
        if u.path not in ("/", "/report") or not self._ok_request(t):
            return self._send(403, "<p>This page can only be opened from the program.</p>")
        if u.path == "/report":
            d = parse_qs(u.query).get("d", [""])[0] or None
            return self._send(200, self.server.app.render_view(self.server.token, folder=d))
        self._send(200, self.server.app.render(self.server.token))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000:
            return self._send(413, "<p>Too much data.</p>")
        raw = self.rfile.read(n)
        app, messages, problem = self.server.app, [], ""
        if self.path == "/licence":
            fields, files = _parse_multipart(self.headers.get("Content-Type", ""), raw)
            if not self._ok_request(fields.get("t", "")):
                return self._send(403, "<p>This page can only be used from the program.</p>")
            try:
                if not files.get("licence"):
                    raise DssError("Choose a licence file first.")
                messages.append(app.load_licence(files["licence"]))
            except DssError as exc:
                problem = str(exc)
            self.server.touch()
            return self._send(200, app.render(self.server.token, messages, problem))
        form = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
        if self.path not in ("/", "/email") or not self._ok_request(form.get("t", [""])[0]):
            return self._send(403, "<p>This page can only be used from the program.</p>")
        if self.path == "/email":
            try:
                messages.append(app.email_report(form.get("d", [""])[0] or None))
            except DssError as exc:
                problem = str(exc)
            self.server.touch()
            return self._send(200, app.render_view(self.server.token, messages, problem, form.get("d", [""])[0] or None))
        action = form.get("action", ["save"])[0]
        passwords = [v[0] for k, v in form.items() if (k.startswith("inst_pw_") or k == "new_pw") and v and v[0]]
        try:
            messages += app.apply_form(form)
            if action not in ("save", "quit"):
                messages += app.action(action)
        except DssError as exc:
            problem = redact(str(exc), *passwords)
        self.server.touch()
        if action == "quit" and not problem:
            self._send(200, "<!DOCTYPE html><meta charset=utf-8><p style='font:19px system-ui;padding:20px'>"
                            "Settings saved. You can close this tab.</p>")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._send(200, app.render(self.server.token, messages, problem))


def _parse_multipart(content_type: str, body: bytes):
    """Read a small multipart/form-data body (the licence upload). Returns (fields, files)."""
    from email.parser import BytesParser
    from email.policy import default
    fields, files = {}, {}
    if "multipart/form-data" not in content_type:
        return fields, files
    msg = BytesParser(policy=default).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    for part in msg.iter_parts() if msg.is_multipart() else []:
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            files[name] = payload
        else:
            fields[name] = payload.decode("utf-8", "replace")
    return fields, files


class SettingsServer(HTTPServer):
    def __init__(self, app: SettingsApp, port: int = 0):
        super().__init__(("127.0.0.1", port), _Handler)
        self.app = app
        self.token = secrets.token_urlsafe(24)
        self._timer = None
        self.touch()

    def touch(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(IDLE_SECONDS, lambda: threading.Thread(target=self.shutdown, daemon=True).start())
        self._timer.daemon = True
        self._timer.start()

    def url_for(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.server_port}{path}?t={self.token}"

    @property
    def url(self) -> str:
        return self.url_for("/")


def serve(open_browser: bool = True, app: Optional[SettingsApp] = None, path: str = "/") -> int:
    server = SettingsServer(app or SettingsApp())
    url = server.url_for(path)
    print(f"This is open in your browser. If not, open: {url}")
    print("Close this window or press Ctrl+C when you are done.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
