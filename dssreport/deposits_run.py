"""Running the deposit matcher without clicks, and keeping its result and the person's answers.

Everything lives in the program's own folder (%LOCALAPPDATA%\\DssReport\\deposits): the latest result, a small
memory of which bank file was already checked, and the person's marks (Looks right / Flag). It reads the
files it is pointed at and never changes them. Nothing here sends anything.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from . import deposits as D
from .dss_export import ExportError
from .errors import DssError, InputError
from .paths import app_dir

REVIEW_MARKS = ("ok", "flag")


def deposits_dir() -> Path:
    return app_dir() / "deposits"


def _json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def newest_file(location: str, extensions: Tuple[str, ...]) -> Path:
    """A file, or the newest matching file in a folder. Plain-words error when there is nothing to read."""
    if not location.strip() or "\0" in location:
        raise InputError("No location is set.")
    p = Path(location.strip().strip('"'))
    if p.is_file():
        return p
    if p.is_dir():
        found = sorted((f for f in p.iterdir() if f.is_file() and f.suffix.lower() in extensions),
                       key=lambda f: (f.stat().st_mtime, f.name), reverse=True)
        if found:
            return found[0]
        raise InputError(f"There is no {'/'.join(extensions)} file in the folder {p} yet.")
    raise InputError(f"{p} was not found.")


def default_dss_file() -> Optional[Path]:
    """The DSS list the program already keeps for the first DSS-export connection, if there is one."""
    try:
        from . import dss_export_source as X
        from .settings import load_settings
        for inst in load_settings().enabled_instances:
            meta = X.stored_info(inst.id) if inst.source_kind == X.KIND else None
            if meta:
                return X.export_dir(inst.id) / meta["stored_as"]
    except DssError:
        return None
    return None


@dataclass
class Checked:
    result: D.DepositResult
    bank_name: str
    dss_name: str
    at: str
    fingerprint: str


def check_files(bank_bytes: bytes, bank_name: str, dss_bytes: bytes, dss_name: str,
                now: Optional[datetime] = None) -> Checked:
    """Match, then keep the result as the latest one."""
    now = now or datetime.now()
    a = D.load_assumptions()
    expected, notes = D.read_expected(dss_bytes, dss_name)
    lines, bad, bank_notes = D.read_bank(bank_bytes, bank_name, a)
    res = D.match(expected, lines, a, notes=notes + bank_notes)
    res.unreadable = bad
    if bad:
        res.notes.append(f"{len(bad)} bank line(s) could not be read and were left out (listed below). Nothing was guessed.")
    fp = hashlib.sha256(bank_bytes + b"|" + dss_bytes).hexdigest()
    chk = Checked(res, Path(bank_name).name, Path(dss_name).name, now.isoformat(timespec="minutes"), fp)
    _write(deposits_dir() / "latest.json", {"bank": chk.bank_name, "dss": chk.dss_name, "at": chk.at, "fingerprint": fp,
                                            "result": D.result_to_json(res)})
    (deposits_dir() / "latest-summary.txt").write_text(summary_text(chk), encoding="utf-8")
    return chk


def load_latest() -> Optional[Checked]:
    raw = _json(deposits_dir() / "latest.json")
    try:
        return Checked(D.result_from_json(raw["result"]), raw["bank"], raw["dss"], raw["at"], raw["fingerprint"])
    except (KeyError, ValueError, TypeError):
        return None


def summary_text(chk: Checked) -> str:
    r = chk.result
    out = [D.summary_line(r), f"Bank file: {chk.bank_name}. DSS list: {chk.dss_name}. Checked {chk.at}.", ""]
    for status, title in ((D.LOOK, "Needs a look"), (D.UNKNOWN, "Cannot tell"), (D.MATCHED, "Matched")):
        rows = [i for i in r.items if i.status == status]
        if rows:
            out.append(title + ":")
            out += [f"  {i.place}, {D._day(i.day)}, {D.money(i.expected)}: {i.explanation}" for i in rows]
            out.append("")
    out.append("Nothing was changed and nothing was sent.")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------------ the person's marks

def reviews() -> dict:
    return _json(deposits_dir() / "reviews.json")


def mark(key: str, value: str, now: Optional[datetime] = None) -> None:
    if value not in REVIEW_MARKS and value != "clear":
        raise InputError("Unknown mark.")
    data = reviews()
    if value == "clear":
        data.pop(key, None)
    else:
        data[key] = {"mark": value, "at": (now or datetime.now()).isoformat(timespec="minutes")}
    _write(deposits_dir() / "reviews.json", data)


# ------------------------------------------------------------------------------------------ the automatic step

def run_watched(bank_location: str, dss_location: str = "", force: bool = False, settle_seconds: float = 0,
                now: Optional[datetime] = None) -> str:
    """What the daily schedule calls. If a NEW bank file is waiting in the watched place, match it and save the
    result; otherwise do nothing. Returns one plain sentence. Raises DssError for a problem the person must fix."""
    if not (bank_location or "").strip():
        return "The deposit matcher has no bank file or folder set, so it did nothing."
    bank = newest_file(bank_location, D.BANK_EXTENSIONS)
    if settle_seconds and time.time() - bank.stat().st_mtime < settle_seconds:
        return f"{bank.name} was changed a moment ago, so it will be checked on the next run."
    dss = newest_file(dss_location, (".csv", ".tsv", ".txt", ".xlsx")) if (dss_location or "").strip() else default_dss_file()
    if dss is None:
        raise InputError("The deposit matcher needs the DSS list. Set where it is in settings.")
    bank_bytes, dss_bytes = bank.read_bytes(), dss.read_bytes()
    fp = hashlib.sha256(bank_bytes + b"|" + dss_bytes).hexdigest()
    state_path = deposits_dir() / "state.json"
    state = _json(state_path)
    if not force and state.get("last_fingerprint") == fp:
        return f"No new bank file: {bank.name} was already checked."
    try:
        chk = check_files(bank_bytes, bank.name, dss_bytes, dss.name, now)
    except ExportError as exc:
        state["last_error"] = f"{bank.name}: {exc}"
        _write(state_path, state)
        raise
    state.update(last_fingerprint=fp, last_checked=chk.at, last_bank=bank.name)
    state.pop("last_error", None)
    _write(state_path, state)
    return D.summary_line(chk.result)


def last_error() -> str:
    return _json(deposits_dir() / "state.json").get("last_error", "")


def scheduled_step(bank_location: str, dss_location: str, log, now: Optional[datetime] = None,
                   settle_seconds: float = 5) -> str:
    """The deposit step of the daily schedule. Never raises (a problem here must not stop the report); the
    outcome is written to the run log and returned as one sentence."""
    if not (bank_location or "").strip():
        return ""
    try:
        msg = run_watched(bank_location, dss_location, settle_seconds=settle_seconds, now=now)
    except DssError as exc:
        msg = f"The deposit matcher could not run: {exc}"
    except OSError as exc:
        msg = f"The deposit matcher could not read a file: {exc.strerror or 'file problem'}."
    log("deposits: " + msg, now)
    return msg
