# Restaurant365 - what is confirmed, what is not

The rule for this product: follow R365's public documentation only, and **do not guess**. Where a
detail is not clearly documented, the program treats it as UNKNOWN, the matching check skips itself,
and the report says "needs mapping".

## What the owner's testing found (this changes the plan)

The owner tested real R365 instances (no tenant details are recorded anywhere here) and found:

- **The OData connector does NOT expose DSS approval status or cash over/short at all.** The two checks this program exists for ("entry not approved", "cash over or short") could therefore never run against a real tenant through OData.
- **What does work is the Daily Sales Summary list export** that an R365 user downloads from the classic DSS list (the Excel/CSV icon). It carries these headings, among others: Approval Status, Location, Location Number, Name, Date, Attachment, Net Sales, Total Deposit, Over/Short, Guest Count, Steps Complete, Log Entries, Paidout Total, Created By, Created On, Modified By, Modified On. Approval Status is plain text: **"Approved"** or **"Unapproved"**.
- R365's newer ("beta") DSS list export has a slightly different layout and header wording, and also a status word **"In Progress"** (and **"Completed"**). The classic layout is expected to go away.

So the program now has a **DSS export (file) source** (`docs/EXPORT_SOURCE.md`), which is the recommended one. The **OData connector is kept as optional and is labelled "does not provide approval or over/short; unproven against a live tenant"**. Everything below about OData describes only that optional connector.

### Still UNKNOWN (not in the export, not checked from it)

| Item | Status |
|---|---|
| POS import status | UNKNOWN. Not in the export. |
| Anything equivalent to "missing receipts" | UNKNOWN. Not in the export (and possibly not an R365 concept at all). |
| Payment exceptions | UNKNOWN. Not in the export. |
| R365's own balancing flag | UNKNOWN. Not in the export. |
| Who approved an entry, and when | UNKNOWN. Not in the export. |
| The exact headings and footer of the beta list | ASSUMED (covered by the heading-alias list). One real beta file is needed to confirm. |
| Meaning of `In Progress` / `Completed` for approval | UNKNOWN. Kept as the original word and shown as UNKNOWN. The owner may map a word per connection after checking it against a known case. |
| Sign convention of Over/Short | ASSUMED negative = short, positive = over. Check against a known entry. |

## How this list was made (read this first)

The build environment could not open R365's documentation website directly. What is written here comes
from web-search result summaries of R365's public help pages and from third-party descriptions. **A
person must read the pages below and confirm each item before relying on it.** Nothing here was checked
against a real R365 tenant, and no real tenant, credential or data was used.

Pages consulted (by search summary only):
- OData connector: https://docs.restaurant365.com/docs/restaurant365-odata-connector
- R365 API connector: https://docs.restaurant365.com/docs/r365-api-connector
- Public API authentication / request access: https://docs.restaurant365.com/apidocs/authentication , https://docs.restaurant365.com/apidocs/request-access
- Daily Sales Summary pages: https://docs.restaurant365.com/docs/daily-sales-summary , https://docs.restaurant365.com/docs/daily-sales-review-a-dss , https://docs.restaurant365.com/docs/daily-sales-approve-a-dss
- Third-party (treat with caution): API Evangelist and Supergood listings for Restaurant365.

## Where your real mapping lives (private, never committed)

`r365_mapping.example.toml` in this repository ships **empty, on purpose**, and the fields are never guessed.
The real mapping for a real tenant is filled in privately by the owner, in the user-config folder on the
computer that runs the report:

