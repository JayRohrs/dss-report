"""Owner-controlled updates: signed packages checked and installed on this computer. No network."""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

from dssreport import licence as L
from dssreport import licence_keys, updates

from . import licence_helpers as H

sys.path.insert(0, str(H.ROOT / "tools"))
import update_tool  # noqa: E402

UKID = "test-update-key"
USECRET = os.urandom(32)
UPUB = H.ed25519_sign.public_from_secret(USECRET).hex()
OTHER_USECRET = os.urandom(32)
TODAY = date(2026, 10, 12)

OLD = {"dssreport/__init__.py": b'__version__ = "0.3.0"\n', "dssreport/thing.py": b"VALUE = 1\n",
       "launcher.pyw": b"# launcher v1\n"}
NEW = {"dssreport/__init__.py": b'__version__ = "0.4.0"\n', "dssreport/thing.py": b"VALUE = 2\n",
       "dssreport/extra.py": b"EXTRA = True\n", "launcher.pyw": b"# launcher v2\n"}


def update_keys(extra=None):
    return mock.patch.dict(licence_keys.UPDATE_PUBLIC_KEYS, {UKID: UPUB, **(extra or {})}, clear=True)


def status(updates_until=date(2099, 1, 1), expires=date(2099, 1, 1), **kw):
    lic = L.Licence("Sample Customer Ltd", 1, expires, updates_until, frozenset(L.CURRENT_FEATURES), licence_id="lic-aaa111")
    return L.status_for(lic, TODAY)


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pdir, self.home = self.tmp / "program", self.tmp / "home"
        self.pdir.mkdir()
        self.home.mkdir()
        for rel, data in OLD.items():
            (self.pdir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pdir / rel).write_bytes(data)
        (self.home / "settings.json").write_text('{"keep": "me"}')
        (self.home / "reports").mkdir()
        (self.home / "reports" / "r.html").write_text("an old report")
        k = update_keys()
        k.__enter__()
        self.addCleanup(lambda: k.__exit__(None, None, None))

    def build(self, files=None, version="0.4.0", release=date(2026, 10, 1), secret=None, kid=UKID, **kw):
        out = self.tmp / f"u-{len(list(self.tmp.glob('u-*')))}.dssupdate"
        return update_tool.build_update(secret or USECRET, kid, files if files is not None else NEW, version, release, out, **kw)

    def apply(self, path, st=None, installed="0.3.0"):
        return updates.apply_update(path, st or status(), self.pdir, self.home, installed=installed)

    def tree(self):
        return {p.relative_to(self.pdir).as_posix(): p.read_bytes() for p in self.pdir.rglob("*") if p.is_file()}


class Installing(Env):
    def test_a_good_update_replaces_only_program_files_and_keeps_a_backup(self):
        msg = self.apply(self.build())
        self.assertIn("Updated from version 0.3.0 to 0.4.0", msg)
        self.assertEqual(self.tree(), NEW)
        self.assertEqual((self.home / "settings.json").read_text(), '{"keep": "me"}')
        self.assertEqual((self.home / "reports" / "r.html").read_text(), "an old report")
        self.assertTrue(updates.has_backup(self.home))

    def test_rollback_restores_the_old_files_and_removes_the_new_ones(self):
        self.apply(self.build())
        msg = updates.rollback(self.pdir, self.home)
        self.assertIn("Went back to version 0.3.0", msg)
        self.assertEqual(self.tree(), OLD)
        with self.assertRaises(updates.UpdateError) as cm:
            updates.rollback(self.pdir, self.home)
        self.assertIn("no earlier version", str(cm.exception))

    def test_a_failure_part_way_puts_everything_back(self):
        real = os.replace
        calls = {"n": 0}

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("disk full")
            return real(a, b)
        with mock.patch("dssreport.updates.os.replace", flaky):
            with self.assertRaises(updates.UpdateError) as cm:
                self.apply(self.build())
        self.assertIn("put back exactly as it was", str(cm.exception))
        self.assertEqual(self.tree(), OLD)                  # exactly as before, no half-written leftovers

    def test_files_listed_for_removal_are_removed_and_restored_on_rollback(self):
        (self.pdir / "dssreport" / "old.py").write_text("OLD = 1\n")
        self.apply(self.build(remove=["dssreport/old.py"]))
        self.assertFalse((self.pdir / "dssreport" / "old.py").exists())
        updates.rollback(self.pdir, self.home)
        self.assertTrue((self.pdir / "dssreport" / "old.py").exists())

    def test_a_source_checkout_is_not_updated(self):
        (self.pdir / ".git").mkdir()
        with self.assertRaises(updates.UpdateError) as cm:
            self.apply(self.build())
        self.assertIn("source checkout", str(cm.exception))


