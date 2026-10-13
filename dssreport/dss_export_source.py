"""The data source "R365 DSS export (file)": reads the Daily Sales Summary list a person downloaded from R365.

Why it exists: R365's OData connector does not expose DSS approval status or cash over/short at all, so
the two checks this program exists for can only run from the DSS list export. The person downloads the file
(read-only for R365: nothing there is changed), chooses it in settings, and this source reads a COPY the
program keeps in its own folder. Nothing leaves the computer: no network, no credentials, no browser automation.
"""

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from .dss_export import (ExportError, FIELD_WORDS, MAX_FILE_BYTES, ParsedExport, SheetStats, load_aliases,
                         parse_export, read_rows)
from .errors import InputError
from .model import DayRecord
from .paths import app_dir
from .settings import Instance
from .sources import DataSource, register_source

KIND = "dss-export"
SOURCE_WORDS = "DSS export file"
NOT_IN_EXPORT = ("These checks could not run because the DSS export file does not contain what they need "
                 "(it has no POS import, missing-receipt or payment-exception columns).")


def export_dir(instance_id: str) -> Path:
    return app_dir() / "exports" / instance_id


def _meta_path(instance_id: str) -> Path:
    return export_dir(instance_id) / "meta.json"


def safe_name(filename: str) -> str:
    """Just the file's own name: no folders, no odd characters (it is shown on screen)."""
    name = Path((filename or "").replace("\\", "/")).name
    name = "".join(ch if (ch.isalnum() or ch in " ._-()") else "_" for ch in name).strip(" .")
    return name[:120] or "export"


def clean_expected_total(value) -> Optional[int]:
    """The optional total the person read off R365's screen ("... of N items"). Anything else is ignored."""
    try:
        n = int(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 10_000_000 else None


def store_export(instance: Instance, filename: str, data: bytes, file_mtime: Optional[float] = None,
                 now: Optional[datetime] = None, today: Optional[date] = None,
                 expected_total: Optional[int] = None) -> dict:
    """Keep a COPY of the chosen file in the program's own folder, after proving it can be read. The file the
    person chose is never opened for writing and never changed. Raises ExportError (plain words) and keeps
    any earlier copy untouched if this one is no good."""
    name = safe_name(filename)
    rows, stats, kind = read_rows(data, name)              # refuses non-tables, oversize files, macros ...
    expected_total = clean_expected_total(expected_total)
    parsed = parse_export(rows, load_aliases(), instance.approval_words, _as_of(file_mtime), today, stats, expected_total)
    now = now or datetime.now()
    d = export_dir(instance.id)
    d.mkdir(parents=True, exist_ok=True)
    ext = Path(name).suffix.lower() if Path(name).suffix.lower() in (".csv", ".tsv", ".xlsx", ".txt") else ".csv"
    final = d / f"current{ext}"
    part = d / f"current{ext}.part"
    part.write_bytes(data)
    for old in d.glob("current.*"):
        if old.name != final.name and not old.name.endswith(".part"):
            old.unlink()
    os.replace(part, final)
    meta = {"original_name": name, "stored_as": final.name, "received_at": now.isoformat(timespec="seconds"),
            "file_mtime": (_as_of(file_mtime).isoformat(timespec="seconds") if file_mtime else None),
            "rows": parsed.rows_read, "size": len(data), "kind": kind, "expected_total": expected_total}
    _meta_path(instance.id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _as_of(file_mtime: Optional[float]) -> Optional[datetime]:
    if not file_mtime:
        return None
    try:
        return datetime.fromtimestamp(float(file_mtime))
    except (OverflowError, OSError, ValueError):
        return None


def stored_info(instance_id: str) -> Optional[dict]:
    try:
        meta = json.loads(_meta_path(instance_id).read_text(encoding="utf-8"))
        return meta if (export_dir(instance_id) / meta["stored_as"]).exists() else None
    except (OSError, ValueError, KeyError):
        return None


@register_source
class DssExportSource(DataSource):
    """Reads the stored copy of the DSS list export for ONE connection."""

    kind = KIND
    name = "R365 DSS export (file)"
    needs_credentials = False
    mapping_formats = frozenset({1})

    def __init__(self, instance: Instance, store=None, include=(), today: Optional[date] = None,
                 now: Optional[datetime] = None, aliases=None):
        super().__init__(instance, store, include)
        self.today = today or date.today()
        self.now = now
        self.aliases = aliases
        self.parsed: Optional[ParsedExport] = None
        self.source_line = ""
        self.source_warnings: List[str] = []
        self.unmapped_text = NOT_IN_EXPORT
        self.unmapped = {"missing_receipts", "payment_exceptions", "pos_import_received", "payments"}

    def set_window(self, start: date, end: date) -> None:
        self.window = (start, end)

    def _read(self) -> ParsedExport:
        meta = stored_info(self.instance.id)
        if meta is None:
            raise InputError("No DSS export file has been chosen for this connection yet. Open settings, go to "
                             "\"Check a DSS export\" and choose the file you downloaded from R365.")
        path = export_dir(self.instance.id) / meta["stored_as"]
        try:
            data = path.read_bytes()
        except OSError:
            raise InputError("The saved copy of the DSS export file could not be read. Choose the file again.")
        rows, stats, _ = read_rows(data, meta["stored_as"])
        as_of = datetime.fromisoformat(meta["file_mtime"]) if meta.get("file_mtime") else None
        parsed = parse_export(rows, self.aliases or load_aliases(), self.instance.approval_words, as_of,
                              self.today, stats, clean_expected_total(meta.get("expected_total")))
        read_at = self.now or datetime.now()
        dated = f"dated {as_of:%Y-%m-%d %H:%M}" if as_of else "date not known"
        self.source_line = (f'Source: {SOURCE_WORDS} "{meta["original_name"]}", {dated}, '
                            f"read {read_at:%Y-%m-%d %H:%M}.")
        self.source_warnings = list(parsed.warnings)
        self.unmapped = set(parsed.unmapped)
        self.name = f"R365 DSS export (file): {self.instance.name}"
        return parsed

    def load(self) -> List[DayRecord]:
        self.parsed = self._read()
        wanted = set(self.include)
        return [r for r in self.parsed.records if not wanted or r.location in wanted]

    def check_connection(self) -> str:
        p = self._read()
        cols = ", ".join(FIELD_WORDS[f] for f in p.columns) or "none"
        span = (f" Days in the file: {p.first_date.isoformat()} to {p.last_date.isoformat()}."
                if p.first_date else "")
        return f"Read {p.rows_read} rows. Columns recognised: {cols}.{span}"

    def describe(self) -> List[str]:
        p = self._read()
        lines = [f"{FIELD_WORDS[f]}  <-  \"{h}\"" for f, h in p.columns.items()]
        lines += [f"{FIELD_WORDS[f]}  <-  (no column)" for f in p.missing]
        lines += [f"not recognised, ignored: \"{h}\"" for h in p.unrecognised]
        return lines
