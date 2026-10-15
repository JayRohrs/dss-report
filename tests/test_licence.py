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
        self.assertEqual(lic.features, frozenset(L.CURRENT_FEATURES))

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
        for f in L.CURRENT_FEATURES:
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
        for f in L.CURRENT_FEATURES:
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


FAST = {"n": 2 ** 10, "r": 8, "p": 1}      # cheap scrypt settings so tests are quick
PASS = "a long throw-away passphrase 123"


class Tool(unittest.TestCase):
    def test_tool_round_trip_with_a_passphrase_protected_key(self):
        import licence_tool
        out = Path(tempfile.mkdtemp())
        pub = licence_tool.keygen(out, "unit-key", PASS, scrypt_params=FAST)
        key_file = out / "unit-key.private.key"
        lic_file = out / "licence.json"
        args = ["sign", "--private-key", str(key_file), "--kid", "unit-key", "--customer", "Round Trip Co",
                "--instances", "1", "--expires", "2099-01-01", "--updates-until", "2099-01-01", "--out", str(lic_file)]
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            licence_tool.main(args, passphrase=PASS)
        lic = L.verify_licence(lic_file.read_bytes(), {"unit-key": pub})
        self.assertEqual((lic.customer, lic.instances), ("Round Trip Co", 1))

    def test_private_key_file_is_not_plain_and_needs_the_passphrase(self):
        import json as _json
        import licence_tool
        out = Path(tempfile.mkdtemp())
        pub = licence_tool.keygen(out, "k", PASS, scrypt_params=FAST)
        text = (out / "k.private.key").read_text()
        doc = _json.loads(text)
        self.assertEqual(doc["kdf"], "scrypt")
        secret = licence_tool.unprotect_secret(text, PASS)
        self.assertEqual(len(secret), 32)
        self.assertEqual(licence_tool.ed25519_sign.public_from_secret(secret).hex(), pub)
        self.assertNotIn(secret.hex(), text)                              # the raw key is not in the file
        with self.assertRaises(SystemExit) as cm:
            licence_tool.unprotect_secret(text, "the wrong passphrase!!")
        self.assertIn("Wrong passphrase", str(cm.exception))
        doc["ct"] = ("00" if doc["ct"][:2] != "00" else "ff") + doc["ct"][2:]       # a changed file is caught too
        with self.assertRaises(SystemExit):
            licence_tool.unprotect_secret(_json.dumps(doc), PASS)

    def test_empty_or_short_passphrases_are_refused(self):
        import licence_tool
        for bad in ("", "short"):
            with self.assertRaises(SystemExit) as cm:
                licence_tool.keygen(Path(tempfile.mkdtemp()), "k", bad, scrypt_params=FAST)
            self.assertIn("passphrase", str(cm.exception).lower())

    def test_refuses_to_keep_the_private_key_in_a_git_folder_and_bad_flags(self):
        import licence_tool
        with self.assertRaises(SystemExit):
            licence_tool.keygen(H.ROOT / "tools" / "keys", "k", PASS, scrypt_params=FAST)   # inside this repo
        out = Path(tempfile.mkdtemp())
        licence_tool.keygen(out, "k", PASS, scrypt_params=FAST)
        with self.assertRaises(SystemExit):
            licence_tool.main(["sign", "--private-key", str(out / "k.private.key"), "--kid", "k", "--customer", "C",
                               "--instances", "1", "--expires", "2099-01-01", "--updates-until", "2099-01-01",
                               "--features", "bogus", "--out", str(out / "x.json")], passphrase=PASS)

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


