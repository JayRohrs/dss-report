"""DSS export source end to end: report, rules, several connections, licence, settings screen, safety.
Made-up data only. Nothing here touches a network or a credential store."""

import builtins
import html as htmllib
import io
import json
import os
import re
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from dssreport import dss_export as E
from dssreport import dss_export_sample as S
from dssreport import dss_export_source as X
from dssreport.cli import main
from dssreport.credstore import InMemoryStoreForTests
from dssreport.errors import InputError
from dssreport.report import MultiReport, Report
from dssreport.runner import run_report
from dssreport.settings import Instance, Settings, load_settings, save_settings
from dssreport.settings_server import SettingsApp, SettingsServer

from . import licence_helpers as H

NOW = datetime.now()
TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def inst(name="Sample Group A", **kw):
    return Instance(id=name.lower().replace(" ", "-"), name=name, source_kind="dss-export", **kw)


class Env(unittest.TestCase):
    instances_allowed = 2

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict("os.environ", {"DSSREPORT_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        k = H.trusted_keys()
        k.__enter__()
        self.addCleanup(lambda: k.__exit__(None, None, None))
        if self.instances_allowed is not None:
            H.install(self.home, instances=self.instances_allowed)
        # an export-only run must never touch the credential store
        def boom():
            raise AssertionError("the credential store was used")
        d = mock.patch("dssreport.runner.default_store", boom)
        d.start()
        self.addCleanup(d.stop)

    def connect(self, *instances):
        save_settings(Settings(instances=list(instances)))

    def give(self, instance, data=None, name="sample-dss-classic.csv", mtime=None, today=None):
        data = data if data is not None else S.csv_bytes("classic", today or TODAY)
        X.store_export(instance, name, data, (mtime if mtime is not None else NOW.timestamp()))

    def run_it(self, **kw):
        out = self.home / "out" / str(len(list((self.home / "out").glob("*"))) if (self.home / "out").exists() else 0)
        return run_report("r365", out, **kw)


class EndToEnd(Env):
    def test_report_from_a_fresh_file_uses_the_existing_rules_and_sections(self):
        a = inst()
        self.connect(a)
        self.give(a)
        res = self.run_it()
        r = res.report
        self.assertIsInstance(r, Report)
        by = {x.name: x for x in r.attention}
        hill = [f.text for f in by["Sample Hill Bistro"].findings]
        self.assertIn("Entry is not approved", hill)
        self.assertIn("Over/Short is -$23.50 as R365 gives it (limit $5.00 either way)", hill)
        self.assertFalse(any(t.startswith("Cash is") for t in hill))   # no claim about direction
        self.assertEqual(sorted(x.name for x in r.clear), ["Sample Dock Cafe", "Sample Pier Grill"])
        diner = [f.text for f in by["Sample Park Diner"].findings]
        self.assertEqual(diner, ["No data for this day"])                         # a missing day is UNKNOWN
        self.assertNotIn("Nothing to review: all", r.headline)

    def test_source_line_and_warnings_are_in_the_report_and_the_email_text(self):
        a = inst()
        self.connect(a)
        self.give(a)
        res = self.run_it()
        html, text = res.html_path.read_text(encoding="utf-8"), res.text_path.read_text(encoding="utf-8")
        pattern = r'Source: DSS export file "sample-dss-classic\.csv", dated \d{4}-\d\d-\d\d \d\d:\d\d, read \d{4}-\d\d-\d\d \d\d:\d\d\.'
        for t in (html, text):
            self.assertRegex(t.replace("&quot;", '"').replace("\n  ", " "), pattern)
            self.assertIn("POS import", t)
            self.assertIn("does not contain what they need", t.replace("\n  ", " "))
        self.assertIn("NOT IN THE EXPORT FILE (not checked)", html)
        self.assertNotIn("needs mapping", html.lower())           # the file source never says "needs mapping"
        self.assertLess(html.index("Source: DSS export file"), html.index("Needs a look"))
        self.assertLess(text.index("Source: DSS export file"), text.index("NEEDS A LOOK"))

    def test_never_calls_the_credential_store_or_the_network(self):
        a = inst()
        self.connect(a)
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network used")), \
                mock.patch("socket.getaddrinfo", side_effect=AssertionError("network used")):
            self.give(a)
            self.run_it()

    def test_a_file_older_than_today_cannot_show_approval_and_the_report_says_so_plainly(self):
        a = inst()
        self.connect(a)
        self.give(a, mtime=(NOW - timedelta(days=1, hours=2)).timestamp())
        res = self.run_it()
        html, text = res.html_path.read_text(encoding="utf-8"), res.text_path.read_text(encoding="utf-8")
        old = (NOW - timedelta(days=1, hours=2)).date().isoformat()
        for t in (html, text):
            flat = re.sub(r"\s+", " ", htmllib.unescape(t))
            self.assertIn(f"This file is dated {old}. A file older than today cannot establish today's approval status", flat)
            self.assertNotIn("Entry is not approved", flat)           # not claimed from a stale file
        self.assertIn("Over/Short is -$23.50 as R365 gives it", html)  # over/short is still checked
        self.assertNotIn("Entry is not approved", html)
        by = {x.name: x for x in res.report.attention}
        self.assertEqual(by["Sample Pier Grill"].status, "UNKNOWN")    # even the "Approved" row is not trusted

    def test_a_file_chosen_without_its_own_date_is_treated_as_unproven(self):
        a = inst()
        self.connect(a)
        X.store_export(a, "x.csv", S.csv_bytes("classic", TODAY), None)
        res = self.run_it()
        self.assertIn("does not say when it was downloaded", res.html_path.read_text(encoding="utf-8"))
        self.assertIn("date not known", res.html_path.read_text(encoding="utf-8"))

    def test_two_connections_keep_their_own_file_proof_and_freshness(self):
        a, b = inst("Sample Group A"), inst("Sample Group B")
        self.connect(a, b)
        self.give(a, name="group-a.csv")
        self.give(b, name="group-b.xlsx", data=S.xlsx_bytes(S.table("beta", TODAY)), mtime=(NOW - timedelta(days=3)).timestamp())
        res = self.run_it()
        self.assertIsInstance(res.report, MultiReport)
        html = res.html_path.read_text(encoding="utf-8").replace("&quot;", '"')
        sec_a = html.split("Sample Group A</h2>")[1].split("Sample Group B</h2>")[0]
        sec_b = html.split("Sample Group B</h2>")[1]
        self.assertIn('"group-a.csv"', sec_a)
        self.assertNotIn("group-b.xlsx", sec_a)
        self.assertNotIn("older than today", sec_a)                    # A is fresh
        self.assertIn('"group-b.xlsx"', sec_b)
        self.assertIn("older than today", sec_b)                       # only B is stale
        self.assertIn("Entry is not approved", sec_a)
        self.assertNotIn("Entry is not approved", sec_b)

    def test_no_file_chosen_yet_is_a_plain_reason_for_that_connection_only(self):
        a, b = inst("Sample Group A"), inst("Sample Group B")
        self.connect(a, b)
        self.give(a)
        res = self.run_it()
        failed = res.report.failed_sections[0]
        self.assertEqual(failed.name, "Sample Group B")
        self.assertTrue(failed.error.startswith("could not read its data: No DSS export file has been chosen"))
        self.assertEqual(len(res.report.ok_sections), 1)

    def test_missing_columns_show_as_not_checked(self):
        a = inst()
        self.connect(a)
        data = f"Location,Date,Approval Status\r\nSample Pier Grill,{YESTERDAY:%m/%d/%Y},Approved\r\n".encode()
        self.give(a, data=data)
        res = self.run_it()
        self.assertIn("Cash over/short", res.report.needs_mapping)
        self.assertIn("This file has no Over/Short column", res.html_path.read_text(encoding="utf-8"))

    def test_the_owner_s_word_meaning_applies_to_that_connection_only(self):
        a, b = inst("Sample Group A", approval_words={"In Progress": "not approved"}), inst("Sample Group B")
        self.connect(a, b)
        beta = S.csv_bytes("beta", TODAY)
        self.give(a, data=beta)
        self.give(b, data=beta)
        res = self.run_it()
        by = {s.name: {x.name: x for x in s.report.attention} for s in res.report.ok_sections}
        a_dock = [f.text for f in by["Sample Group A"]["Sample Dock Cafe"].findings]
        b_dock = [f.text for f in by["Sample Group B"]["Sample Dock Cafe"].findings]
        self.assertIn("Entry is not approved", a_dock)
        self.assertFalse(any("Entry is not approved" == t for t in b_dock))
        self.assertTrue(any("'In Progress'" in t for t in b_dock))

    def test_conflicting_rows_show_up_as_a_conflict_in_the_report(self):
        a = inst()
        self.connect(a)
        d = f"{YESTERDAY:%m/%d/%Y}"
        data = ("Approval Status,Location,Date,Over/Short\r\n"
                f"Approved,Sample Pier Grill,{d},1.00\r\nUnapproved,Sample Pier Grill,{d},1.00\r\n").encode()
        self.give(a, data=data)
        res = self.run_it()
        text = re.sub(r"\s+", " ", res.text_path.read_text(encoding="utf-8"))
        self.assertIn("Conflict: two or more rows for this day disagree on approval status", text)
        self.assertIn("[UNKNOWN]", text)


class LicenceLimit(Env):
    instances_allowed = 1

    def test_the_second_export_connection_is_not_read_when_the_licence_allows_one(self):
        a, b = inst("Sample Group A"), inst("Sample Group B")
        self.connect(a, b)
        self.give(a)
        self.give(b)
        res = self.run_it()
        self.assertEqual([s.name for s in res.report.ok_sections], ["Sample Group A"])
        self.assertTrue(res.report.failed_sections[0].error.startswith("not connected: Licence: over limit"))


class Safety(Env):
    def test_the_source_file_is_never_written_or_changed(self):
        a = inst()
        self.connect(a)
        src_dir = Path(tempfile.mkdtemp())
        src = src_dir / "my-export.xlsx"
        src.write_bytes(S.xlsx_bytes(S.table("classic", TODAY)))
        before = (src.read_bytes(), src.stat().st_mtime_ns, sorted(os.listdir(src_dir)))
        opened = []
        real = builtins.open

        def spy(file, mode="r", *args, **kw):
            opened.append((str(file), mode))
            return real(file, mode, *args, **kw)
        with mock.patch("builtins.open", spy), mock.patch("io.open", spy):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["export", "load", str(src)]), 0)
        self.assertEqual((src.read_bytes(), src.stat().st_mtime_ns, sorted(os.listdir(src_dir))), before)
        for path, mode in opened:
            if Path(path).resolve() == src.resolve():
                self.assertFalse(set(mode) & set("wax+"), f"source opened with mode {mode}")
        self.assertTrue((self.home / "exports" / a.id / "meta.json").exists())          # the COPY is ours

    def test_the_copy_keeps_the_real_file_date_so_freshness_can_be_judged(self):
        a = inst()
        self.connect(a)
        src = Path(tempfile.mkdtemp()) / "old.csv"
        src.write_bytes(S.csv_bytes("classic", TODAY))
        old = (NOW - timedelta(days=2)).timestamp()
        os.utime(src, (old, old))
        with redirect_stdout(io.StringIO()):
            main(["export", "load", str(src), "--instance", "Sample Group A"])
        meta = X.stored_info(a.id)
        self.assertTrue(meta["file_mtime"].startswith((NOW - timedelta(days=2)).date().isoformat()))

    def test_row_contents_are_never_printed_or_logged(self):
        a = inst()
        self.connect(a)
        src = Path(tempfile.mkdtemp()) / "x.csv"
        src.write_bytes(S.csv_bytes("classic", TODAY))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            main(["export", "load", str(src)])
            main(["run", "--input", "r365", "--out", str(self.home / "o")])
        shown = out.getvalue() + err.getvalue()
        for secret in ("Sample Hill Bistro", "Sample Pier Grill", "23.50", "Sample User", "Unapproved"):
            self.assertNotIn(secret, shown)
        from dssreport import scheduler
        from dssreport.settings import Settings as S2
        s = load_settings()
        s.schedule_enabled = True
        scheduler.scheduled_run(s, datetime.now().replace(hour=23, minute=59))
        log = (self.home / "run.log").read_text() if (self.home / "run.log").exists() else ""
        for secret in ("Sample Hill Bistro", "23.50", "Unapproved", "Sample Dock Cafe"):
            self.assertNotIn(secret, log)

    def test_unusable_files_are_refused_before_a_copy_is_kept_and_the_old_copy_survives(self):
        a = inst()
        self.connect(a)
        self.give(a, name="good.csv")
        good = (self.home / "exports" / a.id / "current.csv").read_bytes()
        for name, data in (("bad.xlsm", b"x"), ("old.xls", b"x"), ("notes.pdf", b"x"), ("empty.csv", b""),
                           ("garbage.csv", b"hello\nthere\n"), ("fake.xlsx", b"not a zip")):
            with self.assertRaises(InputError, msg=name):
                X.store_export(a, name, data, NOW.timestamp())
        self.assertEqual((self.home / "exports" / a.id / "current.csv").read_bytes(), good)
        self.assertEqual(X.stored_info(a.id)["original_name"], "good.csv")

    def test_file_names_are_cleaned_before_they_are_shown_or_kept(self):
        self.assertEqual(X.safe_name("..\\..\\evil<script>.csv"), "evil_script_.csv")
        self.assertEqual(X.safe_name("C:/Users/me/My Export (1).xlsx"), "My Export (1).xlsx")
        self.assertEqual(X.safe_name(""), "export")

    def test_modules_have_no_network_credential_or_process_code(self):
        root = Path(__file__).resolve().parent.parent / "dssreport"
        for name in ("dss_export.py", "dss_export_source.py", "dss_export_sample.py"):
            code = (root / name).read_text()
            for bad in ("urllib", "socket", "http.client", "credstore", "subprocess", "os.system", "eval(", "exec(",
                        "webbrowser", "playwright", "selenium", "pickle", "marshal"):
                self.assertNotIn(bad, re.sub(r'""".*?"""', "", code, flags=re.S), f"{name} mentions {bad}")

    def test_the_source_declares_it_needs_no_credentials(self):
        self.assertFalse(X.DssExportSource.needs_credentials)
        a = inst()
        self.connect(a)
        self.give(a)
        self.assertEqual(len(X.DssExportSource(a, None).load()), 55)


