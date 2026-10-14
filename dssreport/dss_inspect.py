"""`python -m dssreport export inspect FILE`: describe a DSS list export WITHOUT revealing any place name, amount
or identifier, so the result can be pasted into a chat or a hand-off note.

It prints only: the file's shape, the column headings (headings are not private), which ones the program
recognised, the status words and how many rows have each, the shape of the dates and numbers (digits replaced by
"d"), counts, and whether the file's own row count agrees. The file is only read."""

import re
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from . import dss_export as E

_LIMIT = Decimal("5.00")


def _shape(text: str) -> str:
    return re.sub(r"[A-Za-z]|\d", lambda m: "d" if m.group().isdigit() else "a", text.strip())


def _top(counter: Counter, n: int = 4) -> str:
    return ", ".join(f"{k} (x{v})" for k, v in counter.most_common(n)) or "none"


def inspect(data: bytes, filename: str, today: Optional[date] = None, user_aliases: Optional[Path] = None,
            cash_limit: Decimal = _LIMIT) -> str:
    today = today or date.today()
    out: List[str] = []
    add = out.append
    rows, stats, kind = E.read_rows(data, filename)
    aliases = E.load_aliases(user=user_aliases) if user_aliases else E.load_aliases()
    add(f"File type: {kind}. Size: {len(data)} bytes. Byte-order mark: {'yes' if data.startswith(b'\xef\xbb\xbf') else 'no'}.")
    if kind in ("csv", "tsv", "txt"):
        add(f"Line endings: {'CRLF' if b'\r\n' in data else 'LF'}.")
    header_idx, cols = None, {}
    for i, row in enumerate(rows[:E.HEADER_SCAN_ROWS]):
        found, _ = aliases.match(row)
        if all(f in found for f in E.REQUIRED):
            header_idx, cols = i, found
            break
    if header_idx is None:
        add("No heading row with Location and Date was found in the first lines. This does not look like a DSS list.")
        return "\n".join(out) + "\n"
    header = rows[header_idx]
    add(f"Heading row is on line {header_idx + 1}. Lines above it: {header_idx}.")
    add(f"Headings ({len(header)}), exactly as written: " + ",".join(header))
    add("Recognised: " + (", ".join(f"{E.FIELD_WORDS[f]} <- '{header[i]}'" for f, i in cols.items()) or "none"))
    add("Not recognised: " + (", ".join(h for i, h in enumerate(header) if i not in cols.values() and h.strip()) or "none"))
    add("No column for: " + (", ".join(E.FIELD_WORDS[f] for f in E.FIELDS if f not in cols) or "nothing missing"))

    body = [r for r in rows[header_idx + 1:] if any(c.strip() for c in r)]

    def col(f):
        i = cols.get(f)
        return [(r[i].strip() if i is not None and i < len(r) else "") for r in body] if i is not None else None

    loc, dates, status, over = col("location"), col("business_date"), col("approval_status"), col("over_short")
    add(f"Rows below the headings: {len(body)}.")
    p = E.parse_export(rows, aliases, None, None, today, stats)
    add(f"Rows kept as one place and day: {len(p.records)}. Rows set aside as unreadable: {p.rows_read - len(p.records) if p.rows_read >= len(p.records) else 0}.")
    counts = col("stated_count")
    if counts is not None:
        nums = Counter(c for c in counts if c)
        add(f"The file's own row count column holds {len(nums)} distinct value(s) "
            f"({'agrees' if set(nums) == {str(len(body))} else 'DOES NOT agree'} with the {len(body)} rows).")
    elif p.stated_total is not None:
        add(f"The file states a total of {p.stated_total}; rows found: {len(body)}.")
    else:
        add("The file carries no row count, so completeness cannot be proven from it.")
    if loc is not None:
        add(f"Distinct places: {len(set(loc))}. Places with leading/trailing spaces: {sum(1 for r in body if r[cols['location']] != r[cols['location']].strip())}. "
            f"Places containing non-ASCII characters: {len({l for l in loc if not l.isascii()})}.")
    if dates is not None:
        add("Date shapes: " + _top(Counter(_shape(d) for d in dates)) + ". Date order read as: " + E.detect_date_order(dates)[0] + ".")
        parsed = [E.parse_date(d, E.detect_date_order(dates)[0]) for d in dates]
        good = [d for d in parsed if d]
        if good:
            add(f"Days covered: {len(set(good))}, from {min(good).isoformat()} to {max(good).isoformat()}.")
        pairs = Counter(zip(loc or [], parsed))
        add(f"Place+day combinations that appear more than once: {sum(1 for v in pairs.values() if v > 1)}.")
    if status is not None:
        add("Status words (count of rows): " + ", ".join(f"'{k}' x{v}" for k, v in Counter(status).most_common()) + ".")
        if cols.get("approval_status") is not None:
            others = [h for h in header if norm_is_status(h) and h != header[cols['approval_status']]]
            if others:
                add("Other status-like columns present: " + ", ".join(others) + " (the program uses '" + header[cols["approval_status"]] + "').")
    if over is not None:
        vals = []
        for v in over:
            amount, _bad = E.parse_money(v)
            vals.append(amount)
        neg = sum(1 for v in vals if v is not None and v < 0)
        pos = sum(1 for v in vals if v is not None and v > 0)
        zero = sum(1 for v in vals if v == 0)
        blank = sum(1 for v, raw in zip(vals, over) if v is None and not raw)
        add(f"Over/Short: {neg} negative, {pos} positive, {zero} zero, {blank} blank. Shapes: " + _top(Counter(_shape(v) for v in over if v)) + ".")
        add(f"Over/Short beyond ${cash_limit} either way: {sum(1 for v in vals if v is not None and abs(v) > cash_limit)} rows. "
            "(The sign convention is NOT proven by this file.)")
        if status is not None:
            unapproved = [i for i, s in enumerate(status) if s.strip().lower() == "unapproved"]
            if unapproved:
                with_diff = sum(1 for i in unapproved if vals[i] is not None and abs(vals[i]) > cash_limit)
                add(f"Of {len(unapproved)} 'Unapproved' rows: {with_diff} have an Over/Short beyond the limit, "
                    f"{len(unapproved) - with_diff} do not. (Not a proven reason for anything.)")
    for f, label in (("net_sales", "Net Sales"), ("deposit", "Total Deposit")):
        v = col(f)
        if v is not None:
            add(f"{label} shapes: " + _top(Counter(_shape(x) for x in v if x)) + f". Blank: {sum(1 for x in v if not x)}.")
    return "\n".join(out) + "\n"


def norm_is_status(heading: str) -> bool:
    return "status" in E.norm(heading)