class Signature(Env):
    def refused(self, path, needle):
        before = self.tree()
        with self.assertRaises(updates.UpdateError) as cm:
            self.apply(path)
        self.assertIn(needle, str(cm.exception))
        self.assertEqual(self.tree(), before)               # nothing was changed
        self.assertFalse(updates.has_backup(self.home))

    def rewrite(self, path, edit):
        out = self.tmp / "tampered.dssupdate"
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                dst.writestr(info, edit(info.filename, src.read(info)))
        return out

    def test_a_changed_program_file_is_refused(self):
        bad = self.rewrite(self.build(), lambda n, d: d + b"\nimport os\n" if n.endswith("thing.py") else d)
        self.refused(bad, "does not match its signed fingerprint")

    def test_a_changed_manifest_is_refused(self):
        bad = self.rewrite(self.build(), lambda n, d: d.replace(b"0.4.0", b"9.9.9") if n == "manifest.json" else d)
        self.refused(bad, "changed or was not made by Jay Rohrs")

    def test_unsigned_wrong_key_unknown_key_and_no_key(self):
        unsigned = self.rewrite(self.build(), lambda n, d: d)
        with zipfile.ZipFile(unsigned) as z:
            names = [i for i in z.infolist() if i.filename != "manifest.sig"]
            data = {i.filename: z.read(i) for i in names}
        out = self.tmp / "unsigned.dssupdate"
        with zipfile.ZipFile(out, "w") as z:
            for k, v in data.items():
                z.writestr(k, v)
        self.refused(out, "not signed")
        self.refused(self.build(secret=OTHER_USECRET), "changed or was not made by Jay Rohrs")
        self.refused(self.build(secret=OTHER_USECRET, kid="stranger"), "key this program does not know")
        with mock.patch.dict(licence_keys.UPDATE_PUBLIC_KEYS, {}, clear=True):
            self.refused(self.build(), "no update key built in")

    def test_a_licence_key_cannot_sign_an_update(self):
        with H.trusted_keys():
            self.assertNotIn(H.KID, licence_keys.UPDATE_PUBLIC_KEYS)
            self.refused(self.build(secret=H.SECRET, kid=H.KID), "key this program does not know")

    def test_not_an_update_file(self):
        p = self.tmp / "x.dssupdate"
        p.write_bytes(b"not a zip")
        self.refused(p, "not an update file")


class Unsafe(Env):
    """Even a correctly signed package may not write outside the program."""

    def test_unsafe_or_out_of_bounds_paths_are_refused_before_anything_is_written(self):
        for bad in ("../evil.py", "/etc/evil.py", "dssreport/../../evil.py", "C:/evil.py", "dssreport\\evil.py",
                    "settings.json", "tests/evil.py", "dssreport//x.py", "dssreport/./x.py"):
            files = dict(NEW)
            files[bad] = b"x = 1\n"
            before = self.tree()
            with self.assertRaises(updates.UpdateError, msg=bad):
                self.apply(self.build(files=files))
            self.assertEqual(self.tree(), before, bad)
            self.assertFalse(updates.has_backup(self.home))

    def test_a_broken_python_file_is_refused(self):
        files = dict(NEW)
        files["dssreport/thing.py"] = b"def broken(:\n"
        with self.assertRaises(updates.UpdateError) as cm:
            self.apply(self.build(files=files))
        self.assertIn("is broken", str(cm.exception))
        self.assertEqual(self.tree(), OLD)

    def test_extra_unlisted_files_and_symlinks_are_refused(self):
        good = self.build()
        out = self.tmp / "extra.dssupdate"
        with zipfile.ZipFile(good) as src, zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                dst.writestr(info, src.read(info))
            dst.writestr("files/dssreport/sneaky.py", b"x = 1\n")
        with self.assertRaises(updates.UpdateError) as cm:
            self.apply(out)
        self.assertIn("does not mention", str(cm.exception))
        link = self.tmp / "link.dssupdate"
        with zipfile.ZipFile(good) as src, zipfile.ZipFile(link, "w") as dst:
            for info in src.infolist():
                if info.filename.endswith("thing.py"):
                    info.external_attr = (0o120777 << 16)
                dst.writestr(info, src.read(info))
        with self.assertRaises(updates.UpdateError) as cm:
            self.apply(link)
        self.assertIn("link", str(cm.exception))

    def test_oversized_packages_are_refused(self):
        files = dict(NEW)
        files["docs/big.md"] = b"x" * (updates.MAX_FILE_BYTES + 1)
        with self.assertRaises(updates.UpdateError) as cm:
            self.apply(self.build(files=files))
        self.assertIn("far bigger", str(cm.exception))


