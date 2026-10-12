"""Read-only connection to a Restaurant365 tenant's OData service.

What is and is not known (see docs/R365_OPEN_QUESTIONS.md):
  * R365 documents Basic sign-in as Domain\\Username + password for its OData connector,
    and a $metadata document. We use exactly that, with GET requests only.
  * Which entity holds daily-sales-summary figures, and what its fields are called,
    is NOT confirmed. Nothing is assumed: the field mapping file starts empty, and any
    check whose field is empty shows "needs mapping".

This client has no way to send anything except GET. Credentials come from the OS
credential store, are sent only to the address the user configured, are never logged,
and redirects are refused so they can never be forwarded elsewhere.
"""

import base64
import json
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

from .adapters.base import Adapter
from .adapters.files import record_from_mapping
from .credstore import CredentialStore, redact
from .errors import ConfigError, InputError
from .model import DayRecord
from .settings import Settings, is_safe_url

CRED_NAME_PREFIX = "r365:"
MAX_DAYS_PER_REQUEST = 31   # a third-party review reports a 31-day cap; unconfirmed, so we stay under it
FIELD_KEYS = ("sales_total", "cash_over_short", "missing_receipts", "payment_exceptions",
              "approved", "pos_import_received")


def credential_name(username: str) -> str:
    return CRED_NAME_PREFIX + username


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class ODataClient:
    """GET-only. There is deliberately no post/put/patch/delete method."""

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        if not is_safe_url(base_url):
            raise InputError("The R365 address must start with https://.")
        self.base = base_url.rstrip("/")
        self._origin = urlparse(self.base)[:2]
        self._password = password
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._auth = f"Basic {token}"
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _get(self, url: str, accept: str) -> bytes:
        if urlparse(url)[:2] != self._origin:
            raise InputError("R365 sent a link to a different website. It was not followed "
                             "(your sign-in is only ever sent to the address you configured).")
        req = urllib.request.Request(url, method="GET",
                                     headers={"Authorization": self._auth, "Accept": accept})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise InputError("R365 refused the sign-in. Check the user name (Domain\\Username) "
                                 "and password in settings, and that this user may use the OData connector.")
            raise InputError(f"R365 answered with an error (HTTP {exc.code}).")
        except (urllib.error.URLError, OSError) as exc:
            raise InputError("Could not reach R365 at the configured address "
                             f"({redact(str(getattr(exc, 'reason', exc)), self._password)}).")

    def get_json(self, url: str) -> dict:
        try:
            return json.loads(self._get(url, "application/json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InputError("R365 sent an answer that was not the expected JSON.")

    def get_metadata_xml(self) -> bytes:
        return self._get(self.base + "/$metadata", "application/xml")

    def get_all(self, first_url: str) -> List[dict]:
        """Follow @odata.nextLink exactly as returned (same website only)."""
        rows, url, pages = [], first_url, 0
        while url:
            pages += 1
            if pages > 500:
                raise InputError("R365 returned an unexpectedly long list of pages; stopped.")
            data = self.get_json(url)
            value = data.get("value")
            if not isinstance(value, list):
                raise InputError("R365's answer had no list of rows ('value').")
            rows.extend(value)
            url = data.get("@odata.nextLink") or data.get("nextLink")
        return rows


# ---------------------------------------------------------------- mapping

class Mapping:
    def __init__(self, raw: Optional[dict] = None):
        raw = raw or {}
        allowed = {"source": {"entity", "location", "business_date", "date_literal"},
                   "fields": set(FIELD_KEYS),
                   "values": {"approved_true", "approved_false",
                              "pos_import_received_true", "pos_import_received_false"},
                   "payments": None}
        for section, body in raw.items():
            if section not in allowed or not isinstance(body, dict):
                raise ConfigError(f"mapping file: unknown section [{section}].")
            if allowed[section] is not None:
                extra = set(body) - allowed[section]
                if extra:
                    raise ConfigError(f"mapping file: unknown setting '{sorted(extra)[0]}' in [{section}].")
        src, flds, vals = raw.get("source", {}), raw.get("fields", {}), raw.get("values", {})
        self.entity = self._name(src, "entity")
        self.location = self._name(src, "location")
        self.business_date = self._name(src, "business_date")
        self.date_literal = src.get("date_literal", "date")
        if self.date_literal not in ("date", "datetime"):
            raise ConfigError('mapping file: date_literal must be "date" or "datetime".')
        self.fields: Dict[str, str] = {k: self._name(flds, k) for k in FIELD_KEYS}
        self.payments: Dict[str, str] = {}
        for ptype, prop in raw.get("payments", {}).items():
            if not isinstance(prop, str):
                raise ConfigError("mapping file: payment properties must be text.")
            if prop.strip():
                self.payments[ptype] = prop.strip()
        self.values = {}
        for k in ("approved_true", "approved_false", "pos_import_received_true", "pos_import_received_false"):
            v = vals.get(k, [])
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ConfigError(f"mapping file: [values] {k} must be a list of words.")
            self.values[k] = {x.strip().lower() for x in v}

    @staticmethod
    def _name(section, key) -> str:
        v = section.get(key, "")
        if not isinstance(v, str):
            raise ConfigError(f"mapping file: {key} must be text.")
        return v.strip()

    @classmethod
    def load(cls, path) -> "Mapping":
        path = Path(path)
        if not path.exists():
            return cls()  # nothing mapped: everything shows "needs mapping"
        try:
            return cls(tomllib.loads(path.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"mapping file {path} is not valid: {exc}")

    @property
    def can_fetch(self) -> bool:
        return bool(self.entity and self.location and self.business_date)

    def unmapped(self) -> Set[str]:
        out = {k for k, v in self.fields.items() if not v}
        if not self.payments:
            out.add("payments")
        return out


def _flag(value, true_words: Set[str], false_words: Set[str]):
    if value is None or isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    if word in true_words:
        return True
    if word in false_words:
        return False
    return None  # not in either list: UNKNOWN, never guessed


# ---------------------------------------------------------------- adapter

class R365Adapter(Adapter):
    name = "Restaurant365 (read-only)"
    needs_window = True

    def __init__(self, settings: Settings, mapping: Mapping, store: CredentialStore, include=()):
        super().__init__()
        self.settings, self.mapping, self.store = settings, mapping, store
        self.include = list(include)
        self.start: Optional[date] = None
        self.end: Optional[date] = None
        self.unmapped = set(mapping.unmapped())
        if not mapping.can_fetch:
            self.unmapped.update(FIELD_KEYS + ("payments",))
            self.unmapped_notes.append(
                "The R365 field mapping is empty, so no data can be read yet. "
                "See docs/R365_OPEN_QUESTIONS.md and r365_mapping.example.toml.")
        for k in FIELD_KEYS:
            if not mapping.fields[k]:
                self.unmapped_notes.append(f"No R365 field is mapped for '{k}'.")

    def set_window(self, start: date, end: date) -> None:
        self.start, self.end = start, end

    def _client(self) -> ODataClient:
        s = self.settings
        if not (s.r365_base_url and s.r365_username):
            raise InputError("R365 is not set up yet. Open the settings screen and fill in the connection.")
        password = self.store.get(credential_name(s.r365_username))
        if not password:
            raise InputError("No R365 password is saved on this computer. Open the settings screen and enter it.")
        return ODataClient(s.r365_base_url, s.r365_username, password)

    def _url(self, start: date, end: date) -> str:
        m = self.mapping
        lit = (lambda d: d.isoformat()) if m.date_literal == "date" else (lambda d: d.isoformat() + "T00:00:00Z")
        flt = f"{m.business_date} ge {lit(start)} and {m.business_date} le {lit(end)}"
        props = [m.location, m.business_date] + [v for v in m.fields.values() if v] + list(m.payments.values())
        select = ",".join(dict.fromkeys(props))
        return (f"{self.settings.r365_base_url.rstrip('/')}/{quote(m.entity)}"
                f"?$filter={quote(flt, safe='(),=:-')}&$select={quote(select, safe=',')}")

    def load(self) -> List[DayRecord]:
        if not self.mapping.can_fetch:
            return []
        if self.start is None or self.end is None:
            raise InputError("Internal: the date range was not set before reading from R365.")
        client = self._client()
        rows: List[dict] = []
        cursor = self.start
        while cursor <= self.end:
            chunk_end = min(self.end, cursor + timedelta(days=MAX_DAYS_PER_REQUEST - 1))
            rows.extend(client.get_all(self._url(cursor, chunk_end)))
            cursor = chunk_end + timedelta(days=1)
        wanted = set(self.include)
        records, seen = [], {}
        for i, row in enumerate(rows, start=1):
            where = f"R365 row {i}"
            rec = record_from_mapping(self._to_raw(row, where), where)
            if wanted and rec.location not in wanted:
                continue
            key = (rec.location, rec.business_date)
            if key in seen:
                raise InputError(
                    f"R365 returned two rows for {rec.location} on {rec.business_date} "
                    f"({seen[key]} and {where}). The report can't tell which is right, so it stopped. "
                    "The entity chosen in the mapping file probably has more than one row per location "
                    "per day; see docs/R365_OPEN_QUESTIONS.md.")
            seen[key] = where
            records.append(rec)
        return records

    def _to_raw(self, row: dict, where: str) -> dict:
        m = self.mapping
        if not isinstance(row, dict):
            raise InputError(f"{where}: not a record.")
        bd = row.get(m.business_date)
        if isinstance(bd, str) and len(bd) > 10 and bd[10] == "T":
            bd = bd[:10]
        raw = {"location": row.get(m.location), "business_date": bd}
        for key in FIELD_KEYS:
            prop = m.fields[key]
            if not prop:
                continue
            val = row.get(prop)
            if key in ("approved", "pos_import_received"):
                val = _flag(val, m.values[key + "_true"], m.values[key + "_false"])
            raw[key] = val
        raw["payments"] = {t: row.get(p) for t, p in m.payments.items()}
        return raw


# ---------------------------------------------------------------- discover / test

def check_connection(settings: Settings, store: CredentialStore) -> str:
    """Return a plain sentence. Raises InputError with a plain message on failure."""
    if not (settings.r365_base_url and settings.r365_username):
        raise InputError("Fill in the R365 address and user name first.")
    password = store.get(credential_name(settings.r365_username))
    if not password:
        raise InputError("No R365 password is saved yet. Type it in the password box and save.")
    ODataClient(settings.r365_base_url, settings.r365_username, password).get_metadata_xml()
    return "Connected to R365 (read-only). The sign-in worked."


def discover(settings: Settings, store: CredentialStore) -> List[str]:
    """List entity sets and their properties from $metadata, for filling in the mapping file."""
    password = store.get(credential_name(settings.r365_username)) if settings.r365_username else None
    if not (settings.r365_base_url and password):
        raise InputError("Set up the R365 connection first (settings screen).")
    xml = ODataClient(settings.r365_base_url, settings.r365_username, password).get_metadata_xml()
    return describe_metadata(xml)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def describe_metadata(xml: bytes) -> List[str]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise InputError("R365's $metadata answer was not readable XML.")
    types: Dict[str, List[Tuple[str, str]]] = {}
    sets: List[Tuple[str, str]] = []
    for el in root.iter():
        t = _local(el.tag)
        if t == "EntityType":
            types[el.get("Name", "")] = [(p.get("Name", ""), p.get("Type", ""))
                                         for p in el if _local(p.tag) == "Property"]
        elif t == "EntitySet":
            sets.append((el.get("Name", ""), (el.get("EntityType", "")).rsplit(".", 1)[-1]))
    lines = []
    for name, etype in sorted(sets):
        lines.append(f"{name}")
        for pname, ptype in types.get(etype, []):
            lines.append(f"    {pname}  ({ptype})")
    return lines or ["(no entity sets found)"]
