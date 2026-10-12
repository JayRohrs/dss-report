"""The review rules, in plain Python. Thresholds come from rules.toml.

Each check returns Findings. A Finding is either:
  ISSUE   - the data is there and breaks a rule
  UNKNOWN - the data needed to check the rule is missing
A location with any UNKNOWN is never reported as having nothing to review.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from .config import Config
from .model import DayRecord

ISSUE = "issue"
UNKNOWN = "unknown"

# rule ids (also used by the tests)
NO_DATA = "no_data"
POS_IMPORT = "missing_pos_import"
CASH = "cash_variance"
RECEIPTS = "missing_receipts"
EXCEPTIONS = "payment_exceptions"
UNAPPROVED = "unapproved_entry"
SALES_BLANK = "sales_blank"
PAYMENTS_TOTAL = "payments_total"

# Which DayRecord fields each check needs. If the data source cannot provide a
# field at all (not mapped), the check is skipped and shown as "needs mapping".
REQUIRES = {
    POS_IMPORT: ("pos_import_received",),
    CASH: ("cash_over_short",),
    RECEIPTS: ("missing_receipts",),
    EXCEPTIONS: ("payment_exceptions",),
    UNAPPROVED: ("approved",),
    PAYMENTS_TOTAL: ("sales_total", "payments"),
    SALES_BLANK: ("sales_total",),
}
LABELS = {
    POS_IMPORT: "POS import",
    CASH: "Cash over/short",
    RECEIPTS: "Missing receipts",
    EXCEPTIONS: "Payment exceptions",
    UNAPPROVED: "Approval",
    PAYMENTS_TOTAL: "Payments add up to sales",
    SALES_BLANK: "Sales total",
}

ON, OFF, NEEDS_MAPPING, NOT_LICENSED = "on", "off", "needs mapping", "not licensed"


def _enabled(cfg: Config, rule: str) -> bool:
    return {POS_IMPORT: cfg.pos_enabled, CASH: cfg.cash_enabled, RECEIPTS: cfg.receipts_enabled,
            EXCEPTIONS: cfg.exceptions_enabled, UNAPPROVED: cfg.unapproved_enabled,
            PAYMENTS_TOTAL: cfg.payments_enabled, SALES_BLANK: True}[rule]


def rule_status(cfg: Config, rule: str, unmapped=frozenset()) -> str:
    """ON, OFF (switched off), or NEEDS_MAPPING (data source has no field for it)."""
    if not _enabled(cfg, rule):
        return OFF
    if rule in cfg.not_licensed:
        return NOT_LICENSED
    if any(f in unmapped for f in REQUIRES[rule]):
        return NEEDS_MAPPING
    return ON


@dataclass(frozen=True)
class Finding:
    business_date: date
    rule: str
    kind: str  # ISSUE or UNKNOWN
    text: str


def money(value: Decimal) -> str:
    return f"${abs(value):,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def evaluate_day(location: str, day: date, rec: Optional[DayRecord], cfg: Config,
                 unmapped=frozenset()) -> List[Finding]:
    if rec is None:
        return [Finding(day, NO_DATA, UNKNOWN, "No data for this day")]
    out: List[Finding] = []

    def add(rule, kind, text):
        out.append(Finding(day, rule, kind, text))

    def on(rule):
        return rule_status(cfg, rule, unmapped) == ON

    if on(POS_IMPORT):
        if rec.pos_import_received is False:
            add(POS_IMPORT, ISSUE, "POS import did not arrive")
        elif rec.pos_import_received is None:
            add(POS_IMPORT, UNKNOWN, "POS import status is blank")

    # With no POS import, sales figures are expected to be blank; the missing
    # import already says so. Otherwise a blank sales total is unknown.
    if on(SALES_BLANK) and rec.pos_import_received is not False and rec.sales_total is None:
        add(SALES_BLANK, UNKNOWN, "Sales total is blank")

    if on(CASH):
        v = rec.cash_over_short
        if v is None:
            add(CASH, UNKNOWN, "Cash over/short is blank")
        elif abs(v) > cfg.cash_limit:
            direction = "short" if v < 0 else "over"
            add(CASH, ISSUE, f"Cash is {money(v)} {direction} (limit {money(cfg.cash_limit)})")

    if on(RECEIPTS):
        n = rec.missing_receipts
        if n is None:
            add(RECEIPTS, UNKNOWN, "Missing-receipt count is blank")
        elif n > cfg.receipts_allowed:
            add(RECEIPTS, ISSUE, f"{_plural(n, 'receipt')} missing")

    if on(EXCEPTIONS):
        n = rec.payment_exceptions
        if n is None:
            add(EXCEPTIONS, UNKNOWN, "Payment-exception count is blank")
        elif n > cfg.exceptions_allowed:
            add(EXCEPTIONS, ISSUE, f"{_plural(n, 'payment exception')}")

    if on(UNAPPROVED):
        if rec.approved is False:
            add(UNAPPROVED, ISSUE, "Entry is not approved")
        elif rec.approved is None:
            add(UNAPPROVED, UNKNOWN, "Approval status is blank")

    # Optional: the payment types should add up to the sales total.
    if on(PAYMENTS_TOTAL) and rec.pos_import_received is not False:
        amounts = list(rec.payments.values())
        if rec.sales_total is None or not amounts or any(a is None for a in amounts):
            if rec.sales_total is not None or amounts:
                add(PAYMENTS_TOTAL, UNKNOWN, "Payment types are blank or missing, so they can't be added up")
        else:
            total = sum(amounts, Decimal("0"))
            if abs(total - rec.sales_total) > cfg.payments_tolerance:
                add(PAYMENTS_TOTAL, ISSUE,
                    f"Payments add up to {money(total)} but the sales total is {money(rec.sales_total)}")
    return out
