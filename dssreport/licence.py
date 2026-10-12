"""Offline signed licences.

A licence is a small file. Its contents are signed by Jay Rohrs with a private key that never leaves
Jay's own machine. This program only holds the matching PUBLIC key and checks the signature right here
on the user's computer. Nothing is sent anywhere, ever, for licensing.

File format (UTF-8 JSON, under 16 KB):
    {"v": 1, "kid": "<key id>", "payload": "<base64url of the payload JSON>", "signature": "<base64url, 64 bytes>"}
The signature covers the exact payload bytes. The payload JSON holds:
    customer, instances, expires (YYYY-MM-DD), updates_until (YYYY-MM-DD), features [..], issued, licence_id

What a lapsed or missing licence does (see docs/LICENSING.md): it never hides or deletes a report.
"""

import base64
import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional

from . import ed25519
from .errors import DssError
from .licence_keys import PUBLIC_KEYS
from .paths import app_dir

MAX_BYTES = 16 * 1024
#: how many days before the end the renewal reminder starts
RENEWAL_NOTICE_DAYS = 30

# ---- feature flags: the one list. A licence file lists the flags it grants.
F_OPTIONAL_RULES = "optional_rules"     # the optional checks (payments add up to sales)
F_EMAIL = "email_m365"                  # create/send the email through Microsoft 365
F_SCHEDULE = "scheduling"               # the automatic weekday run
F_LOCAL_AI = "local_ai"                 # the optional one-sentence summary from a local model
F_HOSTED = "hosted"                     # future: hosted features (nothing built yet)
F_ADDONS = "addons"                     # future: paid add-ons (nothing built yet)

#: The flags for everything built so far. What a customer actually gets is whatever their licence FILE
#: lists: connections and flags are driven entirely by the file, so terms can change without a code change.
CURRENT_FEATURES = (F_OPTIONAL_RULES, F_EMAIL, F_SCHEDULE, F_LOCAL_AI)
ALL_FEATURES = CURRENT_FEATURES + (F_HOSTED, F_ADDONS)

FEATURE_WORDS = {
    F_OPTIONAL_RULES: "Optional checks",
    F_EMAIL: "Email through Microsoft 365",
    F_SCHEDULE: "Automatic schedule",
    F_LOCAL_AI: "Summary sentence from a local model",
    F_HOSTED: "Hosted features (not built yet)",
    F_ADDONS: "Paid add-ons (not built yet)",
}

#: the explicit value a licence file uses for "no limit on connections"
UNLIMITED = "unlimited"

# states
OK, EXPIRED, NOT_FOUND, INVALID, DEMO = "ok", "expired", "not found", "invalid", "demo"


class LicenceError(DssError):
    """The licence file could not be accepted. The message is plain words."""


class FeatureNotLicensed(DssError):
    pass


@dataclass
class Licence:
    customer: str
    instances: Optional[int]        # None = "unlimited" (an explicit value in the licence file)
    expires: date
    updates_until: date
    features: FrozenSet[str]
    issued: Optional[date] = None
    licence_id: str = ""

    @property
    def unlimited(self) -> bool:
        return self.instances is None


@dataclass
class LicenceStatus:
    state: str                                   # OK / EXPIRED / NOT_FOUND / INVALID / DEMO
    message: str                                 # one plain line, starts with "Licence:"
    licence: Optional[Licence] = None
    today: Optional[date] = None

    # -- what the licence lets the program do ------------------------------------------------
    @property
    def instances_allowed(self):
        """How many R365 connections may run (math.inf if the licence says unlimited). A lapsed (expired)
        licence keeps the connections already set up working; a missing or invalid one allows none.
        Demo data never needs a connection."""
        if not (self.licence and self.state in (OK, EXPIRED)):
            return 0
        return math.inf if self.licence.unlimited else self.licence.instances

    def connections_text(self, in_use: int) -> str:
        """Plain words for the settings screen: "unlimited (2 in use)" or "2 used of 3 allowed"."""
        allowed = self.instances_allowed
        if allowed == math.inf:
            return f"unlimited ({in_use} in use)"
        text = f"{in_use} used of {allowed} allowed"
        return text + (" (over the limit)" if in_use > allowed else "")

    @property
    def days_left(self) -> Optional[int]:
        if not self.licence or self.today is None:
            return None
        return (self.licence.expires - self.today).days

    @property
    def notice(self) -> str:
        """A renewal reminder, or "" if none is due. Shown in settings and at the top of the report from
        30 days before the end, and after it. It is only ever a notice: it blocks nothing."""
        if self.state == EXPIRED:
            return (f"Licence expired on {self.licence.expires.isoformat()} — "
                    "renew to add connections or get updates.")
        if self.state == OK:
            days = self.days_left
            if days is not None and days <= RENEWAL_NOTICE_DAYS:
                when = "today" if days <= 0 else f"in {days} day{'' if days == 1 else 's'}"
                return (f"Licence expires {when} (on {self.licence.expires.isoformat()}). "
                        "Renew to keep adding connections and getting updates.")
        return ""

    def can_add_connection(self, in_use: int) -> Optional[str]:
        """None if one more connection may be added, otherwise the plain reason it may not."""
        if self.state == EXPIRED:
            return f"{self.message} A renewed licence is needed to add a connection."
        if self.state != OK:
            return f"{self.message} Load a licence file in settings first."
        allowed = self.instances_allowed
        if in_use >= allowed:
            return (f"Licence: over limit. Your licence allows {allowed} connection"
                    f"{'' if allowed == 1 else 's'} and {in_use} "
                    f"{'is' if in_use == 1 else 'are'} already set up.")
        return None

    def has(self, feature: str) -> bool:
        if feature not in ALL_FEATURES:
            raise ValueError(f"unknown feature flag: {feature}")
        if self.state == DEMO:
            return feature in CURRENT_FEATURES       # demo data is never blocked
        return bool(self.licence) and self.state in (OK, EXPIRED) and feature in self.licence.features

    def require(self, feature: str) -> None:
        if not self.has(feature):
            raise FeatureNotLicensed(
                f"{FEATURE_WORDS[feature]} is not included in your licence. {self.message}")

    def updates_covered(self, release: date) -> Optional[bool]:
        """Is this program version inside the 'supports updates until' date? None if there is no licence."""
        return None if not self.licence else release <= self.licence.updates_until


