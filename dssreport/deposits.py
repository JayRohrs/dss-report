"""The deposit matcher: lines up the deposit each place is EXPECTED to make (from the DSS list) with the
lines on a bank export, and explains each place in plain words.

It is a helper, not a report. It reads two files it is handed (a DSS list export and a bank export in CSV or
OFX form), changes nothing, makes no network call and never sends anything. It never guesses: a place is
"matched" only when the amount is exactly the same, the date is inside the window and nothing else could
equally be the answer. Everything else is "needs a look" (something odd the person should see) or "cannot
tell" (the files do not hold enough to say), with the reasons listed.

What is NOT known yet (the sign of Over/Short, how R365's fields map to a bank deposit, what a real bank file
looks like) is written down as labelled assumptions in data/deposit_matcher.toml and shown on screen.
"""

import csv
import io
import itertools
import re
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .dss_export import (ExportError, MAX_FILE_BYTES, detect_date_order, load_aliases, norm, parse_date,
                         parse_money, read_csv_rows, read_rows)
from .errors import ConfigError
from .paths import app_dir

MATCHED, LOOK, UNKNOWN = "matched", "look", "unknown"
BANK_EXTENSIONS = (".csv", ".ofx", ".qfx", ".txt")
SIGNS = ("unknown", "positive_is_over", "negative_is_over")


# ------------------------------------------------------------------------------------------ assumptions

@dataclass
class Assumptions:
    over_short_sign: str = "unknown"
    window_days_before: int = 0
    window_days_after: int = 3
    near_miss_max: Decimal = Decimal("5.00")
    max_split_lines: int = 3
    max_days_per_deposit: int = 3
    bank_decimal_comma: bool = False
    places: Dict[str, List[str]] = field(default_factory=dict)

    def lines(self) -> List[Tuple[str, str]]:
        """(label, plain sentence) for the screen. Every item says whether it is assumed or unknown."""
        sign = {"unknown": "UNKNOWN: whether a positive Over/Short means cash over or short. It is only quoted, never used to decide.",
                "positive_is_over": "ASSUMED (set by you): a positive Over/Short means cash OVER.",
                "negative_is_over": "ASSUMED (set by you): a negative Over/Short means cash OVER."}[self.over_short_sign]
        return [
            ("Over/Short sign", sign),
            ("R365 field", "ASSUMED: the DSS \"Total Deposit\" is what should reach the bank for that place and day. "
                           "Check one known day against the bank before trusting a match."),
            ("Bank file", "UNKNOWN: what your real bank export looks like. CSV with Date, Description and Amount (or Debit/Credit) "
                          "columns, and OFX, are understood. Positive amounts are taken as money in."),
            ("Timing", f"ASSUMED: a deposit posts {self.window_days_before} to {self.window_days_after} days after the business day."),
            ("Near miss", f"ASSUMED: a difference of up to ${self.near_miss_max} is shown as a near miss. It is never matched."),
            ("Split / combined", f"ASSUMED: one day can be split over up to {self.max_split_lines} bank lines, and one line can "
                                 f"cover up to {self.max_days_per_deposit} consecutive days."),
            ("Decimal comma", "ASSUMED: bank amounts use a point for cents (1,234.50). An amount like 23,50 is not read and is listed."
             if not self.bank_decimal_comma else
             "ASSUMED (set by you): the bank writes cents after a comma (23,50) and a point before thousands."),
        ]


def _shipped() -> Path:
    return Path(__file__).resolve().parent / "data" / "deposit_matcher.toml"


