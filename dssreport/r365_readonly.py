"""Read-only Restaurant365 connector that uses ONLY field names from R365's public documentation.

Public documentation this connector is based on (cited, not copied):
  * OData connector:  https://docs.restaurant365.com/docs/restaurant365-odata-connector
  * R365 API connector: https://docs.restaurant365.com/docs/r365-api-connector

IMPORTANT: when this module was written the build session could not open those pages, so no
entity or field name is confirmed yet. The table of names lives in
`data/r365_documented_fields.toml` and ships with every entry empty. An empty entry is UNKNOWN:
the value comes back as None, the matching check shows "needs mapping", and the gap is listed in
docs/R365_FIELD_GAPS.md. Names are never guessed, and a user's own mapping file is never read here
(use the separate "odata" connector for that).

Read-only: every request goes through `ODataClient` (r365.py), which can send GET and nothing else,
refuses redirects and only ever talks to the address the user configured. No approval, posting or
other write call exists anywhere in this module.

Same interface as the other sources (`DataSource`), so it is switched on by a settings value:
the connection's `source_kind` = "r365-readonly".
"""

import tomllib
from pathlib import Path
from typing import List, Optional

from .errors import ConfigError
from .model import DayRecord
from .r365 import FIELD_KEYS, Mapping, ODataSource
from .sources import DataSource, register_source

DOC_URLS = (
    "https://docs.restaurant365.com/docs/restaurant365-odata-connector",
    "https://docs.restaurant365.com/docs/r365-api-connector",
)
DOCUMENTED_FIELDS_FILE = Path(__file__).parent / "data" / "r365_documented_fields.toml"
UNKNOWN = "UNKNOWN"


def load_documented_fields(path=None) -> Mapping:
    path = Path(path) if path else DOCUMENTED_FIELDS_FILE
    try:
        return Mapping(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"The documented-fields table {path.name} could not be read ({exc}).")


def unknown_fields(mapping: Mapping) -> List[str]:
    """Every item the documentation has not confirmed (these are the rows of docs/R365_FIELD_GAPS.md)."""
    out = [k for k in ("entity", "location", "business_date") if not getattr(mapping, k)]
    out += [k for k in FIELD_KEYS if not mapping.fields[k]]
    if not mapping.payments:
        out.append("payments")
    return out


@register_source
class R365ReadOnlySource(DataSource):
    kind = "r365-readonly"
    name = "Restaurant365 (read-only, documented fields)"

    def __init__(self, instance, store, include=(), documented: Optional[Mapping] = None):
        super().__init__(instance, store, include)
        self.name = f"Restaurant365: {instance.name}"
        self.documented = documented if documented is not None else load_documented_fields()
        self._inner = ODataSource(instance, store, include=include, mapping=self.documented)
        self.unmapped = self._inner.unmapped
        self.unmapped_notes = self._inner.unmapped_notes
        self.warnings = self._inner.warnings
        self.unknown = unknown_fields(self.documented)
        if self.unknown:
            self.unmapped_notes.append(
                f"{UNKNOWN}: R365's public documentation does not confirm: {', '.join(self.unknown)} "
                "(see docs/R365_FIELD_GAPS.md).")

    def set_window(self, start, end) -> None:
        self._inner.set_window(start, end)

    def load(self) -> List[DayRecord]:
        return self._inner.load()

    def check_connection(self) -> str:
        return self._inner.check_connection()

    def describe(self) -> List[str]:
        return self._inner.describe()
