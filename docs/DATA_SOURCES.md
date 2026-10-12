# Data sources: swapping the R365 connector

R365 is changing its API. This program keeps all R365 data access behind **one interface** (`DataSource` in `dssreport/sources.py`) so the current OData connector can be replaced by a connector for the new API **without touching the rules, the report, the email or the settings screen**.

Status: only the OData connector exists (`dssreport/r365.py`). **No connector for the new API is built, and none of its details are guessed here.** This document describes the seam, not the new API.

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
