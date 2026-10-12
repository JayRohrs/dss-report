"""A local MOCK of an OData service, with made-up data. It is NOT Restaurant365 and its entity
and property names are invented for the tests. Used to prove the connector is read-only, pages
correctly, refuses redirects/foreign links, and never leaks the password."""

import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dssreport.adapters.demo import PAY_TYPES, generate

USER = "MOCKDOMAIN\\mock.user"
PASSWORD = "pw-NOT-REAL-4821"
PAGE = 5

METADATA = b"""<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.0"><edmx:DataServices>
<Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="Mock">
<EntityType Name="MockDay"><Property Name="mockLocation" Type="Edm.String"/>
<Property Name="mockDate" Type="Edm.Date"/><Property Name="mockSales" Type="Edm.Decimal"/></EntityType>
<EntityContainer Name="C"><EntitySet Name="MockDailySales" EntityType="Mock.MockDay"/></EntityContainer>
</Schema></edmx:DataServices></edmx:Edmx>"""

MAPPING = {
    "source": {"entity": "MockDailySales", "location": "mockLocation", "business_date": "mockDate"},
    "fields": {"sales_total": "mockSales", "cash_over_short": "mockCashOS",
               "missing_receipts": "mockMissingReceipts", "payment_exceptions": "mockPayExceptions",
               "approved": "mockStatus", "pos_import_received": "mockPosIn"},
    "values": {"approved_true": ["Done"], "approved_false": ["Open"]},
    "payments": {t: f"mockPay_{t}" for t in PAY_TYPES},
}


def rows():
    out = []
    for r in generate():
        d = {"mockLocation": r.location, "mockDate": r.business_date.isoformat(),
             "mockSales": None if r.sales_total is None else float(r.sales_total),
             "mockCashOS": None if r.cash_over_short is None else float(r.cash_over_short),
             "mockMissingReceipts": r.missing_receipts, "mockPayExceptions": r.payment_exceptions,
             "mockStatus": {True: "Done", False: "Open", None: "Mystery"}[r.approved],
             "mockPosIn": r.pos_import_received}
        for t in PAY_TYPES:
            v = r.payments.get(t)
            d[f"mockPay_{t}"] = None if v is None else float(v)
        out.append(d)
    return out


class MockR365(HTTPServer):
    def __init__(self, extra_rows=None):
        super().__init__(("127.0.0.1", 0), Handler)
        self.data = rows() + list(extra_rows or [])
        self.requests = []     # (method, path, had_auth)
        self.foreign_link = None
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}/api/mock"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.shutdown()
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        h = self.headers.get("Authorization", "")
        want = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        return h == want

    def _any(self):
        self.server.requests.append((self.command, self.path, "Authorization" in self.headers))
        if self.command != "GET":
            return self._send(405)
        if not self._authed():
            return self._send(401, b"{}")
        u = urlparse(self.path)
        if u.path == "/api/mock/$metadata":
            return self._send(200, METADATA, "application/xml")
        if u.path == "/api/mock/redirect":
            return self._send(302, extra={"Location": "http://127.0.0.1:1/steal"})
        if u.path == "/api/mock/MockDailySales":
            q = parse_qs(u.query)
            flt = q.get("$filter", [""])[0]
            m = re.findall(r"mockDate (ge|le) (\d{4}-\d{2}-\d{2})", flt)
            lo = next((d for op, d in m if op == "ge"), "0000-00-00")
            hi = next((d for op, d in m if op == "le"), "9999-99-99")
            sel = q.get("$select", [""])[0].split(",")
            hit = [r for r in self.server.data if lo <= r["mockDate"] <= hi]
            skip = int(q.get("$skip", ["0"])[-1])
            page = hit[skip:skip + PAGE]
            body = {"value": [{k: v for k, v in r.items() if k in sel} for r in page]}
            if skip + PAGE < len(hit):
                nxt = f"http://127.0.0.1:{self.server.server_port}{u.path}?{u.query}&$skip={skip + PAGE}"
                body["@odata.nextLink"] = self.server.foreign_link or nxt
            return self._send(200, json.dumps(body).encode())
        self._send(404)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _any
