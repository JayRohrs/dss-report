"""Where the program keeps its own files. Never inside the repo, never with real data in git."""

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Settings, mapping, run log and saved reports live here.

    DSSREPORT_HOME overrides it (used by the installer and the tests).
    """
    env = os.environ.get("DSSREPORT_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DssReport"
    return Path.home() / ".dssreport"


def settings_path() -> Path:
    return app_dir() / "settings.json"


def mapping_path() -> Path:
    return app_dir() / "r365_mapping.toml"


def state_path() -> Path:
    return app_dir() / "state.json"


def log_path() -> Path:
    return app_dir() / "run.log"


def reports_dir() -> Path:
    return app_dir() / "reports"


def resolve_rules_path(explicit=None) -> Path:
    """--rules wins; then rules.toml in the program's home folder (if DSSREPORT_HOME is set);
    then rules.toml in the current folder; else the home folder's (to be created on save)."""
    if explicit:
        return Path(explicit)
    if os.environ.get("DSSREPORT_HOME"):
        return app_dir() / "rules.toml"
    if Path("rules.toml").exists():
        return Path("rules.toml")
    return app_dir() / "rules.toml"
