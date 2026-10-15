import html as htmllib
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from unittest import mock

import tomllib

from dssreport.config import parse_config
from dssreport.credstore import InMemoryStoreForTests
from dssreport.graph import GraphClient
from dssreport.settings import Instance, Settings, load_settings, save_settings
from dssreport.settings_server import SettingsApp, SettingsServer

from . import licence_helpers as H
from .mock_graph import CLIENT_ID, MockGraph
from .mock_r365 import PASSWORD, USER, MockR365


class Base(unittest.TestCase):
    licence_kw = {}          # override per test class; {} = a good 2-connection base licence
    install_licence = True

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict("os.environ", {"DSSREPORT_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        keys = H.trusted_keys()
        keys.__enter__()
        self.addCleanup(lambda: keys.__exit__(None, None, None))
        if self.install_licence:
            H.install(self.home, **self.licence_kw)
        self.store = InMemoryStoreForTests()
        self.graph_base = None
        self.app = SettingsApp(self.store, graph_factory=self._graph)
        self.server = SettingsServer(self.app)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.port = self.server.server_port

    def _graph(self, store):
        if self.graph_base:
            return GraphClient(store, authority=self.graph_base, graph=self.graph_base + "/v1.0")
        return GraphClient(store)

    def get(self, path=None, headers=None):
        url = f"http://127.0.0.1:{self.port}" + (path if path is not None else f"/?t={self.server.token}")
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, htmllib.unescape(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, htmllib.unescape(e.read().decode())

    def post(self, fields, token=None, headers=None, path="/"):
        data = {"t": self.server.token if token is None else token}
        data.update(fields)
        body = urllib.parse.urlencode(data, doseq=True).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, htmllib.unescape(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, htmllib.unescape(e.read().decode())

    def upload_licence(self, raw: bytes, token=None):
        boundary = "----testboundary7391"
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="t"\r\n\r\n{token or self.server.token}\r\n'.encode(),
                 f'--{boundary}\r\nContent-Disposition: form-data; name="licence"; filename="licence.json"\r\n'
                 f'Content-Type: application/json\r\n\r\n'.encode() + raw + b"\r\n",
                 f"--{boundary}--\r\n".encode()]
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/licence", data=b"".join(parts),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, htmllib.unescape(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, htmllib.unescape(e.read().decode())

    def all_files_text(self):
        return " ".join(p.read_text(errors="ignore") for p in self.home.rglob("*") if p.is_file())

    def add_instance(self, name="Sample Group A", url="https://odata.example.com/a", user=USER, **kw):
        s = load_settings()
        inst = Instance(id=name.lower().replace(" ", "-"), name=name, base_url=url, username=user, **kw)
        s.instances.append(inst)
        save_settings(s)
        return inst


RULES = {"payments_tolerance": "0.01", "rule_pos": "1", "rule_cash": "1", "cash_limit": "7.5",
         "rule_receipts": "1", "receipts_allowed": "1", "rule_exceptions": "1", "exceptions_allowed": "0",
         "rule_unapproved": "1", "schedule_time": "07:30", "wd0": "1", "wd1": "1", "wd2": "1", "wd3": "1",
         "wd4": "1", "ai_endpoint": "http://localhost:11434", "ai_model": "my-model"}


def form_for(instances, **extra):
    """What the page would post for the connections that already exist (all left as they are)."""
    f = dict(RULES)
    for i, inst in enumerate(instances):
        f.update({f"inst_id_{i}": inst.id, f"inst_name_{i}": inst.name, f"inst_url_{i}": inst.base_url,
                  f"inst_user_{i}": inst.username})
        if inst.enabled:
            f[f"inst_enabled_{i}"] = "1"
        f[f"inst_include_{i}"] = "\n".join(inst.include)
    f.update(extra)
    return f


class Access(Base):
    def test_page_needs_the_token_and_local_host_header(self):
        self.assertEqual(self.get("/")[0], 403)
        self.assertEqual(self.get("/?t=wrong")[0], 403)
        self.assertEqual(self.get(headers={"Host": "evil.example.com"})[0], 403)
        self.assertEqual(self.get()[0], 200)

    def test_post_needs_token_and_same_origin(self):
        self.assertEqual(self.post(RULES, token="nope")[0], 403)
        self.assertEqual(self.post(RULES, headers={"Origin": "http://evil.example.com"})[0], 403)
        self.assertEqual(self.post({"action": "save", **RULES})[0], 200)

    def test_licence_upload_needs_the_token_too(self):
        self.assertEqual(self.upload_licence(H.make(), token="nope")[0], 403)

    def test_only_listens_on_this_computer(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_a_real_browser_form_post_is_accepted_and_origin_null_is_not(self):
        """Browsers send Origin: null on form posts when Referrer-Policy is no-referrer. We use same-origin, so
        the browser sends the real origin (accepted); a literal "null" origin (sandboxed frame) stays refused."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/?t={self.server.token}")
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.headers["Referrer-Policy"], "same-origin")
        origin = f"http://127.0.0.1:{self.port}"
        self.assertEqual(self.post({"action": "save", **RULES}, headers={"Origin": origin})[0], 200)
        self.assertEqual(self.post({"action": "save", **RULES}, headers={"Origin": "null"})[0], 403)
        self.assertEqual(self.post({"action": "save", **RULES}, headers={"Origin": f"http://localhost:{self.port}"})[0], 200)

    def test_security_headers(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/?t={self.server.token}")
        with urllib.request.urlopen(req) as r:
            self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["X-Frame-Options"], "DENY")


class Page(Base):
    def test_defaults_are_safe(self):
        _, html = self.get()
        for name in ("email_send_auto", "ai_enabled", "email_enabled", "schedule_enabled", "rule_payments"):
            self.assertRegex(html, rf'name="{name}" value="1"(?! checked)', name)
        self.assertRegex(html, r'name="rule_unapproved" value="1" checked')   # approval check on by default
        self.assertRegex(html, r'name="wd0" value="1" checked')
        self.assertRegex(html, r'name="wd6" value="1">')
        self.assertIn("07:00", html)

    def test_every_setting_has_a_one_line_explanation(self):
        _, html = self.get()
        inputs = re.findall(r'<(?:input|textarea)[^>]*name="(\w+)"', html)
        skip = {"t", "licence", "new_pw"} | {f"wd{i}" for i in range(7)}
        for name in set(inputs) - skip:
            block = html.split(f'name="{name}"', 1)[1][:700]
            self.assertIn('class="hint"', block, f"no hint after {name}")

    def test_text_is_never_tiny_and_page_is_phone_ready(self):
        self.add_instance()
        _, html = self.get()
        self.assertIn('name="viewport"', html)
        for value, unit in re.findall(r"font(?:-size)?:\s*([\d.]+)(px|rem)", html):
            self.assertGreaterEqual(float(value) * (16 if unit == "rem" else 1), 16)
        self.assertNotIn("<script", html)


class Saving(Base):
    def test_save_writes_rules_toml_and_settings_json(self):
        inst = self.add_instance()
        f = form_for([inst], action="save")
        f["inst_url_0"] = "https://tenant.example.com/api/v2/views"
        _, html = self.post(f)
        self.assertIn("Settings saved.", html)
        cfg = parse_config(tomllib.loads((self.home / "rules.toml").read_text()))
        self.assertEqual(str(cfg.cash_limit), "7.5")
        self.assertEqual(cfg.receipts_allowed, 1)
        st = load_settings()
        self.assertEqual(st.instances[0].base_url, "https://tenant.example.com/api/v2/views")
        self.assertEqual(st.schedule_time, "07:30")
        self.assertEqual(st.schedule_weekdays, [0, 1, 2, 3, 4])

    def test_bad_input_is_a_plain_message_and_nothing_is_written(self):
        inst = self.add_instance()
        _, html = self.post(form_for([inst], action="save", cash_limit="lots"))
        self.assertIn("The cash limit must be a number.", html)
        self.assertFalse((self.home / "rules.toml").exists())
        f = form_for([inst], action="save")
        f["inst_url_0"] = "http://tenant.example.com"
        _, html = self.post(f)
        self.assertIn("must start with https://", html)
        _, html = self.post(form_for([inst], action="save", email_send_auto="1"))
        self.assertIn("needs 'Prepare an email'", html)

    def test_password_goes_to_the_secure_store_only(self):
        inst = self.add_instance()
        secret = "Typed-Secret-9931"
        _, html = self.post(form_for([inst], action="save", inst_pw_0=secret))
        self.assertIn("A password is saved.", html)
        self.assertNotIn(secret, html)
        self.assertEqual(self.store.get(inst.credential_key), secret)
        self.assertNotIn(secret, self.all_files_text())
        _, page = self.get()
        self.assertNotIn(secret, page)
        self.post(form_for([inst], action="save", inst_forget_0="1"))
        self.assertIsNone(self.store.get(inst.credential_key))

    def test_password_is_not_echoed_even_when_the_save_fails(self):
        inst = self.add_instance()
        secret = "Typed-Secret-4417"
        _, html = self.post(form_for([inst], action="save", inst_pw_0=secret, cash_limit="x"))
        self.assertNotIn(secret, html)
        self.assertNotIn(secret, self.all_files_text())

    def test_schedule_is_applied_through_the_task_scheduler_only_when_changed(self):
        with mock.patch("dssreport.settings_server._is_windows", return_value=True), \
                mock.patch("dssreport.settings_server.scheduler.install_task", return_value="Scheduled for 07:30.") as inst, \
                mock.patch("dssreport.settings_server.scheduler.remove_task", return_value="removed") as rem:
            _, html = self.post({"action": "save", **RULES, "schedule_enabled": "1"})
            self.assertIn("Scheduled for 07:30.", html)
            inst.assert_called_once()
            self.post({"action": "save", **RULES, "schedule_enabled": "1"})
            inst.assert_called_once()
            self.post({"action": "save", **RULES})
            rem.assert_called_once()

    def test_save_and_close_stops_the_server(self):
        status, html = self.post({"action": "quit", **RULES})
        self.assertIn("You can close this tab", html)
        self.assertEqual(status, 200)

    def test_no_secure_store_gives_a_plain_message(self):
        from dssreport.credstore import CredentialStoreError

        class Broken(InMemoryStoreForTests):
            def set(self, *a):
                raise CredentialStoreError("No secure place to keep the password was found on this computer, so nothing was saved.")
        inst = self.add_instance()
        self.app._store = Broken()
        _, html = self.post(form_for([inst], action="save", inst_pw_0="pw"))
        self.assertIn("nothing was saved", html)


class Buttons(Base):
    def test_test_connection_against_mock_r365(self):
        with MockR365() as srv:
            inst = self.add_instance(url=srv.url)
            self.store.set(inst.credential_key, PASSWORD)
            _, html = self.post(form_for([inst], action=f"test_r365:{inst.id}"))
            self.assertIn("Sample Group A: Connected to R365", html)
            self.store.set(inst.credential_key, "wrong")
            _, html = self.post(form_for([inst], action=f"test_r365:{inst.id}"))
            self.assertIn("refused the sign-in", html)

    def test_microsoft_signin_flow_with_mock(self):
        with MockGraph() as g:
            self.graph_base = g.base
            form = {**RULES, "email_enabled": "1", "email_to": "person@example.invalid", "graph_client_id": CLIENT_ID}
            _, html = self.post({"action": "m365_start", **form})
            self.assertIn("MOCK-CODE", html)
            self.assertIn("Not signed in", html)
            _, html = self.post({"action": "m365_finish", **form})
            self.assertIn("still waiting", html)
            g.approved = True
            _, html = self.post({"action": "m365_finish", **form})
            self.assertIn("Signed in to Microsoft 365", html)
            self.assertIn("drafts only", html)
            self.assertNotIn("refresh-1", html + self.all_files_text())
            _, html = self.post({"action": "m365_signout", **form})
            self.assertIn("Signed out", html)


class LocationToggles(Base):
    def seed(self, inst, names):
        from dssreport.state import note_seen, save_state
        save_state(note_seen({}, inst.id, names))

    def test_each_seen_location_has_a_show_tick_per_connection(self):
        a = self.add_instance("Sample Group A")
        b = self.add_instance("Sample Group B")
        self.seed(a, ["Demo Cafe South", "Demo Diner West"])
        from dssreport.state import load_state, note_seen, save_state
        st = load_state()
        save_state(note_seen(st, b.id, ["Sample Pier Grill"]))
        _, html = self.get()
        self.assertRegex(html, r'name="loc_0_0" value="1" checked')
        self.assertIn("Sample Pier Grill", html)
        # untick the first location of connection A and save
        f = form_for([a, b], action="save", locname_0_0="Demo Cafe South", locname_0_1="Demo Diner West",
                     loc_0_1="1", locname_1_0="Sample Pier Grill", loc_1_0="1")
        self.post(f)
        s = load_settings()
        self.assertEqual(s.instances[0].hidden, ["Demo Cafe South"])
        self.assertEqual(s.instances[1].hidden, [])           # B is untouched: toggles are per connection
        _, html = self.get()
        self.assertNotRegex(html, r'name="loc_0_0" value="1" checked')
        f = form_for([load_settings().instances[0], b], action="save", locname_0_0="Demo Cafe South",
                     locname_0_1="Demo Diner West", loc_0_0="1", loc_0_1="1", locname_1_0="Sample Pier Grill", loc_1_0="1")
        self.post(f)
        self.assertEqual(load_settings().instances[0].hidden, [])

    def test_only_these_locations_is_per_connection(self):
        a = self.add_instance("Sample Group A")
        b = self.add_instance("Sample Group B")
        f = form_for([a, b], action="save", inst_include_0="Demo Grill East\r\nDemo Cafe South\r\n")
        self.post(f)
        s = load_settings()
        self.assertEqual(s.instances[0].include, ["Demo Grill East", "Demo Cafe South"])
        self.assertEqual(s.instances[1].include, [])


class NoRealIdentifiers(Base):
    def test_page_has_only_fake_placeholders_for_ids_and_addresses(self):
        _, html = self.get()
        self.assertIn('placeholder="paste the Application (client) ID"', html)
        self.assertIn('placeholder="you@your-company.example"', html)
        self.assertNotRegex(html, r'name="graph_client_id" value="[^"]')
        self.assertNotRegex(html, r'name="email_to" value="[^"]')

    def test_mapping_status_and_private_location_are_shown_per_connection(self):
        self.add_instance()
        _, html = self.get()
        self.assertIn("never committed", html)
        self.assertIn("needs mapping", html)
        self.assertIn("mappings", html)


class ViewThenEmail(Base):
    def make_report(self, name="r1"):
        from dssreport.runner import run_report
        from dssreport.state import load_state, save_state
        res = run_report("demo", self.home / "reports" / name)
        st = load_state()
        st["last_report_dir"] = str(res.html_path.parent)
        save_state(st)
        return res

    def seen(self, path):
        return self.get(f"{path}?t={self.server.token}")

    def test_view_page_needs_the_token_and_shows_the_report_with_nothing_sent(self):
        self.make_report()
        self.assertEqual(self.get("/report")[0], 403)
        status, html = self.seen("/report")
        self.assertEqual(status, 200)
        self.assertIn("Nothing has been emailed", html)
        self.assertIn("1 unapproved (0 ready to approve, 1 with something flagged).", html)
        self.assertIn("Needs to balance", html)
        self.assertIn("Create an email draft in Microsoft 365", html)
        self.assertIn("Open in my mail app", html)

    def test_no_report_yet_is_a_plain_page(self):
        status, html = self.seen("/report")
        self.assertEqual(status, 200)
        self.assertIn("No report yet", html)

    def test_mail_app_link_is_filled_in_and_short_enough(self):
        save_settings(Settings(email_enabled=True, email_to="person@example.invalid"))
        self.make_report()
        _, html = self.seen("/report")
        link = re.search(r'href="(mailto:[^"]+)"', html).group(1)
        self.assertTrue(link.startswith("mailto:person@example.invalid?subject="))
        self.assertLessEqual(len(link), 1800)

    def test_mailto_cuts_long_bodies_at_a_line_break(self):
        from dssreport.settings_server import mailto_link
        body = "\n".join(f"line {i} " + "x" * 60 for i in range(100))
        link = mailto_link("a@example.invalid", "S", body)
        self.assertLessEqual(len(link), 1800)
        self.assertIn("Shortened", urllib.parse.unquote(link))

    def test_emailing_needs_a_click_and_creates_only_a_draft_by_default(self):
        with MockGraph() as g:
            self.graph_base = g.base
            save_settings(Settings(email_enabled=True, email_to="person@example.invalid", graph_client_id=CLIENT_ID))
            self.make_report()
            form = {**RULES, "email_enabled": "1", "email_to": "person@example.invalid", "graph_client_id": CLIENT_ID}
            self.post({"action": "m365_start", **form})
            g.approved = True
            self.post({"action": "m365_finish", **form})
            self.seen("/report")
            self.assertEqual(g.drafts, {})                      # looking is not emailing
            status, page = self.post({}, path="/email")
            self.assertIn("draft addressed to person@example.invalid", page)
            self.assertEqual(len(g.drafts), 1)
            self.assertEqual(g.sent, [])

    def test_email_post_needs_the_token(self):
        self.make_report()
        self.assertEqual(self.post({}, token="wrong", path="/email")[0], 403)

    def test_email_without_a_recipient_is_a_plain_message(self):
        self.make_report()
        _, page = self.post({}, path="/email")
        self.assertIn("Fill in who the email should go to", page)

    def test_send_automatically_changes_the_button_label(self):
        save_settings(Settings(email_enabled=True, email_to="person@example.invalid", email_send_auto=True))
        self.make_report()
        _, html = self.seen("/report")
        self.assertIn("Send it now through Microsoft 365", html)

    def test_earlier_reports_can_be_opened_and_a_bad_folder_name_cannot(self):
        self.make_report("2026-03-10")
        self.make_report("2026-03-11")
        _, html = self.seen("/report")
        self.assertIn("Earlier reports", html)
        self.assertIn("d=2026-03-10", html)
        _, old = self.get(f"/report?t={self.server.token}&d=2026-03-10")
        self.assertIn("1 unapproved (0 ready to approve, 1 with something flagged).", old)
        _, bad = self.get(f"/report?t={self.server.token}&d=../../etc")
        self.assertIn("was not found", bad)


class LicenceSection(Base):
    def test_status_customer_connections_and_dates_are_shown(self):
        self.add_instance()
        _, html = self.get()
        self.assertIn("Licence: valid for Sample Customer Ltd until 2099-12-31.", html)
        self.assertIn("1 used of 2 allowed", html)
        self.assertIn("<th scope=\"row\">Updates:</th><td>until 2099-12-31</td>", html)
        self.assertIn("Email through Microsoft 365", html)
        self.assertIn("nothing is sent anywhere", html)
        self.assertIn('name="licence"', html)

    def test_loading_a_good_licence_file(self):
        (self.home / "licence.json").unlink()
        _, html = self.get()
        self.assertIn("Licence: not found", html)
        _, html = self.upload_licence(H.make(customer="Another Sample Co", instances=5))
        self.assertIn("Licence file loaded", html)
        self.assertIn("valid for Another Sample Co", html)
        self.assertIn("0 used of 5 allowed", html)

    def test_a_tampered_licence_is_refused_plainly_and_the_old_one_stays(self):
        before = (self.home / "licence.json").read_bytes()
        bad = H.make(instances=99, secret=H.OTHER_SECRET)
        _, html = self.upload_licence(bad)
        self.assertIn("That licence file was not loaded", html)
        self.assertIn("signature does not match", html)
        self.assertEqual((self.home / "licence.json").read_bytes(), before)
        _, html = self.upload_licence(b"not a licence")
        self.assertIn("not a licence file", html)

    def test_no_file_chosen(self):
        boundary = "xb"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="t"\r\n\r\n{self.server.token}\r\n'
                f'--{boundary}--\r\n').encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/licence", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req) as r:
            self.assertIn("Choose a licence file first", htmllib.unescape(r.read().decode()))

    def test_expired_licence_is_shown_as_expired(self):
        self.upload_licence(H.make(expires=date(2020, 1, 1)))
        _, html = self.get()
        self.assertIn("Licence: expired on 2020-01-01", html)

    def test_over_the_limit_is_shown(self):
        self.add_instance("Sample Group A")
        self.add_instance("Sample Group B")
        self.upload_licence(H.make(instances=1))
        _, html = self.get()
        self.assertIn("2 used of 1 allowed (over the limit)", html)


class ConnectionLimit(Base):
    licence_kw = {"instances": 1}

    def add_form(self, existing, name):
        return form_for(existing, action="save", new_name=name, new_url="https://odata.example.com/b",
                        new_user=USER, new_pw="pw-x")

    def test_adding_beyond_the_licence_is_refused_with_a_plain_message(self):
        a = self.add_instance("Sample Group A")
        _, html = self.post(self.add_form([a], "Sample Group B"))
        self.assertIn("Licence: over limit. Your licence allows 1 connection and 1 is already set up.", html)
        self.assertEqual([i.name for i in load_settings().instances], ["Sample Group A"])
        self.assertEqual(self.store.items, {})                # nothing was stored either

    def test_adding_within_the_licence_works_and_gets_its_own_credential_and_mapping_file(self):
        _, html = self.post(self.add_form([], "Sample Group A"))
        self.assertIn("Connection 'Sample Group A' added", html)
        inst = load_settings().instances[0]
        self.assertEqual(self.store.get(inst.credential_key), "pw-x")
        self.assertEqual(inst.mapping_file, "mappings/sample-group-a.toml")
        self.assertTrue(str(inst.mapping_path).startswith(str(self.home)))

    def test_enabling_a_disabled_connection_counts_against_the_limit(self):
        a = self.add_instance("Sample Group A")
        b = self.add_instance("Sample Group B", enabled=False)
        f = form_for([a, load_settings().instances[1]], action="save", inst_enabled_1="1")
        _, html = self.post(f)
        self.assertIn("Licence: over limit", html)
        self.assertFalse(load_settings().instances[1].enabled)

    def test_removing_one_makes_room(self):
        a = self.add_instance("Sample Group A")
        f = form_for([a], action="save", inst_remove_0="1", new_name="Sample Group B",
                     new_url="https://odata.example.com/b", new_user=USER)
        _, html = self.post(f)
        self.assertIn("Connection 'Sample Group B' added", html)
        self.assertEqual([i.name for i in load_settings().instances], ["Sample Group B"])



class SeveralConnections(Base):
    licence_kw = {"instances": 3}

    def test_two_connections_are_each_kept_separately(self):
        a = self.add_instance("Sample Group A", url="https://odata.example.com/a")
        b = self.add_instance("Sample Group B", url="https://odata.example.com/b", user="OTHERDOMAIN\\other.user")
        self.assertNotEqual(a.credential_key, b.credential_key)
        self.assertNotEqual(a.mapping_file, b.mapping_file)
        self.post(form_for([a, b], action="save", inst_pw_0="pw-for-a", inst_pw_1="pw-for-b"))
        self.assertEqual(self.store.get(a.credential_key), "pw-for-a")
        self.assertEqual(self.store.get(b.credential_key), "pw-for-b")
        _, html = self.get()
        self.assertIn("Sample Group A", html)
        self.assertIn("Sample Group B", html)
        self.assertIn("2 used of 3 allowed", html)

    def test_two_connections_with_the_same_name_are_refused(self):
        a = self.add_instance("Sample Group A")
        f = form_for([a], action="save", new_name="sample group a", new_url="https://odata.example.com/z", new_user=USER)
        _, html = self.post(f)
        self.assertIn("both called", html)
        self.assertEqual(len(load_settings().instances), 1)


class NoLicence(Base):
    install_licence = False

    def test_no_licence_means_no_new_connection_but_the_page_works(self):
        _, html = self.get()
        self.assertIn("Licence: not found", html)
        _, html = self.post(form_for([], action="save", new_name="Sample Group A",
                                     new_url="https://odata.example.com/a", new_user=USER))
        self.assertIn("Load a licence file in settings first", html)

    def test_licensed_features_cannot_be_switched_on_without_the_flag(self):
        _, html = self.post({"action": "save", **RULES, "schedule_enabled": "1"})
        self.assertIn("Automatic schedule is not included in your licence", html)
        _, html = self.post({"action": "save", **RULES, "ai_enabled": "1"})
        self.assertIn("Summary sentence from a local model is not included", html)
        _, html = self.post({"action": "save", **RULES, "rule_payments": "1"})
        self.assertIn("Optional checks is not included", html)
        _, html = self.post({"action": "save", **RULES, "email_enabled": "1", "email_to": "person@example.invalid"})
        self.assertIn("Email through Microsoft 365 is not included", html)

    def test_existing_reports_can_still_be_viewed_and_the_mail_app_link_still_works(self):
        from dssreport.runner import run_report
        from dssreport.state import save_state
        res = run_report("demo", self.home / "reports" / "r1")      # demo data is never blocked
        save_state({"last_report_dir": str(res.html_path.parent)})
        _, html = self.get(f"/report?t={self.server.token}")
        self.assertIn("1 unapproved (0 ready to approve, 1 with something flagged).", html)
        self.assertIn("Open in my mail app", html)


if __name__ == "__main__":
    unittest.main()


class VersionVsUpdates(Base):
    def test_version_inside_or_after_the_updates_period_is_stated_plainly(self):
        self.upload_licence(H.make(updates_until=date(2099, 1, 1)))
        _, html = self.get()
        self.assertIn("inside your updates period", html)
        self.upload_licence(H.make(updates_until=date(2020, 1, 1)))
        _, html = self.get()
        self.assertIn("newer than your updates period (it still runs", html)


class RenewalAndUnlimitedInSettings(Base):
    def test_reminder_appears_at_30_days_and_not_before(self):
        from datetime import timedelta
        today = date.today()
        self.upload_licence(H.make(expires=today + timedelta(days=31)))
        _, html = self.get()
        self.assertNotIn("Licence expires in", html)
        self.upload_licence(H.make(expires=today + timedelta(days=12)))
        _, html = self.get()
        self.assertIn("Licence expires in 12 days", html)
        self.assertGreaterEqual(html.count("Licence expires in 12 days"), 2)      # top of page and in the section

    def test_expired_notice_uses_the_agreed_wording_and_blocks_nothing(self):
        self.add_instance()
        self.upload_licence(H.make(expires=date(2020, 1, 1)))
        _, html = self.get()
        self.assertIn("Licence expired on 2020-01-01 — renew to add connections or get updates.", html)
        self.assertEqual(self.get(f"/report?t={self.server.token}")[0], 200)       # reports still open
        _, saved = self.post(form_for(load_settings().instances, action="save"))
        self.assertIn("Settings saved.", saved)                                    # settings still save

    def test_unlimited_is_shown_plainly_and_lets_connections_be_added(self):
        self.upload_licence(H.make(instances="unlimited"))
        a = self.add_instance("Sample Group A")
        _, html = self.get()
        self.assertIn("unlimited (1 in use)", html)
        self.assertNotIn("allowed", html.split("<legend>1. Licence</legend>")[1].split("</fieldset>")[0].split("Connections")[1][:60])
        existing = [a]
        for n in "BCDE":
            _, page = self.post(form_for(load_settings().instances, action="save", new_name=f"Sample Group {n}",
                                         new_url="https://odata.example.com/x", new_user=USER))
            self.assertIn(f"Connection 'Sample Group {n}' added", page)
        self.assertEqual(len(load_settings().instances), 5)
        _, html = self.get()
        self.assertIn("unlimited (5 in use)", html)


class UpdatesSection(Base):
    def setUp(self):
        super().setUp()
        from . import test_updates as U
        self.U = U
        self.pdir = Path(tempfile.mkdtemp())
        for rel, data in U.OLD.items():
            (self.pdir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pdir / rel).write_bytes(data)
        self.app.program_dir = self.pdir
        k = U.update_keys()
        k.__enter__()
        self.addCleanup(lambda: k.__exit__(None, None, None))
        self.tmp = Path(tempfile.mkdtemp())

    def package(self, **kw):
        out = self.tmp / f"p{len(list(self.tmp.iterdir()))}.dssupdate"
        self.U.update_tool.build_update(self.U.USECRET, self.U.UKID, self.U.NEW, "9.9.0", date(2026, 10, 1), out, **kw)
        return out.read_bytes()

    def upload(self, raw, path="/update", token=None):
        boundary = "----upd"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="t"\r\n\r\n{token or self.server.token}\r\n'.encode()
                + f'--{boundary}\r\nContent-Disposition: form-data; name="update"; filename="u.dssupdate"\r\n'
                  f'Content-Type: application/octet-stream\r\n\r\n'.encode() + raw + f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, htmllib.unescape(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, htmllib.unescape(e.read().decode())

    def test_section_explains_owner_control_and_shows_versions(self):
        _, html = self.get()
        self.assertIn("2. Updates", html)
        self.assertIn("Installed version", html)
        self.assertIn("never goes online", html)
        self.assertIn('name="update"', html)
        self.assertNotIn("Go back to the previous version", html)

    def test_installing_a_signed_update_file_and_going_back(self):
        status, html = self.upload(self.package())
        self.assertEqual(status, 200)
        self.assertIn("to 9.9.0", html)
        self.assertEqual((self.pdir / "dssreport/thing.py").read_bytes(), b"VALUE = 2\n")
        self.assertIn("Go back to the previous version", html)
        _, html = self.post({}, path="/rollback")
        self.assertIn("Went back to version", html)
        self.assertEqual((self.pdir / "dssreport/thing.py").read_bytes(), b"VALUE = 1\n")

    def test_refusals_are_plain_and_change_nothing(self):
        _, html = self.upload(b"not an update")
        self.assertIn("not an update file", html)
        wrong = self.U.update_tool.build_update(self.U.OTHER_USECRET, self.U.UKID, self.U.NEW, "9.9.0",
                                                date(2026, 10, 1), self.tmp / "w.dssupdate")
        _, html = self.upload(wrong.read_bytes())
        self.assertIn("changed or was not made by Jay Rohrs", html)
        _, html = self.upload(self.package(licence_ids=["someone-elses-licence"]))
        self.assertIn("has not been released to your licence", html)
        self.assertEqual((self.pdir / "dssreport/thing.py").read_bytes(), b"VALUE = 1\n")

    def test_update_period_is_enforced_here_and_the_rest_of_settings_still_works(self):
        self.upload_licence(H.make(updates_until=date(2026, 1, 1)))
        _, html = self.upload(self.package())
        self.assertIn("includes updates until 2026-01-01", html)
        self.assertIn("Licence: valid for", html)                          # nothing else was blocked

    def test_needs_the_token_and_a_file(self):
        self.assertEqual(self.upload(self.package(), token="wrong")[0], 403)
        self.assertEqual(self.post({}, token="wrong", path="/rollback")[0], 403)
        boundary = "x"
        body = f'--{boundary}\r\nContent-Disposition: form-data; name="t"\r\n\r\n{self.server.token}\r\n--{boundary}--\r\n'.encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/update", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req) as r:
            self.assertIn("Choose an update file first", htmllib.unescape(r.read().decode()))

    def test_licence_and_settings_files_are_never_touched_by_an_update(self):
        before = (self.home / "licence.json").read_bytes()
        self.add_instance()
        settings_before = (self.home / "settings.json").read_bytes()
        self.upload(self.package())
        self.assertEqual((self.home / "licence.json").read_bytes(), before)
        self.assertEqual((self.home / "settings.json").read_bytes(), settings_before)


class OnlineUpdates(Base):
    def setUp(self):
        super().setUp()
        from . import test_update_check as C
        from . import test_updates as U
        self.C, self.U = C, U
        self.pdir = Path(tempfile.mkdtemp())
        for rel, data in U.OLD.items():
            (self.pdir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pdir / rel).write_bytes(data)
        self.app.program_dir = self.pdir
        k = U.update_keys()
        k.__enter__()
        self.addCleanup(lambda: k.__exit__(None, None, None))
        self.host = C.MockStaticHost()
        self.host.__enter__()
        self.addCleanup(lambda: self.host.__exit__(None, None, None))
        self.pkgs = Path(tempfile.mkdtemp())
        out = self.pkgs / "dss-update-9.9.0.dssupdate"
        U.update_tool.build_update(U.USECRET, U.UKID, U.NEW, "9.9.0", date(2026, 10, 1), out, notes="Sample notes")
        self.host.files["/dss/dss-update-9.9.0.dssupdate"] = out.read_bytes()
        m = self.pkgs / "manifest.json"
        U.update_tool.write_manifest(U.USECRET, U.UKID, self.pkgs, m)
        self.host.files["/dss/manifest.json"] = m.read_bytes()
        self.url = self.host.base + "/manifest.json"

    def up(self, **f):
        return self.post(f, path="/updates")

    def test_off_by_default_and_checking_while_off_makes_no_request(self):
        _, html = self.get()
        self.assertRegex(html, r'name="update_check_enabled" value="1"(?! checked)')
        self.assertIn('placeholder="https://updates.example.invalid/dss-report/manifest.json"', html)
        self.assertNotRegex(html, r'name="update_manifest_url" value="[^"]')
        _, html = self.up(action="check", update_manifest_url=self.url)
        self.assertIn("Online update checking is switched off", html)
        self.assertEqual(self.host.requests, [])

    def test_saving_the_setting_alone_makes_no_request(self):
        _, html = self.up(action="save", update_check_enabled="1", update_manifest_url=self.url)
        self.assertIn("Update settings saved.", html)
        self.assertEqual(self.host.requests, [])
        s = load_settings()
        self.assertEqual((s.update_check_enabled, s.update_manifest_url), (True, self.url))

    def test_check_then_download_then_install_each_needs_its_own_click(self):
        self.up(action="save", update_check_enabled="1", update_manifest_url=self.url)
        _, html = self.up(action="check", update_check_enabled="1", update_manifest_url=self.url)
        self.assertIn("1 newer version listed. Nothing has been downloaded.", html)
        self.assertIn("Version 9.9.0 (released 2026-10-01) - Sample notes", html)
        self.assertIn("Download version 9.9.0", html)
        self.assertEqual([r[1] for r in self.host.requests], ["GET /dss/manifest.json HTTP/1.1"])
        self.assertEqual((self.pdir / "dssreport/thing.py").read_bytes(), b"VALUE = 1\n")
        _, html = self.up(action="download:dss-update-9.9.0.dssupdate", update_check_enabled="1", update_manifest_url=self.url)
        self.assertIn("downloaded and checked. It is NOT installed yet", html)
        self.assertIn("Downloaded and checked: dss-update-9.9.0.dssupdate", html)
        self.assertEqual((self.pdir / "dssreport/thing.py").read_bytes(), b"VALUE = 1\n")       # still not installed
        _, html = self.up(action="install:dss-update-9.9.0.dssupdate", update_check_enabled="1", update_manifest_url=self.url)
        self.assertIn("Updated from version 0.3.0 to 9.9.0", html)
        self.assertEqual((self.pdir / "dssreport/thing.py").read_bytes(), b"VALUE = 2\n")
        self.assertEqual(update_check_downloads(), [])                                         # the downloaded copy is tidied away

    def test_download_without_checking_first_and_unknown_files_are_refused(self):
        self.up(action="save", update_check_enabled="1", update_manifest_url=self.url)
        _, html = self.up(action="download:dss-update-9.9.0.dssupdate", update_check_enabled="1", update_manifest_url=self.url)
        self.assertIn("Press 'Check for updates now' first", html)
        _, html = self.up(action="install:../../etc/passwd", update_check_enabled="1", update_manifest_url=self.url)
        self.assertIn("downloaded update file was not found", html)

    def test_a_listed_version_outside_the_updates_period_offers_no_download(self):
        self.upload_licence(H.make(updates_until=date(2026, 1, 1)))
        self.up(action="save", update_check_enabled="1", update_manifest_url=self.url)
        _, html = self.up(action="check", update_check_enabled="1", update_manifest_url=self.url)
        self.assertIn("Released after your updates period ended. Renew to get it.", html)
        self.assertNotIn("Download version 9.9.0", html)

    def test_a_bad_address_is_a_plain_message(self):
        _, html = self.up(action="save", update_check_enabled="1", update_manifest_url="http://updates.example.com/m.json")
        self.assertIn("must start with https://", html)
        _, html = self.up(action="save", update_check_enabled="1", update_manifest_url="")
        self.assertIn("fill in the update address", html)

    def test_token_is_required(self):
        self.assertEqual(self.post({"action": "check"}, token="wrong", path="/updates")[0], 403)

    def test_a_tampered_list_is_reported_plainly_in_the_page(self):
        import json
        doc = json.loads(self.host.files["/dss/manifest.json"])   # change the signature itself, so line endings don't matter
        sig = doc["signature"]
        doc["signature"] = ("B" if sig[0] != "B" else "C") + sig[1:]
        self.host.files["/dss/manifest.json"] = json.dumps(doc).encode()
        self.up(action="save", update_check_enabled="1", update_manifest_url=self.url)
        _, html = self.up(action="check", update_check_enabled="1", update_manifest_url=self.url)
        self.assertIn("update list", html)
        self.assertNotIn("Download version", html)


def update_check_downloads():
    from dssreport import update_check
    return update_check.downloaded_files()


class LifetimeInSettings(Base):
    def test_lifetime_is_shown_as_updates_lifetime(self):
        self.upload_licence(H.make(updates_until="lifetime"))
        _, html = self.get()
        self.assertIn('<th scope="row">Updates:</th><td>lifetime</td>', html)
        self.assertEqual(html.count('<th scope="row">Updates:</th><td>lifetime</td>'), 2)      # licence and updates sections
        self.assertIn("inside your updates period", html)