class OwnerControls(Env):
    def refused(self, path, st, needle, installed="0.3.0"):
        with self.assertRaises(updates.UpdateError) as cm:
            self.apply(path, st, installed)
        self.assertIn(needle, str(cm.exception))
        self.assertEqual(self.tree(), OLD)

    def test_needs_a_valid_licence(self):
        for state, msg in ((L.NOT_FOUND, "Licence: not found."), (L.INVALID, "Licence: not valid.")):
            self.refused(self.build(), L.LicenceStatus(state, msg), "Updates need a valid licence file")
        self.refused(self.build(), L.demo_status(), "Updates need a valid licence file")

    def test_release_must_be_inside_the_updates_period(self):
        self.refused(self.build(release=date(2026, 10, 1)), status(updates_until=date(2026, 9, 30)),
                     "includes updates until 2026-09-30")
        self.apply(self.build(release=date(2026, 10, 1)), status(updates_until=date(2026, 10, 1)))   # last day counts

    def test_an_expired_licence_can_still_take_an_update_released_inside_its_updates_period(self):
        st = status(expires=date(2026, 1, 1), updates_until=date(2026, 12, 31))
        self.assertEqual(st.state, L.EXPIRED)
        self.apply(self.build(), st)
        self.assertEqual(self.tree(), NEW)

    def test_owner_can_address_an_update_to_particular_licences(self):
        only_others = self.build(licence_ids=["lic-zzz999"])
        self.refused(only_others, status(), "has not been released to your licence")
        self.apply(self.build(licence_ids=["lic-aaa111", "lic-zzz999"]), status())
        self.assertEqual(self.tree(), NEW)

    def test_versions_must_move_forward_and_respect_the_minimum(self):
        self.refused(self.build(version="0.3.0"), status(), "nothing to install")
        self.refused(self.build(version="0.2.9"), status(), "nothing to install")
        self.refused(self.build(min_version="0.3.5"), status(), "Install version 0.3.5 first")
        with self.assertRaises(updates.UpdateError):          # a bad version number can't even be packaged
            self.build(version="not-a-version")

    def test_updating_never_blocks_running_reports_or_changes_the_licence(self):
        st = status(updates_until=date(2020, 1, 1))
        self.refused(self.build(), st, "Renew to get it")
        self.assertEqual((self.home / "reports" / "r.html").read_text(), "an old report")


class NoNetworkAndNoKeys(unittest.TestCase):
    def test_the_update_module_makes_no_network_calls(self):
        text = (H.ROOT / "dssreport" / "updates.py").read_text()
        for word in ("urllib", "socket", "http", "requests", "ftp"):
            self.assertNotRegex(text, rf"^\s*(import|from)\s+{word}", word)
        self.assertNotIn("urlopen", text)

    def test_the_repo_ships_no_update_key_and_the_tool_is_outside_the_package(self):
        self.assertEqual(licence_keys.UPDATE_PUBLIC_KEYS, {})
        self.assertFalse((H.ROOT / "dssreport" / "update_tool.py").exists())
        self.assertNotIn("tools", (H.ROOT / "install-windows.cmd").read_text())

    def test_the_tool_builds_from_the_real_source_tree_and_the_result_installs(self):
        files = update_tool.collect(H.ROOT)
        self.assertIn("dssreport/updates.py", files)
        self.assertNotIn("tools/update_tool.py", files)
        self.assertFalse(any("tests/" in f or f.startswith("tools") for f in files))
        out = Path(tempfile.mkdtemp()) / "real.dssupdate"
        update_tool.build_update(USECRET, UKID, files, "9.0.0", date(2026, 10, 1), out)
        with update_keys():
            manifest, contents = updates.read_package(out)
        self.assertEqual(manifest.version, "9.0.0")
        self.assertEqual(set(contents), set(files))


class CommandLine(Env):
    def test_update_install_and_status_and_rollback_from_the_command_line(self):
        import io
        from contextlib import redirect_stdout
        from dssreport import cli
        out = io.StringIO()
        with mock.patch("dssreport.updates.program_dir", lambda: self.pdir), \
                mock.patch.dict("os.environ", {"DSSREPORT_HOME": str(self.home)}), \
                mock.patch("dssreport.licence.current_status", lambda *a, **k: status()), \
                mock.patch("dssreport.__version__", "0.3.0"), redirect_stdout(out):
            self.assertEqual(cli.main(["update", "install", str(self.build())]), 0)
            self.assertEqual(self.tree(), NEW)
            cli.main(["update", "status"])
            self.assertEqual(cli.main(["update", "rollback"]), 0)
        self.assertEqual(self.tree(), OLD)
        self.assertIn("Updated from version 0.3.0 to 0.4.0", out.getvalue())
        self.assertIn("An earlier version is saved", out.getvalue())


if __name__ == "__main__":
    unittest.main()


class LifetimeEntitlement(Env):
    def lifetime(self, **kw):
        return L.status_for(L.Licence("Sample Customer Ltd", 1, kw.get("expires", date(2099, 1, 1)), None,
                                      frozenset(L.CURRENT_FEATURES), licence_id="lic-aaa111"), TODAY)

    def test_a_lifetime_licence_takes_any_update_whatever_its_release_date(self):
        self.apply(self.build(release=date(2090, 1, 1)), self.lifetime())
        self.assertEqual(self.tree(), NEW)

    def test_lifetime_still_respects_the_owner_s_other_controls(self):
        with self.assertRaises(updates.UpdateError) as cm:
            self.apply(self.build(licence_ids=["someone-else"]), self.lifetime())
        self.assertIn("not been released to your licence", str(cm.exception))
        with self.assertRaises(updates.UpdateError):
            self.apply(self.build(min_version="0.3.5"), self.lifetime())

    def test_dated_behaviour_is_unchanged(self):
        with self.assertRaises(updates.UpdateError):
            self.apply(self.build(release=date(2026, 10, 1)), status(updates_until=date(2026, 9, 30)))
