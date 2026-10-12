"""Reads rules.toml. Unknown keys are errors so a typo can't silently disable a rule."""

import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List

from .errors import ConfigError


@dataclass
class Config:
    expected: List[str] = field(default_factory=list)
    ignore: List[str] = field(default_factory=list)
    pos_enabled: bool = True
    cash_enabled: bool = True
    cash_limit: Decimal = Decimal("5.00")
    receipts_enabled: bool = True
    receipts_allowed: int = 0
    exceptions_enabled: bool = True
    exceptions_allowed: int = 0
    unapproved_enabled: bool = True
    title: str = "Morning exception report"
    ai_enabled: bool = False
    ai_endpoint: str = "http://localhost:11434"
    ai_model: str = "your-local-model"
    ai_timeout: float = 30.0


_ALLOWED = {
    "locations": {"expected", "ignore"},
    "rules": {"missing_pos_import", "cash_variance", "missing_receipts",
              "payment_exceptions", "unapproved_entry"},
    "report": {"title"},
    "ai": {"enabled", "endpoint", "model", "timeout_seconds"},
}
_RULE_KEYS = {
    "missing_pos_import": {"enabled"},
    "cash_variance": {"enabled", "limit"},
    "missing_receipts": {"enabled", "allowed"},
    "payment_exceptions": {"enabled", "allowed"},
    "unapproved_entry": {"enabled"},
}


def _check_keys(section: str, data: dict, allowed: set) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise ConfigError(
            f"rules file: unknown setting '{extra[0]}' in [{section}]. "
            f"Allowed here: {', '.join(sorted(allowed))}.")


def _bool(section: str, key: str, value) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"rules file: [{section}] {key} must be true or false.")
    return value


def _count(section: str, key: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"rules file: [{section}] {key} must be a whole number, 0 or more.")
    return value


def _names(section: str, key: str, value) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f'rules file: [{section}] {key} must be a list like ["Name A", "Name B"].')
    return [v.strip() for v in value if v.strip()]


def load_config(path) -> Config:
    path = Path(path)
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"rules file not found: {path}")
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"rules file {path} is not valid: {exc}")
    return parse_config(raw)


def parse_config(raw: dict) -> Config:
    cfg = Config()
    _check_keys("top level", raw, set(_ALLOWED))
    for name, allowed in _ALLOWED.items():
        if name in raw and not isinstance(raw[name], dict):
            raise ConfigError(f"rules file: [{name}] must be a section.")

    loc = raw.get("locations", {})
    _check_keys("locations", loc, _ALLOWED["locations"])
    cfg.expected = _names("locations", "expected", loc.get("expected", []))
    cfg.ignore = _names("locations", "ignore", loc.get("ignore", []))

    rules = raw.get("rules", {})
    _check_keys("rules", rules, _ALLOWED["rules"])
    for rname, keys in _RULE_KEYS.items():
        section = rules.get(rname, {})
        if not isinstance(section, dict):
            raise ConfigError(f"rules file: [rules.{rname}] must be a section.")
        _check_keys(f"rules.{rname}", section, keys)
    r = rules.get
    cfg.pos_enabled = _bool("rules.missing_pos_import", "enabled",
                            r("missing_pos_import", {}).get("enabled", True))
    cash = r("cash_variance", {})
    cfg.cash_enabled = _bool("rules.cash_variance", "enabled", cash.get("enabled", True))
    limit = cash.get("limit", 5.00)
    try:
        if isinstance(limit, bool):
            raise InvalidOperation
        cfg.cash_limit = Decimal(str(limit))
    except InvalidOperation:
        raise ConfigError("rules file: [rules.cash_variance] limit must be a number of dollars.")
    if cfg.cash_limit < 0:
        raise ConfigError("rules file: [rules.cash_variance] limit cannot be negative.")
    rec = r("missing_receipts", {})
    cfg.receipts_enabled = _bool("rules.missing_receipts", "enabled", rec.get("enabled", True))
    cfg.receipts_allowed = _count("rules.missing_receipts", "allowed", rec.get("allowed", 0))
    pay = r("payment_exceptions", {})
    cfg.exceptions_enabled = _bool("rules.payment_exceptions", "enabled", pay.get("enabled", True))
    cfg.exceptions_allowed = _count("rules.payment_exceptions", "allowed", pay.get("allowed", 0))
    cfg.unapproved_enabled = _bool("rules.unapproved_entry", "enabled",
                                   r("unapproved_entry", {}).get("enabled", True))

    rep = raw.get("report", {})
    _check_keys("report", rep, _ALLOWED["report"])
    title = rep.get("title", cfg.title)
    if not isinstance(title, str) or not title.strip():
        raise ConfigError("rules file: [report] title must be text.")
    cfg.title = title.strip()

    ai = raw.get("ai", {})
    _check_keys("ai", ai, _ALLOWED["ai"])
    cfg.ai_enabled = _bool("ai", "enabled", ai.get("enabled", False))
    for key in ("endpoint", "model"):
        if not isinstance(ai.get(key, "x"), str):
            raise ConfigError(f"rules file: [ai] {key} must be text.")
    cfg.ai_endpoint = ai.get("endpoint", cfg.ai_endpoint)
    cfg.ai_model = ai.get("model", cfg.ai_model)
    timeout = ai.get("timeout_seconds", cfg.ai_timeout)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError("rules file: [ai] timeout_seconds must be a positive number.")
    cfg.ai_timeout = float(timeout)
    return cfg
