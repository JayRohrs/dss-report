"""Builds the report facts: who needs a look, why, and who has nothing to review."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from .config import Config
from .errors import InputError
from .model import DayRecord
from .rules import ISSUE, UNKNOWN, Finding, evaluate_day

NEEDS_REVIEW = "NEEDS REVIEW"
UNKNOWN_STATUS = "UNKNOWN"


@dataclass
class LocationResult:
    name: str
    findings: List[Finding]

    @property
    def status(self) -> Optional[str]:
        """NEEDS REVIEW, UNKNOWN (data missing, nothing else wrong), or None (nothing to review)."""
        if any(f.kind == ISSUE for f in self.findings):
            return NEEDS_REVIEW
        if self.findings:
            return UNKNOWN_STATUS
        return None


@dataclass
class Report:
    title: str
    dates: List[date]
    attention: List[LocationResult]
    clear: List[LocationResult]
    headline: str
    source_name: str = ""
    summary_sentence: str = ""
    summary_source: str = ""  # "model", "template" or "" (no summary requested)
    rules_note: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.attention) + len(self.clear)

    @property
    def unknown_only(self) -> int:
        return sum(1 for r in self.attention if r.status == UNKNOWN_STATUS)

    @property
    def multi_day(self) -> bool:
        return len(self.dates) > 1


def date_label(dates: List[date]) -> str:
    if len(dates) == 1:
        return dates[0].isoformat()
    return f"{dates[0].isoformat()} to {dates[-1].isoformat()} ({len(dates)} days)"


def _n(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def make_headline(attention: int, unknown_only: int, total: int, label: str) -> str:
    if total == 0:
        return "No locations were found in the data, so nothing could be checked. Status: UNKNOWN."
    clear = total - attention
    if attention == 0:
        return f"Nothing to review: all {_n(total, 'location')} checked out for {label}."
    parts = [f"{attention} of {_n(total, 'location')} need a look for {label}."]
    parts.append(f"{clear} {'has' if clear == 1 else 'have'} nothing to review." if clear
                 else "Every location has something to look at.")
    if unknown_only:
        parts.append(f"{_n(unknown_only, 'location')} {'is' if unknown_only == 1 else 'are'} "
                     "UNKNOWN because data is missing.")
    return " ".join(parts)


def window(records: List[DayRecord], end: Optional[date], days: int) -> List[date]:
    if days < 1:
        raise InputError("--days must be 1 or more.")
    if end is None:
        if not records:
            raise InputError("The input has no records, and no --date was given.")
        end = max(r.business_date for r in records)
    return [end - timedelta(days=days - 1 - i) for i in range(days)]


def rules_note(cfg: Config) -> List[str]:
    def onoff(enabled, text):
        return text if enabled else text.split(":")[0] + ": switched off"
    return [
        onoff(cfg.pos_enabled, "POS import: flagged if it did not arrive"),
        onoff(cfg.cash_enabled, f"Cash over/short: flagged above ${cfg.cash_limit:,.2f} either way"),
        onoff(cfg.receipts_enabled, f"Missing receipts: flagged above {cfg.receipts_allowed}"),
        onoff(cfg.exceptions_enabled, f"Payment exceptions: flagged above {cfg.exceptions_allowed}"),
        onoff(cfg.unapproved_enabled, "Approval: flagged if not approved"),
        "No data or a blank value: always shown as UNKNOWN",
    ]


def build_report(records: List[DayRecord], cfg: Config, end: Optional[date] = None,
                 days: int = 1, source_name: str = "") -> Report:
    dates = window(records, end, days)
    by_key: Dict[tuple, DayRecord] = {(r.location, r.business_date): r for r in records}
    names = set(cfg.expected) | {r.location for r in records}
    names -= set(cfg.ignore)
    results = []
    for name in sorted(names, key=str.lower):
        findings: List[Finding] = []
        for day in dates:
            findings.extend(evaluate_day(name, day, by_key.get((name, day)), cfg))
        results.append(LocationResult(name, findings))
    order = {NEEDS_REVIEW: 0, UNKNOWN_STATUS: 1}
    attention = sorted((r for r in results if r.findings),
                       key=lambda r: (order[r.status], r.name.lower()))
    clear = [r for r in results if not r.findings]
    unknown_only = sum(1 for r in attention if r.status == UNKNOWN_STATUS)
    return Report(
        title=cfg.title, dates=dates, attention=attention, clear=clear,
        headline=make_headline(len(attention), unknown_only, len(results), date_label(dates)),
        source_name=source_name, rules_note=rules_note(cfg))


def reasons(result: LocationResult, multi_day: bool) -> List[str]:
    """One plain line per finding. Unknowns say UNKNOWN so they can't be read as zero."""
    lines = []
    for f in sorted(result.findings, key=lambda f: (f.business_date, f.kind != ISSUE)):
        text = f.text if f.kind == ISSUE else f"UNKNOWN: {f.text}"
        lines.append(f"{f.business_date.isoformat()}: {text}" if multi_day else text)
    return lines
