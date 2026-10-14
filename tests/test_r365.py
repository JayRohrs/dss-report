"""The R365 connector, tested ONLY against a local mock with made-up data.
Nothing here proves it works against a real R365 tenant - see docs/R365_OPEN_QUESTIONS.md."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from dssreport import credstore
from dssreport.adapters.demo import generate
from dssreport.config import Config
from dssreport.credstore import InMemoryStoreForTests
from dssreport.errors import ConfigError, InputError
from dssreport.r365 import Mapping, ODataClient, ODataSource, describe_metadata
from dssreport.report import build_report
from dssreport.settings import Instance, Settings, save_settings

from . import licence_helpers as H

from .mock_r365 import MAPPING, PASSWORD, USER, MockR365


def make(server, mapping=MAPPING, password=PASSWORD, include=()):
    inst = Instance(id="main", name="Sample Group A", base_url=server.url, username=USER)
    store = InMemoryStoreForTests()
    if password is not None:
        store.set(inst.credential_key, password)
    return inst, store, ODataSource(inst, store, include=include, mapping=Mapping(mapping))


class Fetching(unittest.TestCase):
    def test_rows_match_the_made_up_source_data_across_pages(self):
        with MockR365() as srv:
            _, _, ad = make(srv)
            ad.set_window(date(2026, 2, 28), date(2026, 3, 13))
            got = ad.load()
        want = generate()
        self.assertEqual(sorted(got, key=lambda r: (r.location, r.business_date)),
                         sorted(want, key=lambda r: (r.location, r.business_date)))
        self.assertGreater(len([r for r in srv.requests if "MockDailySales" in r[1]]), 5)  # paged

    def test_only_get_requests_are_ever_sent_and_always_signed_in(self):
        with MockR365() as srv:
            settings, store, ad = make(srv)
            ad.set_window(date(2026, 3, 13), date(2026, 3, 13))
            ad.load()
            ad.check_connection()
        self.assertTrue(srv.requests)
        self.assertEqual({m for m, _, _ in srv.requests}, {"GET"})
        self.assertTrue(all(auth for _, _, auth in srv.requests))
        self.assertTrue(all(PASSWORD not in path for _, path, _ in srv.requests))

    def test_client_has_no_way_to_write(self):
        for verb in ("post", "put", "patch", "delete", "send"):
            self.assertFalse(hasattr(ODataClient, verb))

    def test_window_and_report_end_to_end(self):
        with MockR365() as srv:
            _, _, ad = make(srv)
            ad.set_window(date(2026, 3, 13), date(2026, 3, 13))
            recs = ad.load()
        # South sent no rows at all; it is only visible because it was seen on earlier runs
        cfg = Config(unapproved_enabled=True, expected=["Demo Cafe South"])
        r = build_report(recs, cfg, end=date(2026, 3, 13), unmapped=frozenset(ad.unmapped))
        self.assertEqual([x.name for x in r.clear], ["Demo Diner West"])
        self.assertIn(("Demo Cafe South", "UNKNOWN"), [(x.name, x.status) for x in r.attention])
        self.assertIn("UNKNOWN", r.headline)

    def test_include_list_filters_locations(self):
        with MockR365() as srv:
            _, _, ad = make(srv, include=["Demo Grill East"])
            ad.set_window(date(2026, 3, 13), date(2026, 3, 13))
            self.assertEqual({r.location for r in ad.load()}, {"Demo Grill East"})

    def test_unrecognised_status_word_is_unknown_not_guessed(self):
        extra = [{"mockLocation": "Demo Extra", "mockDate": "2026-03-13", "mockSales": 10.0,
                  "mockCashOS": 0.0, "mockMissingReceipts": 0, "mockPayExceptions": 0,
                  "mockStatus": "Mystery", "mockPosIn": True,
                  **{f"mockPay_{t}": 0.0 for t in ("cash", "card", "gift_card", "delivery_app")}}]
        with MockR365(extra) as srv:
            _, _, ad = make(srv)
            ad.set_window(date(2026, 3, 13), date(2026, 3, 13))
            rec = [r for r in ad.load() if r.location == "Demo Extra"][0]
        self.assertIsNone(rec.approved)
        r = build_report([rec], Config(unapproved_enabled=True))
        self.assertEqual(r.attention[0].status, "UNKNOWN")

    def test_duplicate_rows_stop_with_a_plain_message(self):
        dup = [dict(next(r for r in __import__("tests.mock_r365", fromlist=["rows"]).rows()
                         if r["mockDate"] == "2026-03-13"))]
        with MockR365(dup) as srv:
            _, _, ad = make(srv)
            ad.set_window(date(2026, 3, 13), date(2026, 3, 13))
            with self.assertRaises(InputError) as cm:
                ad.load()
        self.assertIn("two rows", str(cm.exception))
        self.assertIn("2026-03-13", str(cm.exception))


class SafetyAndErrors(unittest.TestCase):
    def test_wrong_password_gives_plain_message_without_secrets(self):
        with MockR365() as srv:
            _, _, ad = make(srv, password="wrong-pw-777")
            ad.set_window(date(2026, 3, 13), date(2026, 3, 13))
            with self.assertRaises(InputError) as cm:
                ad.load()
        self.assertIn("refused the sign-in", str(cm.exception))
        self.assertNotIn("wrong-pw-777", str(cm.exception))

    def test_no_saved_password(self):
        with MockR365() as srv:
            _, _, ad = make(srv, password=None)
            ad.set_window(date(2026, 3, 13), date(2026, 3, 13))
            with self.assertRaises(InputError) as cm:
                ad.load()
        self.assertIn("No R365 password is saved", str(cm.exception))

    def test_redirects_are_refused(self):
        with MockR365() as srv:
            c = ODataClient(srv.url, USER, PASSWORD)
            with self.assertRaises(InputError):
                c._get(srv.url + "/redirect", "application/json")

    def test_next_link_to_another_site_is_not_followed(self):
        with MockR365() as srv:
            srv.foreign_link = "http://127.0.0.1:1/other"
            _, _, ad = make(srv)
            ad.set_window(date(2026, 2, 28), date(2026, 3, 13))
            with self.assertRaises(InputError) as cm:
                ad.load()
        self.assertIn("different website", str(cm.exception))

    def test_plain_http_is_only_allowed_on_this_computer(self):
        with self.assertRaises(InputError):
            ODataClient("http://tenant.example.com/api", USER, PASSWORD)
        with self.assertRaises(InputError):
            ODataClient("https://user:pw@tenant.example.com/api", USER, PASSWORD)

    def test_unreachable_server_message_has_no_secret(self):
        c = ODataClient("http://127.0.0.1:1/api", USER, PASSWORD, timeout=2)
        with self.assertRaises(InputError) as cm:
            c.get_metadata_xml()
        self.assertNotIn(PASSWORD, str(cm.exception))
        # Windows can time out on a closed port instead of refusing at once; both are plain, secret-free reasons
        self.assertTrue("nothing answered at that address" in str(cm.exception)
                        or "it took too long to answer" in str(cm.exception))
        self.assertNotIn("Errno", str(cm.exception))


class Mapping_(unittest.TestCase):
    def test_empty_mapping_reads_nothing_and_everything_needs_mapping(self):
        with MockR365() as srv:
            settings, store, ad = make(srv, mapping={})
            self.assertEqual(ad.load(), [])
            self.assertEqual(srv.requests, [])  # not even a request
        self.assertTrue({"approved", "cash_over_short", "payments", "sales_total"} <= ad.unmapped)
        r = build_report([], Config(include=["Demo Grill East"]), end=date(2026, 3, 13),
                         unmapped=frozenset(ad.unmapped))
        self.assertEqual(r.clear, [])
        self.assertEqual(r.attention[0].status, "UNKNOWN")
        self.assertIn("Cash over/short", r.needs_mapping)
        self.assertNotIn("Nothing to review", r.headline)

    def test_partial_mapping_skips_only_what_is_unmapped(self):
        partial = {"source": MAPPING["source"], "fields": {"cash_over_short": "mockCashOS"}}
        with MockR365() as srv:
            _, _, ad = make(srv, mapping=partial)
            ad.set_window(date(2026, 3, 13), date(2026, 3, 13))
            recs = ad.load()
        self.assertNotIn("cash_over_short", ad.unmapped)
        self.assertIn("approved", ad.unmapped)
        r = build_report(recs, Config(unapproved_enabled=True), end=date(2026, 3, 13),
                         unmapped=frozenset(ad.unmapped))
        self.assertIn("Approval", r.needs_mapping)
        self.assertIn("Grill East", " ".join(x.name for x in r.attention))

    def test_shipped_template_is_empty_and_loads(self):
        m = Mapping.load(Path(__file__).resolve().parent.parent / "r365_mapping.example.toml")
        self.assertFalse(m.can_fetch)
        self.assertTrue({"approved", "pos_import_received"} <= m.unmapped())

    def test_missing_mapping_file_means_nothing_mapped(self):
        self.assertFalse(Mapping.load(Path(tempfile.mkdtemp()) / "none.toml").can_fetch)

    def test_typos_are_errors(self):
        with self.assertRaises(ConfigError):
            Mapping({"fields": {"cash_ovr_short": "x"}})
        with self.assertRaises(ConfigError):
            Mapping({"source": {"date_literal": "epoch"}})


class DiscoverAndTest(unittest.TestCase):
    def test_discover_lists_entities_and_properties(self):
        with MockR365() as srv:
            _, _, ad = make(srv)
            lines = ad.describe()
        self.assertIn("MockDailySales", lines)
        self.assertTrue(any("mockLocation" in x for x in lines))

    def test_describe_bad_xml(self):
        with self.assertRaises(InputError):
            describe_metadata(b"<not xml")

    def test_check_connection(self):
        with MockR365() as srv:
            _, _, ad = make(srv)
            self.assertIn("Connected", ad.check_connection())


class CredentialStores(unittest.TestCase):
    def test_secret_tool_gets_secret_on_stdin_not_in_arguments(self):
        calls = []

        def fake_run(args, input=None, capture_output=False):
            calls.append((args, input))
            return mock.Mock(returncode=0, stdout=b"")

        with mock.patch("dssreport.credstore.subprocess.run", fake_run):
            credstore.SecretToolStore("secret-tool").set("r365:x", "s3cret-value")
        args, stdin = calls[0]
        self.assertEqual(stdin, b"s3cret-value")
        self.assertNotIn("s3cret-value", " ".join(args))

    def test_no_secure_store_means_refuse_not_fall_back_to_a_file(self):
        with mock.patch("dssreport.credstore.sys.platform", "darwin"):
            with self.assertRaises(credstore.CredentialStoreError):
                credstore.default_store()

    def test_redact(self):
        self.assertEqual(credstore.redact("bad pw-1 here", "pw-1", None), "bad *** here")


class CommandLine(unittest.TestCase):
    def _run_cli(self, home, srv, include=None):
        from dssreport.cli import main
        from dssreport.settings import save_settings
        out = tempfile.mkdtemp()
        mapping = Path(home) / "r365_mapping.toml"
        mapping.write_text("""
