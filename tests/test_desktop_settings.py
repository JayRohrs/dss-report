"""Everything optional is OFF by default; the settings file round-trips; bad values are refused."""

import dataclasses
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from dssreport.desktop import cli, daily
from dssreport.desktop import settings as st
from dssreport.errors import ConfigError


class Defaults(unittest.TestCase):
    def test_every_optional_thing_is_off_and_nothing_is_filled_in(self):
        d = st.DesktopSettings()
        for f in dataclasses.fields(d):
            if f.type is bool:
                self.assertIs(getattr(d, f.name), False, f.name)
        self.assertFalse(d.daily_run_enabled)
        self.assertFalse(d.draft_email_enabled)
        self.assertFalse(d.open_report_after_run)
        self.assertEqual((d.draft_to, d.graph_client_id), ("", ""))
        self.assertEqual(d.source, "demo")       # made-up data until the owner chooses otherwise

    def test_no_file_means_defaults(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(st.load(Path(t) / "none.json"), st.DesktopSettings())

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "s.json"
            s = st.DesktopSettings(run_time="06:15", source="demo")
            st.save(s, p)
            self.assertEqual(st.load(p), s)

    def test_draft_needs_an_address_and_app_id_before_it_can_be_on(self):
        with self.assertRaises(ConfigError):
            st.validate(st.DesktopSettings(draft_email_enabled=True))
        with self.assertRaises(ConfigError):
            st.validate(st.DesktopSettings(draft_email_enabled=True, draft_to="a@example.invalid"))
        st.validate(st.DesktopSettings(draft_email_enabled=True, draft_to="a@example.invalid",
                                       graph_client_id="FAKE-APP-ID"))

    def test_bad_values_refused(self):
        for bad in (dict(run_time="7am"), dict(draft_to="not an address"), dict(source=" "),
                    dict(graph_client_id="bad id!"), dict(graph_tenant="")):
            with self.assertRaises(ConfigError, msg=str(bad)):
                st.validate(st.DesktopSettings(**bad))

    def test_unreadable_file_gives_plain_error(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "s.json"
            p.write_text("{nope")
            with self.assertRaises(ConfigError):
                st.load(p)


class SwitchesAndLog(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patcher = mock.patch.dict(os.environ, {"DSSREPORT_HOME": self.home.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_first_run_with_defaults_does_nothing_but_log_that_it_is_off(self):
        calls = []
        code = daily.daily_run(st.DesktopSettings(), now=datetime(2026, 11, 4, 7, 0),
                               runner=lambda *a, **k: calls.append(1))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("switched off", daily.log_file().read_text())

    def test_draft_off_by_default_means_no_mailer_is_even_built(self):
        class R:
            class report:
                headline = "All made-up"
            all_failed = False
            html_path = Path(self.home.name) / "r.html"
            text_path = Path(self.home.name) / "r.txt"

        def runner(*a, **k):
            return R

        def no_mailer(_):
            raise AssertionError("mailer must not be built when drafts are off")

        s = st.DesktopSettings(daily_run_enabled=True)
        self.assertEqual(daily.daily_run(s, now=datetime(2026, 11, 4, 7), runner=runner, mailer_factory=no_mailer), 0)
        self.assertIn("no draft requested", daily.log_file().read_text())

    def test_status_and_set_commands(self):
        self.assertEqual(cli.main(["status"]), 0)
        self.assertEqual(cli.main(["set", "run_time", "06:45"]), 0)
        self.assertEqual(st.load().run_time, "06:45")
        self.assertEqual(cli.main(["set", "nonsense", "x"]), 2)
        self.assertEqual(cli.main(["set", "daily_run_enabled", "true"]), 2)   # on/off only via schedule/draft

    def test_draft_off_command_and_demo_run_end_to_end(self):
        self.assertEqual(cli.main(["draft", "off"]), 0)
        self.assertFalse(st.load().draft_email_enabled)
        self.assertEqual(cli.main(["run-now"]), 0)       # real demo data, real runner
        self.assertIn("ran for", daily.log_file().read_text())
        self.assertTrue(any(Path(self.home.name, "reports").rglob("report.html")))

    def test_scheduled_run_does_not_repeat_for_the_same_day(self):
        s = st.DesktopSettings(daily_run_enabled=True)
        now = datetime(2026, 11, 4, 7)
        self.assertEqual(daily.daily_run(s, now=now), 0)
        self.assertEqual(daily.daily_run(s, now=now), 0)
        self.assertIn("already made", daily.log_file().read_text())

    def test_schedule_commands_need_the_packaged_program(self):
        self.assertEqual(cli.main(["schedule", "on"]), 2)     # running from source, not the exe
        self.assertFalse(st.load().daily_run_enabled)


if __name__ == "__main__":
    unittest.main()