class Cli(Env):
    def test_demo_export_writes_the_sample_files(self):
        out = self.home / "samples"
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["demo-export", "--out", str(out)]), 0)
        self.assertEqual(len(list(out.iterdir())), 5)
        self.assertIn("Check DSS export now", buf.getvalue())

    def test_export_load_without_a_connection_is_a_plain_message(self):
        err = io.StringIO()
        src = self.home / "x.csv"
        src.write_bytes(S.csv_bytes("classic", TODAY))
        with redirect_stderr(err):
            self.assertEqual(main(["export", "load", str(src)]), 2)
        self.assertIn("There is no DSS export connection", err.getvalue())

    def test_the_whole_demo_path_works_from_the_command_line(self):
        a = inst()
        self.connect(a)
        out = self.home / "samples"
        with redirect_stdout(io.StringIO()):
            main(["demo-export", "--out", str(out)])
            main(["export", "load", str(out / "sample-dss-beta-style.xlsx")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["run", "--input", "r365", "--out", str(self.home / "r")]), 0)
        self.assertIn("3 of 4 locations need a look", buf.getvalue())
        self.assertIn("2 locations are UNKNOWN because data is missing", buf.getvalue())


class UpdatePackagesCarryTheAliasFile(unittest.TestCase):
    def test_update_packages_include_the_heading_list(self):
        import sys
        sys.path.insert(0, str(H.ROOT / "tools"))
        import update_tool
        self.assertIn("dssreport/data/dss_export_aliases.toml", update_tool.collect(H.ROOT))