[source]
entity = "MockDailySales"
location = "mockLocation"
business_date = "mockDate"
[fields]
cash_over_short = "mockCashOS"
""")
        if include:
            from dssreport.config import Config, dump_rules
            (Path(home) / "rules.toml").write_text(dump_rules(Config(include=include)))
        inst = Instance(id="main", name="Sample Group A", base_url=srv.url, username=USER,
                        mapping_file="r365_mapping.toml")
        save_settings(Settings(instances=[inst]))
        H.install(home)
        store = InMemoryStoreForTests()
        store.set(inst.credential_key, PASSWORD)
        with H.trusted_keys(), mock.patch("dssreport.runner.default_store", lambda: store):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main(["run", "--input", "r365", "--out", out, "--date", "2026-03-13", "--full"])
        self.assertEqual(code, 0)
        return (Path(out) / "email.txt").read_text()

    def test_silent_location_is_not_remembered_or_listed_unless_the_user_lists_it(self):
        from dssreport.state import load_state, save_state
        home = tempfile.mkdtemp()
        with mock.patch.dict("os.environ", {"DSSREPORT_HOME": home}):
            # earlier runs saw the cafe; that must NOT make it "expected" now
            save_state({"seen_by_instance": {"main": ["Demo Cafe South", "Demo Closed Years Ago"]}})
            with MockR365() as srv:
                text = self._run_cli(home, srv)
            self.assertNotIn("Demo Cafe South", text)
            self.assertNotIn("Demo Closed Years Ago", text)
            self.assertIn("sent nothing at all is not listed", text)       # said out loud, in the report
            # seen list grows (for the show/hide toggles only)
            self.assertIn("Demo Diner West", load_state()["seen_by_instance"]["main"])

    def test_silent_location_shows_unknown_when_listed_under_only_these_locations(self):
        home = tempfile.mkdtemp()
        with mock.patch.dict("os.environ", {"DSSREPORT_HOME": home}):
            with MockR365() as srv:
                text = self._run_cli(home, srv, include=["Demo Cafe South", "Demo Grill East"])
        self.assertIn("Demo Cafe South [UNKNOWN]", text)
        self.assertIn("No data for this day", text)
        self.assertNotIn("Demo Diner West", text)
        self.assertNotIn("sent nothing at all is not listed", text)

    def test_rows_with_blank_required_values_show_unknown(self):
        extra = [{"mockLocation": "Demo Blanks", "mockDate": "2026-03-13", "mockSales": 10.0,
                  "mockCashOS": None, "mockMissingReceipts": 0, "mockPayExceptions": 0,
                  "mockStatus": "Done", "mockPosIn": True,
                  **{f"mockPay_{t}": 0.0 for t in ("cash", "card", "gift_card", "delivery_app")}}]
        home = tempfile.mkdtemp()
        with mock.patch.dict("os.environ", {"DSSREPORT_HOME": home}):
            with MockR365(extra) as srv:
                text = self._run_cli(home, srv)
        self.assertIn("Demo Blanks [UNKNOWN]", text)

    def test_cli_r365_run_with_everything_unmapped(self):
        from dssreport.cli import main
        home = tempfile.mkdtemp()
        out = tempfile.mkdtemp()
        with mock.patch.dict("os.environ", {"DSSREPORT_HOME": home}):
            with MockR365() as srv:
                inst = Instance(id="main", name="Sample Group A", base_url=srv.url, username=USER)
                save_settings(Settings(instances=[inst]))
                H.install(home)
                store = InMemoryStoreForTests()
                store.set(inst.credential_key, PASSWORD)
                with H.trusted_keys(), mock.patch("dssreport.runner.default_store", lambda: store):
                    o, e = io.StringIO(), io.StringIO()
                    with redirect_stdout(o), redirect_stderr(e):
                        code = main(["run", "--input", "r365", "--out", out, "--date", "2026-03-13", "--full"])
        self.assertEqual(code, 0, e.getvalue())
        html = (Path(out) / "report.html").read_text()
        self.assertIn("needs mapping", html.lower())
        self.assertIn("UNKNOWN", html)
        self.assertNotIn(PASSWORD, html + o.getvalue() + e.getvalue())


if __name__ == "__main__":
    unittest.main()
