#!/usr/bin/env python3
"""Make licence keys and sign licences. Kept OUT of the shipped program (the installer copies only the
dssreport folder). Run it on Jay's own machine.

    python tools/licence_tool.py keygen --out <PRIVATE folder outside the repo> [--kid 2026-a]
    python tools/licence_tool.py sign --private-key <file> --kid 2026-a --customer "Name" \\
        --instances 2 --expires 2027-03-31 --updates-until 2027-03-31 [--features a,b] --out licence.json
    python tools/licence_tool.py show licence.json

The PRIVATE key never goes in the repo. This tool refuses to write a private key inside a git working
folder. The real signing key is generated once, kept offline, and backed up by Jay; only the PUBLIC half
is pasted into dssreport/licence_keys.py. For tests, a throw-away pair is generated fresh each run.
"""

import argparse
import base64
import json
import secrets
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ed25519_sign  # noqa: E402
from dssreport.licence import ALL_FEATURES, BASE_FEATURES  # noqa: E402


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def inside_git_repo(path: Path) -> bool:
    for parent in [path.resolve()] + list(path.resolve().parents):
        if (parent / ".git").exists():
            return True
    return False


def make_licence(secret: bytes, kid: str, customer: str, instances: int, expires: date, updates_until: date,
                 features=BASE_FEATURES, issued: date = None) -> bytes:
    payload = {"customer": customer, "instances": instances, "expires": expires.isoformat(),
               "updates_until": updates_until.isoformat(), "features": sorted(features),
               "issued": (issued or date.today()).isoformat(), "licence_id": secrets.token_hex(6)}
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    doc = {"v": 1, "kid": kid, "payload": b64(payload_bytes), "signature": b64(ed25519_sign.sign(secret, payload_bytes))}
    return (json.dumps(doc, indent=2) + "\n").encode("utf-8")


def keygen(out: Path, kid: str, allow_in_repo: bool = False) -> str:
    if inside_git_repo(out) and not allow_in_repo:
        raise SystemExit("Refusing: that folder is inside a git repository. Keep the PRIVATE key somewhere "
                         "outside any repo (and back it up).")
    out.mkdir(parents=True, exist_ok=True)
    secret = ed25519_sign.new_secret()
    key_file = out / f"{kid}.private.key"
    key_file.write_text(secret.hex() + "\n")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return ed25519_sign.public_from_secret(secret).hex()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", required=True)
    k.add_argument("--kid", default="key-1")
    s = sub.add_parser("sign")
    s.add_argument("--private-key", required=True)
    s.add_argument("--kid", required=True)
    s.add_argument("--customer", required=True)
    s.add_argument("--instances", type=int, required=True)
    s.add_argument("--expires", type=date.fromisoformat, required=True)
    s.add_argument("--updates-until", type=date.fromisoformat, required=True)
    s.add_argument("--features", default=",".join(BASE_FEATURES), help=f"comma list from: {', '.join(ALL_FEATURES)}")
    s.add_argument("--out", required=True)
    sh = sub.add_parser("show")
    sh.add_argument("file")
    a = p.parse_args(argv)
    if a.cmd == "keygen":
        pub = keygen(Path(a.out), a.kid)
        print(f'Private key written to {Path(a.out) / (a.kid + ".private.key")} (keep it secret, keep it OUT of the repo).')
        print(f'Paste into dssreport/licence_keys.py:\n    "{a.kid}": "{pub}",')
    elif a.cmd == "sign":
        feats = [f for f in a.features.split(",") if f]
        bad = [f for f in feats if f not in ALL_FEATURES]
        if bad:
            raise SystemExit(f"Unknown feature flag(s): {', '.join(bad)}")
        secret = bytes.fromhex(Path(a.private_key).read_text().strip())
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