def load_assumptions(shipped: Optional[Path] = None, user: Optional[Path] = None) -> Assumptions:
    shipped = shipped or _shipped()
    user = user or app_dir() / "deposit_matcher.toml"
    merged: dict = {}
    places: Dict[str, List[str]] = {}
    for path in (shipped, user):
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        except tomllib.TOMLDecodeError as exc:
            if path == user:
                raise ConfigError(f"{path} could not be read ({exc}). Fix or delete it.")
            continue
        merged.update(raw.get("assumptions", {}) if isinstance(raw.get("assumptions"), dict) else {})
        for name, hints in (raw.get("places", {}) if isinstance(raw.get("places"), dict) else {}).items():
            if isinstance(hints, list):
                places[str(name)] = [str(h) for h in hints if str(h).strip()]
    a = Assumptions(places=places)
    try:
        if merged.get("over_short_sign", "unknown") not in SIGNS:
            raise ConfigError("over_short_sign must be unknown, positive_is_over or negative_is_over.")
        a.over_short_sign = merged.get("over_short_sign", "unknown")
        a.window_days_before = int(merged.get("window_days_before", 0))
        a.window_days_after = int(merged.get("window_days_after", 3))
        a.near_miss_max = Decimal(str(merged.get("near_miss_max", "5.00")))
        a.max_split_lines = int(merged.get("max_split_lines", 3))
        a.max_days_per_deposit = int(merged.get("max_days_per_deposit", 3))
        a.bank_decimal_comma = bool(merged.get("bank_decimal_comma", False))
    except (ValueError, TypeError, InvalidOperation):
        raise ConfigError("deposit_matcher.toml has a value that is not a number where a number is needed.")
    if not (0 <= a.window_days_before <= 10 and 0 <= a.window_days_after <= 14 and 1 <= a.max_split_lines <= 5
            and 1 <= a.max_days_per_deposit <= 5 and 0 <= a.near_miss_max <= 1000):
        raise ConfigError("deposit_matcher.toml: a window or limit is outside the sensible range.")
    return a


def load_wording(shipped: Optional[Path] = None, user: Optional[Path] = None) -> Dict[str, str]:
    shipped = shipped or Path(__file__).resolve().parent / "data" / "reason_terms.toml"
    user = user or app_dir() / "reason_terms.toml"
    out: Dict[str, str] = dict(_FALLBACK_WORDS)
    for path in (shipped, user):
        try:
            table = tomllib.loads(path.read_text(encoding="utf-8")).get("deposits", {})
        except (OSError, tomllib.TOMLDecodeError):
            continue
        for k, v in (table.items() if isinstance(table, dict) else ()):
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
    return out


_FALLBACK_WORDS = {"matched": "The bank shows {amount} on {date}, the same as the {expected} expected for {day}.",
                   "missing": "No matching bank line was found from {first} to {last}."}


# ------------------------------------------------------------------------------------------ data shapes

@dataclass
class Expected:
    place: str
    day: date
    amount: Optional[Decimal]
    over_short: Optional[Decimal] = None
    number: str = ""
    conflict: bool = False


@dataclass
class BankLine:
    idx: int
    day: date
    amount: Decimal
    text: str
    ref: str = ""
    count: int = 1          # how many identical lines the file holds (a duplicate when > 1)


@dataclass
class Item:
    place: str
    day: date
    expected: Optional[Decimal]
    status: str
    kind: str
    explanation: str
    reasons: List[str] = field(default_factory=list)
    lines: List[int] = field(default_factory=list)
    score: int = 0
    over_short: Optional[Decimal] = None

    @property
    def key(self) -> str:
        return f"{self.place}|{self.day.isoformat()}|{self.expected}|{self.kind}"


@dataclass
class DepositResult:
    items: List[Item]
    lines: Dict[int, BankLine]
    unclaimed: List[int]
    bank_first: Optional[date]
    bank_last: Optional[date]
    notes: List[str] = field(default_factory=list)       # plain things the person should know
    unreadable: List[str] = field(default_factory=list)  # bank lines that could not be read (position only)
    left_out: int = 0                                    # DSS days outside the bank file's dates
    nothing_expected: int = 0                            # DSS days with a zero deposit
    assumptions: List[Tuple[str, str]] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i.status == status)


def money(d: Optional[Decimal]) -> str:
    return "unknown" if d is None else f"${d:,.2f}"


def _day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


# ------------------------------------------------------------------------------------------ reading files

