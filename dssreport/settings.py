"""Settings that are not review rules (connection, email, schedule). Saved as settings.json in the
program's own folder. No passwords or tokens are ever stored here - those go to the OS credential store."""

import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from .errors import ConfigError
from .paths import settings_path

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


@dataclass
class Settings:
    r365_enabled: bool = False
    r365_base_url: str = ""
    r365_username: str = ""          # Domain\Username as R365 documents it (not a secret)
    email_enabled: bool = False
    email_to: str = ""
    email_send_auto: bool = False    # off unless ticked: otherwise a draft is created
    graph_client_id: str = ""        # public app id, not a secret
    graph_tenant: str = "organizations"
    schedule_enabled: bool = False
    schedule_time: str = "07:00"
    schedule_weekdays: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon=0
    schedule_late_after_minutes: int = 90


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
    if s.r365_base_url and not is_safe_url(s.r365_base_url):
        raise ConfigError("The R365 address must start with https:// (and not contain a user name or password).")
    if s.r365_enabled and not (s.r365_base_url and s.r365_username):
        raise ConfigError("To connect to R365, fill in the address and the user name.")
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
    if s.schedule_late_after_minutes < 0:
        raise ConfigError("'Late after' minutes cannot be negative.")
    return s


def load_settings(path=None) -> Settings:
    path = Path(path) if path else settings_path()
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"The settings file {path} could not be read ({exc}). Fix or delete it.")
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save_settings(s: Settings, path=None) -> Path:
    validate(s)
    path = Path(path) if path else settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(s), indent=2) + "\n", encoding="utf-8")
    return path
