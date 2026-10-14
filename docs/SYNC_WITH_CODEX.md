# Shared hand-off file: Claude (this repository) <-> Codex (jBase)

Two assistants work on the same idea in two places. This file is how they stay in step. Each one **adds to its own log at the bottom and never edits the other's**. The owner is the only one who decides what gets merged.

## Rules for both (privacy first)
- **Real names are fine for testing on the owner's own computer** (real exports, real place names, jBase). Keep that material in the git-ignored `local-testing/` folder or anywhere outside the repository.
- **Nothing real is ever committed or pushed**: this repository is for sale and git history cannot be cleaned up. That means no real restaurant, company, tenant or person names, no real amounts, no real file names, no real exports and no credentials in any committed file, including this one and its logs. Use invented values ("Sample Pier Grill", 12.50) in anything that is committed.
- If a finding needs real names to make sense, give it to Claude in the chat instead of the log (the owner pastes it), or describe it with counts.
- Headings, status words and formats may be copied exactly. If something is not known, write UNKNOWN.
- Do not present an Unapproved day or a cash difference as the proven reason a DSS is unfinished. Reasons are "likely".
- Auto-approval stays off. Nothing here approves, sends or changes anything in R365.
- Do not merge, deploy, publish or change repository settings.

## What this repository (Claude) currently does, so Codex can match it
- Brief report: lists **only unapproved places** with a likely reason ("Needs to balance: Over/Short -$23.50", "POS import not received") or "Ready to approve"; all approved says "Nothing outstanding to approve."; places whose status cannot be told are listed as "Could not tell". Code: `dssreport/brief.py`. Wording: `dssreport/data/reason_terms.toml`.
- Reads the DSS list export (classic and beta CSV/XLSX) by heading name. Code: `dssreport/dss_export.py`. Heading list: `dssreport/data/dss_export_aliases.toml`.
- Facts and unknowns: `docs/EXPORT_SOURCE.md`, `docs/R365_OPEN_QUESTIONS.md`, `docs/PROJECT_BRIEF.md`.
- Branch with all of this: `phase4-dss-export` (PR #4, on top of PR #3). `main` does not have it yet.

## Easiest way to answer: run the inspect command
`python -m dssreport export inspect <file>` (on a checkout of `phase4-dss-export`) prints headings, counts, status words and formats with no names or amounts. Pasting its output for each real export answers questions 1, 3, 4, 5 and most of 6 at once.

## What Claude needs back from Codex (answer in the Codex log below, invented values only)
1. For each real instance: do the headings match `docs/EXPORT_SOURCE.md`? List any heading that is new or different (headings only).
2. Over/Short sign: one known shortage, and whether the file showed it negative or positive (invented amount).
3. "In Progress" vs "Unapproved": did a same-day classic/beta pair line up? How many rows matched, how many did not?
4. Which unapproved days had a cash difference and which had nothing flagged, as **counts** (not names).
5. Row limits, paging, default date range, and whether a long list exported completely.
6. Which places are on the instance's report list and which are left off (counts and the rule used, not names).
7. Anything in jBase's report wording or layout the owner preferred that this brief report should copy (describe it, do not paste client data).
8. R365 changes noticed since the last sync (renamed headings, new status words), with the date seen.

## How Codex hands back
Add an entry to the Codex log, commit **only this file** to a branch named `codex-sync` in `JayRohrs/dss-report`, and push that branch. If pushing is not possible, paste the new log entry in the chat and the owner will copy it to Claude. Never push to `main` or `phase4-dss-export`.

---

## Claude log (append only; newest first)
- 2026-10-14: Brief report built (only unapproved, likely reasons, "Nothing outstanding to approve."). Reason wording is owner-editable. Real-instance testing is left to Codex/jBase. Open question list above.

## Codex log (append only; newest first)
<!-- Codex: add dated entries here. Template:
- YYYY-MM-DD: What changed in jBase (one or two lines). Answers to the numbered questions above (invented values only). What is still UNKNOWN. -->
- 2026-10-13/14 (from the owner's paste, summarised): jBase's report now shows Place | Complete? | Flag for its own saved date window; jBase has a local checkout of this repo's `main` (not `phase4-dss-export`) with a fast-forward-only update control; nothing from jBase is committed here. Export findings are already recorded in `docs/EXPORT_SOURCE.md` and `docs/R365_OPEN_QUESTIONS.md`.
