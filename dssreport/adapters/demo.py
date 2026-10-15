"""Made-up demo data: 3 invented restaurants, 14 days, a few planted exceptions.

Everything here is fictional. The same data is produced every time.
"""

import csv
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List

from ..model import DayRecord
from .base import Adapter

LOCATIONS = ["Demo Bistro North", "Demo Grill East", "Demo Cafe South", "Demo Diner West"]
LAST_DAY = date(2026, 3, 13)
DAYS = 14
PAY_TYPES = ["cash", "card", "gift_card", "delivery_app"]

# Planted exceptions, so the demo and the tests have something to find.
PLANTED = {
    # latest day: every kind of result a first-time viewer should see
    "pos_missing_cash_blank": ("Demo Bistro North", date(2026, 3, 13)),  # issue + UNKNOWN
    "cash_short_receipts_unapproved": ("Demo Grill East", date(2026, 3, 13)),
    "no_row": ("Demo Cafe South", date(2026, 3, 13)),                    # no data: UNKNOWN
    "clean_day": ("Demo Diner West", date(2026, 3, 13)),
    # earlier days (see them with --days 14)
    "payment_exceptions": ("Demo Bistro North", date(2026, 3, 11)),
    "cash_over": ("Demo Grill East", date(2026, 3, 10)),
    "cash_blank": ("Demo Diner West", date(2026, 3, 9)),                 # blank cash only: UNKNOWN
    "missing_receipt": ("Demo Bistro North", date(2026, 3, 5)),
    "payments_dont_add_up": ("Demo Cafe South", date(2026, 3, 7)),       # optional rule
}


def _d(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def generate() -> List[DayRecord]:
    rng = random.Random(20260313)
    records = []
    for loc in LOCATIONS:
        base = {"Demo Bistro North": 5200, "Demo Grill East": 7400, "Demo Cafe South": 3100,
                "Demo Diner West": 4300}[loc]
        for offset in range(DAYS):
            day = LAST_DAY - timedelta(days=DAYS - 1 - offset)
            if (loc, day) == PLANTED["no_row"]:
                continue
            sales = _d(base + rng.randint(-600, 900) + rng.randint(0, 99) / 100)
            cash = _d(sales * Decimal("0.18"))
            gift = _d(sales * Decimal("0.03"))
            delivery = _d(sales * Decimal("0.07"))
            payments = {"cash": cash, "card": sales - cash - gift - delivery,
                        "gift_card": gift, "delivery_app": delivery}
            fields = dict(
                location=loc, business_date=day, sales_total=sales, payments=payments,
                cash_over_short=_d(rng.randint(-150, 150) / 100), missing_receipts=0,
                payment_exceptions=0, approved=True, pos_import_received=True)
            if (loc, day) == PLANTED["pos_missing_cash_blank"]:
                fields.update(sales_total=None, payments={t: None for t in PAY_TYPES},
                              pos_import_received=False, cash_over_short=None)
            elif (loc, day) == PLANTED["cash_short_receipts_unapproved"]:
                fields.update(cash_over_short=_d("-23.50"), missing_receipts=2, approved=False)
            elif (loc, day) == PLANTED["payment_exceptions"]:
                fields.update(payment_exceptions=2)
            elif (loc, day) == PLANTED["cash_over"]:
                fields.update(cash_over_short=_d("12.00"))
            elif (loc, day) == PLANTED["cash_blank"]:
                fields.update(cash_over_short=None)
            elif (loc, day) == PLANTED["payments_dont_add_up"]:
                fields.update(payments={**payments, "card": payments["card"] - _d("40.00")})
            elif (loc, day) == PLANTED["missing_receipt"]:
                fields.update(missing_receipts=1)
            records.append(DayRecord(**fields))
    return records


class DemoAdapter(Adapter):
    name = "built-in demo data (made up)"

    def load(self) -> List[DayRecord]:
        return generate()


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def write_demo_files(out_dir, formats=("csv", "json")) -> List[Path]:
    """Write the demo data as CSV and/or JSON so people can see the input format."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = generate()
    written = []
    if "csv" in formats:
        path = out / "dss_demo.csv"
        header = (["location", "business_date", "sales_total"] + [f"pay_{t}" for t in PAY_TYPES]
                  + ["cash_over_short", "missing_receipts", "payment_exceptions",
                     "approved", "pos_import_received"])
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(header)
            for r in records:
                w.writerow([r.location, r.business_date.isoformat(), _cell(r.sales_total)]
                           + [_cell(r.payments.get(t)) for t in PAY_TYPES]
                           + [_cell(r.cash_over_short), _cell(r.missing_receipts),
                              _cell(r.payment_exceptions), _cell(r.approved),
                              _cell(r.pos_import_received)])
        written.append(path)
    if "json" in formats:
        path = out / "dss_demo.json"
        data = [{
            "location": r.location, "business_date": r.business_date.isoformat(),
            "sales_total": None if r.sales_total is None else str(r.sales_total),
            "payments": {t: (None if v is None else str(v)) for t, v in r.payments.items()},
            "cash_over_short": None if r.cash_over_short is None else str(r.cash_over_short),
            "missing_receipts": r.missing_receipts, "payment_exceptions": r.payment_exceptions,
            "approved": r.approved, "pos_import_received": r.pos_import_received,
        } for r in records]
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written
