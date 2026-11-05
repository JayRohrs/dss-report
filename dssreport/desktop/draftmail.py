"""Create a Microsoft 365 DRAFT message with the report attached. It never sends anything.

How the "never sends" promise is kept:
  * Only two Graph calls exist in this file: create a message (which stays a draft in the Drafts
    folder) and add a file to it. There is no call that delivers a message.
  * The only permission asked for is Mail.ReadWrite. The delivering permission is never requested, so
    Microsoft would refuse a send even if code tried (see docs/GRAPH_PERMISSIONS.md).
  * Every web request passes an allow-list first (`check_allowed`); anything else is refused.
  * tests/test_desktop_draft_only.py reads this file's code and fails if any send-like word appears.

The person opens Outlook, looks at the draft, and sends it themselves if they want to.
"""

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from ..credstore import CredentialStore, redact
from ..errors import DssError
from ..settings import is_safe_url

AUTHORITY = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SESSION_KEY = "graph:session"        # same entry the settings page's sign-in writes
SCOPES = ["offline_access", "Mail.ReadWrite"]
MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024   # Graph's limit for a simple (non-upload-session) attachment

_ALLOWED = [
    ("POST", re.compile(r"/[^/]+/oauth2/v2\.0/token")),
    ("POST", re.compile(r"/v1\.0/me/messages")),
    ("POST", re.compile(r"/v1\.0/me/messages/[^/]+/attachments")),
]

Http = Callable[[str, str, Optional[bytes], dict], Tuple[int, dict]]


class DraftError(DssError):
    pass


def check_allowed(method: str, url: str) -> None:
    path = urllib.parse.urlparse(url).path
    if not any(method == m and rx.fullmatch(path) for m, rx in _ALLOWED):
        raise DraftError("Refused: this program may only create a draft and attach a file.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _urllib_http(method: str, url: str, data: Optional[bytes], headers: dict, timeout: float = 30.0):
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except (ValueError, OSError):
            return exc.code, {}
    except (urllib.error.URLError, OSError) as exc:
        raise DraftError(f"Could not reach Microsoft ({getattr(exc, 'reason', exc)}).")


class DraftMailer:
    def __init__(self, store: CredentialStore, client_id: str, tenant: str = "organizations",
                 authority: str = AUTHORITY, graph: str = GRAPH, http: Optional[Http] = None):
        for u in (authority, graph):
            if not is_safe_url(u):
                raise DraftError("Microsoft addresses must be https.")
        self.store, self.client_id, self.tenant = store, client_id, tenant
        self.authority, self.graph = authority.rstrip("/"), graph.rstrip("/")
        self._http = http or _urllib_http
        self._access: Optional[str] = None

    def _call(self, url: str, data: Optional[bytes], headers: dict) -> Tuple[int, dict]:
        check_allowed("POST", url)
        return self._http("POST", url, data, headers)

    def _token(self) -> None:
        raw = self.store.get(SESSION_KEY)
        try:
            session = json.loads(raw) if raw else None
        except ValueError:
            session = None
        if not session or "refresh_token" not in session:
            raise DraftError("Not signed in to Microsoft 365. Open settings and sign in first.")
        form = urllib.parse.urlencode({
            "client_id": self.client_id, "grant_type": "refresh_token",
            "refresh_token": session["refresh_token"], "scope": " ".join(SCOPES)}).encode()
        status, body = self._call(f"{self.authority}/{self.tenant}/oauth2/v2.0/token", form,
                                  {"Content-Type": "application/x-www-form-urlencoded"})
        if status != 200 or "access_token" not in body:
            raise DraftError("Microsoft 365 sign-in has expired. Open settings and sign in again.")
        self._access = body["access_token"]
        if body.get("refresh_token"):
            self.store.set(SESSION_KEY, json.dumps({"refresh_token": body["refresh_token"],
                                                    "scope": body.get("scope", " ".join(SCOPES)).split()}))

    def _json(self, path: str, payload: dict) -> Tuple[int, dict]:
        return self._call(self.graph + path, json.dumps(payload).encode(),
                          {"Content-Type": "application/json", "Authorization": f"Bearer {self._access}"})

    def create_draft(self, to: str, subject: str, body_text: str, attachment_name: str,
                     attachment: bytes, content_type: str = "text/html") -> str:
        """Returns the draft's id. The message stays in the Drafts folder."""
        if len(attachment) > MAX_ATTACHMENT_BYTES:
            raise DraftError("The report is too large to attach to a draft (over 3 MB).")
        try:
            self._token()
            status, msg = self._json("/me/messages", {
                "subject": subject,
                "body": {"contentType": "Text", "content": body_text},
                "toRecipients": [{"emailAddress": {"address": to}}]})
            if status not in (200, 201) or "id" not in msg:
                raise DraftError(f"Microsoft 365 would not create the draft (HTTP {status}).")
            mid = urllib.parse.quote(msg["id"], safe="")
            status, _ = self._json(f"/me/messages/{mid}/attachments", {
                "@odata.type": "#microsoft.graph.fileAttachment", "name": attachment_name,
                "contentType": content_type,
                "contentBytes": base64.b64encode(attachment).decode()})
            if status not in (200, 201):
                raise DraftError(f"The draft was created but the report could not be attached (HTTP {status}).")
        except DraftError as exc:
            raise DraftError(redact(str(exc), self._access))
        return msg["id"]


def sign_in_scopes() -> List[str]:
    """The permissions the sign-in asks for. Used by the sign-in command so it can never ask for more."""
    return list(SCOPES)
