import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dssreport import ed25519

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ed25519_sign  # noqa: E402

# RFC 8032 section 7.1 test vectors (secret key, public key, message, signature)
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e0652249015"
     "55fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]


class RFC8032(unittest.TestCase):
    def test_published_vectors_verify_and_sign_identically(self):
        for sk, pk, msg, sig in VECTORS:
            sk, pk, msg, sig = (bytes.fromhex(x) for x in (sk, pk, msg, sig))
            self.assertEqual(ed25519_sign.public_from_secret(sk), pk)
            self.assertEqual(ed25519_sign.sign(sk, msg), sig)
            self.assertTrue(ed25519.verify(pk, msg, sig))

    def test_any_change_fails(self):
        sk = os.urandom(32)
        pk = ed25519_sign.public_from_secret(sk)
        sig = ed25519_sign.sign(sk, b"hello")
        self.assertTrue(ed25519.verify(pk, b"hello", sig))
        self.assertFalse(ed25519.verify(pk, b"hellp", sig))
        bad = bytearray(sig)
        bad[5] ^= 1
        self.assertFalse(ed25519.verify(pk, b"hello", bytes(bad)))
        other = ed25519_sign.public_from_secret(os.urandom(32))
        self.assertFalse(ed25519.verify(other, b"hello", sig))

    def test_garbage_inputs_are_rejected_not_crashes(self):
        self.assertFalse(ed25519.verify(b"", b"m", b""))
        self.assertFalse(ed25519.verify(b"\xff" * 32, b"m", b"\xff" * 64))
        self.assertFalse(ed25519.verify(b"\x00" * 32, b"m", b"\x00" * 64))
        # s >= group order is not a valid signature
        sk = os.urandom(32)
        sig = ed25519_sign.sign(sk, b"m")
        forged = sig[:32] + int.to_bytes(ed25519.Q + 1, 32, "little")
        self.assertFalse(ed25519.verify(ed25519_sign.public_from_secret(sk), b"m", forged))

    @unittest.skipUnless(shutil.which("openssl"), "openssl not installed")
    def test_agrees_with_openssl(self):
        tmp = Path(tempfile.mkdtemp())
        key, pub, msg, sig = (tmp / n for n in ("k.pem", "p.pem", "m.bin", "s.bin"))
        r = subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(key)], capture_output=True)
        if r.returncode != 0:
            self.skipTest("openssl has no ed25519")
        subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
        msg.write_bytes(b"licence bytes " * 20)
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(msg),
                        "-out", str(sig)], check=True, capture_output=True)
        der = subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"],
                             check=True, capture_output=True).stdout
        self.assertTrue(ed25519.verify(der[-32:], msg.read_bytes(), sig.read_bytes()))
        self.assertFalse(ed25519.verify(der[-32:], msg.read_bytes() + b"x", sig.read_bytes()))


if __name__ == "__main__":
    unittest.main()
