"""Ed25519 key generation and SIGNING (RFC 8032 reference). For the licence tool only.

Not part of the shipped program. Not constant-time: use it on your own machine to make licences, not as a
general crypto library.
"""

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dssreport.ed25519 import G, Q, point_compress, point_mul, sha512_mod_q  # noqa: E402


def _expand(secret: bytes):
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_from_secret(secret: bytes) -> bytes:
    a, _ = _expand(secret)
    return point_compress(point_mul(a, G))


def new_secret() -> bytes:
    return os.urandom(32)


def sign(secret: bytes, message: bytes) -> bytes:
    a, prefix = _expand(secret)
    public = point_compress(point_mul(a, G))
    r = sha512_mod_q(prefix + message)
    r_bytes = point_compress(point_mul(r, G))
    h = sha512_mod_q(r_bytes + public + message)
    s = (r + h * a) % Q
    return r_bytes + int.to_bytes(s, 32, "little")
