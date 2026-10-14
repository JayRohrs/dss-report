#!/usr/bin/env python3
"""Make licence keys and sign licences. Kept OUT of the shipped program (the installer copies only the
dssreport folder). Run it on Jay's own machine.

    python tools/licence_tool.py keygen --out <PRIVATE folder outside every git folder> [--kid 2026-a]
        (asks for a passphrase; the private key file is saved passphrase-protected)
    python tools/licence_tool.py sign --private-key <file> --kid 2026-a --customer "Name" \\
        --instances 2|unlimited --expires 2027-03-31 --updates-until 2027-03-31|lifetime [--features a,b] --out licence.json
    python tools/licence_tool.py show licence.json

The PRIVATE key never goes in the repo. This tool refuses to write a private key inside a git working
folder, and refuses an empty or short passphrase. The real signing key is generated once, kept outside every
git folder, passphrase-protected, with an offline backup; only the PUBLIC half is pasted into
dssreport/licence_keys.py. For tests, a throw-away pair is generated fresh each run.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ed25519_sign  # noqa: E402
from dssreport.licence import ALL_FEATURES, CURRENT_FEATURES, LIFETIME, UNLIMITED  # noqa: E402


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def inside_git_repo(path: Path) -> bool:
    for parent in [path.resolve()] + list(path.resolve().parents):
        if (parent / ".git").exists():
            return True
    return False


def make_licence(secret: bytes, kid: str, customer: str, instances, expires: date, updates_until,
                 features=CURRENT_FEATURES, issued: date = None) -> bytes:
    # instances: a whole number, or the word "unlimited"
    payload = {"customer": customer, "instances": instances, "expires": expires.isoformat(),
               "updates_until": updates_until if updates_until == LIFETIME else updates_until.isoformat(), "features": sorted(features),
               "issued": (issued or date.today()).isoformat(), "licence_id": secrets.token_hex(6)}
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    doc = {"v": 1, "kid": kid, "payload": b64(payload_bytes), "signature": b64(ed25519_sign.sign(secret, payload_bytes))}
    return (json.dumps(doc, indent=2) + "\n").encode("utf-8")


# ---- passphrase-protected private key files -----------------------------------------------------
# scrypt turns the passphrase into two keys; the 32-byte secret is XORed with an HMAC-SHA256 keystream
# and sealed with an HMAC tag (encrypt-then-MAC). Wrong passphrase or a changed file fails the tag check.
_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int):
    raw = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=64)
    return raw[:32], raw[32:]


def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
    out, counter = b"", 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def protect_secret(secret: bytes, passphrase: str, scrypt_params=None) -> str:
    if not passphrase:
        raise SystemExit("A passphrase is required. The private key file must be passphrase-protected.")
    prm = scrypt_params or _SCRYPT
    salt, nonce = os.urandom(16), os.urandom(16)
    enc_key, mac_key = _derive(passphrase, salt, **prm)
    ct = bytes(a ^ b for a, b in zip(secret, _stream(enc_key, nonce, len(secret))))
    tag = hmac.new(mac_key, b"dss-licence-key-v1" + salt + nonce + ct, hashlib.sha256).digest()
    return json.dumps({"v": 1, "kdf": "scrypt", **prm, "salt": salt.hex(), "nonce": nonce.hex(),
                       "ct": ct.hex(), "tag": tag.hex()}, indent=2) + "\n"


def unprotect_secret(text: str, passphrase: str) -> bytes:
    try:
        d = json.loads(text)
        prm = {k: int(d[k]) for k in ("n", "r", "p")}
        salt, nonce, ct, tag = (bytes.fromhex(d[k]) for k in ("salt", "nonce", "ct", "tag"))
    except (ValueError, KeyError, TypeError):
        raise SystemExit("That is not a passphrase-protected private key file made by this tool.")
    enc_key, mac_key = _derive(passphrase, salt, **prm)
    expect = hmac.new(mac_key, b"dss-licence-key-v1" + salt + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expect, tag):
        raise SystemExit("Wrong passphrase (or the key file has been changed).")
    return bytes(a ^ b for a, b in zip(ct, _stream(enc_key, nonce, len(ct))))


def keygen(out: Path, kid: str, passphrase: str, allow_in_repo: bool = False, scrypt_params=None) -> str:
    if inside_git_repo(out) and not allow_in_repo:
        raise SystemExit("Refusing: that folder is inside a git repository. Keep the PRIVATE key somewhere "
                         "outside every git folder (and back it up offline).")
    sealed = protect_secret_check(passphrase)
    out.mkdir(parents=True, exist_ok=True)
    secret = ed25519_sign.new_secret()
    key_file = out / f"{kid}.private.key"
    key_file.write_text(protect_secret(secret, sealed, scrypt_params))
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return ed25519_sign.public_from_secret(secret).hex()


def protect_secret_check(passphrase: str) -> str:
    if not passphrase or len(passphrase) < 12:
        raise SystemExit("Use a passphrase of at least 12 characters.")
    return passphrase


def _instances(text: str):
    if text.strip().lower() == UNLIMITED:
        return UNLIMITED
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError('use a whole number, or "unlimited"')
    if n < 0:
        raise argparse.ArgumentTypeError("cannot be negative")
    return n


def _updates_until(text: str):
    if text.strip().lower() == LIFETIME:
        return LIFETIME
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError('use a date like 2027-03-31, or "lifetime"')


def _ask_passphrase(confirm: bool) -> str:
    first = getpass.getpass("Passphrase for the private key file: ")
    if confirm and getpass.getpass("Type it again: ") != first:
        raise SystemExit("The two passphrases did not match.")
    return first


def main(argv=None, passphrase: str = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", required=True)
    k.add_argument("--kid", default="key-1")
    s = sub.add_parser("sign")
    s.add_argument("--private-key", required=True)
    s.add_argument("--kid", required=True)
    s.add_argument("--customer", required=True)
    s.add_argument("--instances", type=_instances, required=True,
                   help='how many R365 connections: a whole number, or the word "unlimited"')
    s.add_argument("--expires", type=date.fromisoformat, required=True)
    s.add_argument("--updates-until", type=_updates_until, required=True,
                   help='the last date updates are included (YYYY-MM-DD), or the word "lifetime"')
    s.add_argument("--features", default=",".join(CURRENT_FEATURES), help=f"comma list from: {', '.join(ALL_FEATURES)}")
    s.add_argument("--out", required=True)
    sh = sub.add_parser("show")
    sh.add_argument("file")
    a = p.parse_args(argv)
    if a.cmd == "keygen":
        pub = keygen(Path(a.out), a.kid, passphrase if passphrase is not None else _ask_passphrase(True))
        print(f'Private key written to {Path(a.out) / (a.kid + ".private.key")} (keep it secret, keep it OUT of the repo).')
        print(f'Paste into dssreport/licence_keys.py:\n    "{a.kid}": "{pub}",')
    elif a.cmd == "sign":
        feats = [f for f in a.features.split(",") if f]
        bad = [f for f in feats if f not in ALL_FEATURES]
        if bad:
            raise SystemExit(f"Unknown feature flag(s): {', '.join(bad)}")
        secret = unprotect_secret(Path(a.private_key).read_text(),
                                  passphrase if passphrase is not None else _ask_passphrase(False))
        Path(a.out).write_bytes(make_licence(secret, a.kid, a.customer, a.instances, a.expires, a.updates_until, feats))
        print(f"Wrote {a.out}")
    else:
        doc = json.loads(Path(a.file).read_text())
        pad = doc["payload"] + "=" * (-len(doc["payload"]) % 4)
        print(json.dumps(json.loads(base64.urlsafe_b64decode(pad)), indent=2))
        print("(This shows the contents only. The program checks the signature.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