- Windows: `%LOCALAPPDATA%\DssReport\mappings\<connection>.toml`, one file per R365 connection (a single-connection install from before keeps using `r365_mapping.toml`)
- (the settings screen shows each connection's exact path and how many items are still empty)
- Every mapping file starts with `version = 1`. A future connector for R365's new API can require a different version; see `docs/DATA_SOURCES.md`.

That folder is outside this repository. `r365_mapping.toml`, `settings.json` and `state.json` are also in
`.gitignore` and a test fails if one appears in the repo. The same goes for the R365 address, user name,
Microsoft app ID, tenant and email addresses: they are typed into the settings screen on the user's
computer and are never put in the repo, the docs, the tests or the screenshots (which use obviously fake
placeholders).

## What the public documentation appears to say

| Item | What we saw | How the program uses it |
|---|---|---|
| OData sign-in | "Domain\Username" with the R365 password (HTTP Basic) | Settings screen asks for exactly that. Sent only to the address you enter, over https. |
| OData address | `https://odata.restaurant365.net/api/v2/views`, with a `$metadata` document | Not built in. You type the address; "test connection" reads `$metadata`. |
| Which data OData offers | Documented entity found: Transaction. A page says sales and labor from intraday polling are not in OData, only after polling of the Daily Sales Summary. | Nothing is assumed about a DSS entity. |
| DSS over/short | The DSS page flags over/short outside -$5.00 to +$5.00 | Our default limit is $5.00, you can change it. |
| DSS approval | Approval needs the "Approve" permission, is done in the Classic experience, and is immediate and irreversible | See question 3. |
| Paging | Public API lists use an `items` array and `nextLink`; OData normally uses `@odata.nextLink` | The connector accepts either and follows the link only if it stays on the same website. |
| Public (non-OData) API | Early-adopter group, closed to new requests when last seen; token-based | **Not used.** |

## Open questions about the optional OData connector (each one needs a person with a real tenant or R365 support)

Close a question by running `python -m dssreport r365 discover` against your own tenant, reading R365's
documentation for that entity, then filling in `r365_mapping.toml`.

1. **Which OData entity holds one row per location per business day with the daily-sales-summary figures?** Not clearly documented. If none exists, this product can only use what R365 does expose and some checks will stay "needs mapping".
2. **What are the property names** for sales total, payments by type, cash over/short, missing receipts, payment exceptions, location name and business date? Unconfirmed. `r365_mapping.toml` ships empty.
3. **DSS approval status.** Catching entries that were not approved is the point of the tool, so the approval check is **on by default**. The UI concept (approved / complete) is documented; how it appears in OData (a true/false, a status word, an entity of its own) is not. Until an approval field is mapped, the report shows "needs mapping" for it and does not run it; the moment a field is mapped it runs, with nothing to switch on. If the property holds words, list which words mean approved and not approved in the mapping; any other word is shown as UNKNOWN, never guessed. (The demo and CSV paths have an approval column, so they show the check working.)
4. **POS import received.** R365 describes polling/importing sales from the POS. How "the POS import has arrived for that day" can be read through OData is not confirmed.
5. **"Missing receipts" and "payment exceptions."** The documentation we saw talks about *exception sales tickets* on the DSS; we found no documented DSS concept called "missing receipts". These two counts may not exist in R365 and may need to be renamed or dropped. Until mapped they are skipped.
6. **Payments add up to sales (optional check).** Needs the sales total and every payment type mapped, and a decision on which payment types count. Ships off, "needs mapping".
7. **Date filter format** (`2026-03-13` vs `2026-03-13T00:00:00Z`) and **property types.** Set with `date_literal` in the mapping; unconfirmed.
8. **Query limits.** A third-party review mentions a 31-day cap on sales queries. Unconfirmed; the connector asks for at most 31 days at a time.
9. **Getting access.** Who in R365 enables the OData connector for a customer, who signs off, and what the agreement says about a third-party program reading the data using the customer's own login. Needs R365 support and a conversation with the customer.
10. **Locations that return nothing.** A location that returns no rows at all can't be seen in the data. Decision by the owner: the program does **not** remember earlier locations as expected. A location is shown as UNKNOWN only if the user lists it under "Only these locations" or it returned rows with blank required values. The report says so in its footer. Locations seen on earlier runs are used only to build the Show/Hide list in settings, so a closed restaurant can be switched off.

## Microsoft 365 (email) - also unconfirmed against a real tenant

11. The sign-in needs an **app registration** in the customer's Microsoft 365 (a public client with "allow public client flows" on). The user enters the app (client) ID, and their own address, in settings or at first sign-in. None is built in or committed. Not done here.
12. Permissions requested: `Mail.ReadWrite` (create a draft) and, only if "send automatically" is ticked, `Mail.Send`; plus `offline_access` so you don't sign in every day. We believe these are the least that Microsoft documents for creating and sending a message; confirm in the customer's tenant, including whether an administrator must consent.
13. Conditional-access rules in some tenants block this kind of sign-in.

## Windows pieces - written but not run on Windows

14. `install-windows.cmd`, the Credential Manager store (`credstore.py`) and the Task Scheduler setup (`scheduler.py`) were written carefully and checked for obvious mistakes, but **have not been run on a Windows machine**. Treat the first Windows run as a test.
