import html as htmllib
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

import tomllib

from dssreport.config import parse_config
from dssreport.credstore import InMemoryStoreForTests
from dssreport.graph import GraphClient
from dssreport.r365 import credential_name
from dssreport.settings import load_settings
from dssreport.settings_server import SettingsApp, SettingsServer

from .mock_graph import CLIENT_ID, MockGraph
from .mock_r365 import PASSWORD, USER, MockR365


class Base(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict("os.environ", {"DSSREPORT_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.store = InMemoryStoreForTests()
        self.graph_base = None
        self.app = SettingsApp(self.store, graph_factory=self._graph)
        self.server = SettingsServer(self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
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

    def post(self, fields, token=None, headers=None):
        data = {"t": self.server.token if token is None else token}
        data.update(fields)
        body = urllib.parse.urlencode(data, doseq=True).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/", data=body, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, htmllib.unescape(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, htmllib.unescape(e.read().decode())

    def all_files_text(self):
        return " ".join(p.read_text(errors="ignore") for p in self.home.rglob("*") if p.is_file())


GOOD = {"r365_username": USER, "payments_tolerance": "0.01", "rule_pos": "1", "rule_cash": "1", "cash_limit": "7.5",
        "rule_receipts": "1", "receipts_allowed": "1", "rule_exceptions": "1", "exceptions_allowed": "0",
        "schedule_time": "07:30", "wd0": "1", "wd1": "1", "wd2": "1", "wd3": "1", "wd4": "1",
        "ai_endpoint": "http://localhost:11434", "ai_model": "my-model"}


class Access(Base):
    def test_page_needs_the_token_and_local_host_header(self):
        self.assertEqual(self.get("/")[0], 403)
        self.assertEqual(self.get("/?t=wrong")[0], 403)
        self.assertEqual(self.get(headers={"Host": "evil.example.com"})[0], 403)
        self.assertEqual(self.get()[0], 200)

    def test_post_needs_token_and_same_origin(self):
        self.assertEqual(self.post(GOOD, token="nope")[0], 403)
        self.assertEqual(self.post(GOOD, headers={"Origin": "http://evil.example.com"})[0], 403)
        self.assertEqual(self.post({"action": "save", **GOOD})[0], 200)

    def test_only_listens_on_this_computer(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_security_headers(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/?t={self.server.token}")
        with urllib.request.urlopen(req) as r:
            self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["X-Frame-Options"], "DENY")


class Page(Base):
    def test_defaults_are_safe(self):
        _, html = self.get()
        for name in ("email_send_auto", "ai_enabled", "email_enabled", "schedule_enabled",
                     "rule_payments", "r365_enabled"):
            self.assertRegex(html, rf'name="{name}" value="1"(?! checked)', name)
        self.assertRegex(html, r'name="rule_unapproved" value="1" checked')   # approval check on by default
        # weekdays ticked, weekend not
        self.assertRegex(html, r'name="wd0" value="1" checked')
        self.assertRegex(html, r'name="wd6" value="1">')
        self.assertIn("07:00", html)

    def test_every_setting_has_a_one_line_explanation(self):
        _, html = self.get()
        inputs = re.findall(r'<(?:input|textarea)[^>]*name="(\w+)"', html)
        skip = {"t", "r365_password"}  # password has its own explanation below the box
        for name in set(inputs) - skip - {f"wd{i}" for i in range(7)}:
            block = html.split(f'name="{name}"', 1)[1][:600]
            self.assertIn('class="hint"', block, f"no hint after {name}")
        self.assertIn("Kept only in this computer", html)

    def test_text_is_never_tiny_and_page_is_phone_ready(self):
        _, html = self.get()
        self.assertIn('name="viewport"', html)
        for value, unit in re.findall(r"font(?:-size)?:\s*([\d.]+)(px|rem)", html):
            self.assertGreaterEqual(float(value) * (16 if unit == "rem" else 1), 16)
        self.assertNotRegex(html, r"https?://(?!127|localhost)[^\s\"']*\.(js|css)")
        self.assertNotIn("<script", html)


class Saving(Base):
    def test_save_writes_rules_toml_and_settings_json(self):
        s, html = self.post({"action": "save", **GOOD, "r365_enabled": "1",
                             "r365_base_url": "https://tenant.example.com/api/v2/views",
                             "locations_include": "Demo Grill East\r\nDemo Cafe South\r\n"})
        self.assertIn("Settings saved.", html)
        cfg = parse_config(tomllib.loads((self.home / "rules.toml").read_text()))
        self.assertEqual(str(cfg.cash_limit), "7.5")
        self.assertEqual(cfg.receipts_allowed, 1)
        self.assertEqual(cfg.include, ["Demo Grill East", "Demo Cafe South"])
        self.assertFalse(cfg.unapproved_enabled)
        st = load_settings()
        self.assertTrue(st.r365_enabled)
        self.assertEqual(st.schedule_time, "07:30")
        self.assertEqual(st.schedule_weekdays, [0, 1, 2, 3, 4])

    def test_bad_input_is_a_plain_message_and_nothing_is_written(self):
        _, html = self.post({"action": "save", **GOOD, "cash_limit": "lots"})
        self.assertIn("The cash limit must be a number.", html)
        self.assertFalse((self.home / "rules.toml").exists())
        _, html = self.post({"action": "save", **GOOD, "r365_base_url": "http://tenant.example.com"})
        self.assertIn("must start with https://", html)
        _, html = self.post({"action": "save", **GOOD, "email_send_auto": "1"})
        self.assertIn("needs 'Prepare an email'", html)

    def test_password_goes_to_the_secure_store_only(self):
        secret = "Typed-Secret-9931"
        _, html = self.post({"action": "save", **GOOD, "r365_password": secret,
                             "r365_base_url": "https://tenant.example.com/x"})
        self.assertIn("A password is saved.", html)
        self.assertNotIn(secret, html)
        self.assertEqual(self.store.get(credential_name(USER)), secret)
        self.assertNotIn(secret, self.all_files_text())
        _, page = self.get()
        self.assertNotIn(secret, page)
        # and it can be forgotten
        self.post({"action": "save", **GOOD, "r365_forget": "1", "r365_base_url": "https://tenant.example.com/x"})
        self.assertIsNone(self.store.get(credential_name(USER)))

    def test_password_is_not_echoed_even_when_the_save_fails(self):
        secret = "Typed-Secret-4417"
        _, html = self.post({"action": "save", **GOOD, "r365_password": secret, "cash_limit": "x"})
        self.assertNotIn(secret, html)
        self.assertNotIn(secret, self.all_files_text())

    def test_schedule_is_applied_through_the_task_scheduler_only_when_changed(self):
        with mock.patch("dssreport.settings_server._is_windows", return_value=True), \
                mock.patch("dssreport.settings_server.scheduler.install_task", return_value="Scheduled for 07:30.") as inst, \
                mock.patch("dssreport.settings_server.scheduler.remove_task", return_value="removed") as rem:
            _, html = self.post({"action": "save", **GOOD, "schedule_enabled": "1"})
            self.assertIn("Scheduled for 07:30.", html)
            inst.assert_called_once()
            self.post({"action": "save", **GOOD, "schedule_enabled": "1"})   # unchanged -> no second call
            inst.assert_called_once()
            self.post({"action": "save", **GOOD})
            rem.assert_called_once()

    def test_save_and_close_stops_the_server(self):
        status, html = self.post({"action": "quit", **GOOD})
        self.assertIn("You can close this tab", html)
        self.assertEqual(status, 200)


class Buttons(Base):
    def test_test_connection_against_mock_r365(self):
        with MockR365() as srv:
            self.store.set(credential_name(USER), PASSWORD)
            _, html = self.post({"action": "test_r365", **GOOD, "r365_enabled": "1", "r365_base_url": srv.url})
            self.assertIn("Connected to R365", html)
            self.store.set(credential_name(USER), "wrong")
            _, html = self.post({"action": "test_r365", **GOOD, "r365_enabled": "1", "r365_base_url": srv.url})
            self.assertIn("refused the sign-in", html)
            self.assertNotIn("wrong</", html)

    def test_microsoft_signin_flow_with_mock(self):
        with MockGraph() as g:
            self.graph_base = g.base
            form = {**GOOD, "email_enabled": "1", "email_to": "person@example.invalid", "graph_client_id": CLIENT_ID}
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

    def test_no_secure_store_gives_a_plain_message(self):
        from dssreport.credstore import CredentialStoreError

        class Broken(InMemoryStoreForTests):
            def set(self, *a):
                raise CredentialStoreError("No secure place to keep the password was found on this computer, so nothing was saved.")
        self.app._store = Broken()
        _, html = self.post({"action": "save", **GOOD, "r365_password": "pw", "r365_base_url": "https://t.example.com/x"})
        self.assertIn("nothing was saved", html)


if __name__ == "__main__":
    unittest.main()


class LocationToggles(Base):
    def seed(self, names):
        from dssreport.state import note_seen, save_state
        save_state(note_seen({}, names))

    def test_each_seen_location_has_a_show_tick_and_unticking_hides_it(self):
        self.seed(["Demo Cafe South", "Demo Diner West"])
        _, html = self.get()
        self.assertRegex(html, r'name="loc_show_0" value="1" checked')
        self.assertIn("Demo Cafe South", html)
        # untick the first (leave out loc_show_0) and save
        self.post({"action": "save", **GOOD, "loc_name_0": "Demo Cafe South", "loc_name_1": "Demo Diner West",
                   "loc_show_1": "1"})
        cfg = parse_config(tomllib.loads((self.home / "rules.toml").read_text()))
        self.assertEqual(cfg.ignore, ["Demo Cafe South"])
        _, html = self.get()
        self.assertNotRegex(html, r'name="loc_show_0" value="1" checked')
        self.assertRegex(html, r'name="loc_show_1" value="1" checked')
        # tick it again -> shown again
        self.post({"action": "save", **GOOD, "loc_name_0": "Demo Cafe South", "loc_name_1": "Demo Diner West",
                   "loc_show_0": "1", "loc_show_1": "1"})
        cfg = parse_config(tomllib.loads((self.home / "rules.toml").read_text()))
        self.assertEqual(cfg.ignore, [])

    def test_hidden_location_is_left_out_of_the_report(self):
        from dssreport.adapters.demo import generate
        from dssreport.report import build_report
        recs = generate()
        r = build_report(recs, parse_config({"locations": {"ignore": ["Demo Cafe South"]}}))
        names = [x.name for x in r.attention + r.clear]
        self.assertNotIn("Demo Cafe South", names)
        self.assertEqual(len(names), 3)

    def test_hidden_locations_stay_listed_so_they_can_be_switched_back_on(self):
        self.post({"action": "save", **GOOD, "loc_name_0": "Demo Old Place"})   # not ticked -> hidden
        _, html = self.get()
        self.assertIn("Demo Old Place", html)
        self.assertNotRegex(html, r'name="loc_show_0" value="1" checked')


class NoRealIdentifiers(Base):
    def test_page_has_only_fake_placeholders_for_ids_and_addresses(self):
        _, html = self.get()
        self.assertIn('placeholder="paste the Application (client) ID"', html)
        self.assertIn('placeholder="you@your-company.example"', html)
        self.assertNotRegex(html, r'name="graph_client_id" value="[^"]')
        self.assertNotRegex(html, r'name="email_to" value="[^"]')

    def test_mapping_status_and_private_location_are_shown(self):
        _, html = self.get()
        self.assertIn("never committed anywhere", html)
        self.assertIn("needs mapping", html)


class ViewThenEmail(Base):
    def make_report(self):
        from dssreport.runner import run_report
        from dssreport.state import save_state
        res = run_report("demo", self.home / "reports" / "r1")
        save_state({"last_report_dir": str(res.html_path.parent)})
        return res

    def seen(self, path):
        return self.get(f"{path}?t={self.server.token}")

    def test_view_page_needs_the_token_and_shows_the_report_with_nothing_sent(self):
        self.make_report()
        self.assertEqual(self.get("/report")[0], 403)
        status, html = self.seen("/report")
        self.assertEqual(status, 200)
        self.assertIn("Nothing has been emailed", html)
        self.assertIn("3 of 4 locations need a look", html)
        self.assertIn("Entry is not approved", html)
        self.assertIn("Create an email draft in Microsoft 365", html)
        self.assertIn("Open in my mail app", html)

    def test_no_report_yet_is_a_plain_page(self):
        status, html = self.seen("/report")
        self.assertEqual(status, 200)
        self.assertIn("No report yet", html)

    def test_mail_app_link_is_filled_in_and_short_enough(self):
        from dssreport.settings import Settings, save_settings
        save_settings(Settings(email_enabled=True, email_to="person@example.invalid"))
        self.make_report()
        _, html = self.seen("/report")
        link = re.search(r'href="(mailto:[^"]+)"', html).group(1)
        self.assertTrue(link.startswith("mailto:person@example.invalid?subject="))
        self.assertLessEqual(len(link), 1800)
        self.assertIn("body=", link)

    def test_mailto_cuts_long_bodies_at_a_line_break(self):
        from dssreport.settings_server import mailto_link
        body = "\n".join(f"line {i} " + "x" * 60 for i in range(100))
        link = mailto_link("a@example.invalid", "S", body)
        self.assertLessEqual(len(link), 1800)
        self.assertIn("Shortened", urllib.parse.unquote(link))

    def test_emailing_needs_a_click_and_creates_only_a_draft_by_default(self):
        from dssreport.settings import Settings, save_settings
        with MockGraph() as g:
            self.graph_base = g.base
            save_settings(Settings(email_enabled=True, email_to="person@example.invalid",
                                   graph_client_id=CLIENT_ID))
            self.make_report()
            _, _ = self.post({"action": "m365_start", **GOOD, "email_enabled": "1",
                              "email_to": "person@example.invalid", "graph_client_id": CLIENT_ID})
            g.approved = True
            self.post({"action": "m365_finish", **GOOD, "email_enabled": "1",
                       "email_to": "person@example.invalid", "graph_client_id": CLIENT_ID})
            self.seen("/report")
            self.assertEqual(g.drafts, {})                      # looking is not emailing
            req_body = urllib.parse.urlencode({"t": self.server.token}).encode()
            with urllib.request.urlopen(urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/email", data=req_body)) as r:
                page = htmllib.unescape(r.read().decode())
            self.assertIn("draft addressed to person@example.invalid", page)
            self.assertEqual(len(g.drafts), 1)
            self.assertEqual(g.sent, [])
            self.assertIn("3 of 4 locations", g.drafts["draft-1"]["message"]["body"]["content"])

    def test_email_post_needs_the_token(self):
        self.make_report()
        body = urllib.parse.urlencode({"t": "wrong"}).encode()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.port}/email", data=body))
        self.assertEqual(cm.exception.code, 403)

    def test_email_without_a_recipient_is_a_plain_message(self):
        self.make_report()
        body = urllib.parse.urlencode({"t": self.server.token}).encode()
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.port}/email", data=body)) as r:
            self.assertIn("Fill in who the email should go to", htmllib.unescape(r.read().decode()))

    def test_send_automatically_changes_the_button_label(self):
        from dssreport.settings import Settings, save_settings
        save_settings(Settings(email_enabled=True, email_to="person@example.invalid", email_send_auto=True))
        self.make_report()
        _, html = self.seen("/report")
        self.assertIn("Send it now through Microsoft 365", html)
