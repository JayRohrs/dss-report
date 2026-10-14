"""The OPTIONAL online update check, tested only against a local mock static host with made-up files."""

import base64
import hashlib
import json
import re
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from dssreport import licence as L
from dssreport import licence_keys, update_check, updates
from dssreport.update_check import Available

from . import licence_helpers as H
from . import test_updates as U

TODAY = date(2026, 10, 12)


class MockStaticHost(HTTPServer):
    """A plain static file host: what the owner would use. Records exactly what it was sent."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.files = {}            # path -> bytes
        self.requests = []         # (command, raw request line, dict of headers)
        self.redirect = None
        self.thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server_port}/dss"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _any(self):
        self.server.requests.append((self.command, self.requestline, dict(self.headers.items())))
        if self.server.redirect:
            self.send_response(302)
            self.send_header("Location", self.server.redirect)
            self.end_headers()
            return
        body = self.server.files.get(self.path)
        if self.command != "GET" or body is None:
            self.send_response(404 if self.command == "GET" else 405)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _any


def licence_status(**kw):
    return U.status(**kw)


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        k = U.update_keys()
        k.__enter__()
        self.addCleanup(lambda: k.__exit__(None, None, None))
        self.host = MockStaticHost()
        self.host.__enter__()
        self.addCleanup(lambda: self.host.__exit__(None, None, None))
        self.pkgs = self.tmp / "pkgs"
        self.pkgs.mkdir()

    def publish(self, version, release=date(2026, 10, 1), files=None, secret=None, kid=U.UKID, name=None, **kw):
        name = name or f"dss-update-{version}.dssupdate"
        out = self.pkgs / name
        U.update_tool.build_update(secret or U.USECRET, kid, files if files is not None else U.NEW, version,
                                   release, out, **kw)
        self.host.files[f"/dss/{name}"] = out.read_bytes()
        return out

    def publish_manifest(self, secret=None, kid=U.UKID):
        m = self.tmp / "manifest.json"
        U.update_tool.write_manifest(secret or U.USECRET, kid, self.pkgs, m)
        self.host.files["/dss/manifest.json"] = m.read_bytes()
        return m

    @property
    def url(self):
        return self.host.base + "/manifest.json"


class Listing(Env):
    def test_lists_only_newer_versions_newest_first_and_downloads_nothing(self):
        self.publish("0.2.0")
        self.publish("0.3.0")
        self.publish("0.4.0")
        self.publish("0.5.0")
        self.publish_manifest()
        found = update_check.check(self.url, "0.3.0")
        self.assertEqual([a.version for a in found], ["0.5.0", "0.4.0"])
        self.assertEqual([r[1] for r in self.host.requests], ["GET /dss/manifest.json HTTP/1.1"])   # the list only
        self.assertEqual(update_check.downloaded_files(self.tmp / "none"), [])

    def test_nothing_newer_is_a_plain_answer(self):
        self.publish("0.3.0")
        self.publish_manifest()
        self.assertEqual(update_check.check(self.url, "0.3.0"), [])


class SendsNothingAboutTheUser(Env):
    def test_one_plain_get_with_generic_headers_and_no_identifying_details(self):
        self.publish("0.4.0")
        self.publish_manifest()
        update_check.check(self.url, "0.3.0")
        self.assertEqual(len(self.host.requests), 1)
        cmd, line, headers = self.host.requests[0]
        self.assertEqual(cmd, "GET")
        self.assertEqual(line, "GET /dss/manifest.json HTTP/1.1")          # no query string, nothing appended
        self.assertLessEqual({k.lower() for k in headers}, {"host", "user-agent", "accept", "accept-encoding", "connection"})
        for forbidden in ("authorization", "cookie", "referer", "x-licence", "from"):
            self.assertNotIn(forbidden, {k.lower() for k in headers})
        raw = (line + json.dumps(headers)).lower()
        for secret in ("lic-aaa111", "sample customer", "0.3.0", "python", "windows", "linux", "mozilla"):
            self.assertNotIn(secret, raw)
        self.assertEqual(headers["User-Agent"], "dss-report-update-check")

    def test_download_is_also_a_plain_get_of_a_file_next_to_the_list(self):
        self.publish("0.4.0")
        self.publish_manifest()
        entry = update_check.check(self.url, "0.3.0")[0]
        update_check.download(self.url, entry, licence_status(), dest_dir=self.tmp / "dl", installed="0.3.0")
        cmd, line, headers = self.host.requests[1]
        self.assertEqual((cmd, line), ("GET", "GET /dss/dss-update-0.4.0.dssupdate HTTP/1.1"))
        self.assertLessEqual({k.lower() for k in headers}, {"host", "user-agent", "accept", "accept-encoding", "connection"})

    def test_source_has_no_licence_or_customer_in_the_request_code(self):
        text = (H.ROOT / "dssreport" / "update_check.py").read_text()
        code = re.sub(r'""".*?"""', "", text, flags=re.S)
        for word in ("licence_id", "customer", "platform", "socket.gethostname", "getpass", "os.environ", "uname"):
            self.assertNotIn(word, code)


class ListIsVerified(Env):
    def check_fails(self, needle):
        with self.assertRaises(update_check.UpdateCheckError) as cm:
            update_check.check(self.url, "0.3.0")
        self.assertIn(needle, str(cm.exception))

    def test_tampered_list(self):
        self.publish("0.4.0")
        m = self.publish_manifest()
        doc = json.loads(m.read_text())
        payload = json.loads(base64.urlsafe_b64decode(doc["payload"] + "=="))
        payload["versions"][0]["sha256"] = "0" * 64
        doc["payload"] = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        self.host.files["/dss/manifest.json"] = json.dumps(doc).encode()
        self.check_fails("changed or was not made by Jay Rohrs")

    def test_wrong_unknown_and_missing_keys_and_garbage(self):
        self.publish("0.4.0")
        self.publish_manifest(secret=U.OTHER_USECRET)
        self.check_fails("changed or was not made by Jay Rohrs")
        self.publish_manifest(secret=U.OTHER_USECRET, kid="stranger")
        self.check_fails("key this program does not know")
        self.publish_manifest()
        with mock.patch.dict(licence_keys.UPDATE_PUBLIC_KEYS, {}, clear=True):
            self.check_fails("no update key built in")
        for junk in (b"", b"not json", b"[]", b'{"v": 1}', b'{"v":1,"kid":"x","payload":5,"signature":6}'):
            self.host.files["/dss/manifest.json"] = junk
            self.check_fails("did not give a valid update list" if junk not in (b"{\"v\": 1}",) else "valid update list")

    def test_a_licence_key_cannot_sign_the_list(self):
        self.publish("0.4.0")
        self.publish_manifest(secret=H.SECRET, kid=H.KID)
        with H.trusted_keys():
            self.check_fails("key this program does not know")

    def test_entries_may_not_point_anywhere_but_next_to_the_list(self):
        for bad in ("../evil.dssupdate", "http://evil.example.com/x.dssupdate", "sub/dir.dssupdate", ".hidden.dssupdate",
                    "x.zip", "a b.dssupdate", "x.dssupdate?token=1"):
            payload = json.dumps({"versions": [{"version": "0.4.0", "release_date": "2026-10-01", "file": bad,
                                                "sha256": "a" * 64}]}).encode()
            b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
            doc = {"v": 1, "kid": U.UKID, "payload": b64(payload), "signature": b64(U.H.ed25519_sign.sign(U.USECRET, payload))}
            self.host.files["/dss/manifest.json"] = json.dumps(doc).encode()
            self.check_fails("damaged")

    def test_redirects_errors_and_oversize_are_plain_messages(self):
        self.host.redirect = "http://127.0.0.1:1/elsewhere"
        with self.assertRaises(update_check.ConnectionFailed):
            update_check.check(self.url, "0.3.0")
        self.host.redirect = None
        with self.assertRaises(update_check.ConnectionFailed) as cm:
            update_check.check(self.host.base + "/missing.json", "0.3.0")
        self.assertIn("HTTP 404", str(cm.exception))
        self.host.files["/dss/manifest.json"] = b"x" * (update_check.MAX_MANIFEST_BYTES + 10)
        self.check_fails("far more data than expected")
        with self.assertRaises(update_check.ConnectionFailed) as cm:
            update_check.check("http://127.0.0.1:1/dss/manifest.json", "0.3.0")
        self.assertIn("Could not reach the update address", str(cm.exception))

    def test_only_sensible_addresses_are_accepted(self):
        for bad in ("http://updates.example.com/m.json", "https://u:p@updates.example.com/m.json",
                    "https://updates.example.com/m.json?id=1", "https://updates.example.com/m.json#x", "ftp://x/y", ""):
            self.assertFalse(update_check.is_valid_manifest_url(bad), bad)
            with self.assertRaises(update_check.UpdateCheckError):
                update_check.check(bad, "0.3.0")
        self.assertTrue(update_check.is_valid_manifest_url("https://updates.example.invalid/dss-report/manifest.json"))


class Downloading(Env):
    def entry(self):
        self.publish_manifest()
        return update_check.check(self.url, "0.3.0")[0]

    def dl(self, entry, st=None):
        return update_check.download(self.url, entry, st or licence_status(), dest_dir=self.tmp / "dl", installed="0.3.0")

    def test_a_good_download_is_kept_checked_and_not_installed(self):
        self.publish("0.4.0")
        path = self.dl(self.entry())
        self.assertTrue(path.exists())
        self.assertEqual(path.parent, self.tmp / "dl")
        manifest, _ = updates.read_package(path)             # it verifies like any hand-supplied file
        self.assertEqual(manifest.version, "0.4.0")
        self.assertEqual(list((self.tmp / "dl").glob("*.part")), [])

    def test_a_file_that_does_not_match_the_signed_fingerprint_is_thrown_away(self):
        self.publish("0.4.0")
        entry = self.entry()
        self.host.files["/dss/dss-update-0.4.0.dssupdate"] = self.host.files["/dss/dss-update-0.4.0.dssupdate"] + b"x"
        with self.assertRaises(update_check.UpdateCheckError) as cm:
            self.dl(entry)
        self.assertIn("does not match the fingerprint", str(cm.exception))
        self.assertEqual(list((self.tmp / "dl").glob("*")) if (self.tmp / "dl").exists() else [], [])

    def test_a_package_signed_by_the_wrong_key_is_thrown_away_even_if_the_list_vouches_for_it(self):
        self.publish("0.4.0", secret=U.OTHER_USECRET)              # package signed by someone else
        entry = self.entry()                                        # but the (genuine) list names its hash
        with self.assertRaises(updates.UpdateError) as cm:
            self.dl(entry)
        self.assertIn("changed or was not made by Jay Rohrs", str(cm.exception))
        self.assertEqual(list((self.tmp / "dl").glob("*")), [])

    def test_the_package_must_be_the_version_the_list_promised(self):
        pkg = self.publish("0.4.0")
        self.publish_manifest()
        other = self.publish("0.9.0", name="dss-update-0.4.0.dssupdate")          # same file name, different content
        entry = Available("0.4.0", date(2026, 10, 1), "dss-update-0.4.0.dssupdate", hashlib.sha256(other.read_bytes()).hexdigest())
        with self.assertRaises(update_check.UpdateCheckError) as cm:
            self.dl(entry)
        self.assertIn("not the version the signed list promised", str(cm.exception))

    def test_the_licence_rules_apply_at_download_exactly_as_for_a_hand_supplied_file(self):
        self.publish("0.4.0", release=date(2026, 10, 1))
        entry = self.entry()
        with self.assertRaises(updates.UpdateError) as cm:
            self.dl(entry, licence_status(updates_until=date(2026, 1, 1)))
        self.assertIn("includes updates until 2026-01-01", str(cm.exception))
        with self.assertRaises(updates.UpdateError):
            self.dl(entry, L.LicenceStatus(L.NOT_FOUND, "Licence: not found."))
        self.assertEqual(list((self.tmp / "dl").glob("*")), [])
        self.publish("0.4.0", release=date(2026, 10, 1), licence_ids=["someone-else"])
        with self.assertRaises(updates.UpdateError) as cm:
            self.dl(self.entry())
        self.assertIn("has not been released to your licence", str(cm.exception))

    def test_nothing_installs_by_itself(self):
        pdir = self.tmp / "program"
        pdir.mkdir()
        for rel, data in U.OLD.items():
            (pdir / rel).parent.mkdir(parents=True, exist_ok=True)
            (pdir / rel).write_bytes(data)
        self.publish("0.4.0")
        path = self.dl(self.entry())
        self.assertEqual({p.relative_to(pdir).as_posix(): p.read_bytes() for p in pdir.rglob("*") if p.is_file()}, U.OLD)
        updates.apply_update(path, licence_status(), pdir, self.tmp / "home", installed="0.3.0")     # only an explicit install
        self.assertEqual((pdir / "dssreport/thing.py").read_bytes(), b"VALUE = 2\n")

    def test_the_manual_signed_file_route_still_works_without_any_online_setting(self):
        pdir, home = self.tmp / "program", self.tmp / "home"
        pdir.mkdir()
        home.mkdir()
        for rel, data in U.OLD.items():
            (pdir / rel).parent.mkdir(parents=True, exist_ok=True)
            (pdir / rel).write_bytes(data)
        pkg = self.publish("0.4.0")
        self.host.requests.clear()
        updates.apply_update(pkg, licence_status(), pdir, home, installed="0.3.0")
        self.assertEqual(self.host.requests, [])                          # no network involved at all


class NetworkSurface(unittest.TestCase):
    ALLOWED = {"r365.py", "graph.py", "summary.py", "update_check.py"}

    def test_only_the_documented_modules_can_make_network_calls(self):
        pattern = re.compile(r"^\s*(import urllib\.request|from urllib import request|import socket|import http\.client|"
                             r"from http import client|import ftplib|import smtplib|import requests)", re.M)
        found = {p.name for p in (H.ROOT / "dssreport").rglob("*.py") if pattern.search(p.read_text())}
        self.assertEqual(found, self.ALLOWED)

    def test_off_by_default_with_no_address_built_in(self):
        from dssreport.settings import Settings
        s = Settings()
        self.assertFalse(s.update_check_enabled)
        self.assertEqual(s.update_manifest_url, "")
        text = (H.ROOT / "dssreport" / "update_check.py").read_text()
        self.assertNotRegex(text, r"https?://(?!127\.0\.0\.1|localhost)[A-Za-z0-9.-]+\.[a-z]{2,}")

    def test_no_update_public_key_in_the_repo(self):
        self.assertEqual(licence_keys.UPDATE_PUBLIC_KEYS, {})
        self.assertEqual(licence_keys.PUBLIC_KEYS, {})


if __name__ == "__main__":
    unittest.main()