class RenewalNotice(unittest.TestCase):
    def notice(self, days_left):
        from datetime import timedelta
        lic = L.Licence("X", 1, TODAY + timedelta(days=days_left), TODAY, frozenset())
        return L.status_for(lic, TODAY).notice

    def test_no_reminder_until_30_days_before_the_end(self):
        self.assertEqual(self.notice(31), "")
        self.assertEqual(self.notice(200), "")

    def test_reminder_starts_at_30_days(self):
        self.assertTrue(self.notice(30).startswith("Licence expires in 30 days (on 2026-07-01)."))
        self.assertTrue(self.notice(2).startswith("Licence expires in 2 days"))
        self.assertTrue(self.notice(1).startswith("Licence expires in 1 day ("))
        self.assertTrue(self.notice(0).startswith("Licence expires today"))

    def test_after_the_end_the_notice_says_renew_to_add_connections_or_get_updates(self):
        self.assertEqual(self.notice(-1), "Licence expired on 2026-05-31 \u2014 renew to add connections or get updates.")
        self.assertEqual(self.notice(-400), "Licence expired on 2025-04-27 \u2014 renew to add connections or get updates.")

    def test_no_notice_without_a_licence_or_in_demo_mode(self):
        self.assertEqual(L.demo_status().notice, "")
        self.assertEqual(L.LicenceStatus(L.NOT_FOUND, "Licence: not found.").notice, "")
        self.assertEqual(L.LicenceStatus(L.INVALID, "Licence: not valid.").notice, "")

    def test_the_reminder_blocks_nothing(self):
        from datetime import timedelta
        lic = L.Licence("X", 2, TODAY + timedelta(days=3), TODAY, frozenset(L.CURRENT_FEATURES))
        s = L.status_for(lic, TODAY)
        self.assertEqual(s.state, L.OK)
        self.assertIsNone(s.can_add_connection(1))
        for f in L.CURRENT_FEATURES:
            self.assertTrue(s.has(f))


class Unlimited(unittest.TestCase):
    def read(self, instances):
        with H.trusted_keys():
            return L.verify_licence(H.make(instances=instances))

    def test_explicit_unlimited_is_read_and_everything_else_is_a_number(self):
        lic = self.read("unlimited")
        self.assertTrue(lic.unlimited)
        self.assertIsNone(lic.instances)
        self.assertFalse(self.read(0).unlimited)
        self.assertEqual(self.read(7).instances, 7)

    def test_anything_else_is_a_damaged_licence_not_silently_unlimited(self):
        for bad in ("lots", "Unlimited ", -1, 1.5, True, None, [], "0"):
            with self.assertRaises(L.LicenceError, msg=repr(bad)):
                self.read(bad)

    def test_unlimited_allows_any_number_and_displays_plainly(self):
        s = L.status_for(self.read("unlimited"), TODAY)
        self.assertEqual(s.instances_allowed, float("inf"))
        for n in (0, 1, 50, 5000):
            self.assertIsNone(s.can_add_connection(n))
        self.assertEqual(s.connections_text(0), "unlimited (0 in use)")
        self.assertEqual(s.connections_text(12), "unlimited (12 in use)")
        self.assertEqual(L.instance_overflow(s, 99), 0)

    def test_numbers_still_display_as_before(self):
        s = L.status_for(self.read(2), TODAY)
        self.assertEqual(s.connections_text(1), "1 used of 2 allowed")
        self.assertEqual(s.connections_text(3), "3 used of 2 allowed (over the limit)")

    def test_one_connection_licence_and_zero_connection_licence(self):
        s1 = L.status_for(self.read(1), TODAY)
        self.assertIsNone(s1.can_add_connection(0))
        self.assertIn("over limit", s1.can_add_connection(1))
        s0 = L.status_for(self.read(0), TODAY)
        self.assertIn("allows 0 connections", s0.can_add_connection(0))

    def test_the_tool_signs_unlimited_and_refuses_junk(self):
        import licence_tool
        out = Path(tempfile.mkdtemp())
        pub = licence_tool.keygen(out, "k", PASS, scrypt_params=FAST)
        import io
        from contextlib import redirect_stdout
        base = ["sign", "--private-key", str(out / "k.private.key"), "--kid", "k", "--customer", "Own Company Sample",
                "--expires", "2099-01-01", "--updates-until", "2099-01-01", "--out", str(out / "l.json")]
        with redirect_stdout(io.StringIO()):
            licence_tool.main(base + ["--instances", "unlimited"], passphrase=PASS)
        self.assertTrue(L.verify_licence((out / "l.json").read_bytes(), {"k": pub}).unlimited)
        for junk in ("lots", "-3", "1.5"):
            with self.assertRaises(SystemExit):
                licence_tool.main(base + ["--instances", junk], passphrase=PASS)


