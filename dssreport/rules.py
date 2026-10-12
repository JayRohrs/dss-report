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


def evaluate_day(location: str, day: date, rec: Optional[DayRecord], cfg: Config) -> List[Finding]:
    if rec is None:
        return [Finding(day, NO_DATA, UNKNOWN, "No data for this day")]
    out: List[Finding] = []

    def add(rule, kind, text):
        out.append(Finding(day, rule, kind, text))

    if cfg.pos_enabled:
        if rec.pos_import_received is False:
            add(POS_IMPORT, ISSUE, "POS import did not arrive")
        elif rec.pos_import_received is None:
            add(POS_IMPORT, UNKNOWN, "POS import status is blank")

    # With no POS import, sales figures are expected to be blank; the missing
    # import already says so. Otherwise a blank sales total is unknown.
    if rec.pos_import_received is not False and rec.sales_total is None:
        add(SALES_BLANK, UNKNOWN, "Sales total is blank")

    if cfg.cash_enabled:
        v = rec.cash_over_short
        if v is None:
            add(CASH, UNKNOWN, "Cash over/short is blank")
        elif abs(v) > cfg.cash_limit:
            direction = "short" if v < 0 else "over"
            add(CASH, ISSUE, f"Cash is {money(v)} {direction} (limit {money(cfg.cash_limit)})")

    if cfg.receipts_enabled:
        n = rec.missing_receipts
        if n is None:
            add(RECEIPTS, UNKNOWN, "Missing-receipt count is blank")
        elif n > cfg.receipts_allowed:
            add(RECEIPTS, ISSUE, f"{_plural(n, 'receipt')} missing")

    if cfg.exceptions_enabled:
        n = rec.payment_exceptions
        if n is None:
            add(EXCEPTIONS, UNKNOWN, "Payment-exception count is blank")
        elif n > cfg.exceptions_allowed:
            add(EXCEPTIONS, ISSUE, f"{_plural(n, 'payment exception')}")

    if cfg.unapproved_enabled:
        if rec.approved is False:
            add(UNAPPROVED, ISSUE, "Entry is not approved")
        elif rec.approved is None:
            add(UNAPPROVED, UNKNOWN, "Approval status is blank")
    return out
