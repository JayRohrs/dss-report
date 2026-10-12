"""Settings that are not review rules (connections, email, schedule). Saved as settings.json in the
program's own folder. No passwords or tokens are ever stored here - those go to the OS credential store."""

import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from .errors import ConfigError
from .paths import app_dir, settings_path

LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


@dataclass
class Instance:
    """One Restaurant365 connection. Each has its own name, address, user, saved password, field
    mapping file (outside the repo) and its own location settings."""
    id: str
    name: str
    base_url: str = ""
    username: str = ""               # Domain\Username as R365 documents it (not a secret)
    enabled: bool = True
    source_kind: str = "odata"       # which connector reads this instance (see docs/DATA_SOURCES.md)
    mapping_file: str = ""           # relative to the program's folder; default mappings/<id>.toml
    credential_key: str = ""         # name of this instance's entry in the OS credential store
    include: List[str] = field(default_factory=list)   # "only these locations" (optional)
    hidden: List[str] = field(default_factory=list)    # locations switched off

    def __post_init__(self):
        if not self.mapping_file:
            self.mapping_file = f"mappings/{self.id}.toml"
        if not self.credential_key:
            self.credential_key = f"r365:{self.id}"

    @property
    def mapping_path(self) -> Path:
        return app_dir() / self.mapping_file


@dataclass
class Settings:
    instances: List[Instance] = field(default_factory=list)
    email_enabled: bool = False
    email_to: str = ""
    email_send_auto: bool = False    # off unless ticked: otherwise a draft is created
    graph_client_id: str = ""        # public app id, not a secret
    graph_tenant: str = "organizations"
    schedule_enabled: bool = False
    schedule_time: str = "07:00"
    schedule_weekdays: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon=0
    schedule_late_after_minutes: int = 90
    update_check_enabled: bool = False   # optional online update check: OFF unless ticked
    update_manifest_url: str = ""        # the owner's signed update list; no real address is built in

    def instance(self, instance_id: str) -> Optional[Instance]:
        return next((i for i in self.instances if i.id == instance_id), None)

    @property
    def enabled_instances(self) -> List[Instance]:
        return [i for i in self.instances if i.enabled]


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return s or "connection"


def unique_id(name: str, taken) -> str:
    base, n, cand = slugify(name), 2, slugify(name)
    while cand in taken:
        cand = f"{base[:36]}-{n}"
        n += 1
    return cand


def is_safe_url(url: str) -> bool:
    """https only; plain http is allowed only for this computer (mock servers in tests)."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if not u.hostname or u.username or u.password:
        return False
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in LOOPBACK)


def validate(s: Settings) -> Settings:
    ids, names = set(), set()
    for i in s.instances:
        if not _ID.fullmatch(i.id):
            raise ConfigError("A connection has an invalid internal id.")
        if i.id in ids:
            raise ConfigError("Two connections have the same internal id.")
        ids.add(i.id)
        if not i.name.strip() or len(i.name) > 60:
            raise ConfigError("Every connection needs a name (up to 60 characters).")
        if i.name.strip().lower() in names:
            raise ConfigError(f"Two connections are both called '{i.name}'. Give each its own name.")
        names.add(i.name.strip().lower())
        from . import r365  # noqa: F401  (registers the built-in connector)
        from .sources import SOURCE_KINDS
        if i.source_kind not in SOURCE_KINDS:
            raise ConfigError(f"Connection '{i.name}': this program does not know the data source '{i.source_kind}'.")
        if i.base_url and not is_safe_url(i.base_url):
            raise ConfigError(f"Connection '{i.name}': the R365 address must start with https:// "
                              "(and not contain a user name or password).")
        if i.enabled and not (i.base_url and i.username):
            raise ConfigError(f"Connection '{i.name}': fill in the address and the user name, or untick Connect.")
        if ".." in Path(i.mapping_file).parts or Path(i.mapping_file).is_absolute():
            raise ConfigError(f"Connection '{i.name}': the mapping file must be inside the program's own folder.")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s.schedule_time):
        raise ConfigError("The schedule time must look like 07:00 (24-hour clock).")
    if not s.schedule_weekdays or any(d not in range(7) for d in s.schedule_weekdays):
        raise ConfigError("Pick at least one day for the schedule.")
    if s.email_to and not re.fullmatch(r"[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+", s.email_to):
        raise ConfigError("The email address doesn't look right. Use one address, like name@company.example.")
    if s.email_enabled and not s.email_to:
        raise ConfigError("To prepare emails, fill in who they go to.")
    if s.email_send_auto and not s.email_enabled:
        raise ConfigError("'Send automatically' needs 'Prepare an email' to be ticked as well.")
    if not re.fullmatch(r"[A-Za-z0-9-]{0,64}", s.graph_client_id):
        raise ConfigError("The Microsoft app ID should be letters, digits and dashes only.")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", s.graph_tenant):
        raise ConfigError("The Microsoft tenant should be 'organizations' or a tenant name/ID.")
    if s.update_manifest_url:
        from .update_check import is_valid_manifest_url
        if not is_valid_manifest_url(s.update_manifest_url):
            raise ConfigError("The update address must start with https:// and have no extra parts "
                              "(no user name, no ? query, no # part).")
    if s.update_check_enabled and not s.update_manifest_url:
        raise ConfigError("To check for updates online, fill in the update address.")
    if s.schedule_late_after_minutes < 0:
        raise ConfigError("'Late after' minutes cannot be negative.")
    return s


def _instance_from(raw: dict) -> Instance:
    known = {f.name for f in fields(Instance)}
    return Instance(**{k: v for k, v in raw.items() if k in known})


def load_settings(path=None) -> Settings:
    path = Path(path) if path else settings_path()
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"The settings file {path} could not be read ({exc}). Fix or delete it.")
    known = {f.name for f in fields(Settings)} - {"instances"}
    s = Settings(**{k: v for k, v in raw.items() if k in known})
    if "instances" in raw:
        s.instances = [_instance_from(i) for i in raw["instances"] if isinstance(i, dict)]
    elif raw.get("r365_base_url") or raw.get("r365_username"):
        # Phase 2 saved a single connection in flat fields. Carry it over unchanged: same saved
        # password entry, same mapping file.
        user = raw.get("r365_username", "")
        s.instances = [Instance(id="main", name="Restaurant365", base_url=raw.get("r365_base_url", ""),
                                username=user, enabled=bool(raw.get("r365_enabled", False)),
                                mapping_file="r365_mapping.toml", credential_key=f"r365:{user}")]
    return s


def save_settings(s: Settings, path=None) -> Path:
    validate(s)
    path = Path(path) if path else settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(s), indent=2) + "\n", encoding="utf-8")
    return path
