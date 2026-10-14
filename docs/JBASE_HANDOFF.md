# For the jBase build (read by Codex): what the owner decided that jBase may not have yet

This extends `docs/SYNC_WITH_CODEX.md`, which Codex has already read; its privacy rules and hand-back steps still apply and are not repeated in full here. **Real names are fine in the chat with the owner, never in anything committed or pushed.**

jBase is the main, full-featured program. This repository is the standalone, sellable DSS report. Take from here only what helps jBase; do not copy this repository's structure into jBase.

## 1. The DSS report the owner wants (replaces "Place | Complete? | Flag" and anything longer)
A very fast brief an accounting manager (AM) can read in seconds, then drill into.
- **Only what is still unapproved.** Do not list approved places.
- **If everything is approved:** say "Nothing outstanding to approve." (nothing else).
- **Each unapproved place gets one short line**, either "Ready to approve" (nothing else flagged) or a **likely** reason in plain accounting words, for example "Needs to balance: Over/Short -12.50" or "POS import not received". The owner says it is almost always one of two things needing a human. Reasons are *likely*, never stated as the proven cause.
- **A place whose status cannot be told** (no row, blank or unclear status such as "In Progress", file older than today, conflicting rows, no approval column) goes under **"Could not tell"**. Never count it as approved and never hide it.
- Over/Short sign is **unproven**: show the number as R365 gives it, never call it "short" or "over".
- No long pages, no jargon the owner is unsure of, no "tasks" lists on this report.
- Reference implementation and wording: `dssreport/brief.py` and `dssreport/data/reason_terms.toml` on `main`. The wording file is owner-editable; do the same in jBase (a plain list of phrases, not code).

## 2. jBase screens the owner said were not right
- **Active clients come first** in the client list, not near the end (reported live as fixed; re-check).
- An existing customer must never be shown as a lead (reported fixed; add a test that a customer-type client cannot appear under Researching).
- The OCRA page: short, readable, secondary detail collapsed, no unexplained words or task jargon.
- The hours/rate entry: editable hours and rate, totals computed automatically, shows what is owed after credits (reported done; re-check it persists after a restart).

## 3. Which places and instances are included
- Work from an explicit **list of places per R365 instance**. Some instances set their DSS up differently and are simply left off the list. There may be **two DSS versions** (classic and beta).
- **Do not check for missing places.** Only places that report matter. A listed place with no row shows under "Could not tell".
- The two real instances for testing are the owner's own (the owner will name them in chat). The product should work for any instance later.

## 4. R365 changes often and at different times per instance
- Find columns by **heading name** from an editable list, not by position. Unknown headings are listed by name; a renamed heading is a one-line addition, not a code change. See `dssreport/data/dss_export_aliases.toml` and `docs/EXPORT_SOURCE.md`.
- Status words are mapped **per instance by the owner** (for example what "In Progress" means) after checking against a known case; until then they stay UNKNOWN.
- Record the date a change was noticed, per instance.

## 5. Getting the DSS list (decisions)
- **Hold on automatic fetching.** For now the owner exports the list manually.
- **OData:** earlier testing found it does not expose approval status or over/short. The owner thinks it may now. **Please settle it inside jBase** by listing the fields each instance's OData offers (names only) and report whether any approval or over/short field exists. If it does, map it; if not, record that.
- **Web export** (driving the beta screen's Export with the owner's own signed-in account) is a possible later route. It is fragile and needs the owner's explicit go-ahead before any building. Do not start it.
- Never change anything in R365. Auto-approval stays **off**.

## 6. Later (do not start)
- Entries that **need coding** go to the AM's folder. The DSS list export has no field for it, so the report can only say UNKNOWN today.
- A local AI (an Ollama-style model) may later write the one-line summary, and only once every rule is verified at 100% may it assist with approval or coding review. Not needed now. Nothing leaves the computer.

## 7. Proven facts to rely on (from the owner's real export testing; details in `docs/EXPORT_SOURCE.md`)
- Classic and beta CSV headings, the classic `__count` row total, the beta byte-order mark, and the number and date formats are all recorded there.
- UNKNOWN: Over/Short sign; whether beta "In Progress" equals classic "Unapproved" (only one matching pair seen); why one beta row was missing; whether XLSX or TSV can be downloaded; row limits and paging.

## 8. What to send back (counts and rules only in anything committed)
1. A short list of what jBase already did that matches this file, and what it changed to match it.
2. The OData field answer from section 5.
3. Anything in jBase's brief report the owner liked that `dssreport/brief.py` should copy, described in words.
4. Anything above that conflicts with how jBase works, and why.
Hand back by pasting into the chat with the owner, or by adding a dated entry to the Codex log in `docs/SYNC_WITH_CODEX.md` on a branch named `codex-sync` (never `main`, no pull request, nothing merged).

## Handy tool
`python -m dssreport export inspect FILE` prints headings, counts, status words and formats with no names or amounts. Safe to paste.