# ---------------------------------------------------------------------------------------- the settings screen

class Screen(Env):
    def setUp(self):
        super().setUp()
        self.store = InMemoryStoreForTests()
        self.app = SettingsApp(self.store)
        self.server = SettingsServer(self.app)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.port = self.server.server_port

    def get(self, path=None):
        url = f"http://127.0.0.1:{self.port}" + (path if path is not None else f"/?t={self.server.token}")
        with urllib.request.urlopen(url) as r:
            return r.status, htmllib.unescape(r.read().decode()), r.headers

    def post(self, path, fields=None, token=None, **kw):
        data = {"t": self.server.token if token is None else token}
        data.update(fields or {})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=urllib.parse.urlencode(data, doseq=True).encode())
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, htmllib.unescape(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, htmllib.unescape(e.read().decode())

    def upload(self, instance_id, name, data, mtime_ms="", token=None):
        b = "----expb"
        body = b"".join([
            f'--{b}\r\nContent-Disposition: form-data; name="t"\r\n\r\n{token or self.server.token}\r\n'.encode(),
            f'--{b}\r\nContent-Disposition: form-data; name="inst"\r\n\r\n{instance_id}\r\n'.encode(),
            f'--{b}\r\nContent-Disposition: form-data; name="file_mtime"\r\n\r\n{mtime_ms}\r\n'.encode(),
            f'--{b}\r\nContent-Disposition: form-data; name="export"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(),
            data, f"\r\n--{b}--\r\n".encode()])
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/export", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, htmllib.unescape(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, htmllib.unescape(e.read().decode("utf-8"))

    def fresh_ms(self):
        return str(int(datetime.now().timestamp() * 1000))

    def test_the_how_this_works_note_the_section_and_the_source_choices(self):
        a = inst()
        self.connect(a)
        _, html, _ = self.get()
        self.assertIn("3. Check a DSS export", html)
        self.assertIn("This is read-only", html)
        self.assertIn("you download the Daily Sales Summary list from R365 yourself", html)
        self.assertIn("Excel icon at the top right with nothing ticked", html)
        self.assertIn("Nothing is changed in R365", html)
        self.assertIn("Check DSS export now", html)
        self.assertIn("R365 DSS export file (carries approval status and cash over/short)", html)
        self.assertIn("optional - does not provide approval or over/short; unproven against a live tenant", html)
        self.assertRegex(html, r'name="inst_kind_0"')

    def test_with_no_export_connection_the_section_says_how_to_add_one(self):
        _, html, _ = self.get()
        self.assertIn("No connection uses the DSS export yet", html)
        self.assertNotIn("<script", html)
        self.assertNotIn('name="export"', html)

    def test_the_export_form_posts_to_this_computer_only_and_runs_one_small_script_with_a_nonce(self):
        self.connect(inst())
        _, html, headers = self.get()
        self.assertEqual(html.count("<script"), 1)
        nonce = re.search(r'<script nonce="([^"]+)"', html).group(1)
        self.assertIn(f"script-src 'nonce-{nonce}'", headers["Content-Security-Policy"])
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertNotRegex(html, r"<script[^>]+src=")                 # no outside script, ever

    def test_choosing_a_file_checks_it_and_shows_the_report_with_nothing_emailed(self):
        a = inst()
        self.connect(a)
        status, page = self.upload(a.id, "my list.csv", S.csv_bytes("classic", TODAY), self.fresh_ms())
        self.assertEqual(status, 200)
        self.assertIn("Checked my list.csv (55 rows).", page)
        self.assertIn("Nothing has been emailed", page)
        self.assertIn("Entry is not approved", page)
        self.assertIn('Source: DSS export file "my list.csv"', page.replace("&quot;", '"'))
        self.assertEqual(X.stored_info(a.id)["original_name"], "my list.csv")
        _, settings_page, _ = self.get()
        self.assertIn("Last file: my list.csv", settings_page)

    def test_the_file_s_own_date_from_the_browser_decides_freshness(self):
        a = inst()
        self.connect(a)
        old_ms = str(int((datetime.now() - timedelta(days=2)).timestamp() * 1000))
        _, page = self.upload(a.id, "old.csv", S.csv_bytes("classic", TODAY), old_ms)
        self.assertIn("older than today cannot establish today's approval status", page)
        _, page = self.upload(a.id, "nodate.csv", S.csv_bytes("classic", TODAY), "")            # script blocked/unavailable
        self.assertIn("does not say when it was downloaded", page)
        _, page = self.upload(a.id, "junk.csv", S.csv_bytes("classic", TODAY), "not-a-number")
        self.assertIn("does not say when it was downloaded", page)

    def test_refusals_are_plain_and_a_bad_file_does_not_replace_a_good_one(self):
        a = inst()
        self.connect(a)
        self.upload(a.id, "good.csv", S.csv_bytes("classic", TODAY), self.fresh_ms())
        for name, data, needle in (("macro.xlsm", b"x", "Macro-enabled"), ("old.xls", b"x", "Old-style .xls"),
                                   ("notes.pdf", b"x", "ending in .xlsx"), ("junk.csv", b"hello\nworld\n", "does not look like an R365")):
            status, page = self.upload(a.id, name, data, self.fresh_ms())
            self.assertIn(needle, page, name)
        self.assertEqual(X.stored_info(a.id)["original_name"], "good.csv")
        self.assertIn("Choose the DSS export file first", self.upload_empty(a.id))

    def upload_empty(self, instance_id):
        b = "xb"
        body = (f'--{b}\r\nContent-Disposition: form-data; name="t"\r\n\r\n{self.server.token}\r\n'
                f'--{b}\r\nContent-Disposition: form-data; name="inst"\r\n\r\n{instance_id}\r\n--{b}--\r\n').encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/export", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        with urllib.request.urlopen(req) as r:
            return htmllib.unescape(r.read().decode())

    def test_oversize_files_are_refused(self):
        a = inst()
        self.connect(a)
        with mock.patch.object(E, "MAX_FILE_BYTES", 200):
            status, page = self.upload(a.id, "big.csv", S.csv_bytes("classic", TODAY), self.fresh_ms())
        self.assertIn("far bigger", page)

    def test_it_needs_the_token_a_real_connection_that_is_on_and_a_licence(self):
        a = inst()
        self.connect(a)
        self.assertEqual(self.upload(a.id, "x.csv", S.csv_bytes("classic", TODAY), token="wrong")[0], 403)
        _, page = self.upload("nope", "x.csv", S.csv_bytes("classic", TODAY))
        self.assertIn("That is not a DSS export connection", page)
        self.connect(inst(enabled=False))
        _, page = self.upload(a.id, "x.csv", S.csv_bytes("classic", TODAY))
        self.assertIn("Tick \"Connect\" for this connection and save first", page)
        odata = Instance(id="odata-one", name="Sample OData", base_url="https://odata.example.com/a", username="D\\u")
        self.connect(a, odata)
        _, page = self.upload("odata-one", "x.csv", S.csv_bytes("classic", TODAY))
        self.assertIn("That is not a DSS export connection", page)
        (self.home / "licence.json").unlink()
        _, page = self.upload(a.id, "x.csv", S.csv_bytes("classic", TODAY))
        self.assertIn("Licence: not found", page)

    def test_status_word_meanings_can_be_set_per_connection_and_bad_ones_are_refused(self):
        a = inst()
        self.connect(a)
        form = {"inst_id_0": a.id, "inst_name_0": a.name, "inst_enabled_0": "1", "inst_kind_0": "dss-export",
                "payments_tolerance": "0.01", "cash_limit": "5.00", "receipts_allowed": "0", "exceptions_allowed": "0",
                "rule_pos": "1", "rule_cash": "1", "rule_receipts": "1", "rule_exceptions": "1", "rule_unapproved": "1",
                "schedule_time": "07:00", "wd0": "1", "ai_endpoint": "http://localhost:11434", "ai_model": "m",
                "action": "save"}
        _, page = self.post("/", {**form, "inst_words_0": "In Progress = not approved\nCompleted = approved"})
        self.assertIn("Settings saved.", page)
        self.assertEqual(load_settings().instances[0].approval_words, {"In Progress": "not approved", "Completed": "approved"})
        self.assertIn("In Progress = not approved", self.get()[1])
        _, page = self.post("/", {**form, "inst_words_0": "Approved = not approved"})
        self.assertIn("cannot be changed", page)
        _, page = self.post("/", {**form, "inst_words_0": "In Progress = maybe"})
        self.assertIn("must mean 'approved' or 'not approved'", page)
        _, page = self.post("/", {**form, "inst_words_0": "no equals sign"})
        self.assertIn("In Progress = not approved", page)
        self.assertEqual(load_settings().instances[0].approval_words, {"In Progress": "not approved", "Completed": "approved"})
        _, page = self.post("/", {**form, "inst_words_0": ""})
        self.assertEqual(load_settings().instances[0].approval_words, {})               # off again

    def test_a_new_connection_defaults_to_the_export_and_needs_no_address_or_password(self):
        _, page = self.post("/", {"payments_tolerance": "0.01", "cash_limit": "5.00", "receipts_allowed": "0",
                                  "exceptions_allowed": "0", "schedule_time": "07:00", "wd0": "1", "rule_pos": "1",
                                  "ai_endpoint": "http://localhost:11434", "ai_model": "m", "action": "save",
                                  "new_name": "Sample Group A", "new_kind": "dss-export"})
        self.assertIn("Connection 'Sample Group A' added. Choose a DSS export file for it", page)
        i = load_settings().instances[0]
        self.assertEqual((i.source_kind, i.base_url, i.username), ("dss-export", "", ""))
        self.assertEqual(self.store.items, {})

    def test_a_connection_can_be_switched_between_sources(self):
        a = inst()
        self.connect(a)
        form = {"inst_id_0": a.id, "inst_name_0": a.name, "inst_enabled_0": "1", "inst_kind_0": "odata",
                "inst_url_0": "https://odata.example.com/a", "inst_user_0": "D\\u", "payments_tolerance": "0.01",
                "cash_limit": "5.00", "receipts_allowed": "0", "exceptions_allowed": "0", "schedule_time": "07:00",
                "wd0": "1", "ai_endpoint": "http://localhost:11434", "ai_model": "m", "action": "save"}
        _, page = self.post("/", form)
        self.assertIn("Settings saved.", page)
        self.assertEqual(load_settings().instances[0].source_kind, "odata")
        self.assertIn("Field mapping file (private", self.get()[1])


if __name__ == "__main__":
    unittest.main()
