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
from urllib.parse import parse_qs, urlparse

from . import paths, scheduler
from .config import Config, dump_rules, parse_config
from .credstore import CredentialStore, CredentialStoreError, default_store, redact
from .errors import DssError
from .graph import GraphClient, scopes_for
from .r365 import check_connection, credential_name
from .runner import load_rules
from .settings import Settings, load_settings, save_settings, validate

IDLE_SECONDS = 30 * 60
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

CSS = """
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


def _checkbox(name, checked, label, hint):
    return (f'<div class="row"><label class="check"><input type="checkbox" name="{name}" value="1"'
            f'{" checked" if checked else ""}><span>{escape(label)}'
            f'<span class="hint" style="display:block;font-weight:400">{escape(hint)}</span></span></label></div>')


def _field(name, value, label, hint, kind="text", extra=""):
    return (f'<div class="row"><label for="{name}">{escape(label)}</label>'
            f'<input type="{kind}" id="{name}" name="{name}" value="{escape(str(value))}" {extra}>'
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

        raw_rules = {
            "locations": {"include": _lines(g("locations_include")), "ignore": _lines(g("locations_ignore")),
                          "expected": cfg.expected},
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

        days = sorted(int(k[2:]) for k in f if k.startswith("wd") and k[2:].isdigit())
        s = Settings(
            r365_enabled=on("r365_enabled"), r365_base_url=g("r365_base_url"), r365_username=g("r365_username"),
            email_enabled=on("email_enabled"), email_to=g("email_to"), email_send_auto=on("email_send_auto"),
            graph_client_id=g("graph_client_id"), graph_tenant=g("graph_tenant", "organizations") or "organizations",
            schedule_enabled=on("schedule_enabled"), schedule_time=g("schedule_time", "07:00"),
            schedule_weekdays=days, schedule_late_after_minutes=old_settings.schedule_late_after_minutes)
        validate(s)

        msgs = []
        password = f.get("r365_password", [""])[0]
        if password and s.r365_username:
            try:
                self.store.set(credential_name(s.r365_username), password)
                msgs.append("R365 password saved in this computer's secure store.")
            except CredentialStoreError as exc:
                raise DssError(str(exc))
        elif password:
            raise DssError("Fill in the R365 user name before saving a password.")
        if on("r365_forget") and s.r365_username:
            self.store.delete(credential_name(s.r365_username))
            msgs.append("Saved R365 password removed.")

        self.rules_path.parent.mkdir(parents=True, exist_ok=True)
        self.rules_path.write_text(dump_rules(new_cfg), encoding="utf-8")
        save_settings(s)
        msgs.insert(0, "Settings saved.")

        if (s.schedule_enabled, s.schedule_time, s.schedule_weekdays) != (
                old_settings.schedule_enabled, old_settings.schedule_time, old_settings.schedule_weekdays) \
                or on("schedule_apply"):
            msgs.append(self._apply_schedule(s))
        return msgs

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
        if name == "test_r365":
            return [check_connection(s, self.store)]
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

    # ---------------- page
    def render(self, token: str, messages=(), problem: str = "") -> str:
        s, c = self.current()
        try:
            pw_saved = bool(s.r365_username and self.store.get(credential_name(s.r365_username)))
            store_note = ""
        except DssError as exc:
            pw_saved, store_note = False, str(exc)
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
        out.append(f'<form method="post" action="/"><input type="hidden" name="t" value="{e(token)}">')

        out.append('<fieldset><legend>1. Restaurant365</legend>')
        out.append(_checkbox("r365_enabled", s.r365_enabled, "Connect to Restaurant365",
                             "Reads your daily sales summaries, read-only. Nothing is ever changed in R365."))
        out.append(_field("r365_base_url", s.r365_base_url, "R365 address",
                          "The OData address your R365 contact gave you. It must start with https://."))
        out.append(_field("r365_username", s.r365_username, "User name",
                          "The way R365 writes it: Domain\\Username."))
        out.append('<div class="row"><label for="r365_password">Password</label>'
                   '<input type="password" id="r365_password" name="r365_password" autocomplete="new-password">'
                   f'<p class="hint">Kept only in this computer\'s secure store, never in a file. '
                   f'<span class="state">{"A password is saved." if pw_saved else "No password saved yet."}</span> '
                   'Leave blank to keep the saved one.</p></div>')
        out.append(_checkbox("r365_forget", False, "Forget the saved password", "Tick and Save to remove it from this computer."))
        out.append('<button type="submit" name="action" value="test_r365">Save and test the connection</button>')
        out.append('<p class="hint">Which R365 fields hold each figure is set in r365_mapping.toml. '
                   'Until that is filled in, checks show "needs mapping" in the report.</p></fieldset>')

        out.append('<fieldset><legend>2. Locations</legend>')
        out.append(_area("locations_include", c.include, "Only these locations",
                         "One per line, spelled as in R365. Leave empty to include every location found."))
        out.append(_area("locations_ignore", c.ignore, "Leave these out",
                         "One per line, for example a restaurant that has closed."))
        out.append('</fieldset>')

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
                             "Off until the R365 approval field is confirmed for your tenant (see docs/R365_OPEN_QUESTIONS.md)."))
        out.append(_checkbox("rule_payments", c.payments_enabled, "Payments add up to sales (optional)",
                             "Flag a day where the payment types don't add up to the sales total. Needs mapping for R365."))
        out.append(_field("payments_tolerance", f"{c.payments_tolerance}", "Payments tolerance ($)", "How far apart they may be before it is flagged.", "number", 'step="0.01" min="0"'))
        out.append('<p class="hint">A location with no data, or a blank figure, is always shown as UNKNOWN. That cannot be switched off.</p></fieldset>')

        out.append('<fieldset><legend>4. Email</legend>')
        out.append(_checkbox("email_enabled", s.email_enabled, "Prepare an email each time the report runs",
                             "Puts the report in your own Microsoft 365 mailbox as a draft you can read and send."))
        out.append(_field("email_to", s.email_to, "Send to", "One email address."))
        out.append(_checkbox("email_send_auto", s.email_send_auto, "Send automatically",
                             "Off by default. When off, you only get a draft to check and send yourself."))
        out.append(_field("graph_client_id", s.graph_client_id, "Microsoft app ID",
                          "The app registration ID your administrator set up (it is not a secret)."))
        out.append(_field("graph_tenant", s.graph_tenant, "Microsoft tenant", "Leave as 'organizations' unless told otherwise."))
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
        if u.path != "/" or not self._ok_request(t):
            return self._send(403, "<p>This page can only be opened from the program.</p>")
        self._send(200, self.server.app.render(self.server.token))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000:
            return self._send(413, "<p>Too much data.</p>")
        form = parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True)
        if self.path != "/" or not self._ok_request(form.get("t", [""])[0]):
            return self._send(403, "<p>This page can only be used from the program.</p>")
        app, messages, problem = self.server.app, [], ""
        action = form.get("action", ["save"])[0]
        password = form.get("r365_password", [""])[0]
        try:
            messages += app.apply_form(form)
            if action not in ("save", "quit"):
                messages += app.action(action)
        except DssError as exc:
            problem = redact(str(exc), password)
        self.server.touch()
        if action == "quit" and not problem:
            self._send(200, "<!DOCTYPE html><meta charset=utf-8><p style='font:19px system-ui;padding:20px'>"
                            "Settings saved. You can close this tab.</p>")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._send(200, app.render(self.server.token, messages, problem))


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

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/?t={self.token}"


def serve(open_browser: bool = True, app: Optional[SettingsApp] = None) -> int:
    server = SettingsServer(app or SettingsApp())
    print(f"Settings are open in your browser. If not, open: {server.url}")
    print("Close this window or press Ctrl+C when you are done.")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
