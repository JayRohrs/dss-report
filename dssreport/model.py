"""The one record shape every adapter must produce.

Every field except location and business_date may be None. None means
"we do not know" and is never treated as zero, false or clean.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Optional


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
