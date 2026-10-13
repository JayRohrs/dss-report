"""The one record shape every adapter must produce.

Every field except location and business_date may be None. None means
"we do not know" and is never treated as zero, false or clean.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class DayRecord:
    location: str
    business_date: date
    sales_total: Optional[Decimal] = None
    # payment type -> amount (None = that type was left blank)
    payments: Dict[str, Optional[Decimal]] = field(default_factory=dict)
    # negative = cash short, positive = cash over
    cash_over_short: Optional[Decimal] = None
    missing_receipts: Optional[int] = None
    payment_exceptions: Optional[int] = None
    approved: Optional[bool] = None
    pos_import_received: Optional[bool] = None
    # Why approval is unknown, in words (a status word that is not treated as approved/not approved, a file
    # that is too old, ...). Shown in the report as UNKNOWN; never turned into approved or not approved.
    approval_note: Optional[str] = None
    # Fields on which several source rows for this day disagreed (shown as UNKNOWN and listed as a conflict)
    conflicts: Tuple[str, ...] = ()