def read_expected(data: bytes, filename: str) -> Tuple[List[Expected], List[str]]:
    """Expected deposits from a DSS list export (CSV, TSV or Excel): one per place and day."""
    rows, stats, _ = read_rows(data, filename)
    aliases = load_aliases()
    for i, row in enumerate(rows[:40]):
        found, _notes = aliases.match(row)
        if all(f in found for f in ("location", "business_date")):
            break
    else:
        raise ExportError("This does not look like an R365 Daily Sales Summary list: no heading row with Location and Date.")
    if "deposit" not in found:
        raise ExportError("This DSS list has no Total Deposit column, so there is nothing to match to the bank.")
    body = [r for r in rows[i + 1:] if any(c.strip() for c in r)]
    cell = lambda r, f: r[found[f]].strip() if f in found and found[f] < len(r) else ""
    order, warn = detect_date_order([cell(r, "business_date") for r in body])
    notes = [warn] if warn else []
    by: Dict[Tuple[str, date], Expected] = {}
    unreadable = 0
    for r in body:
        place = re.sub(r"\s+", " ", cell(r, "location"))
        d = parse_date(cell(r, "business_date"), order)
        if not place or d is None:
            continue
        amt, bad = parse_money(cell(r, "deposit"))
        unreadable += bad
        osv, _ = parse_money(cell(r, "over_short")) if "over_short" in found else (None, False)
        e = Expected(place, d, amt, osv, cell(r, "location_number"))
        old = by.get((place, d))
        if old is None:
            by[(place, d)] = e
        elif old.amount != e.amount:
            old.conflict = True
    if unreadable:
        notes.append(f"{unreadable} DSS deposit amount(s) could not be read (for example a comma used as a decimal mark). "
                     "They are shown as \"cannot tell\"; nothing was guessed.")
    return sorted(by.values(), key=lambda e: (e.place, e.day)), notes


_BANK_FIELDS = {
    "date": ["Date", "Posted", "Posting Date", "Post Date", "Posted Date", "Transaction Date", "Trans Date"],
    "text": ["Description", "Memo", "Details", "Narrative", "Name", "Payee", "Transaction"],
    "amount": ["Amount", "Transaction Amount"],
    "debit": ["Debit", "Withdrawal", "Withdrawals", "Debits"],
    "credit": ["Credit", "Deposit", "Deposits", "Credits"],
    "ref": ["Reference", "Ref", "Reference Number", "FITID", "Check or Slip #", "Id"],
}


def _bank_amount(text: str, a: Assumptions) -> Tuple[Optional[Decimal], bool]:
    """(value, unreadable). With the default assumption this is exactly the DSS comma rule: 1,234.50 reads, 23,50
    does not. Only when the person has said the bank writes cents after a comma is 23,50 read, and then a point
    is accepted only as a thousands mark (1.234,50); a lone point (700.00) is refused rather than guessed."""
    t = (text or "").strip().replace("\u2212", "-")
    if not a.bank_decimal_comma or not t:
        return parse_money(t)
    body = t.lstrip("+-").replace("$", "").replace(" ", "")
    if body.startswith("(") or body.endswith(")") or body.endswith("-"):
        return None, True
    if not re.fullmatch(r"(\d{1,3}(\.\d{3})*|\d+)(,\d{1,2})?", body):
        return None, True
    value = Decimal(body.replace(".", "").replace(",", "."))
    return (-value if t.startswith("-") else value), False


def _read_bank_csv(data: bytes, a: Assumptions, filename: str) -> Tuple[List[BankLine], List[str], int]:
    rows = read_csv_rows(data, None)
    cols: dict = {}
    hdr = None
    for i, row in enumerate(rows[:40]):
        normed = [norm(c) for c in row]
        found = {}
        for f, words in _BANK_FIELDS.items():
            for w in words:
                if norm(w) in normed:
                    found[f] = normed.index(norm(w))
                    break
        if "date" in found and ("amount" in found or "credit" in found):
            hdr, cols = i, found
            break
    if hdr is None:
        raise ExportError("This does not look like a bank export: no heading row with a date and an amount "
                          "(or Debit/Credit) column was found.")
    body = [r for r in rows[hdr + 1:] if any(c.strip() for c in r)]
    cell = lambda r, f: r[cols[f]].strip() if f in cols and cols[f] < len(r) else ""
    order, _warn = detect_date_order([cell(r, "date") for r in body])
    lines, bad, ignored = [], [], 0
    for n, r in enumerate(body, start=hdr + 2):
        d = parse_date(cell(r, "date"), order)
        if "amount" in cols:
            amt, unread = _bank_amount(cell(r, "amount"), a)
        else:
            amt, unread = _bank_amount(cell(r, "credit"), a)
        if d is None or unread or (amt is None and "amount" in cols):
            bad.append(f"line {n}: " + ("the date" if d is None else "the amount") + " could not be read, so it was left out")
            continue
        if amt is None or amt <= 0:
            ignored += 1
            continue
        lines.append(BankLine(0, d, amt, re.sub(r"\s+", " ", cell(r, "text")), cell(r, "ref")))
    return lines, bad, ignored


def _ofx_tag(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}>([^<\r\n]*)", block, re.I)
    return unescape(m.group(1).strip()) if m else ""


