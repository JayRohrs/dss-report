"""Builds the report facts: who needs a look, why, and who has nothing to review."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from .config import Config
from .errors import InputError
from .model import DayRecord
from .rules import (ISSUE, LABELS, NEEDS_MAPPING, NOT_LICENSED, OFF, ON, PAYMENTS_TOTAL, REQUIRES, UNKNOWN,
                    Finding, evaluate_day, rule_status)

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
    #: checks that could not run because the data source has no mapped field for them
    needs_mapping: List[str] = field(default_factory=list)
    late_note: str = ""
    scope_note: str = ""
    licence_line: str = ""
    licence_problem: bool = False
    licence_notice: str = ""

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


def make_headline(attention: int, unknown_only: int, total: int, label: str,
                  skipped: int = 0) -> str:
    if total == 0:
        return "No locations were found in the data, so nothing could be checked. Status: UNKNOWN."
    clear = total - attention
    caveat = (f" {_n(skipped, 'check')} could not run (needs mapping), so this is not a full all-clear."
              if skipped else "")
    if attention == 0:
        return (f"Nothing flagged: all {_n(total, 'location')} passed the checks that ran for {label}."
                if skipped else f"Nothing to review: all {_n(total, 'location')} checked out for {label}.") + caveat
    parts = [f"{attention} of {_n(total, 'location')} need a look for {label}."]
    parts.append(f"{clear} {'has' if clear == 1 else 'have'} nothing to review." if clear
                 else "Every location has something to look at.")
    if unknown_only:
        parts.append(f"{_n(unknown_only, 'location')} {'is' if unknown_only == 1 else 'are'} "
                     "UNKNOWN because data is missing.")
    return " ".join(parts) + caveat


def window(records: List[DayRecord], end: Optional[date], days: int) -> List[date]:
    if days < 1:
        raise InputError("--days must be 1 or more.")
    if end is None:
        if not records:
            raise InputError("The input has no records, and no --date was given.")
        end = max(r.business_date for r in records)
    return [end - timedelta(days=days - 1 - i) for i in range(days)]


def rules_note(cfg: Config, unmapped=frozenset()) -> List[str]:
    from .rules import (CASH, EXCEPTIONS, POS_IMPORT, RECEIPTS, UNAPPROVED)
    detail = {
        POS_IMPORT: "flagged if it did not arrive",
        CASH: f"flagged above ${cfg.cash_limit:,.2f} either way",
        RECEIPTS: f"flagged above {cfg.receipts_allowed}",
        EXCEPTIONS: f"flagged above {cfg.exceptions_allowed}",
        UNAPPROVED: "flagged if not approved",
        PAYMENTS_TOTAL: f"flagged if more than ${cfg.payments_tolerance:,.2f} apart",
    }
    notes = []
    for rule, text in detail.items():
        status = rule_status(cfg, rule, unmapped)
        if status == ON:
            notes.append(f"{LABELS[rule]}: {text}")
        elif status == NOT_LICENSED:
            notes.append(f"{LABELS[rule]}: NOT IN YOUR LICENCE (not checked)")
        elif status == NEEDS_MAPPING:
            notes.append(f"{LABELS[rule]}: NEEDS MAPPING (not checked; see docs/R365_OPEN_QUESTIONS.md)")
        else:
            notes.append(f"{LABELS[rule]}: switched off")
    notes.append("No data or a blank value: always shown as UNKNOWN")
    return notes


def skipped_checks(cfg: Config, unmapped=frozenset()) -> List[str]:
    return [LABELS[r] for r in REQUIRES if rule_status(cfg, r, unmapped) == NEEDS_MAPPING]


def build_report(records: List[DayRecord], cfg: Config, end: Optional[date] = None,
                 days: int = 1, source_name: str = "", unmapped=frozenset()) -> Report:
    dates = window(records, end, days)
    by_key: Dict[tuple, DayRecord] = {(r.location, r.business_date): r for r in records}
    if cfg.include:
        names = set(cfg.include)
    else:
        names = set(cfg.expected) | {r.location for r in records}
    names -= set(cfg.ignore)
    results = []
    for name in sorted(names, key=str.lower):
        findings: List[Finding] = []
        for day in dates:
            findings.extend(evaluate_day(name, day, by_key.get((name, day)), cfg, unmapped))
        results.append(LocationResult(name, findings))
    order = {NEEDS_REVIEW: 0, UNKNOWN_STATUS: 1}
    attention = sorted((r for r in results if r.findings),
                       key=lambda r: (order[r.status], r.name.lower()))
    clear = [r for r in results if not r.findings]
    unknown_only = sum(1 for r in attention if r.status == UNKNOWN_STATUS)
    skipped = skipped_checks(cfg, unmapped)
    return Report(
        title=cfg.title, dates=dates, attention=attention, clear=clear,
        headline=make_headline(len(attention), unknown_only, len(results), date_label(dates),
                               len(skipped)),
        source_name=source_name, rules_note=rules_note(cfg, unmapped), needs_mapping=skipped)


def reasons(result: LocationResult, multi_day: bool) -> List[str]:
    """One plain line per finding. Unknowns say UNKNOWN so they can't be read as zero."""
    lines = []
    for f in sorted(result.findings, key=lambda f: (f.business_date, f.kind != ISSUE)):
        text = f.text if f.kind == ISSUE else f"UNKNOWN: {f.text}"
        lines.append(f"{f.business_date.isoformat()}: {text}" if multi_day else text)
    return lines


