"""The draft email step can create a draft and attach a file. It has no way to send, and these tests
fail if one is ever added."""

import ast
import base64
import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from dssreport.credstore import InMemoryStoreForTests
from dssreport.desktop import daily, draftmail
from dssreport.desktop import settings as st
from dssreport.desktop.draftmail import SCOPES, DraftError, DraftMailer, check_allowed

from .mock_graph import CLIENT_ID, MockGraph

SRC = Path(draftmail.__file__).resolve().parent
CODE_PATH_FILES = [SRC / "draftmail.py", SRC / "daily.py"]
SEND_WORDS = re.compile(r"send|deliver|forward|reply|transmit", re.I)


def code_tokens(path: Path):
    """Every identifier, attribute and string in the file EXCEPT docstrings (which may say 'never sends')."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.arg)):
            out.append(getattr(node, "name", None) or node.arg)
        elif isinstance(node, ast.alias):
            out.append(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            out.append(node.value)
    return out


class NoSendInTheCode(unittest.TestCase):
    def test_no_send_like_word_anywhere_in_the_code_path(self):
        for path in CODE_PATH_FILES:
            bad = [t for t in code_tokens(path) if SEND_WORDS.search(t)]
            self.assertEqual(bad, [], f"{path.name} contains send-like code: {bad}")

    def test_the_old_client_that_can_send_is_not_imported_by_the_code_path(self):
        for path in CODE_PATH_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"from \.\.graph|import graph|GraphClient")
        # cli.py uses it only for the sign-in screen and asks for the draft permission only
        cli_text = (SRC / "cli.py").read_text(encoding="utf-8")
        self.assertIn("sign_in_scopes()", cli_text)

    def test_only_draft_permission_is_ever_requested(self):
        self.assertEqual(sorted(SCOPES), ["Mail.ReadWrite", "offline_access"])
        self.assertEqual(sorted(draftmail.sign_in_scopes()), ["Mail.ReadWrite", "offline_access"])
        self.assertNotIn("Mail.Send", " ".join(code_tokens(SRC / "draftmail.py")))

    def test_allow_list_accepts_only_token_draft_and_attachment(self):
        check_allowed("POST", "https://login.microsoftonline.com/organizations/oauth2/v2.0/token")
        check_allowed("POST", "https://graph.microsoft.com/v1.0/me/messages")
        check_allowed("POST", "https://graph.microsoft.com/v1.0/me/messages/AAA%3D/attachments")
        for method, url in [
            ("POST", "https://graph.microsoft.com/v1.0/me/messages/AAA/send"),
            ("POST", "https://graph.microsoft.com/v1.0/me/sendMail"),
            ("POST", "https://graph.microsoft.com/v1.0/me/messages/AAA/forward"),
            ("POST", "https://graph.microsoft.com/v1.0/me/messages/AAA/reply"),
            ("PATCH", "https://graph.microsoft.com/v1.0/me/messages/AAA"),
            ("GET", "https://graph.microsoft.com/v1.0/me/messages"),
        ]:
            with self.assertRaises(DraftError, msg=url):
                check_allowed(method, url)


def signed_in_store():
    store = InMemoryStoreForTests()
    store.set(draftmail.SESSION_KEY, json.dumps({"refresh_token": "refresh-1", "scope": SCOPES}))
    return store


class DraftAgainstMock(unittest.TestCase):
    def test_creates_a_draft_with_the_report_attached_and_sends_nothing(self):
        with MockGraph() as srv:
            m = DraftMailer(signed_in_store(), CLIENT_ID, authority=srv.base, graph=srv.base + "/v1.0")
            mid = m.create_draft("owner@example.invalid", "Report (draft)", "Body", "r.html", b"<p>made-up</p>")
            self.assertEqual(srv.sent, [])
            self.assertEqual(list(srv.drafts), [mid])
            self.assertEqual(srv.drafts[mid]["message"]["toRecipients"][0]["emailAddress"]["address"],
                             "owner@example.invalid")
            att = srv.drafts[mid]["attachments"][0]
            self.assertEqual(att["name"], "r.html")
            self.assertEqual(base64.b64decode(att["contentBytes"]), b"<p>made-up</p>")
            paths = [p for _, p, _, _ in srv.log]
            for p in paths:
                self.assertFalse(re.search(r"send|forward|reply", p, re.I), p)
            self.assertEqual(sorted(set(paths)), sorted({"/organizations/oauth2/v2.0/token", "/v1.0/me/messages",
                                                         f"/v1.0/me/messages/{mid}/attachments"}))
            scopes_asked = [b for _, p, _, b in srv.log if p.endswith("/token")][0]
            self.assertNotIn("Mail.Send", scopes_asked)

    def test_not_signed_in_is_a_plain_error_and_makes_no_calls(self):
        with MockGraph() as srv:
            m = DraftMailer(InMemoryStoreForTests(), CLIENT_ID, authority=srv.base, graph=srv.base + "/v1.0")
            with self.assertRaises(DraftError):
                m.create_draft("a@example.invalid", "s", "b", "r.html", b"x")
            self.assertEqual(srv.log, [])

    def test_oversize_report_is_refused(self):
        m = DraftMailer(signed_in_store(), CLIENT_ID, authority="https://example.invalid",
                        graph="https://example.invalid/v1.0", http=lambda *a: self.fail("no call expected"))
        with self.assertRaises(DraftError):
            m.create_draft("a@example.invalid", "s", "b", "r.html", b"x" * (draftmail.MAX_ATTACHMENT_BYTES + 1))

    def test_a_transport_asked_to_send_is_stopped_before_the_network(self):
        called = []
        m = DraftMailer(signed_in_store(), CLIENT_ID, authority="https://example.invalid",
                        graph="https://example.invalid/v1.0", http=lambda *a: called.append(a) or (200, {}))
        with self.assertRaises(DraftError):
            m._call("https://example.invalid/v1.0/me/messages/ID/send", b"", {})
        self.assertEqual(called, [])


class DailyRunDraftsOnly(unittest.TestCase):
    def test_daily_run_with_draft_on_leaves_a_draft_and_nothing_sent(self):
        with MockGraph() as srv, tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"DSSREPORT_HOME": home}):
            s = st.DesktopSettings(daily_run_enabled=True, draft_email_enabled=True,
                                   draft_to="owner@example.invalid", graph_client_id=CLIENT_ID)
            factory = lambda _s: DraftMailer(signed_in_store(), CLIENT_ID, authority=srv.base,
                                             graph=srv.base + "/v1.0")
            self.assertEqual(daily.daily_run(s, now=datetime(2026, 11, 4, 7), mailer_factory=factory), 0)
            self.assertEqual(len(srv.drafts), 1)
            self.assertEqual(srv.sent, [])
            self.assertIn("not sent", daily.log_file().read_text())

    def test_failed_draft_is_logged_and_reported_but_the_report_still_exists(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"DSSREPORT_HOME": home}):
            s = st.DesktopSettings(daily_run_enabled=True, draft_email_enabled=True,
                                   draft_to="owner@example.invalid", graph_client_id=CLIENT_ID)
            factory = lambda _s: DraftMailer(InMemoryStoreForTests(), CLIENT_ID)   # not signed in
            self.assertEqual(daily.daily_run(s, now=datetime(2026, 11, 4, 7), mailer_factory=factory), 1)
            self.assertIn("draft FAILED", daily.log_file().read_text())
            self.assertTrue(any(Path(home, "reports").rglob("report.html")))


if __name__ == "__main__":
    unittest.main()