def _read_bank_ofx(data: bytes, a: Assumptions) -> Tuple[List[BankLine], List[str], int]:
    text = data.decode("utf-8", "replace")
    lines, bad, ignored = [], [], 0
    blocks = re.split(r"<STMTTRN>", text, flags=re.I)[1:]
    for n, block in enumerate(blocks, start=1):
        block = re.split(r"</STMTTRN>|</BANKTRANLIST>", block, flags=re.I)[0]
        raw_date = re.match(r"(\d{4})(\d{2})(\d{2})", _ofx_tag(block, "DTPOSTED"))
        try:
            d = date(int(raw_date.group(1)), int(raw_date.group(2)), int(raw_date.group(3)))
        except (AttributeError, ValueError):
            bad.append(f"entry {n}: the date could not be read, so it was left out")
            continue
        amt, unread = parse_money(_ofx_tag(block, "TRNAMT"))      # a comma is never guessed here either
        if unread or amt is None:
            bad.append(f"entry {n}: the amount could not be read, so it was left out")
            continue
        if amt <= 0:
            ignored += 1
            continue
        name = " ".join(x for x in (_ofx_tag(block, "NAME"), _ofx_tag(block, "MEMO")) if x)
        lines.append(BankLine(0, d, amt, re.sub(r"\s+", " ", name), _ofx_tag(block, "FITID")))
    if not blocks:
        raise ExportError("This OFX file holds no transactions.")
    return lines, bad, ignored


def read_bank(data: bytes, filename: str, a: Assumptions) -> Tuple[List[BankLine], List[str], List[str]]:
    """(lines, unreadable-line notes, plain notes). Only money coming in is kept."""
    if len(data) > MAX_FILE_BYTES:
        raise ExportError("This bank file is too large to be a normal statement.")
    ext = Path(filename).suffix.lower()
    if ext not in BANK_EXTENSIONS:
        raise ExportError("The bank file must be a .csv, .ofx or .qfx file.")
    is_ofx = ext in (".ofx", ".qfx") or b"<OFX" in data[:2000].upper()
    lines, bad, ignored = _read_bank_ofx(data, a) if is_ofx else _read_bank_csv(data, a, filename)
    notes = [f"{ignored} money-out or zero line(s) in the bank file were ignored."] if ignored else []
    # identical lines (same day, amount, text and no distinguishing reference) are one entry seen several times
    folded: Dict[tuple, BankLine] = {}
    for ln in lines:
        k = (ln.day, ln.amount, ln.text.lower(), ln.ref)
        if k in folded:
            folded[k].count += 1
        else:
            folded[k] = ln
    out = sorted(folded.values(), key=lambda l: (l.day, l.amount, l.text))
    for i, ln in enumerate(out):
        ln.idx = i
    return out, bad, notes


# ------------------------------------------------------------------------------------------ matching

def _hint_places(lines: List[BankLine], expected: List[Expected], a: Assumptions) -> Dict[int, set]:
    """Which places the bank text names (by place name, place number or a hint from the config)."""
    hints: Dict[str, List[str]] = {}
    for e in expected:
        h = hints.setdefault(e.place, [e.place.lower()])
        if e.number and e.number not in h:
            h.append(e.number)
    for name, extra in a.places.items():
        hints.setdefault(name, [name.lower()]).extend(x.lower() for x in extra)
    out: Dict[int, set] = {}
    for ln in lines:
        text, hit = ln.text.lower(), set()
        for place, words in hints.items():
            for w in words:
                if (re.search(rf"(?<![0-9a-z]){re.escape(w)}(?![0-9a-z])", text) if w.isdigit() else w in text):
                    hit.add(place)
                    break
        out[ln.idx] = hit
    return out


def _same_digits(x: Decimal, y: Decimal) -> bool:
    sx, sy = f"{x:.2f}".replace(".", ""), f"{y:.2f}".replace(".", "")
    return x != y and sorted(sx) == sorted(sy) and len(sx) == len(sy)


