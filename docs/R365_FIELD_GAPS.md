# R365 field gaps (read-only connector `r365-readonly`)

The connector `dssreport/r365_readonly.py` uses only names written on R365's public documentation:
<https://docs.restaurant365.com/docs/restaurant365-odata-connector> and
<https://docs.restaurant365.com/docs/r365-api-connector>.

**Status: nothing is confirmed yet.** The session that built it could not open docs.restaurant365.com
(blocked by that session's network), so no name was copied from the docs and none was guessed. The
table `dssreport/data/r365_documented_fields.toml` ships with every entry empty. Each empty entry is
**UNKNOWN**: the value comes back as `None`, the matching check shows "needs mapping" in the report, and
the connector sends no data request at all until the entity, location and date names are filled in.

To close a gap: read the public R365 page, put the exact name in the table, and write the page address
beside it. Never use a name from a real tenant's data, a third-party site, or memory.

| Item | Status | Needed from the public docs |
|---|---|---|
| `entity` | UNKNOWN | Entity set with one row per location per business day |
| `location` | UNKNOWN | Property with the location name |
| `business_date` | UNKNOWN | Property with the business date (and date format) |
| `sales_total` | UNKNOWN | Daily sales total property |
| `cash_over_short` | UNKNOWN | Owner's testing says OData does not expose it (see R365_OPEN_QUESTIONS.md) |
| `missing_receipts` | UNKNOWN | May not be an R365 concept |
| `payment_exceptions` | UNKNOWN | May not be an R365 concept |
| `approved` | UNKNOWN | Owner's testing says OData does not expose it; also needs the words for yes/no |
| `pos_import_received` | UNKNOWN | How a POS import is shown, if at all |
| `payments` | UNKNOWN | Payment type -> amount properties |

Keep this table in step with the data file: a test fails if an UNKNOWN item is missing here.
