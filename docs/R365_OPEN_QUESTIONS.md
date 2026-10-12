# Restaurant365 - what is confirmed, what is not

The rule for this product: follow R365's public documentation only, and **do not guess**. Where a
detail is not clearly documented, the program treats it as UNKNOWN, the matching check skips itself,
and the report says "needs mapping".

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

## Open questions (each one needs a person with a real tenant or R365 support)

Close a question by running `python -m dssreport r365 discover` against your own tenant, reading R365's
documentation for that entity, then filling in `r365_mapping.toml`.

1. **Which OData entity holds one row per location per business day with the daily-sales-summary figures?** Not clearly documented. If none exists, this product can only use what R365 does expose and some checks will stay "needs mapping".
2. **What are the property names** for sales total, payments by type, cash over/short, missing receipts, payment exceptions, location name and business date? Unconfirmed. `r365_mapping.toml` ships empty.
3. **DSS approval status.** The UI concept (approved / complete) is documented; how it appears in OData (a true/false, a status word, an entity of its own) is not. **The approval check ships switched off** and shows "needs mapping" until the mapping and the words that mean approved / not approved are confirmed. Unrecognised words are shown as UNKNOWN, never guessed.
4. **POS import received.** R365 describes polling/importing sales from the POS. How "the POS import has arrived for that day" can be read through OData is not confirmed.
5. **"Missing receipts" and "payment exceptions."** The documentation we saw talks about *exception sales tickets* on the DSS; we found no documented DSS concept called "missing receipts". These two counts may not exist in R365 and may need to be renamed or dropped. Until mapped they are skipped.
6. **Payments add up to sales (optional check).** Needs the sales total and every payment type mapped, and a decision on which payment types count. Ships off, "needs mapping".
7. **Date filter format** (`2026-03-13` vs `2026-03-13T00:00:00Z`) and **property types.** Set with `date_literal` in the mapping; unconfirmed.
8. **Query limits.** A third-party review mentions a 31-day cap on sales queries. Unconfirmed; the connector asks for at most 31 days at a time.
9. **Getting access.** Who in R365 enables the OData connector for a customer, who signs off, and what the agreement says about a third-party program reading the data using the customer's own login. Needs R365 support and a conversation with the customer.
10. **Locations that return nothing.** A location with no rows can't be seen in the data. The program remembers locations seen on earlier runs and shows a silent one as UNKNOWN; the "Only these locations" setting does the same. The very first run only knows the locations that returned rows.

## Microsoft 365 (email) - also unconfirmed against a real tenant

11. The sign-in needs an **app registration** in the customer's Microsoft 365 (a public client with "allow public client flows" on). Its ID goes in settings. Not done here.
12. Permissions requested: `Mail.ReadWrite` (create a draft) and, only if "send automatically" is ticked, `Mail.Send`; plus `offline_access` so you don't sign in every day. We believe these are the least that Microsoft documents for creating and sending a message; confirm in the customer's tenant, including whether an administrator must consent.
13. Conditional-access rules in some tenants block this kind of sign-in.

## Windows pieces - written but not run on Windows

14. `install-windows.cmd`, the Credential Manager store (`credstore.py`) and the Task Scheduler setup (`scheduler.py`) were written carefully and checked for obvious mistakes, but **have not been run on a Windows machine**. Treat the first Windows run as a test.
