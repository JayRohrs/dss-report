"""Task Scheduler command construction (built as text; Windows is not needed to test it)."""

import unittest

from dssreport.desktop import taskcmd
from dssreport.errors import DssError

EXE = r"C:\Users\Pat Owner\AppData\Local\DssReport\dss-report.exe"   # made-up path, with a space


class CreateCommand(unittest.TestCase):
    def test_exact_arguments(self):
        self.assertEqual(taskcmd.create_command(EXE, "07:30"), [
            "schtasks", "/Create", "/TN", "DSS Report Daily", "/SC", "DAILY", "/ST", "07:30",
            "/TR", f'"{EXE}" daily-run', "/RL", "LIMITED", "/F"])

    def test_runs_without_admin_rights(self):
        cmd = taskcmd.create_command(EXE, "07:00")
        self.assertEqual(cmd[cmd.index("/RL") + 1], "LIMITED")
        self.assertNotIn("HIGHEST", cmd)
        self.assertNotIn("/RU", cmd)          # runs as the signed-in user, no stored password

    def test_program_with_spaces_is_quoted(self):
        cmd = taskcmd.create_command(EXE, "07:00")
        self.assertTrue(cmd[cmd.index("/TR") + 1].startswith('"C:\\Users\\Pat Owner'))

    def test_one_line_form_is_pasteable(self):
        line = taskcmd.one_line(taskcmd.create_command(EXE, "07:00"))
        self.assertTrue(line.startswith('schtasks /Create /TN "DSS Report Daily" /SC DAILY /ST 07:00 /TR '))
        self.assertIn("daily-run", line)

    def test_bad_times_are_refused(self):
        for bad in ("7:00", "24:00", "07:60", "", "07:00; calc", "07:00 /RU SYSTEM"):
            with self.assertRaises(DssError, msg=bad):
                taskcmd.create_command(EXE, bad)

    def test_quote_in_path_is_refused(self):
        with self.assertRaises(DssError):
            taskcmd.create_command('C:\\x" & calc & "', "07:00")

    def test_delete_and_query(self):
        self.assertEqual(taskcmd.delete_command(), ["schtasks", "/Delete", "/TN", "DSS Report Daily", "/F"])
        self.assertEqual(taskcmd.query_command(), ["schtasks", "/Query", "/TN", "DSS Report Daily"])

    def test_not_windows_gives_a_plain_message(self):
        import sys
        if sys.platform != "win32":
            with self.assertRaises(DssError):
                taskcmd.install(EXE, "07:00")


if __name__ == "__main__":
    unittest.main()
