import base64
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from dssreport import licence as L
from dssreport import licence_keys

from . import licence_helpers as H

TODAY = date(2026, 6, 1)


def tamper(raw: bytes, **changes) -> bytes:
    doc = json.loads(raw)
    payload = json.loads(base64.urlsafe_b64decode(doc["payload"] + "=="))
    payload.update(changes)
    doc["payload"] = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return json.dumps(doc).encode()


class Signature(unittest.TestCase):
    def verify(self, raw):
        with H.trusted_keys():
            return L.verify_licence(raw)

    def test_valid_licence_is_read(self):
        lic = self.verify(H.make(customer="Sample Customer Ltd", instances=3))
        self.assertEqual((lic.customer, lic.instances), ("Sample Customer Ltd", 3))
        self.assertEqual(lic.expires, date(2099, 12, 31))
        self.assertEqual(lic.features, frozenset(L.BASE_FEATURES))

    def test_tampered_payload_fails_plainly(self):
        for change in ({"instances": 99}, {"expires": "2199-01-01"}, {"customer": "Someone Else"},
                       {"features": list(L.ALL_FEATURES)}):
            with self.assertRaises(L.LicenceError) as cm:
                self.verify(tamper(H.make(), **change))
            self.assertIn("changed or was not made by Jay Rohrs", str(cm.exception))

    def test_tampered_signature_fails(self):
        doc = json.loads(H.make())
        sig = bytearray(base64.urlsafe_b64decode(doc["signature"] + "=="))
        sig[0] ^= 1
        doc["signature"] = base64.urlsafe_b64encode(bytes(sig)).rstrip(b"=").decode()
        with self.assertRaises(L.LicenceError) as cm:
            self.verify(json.dumps(doc).encode())
        self.assertIn("signature does not match", str(cm.exception))

    def test_unsigned_licence_fails(self):
        doc = json.loads(H.make())
        del doc["signature"]
        with self.assertRaises(L.LicenceError) as cm:
            self.verify(json.dumps(doc).encode())
        self.assertIn("not signed", str(cm.exception))

    def test_wrong_key_fails(self):
        # signed by someone else but claiming our key id
        with self.assertRaises(L.LicenceError) as cm:
            self.verify(H.make(secret=H.OTHER_SECRET))
        self.assertIn("signature does not match", str(cm.exception))
        # signed with a key id this program has never heard of
        with self.assertRaises(L.LicenceError) as cm:
            self.verify(H.make(secret=H.OTHER_SECRET, kid="other-key"))
        self.assertIn("key this program does not know", str(cm.exception))

    def test_development_build_with_no_key_cannot_verify_anything(self):
        self.assertEqual(licence_keys.PUBLIC_KEYS, {})        # the repo ships no key on purpose
        with self.assertRaises(L.LicenceError) as cm:
            L.verify_licence(H.make())
        self.assertIn("no licence key built in", str(cm.exception))

    def test_garbage_is_a_plain_error_not_a_crash(self):
        for raw in (b"", b"not json", b"[]", b'{"v": 1}', b'{"v": 2, "signature": "x"}', b"\xff\xfe\x00",
                    b'{"v":1,"kid":"test-key","payload":"!!!","signature":"!!!"}', b"x" * 20000):
            with self.assertRaises(L.LicenceError):
                self.verify(raw)

    def test_unknown_feature_flags_are_ignored_not_trusted(self):
        lic = self.verify(H.make(features=["scheduling", "made_up_flag"]))
        self.assertEqual(lic.features, frozenset({"scheduling"}))


class Status(unittest.TestCase):
    def status(self, raw=None, **kw):
        home = Path(tempfile.mkdtemp())
        path = H.install(home, raw, **kw)
        with H.trusted_keys():
            return L.current_status(TODAY, path)

    def test_ok(self):
        s = self.status()
        self.assertEqual(s.state, L.OK)
        self.assertIn("valid for Sample Customer Ltd until 2099-12-31", s.message)
        self.assertEqual(s.instances_allowed, 2)

    def test_expired_is_a_status_not_a_lockout(self):
        s = self.status(expires=date(2026, 5, 31))
        self.assertEqual(s.state, L.EXPIRED)
        self.assertTrue(s.message.startswith("Licence: expired on 2026-05-31"))
        self.assertIn("reports and existing connections keep working", s.message)
        self.assertEqual(s.instances_allowed, 2)                 # existing connections keep running
        self.assertIn("renewed licence", s.can_add_connection(0))  # but nothing new can be added

    def test_expiry_day_itself_is_still_valid(self):
        self.assertEqual(self.status(expires=TODAY).state, L.OK)

    def test_not_found(self):
        with H.trusted_keys():
            s = L.current_status(TODAY, Path(tempfile.mkdtemp()) / "licence.json")
        self.assertEqual(s.state, L.NOT_FOUND)
        self.assertTrue(s.message.startswith("Licence: not found"))
        self.assertEqual(s.instances_allowed, 0)

    def test_invalid_file_says_so_and_allows_nothing(self):
        s = self.status(raw=tamper(H.make(), instances=50))
        self.assertEqual(s.state, L.INVALID)
        self.assertTrue(s.message.startswith("Licence: not valid."))
        self.assertEqual(s.instances_allowed, 0)
        self.assertIn("Existing reports can still be viewed", s.message)

    def test_demo_mode_is_not_blocked(self):
        d = L.demo_status()
        self.assertEqual(d.state, L.DEMO)
        for f in L.BASE_FEATURES:
            self.assertTrue(d.has(f))
        self.assertFalse(d.has(L.F_HOSTED))

    def test_updates_date(self):
        s = self.status(updates_until=date(2026, 1, 1))
        self.assertFalse(s.updates_covered(date(2026, 3, 1)))
        self.assertTrue(s.updates_covered(date(2025, 12, 1)))
        self.assertIsNone(L.demo_status().updates_covered(date(2026, 3, 1)))


