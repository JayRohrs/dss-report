"""`export inspect`: a description of a DSS list that is safe to paste (no names, no amounts). Made-up data only."""

import io
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

from dssreport import dss_export_sample as S
from dssreport.cli import main
from dssreport.dss_inspect import inspect


class Inspect(unittest.TestCase):
    def test_classic_and_beta_are_described_by_shape_only(self):
        classic = inspect(S.csv_bytes("classic", date(2026, 3, 14)), "x.csv")
        self.assertIn("Heading row is on line 1.", classic)
        self.assertIn("ApprovalStatus,Status,Location,LocationNumber", classic)
        self.assertIn("Approval Status <- 'ApprovalStatus'", classic)
        self.assertIn("(agrees with the 55 rows)", classic)
        self.assertIn("Other status-like columns present: Status", classic)
        self.assertIn("'Unapproved' x1", classic)
        beta = inspect(S.csv_bytes("beta", date(2026, 3, 14)), "y.csv")
        self.assertIn("Byte-order mark: yes", beta)
        self.assertIn("carries no row count", beta)
        self.assertIn("'In Progress' x2", beta)

    def test_nothing_private_is_printed(self):
        for kind in ("classic", "beta"):
            text = inspect(S.csv_bytes(kind, date(2026, 3, 14)), "x.csv")
            for name in ("Sample Pier Grill", "Sample Hill Bistro", "Sample Dock Cafe", "Sample Park Diner"):
                self.assertNotIn(name, text)
            self.assertNotIn("23.5", text)                                  # no amount from the file
            self.assertNotIn("3000", text)
            self.assertNotRegex(text, r"\d{4}-\d\d-\d\dT")                    # no stamps from the file
            self.assertIsNone(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", text))   # no record ids

    def test_it_says_when_a_file_is_not_a_dss_list_and_when_counts_disagree(self):
        self.assertIn("does not look like a DSS list", inspect(b"a,b\r\n1,2\r\n", "z.csv"))
        data = S.csv_bytes("classic", date(2026, 3, 14)).replace(b",55,", b",250,")
        self.assertIn("DOES NOT agree", inspect(data, "x.csv"))

    def test_the_command_reads_a_file_and_never_changes_it(self):
        d = Path(tempfile.mkdtemp())
        f = d / "a.csv"
        f.write_bytes(S.csv_bytes("classic", date(2026, 3, 14)))
        before = f.read_bytes()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["export", "inspect", str(f)]), 0)
        self.assertIn("Headings (23)", out.getvalue())
        self.assertEqual(f.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()


class Packaging(unittest.TestCase):
    def test_the_wording_and_heading_files_travel_with_installs_and_signed_updates(self):
        import sys
        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root / "tools"))
        try:
            import update_tool
            names = {str(f if not isinstance(f, tuple) else f[0]) for f in update_tool.collect(root)}
        finally:
            sys.path.pop(0)
        for needed in ("dssreport/data/reason_terms.toml", "dssreport/data/dss_export_aliases.toml",
                       "dssreport/brief.py", "dssreport/dss_inspect.py"):
            self.assertIn(needed, names)
        installer = (root / "install-windows.cmd").read_text(encoding="utf-8")
        self.assertIn('robocopy "%SRC%dssreport"', installer)         # the whole program folder, data files included
