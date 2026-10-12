#!/usr/bin/env python3
"""Build and sign an update package. Kept OUT of the shipped program (like licence_tool.py).

    python tools/update_tool.py make --private-key <key file> --kid 2026-u --source <repo folder> \\
        --version 0.4.0 --release-date 2026-11-01 [--min-version 0.3.0] [--licence-ids id1,id2] \\
        [--notes "text"] --out dss-update-0.4.0.dssupdate

You decide who gets the file and when. Nothing is sent anywhere by the program. `--licence-ids` limits the
update to particular licences (find an id with `licence_tool.py show`); without it any licence whose
"updates until" date covers --release-date can install it. Use a DIFFERENT key pair from the licence key
(`licence_tool.py keygen --kid 2026-u ...`) and paste its public half into UPDATE_PUBLIC_KEYS.
The private key stays outside every git folder, passphrase-protected, with an offline backup (docs/LICENSING.md).
"""

import argparse
import base64
import hashlib
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ed25519_sign  # noqa: E402
import licence_tool  # noqa: E402
from dssreport import updates  # noqa: E402


def collect(source: Path):
    files = {}
    for p in sorted((source / "dssreport").rglob("*")):
        if p.is_file() and p.suffix in (".py", ".pyw") and "__pycache__" not in p.parts:
            files[p.relative_to(source).as_posix()] = p.read_bytes()
    for name in updates.ALLOWED_FILES:
        if (source / name).is_file():
            files[name] = (source / name).read_bytes()
    docs = source / "docs"
    if docs.is_dir():
        for p in sorted(docs.rglob("*.md")):
            files[p.relative_to(source).as_posix()] = p.read_bytes()
    return files


def build_update(secret: bytes, kid: str, files: dict, version: str, release_date: date, out: Path,
                 min_version: str = "", licence_ids=(), notes: str = "", remove=()) -> Path:
    updates.parse_version(version)
    manifest = {"version": version, "release_date": release_date.isoformat(), "kid": kid, "notes": notes,
                "files": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())},
                "remove": sorted(remove), "min_version": min_version, "licence_ids": sorted(licence_ids)}
    mbytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = base64.urlsafe_b64encode(ed25519_sign.sign(secret, mbytes)).rstrip(b"=")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(updates.MANIFEST, mbytes)
        zf.writestr(updates.SIGNATURE, sig)
        for rel, data in files.items():
            zf.writestr(updates.PREFIX + rel, data)
    return out


def main(argv=None, passphrase: str = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--private-key", required=True)
    m.add_argument("--kid", required=True)
    m.add_argument("--source", required=True)
    m.add_argument("--version", required=True)
    m.add_argument("--release-date", type=date.fromisoformat, required=True)
    m.add_argument("--min-version", default="")
    m.add_argument("--licence-ids", default="")
    m.add_argument("--notes", default="")
    m.add_argument("--out", required=True)
    a = p.parse_args(argv)
    secret = licence_tool.unprotect_secret(Path(a.private_key).read_text(),
                                           passphrase if passphrase is not None else licence_tool._ask_passphrase(False))
    files = collect(Path(a.source))
    ids = [x for x in a.licence_ids.split(",") if x]
    build_update(secret, a.kid, files, a.version, a.release_date, Path(a.out), a.min_version, ids, a.notes)
    print(f"Wrote {a.out} ({len(files)} files). Send it only to the customers you choose.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
