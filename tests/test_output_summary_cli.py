import json
import re
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from pathlib import Path

from dssreport import summary
from dssreport.cli import main
from dssreport.config import Config
from dssreport.render import render_html, render_text
from dssreport.report import build_report

from .helpers import demo_report, rec


def run_cli(*args):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


class Outputs(unittest.TestCase):
    def test_html_is_self_contained_and_readable(self):
        html = render_html(demo_report(date(2026, 3, 13)))
        self.assertNotRegex(html, r"(src|href)=[\"']https?:")
        self.assertNotIn("<script", html)
        self.assertNotIn("@import", html)
        self.assertIn('name="viewport"', html)
        sizes = re.findall(r"font(?:-size)?:\s*([\d.]+)(px|rem)", html)
        self.assertTrue(sizes)
        for value, unit in sizes:
            px = float(value) * (16 if unit == "rem" else 1)
            self.assertGreaterEqual(px, 16, f"font size {value}{unit} is too small")

    def test_html_escapes_names(self):
        r = build_report([rec(location="<b>Evil</b> & Co", approved=False)], Config())
        html = render_html(r)
        self.assertNotIn("<b>Evil</b>", html)
        self.assertIn("&lt;b&gt;Evil&lt;/b&gt; &amp; Co", html)

    def test_unknown_shown_in_both_outputs_and_never_all_clean(self):
        r = demo_report(date(2026, 3, 13))  # South has no row
        for text in (render_html(r), render_text(r)):
            self.assertIn("UNKNOWN", text)
            self.assertIn("No data for this day", text)
            self.assertNotIn("all clean", text.lower())
        # South must not be listed under "Nothing to review"
        text = render_text(r)
        self.assertNotIn("Demo Cafe South", text.split("NOTHING TO REVIEW")[1])

    def test_email_text_is_plain(self):
        text = render_text(demo_report(date(2026, 3, 13)))
        self.assertTrue(text.startswith("Subject: "))
        self.assertNotIn("<", text)
        self.assertTrue(all(len(line) <= 80 for line in text.splitlines()))


class SummaryChecks(unittest.TestCase):
    def setUp(self):
        self.report = demo_report(date(2026, 3, 13))  # North + East need a look, South is UNKNOWN, West is fine

    def test_template_sentence_agrees_with_itself(self):
        self.assertTrue(summary.sentence_agrees(summary.standard_sentence(self.report), self.report))

    def test_good_model_sentence_is_used(self):
        s = "3 of 4 locations need a look: Demo Bistro North, Demo Grill East and Demo Cafe South, and one is UNKNOWN because data is missing."
        self.assertTrue(summary.sentence_agrees(s, self.report))

    def test_disagreeing_sentences_are_rejected(self):
        names = "Demo Bistro North, Demo Grill East and Demo Cafe South"
        for s in ["All 4 locations are clean today.",
                  "Everything is fine, no issues at all.",
                  "2 of 4 locations need a look: Demo Bistro North and Demo Grill East.",
                  f"3 of 4 locations need a look: {names}, and 5 receipts are missing (UNKNOWN data).",
                  f"3 of 4 locations need a look: {names}, and Demo Diner West (UNKNOWN data).",
                  "Three locations need a look.",
                  ""]:
            self.assertFalse(summary.sentence_agrees(s, self.report), s)

    def test_unknown_must_be_mentioned(self):
        names = "Demo Bistro North, Demo Grill East and Demo Cafe South"
        # South has no data: a sentence that doesn't say data is missing is rejected
        self.assertFalse(summary.sentence_agrees(f"3 of 4 locations need a look: {names}.", self.report))
        self.assertTrue(summary.sentence_agrees(
            f"3 of 4 locations need a look: {names}; Demo Cafe South has no data (UNKNOWN).", self.report))

    def test_add_summary_uses_model_when_it_agrees(self):
        good = "3 of 4 locations need a look: Demo Bistro North, Demo Grill East and Demo Cafe South, and one is UNKNOWN because data is missing."
        note = summary.add_summary(self.report, Config(), ask=lambda p, c: good)
        self.assertEqual((self.report.summary_source, self.report.summary_sentence, note), ("model", good, ""))

    def test_add_summary_discards_wrong_sentence(self):
        note = summary.add_summary(self.report, Config(), ask=lambda p, c: "All 4 locations are clean.")
        self.assertEqual(self.report.summary_source, "template")
        self.assertEqual(self.report.summary_sentence, summary.standard_sentence(self.report))
        self.assertIn("discarded", note)

    def test_add_summary_falls_back_when_model_is_down(self):
        def down(p, c):
            raise OSError("connection refused")
        note = summary.add_summary(self.report, Config(), ask=down)
        self.assertEqual(self.report.summary_source, "template")
        self.assertIn("could not be used", note)

    def test_non_local_endpoint_is_refused(self):
        cfg = Config(ai_endpoint="http://example.com:11434")
        with self.assertRaises(ValueError):
            summary.ask_model("hi", cfg)
        note = summary.add_summary(self.report, cfg)
        self.assertEqual(self.report.summary_source, "template")
        self.assertIn("this computer", note)

    def test_real_http_round_trip_to_a_local_stub(self):
        reply = {"text": "3 of 4 locations need a look: Demo Bistro North, Demo Grill East and Demo Cafe South, and one is UNKNOWN because data is missing."}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert self.path == "/api/generate" and body["stream"] is False
                data = json.dumps({"response": reply["text"]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            cfg = Config(ai_enabled=True, ai_endpoint=f"http://127.0.0.1:{server.server_port}", ai_timeout=5)
            self.assertEqual(summary.add_summary(self.report, cfg), "")
            self.assertEqual(self.report.summary_source, "model")
            reply["text"] = "Nothing to worry about."
            report2 = demo_report(date(2026, 3, 13))
            summary.add_summary(report2, cfg)
            self.assertEqual(report2.summary_source, "template")
        finally:
            server.shutdown()
            server.server_close()


class CommandLine(unittest.TestCase):
    def test_demo_run_writes_both_files_without_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_cli("run", "--input", "demo", "--out", tmp)
            self.assertEqual(code, 0, err)
            self.assertIn("3 of 4 locations need a look", out)
            html = (Path(tmp) / "report.html").read_text()
            self.assertTrue((Path(tmp) / "email.txt").exists())
            self.assertNotIn("local model", html)  # AI is off by default

    def test_bad_input_is_a_plain_message_not_a_traceback(self):
        code, out, err = run_cli("run", "--input", "/no/such/file.csv", "--out", "/tmp/x-unused")
        self.assertEqual(code, 2)
        self.assertIn("Problem:", err)

    def test_days_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run_cli("run", "--input", "demo", "--out", tmp, "--days", "14")
            self.assertEqual(code, 0)
            self.assertIn("UNKNOWN", out)


if __name__ == "__main__":
    unittest.main()