def match(expected: List[Expected], lines: List[BankLine], a: Optional[Assumptions] = None,
          wording: Optional[Dict[str, str]] = None, notes: Optional[List[str]] = None) -> DepositResult:
    a = a or load_assumptions()
    words = wording or load_wording()
    by_idx = {l.idx: l for l in lines}
    first = min((l.day for l in lines), default=None)
    last = max((l.day for l in lines), default=None)
    res = DepositResult([], by_idx, [], first, last, list(notes or []), assumptions=a.lines())
    if not lines:
        res.notes.append("The bank file has no money-in lines, so every expected deposit is shown as \"cannot tell\".")
    names = _hint_places(lines, expected, a)
    used: set = set()                        # bank lines already given to a place

    def say(kind: str, **v) -> str:
        v.setdefault("n", "")
        try:
            return words.get(kind, _FALLBACK_WORDS.get(kind, kind)).format(**v)
        except (KeyError, IndexError, ValueError):
            return _FALLBACK_WORDS.get("matched", kind)

    def window(e_day: date) -> Tuple[date, date]:
        return e_day - timedelta(days=a.window_days_before), e_day + timedelta(days=a.window_days_after)

    def free(e: Expected, lo: date, hi: date) -> List[BankLine]:
        return [l for l in lines if l.idx not in used and lo <= l.day <= hi
                and (not names[l.idx] or e.place in names[l.idx])]

    def lines_text(ls: List[BankLine]) -> str:
        return "; ".join(f"{money(l.amount)} on {_day(l.day)}" for l in ls)

    def os_text(e: Expected, diff: Decimal) -> str:
        if e.over_short is None or abs(e.over_short) != abs(diff) or diff == 0:
            return ""
        if a.over_short_sign == "unknown":
            return (" " + say("over_short_link", os=f"{e.over_short:+.2f}") + " " + say("over_short_unknown_sign")).rstrip()
        over = (e.over_short > 0) == (a.over_short_sign == "positive_is_over")
        return " " + say("over_short_link", os=f"{abs(e.over_short):.2f} {'over' if over else 'short'}")

    def add(e: Expected, status: str, kind: str, text: str, reasons=(), ls=(), score=0):
        res.items.append(Item(e.place, e.day, e.amount, status, kind, text, list(reasons), [l.idx for l in ls], score, e.over_short))
        used.update(l.idx for l in ls)

    todo: List[Expected] = []
    for e in expected:
        lo, hi = window(e.day)
        if last is not None and e.day > last or first is not None and hi < first:
            res.left_out += 1
            continue
        if e.conflict:
            add(e, UNKNOWN, "conflict", say("conflict", day=_day(e.day)), ["The DSS list holds two different deposit amounts for this day."])
        elif e.amount is None or e.amount < 0:
            add(e, UNKNOWN, "no_amount", say("no_amount", day=_day(e.day)), ["The deposit amount is blank or could not be read."])
        elif e.amount == 0:
            res.nothing_expected += 1
        else:
            todo.append(e)

    # ---- A. exact amounts. Each expected deposit and each line must pair up one to one, else nothing is matched.
    edges: Dict[int, List[BankLine]] = {}
    for n, e in enumerate(todo):
        lo, hi = window(e.day)
        ex = [l for l in free(e, lo, hi) if l.amount == e.amount]
        named = [l for l in ex if e.place in names[l.idx]]
        edges[n] = named or ex
    line_users: Dict[int, List[int]] = {}
    for n, ls in edges.items():
        for l in ls:
            line_users.setdefault(l.idx, []).append(n)
    resolved: set = set()
    for n, e in enumerate(todo):
        ls = edges[n]
        if not ls:
            continue
        shared = any(len(line_users[l.idx]) > 1 for l in ls)
        if len(ls) == 1 and not shared:
            l = ls[0]
            if l.count > 1:
                add(e, LOOK, "duplicate", say("duplicate", amount=money(l.amount), date=_day(l.day), n=l.count),
                    [f"+60 The amount equals the DSS deposit, but the bank file holds this line {l.count} times."], [l], 40)
            else:
                named = e.place in names[l.idx]
                gap = (l.day - e.day).days
                reasons = [f"+60 The amount equals the DSS deposit exactly ({money(l.amount)}).",
                           f"+25 It posted {'the same day' if gap == 0 else f'{gap} day(s) after'} the business day, inside the {a.window_days_before}-{a.window_days_after} day window.",
                           "+15 The bank text names the place." if named else
                           "+0 The bank text does not name the place; matched on amount and date alone, and no other place expects this amount."]
                weekend = e.day.weekday() >= 4 and l.day.weekday() == 0 and gap > 0
                if weekend:
                    reasons.append("Note: a Friday-to-Sunday business day usually reaches the bank on Monday.")
                text = say("matched_weekend" if weekend else "matched", amount=money(l.amount), date=_day(l.day),
                           expected=money(e.amount), day=_day(e.day))
                text += " " + say("name_found" if named else "name_missing")
                add(e, MATCHED, "exact", text, reasons, [l], 100 if named else 85)
            resolved.add(n)
        else:
            amt = ls[0].amount
            add(e, LOOK, "ambiguous", say("ambiguous", amount=money(amt)),
                ["The amount is the same on more than one place/day or more than one bank line, and the bank text does not say which."],
                [], 20)
            resolved.add(n)
            used.update(l.idx for l in ls)

    rest = [e for n, e in enumerate(todo) if n not in resolved]

    # ---- B. one bank line that covers two or three consecutive days of one place (weekend deposits included)
    by_place: Dict[str, List[Expected]] = {}
    for e in rest:
        by_place.setdefault(e.place, []).append(e)
    for place, es in by_place.items():
        es.sort(key=lambda x: x.day)
        for size in range(a.max_days_per_deposit, 1, -1):
            for i in range(len(es) - size + 1):
                grp = es[i:i + size]
                if any(g.day != grp[0].day + timedelta(days=k) for k, g in enumerate(grp)):
                    continue                                  # must be consecutive calendar days
                if any(any((it.place, it.day) == (g.place, g.day) for it in res.items) for g in grp):
                    continue
                total = sum((g.amount for g in grp), Decimal(0))
                lo, hi = window(grp[0].day)
                hi = grp[-1].day + timedelta(days=a.window_days_after)
                hit = [l for l in free(grp[0], lo, hi) if l.amount == total]
                if len(hit) != 1:
                    continue
                l = hit[0]
                weekend = any(g.day.weekday() >= 5 for g in grp) or (grp[0].day.weekday() == 4 and size > 1)
                days = " and ".join(_day(g.day) for g in grp) if size == 2 else ", ".join(_day(g.day) for g in grp)
                for g in grp:
                    text = say("two_days_weekend" if weekend else "two_days", amount=money(l.amount), date=_day(l.day),
                               days=days, expected=money(g.amount), day=_day(g.day))
                    add(g, LOOK, "two_days", text,
                        [f"+60 The line equals the {size} days' DSS deposits added together ({money(total)}).",
                         "+0 No single day matches by itself, so this is not matched on its own." ],
                        [l], 55)
    rest = [e for e in rest if not any((it.place, it.day) == (e.place, e.day) for it in res.items)]

    # ---- C. one day paid in two or three bank lines
    for e in list(rest):
        lo, hi = window(e.day)
        pool = free(e, lo, hi)
        subsets = [c for k in range(2, a.max_split_lines + 1) for c in itertools.combinations(pool, k)
                   if sum((l.amount for l in c), Decimal(0)) == e.amount and all(l.count == 1 for l in c)]
        named = [c for c in subsets if all(e.place in names[l.idx] for l in c)]
        subsets = named or subsets
        if len(subsets) == 1:
            c = list(subsets[0])
            add(e, LOOK, "split", say("split", expected=money(e.amount), day=_day(e.day), n=len(c), lines=lines_text(c)),
                [f"+60 {len(c)} lines add up to exactly {money(e.amount)}.", "+0 No single line equals it, so this is not matched on its own."], c, 55)
            rest.remove(e)
        elif len(subsets) > 1:
            add(e, UNKNOWN, "ambiguous", say("ambiguous", amount=money(e.amount)),
                [f"More than one set of bank lines adds up to {money(e.amount)}; the bank text does not say which."], [], 15)
            rest.remove(e)

    # ---- D. a near miss (small difference or swapped digits). Shown, never matched.
    for e in list(rest):
        lo, hi = window(e.day)
        pool = free(e, lo, hi)
        close = [l for l in pool if abs(l.amount - e.amount) <= a.near_miss_max or _same_digits(l.amount, e.amount)]
        if len(close) == 1:
            l = close[0]
            diff = l.amount - e.amount
            typo = _same_digits(l.amount, e.amount)
            text = say("typo" if typo else "near_miss", amount=money(l.amount), date=_day(l.day), expected=money(e.amount),
                       day=_day(e.day), diff=money(abs(diff)))
            text += os_text(e, diff)
            reasons = [f"The bank line is {money(abs(diff))} {'above' if diff > 0 else 'below'} the DSS deposit."]
            if typo:
                reasons.append("The digits are the same but in a different order.")
            add(e, LOOK, "typo" if typo else "near_miss", text, reasons, [l], 35)
            rest.remove(e)
        elif len(close) > 1:
            add(e, UNKNOWN, "several_close", say("several_close", n=len(close), expected=money(e.amount), day=_day(e.day),
                                                  lines=lines_text(close)),
                ["More than one bank line is close; nothing says which one is meant."], [], 10)
            rest.remove(e)

    # ---- E. nothing found
    for e in rest:
        lo, hi = window(e.day)
        pool = free(e, lo, hi)
        if last is not None and hi > last:
            add(e, UNKNOWN, "bank_ends", say("bank_ends", last=_day(last), day=_day(e.day)),
                ["The bank file stops before the deposit window closes."])
        elif [l for l in pool if e.place in names[l.idx]]:
            pool = [l for l in pool if e.place in names[l.idx]]
            add(e, LOOK, "no_match", say("no_match", n=len(pool), first=_day(lo), last=_day(hi), expected=money(e.amount), day=_day(e.day)),
                ["Other bank lines exist in the window, but none match."])
        else:
            add(e, LOOK, "missing", say("missing", expected=money(e.amount), first=_day(lo), last=_day(hi)),
                ["No bank line in the window."])

    res.items.sort(key=lambda i: ({LOOK: 0, UNKNOWN: 1, MATCHED: 2}[i.status], i.place, i.day))
    res.unclaimed = [l.idx for l in lines if l.idx not in used and
                     (not res.items or any(it.day - timedelta(days=a.window_days_before) <= l.day <= it.day + timedelta(days=a.window_days_after) for it in res.items))]
    repeated = sum(1 for l in lines if l.count > 1)
    if repeated:
        res.notes.append(f"{repeated} bank line(s) appear more than once in the file; they are never counted twice.")
    if res.left_out:
        res.notes.append(f"{res.left_out} DSS day(s) fall outside the dates the bank file covers and were left out.")
    return res


