# Developer notes (internal)

This is for whoever maintains the program. Reviewers do not need it.

## How the pieces fit

```
data source ──► DayRecord list ──► rules (rules.toml) ──► Report ──► report.html + email.txt ──► (optional) Microsoft 365 draft
(R365 / demo / files)
```

The product's one real data source is **Restaurant365, read-only** (`dssreport/r365.py`). The demo generator and the CSV/JSON reader exist so the program can be tried, demonstrated and tested without any tenant. The source is kept behind a small interface (`dssreport/adapters/base.py`) only so these three can share the rules and report code.

## The record

| Field | Meaning | Unknown is |
|---|---|---|
| `location` | name (required) | — |
| `business_date` | date (required) | — |
| `sales_total` | money | `None` |
| `payments` | payment type → money | `None` per type |
| `cash_over_short` | money; negative = short, positive = over | `None` |
| `missing_receipts` | whole number | `None` |
| `payment_exceptions` | whole number | `None` |
| `approved` | true/false | `None` |
| `pos_import_received` | true/false | `None` |

**Rule one:** a blank or unavailable value is `None`. Never fill a gap with 0 or False. `None` is reported as UNKNOWN.

**Rule two:** a source that cannot provide a field *at all* lists it in `adapter.unmapped`. Checks that need it are skipped and shown as "needs mapping" (not as UNKNOWN on every row, and never as clean).

## Demo / test file format (CSV or JSON)

CSV columns: `location, business_date (YYYY-MM-DD), sales_total, pay_<type> (any number), cash_over_short, missing_receipts, payment_exceptions, approved (yes/no), pos_import_received (yes/no)`. Blank = unknown. JSON is a list of objects with the same names and `payments` as an object. See `examples/demo/`. Bad values stop the run and say which row; two rows for the same location and day stop the run and say which two and how to fix it.

## Where things are

| File | Job |
|---|---|
| `rules.py`, `report.py` | the checks and the report facts |
| `render.py` | HTML page and plain-text email |
| `r365.py` | read-only OData client, field mapping, `$metadata` discovery |
| `credstore.py` | OS credential store (Windows Credential Manager; Linux `secret-tool`) |
| `graph.py` | Microsoft 365 sign-in (device code) and draft/send |
| `settings.py`, `settings_server.py` | the settings screen and `settings.json` |
| `scheduler.py` | what to do when woken, late label, Windows Task Scheduler XML |
| `settings_server.py` (view page) | `/report` shows the saved report with "create Microsoft 365 draft" and "open in my mail app" buttons; nothing is emailed until a button is pressed |
| `state.py` | run memory: last scheduled slot, last report folder, locations seen (used only for the Show/Hide list, never as expected locations) |
| `licence.py`, `licence_keys.py`, `ed25519.py` | offline signed licences: format, signature check (stdlib Ed25519), status, feature flags, connection limit. `tools/` holds the signing side, outside the shipped package |
| `updates.py` | owner-signed update files: verify, check the licence allows it, install only program files, backup and rollback. No network. `tools/update_tool.py` builds them |
| `sources.py` | the one interface to R365 data (`DataSource`), a registry of connector kinds, mapping-format check |
| `summary.py` | optional local-model sentence and the check that discards a wrong one |

## Tests

`python -m unittest`. Everything that talks to the network is tested only against local mocks in `tests/mock_r365.py` and `tests/mock_graph.py` (made-up data, invented names). Passing tests do **not** prove the R365 or Microsoft connections work against the real services; see `docs/R365_OPEN_QUESTIONS.md`.
