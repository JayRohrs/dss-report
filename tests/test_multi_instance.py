"""Several R365 connections in one report, the licence limit, and what a lapsed licence does.
Tested only against local mock servers with made-up data."""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from dssreport import licence as L
from dssreport.credstore import InMemoryStoreForTests
from dssreport.errors import ConfigError, InputError
from dssreport.render import render_html, render_text
from dssreport.report import MultiReport, Report
from dssreport.runner import run_report
from dssreport.settings import Instance, Settings, save_settings
from dssreport.state import load_state

from . import licence_helpers as H
from .mock_r365 import MAPPING, PASSWORD, USER, MockR365, alt_rows, mapping_toml

DAY = date(2026, 3, 13)


class Env(unittest.TestCase):
    """A private program folder, a throw-away licence key and an in-memory credential store."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict("os.environ", {"DSSREPORT_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        k = H.trusted_keys()
        k.__enter__()
        self.addCleanup(lambda: k.__exit__(None, None, None))
        self.store = InMemoryStoreForTests()
        d = mock.patch("dssreport.runner.default_store", lambda: self.store)
        d.start()
        self.addCleanup(d.stop)
        self.instances = []

    def licence(self, **kw):
        H.install(self.home, **kw)

    def add(self, name, url, mapping=MAPPING, password=PASSWORD, **kw):
        inst = Instance(id=name.lower().replace(" ", "-"), name=name, base_url=url, username=USER, **kw)
        (self.home / "mappings").mkdir(exist_ok=True)
        inst.mapping_path.write_text(mapping_toml(mapping))
        if password is not None:
            self.store.set(inst.credential_key, password)
        self.instances.append(inst)
        save_settings(Settings(instances=self.instances))
        return inst

    def do_run(self, **kw):
        out = self.home / "out" / str(len(list((self.home / "out").glob("*"))) if (self.home / "out").exists() else 0)
        kw.setdefault("end", DAY)
        return run_report("r365", out, **kw)


class TwoInstances(Env):
    def test_report_covers_both_grouped_by_instance(self):
        self.licence(instances=2)
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            self.add("Sample Group A", a.url)
            self.add("Sample Group B", b.url)
            res = self.do_run()
        r = res.report
        self.assertIsInstance(r, MultiReport)
        self.assertEqual([s.name for s in r.sections], ["Sample Group A", "Sample Group B"])
        self.assertEqual(r.failed_sections, [])
        # same shapes, different names. The cafe sent no row at all, so (by the owner's rule) it is not
        # listed; the blank cash figure is still UNKNOWN inside the location that needs a look.
        for s in r.sections:
            self.assertEqual(len(s.report.attention), 2)
            self.assertEqual(len(s.report.clear), 1)
        self.assertIn("4 of 6 locations need a look", r.headline)
        self.assertIn("across 2 connections", r.headline)
        html = res.html_path.read_text(encoding="utf-8")
        self.assertLess(html.index("Sample Group A"), html.index("Demo Bistro North"))
        self.assertLess(html.index("Demo Bistro North"), html.index("Sample Group B"))
        self.assertLess(html.index("Sample Group B"), html.index("Sample Pier Grill"))
        text = res.text_path.read_text(encoding="utf-8")
        self.assertIn("SAMPLE GROUP B", text)
        self.assertIn("Sample Pier Grill [NEEDS REVIEW]", text)
        self.assertIn("UNKNOWN: Cash over/short is blank", text)    # blank required values stay UNKNOWN
        self.assertNotIn(PASSWORD, html + text)

    def test_each_connection_uses_its_own_credential_and_mapping(self):
        self.licence(instances=2)
        partial = {"source": MAPPING["source"], "fields": {"cash_over_short": "mockCashOS"}}
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            ia = self.add("Sample Group A", a.url)
            ib = self.add("Sample Group B", b.url, mapping=partial, password="b-has-its-own-password")
            # B's server only accepts the shared mock password, so give it that, but keep the keys distinct
            self.store.set(ib.credential_key, PASSWORD)
            res = self.do_run()
        self.assertNotEqual(ia.credential_key, ib.credential_key)
        by = {s.name: s.report for s in res.report.sections}
        self.assertEqual(by["Sample Group A"].needs_mapping, [])
        self.assertIn("Approval", by["Sample Group B"].needs_mapping)       # only B has an unfinished mapping

    def test_hidden_locations_and_only_these_are_per_connection(self):
        self.licence(instances=2)
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            self.add("Sample Group A", a.url, hidden=["Demo Grill East"])
            self.add("Sample Group B", b.url, include=["Sample Dock Cafe", "Sample Never Sent Cafe"])
            res = self.do_run()
        by = {s.name: s.report for s in res.report.sections}
        a_names = [x.name for x in by["Sample Group A"].attention + by["Sample Group A"].clear]
        self.assertNotIn("Demo Grill East", a_names)
        self.assertEqual(len(a_names), 2)
        b_names = {x.name: x.status for x in by["Sample Group B"].attention + by["Sample Group B"].clear}
        self.assertEqual(set(b_names), {"Sample Dock Cafe", "Sample Never Sent Cafe"})
        self.assertEqual(b_names["Sample Never Sent Cafe"], "UNKNOWN")

    def test_seen_locations_are_kept_per_connection(self):
        self.licence(instances=2)
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            ia = self.add("Sample Group A", a.url)
            ib = self.add("Sample Group B", b.url)
            self.do_run()
        seen = load_state()["seen_by_instance"]
        self.assertIn("Demo Diner West", seen[ia.id])
        self.assertNotIn("Sample Park Diner", seen[ia.id])
        self.assertIn("Sample Park Diner", seen[ib.id])

    def test_one_connection_that_worked_keeps_the_familiar_layout(self):
        self.licence(instances=2)
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            res = self.do_run()
        self.assertIsInstance(res.report, Report)
        self.assertIn("2 of 3 locations need a look", res.report.headline)


class OneFailing(Env):
    def test_failing_connection_is_shown_at_the_top_and_the_other_is_not_hidden(self):
        self.licence(instances=2)
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            self.add("Sample Group B", "http://127.0.0.1:1/api/mock")          # nothing is listening
            res = self.do_run()
        r = res.report
        self.assertEqual([s.name for s in r.failed_sections], ["Sample Group B"])
        self.assertTrue(r.failed_sections[0].error.startswith("could not connect: Could not reach R365"))
        self.assertEqual(len(r.ok_sections[0].report.attention), 2)         # A still fully reported
        html, text = res.html_path.read_text(encoding="utf-8"), res.text_path.read_text(encoding="utf-8")
        self.assertIn("Sample Group B: could not connect:", html)
        self.assertLess(html.index("could not connect"), html.index("Demo Bistro North"))   # at the top
        self.assertIn("1 connection could not be reached", r.headline)
        self.assertIn("could not connect", text.split("SAMPLE GROUP A")[0])
        self.assertIn("1 connection could not connect", text.splitlines()[0])
        for t in (html, text):
            self.assertNotIn("Nothing to review: all", t)
            self.assertNotIn(PASSWORD, t)

    def test_wrong_password_is_a_plain_reason_for_that_connection_only(self):
        self.licence(instances=2)
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            self.add("Sample Group A", a.url)
            self.add("Sample Group B", b.url, password="wrong-secret-123")
            res = self.do_run()
        failed = res.report.failed_sections[0]
        self.assertIn("refused the sign-in", failed.error)
        self.assertNotIn("wrong-secret-123", res.html_path.read_text(encoding="utf-8") + res.text_path.read_text(encoding="utf-8"))
        self.assertEqual(len(res.report.ok_sections), 1)

    def test_a_data_problem_in_one_connection_is_labelled_as_such(self):
        self.licence(instances=2)
        dup = [r for r in alt_rows() if r["mockDate"] == "2026-03-13"][:1]
        with MockR365() as a, MockR365(rows_override=alt_rows() + dup) as b:       # a duplicate row
            self.add("Sample Group A", a.url)
            self.add("Sample Group B", b.url)
            res = self.do_run()
        self.assertTrue(res.report.failed_sections[0].error.startswith("could not read its data:"))
        self.assertIn("two rows", res.report.failed_sections[0].error)

    def test_all_failing_is_unknown_and_still_produces_a_report(self):
        self.licence(instances=2)
        self.add("Sample Group A", "http://127.0.0.1:1/a")
        self.add("Sample Group B", "http://127.0.0.1:1/b")
        res = self.do_run()
        self.assertTrue(res.all_failed)
        self.assertIn("None of the 2 connections could be reached", res.report.headline)
        self.assertIn("UNKNOWN", res.report.headline)
        self.assertIn("Subject:", res.text_path.read_text(encoding="utf-8"))

    def test_no_connection_set_up_is_a_plain_error(self):
        self.licence()
        with self.assertRaises(InputError):
            self.do_run()


class LicenceAtRunTime(Env):
    def test_connections_beyond_the_limit_are_not_connected_and_say_so(self):
        self.licence(instances=1)
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            self.add("Sample Group A", a.url)
            self.add("Sample Group B", b.url)
            res = self.do_run()
        self.assertEqual([s.name for s in res.report.ok_sections], ["Sample Group A"])
        err = res.report.failed_sections[0].error
        self.assertTrue(err.startswith("not connected: Licence: over limit"))
        self.assertEqual(b.requests, [])                       # the second server was never contacted

    def test_missing_licence_connects_nothing_but_the_report_is_still_made_and_says_why(self):
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            res = self.do_run()
        self.assertTrue(res.all_failed)
        self.assertEqual(a.requests, [])
        html = res.html_path.read_text(encoding="utf-8")
        self.assertIn("Licence: not found", html)
        self.assertIn("not connected", html)

    def test_expired_licence_keeps_existing_connections_working_and_says_expired(self):
        self.licence(instances=1, expires=date(2020, 1, 1))
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            res = self.do_run()
        self.assertIsInstance(res.report, Report)                # it connected and reported
        self.assertEqual(len(res.report.attention), 2)
        html, text = res.html_path.read_text(encoding="utf-8"), res.text_path.read_text(encoding="utf-8")
        for t in (html, text):
            self.assertIn("Licence: expired on 2020-01-01", t)

    def test_lapsed_licence_never_touches_reports_already_made(self):
        self.licence(instances=1)
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            first = self.do_run()
        saved = first.html_path.read_text(encoding="utf-8")
        (self.home / "licence.json").unlink()                    # licence disappears
        with MockR365() as a:
            self.instances[0].base_url = a.url
            save_settings(Settings(instances=self.instances))
            self.do_run()
        self.assertEqual(first.html_path.read_text(encoding="utf-8"), saved)     # the earlier report is exactly as it was
        self.assertTrue(first.html_path.exists())

    def test_valid_licence_shows_a_quiet_footer_line_not_a_warning(self):
        self.licence(instances=1)
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            res = self.do_run()
        html = res.html_path.read_text(encoding="utf-8")
        self.assertIn("Licence: valid for Sample Customer Ltd", html)
        self.assertNotIn('class="warn">Licence:', html)

    def test_demo_data_needs_no_licence(self):
        res = run_report("demo", self.home / "out-demo")        # no licence installed at all
        self.assertIn("3 of 4 locations need a look", res.report.headline)
        self.assertIn("demo mode", res.html_path.read_text(encoding="utf-8"))


class FeatureFlags(Env):
    def test_optional_rule_runs_only_with_the_flag(self):
        (self.home / "rules.toml").write_text("[rules.payments_total]\nenabled = true\ntolerance = 0.01\n")
        with MockR365() as a:
            self.licence(instances=1, features=["scheduling"])               # no optional_rules
            self.add("Sample Group A", a.url)
            off = self.do_run(days=14)
            self.licence(instances=1, features=["optional_rules"])
            on = self.do_run(days=14)
        self.assertIn("Payments add up to sales: NOT IN YOUR LICENCE (not checked)", off.report.rules_note)
        self.assertNotIn("Payments add up", " ".join(f.text for r in off.report.attention for f in r.findings))
        self.assertIn("Payments add up to", " ".join(f.text for r in on.report.attention for f in r.findings))

    def test_demo_mode_has_the_optional_rule_available(self):
        (self.home / "rules.toml").write_text("[rules.payments_total]\nenabled = true\ntolerance = 0.01\n")
        res = run_report("demo", self.home / "o", days=14)
        self.assertIn("Payments add up to", " ".join(f.text for r in res.report.attention for f in r.findings))

    def test_local_ai_sentence_needs_its_flag(self):
        self.licence(instances=1, features=["optional_rules"])
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            res = self.do_run(ai=True)
        self.assertEqual(res.report.summary_sentence, "")
        self.assertTrue(any("Summary sentence from a local model is not included" in n for n in res.notes))

    def test_email_needs_its_flag_and_the_report_is_still_saved(self):
        save_settings(Settings(email_enabled=True, email_to="person@example.invalid"))
        self.licence(instances=1, features=["scheduling"])
        res = run_report("demo", self.home / "o", email=True)
        self.assertIn("The email was NOT created", res.email_outcome)
        self.assertIn("Email through Microsoft 365 is not included", res.email_outcome)
        self.assertTrue(res.html_path.exists())

    def test_every_current_feature_is_in_the_base_licence_and_future_ones_are_not(self):
        with H.trusted_keys():
            lic = L.verify_licence(H.make())
        self.assertEqual(lic.features, frozenset(L.CURRENT_FEATURES))
        self.assertNotIn(L.F_HOSTED, lic.features)


class FakeSecondSource(Env):
    """Swapping the connector: a different kind of source goes through the same rules, report and
    email with no change to any of them."""

    def test_a_new_kind_of_source_plugs_in_without_touching_anything_else(self):
        from datetime import date as d
        from decimal import Decimal
        from dssreport import sources
        from dssreport.model import DayRecord

        @sources.register_source
        class FakeNewApi(sources.DataSource):
            kind = "fake-new-api"
            name = "Fake new API (test only)"
            mapping_formats = frozenset({2})

            def __init__(self, instance, store, include=()):
                super().__init__(instance, store, include)
                self.unmapped = set()

            def set_window(self, start, end):
                self.window = (start, end)

            def load(self):
                return [DayRecord("Sample New Place", d(2026, 3, 13), Decimal("100"), {"cash": Decimal("100")},
                                  Decimal("-9.00"), 0, 0, False, True)]

            def check_connection(self):
                return "Fake connected."

            def describe(self):
                return ["FakeEntity"]

        self.addCleanup(lambda: sources.SOURCE_KINDS.pop("fake-new-api", None))
        self.licence(instances=1)
        self.add("Sample Group A", "https://odata.example.com/a", source_kind="fake-new-api")
        res = self.do_run()
        names = [r.name for r in res.report.attention]
        self.assertEqual(names, ["Sample New Place"])
        texts = [f.text for f in res.report.attention[0].findings]
        self.assertIn("Cash is $9.00 short (limit $5.00)", texts)
        self.assertIn("Entry is not approved", texts)           # the same rules, unchanged
        self.assertIn("Sample New Place", res.text_path.read_text(encoding="utf-8"))

    def test_unknown_source_kind_is_a_plain_settings_error(self):
        with self.assertRaises(ConfigError) as cm:
            save_settings(Settings(instances=[Instance(id="a", name="A", source_kind="no-such-kind")]))
        self.assertIn("does not know the data source", str(cm.exception))


class MappingVersion(Env):
    def test_template_and_new_mappings_carry_a_version(self):
        from dssreport.r365 import Mapping
        m = Mapping.load(H.ROOT / "r365_mapping.example.toml")
        self.assertEqual(m.version, 1)

    def test_old_files_without_a_version_are_format_1(self):
        from dssreport.r365 import Mapping
        self.assertEqual(Mapping(MAPPING).version, 1)

    def test_a_connector_refuses_a_mapping_in_a_format_it_does_not_read(self):
        from dssreport.r365 import Mapping, ODataSource
        inst = Instance(id="a", name="A", base_url="https://odata.example.com/a", username=USER)
        with self.assertRaises(ConfigError) as cm:
            ODataSource(inst, self.store, mapping=Mapping({"version": 2, **MAPPING}))
        self.assertIn("is format 2, but this connector reads format 1", str(cm.exception))

    def test_bad_version_values(self):
        from dssreport.r365 import Mapping
        for bad in ("one", True, 1.5):
            with self.assertRaises(ConfigError):
                Mapping({"version": bad})

    def test_a_mapping_problem_in_one_instance_does_not_hide_the_other(self):
        self.licence(instances=2)
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            self.add("Sample Group A", a.url)
            ib = self.add("Sample Group B", b.url)
            ib.mapping_path.write_text("version = 7\n" + mapping_toml(MAPPING))
            res = self.do_run()
        self.assertEqual(len(res.report.ok_sections), 1)
        self.assertIn("format 7", res.report.failed_sections[0].error)


class LegacySingleConnection(Env):
    def test_phase_2_settings_are_carried_over_with_the_same_password_and_mapping(self):
        import json
        (self.home).mkdir(exist_ok=True)
        (self.home / "settings.json").write_text(json.dumps({
            "r365_enabled": True, "r365_base_url": "https://odata.example.com/old", "r365_username": USER}))
        from dssreport.settings import load_settings
        s = load_settings()
        inst = s.instances[0]
        self.assertEqual((inst.name, inst.enabled, inst.base_url), ("Restaurant365", True, "https://odata.example.com/old"))
        self.assertEqual(inst.credential_key, f"r365:{USER}")
        self.assertEqual(inst.mapping_path, self.home / "r365_mapping.toml")


if __name__ == "__main__":
    unittest.main()


class RenewalNoticeInReports(Env):
    def test_notice_is_at_the_top_of_the_report_and_the_email_from_30_days_out(self):
        from datetime import timedelta
        self.licence(instances=1, expires=date.today() + timedelta(days=9))
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            res = self.do_run()
        html, text = res.html_path.read_text(encoding="utf-8"), res.text_path.read_text(encoding="utf-8")
        note = "Licence expires in 9 days"
        self.assertIn(note, html)
        self.assertIn(note, text)
        self.assertLess(html.index(note), html.index("Needs a look"))
        self.assertLess(text.index(note), text.index("NEEDS A LOOK"))

    def test_no_notice_far_from_expiry(self):
        from datetime import timedelta
        self.licence(instances=1, expires=date.today() + timedelta(days=90))
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            res = self.do_run()
        self.assertNotIn("Licence expires in", res.html_path.read_text(encoding="utf-8"))

    def test_expired_notice_is_at_the_top_and_the_report_is_still_made_in_full(self):
        self.licence(instances=1, expires=date(2020, 1, 1))
        with MockR365() as a:
            self.add("Sample Group A", a.url)
            res = self.do_run()
        note = "Licence expired on 2020-01-01 — renew to add connections or get updates."
        html, text = res.html_path.read_text(encoding="utf-8"), res.text_path.read_text(encoding="utf-8")
        self.assertIn(note, html)
        self.assertLess(html.index(note), html.index("Needs a look"))
        self.assertIn(note, text)
        self.assertEqual(len(res.report.attention), 2)                  # nothing about the report was cut

    def test_notice_also_tops_a_two_connection_report(self):
        from datetime import timedelta
        self.licence(instances=2, expires=date.today() + timedelta(days=5))
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            self.add("Sample Group A", a.url)
            self.add("Sample Group B", b.url)
            res = self.do_run()
        html = res.html_path.read_text(encoding="utf-8")
        self.assertLess(html.index("Licence expires in 5 days"), html.index("Sample Group A</h2>"))


class UnlimitedAtRunTime(Env):
    def test_unlimited_connects_every_configured_connection(self):
        self.licence(instances="unlimited")
        servers = [MockR365(rows_override=alt_rows()) for _ in range(3)]
        try:
            for s in servers:
                s.thread.start()
            for i, s in enumerate(servers):
                self.add(f"Sample Group {i}", s.url)
            res = self.do_run()
        finally:
            for s in servers:
                s.shutdown()
                s.server_close()
        self.assertEqual(len(res.report.ok_sections), 3)
        self.assertEqual(res.report.failed_sections, [])

    def test_terms_change_with_the_file_alone(self):
        """Same program, different licence file: connections and flags change, nothing else does."""
        with MockR365() as a, MockR365(rows_override=alt_rows()) as b:
            self.add("Sample Group A", a.url)
            self.add("Sample Group B", b.url)
            self.licence(instances=1, features=[])
            one = self.do_run()
            self.licence(instances="unlimited", features=["optional_rules"])
            many = self.do_run()
        self.assertEqual(len(one.report.ok_sections), 1)
        self.assertEqual(len(many.report.ok_sections), 2)
