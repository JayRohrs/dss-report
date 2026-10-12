"""Optional: put the morning report into the user's own Microsoft 365 mailbox.

  * Delegated sign-in as the user (device-code flow). No password is ever typed into or stored by
    this program. The only thing kept is a refresh token, in the OS credential store.
  * Least permission: DRAFT only needs Mail.ReadWrite. Mail.Send is requested only if the user
    ticks "send automatically" (off by default). Nothing else is requested.
  * Draft-first: the default is to create a draft in the user's Drafts folder for them to look
    at and send themselves.
  * Calls go to Microsoft's sign-in and Graph addresses only (constants below). Tests use a mock.

Not yet confirmed against a real Microsoft 365 tenant - see docs/R365_OPEN_QUESTIONS.md ("Microsoft 365").
"""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

from .credstore import CredentialStore, redact
from .errors import DssError
from .settings import Settings, is_safe_url

AUTHORITY = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SESSION_KEY = "graph:session"
SCOPE_DRAFT = ["offline_access", "Mail.ReadWrite"]
SCOPE_SEND = SCOPE_DRAFT + ["Mail.Send"]


class GraphError(DssError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float
    interval: int
    scopes: List[str]


def scopes_for(settings: Settings) -> List[str]:
    return list(SCOPE_SEND if settings.email_send_auto else SCOPE_DRAFT)


class GraphClient:
    def __init__(self, store: CredentialStore, authority: str = AUTHORITY, graph: str = GRAPH,
                 timeout: float = 30.0):
        for u in (authority, graph):
            if not is_safe_url(u):
                raise GraphError("Microsoft addresses must be https.")
        self.store, self.authority, self.graph, self.timeout = store, authority.rstrip("/"), graph.rstrip("/"), timeout
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._access: Optional[str] = None

    # ----------------------------------------------------------- http
    def _call(self, url, data: Optional[bytes], headers: dict):
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read()
                return resp.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read() or b"{}")
            except (ValueError, OSError):
                body = {}
            return exc.code, body
        except (urllib.error.URLError, OSError) as exc:
            raise GraphError(f"Could not reach Microsoft ({getattr(exc, 'reason', exc)}).")

    def _form(self, url, fields: dict):
        return self._call(url, urllib.parse.urlencode(fields).encode(),
                          {"Content-Type": "application/x-www-form-urlencoded"})

    def _json(self, path, payload):
        status, body = self._call(self.graph + path, json.dumps(payload).encode(),
                                  {"Content-Type": "application/json",
                                   "Authorization": f"Bearer {self._access}"})
        return status, body

    # ----------------------------------------------------------- sign-in
    def start_signin(self, client_id: str, tenant: str, scopes: List[str]) -> DeviceCode:
        if not client_id:
            raise GraphError("Fill in the Microsoft app ID in settings first (see docs).")
        status, body = self._form(f"{self.authority}/{tenant}/oauth2/v2.0/devicecode",
                                  {"client_id": client_id, "scope": " ".join(scopes)})
        if status != 200 or "device_code" not in body:
            raise GraphError("Microsoft would not start the sign-in. Check the app ID and tenant in settings.")
        return DeviceCode(body["device_code"], body["user_code"], body["verification_uri"],
                          time.time() + int(body.get("expires_in", 900)), int(body.get("interval", 5)), scopes)

    def finish_signin(self, client_id: str, tenant: str, dc: DeviceCode) -> str:
        """Returns 'pending' or 'done'. Raises GraphError if it failed or expired."""
        if time.time() > dc.expires_at:
            raise GraphError("The sign-in code expired. Start the sign-in again.")
        status, body = self._form(f"{self.authority}/{tenant}/oauth2/v2.0/token", {
            "client_id": client_id, "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dc.device_code})
        if status == 200 and "refresh_token" in body:
            self._save(body, dc.scopes)
            self._access = body.get("access_token")
            return "done"
        if body.get("error") in ("authorization_pending", "slow_down"):
            return "pending"
        raise GraphError("Microsoft did not complete the sign-in (" + str(body.get("error", status)) + ").")

    def _save(self, body: dict, scopes: List[str]) -> None:
        granted = body.get("scope", " ".join(scopes)).split()
        self.store.set(SESSION_KEY, json.dumps({"refresh_token": body["refresh_token"], "scope": granted}))

    def _session(self) -> Optional[dict]:
        raw = self.store.get(SESSION_KEY)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    def signed_in(self) -> bool:
        return self._session() is not None

    def granted_scopes(self) -> List[str]:
        s = self._session()
        return list(s["scope"]) if s else []

    def sign_out(self) -> None:
        self.store.delete(SESSION_KEY)
        self._access = None

    def _token(self, client_id: str, tenant: str, scopes: List[str]) -> None:
        s = self._session()
        if not s:
            raise GraphError("Not signed in to Microsoft 365. Open settings and sign in.")
        have = {x.lower() for x in s["scope"]}
        if not {x.lower() for x in scopes} <= have and "mail.send" in {x.lower() for x in scopes}:
            raise GraphError("Sending automatically needs one more permission. "
                             "Open settings and sign in to Microsoft 365 again.")
        status, body = self._form(f"{self.authority}/{tenant}/oauth2/v2.0/token", {
            "client_id": client_id, "grant_type": "refresh_token",
            "refresh_token": s["refresh_token"], "scope": " ".join(scopes)})
        if status != 200 or "access_token" not in body:
            raise GraphError("Microsoft 365 sign-in has expired. Open settings and sign in again.")
        self._access = body["access_token"]
        if body.get("refresh_token"):
            self._save(body, scopes)

    # ----------------------------------------------------------- mail
    def create_draft(self, settings: Settings, subject: str, text_body: str,
                     attachment_name: str, attachment_html: str, send: bool) -> str:
        scopes = SCOPE_SEND if send else SCOPE_DRAFT
        self._token(settings.graph_client_id, settings.graph_tenant, scopes)
        status, msg = self._json("/me/messages", {
            "subject": subject,
            "body": {"contentType": "Text", "content": text_body},
            "toRecipients": [{"emailAddress": {"address": settings.email_to}}]})
        if status not in (200, 201) or "id" not in msg:
            raise GraphError(f"Microsoft 365 would not create the draft (HTTP {status}).")
        mid = urllib.parse.quote(msg["id"], safe="")
        status, _ = self._json(f"/me/messages/{mid}/attachments", {
            "@odata.type": "#microsoft.graph.fileAttachment", "name": attachment_name,
            "contentType": "text/html",
            "contentBytes": base64.b64encode(attachment_html.encode("utf-8")).decode()})
        if status not in (200, 201):
            raise GraphError(f"The draft was created but the report page could not be attached (HTTP {status}).")
        if send:
            status, _ = self._json(f"/me/messages/{mid}/send", {})
            if status not in (200, 202):
                raise GraphError(f"The draft was created but Microsoft 365 would not send it (HTTP {status}).")
        return msg["id"]


def deliver_email(report_subject: str, text_body: str, html_page: str, settings: Settings,
                  store: CredentialStore, client: Optional[GraphClient] = None) -> str:
    """Create the email in the user's mailbox. Returns a plain sentence saying what happened."""
    client = client or GraphClient(store)
    send = settings.email_send_auto
    try:
        client.create_draft(settings, report_subject, text_body, "report.html", html_page, send)
    except GraphError as exc:
        raise GraphError(redact(str(exc), client._access))
    return (f"Email sent to {settings.email_to} from your Microsoft 365 account." if send
            else f"A draft addressed to {settings.email_to} is waiting in your Microsoft 365 Drafts folder.")
