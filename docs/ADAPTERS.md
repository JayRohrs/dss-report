# Data sources (adapters)

An adapter turns "wherever the numbers live" into a list of `DayRecord` objects (see `dssreport/model.py`). The rules and report never know where the data came from.

## The record

| Field | Meaning | Unknown is |
|---|---|---|
| `location` | name, text (required) | — |
| `business_date` | date (required) | — |
| `sales_total` | money | `None` |
| `payments` | payment type → money | `None` per type |
| `cash_over_short` | money; negative = short, positive = over | `None` |
| `missing_receipts` | whole number | `None` |
| `payment_exceptions` | whole number | `None` |
| `approved` | true/false | `None` |
| `pos_import_received` | true/false | `None` |

**The one rule that matters:** if a value is blank or unavailable, return `None`. Never return 0 or False to fill a gap. `None` is reported as UNKNOWN; a made-up 0 would hide a problem.

## Built in

- **CSV/JSON** (`--input file.csv`, `file.json`, or a folder of them). CSV columns: `location, business_date (YYYY-MM-DD), sales_total, pay_<type> (any number), cash_over_short, missing_receipts, payment_exceptions, approved (yes/no), pos_import_received (yes/no)`. JSON is a list of objects with the same names, with `payments` as an object. See `examples/demo/`. Bad values stop the run with the file and line; two rows for the same location and day are an error; unrecognised columns produce a warning.
- **Demo** (`--input demo`): made-up data generated in `dssreport/adapters/demo.py`.

## Writing an adapter for your own accounting system

Adapters can be written for any accounting system that offers an export or an API. Someone comfortable with Python can do it in an afternoon:

1. Create `dssreport/adapters/mysystem.py` with a class that extends `Adapter` and implements `load()`:

```python
from .base import Adapter
from ..model import DayRecord
from ..errors import InputError

class MySystemAdapter(Adapter):
    name = "My accounting system"

    def __init__(self, spec):
        super().__init__()
        # read settings, e.g. a base address from an environment variable.
        # Never put passwords or keys in the code or the repo.

    def load(self):
        records = []
        for row in self._fetch_rows():              # read-only calls
            records.append(DayRecord(
                location=row["store"],
                business_date=...,                  # a datetime.date
                sales_total=Decimal(row["sales"]) if row.get("sales") not in (None, "") else None,
                # ...same pattern for each field; unknown -> None
            ))
        return records
```

2. Register it in `dssreport/adapters/__init__.py`: return `MySystemAdapter(spec)` for a keyword such as `--input mysystem`.
3. Run it against test data first. Add a test next to `tests/test_adapters_config.py`.

Guidelines: read only; raise `InputError` with a plain message for rows you can't understand rather than skipping them; map only what the system actually provides (leave the rest `None`); keep real data and credentials out of the repo (see `SECURITY.md`).

Simplest alternative: export from your system to CSV with the columns above and use the CSV adapter.
