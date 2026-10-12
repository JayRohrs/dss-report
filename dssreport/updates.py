"""Updates that the OWNER controls: signed update files, checked and installed on this computer.

How it works (docs/UPDATES.md):
  * The owner builds an update package with tools/update_tool.py and signs it with a private key only the
    owner has. The owner decides who is sent one and when. Nothing here goes online: no update check, no
    download, no phone-home. The file reaches the customer however the owner chooses (email, a link, a USB stick).
  * This program checks the signature with a public key built into it, then checks the package is allowed
    for THIS licence: released inside the licence's "updates until" date, and (if the owner restricted it)
    addressed to this licence. Then it replaces only the program files, keeps a backup, and can roll back.
  * Settings, saved passwords, mapping files, licences and every report are never touched.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from . import ed25519
from . import licence as lic
from . import licence_keys
from .errors import DssError
from .paths import app_dir

MAX_FILES = 600
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MANIFEST, SIGNATURE, PREFIX = "manifest.json", "manifest.sig", "files/"

#: the only places an update may write (relative to the program folder)
ALLOWED_DIRS = ("dssreport/", "docs/")
ALLOWED_FILES = ("launcher.pyw", "r365_mapping.example.toml", "README.md", "SECURITY.md")


class UpdateError(DssError):
    """The update could not be installed. The message is plain words and nothing was changed."""


@dataclass
class Manifest:
    version: str
    release_date: date
    kid: str
    files: Dict[str, str]
    remove: List[str] = field(default_factory=list)
    min_version: str = ""
    licence_ids: List[str] = field(default_factory=list)   # empty = any licence
    notes: str = ""


def parse_version(text: str) -> Tuple[int, ...]:
    if not isinstance(text, str) or not re.fullmatch(r"\d{1,4}(\.\d{1,4}){1,3}", text):
        raise UpdateError("The update has a version number this program cannot read.")
    return tuple(int(x) for x in text.split("."))


def _safe_path(rel: str) -> str:
    """A path inside the program folder that an update is allowed to write. Raises if not."""
    if (not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel or ":" in rel
            or rel.startswith("/") or any(part in ("", ".", "..") for part in rel.split("/"))):
        raise UpdateError("The update file contains an unsafe file path, so it was refused.")
    p = PurePosixPath(rel).as_posix()
    if not (p in ALLOWED_FILES or any(p.startswith(d) for d in ALLOWED_DIRS)):
        raise UpdateError("The update file tries to change something outside the program itself, so it was refused.")
    return p


def _b64(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
    except (ValueError, TypeError):
        raise UpdateError("The update file is damaged (its signature is not readable).")


def read_package(path, keys: Optional[Dict[str, str]] = None) -> Tuple[Manifest, Dict[str, bytes]]:
    """Open an update file and verify EVERYTHING before anything is written anywhere.
    Returns the manifest and the file contents. Raises UpdateError in plain words."""
    keys = licence_keys.UPDATE_PUBLIC_KEYS if keys is None else keys
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        raise UpdateError("That is not an update file (it could not be opened).")
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES + 2:
            raise UpdateError("The update file has too many files, so it was refused.")
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES or any(i.file_size > MAX_FILE_BYTES for i in infos):
            raise UpdateError("The update file is far bigger than a program update should be, so it was refused.")
        names = {i.filename for i in infos}
        if MANIFEST not in names or SIGNATURE not in names:
            raise UpdateError("This update file is not signed, so it cannot be installed.")
        manifest_bytes, sig_text = zf.read(MANIFEST), zf.read(SIGNATURE).decode("ascii", "replace")
        try:
            raw = json.loads(manifest_bytes.decode("utf-8"))
            kid = str(raw["kid"])
        except (ValueError, KeyError, UnicodeDecodeError, TypeError):
            raise UpdateError("The update file is damaged (its details cannot be read).")
        if not keys:
            raise UpdateError("This copy of the program has no update key built in (a development build), "
                              "so no update can be checked.")
        if kid not in keys:
            raise UpdateError("This update was signed with a key this program does not know.")
        try:
            public = bytes.fromhex(keys[kid])
        except ValueError:
            raise UpdateError("This program's built-in update key is damaged.")
        if not ed25519.verify(public, manifest_bytes, _b64(sig_text)):
            raise UpdateError("This update has been changed or was not made by Jay Rohrs. The signature does not match.")
        try:
            files = {_safe_path(k): str(v) for k, v in raw["files"].items()}
            manifest = Manifest(
                version=str(raw["version"]), release_date=date.fromisoformat(str(raw["release_date"])), kid=kid,
                files=files, remove=[_safe_path(x) for x in raw.get("remove", [])],
                min_version=str(raw.get("min_version", "")),
                licence_ids=[str(x) for x in raw.get("licence_ids", [])], notes=str(raw.get("notes", ""))[:2000])
        except (KeyError, ValueError, TypeError, AttributeError):
            raise UpdateError("The update file is damaged (its details are incomplete).")
        parse_version(manifest.version)
        if manifest.min_version:
            parse_version(manifest.min_version)
        # the package must contain exactly what the signed manifest lists, byte for byte
        extra = {n for n in names if n not in (MANIFEST, SIGNATURE) and not n.endswith("/")} - {PREFIX + f for f in files}
        if extra:
            raise UpdateError("The update file contains files its signed list does not mention, so it was refused.")
        contents: Dict[str, bytes] = {}
        for rel, want in files.items():
            info = zf.getinfo(PREFIX + rel) if (PREFIX + rel) in names else None
            if info is None:
                raise UpdateError("The update file is missing a file its signed list names.")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError("The update file contains a link instead of a file, so it was refused.")
            data = zf.read(info)
            if hashlib.sha256(data).hexdigest() != want:
                raise UpdateError("A file inside the update does not match its signed fingerprint, so it was refused.")
            if rel.endswith((".py", ".pyw")):
                try:
                    compile(data, rel, "exec", dont_inherit=True)
                except (SyntaxError, ValueError):
                    raise UpdateError("A program file inside the update is broken, so it was refused.")
            contents[rel] = data
    return manifest, contents


def check_allowed(m: Manifest, status: "lic.LicenceStatus", installed: str) -> None:
    """Is THIS computer allowed to take this update? (The owner's controls.) Raises UpdateError."""
    if parse_version(m.version) <= parse_version(installed):
        raise UpdateError(f"This is version {m.version} and you already have {installed}, so there is nothing to install.")
    if m.min_version and parse_version(installed) < parse_version(m.min_version):
        raise UpdateError(f"Install version {m.min_version} first; this update builds on it.")
    if not status.licence or status.state not in (lic.OK, lic.EXPIRED):
        raise UpdateError("Updates need a valid licence file. " + status.message)
    L = status.licence
    if m.licence_ids and L.licence_id not in m.licence_ids:
        raise UpdateError("This update has not been released to your licence. Contact Jay Rohrs.")
    if not L.updates_lifetime and m.release_date > L.updates_until:
        raise UpdateError(f"Your licence includes updates until {L.updates_until.isoformat()}, and this update was "
                          f"released on {m.release_date.isoformat()}. Renew to get it. Your current version keeps "
                          "working and all your reports are unchanged.")


def program_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _refuse_source_checkout(pdir: Path) -> None:
    if (pdir / ".git").exists():
        raise UpdateError("This looks like a source checkout, not an installed copy, so it is not updated this way.")


def _backup_dir(home: Path) -> Path:
    return home / "previous"


def apply_update(path, status: "lic.LicenceStatus", pdir: Optional[Path] = None, home: Optional[Path] = None,
                 keys: Optional[Dict[str, str]] = None, installed: Optional[str] = None) -> str:
    """Install an update file. Nothing is written unless every check passes; if writing fails part-way,
    everything is put back. Returns a plain sentence."""
    from . import __version__
    pdir = Path(pdir) if pdir else program_dir()
    home = Path(home) if home else app_dir()
    installed = installed or __version__
    _refuse_source_checkout(pdir)
    manifest, contents = read_package(path, keys)
    check_allowed(manifest, status, installed)

    backup = _backup_dir(home)
    tmp_backup = home / "previous.new"
    if tmp_backup.exists():
        shutil.rmtree(tmp_backup)
    (tmp_backup / "files").mkdir(parents=True)
    replaced, added = [], []
    targets = list(contents) + [r for r in manifest.remove]
    for rel in targets:
        cur = pdir / rel
        if cur.is_file():
            dest = tmp_backup / "files" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cur, dest)
            replaced.append(rel)
        elif rel in contents:
            added.append(rel)
    (tmp_backup / "backup.json").write_text(json.dumps(
        {"from_version": installed, "to_version": manifest.version, "replaced": replaced, "added": added}), encoding="utf-8")
    try:
        for rel, data in contents.items():
            dest = pdir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".dssnew")
            part.write_bytes(data)
            os.replace(part, dest)
        for rel in manifest.remove:
            (pdir / rel).unlink(missing_ok=True)
    except Exception:
        for rel in contents:
            (pdir / rel).with_name(Path(rel).name + ".dssnew").unlink(missing_ok=True)
        _restore(tmp_backup, pdir)
        raise UpdateError("The update could not be written, so your program was put back exactly as it was.")
    if backup.exists():
        shutil.rmtree(backup)
    os.replace(tmp_backup, backup)
    return (f"Updated from version {installed} to {manifest.version}. Close this program and open it again "
            "to use the new version. Your settings, saved passwords, licence and reports were not touched.")


def _restore(backup: Path, pdir: Path) -> None:
    info = json.loads((backup / "backup.json").read_text(encoding="utf-8"))
    for rel in info["replaced"]:
        src, dest = backup / "files" / rel, pdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    for rel in info["added"]:
        (pdir / rel).unlink(missing_ok=True)


def rollback(pdir: Optional[Path] = None, home: Optional[Path] = None) -> str:
    """Go back to the version that was installed before the last update."""
    pdir = Path(pdir) if pdir else program_dir()
    home = Path(home) if home else app_dir()
    _refuse_source_checkout(pdir)
    backup = _backup_dir(home)
    if not (backup / "backup.json").exists():
        raise UpdateError("There is no earlier version saved to go back to.")
    info = json.loads((backup / "backup.json").read_text(encoding="utf-8"))
    _restore(backup, pdir)
    shutil.rmtree(backup)
    return (f"Went back to version {info['from_version']}. Close this program and open it again. "
            "Your settings, licence and reports were not touched.")


def has_backup(home: Optional[Path] = None) -> bool:
    return (_backup_dir(Path(home) if home else app_dir()) / "backup.json").exists()
