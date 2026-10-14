# Project brief (the one place to find what this is, what is decided and what is open)

Update this file when a decision changes. Everything in it is about the product, not any client: no real names, amounts or files belong in this repository.

## What it is
A small program that reads the Restaurant365 (R365) Daily Sales Summary (DSS) list for one or more R365 instances and tells an accounting manager, in a few seconds, **what is still unapproved and the likely reason**. It is meant to be sold as a standalone package that can work for any customer instance, and to be kept up to date from jBase.

## The report (decided)
- Only unapproved places are listed. Everything approved: "Nothing outstanding to approve."
- Each unapproved place gets one line: **Ready to approve** or a **likely** reason ("Needs to balance: Over/Short ...", "POS import not received", ...). Almost always it is one of two things that need a person.
- Anything that cannot be told (no row, unclear status like "In Progress", stale file, conflicting rows, no approval column) is listed under "Could not tell", never treated as approved.
- Reasons are likely, never proven causes; nothing approves anything. Auto-approval is a later phase and stays off until every required check is verified.
- Wording lives in `dssreport/data/reason_terms.toml`; the owner can override it with `reason_terms.toml` in the DssReport folder.

## Which places are checked (decided)
- Work from a list: each connection's **"Only these locations"** and hide list. Some instances set their DSS up differently and are simply left off the list.
- There is no "expected places" check. Only places that report matter; a place that is listed but has no row shows as "could not tell".
- There may be two versions of the DSS layout (classic and beta). Both are read; see `docs/EXPORT_SOURCE.md`.

## Keeping up with R365 changes
R365 changes its screens and exports at different times on different instances. The reader finds columns by **heading name** from an editable list (`dss_export_aliases.toml`, added to by a file in the DssReport folder), so a renamed heading is a one-line addition, not a code change. Unknown headings are listed by name in the report. Status words are mapped by the owner per connection ("In Progress" means whatever the owner says; until then Unknown).

## Unproven (do not state as fact)
- The sign of Over/Short (wording stays neutral until one known shortage confirms it).
- Whether "In Progress" (beta) equals "Unapproved" (classic): one matching pair seen.
- Why one beta row was missing from an export; whether XLSX/TSV can be downloaded; whether a long list is paged or capped.
- Whether R365 can deliver the DSS list export on a schedule (ask R365 support; the program can pick up a file from a folder once there is a reliable delivery).

## Real-world testing
Testing against the two real instances happens outside this repository (jBase / Codex) so that no private data enters it. Bring back only headings, formats and invented examples. Never commit a real export.

## Updates and jBase
The standalone program's updates are owner-signed packages (`docs/UPDATES.md`). jBase may keep a checkout of this repository up to date (fast-forward only); that does not publish or install anything for customers. Syncing jBase's own brief report with this one is a manual step until the two share a format.

## Local AI (later)
Optional and off. An Ollama-style local model could write the one-line summary or, once every rule is verified 100%, assist with the approval review. It is not needed for the brief report today, and nothing sends data off the computer.

## Open next steps
1. Merge PR #3 and PR #4 so `main` carries this work and jBase can follow it.
2. Confirm the Over/Short sign and the In Progress meaning from real files (outside this repo).
3. Ask R365 whether the DSS list export can be scheduled; then add a watched-folder pickup before 6 AM.
