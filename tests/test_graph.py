"""Microsoft 365 email, tested ONLY against a local mock. A real tenant has not been tried."""

import base64
import json
import unittest

from dssreport.credstore import InMemoryStoreForTests
from dssreport.graph import SCOPE_DRAFT, SCOPE_SEND, GraphClient, GraphError, deliver_email, scopes_for
from dssreport.settings import ConfigError, Settings, validate

from .mock_graph import CLIENT_ID, MockGraph


def settings(**kw):
    base = dict(email_enabled=True, email_to="reviewer@example.com", graph_client_id=CLIENT_ID)
    base.update(kw)
    return Settings(**base)


def signed_in_client(srv, st):
    store = InMemoryStoreForTests()
    c = GraphClient(store, authority=srv.base, graph=srv.base + "/v1.0")
    dc = c.start_signin(st.graph_client_id, st.graph_tenant, scopes_for(st))
    srv.approved = True
    assert c.finish_signin(st.graph_client_id, st.graph_tenant, dc) == "done"
    return c, store


class SignIn(unittest.TestCase):
    def test_device_code_flow_pending_then_done_and_only_a_refresh_token_is_kept(self):
        with MockGraph() as srv:
            st = settings()
            store = InMemoryStoreForTests()
            c = GraphClient(store, authority=srv.base, graph=srv.base + "/v1.0")
            dc = c.start_signin(CLIENT_ID, st.graph_tenant, scopes_for(st))
            self.assertEqual(dc.user_code, "MOCK-CODE")
            self.assertEqual(c.finish_signin(CLIENT_ID, st.graph_tenant, dc), "pending")
            self.assertFalse(c.signed_in())
            srv.approved = True
            self.assertEqual(c.finish_signin(CLIENT_ID, st.graph_tenant, dc), "done")
            self.assertTrue(c.signed_in())
        self.assertEqual(list(store.items), ["graph:session"])
        wire = " ".join(b for _, _, _, b in srv.log)
        self.assertNotIn("password", wire.lower())

    def test_least_permissions(self):
        self.assertEqual(scopes_for(settings()), SCOPE_DRAFT)
        self.assertNotIn("Mail.Send", scopes_for(settings()))
        self.assertIn("Mail.Send", scopes_for(settings(email_send_auto=True)))
        self.assertEqual(sorted(SCOPE_SEND), sorted(["offline_access", "Mail.ReadWrite", "Mail.Send"]))

    def test_not_signed_in_is_a_plain_error(self):
        with MockGraph() as srv:
            c = GraphClient(InMemoryStoreForTests(), authority=srv.base, graph=srv.base + "/v1.0")
            with self.assertRaises(GraphError) as cm:
                deliver_email("s", "t", "<p>h</p>", settings(), InMemoryStoreForTests(), c)
        self.assertIn("Not signed in", str(cm.exception))

    def test_https_required_for_microsoft_addresses(self):
        with self.assertRaises(GraphError):
            GraphClient(InMemoryStoreForTests(), authority="http://login.example.com")


class Drafts(unittest.TestCase):
    def test_default_creates_a_draft_and_does_not_send(self):
        with MockGraph() as srv:
            st = settings()
            c, store = signed_in_client(srv, st)
            msg = deliver_email("Subject here", "Body text", "<h1>page</h1>", st, store, c)
        self.assertIn("Drafts folder", msg)
        self.assertEqual(srv.sent, [])
        draft = srv.drafts["draft-1"]
        self.assertEqual(draft["message"]["subject"], "Subject here")
        self.assertEqual(draft["message"]["toRecipients"][0]["emailAddress"]["address"], "reviewer@example.com")
        self.assertEqual(draft["message"]["body"]["content"], "Body text")
        att = draft["attachments"][0]
        self.assertEqual(base64.b64decode(att["contentBytes"]).decode(), "<h1>page</h1>")

    def test_send_only_when_ticked(self):
        with MockGraph() as srv:
            st = settings(email_send_auto=True)
            c, store = signed_in_client(srv, st)
            msg = deliver_email("S", "T", "<p/>", st, store, c)
        self.assertIn("sent", msg)
        self.assertEqual(srv.sent, ["draft-1"])

    def test_ticking_send_after_draft_only_signin_asks_for_new_consent_and_sends_nothing(self):
        with MockGraph() as srv:
            c, store = signed_in_client(srv, settings())  # signed in with draft-only scopes
            with self.assertRaises(GraphError) as cm:
                deliver_email("S", "T", "<p/>", settings(email_send_auto=True), store, c)
        self.assertIn("one more permission", str(cm.exception))
        self.assertEqual(srv.sent, [])
        self.assertEqual(srv.drafts, {})

    def test_expired_sign_in_is_a_plain_error(self):
        with MockGraph() as srv:
            st = settings()
            c, store = signed_in_client(srv, st)
            srv.refresh_ok = False
            with self.assertRaises(GraphError) as cm:
                deliver_email("S", "T", "<p/>", st, store, c)
        self.assertIn("sign in again", str(cm.exception))

    def test_only_documented_calls_are_made(self):
        with MockGraph() as srv:
            st = settings(email_send_auto=True)
            c, store = signed_in_client(srv, st)
            deliver_email("S", "T", "<p/>", st, store, c)
        paths = [p.split("?")[0] for _, p, _, _ in srv.log]
        self.assertTrue(set(p for p in paths if p.startswith("/v1.0")) <=
                        {"/v1.0/me/messages", "/v1.0/me/messages/draft-1/attachments",
                         "/v1.0/me/messages/draft-1/send"})


class SettingsValidation(unittest.TestCase):
    def test_send_auto_needs_email_on_and_defaults_off(self):
        self.assertFalse(Settings().email_send_auto)
        with self.assertRaises(ConfigError):
            validate(Settings(email_send_auto=True))
        with self.assertRaises(ConfigError):
            validate(Settings(email_enabled=True, email_to="not an address"))


if __name__ == "__main__":
    unittest.main()
