"""Ed25519 signature VERIFICATION, in plain Python (standard library only).

This follows the reference algorithm in RFC 8032 section 6 and is checked in the tests against the
RFC's own test vectors and against OpenSSL. It is used to check licence files on the user's own
computer. It only verifies: signing lives in tools/, outside the shipped program, because the
private key must never be part of what customers receive.

It is not constant-time. That does not matter here: verification only handles public data.
"""

import hashlib

P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)


def _inv(x: int) -> int:
    return pow(x, P - 2, P)


def point_add(a, b):
    """Add two points in extended coordinates (X, Y, Z, T)."""
    A = (a[1] - a[0]) * (b[1] - b[0]) % P
    B = (a[1] + a[0]) * (b[1] + b[0]) % P
    C = 2 * a[3] * b[3] * D % P
    Dd = 2 * a[2] * b[2] % P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def point_mul(s: int, point):
    result = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            result = point_add(result, point)
        point = point_add(point, point)
        s >>= 1
    return result


def point_equal(a, b) -> bool:
    return ((a[0] * b[2] - b[0] * a[2]) % P == 0) and ((a[1] * b[2] - b[1] * a[2]) % P == 0)


def _recover_x(y: int, sign: int):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * _SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * _inv(5) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def point_compress(point) -> bytes:
    zinv = _inv(point[2])
    x, y = point[0] * zinv % P, point[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def point_decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def sha512_mod_q(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % Q


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True only if `signature` is a valid Ed25519 signature of `message` by `public_key`."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = point_decompress(public_key)
    if a is None:
        return False
    r_bytes = signature[:32]
    r = point_decompress(r_bytes)
    if r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= Q:
        return False
    h = sha512_mod_q(r_bytes + public_key + message)
    return point_equal(point_mul(s, G), point_add(r, point_mul(h, a)))