def has_feature(status: LicenceStatus, feature: str) -> bool:
    """The single helper everything uses to ask "is this switched on by the licence?"."""
    return status.has(feature)


# ------------------------------------------------------------------------------------ parsing

def _b64(text: str, what: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise LicenceError(f"The licence file is damaged ({what} is not readable).")


def _date(value, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise LicenceError(f"The licence file is damaged ({name} is not a date).")


def verify_licence(raw: bytes, public_keys: Optional[Dict[str, str]] = None) -> Licence:
    """Check the signature and read the licence. Does NOT look at today's date (expiry is a status,
    not a failure: an expired licence is still a genuine one). Raises LicenceError in plain words."""
    keys = PUBLIC_KEYS if public_keys is None else public_keys
    if len(raw) > MAX_BYTES:
        raise LicenceError("That file is too big to be a licence file.")
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LicenceError("That file is not a licence file (it could not be read).")
    if not isinstance(doc, dict):
        raise LicenceError("That file is not a licence file.")
    if doc.get("v") != 1:
        raise LicenceError("This licence file is a newer format than this program understands. Update the program.")
    if not doc.get("signature"):
        raise LicenceError("This licence is not signed, so it cannot be accepted.")
    if not isinstance(doc.get("payload"), str) or not isinstance(doc.get("signature"), str):
        raise LicenceError("The licence file is damaged.")
    kid = str(doc.get("kid", ""))
    if not keys:
        raise LicenceError("This copy of the program has no licence key built in (a development build), "
                           "so no licence can be checked.")
    if kid not in keys:
        raise LicenceError("This licence was signed with a key this program does not know. "
                           "It may be for a different product or a newer version.")
    payload_bytes = _b64(doc["payload"], "the licence details")
    signature = _b64(doc["signature"], "the signature")
    try:
        public = bytes.fromhex(keys[kid])
    except ValueError:
        raise LicenceError("This program's built-in licence key is damaged.")
    if not ed25519.verify(public, payload_bytes, signature):
        raise LicenceError("This licence has been changed or was not made by Jay Rohrs. The signature does not match.")
    try:
        p = json.loads(payload_bytes.decode("utf-8"))
        features = p["features"]
        if not isinstance(p["customer"], str) or not p["customer"].strip():
            raise ValueError
        n = p["instances"]
        if n != UNLIMITED and (isinstance(n, bool) or not isinstance(n, int) or n < 0):
            raise ValueError
        if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
            raise ValueError
    except (KeyError, ValueError, TypeError, UnicodeDecodeError):
        raise LicenceError("The licence file is damaged (its details are incomplete).")
    return Licence(
        customer=p["customer"].strip(), instances=None if p["instances"] == UNLIMITED else p["instances"],
        expires=_date(p["expires"], "the expiry"), updates_until=_date(p["updates_until"], "the updates date"),
        features=frozenset(f for f in features if f in ALL_FEATURES),     # unknown flags are ignored
        issued=_date(p["issued"], "the issue date") if p.get("issued") else None,
        licence_id=str(p.get("licence_id", "")))


def status_for(licence: Licence, today: date) -> LicenceStatus:
    if today > licence.expires:
        return LicenceStatus(
            EXPIRED, f"Licence: expired on {licence.expires.isoformat()} (for {licence.customer}). "
                     "Your reports and existing connections keep working; renew to add connections or get updates.",
            licence, today)
    return LicenceStatus(
        OK, f"Licence: valid for {licence.customer} until {licence.expires.isoformat()}.", licence, today)


def licence_path() -> Path:
    return app_dir() / "licence.json"


def current_status(today: Optional[date] = None, path: Optional[Path] = None,
                   public_keys: Optional[Dict[str, str]] = None) -> LicenceStatus:
    """Read the installed licence file (no network). Never raises."""
    today = today or date.today()
    path = Path(path) if path else licence_path()
    if not path.exists():
        return LicenceStatus(NOT_FOUND, "Licence: not found. Load a licence file in settings. "
                                        "Existing reports can still be viewed.", None, today)
    try:
        raw = path.read_bytes()
        return status_for(verify_licence(raw, public_keys), today)
    except OSError:
        return LicenceStatus(INVALID, "Licence: the licence file could not be read.", None, today)
    except LicenceError as exc:
        return LicenceStatus(INVALID, f"Licence: not valid. {exc} Existing reports can still be viewed.", None, today)


def demo_status() -> LicenceStatus:
    return LicenceStatus(DEMO, "Licence: demo mode (made-up data, no licence needed).", None, None)


def install_licence(raw: bytes, public_keys: Optional[Dict[str, str]] = None,
                    path: Optional[Path] = None, today: Optional[date] = None) -> LicenceStatus:
    """Check a licence file and, only if its signature is genuine, keep a copy. Raises LicenceError
    otherwise and leaves any licence already installed untouched."""
    lic = verify_licence(raw, public_keys)
    path = Path(path) if path else licence_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return status_for(lic, today or date.today())


def instance_overflow(status: LicenceStatus, in_use: int) -> int:
    """How many of the configured connections are beyond what the licence allows."""
    return max(0, in_use - status.instances_allowed)