# ------------------------------------------------------------------ several connections in one report

@dataclass
class Section:
    """One R365 connection's part of the report: either a Report, or the plain reason it has none."""
    name: str
    report: Optional[Report] = None
    error: str = ""          # e.g. "could not connect: R365 refused the sign-in..."


@dataclass
class MultiReport:
    title: str
    dates: List[date]
    sections: List[Section]
    headline: str
    rules_note: List[str] = field(default_factory=list)
    needs_mapping: List[str] = field(default_factory=list)
    source_name: str = ""
    late_note: str = ""
    licence_line: str = ""
    licence_problem: bool = False
    licence_notice: str = ""
    summary_sentence: str = ""
    summary_source: str = ""
    scope_note: str = ""

    @property
    def ok_sections(self) -> List[Section]:
        return [s for s in self.sections if s.report is not None]

    @property
    def failed_sections(self) -> List[Section]:
        return [s for s in self.sections if s.report is None]

    @property
    def all_failed(self) -> bool:
        return bool(self.sections) and not self.ok_sections

    @property
    def multi_day(self) -> bool:
        return len(self.dates) > 1

    def flat(self) -> Report:
        """All locations in one list (named "Connection: Location"), for the optional summary sentence."""
        att, clear = [], []
        for s in self.ok_sections:
            for r in s.report.attention:
                att.append(LocationResult(f"{s.name}: {r.name}", r.findings))
            for r in s.report.clear:
                clear.append(LocationResult(f"{s.name}: {r.name}", r.findings))
        return Report(self.title, self.dates, att, clear, self.headline, self.source_name)


def make_multi_headline(sections: List[Section], label: str, skipped: int) -> str:
    ok = [s for s in sections if s.report is not None]
    failed = len(sections) - len(ok)
    if not sections:
        return "No R365 connections are set up, so nothing could be checked. Status: UNKNOWN."
    if not ok:
        return (f"None of the {_n(len(sections), 'connection')} could be reached, so nothing could be "
                "checked. Status: UNKNOWN.")
    total = sum(s.report.total for s in ok)
    attention = sum(len(s.report.attention) for s in ok)
    unknown_only = sum(s.report.unknown_only for s in ok)
    where = f"across {_n(len(ok), 'connection')}"
    caveat = (f" {_n(skipped, 'check')} could not run (needs mapping), so this is not a full all-clear."
              if skipped else "")
    fail_note = (f" {_n(failed, 'connection')} could not be reached, so {'its' if failed == 1 else 'their'} "
                 "locations are UNKNOWN.") if failed else ""
    if attention == 0:
        if failed:
            return f"Nothing flagged at the {_n(len(ok), 'connection')} that answered ({_n(total, 'location')}) for {label}." + fail_note + caveat
        head = (f"Nothing flagged: all {_n(total, 'location')} {where} passed the checks that ran for {label}."
                if skipped else f"Nothing to review: all {_n(total, 'location')} {where} checked out for {label}.")
        return head + caveat
    clear = total - attention
    parts = [f"{attention} of {_n(total, 'location')} need a look for {label}, {where}."]
    parts.append(f"{clear} {'has' if clear == 1 else 'have'} nothing to review." if clear
                 else "Every location has something to look at.")
    if unknown_only:
        parts.append(f"{_n(unknown_only, 'location')} {'is' if unknown_only == 1 else 'are'} "
                     "UNKNOWN because data is missing.")
    return " ".join(parts) + fail_note + caveat


def build_multi_report(sections: List[Section], cfg: Config, dates: List[date],
                       source_name: str = "") -> MultiReport:
    ok = [s for s in sections if s.report is not None]
    skipped = sorted({x for s in ok for x in s.report.needs_mapping})
    return MultiReport(
        title=cfg.title, dates=dates, sections=sections,
        headline=make_multi_headline(sections, date_label(dates), len(skipped)),
        rules_note=(ok[0].report.rules_note if ok else rules_note(cfg)), needs_mapping=skipped,
        source_name=source_name)