# ------------------------------------------------------------------------------------------ saving and notes

def result_to_json(res: DepositResult) -> dict:
    def enc(o):
        if isinstance(o, (date,)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return str(o)
        raise TypeError
    import json
    return json.loads(json.dumps(asdict(res), default=enc))


def result_from_json(raw: dict) -> DepositResult:
    d = lambda s: date.fromisoformat(s) if s else None
    dec = lambda s: Decimal(s) if s is not None else None
    items = [Item(i["place"], d(i["day"]), dec(i["expected"]), i["status"], i["kind"], i["explanation"], i["reasons"],
                  i["lines"], i["score"], dec(i.get("over_short"))) for i in raw["items"]]
    lines = {int(k): BankLine(v["idx"], d(v["day"]), dec(v["amount"]), v["text"], v.get("ref", ""), v.get("count", 1))
             for k, v in raw["lines"].items()}
    return DepositResult(items, lines, raw["unclaimed"], d(raw["bank_first"]), d(raw["bank_last"]), raw["notes"],
                         raw["unreadable"], raw.get("left_out", 0), raw.get("nothing_expected", 0),
                         [tuple(x) for x in raw.get("assumptions", [])])


def summary_line(res: DepositResult) -> str:
    return (f"Deposits: {res.count(MATCHED)} matched, {res.count(LOOK)} need a look, {res.count(UNKNOWN)} cannot be told"
            + (f"; {len(res.unclaimed)} bank line(s) belong to no place" if res.unclaimed else "") + ".")


def draft_note(item: Item, res: DepositResult, manager: str = "") -> Tuple[str, str]:
    """(subject, body) of a follow-up note for a person to read, change and send themselves. Text only."""
    subject = f"Deposit check: {item.place}, {_day(item.day)}"
    lines = [res.lines[i] for i in item.lines if i in res.lines]
    body = [f"Hi{(' ' + manager) if manager else ''},", "",
            f"I was checking the bank deposits against the Daily Sales Summary for {item.place} on {_day(item.day)}.",
            f"The DSS expects a deposit of {money(item.expected)}.", ""]
    if lines:
        body.append("Bank line(s) I looked at: " + "; ".join(f"{money(l.amount)} on {_day(l.day)}" for l in lines) + ".")
    body += [item.explanation, "",
             "Could you confirm what was deposited and when, or send the deposit slip? I have not changed anything.", "",
             "Thanks"]
    return subject, "\n".join(body)
