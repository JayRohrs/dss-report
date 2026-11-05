"""Desktop settings: every optional thing is OFF until the owner switches it on.

Saved as desktop_settings.json in the program's own folder (%LOCALAPPDATA%\\DssReport). No passwords or
tokens are stored here; the Microsoft 365 sign-in lives in the OS credential store.
"""

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from ..errors import ConfigError
from ..paths import app_dir

FILE_NAME = "desktop_settings.json"


def settings_file() -> Path:
    return app_dir() / FILE_NAME


@dataclass
class DesktopSettings:
    daily_run_enabled: bool = False      # the on/off switch for the Windows scheduled daily run
    run_time: str = "07:00"              # 24-hour clock, local time
    source: str = "demo"                 # "demo" (made-up data), a file path, or "r365"
    draft_email_enabled: bool = False    # create a Microsoft 365 DRAFT (never sent by this program)
    draft_to: str = ""
    graph_client_id: str = ""            # public app id, not a secret
    graph_tenant: str = "organizations"
    open_report_after_run: bool = False


def validate(s: DesktopSettings) -> DesktopSettings:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s.run_time):
        raise ConfigError("The daily run time must look like 07:00 (24-hour clock).")
    if not s.source.strip():
        raise ConfigError("Choose a data source: demo, r365, or the path to a DSS export file.")
    if s.draft_to and not re.fullmatch(r"[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+", s.draft_to):
        raise ConfigError("The draft email address doesn't look right. Use one address, like name@company.example.")
    if s.draft_email_enabled and not s.draft_to:
        raise ConfigError("To prepare a draft email, fill in who it is addressed to.")
    if s.draft_email_enabled and not s.graph_client_id:
        raise ConfigError("To prepare a draft email, fill in the Microsoft app ID (see docs/GRAPH_PERMISSIONS.md).")
    if not re.fullmatch(r"[A-Za-z0-9-]{0,64}", s.graph_client_id):
        raise ConfigError("The Microsoft app ID should be letters, digits and dashes only.")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", s.graph_tenant):
        raise ConfigError("The Microsoft tenant should be 'organizations' or a tenant name/ID.")
    return s


def load(path: Optional[Path] = None) -> DesktopSettings:
    path = Path(path) if path else settings_file()
    if not path.exists():
        return DesktopSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        raise ConfigError(f"The settings file {path} could not be read ({exc}). Fix or delete it.")
    known = {f.name for f in fields(DesktopSettings)}
    return DesktopSettings(**{k: v for k, v in raw.items() if k in known})


def save(s: DesktopSettings, path: Optional[Path] = None) -> Path:
    validate(s)
    path = Path(path) if path else settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(s), indent=2) + "\n", encoding="utf-8")
    return path
