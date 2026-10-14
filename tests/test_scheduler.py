import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from unittest import mock

from dssreport import scheduler
from dssreport.errors import InputError
from dssreport.settings import Settings
from dssreport.state import load_state

S = Settings(schedule_enabled=True, schedule_time="07:00")  # Mon-Fri by default


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm)


class Decisions(unittest.TestCase):
    # 2026-03-09 is a Monday
    def test_weekdays_only_by_default(self):
        self.assertEqual(S.schedule_weekdays, [0, 1, 2, 3, 4])
        self.assertEqual(scheduler.due_slot(dt(2026, 3, 14, 9), S), dt(2026, 3, 13, 7))  # Saturday -> Friday slot

    def test_on_time_run_is_not_late(self):
        d = scheduler.decide(dt(2026, 3, 10, 7, 5), S, {})
        self.assertTrue(d.run)
        self.assertFalse(d.late)
        self.assertEqual(d.late_note, "")

    def test_before_the_time_nothing_new_is_due(self):
        d = scheduler.decide(dt(2026, 3, 10, 6, 0), S, {"last_slot": dt(2026, 3, 9, 7).isoformat()})
        self.assertFalse(d.run)

    def test_runs_once_per_slot(self):
        state = {"last_slot": dt(2026, 3, 10, 7).isoformat()}
        self.assertFalse(scheduler.decide(dt(2026, 3, 10, 12), S, state).run)

    def test_missed_run_runs_once_on_next_start_and_is_labelled_late(self):
        # computer off Tuesday 07:00; switched on Tuesday 10:30
        state = {"last_slot": dt(2026, 3, 9, 7).isoformat()}
        d = scheduler.decide(dt(2026, 3, 10, 10, 30), S, state)
        self.assertTrue(d.run)
        self.assertTrue(d.late)
        self.assertIn("Late", d.late_note)
        self.assertIn("Tuesday 07:00", d.late_note)

    def test_several_missed_slots_still_run_only_once(self):
        state = {"last_slot": dt(2026, 3, 9, 7).isoformat()}   # off Tue..Thu, back Fri 09:00
        now = dt(2026, 3, 13, 9)
        d = scheduler.decide(now, S, state)
        self.assertTrue(d.run)
        state["last_slot"] = d.slot.isoformat()
        self.assertFalse(scheduler.decide(dt(2026, 3, 13, 9, 30), S, state).run)

    def test_weekend_start_after_missed_friday_is_late_run_once(self):
        state = {"last_slot": dt(2026, 3, 12, 7).isoformat()}
        d = scheduler.decide(dt(2026, 3, 14, 9), S, state)   # Saturday
        self.assertTrue(d.run and d.late)

    def test_off_means_off(self):
        self.assertFalse(scheduler.decide(dt(2026, 3, 10, 9), Settings(), {}).run)

    def test_report_covers_the_last_finished_day(self):
        self.assertEqual(scheduler.report_day(dt(2026, 3, 10, 7)).isoformat(), "2026-03-09")


class ScheduledRun(unittest.TestCase):
    def setUp(self):
        from . import licence_helpers as H
        self.H = H
        self.home = tempfile.mkdtemp()
        p = mock.patch.dict("os.environ", {"DSSREPORT_HOME": self.home})
        p.start()
        self.addCleanup(p.stop)
        k = H.trusted_keys()
        k.__enter__()
        self.addCleanup(lambda: k.__exit__(None, None, None))
        H.install(self.home)                 # a valid licence that includes the schedule

    def fake_runner(self, calls):
        def run(spec, out, end=None, days=1, rules_path=None, late_note="", email=False):
            calls.append(dict(spec=spec, out=out, end=end, late_note=late_note, email=email))
            rep = mock.Mock(headline="2 of 4 locations need a look.")
            return mock.Mock(report=rep, email_outcome="A draft is waiting.", all_failed=False)
        return run

    def test_run_records_state_and_log_and_passes_late_label(self):
        calls = []
        now = dt(2026, 3, 10, 10, 30)
        out = scheduler.scheduled_run(S, now, runner=self.fake_runner(calls))
        self.assertIn("need a look", out)
        self.assertEqual(calls[0]["end"].isoformat(), "2026-03-09")
        self.assertIn("Late", calls[0]["late_note"])
        self.assertEqual(load_state()["last_slot"], dt(2026, 3, 10, 7).isoformat())
        self.assertIn("(LATE)", (Path(self.home) / "run.log").read_text())
        # second wake-up the same morning does nothing
        calls.clear()
        scheduler.scheduled_run(S, dt(2026, 3, 10, 11), runner=self.fake_runner(calls))
        self.assertEqual(calls, [])

    def test_failure_is_recorded_and_retried_next_time(self):
        def boom(*a, **k):
            raise InputError("R365 refused the sign-in.")
        out = scheduler.scheduled_run(S, dt(2026, 3, 10, 7, 1), runner=boom)
        self.assertIn("could not be made", out)
        self.assertNotIn("last_slot", load_state())
        self.assertIn("refused", load_state()["last_error"])
        calls = []
        scheduler.scheduled_run(S, dt(2026, 3, 10, 7, 30), runner=self.fake_runner(calls))
        self.assertEqual(len(calls), 1)  # retried, and the later run is not labelled as a different slot


    def test_schedule_needs_the_scheduling_feature(self):
        self.H.install(self.home, features=["optional_rules"])
        calls = []
        out = scheduler.scheduled_run(S, dt(2026, 3, 10, 7, 1), runner=self.fake_runner(calls))
        self.assertIn("not included in your licence", out)
        self.assertEqual(calls, [])

    def test_all_connections_failing_is_retried_not_marked_done(self):
        def all_failed(spec, out, end=None, days=1, rules_path=None, late_note="", email=False):
            rep = mock.Mock(headline="None of the 2 connections could be reached.")
            return mock.Mock(report=rep, all_failed=True, email_outcome="")
        scheduler.scheduled_run(S, dt(2026, 3, 10, 7, 1), runner=all_failed)
        self.assertNotIn("last_slot", load_state())
        self.assertIn("last_report_dir", load_state())     # the report that says why can still be opened
        calls = []
        scheduler.scheduled_run(S, dt(2026, 3, 10, 7, 30), runner=self.fake_runner(calls))
        self.assertEqual(len(calls), 1)


class TaskXml(unittest.TestCase):
    def test_xml_is_valid_and_has_the_settings_that_matter(self):
        xml = scheduler.task_xml(S, r"C:\Py & Co\pythonw.exe", r"C:\x\launcher.pyw", r"C:\x")
        root = ET.fromstring(xml.split("?>", 1)[1])
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.find(".//t:StartWhenAvailable", ns).text, "true")
        days = [c.tag.split("}")[1] for c in root.find(".//t:DaysOfWeek", ns)]
        self.assertEqual(days, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        self.assertIsNotNone(root.find(".//t:LogonTrigger", ns))
        self.assertIn("07:00:00", root.find(".//t:StartBoundary", ns).text)
        self.assertEqual(root.find(".//t:Command", ns).text, r"C:\Py & Co\pythonw.exe")
        self.assertIn("scheduled-run", root.find(".//t:Arguments", ns).text)

    def test_install_refuses_off_windows(self):
        with mock.patch("dssreport.scheduler.sys.platform", "linux"):
            with self.assertRaises(Exception):
                scheduler.install_task(S)


if __name__ == "__main__":
    unittest.main()
