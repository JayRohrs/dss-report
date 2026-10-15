"""CSV / JSON adapter.

CSV columns (header row required, extra columns are ignored with a warning):
  location, business_date (YYYY-MM-DD), sales_total, pay_<type> (any number of
  these, e.g. pay_cash, pay_card), cash_over_short, missing_receipts,
  payment_exceptions, approved (yes/no), pos_import_received (yes/no)

A blank cell means "not known". JSON is a list of objects with the same names,
except payments is an object: {"cash": 100, "card": 250}. JSON null = not known.
"""

import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List

from ..errors import InputError
from ..model import DayRecord
from .base import Adapter

KNOWN = {"location", "business_date", "sales_total", "payments", "cash_over_short",
         "missing_receipts", "payment_exceptions", "approved", "pos_import_received"}
_TRUE = {"yes", "y", "true", "1"}
_FALSE = {"no", "n", "false", "0"}


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _money(value, where, name):
    if _blank(value):
        return None
    if isinstance(value, bool):
        raise InputError(f"{where}: {name} must be a number, got {value!r}.")
    text = str(value).strip().replace("$", "").replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise InputError(f"{where}: {name} must be a number, got {value!r}.")
    if not number.is_finite():
        raise InputError(f"{where}: {name} must be a number, got {value!r}.")
    return number


def _count(value, where, name):
    if _blank(value):
        return None
    if isinstance(value, bool):
        raise InputError(f"{where}: {name} must be a whole number, got {value!r}.")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        number = None
    if number is None or number != number.to_integral_value() or number < 0:
        raise InputError(f"{where}: {name} must be a whole number, 0 or more, got {value!r}.")
    return int(number)


def _flag(value, where, name):
    if _blank(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise InputError(f"{where}: {name} must be yes or no, got {value!r}.")


def record_from_mapping(raw: dict, where: str) -> DayRecord:
    """Shared by the CSV and JSON readers. `raw` uses the field names above."""
    location = raw.get("location")
    if _blank(location):
        raise InputError(f"{where}: location is empty.")
    text = raw.get("business_date")
    try:
        business_date = date.fromisoformat(str(text).strip())
    except ValueError:
        raise InputError(f"{where}: business_date must look like 2026-03-13, got {text!r}.")
    payments = {}
    for key, value in (raw.get("payments") or {}).items():
        payments[str(key)] = _money(value, where, f"payment '{key}'")
    return DayRecord(
        location=str(location).strip(),
        business_date=business_date,
        sales_total=_money(raw.get("sales_total"), where, "sales_total"),
        payments=payments,
        cash_over_short=_money(raw.get("cash_over_short"), where, "cash_over_short"),
        missing_receipts=_count(raw.get("missing_receipts"), where, "missing_receipts"),
        payment_exceptions=_count(raw.get("payment_exceptions"), where, "payment_exceptions"),
        approved=_flag(raw.get("approved"), where, "approved"),
        pos_import_received=_flag(raw.get("pos_import_received"), where, "pos_import_received"),
    )


class FileAdapter(Adapter):
    """Reads one .csv/.json file, or every .csv/.json file in a folder."""

    name = "CSV/JSON files"

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)

    def _files(self) -> List[Path]:
        if self.path.is_dir():
            files = sorted(p for p in self.path.iterdir()
                           if p.suffix.lower() in (".csv", ".json") and p.is_file())
            if not files:
                raise InputError(f"No .csv or .json files found in {self.path}.")
            return files
        if not self.path.is_file():
            raise InputError(f"Input not found: {self.path}")
        if self.path.suffix.lower() not in (".csv", ".json"):
            raise InputError(f"Input must be a .csv or .json file or a folder of them: {self.path}")
        return [self.path]

    def load(self) -> List[DayRecord]:
        records, seen = [], {}
        for file in self._files():
            rows = self._read_csv(file) if file.suffix.lower() == ".csv" else self._read_json(file)
            for where, raw in rows:
                rec = record_from_mapping(raw, where)
                key = (rec.location, rec.business_date)
                if key in seen:
                    raise InputError(
                        f"{rec.location} has two rows for {rec.business_date} "
                        f"({seen[key]} and {where}). The report can't tell which one is right, "
                        f"so it stopped. Delete one of the two rows (or fix its date) and run it again.")
                seen[key] = where
                records.append(rec)
        return records

    def _read_csv(self, file: Path):
        out = []
        with open(file, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            names = [n.strip() for n in (reader.fieldnames or [])]
            missing = {"location", "business_date"} - set(names)
            if missing:
                raise InputError(f"{file.name}: missing column(s): {', '.join(sorted(missing))}.")
            for n in names:
                if n not in KNOWN and not n.startswith("pay_"):
                    self.warnings.append(
                        f"{file.name}: column '{n}' was not recognised and was ignored.")
            for i, row in enumerate(reader, start=2):
                row = {(k or "").strip(): v for k, v in row.items()}
                if None in row.values() and "" in row:
                    raise InputError(f"{file.name} line {i}: more cells than headings.")
                payments = {k[4:]: v for k, v in row.items() if k.startswith("pay_") and len(k) > 4}
                raw = {k: v for k, v in row.items() if k in KNOWN}
                raw["payments"] = payments
                out.append((f"{file.name} line {i}", raw))
        return out

    def _read_json(self, file: Path):
        try:
            data = json.loads(file.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise InputError(f"{file.name}: not valid JSON ({exc}).")
        if isinstance(data, dict):
            data = data.get("records")
        if not isinstance(data, list):
            raise InputError(f"{file.name}: expected a list of records.")
        out = []
        for i, item in enumerate(data, start=1):
            where = f"{file.name} record {i}"
            if not isinstance(item, dict):
                raise InputError(f"{where}: expected an object.")
            for n in item:
                if n not in KNOWN:
                    self.warnings.append(f"{where}: field '{n}' was not recognised and was ignored.")
            if item.get("payments") is not None and not isinstance(item["payments"], dict):
                raise InputError(f"{where}: payments must be an object like {{\"cash\": 100}}.")
            out.append((where, item))
        return out
