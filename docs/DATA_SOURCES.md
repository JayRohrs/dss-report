# Data sources: swapping the R365 connector

R365 is changing its API. This program keeps all R365 data access behind **one interface** (`DataSource` in `dssreport/sources.py`) so the current OData connector can be replaced by a connector for the new API **without touching the rules, the report, the email or the settings screen**.

Status: two sources exist. **Neither is a connector for R365's new API; none of that API's details are guessed here.** This document describes the seam, not the new API.

| `kind` | Module | What it is | Status |
|---|---|---|---|
| `dss-export` | `dss_export_source.py`, `dss_export.py` | Reads the DSS list **export file** the person downloaded from R365 (CSV, TSV, Excel). The recommended source: it carries approval status and cash over/short. No network, no credentials. | Built; tested with made-up files only. See `docs/EXPORT_SOURCE.md`. |
| `odata` | `r365.py` | The OData connector. **Optional: does not provide approval or over/short; unproven against a live tenant.** | Built; tested against a mock only. |

The owner's testing found that OData does not expose DSS approval status or cash over/short at all (see `docs/R365_OPEN_QUESTIONS.md`), which is why the file source exists. It plugs in through exactly this interface, with no change to the rules, report, email, schedule or licence logic beyond what the file's own statements need.

### How a source that reads a file uses the same seam

- `needs_credentials = False` tells the runner not to open the credential store for it (it may be given `store=None`).
- The person's file is stored as a copy under the program's own folder; `load()` reads that copy. A connection with no file yet raises a plain `InputError` ("No DSS export file has been chosen...") shown as "could not read its data".
- A source may describe itself to the report with three optional attributes: `source_line` ("Source: DSS export file ..., dated ..., read ..."), `source_warnings` (plain statements such as "Partial list" or "This file has no Over/Short column") and `unmapped_text` (why some checks could not run). The runner copies them into the report; the report and email show them under the headline.
- `DayRecord` gained two optional fields for sources that know *why* something is unknown: `approval_note` (a status word that is not treated as approved/not approved, a file that is too old...) and `conflicts` (fields on which several source rows for one day disagreed). The rules turn them into UNKNOWN findings; they never turn them into a yes or no.

## What talks to what

```
rules, report, email, schedule, settings screen
            │  (only this)
            ▼
   DataSource  ──  one per R365 connection ("instance")
            ▲
   ODataSource  (today)        NewApiSource  (later, not built)
```

`runner.py` reads the list of connections from settings, asks `build_source(instance, store)` for the right connector for each (by the instance's `source_kind`), calls `set_window`, `load`, and builds one report section per connection. Nothing else knows what kind of source it is.

## The interface

```python
class DataSource(Adapter):
    kind: str                        # the name saved in settings, e.g. "odata"
    mapping_formats: frozenset[int]  # mapping-file versions this connector reads
    needs_window = True

    def __init__(self, instance, store, include=()): ...

    def set_window(self, start: date, end: date) -> None
    def load(self) -> list[DayRecord]
    unmapped: set[str]               # DayRecord fields this source cannot provide at all
    unmapped_notes: list[str]; warnings: list[str]

    def check_connection(self) -> str    # plain sentence, or raise
    def describe(self) -> list[str]      # what the instance offers, to help fill in a mapping
```

`DayRecord` (`dssreport/model.py`) is the only shape the rest of the program sees: location, business date, sales total, payments by type, cash over/short, missing receipts, payment exceptions, approved, POS import received.

### Rules every connector must keep

1. **Read-only.** No way to write to R365.
2. **Blank means `None`.** Never turn an unknown into 0 or False. `None` is reported as UNKNOWN.
3. **Unavailable fields go in `unmapped`.** The matching checks then show "needs mapping" instead of guessing. Do not invent fields.
4. **Credentials** come from `store.get(instance.credential_key)` (the operating system's credential store). Never log them, never put them in an error message, never send them to any address except the one the user configured.
5. **Plain-words errors.** Raise `ConnectionFailed` when the connection cannot be made (shown as "could not connect: ..."), `InputError` for bad data (shown as "could not read its data: ..."), `ConfigError` for a bad mapping. One connection failing must not stop the others; the runner already guarantees that.
6. **No other network calls.** Only the user-configured address.

### Adding a connector (when R365's new API details are confirmed from their own documentation)

1. Write `class NewApiSource(DataSource)` with a new `kind` and the `mapping_formats` it needs.
2. Decorate it with `@register_source`, and make sure its module is imported by `build_source`.
3. Add a test with a local mock server, like `tests/mock_r365.py`.
4. Switch an instance to it by setting its `source_kind` (the settings file keeps it per connection, so one customer can run an old OData connection next to a new API one).

Nothing in `rules.py`, `report.py`, `render.py`, `graph.py`, `scheduler.py` or `settings_server.py` changes. A test (`FakeSecondSource` in `tests/test_multi_instance.py`) registers a second kind of source and runs it end to end to prove this.

## Mapping files and their version

Each connection has its own mapping file, outside the repo (`%LOCALAPPDATA%\DssReport\mappings\<connection>.toml`). The first line is `version = 1`. A connector lists the versions it understands in `mapping_formats`. If a file has a different version the connector refuses it with a plain message ("The mapping file ... is format 2, but this connector reads format 1"), so a future connector can require its own format without silently misreading an old one. Files made before versions existed count as format 1.

The mapping format itself (which names go where) belongs to the connector. The template in the repo, `r365_mapping.example.toml`, is for the OData connector and ships empty.

## Which connection a record came from

The report groups by connection name. Per connection, the program keeps: name, address, user name, credential entry, mapping file, "only these locations", hidden locations. All of it is in the user's own folder, not the repo.
