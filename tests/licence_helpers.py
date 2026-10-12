"""Throw-away licence keys for tests. The private key exists only in memory during a test run."""

import contextlib
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ed25519_sign  # noqa: E402
import licence_tool  # noqa: E402

from dssreport import licence_keys  # noqa: E402

KID = "test-key"
SECRET = os.urandom(32)                       # new every run; never written to disk
PUBLIC_HEX = ed25519_sign.public_from_secret(SECRET).hex()
OTHER_SECRET = os.urandom(32)                 # a different signer ("wrong key")


def make(customer="Sample Customer Ltd", instances=2, expires=date(2099, 12, 31),
         updates_until=date(2099, 12, 31), features=licence_tool.CURRENT_FEATURES, secret=None, kid=KID,
         issued=date(2026, 1, 1)) -> bytes:
    return licence_tool.make_licence(secret or SECRET, kid, customer, instances, expires, updates_until,
                                     features, issued)


@contextlib.contextmanager
def trusted_keys():
    """Make the program trust the throw-away public key (and nothing else) while the block runs."""
    with mock.patch.dict(licence_keys.PUBLIC_KEYS, {KID: PUBLIC_HEX}, clear=True):
        yield


def install(home: Path, raw: bytes = None, **kw) -> Path:
    path = Path(home) / "licence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw if raw is not None else make(**kw))
    return path