class FlagsAndConnectionsComeOnlyFromTheFile(unittest.TestCase):
    def test_flags_are_exactly_what_the_file_lists(self):
        with H.trusted_keys():
            for feats in ([], ["email_m365"], list(L.ALL_FEATURES)):
                lic = L.verify_licence(H.make(features=feats))
                s = L.status_for(lic, TODAY)
                self.assertEqual({f for f in L.ALL_FEATURES if s.has(f)}, set(feats))

    def test_no_price_or_tier_names_in_the_program_or_the_tool(self):
        import re
        words = re.compile(r"\b(price|prices|pricing|priced|tier|tiers|premium|enterprise|subscription|"
                           r"freemium|basic plan|pro plan|per month|per year)\b", re.I)
        for folder in ("dssreport", "tools"):
            for p in (H.ROOT / folder).rglob("*.py"):
                m = words.search(p.read_text())
                self.assertIsNone(m, f"{p} mentions '{m.group(0) if m else ''}'")

    def test_the_only_connection_numbers_in_code_are_not_a_default_allowance(self):
        # no licence -> zero connections: nothing in the code grants a number of its own
        s = L.LicenceStatus(L.NOT_FOUND, "Licence: not found.")
        self.assertEqual(s.instances_allowed, 0)
        self.assertEqual(L.demo_status().instances_allowed, 0)


if __name__ == "__main__":
    unittest.main()


class LifetimeUpdates(unittest.TestCase):
    def signed(self, value) -> bytes:
        """A genuinely signed licence whose updates_until is whatever we put there (to test the reader)."""
        import licence_tool
        payload = {"customer": "Sample", "instances": 1, "expires": "2099-01-01", "updates_until": value,
                   "features": [], "issued": "2026-01-01", "licence_id": "x"}
        pb = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        doc = {"v": 1, "kid": H.KID, "payload": licence_tool.b64(pb),
               "signature": licence_tool.b64(licence_tool.ed25519_sign.sign(H.SECRET, pb))}
        return json.dumps(doc).encode()

    def read(self, value):
        with H.trusted_keys():
            return L.verify_licence(self.signed(value if not isinstance(value, date) else value.isoformat()))

    def test_lifetime_is_read_dated_values_still_work(self):
        lic = self.read("lifetime")
        self.assertTrue(lic.updates_lifetime)
        self.assertIsNone(lic.updates_until)
        self.assertEqual(lic.updates_text(), "lifetime")
        d = self.read(date(2027, 3, 31))
        self.assertFalse(d.updates_lifetime)
        self.assertEqual(d.updates_text(), "until 2027-03-31")

    def test_anything_else_is_damaged_not_silently_lifetime(self):
        for bad in ("Lifetime ", "forever", "unlimited", "", None, 5, True, "2027-13-01"):
            with self.assertRaises(L.LicenceError, msg=repr(bad)):
                self.read(bad)

    def test_lifetime_covers_every_release_date_and_survives_expiry(self):
        s = L.status_for(self.read("lifetime"), TODAY)
        for d in (date(2020, 1, 1), date(2099, 1, 1), date(9999, 1, 1)):
            self.assertTrue(s.updates_covered(d))
        from datetime import timedelta
        lic = L.Licence("X", 1, TODAY - timedelta(days=5), None, frozenset())
        self.assertEqual(L.status_for(lic, TODAY).state, L.EXPIRED)               # licence expired, updates still lifetime
        self.assertTrue(L.status_for(lic, TODAY).updates_covered(date(2099, 1, 1)))

    def test_the_tool_signs_lifetime_and_refuses_junk(self):
        import io
        from contextlib import redirect_stdout
        import licence_tool
        out = Path(tempfile.mkdtemp())
        pub = licence_tool.keygen(out, "k", PASS, scrypt_params=FAST)
        base = ["sign", "--private-key", str(out / "k.private.key"), "--kid", "k", "--customer", "Own Company Sample",
                "--instances", "1", "--expires", "2099-01-01", "--out", str(out / "l.json")]
        with redirect_stdout(io.StringIO()):
            licence_tool.main(base + ["--updates-until", "lifetime"], passphrase=PASS)
        self.assertTrue(L.verify_licence((out / "l.json").read_bytes(), {"k": pub}).updates_lifetime)
        for junk in ("forever", "2027-99-99"):
            with self.assertRaises(SystemExit):
                licence_tool.main(base + ["--updates-until", junk], passphrase=PASS)