class Instances(unittest.TestCase):
    def test_limit(self):
        s = L.status_for(L.Licence("X", 2, date(2099, 1, 1), date(2099, 1, 1), frozenset()), TODAY)
        self.assertIsNone(s.can_add_connection(0))
        self.assertIsNone(s.can_add_connection(1))
        msg = s.can_add_connection(2)
        self.assertIn("over limit", msg)
        self.assertIn("allows 2 connections", msg)
        self.assertEqual(L.instance_overflow(s, 3), 1)

    def test_no_licence_no_connections(self):
        s = L.LicenceStatus(L.NOT_FOUND, "Licence: not found.")
        self.assertIn("Load a licence", s.can_add_connection(0))


class Features(unittest.TestCase):
    def test_flags_on_and_off(self):
        s = L.status_for(L.Licence("X", 1, date(2099, 1, 1), date(2099, 1, 1), frozenset({L.F_EMAIL})), TODAY)
        self.assertTrue(L.has_feature(s, L.F_EMAIL))
        self.assertFalse(L.has_feature(s, L.F_SCHEDULE))
        s.require(L.F_EMAIL)
        with self.assertRaises(L.FeatureNotLicensed) as cm:
            s.require(L.F_SCHEDULE)
        self.assertIn("Automatic schedule is not included in your licence", str(cm.exception))

    def test_unknown_flag_name_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            L.demo_status().has("nonsense")

    def test_base_licence_has_everything_built_so_far_but_not_future_flags(self):
        with H.trusted_keys():
            lic = L.verify_licence(H.make())
        s = L.status_for(lic, TODAY)
        for f in L.BASE_FEATURES:
            self.assertTrue(s.has(f), f)
        self.assertFalse(s.has(L.F_HOSTED))
        self.assertFalse(s.has(L.F_ADDONS))

    def test_expired_licence_keeps_the_flags_it_had_and_gets_no_new_ones(self):
        s = L.status_for(L.Licence("X", 1, date(2026, 1, 1), date(2026, 1, 1), frozenset({L.F_EMAIL})), TODAY)
        self.assertEqual(s.state, L.EXPIRED)
        self.assertTrue(s.has(L.F_EMAIL))
        self.assertFalse(s.has(L.F_HOSTED))


class Installing(unittest.TestCase):
    def test_bad_file_does_not_replace_a_good_one(self):
        home = Path(tempfile.mkdtemp())
        path = home / "licence.json"
        good = H.make(customer="Good Customer")
        with H.trusted_keys():
            L.install_licence(good, path=path, today=TODAY)
            with self.assertRaises(L.LicenceError):
                L.install_licence(tamper(good, instances=9), path=path, today=TODAY)
            self.assertEqual(path.read_bytes(), good)
            st = L.install_licence(H.make(expires=date(2020, 1, 1)), path=path, today=TODAY)
        self.assertEqual(st.state, L.EXPIRED)      # genuine but expired files are accepted (and shown as expired)


class Tool(unittest.TestCase):
    def test_tool_round_trip_and_refuses_to_keep_private_key_in_a_repo(self):
        import licence_tool
        out = Path(tempfile.mkdtemp())
        pub = licence_tool.keygen(out, "unit-key")
        key_file = out / "unit-key.private.key"
        self.assertEqual(len(bytes.fromhex(key_file.read_text().strip())), 32)
        lic_file = out / "licence.json"
        licence_tool.main(["sign", "--private-key", str(key_file), "--kid", "unit-key", "--customer", "Round Trip Co",
                           "--instances", "1", "--expires", "2099-01-01", "--updates-until", "2099-01-01",
                           "--out", str(lic_file)])
        lic = L.verify_licence(lic_file.read_bytes(), {"unit-key": pub})
        self.assertEqual(lic.customer, "Round Trip Co")
        with self.assertRaises(SystemExit):
            licence_tool.keygen(H.ROOT / "tools" / "keys", "k")      # inside this git repo -> refused
        with self.assertRaises(SystemExit):
            licence_tool.main(["sign", "--private-key", str(key_file), "--kid", "k", "--customer", "C",
                               "--instances", "1", "--expires", "2099-01-01", "--updates-until", "2099-01-01",
                               "--features", "bogus", "--out", str(out / "x.json")])

    def test_tool_is_outside_the_shipped_package_and_installer_does_not_copy_it(self):
        self.assertFalse((H.ROOT / "dssreport" / "licence_tool.py").exists())
        self.assertFalse((H.ROOT / "dssreport" / "ed25519_sign.py").exists())
        self.assertNotIn("tools", (H.ROOT / "install-windows.cmd").read_text())

    def test_no_private_key_in_the_repo(self):
        for p in H.ROOT.rglob("*"):
            if ".git" in p.parts or not p.is_file():
                continue
            self.assertFalse(p.name.endswith(".private.key") or p.suffix == ".pem", str(p))
        self.assertIn("*.private.key", (H.ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
