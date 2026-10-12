"""The OPTIONAL online update check. Off by default.

What it does, and the only thing it does:
  1. When the user presses "Check for updates now", it makes one plain GET of a small SIGNED list
     (the manifest) from the address the user set in settings.
  2. It shows which newer versions are listed. Nothing is downloaded yet.
  3. When the user presses "Download", it makes one plain GET of that version's package file from the same
     folder, checks its fingerprint against the signed list, and then verifies the package exactly like a
     file supplied by hand (signature, safe paths, licence's update period, ...).
  4. The user then presses "Install". Nothing ever installs by itself.

It sends NOTHING about the user: no licence id, no customer name, no settings, no machine data, no
program version, no query string, no cookies. The request is a GET for the address itself with a fixed
generic header set. The address is one the user chose (the owner's own static page or release file); the
security comes only from the signatures, which are checked with the update public key built into the program.
"""

import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from . import ed25519, licence_keys
from . import licence as lic
from . import updates
from .errors import ConnectionFailed, DssError
from .paths import app_dir
from .settings import is_safe_url

MAX_MANIFEST_BYTES = 256 * 1024
MAX_PACKAGE_BYTES = updates.MAX_TOTAL_BYTES + 5 * 1024 * 1024
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.dssupdate")

#: the ONLY request headers ever sent. Nothing identifies the user, the licence or the computer.
REQUEST_HEADERS = {"User-Agent": "dss-report-update-check", "Accept": "*/*", "Connection": "close"}


class UpdateCheckError(DssError):
    pass


@dataclass
class Available:
    version: str
    release_date: date
    file: str
    sha256: str
    notes: str = ""


def downloads_dir() -> Path:
    return app_dir() / "downloads"


def is_valid_manifest_url(url: str) -> bool:
    """https (or this computer, for tests), no user name/password, no query string, no fragment."""
    if not is_safe_url(url):
        return False
    u = urlparse(url)
    return not (u.query or u.fragment or u.params)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get(url: str, limit: int, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, method="GET", headers=dict(REQUEST_HEADERS))
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise ConnectionFailed(f"The update address answered with an error (HTTP {exc.code}).")
    except (urllib.error.URLError, OSError) as exc:
        raise ConnectionFailed(f"Could not reach the update address ({getattr(exc, 'reason', exc)}).")
    if len(data) > limit:
        raise UpdateCheckError("The update address sent far more data than expected, so it was ignored.")
    return data


def _b64(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise UpdateCheckError("The update list is damaged (its signature is not readable).")


def verify_manifest(raw: bytes, keys: Optional[Dict[str, str]] = None) -> List[Available]:
    """Check the signed list and read it. Same key and same checks as an update file."""
    keys = licence_keys.UPDATE_PUBLIC_KEYS if keys is None else keys
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
        kid, payload_text, sig_text = str(doc["kid"]), doc["payload"], doc["signature"]
        if doc.get("v") != 1 or not isinstance(payload_text, str) or not isinstance(sig_text, str):
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, AttributeError):
        raise UpdateCheckError("The update address did not give a valid update list.")
    if not keys:
        raise UpdateCheckError("This copy of the program has no update key built in (a development build), "
                               "so an update list cannot be checked.")
    if kid not in keys:
        raise UpdateCheckError("The update list was signed with a key this program does not know.")
    try:
        public = bytes.fromhex(keys[kid])
    except ValueError:
        raise UpdateCheckError("This program's built-in update key is damaged.")
    payload = _b64(payload_text)
    if not ed25519.verify(public, payload, _b64(sig_text)):
        raise UpdateCheckError("The update list has been changed or was not made by Jay Rohrs. "
                               "The signature does not match, so it was ignored.")
    try:
        entries = json.loads(payload.decode("utf-8"))["versions"]
        out = []
        for e in entries:
            a = Available(version=str(e["version"]), release_date=date.fromisoformat(str(e["release_date"])),
                          file=str(e["file"]), sha256=str(e["sha256"]).lower(), notes=str(e.get("notes", ""))[:500])
            updates.parse_version(a.version)
            if not FILE_NAME.fullmatch(a.file) or not re.fullmatch(r"[0-9a-f]{64}", a.sha256):
                raise ValueError
            out.append(a)
    except (KeyError, ValueError, TypeError, UnicodeDecodeError, UpdateCheckError, updates.UpdateError):
        raise UpdateCheckError("The update list is damaged (its entries are not readable).")
    return out


def check(url: str, installed: str, keys: Optional[Dict[str, str]] = None) -> List[Available]:
    """GET the signed list and return the versions newer than `installed`, newest first."""
    if not is_valid_manifest_url(url):
        raise UpdateCheckError("The update address must start with https:// and have no extra parts "
                               "(no user name, query or #).")
    entries = verify_manifest(_get(url, MAX_MANIFEST_BYTES), keys)
    installed_v = updates.parse_version(installed)
    newer = [a for a in entries if updates.parse_version(a.version) > installed_v]
    return sorted(newer, key=lambda a: updates.parse_version(a.version), reverse=True)


def package_url(manifest_url: str, entry: Available) -> str:
    """The package lives next to the list: same site, same folder, a plain file name (checked above)."""
    u = urlparse(manifest_url)
    folder = u.path.rsplit("/", 1)[0]
    return urlunparse((u.scheme, u.netloc, f"{folder}/{entry.file}", "", "", ""))


def download(manifest_url: str, entry: Available, status: "lic.LicenceStatus", keys: Optional[Dict[str, str]] = None,
             dest_dir: Optional[Path] = None, installed: Optional[str] = None) -> Path:
    """Download one listed package and verify it fully. Keeps it only if everything passes. Does NOT install."""
    from . import __version__
    if not is_valid_manifest_url(manifest_url):
        raise UpdateCheckError("The update address must start with https:// and have no extra parts.")
    data = _get(package_url(manifest_url, entry), MAX_PACKAGE_BYTES)
    if hashlib.sha256(data).hexdigest() != entry.sha256:
        raise UpdateCheckError("The downloaded file does not match the fingerprint in the signed list, so it was thrown away.")
    dest_dir = Path(dest_dir) if dest_dir else downloads_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / entry.file
    part = dest_dir / (entry.file + ".part")
    part.write_bytes(data)
    try:
        manifest, _ = updates.read_package(part, keys)               # same checks as a file supplied by hand
        if (manifest.version, manifest.release_date) != (entry.version, entry.release_date):
            raise UpdateCheckError("The downloaded file is not the version the signed list promised, so it was thrown away.")
        updates.check_allowed(manifest, status, installed or __version__)
    except DssError:
        part.unlink(missing_ok=True)
        raise
    part.replace(final)
    return final


def downloaded_files(dest_dir: Optional[Path] = None) -> List[Path]:
    d = Path(dest_dir) if dest_dir else downloads_dir()
    try:
        return sorted(p for p in d.iterdir() if p.is_file() and FILE_NAME.fullmatch(p.name))
    except OSError:
        return []
