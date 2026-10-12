"""A local MOCK of Microsoft sign-in and Graph mail endpoints. Not Microsoft. Made-up ids and tokens."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

CLIENT_ID = "00000000-0000-0000-0000-00000000mock"


class MockGraph(HTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.log = []            # (method, path, headers dict, body)
        self.approved = False    # flip to simulate the user finishing sign-in
        self.drafts = {}
        self.sent = []
        self.refresh_ok = True
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.shutdown()
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, code, obj=None):
        body = json.dumps(obj if obj is not None else {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode()
        srv = self.server
        srv.log.append(("POST", self.path, dict(self.headers), raw))
        if self.path.endswith("/oauth2/v2.0/devicecode"):
            f = parse_qs(raw)
            self.server.last_scope = f["scope"][0]
            return self._reply(200, {"device_code": "dev-123", "user_code": "MOCK-CODE",
                                     "verification_uri": "https://example.invalid/devicelogin",
                                     "expires_in": 900, "interval": 1})
        if self.path.endswith("/oauth2/v2.0/token"):
            f = {k: v[0] for k, v in parse_qs(raw).items()}
            if f["grant_type"].endswith("device_code"):
                if not srv.approved:
                    return self._reply(400, {"error": "authorization_pending"})
                return self._reply(200, {"access_token": "tok:" + srv.last_scope, "refresh_token": "refresh-1",
                                         "scope": srv.last_scope, "expires_in": 3600})
            if f["grant_type"] == "refresh_token":
                if not srv.refresh_ok or f["refresh_token"] != "refresh-1":
                    return self._reply(400, {"error": "invalid_grant"})
                return self._reply(200, {"access_token": "tok:" + f["scope"], "expires_in": 3600})
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer tok:"):
            return self._reply(401, {"error": "no token"})
        scopes = auth[len("Bearer tok:"):].split()
        body = json.loads(raw or "{}")
        if self.path == "/v1.0/me/messages":
            if "Mail.ReadWrite" not in scopes:
                return self._reply(403)
            mid = f"draft-{len(srv.drafts) + 1}"
            srv.drafts[mid] = {"message": body, "attachments": []}
            return self._reply(201, {"id": mid})
        if self.path.startswith("/v1.0/me/messages/") and self.path.endswith("/attachments"):
            mid = self.path.split("/")[4]
            srv.drafts[mid]["attachments"].append(body)
            return self._reply(201, {"id": "att-1"})
        if self.path.startswith("/v1.0/me/messages/") and self.path.endswith("/send"):
            if "Mail.Send" not in scopes:
                return self._reply(403)
            srv.sent.append(self.path.split("/")[4])
            return self._reply(202)
        self._reply(404)

    do_GET = do_PUT = do_PATCH = do_DELETE = lambda self: self._reply(405)
