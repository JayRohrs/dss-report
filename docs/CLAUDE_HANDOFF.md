# Hand-off for a new Claude session: the whole story of this project

Read this first, then `docs/PROJECT_BRIEF.md`, `docs/EXPORT_SOURCE.md`, `docs/R365_OPEN_QUESTIONS.md` and `docs/SYNC_WITH_CODEX.md` (the Codex log on branch `codex-sync` is newer than `main`'s copy). Written 2026-11-02.

## Who and what
- The owner (Jay) runs an accounting service for restaurant groups on Restaurant365 (R365). Plain-words reports, no jargon. All data in this repo is invented.
- **Two builds exist.** (1) **jBase**, the owner's full-featured program, built by **Codex** locally on the owner's computer; it is the main product. (2) **This repository**, the standalone, sellable DSS report, built by Claude. They share ideas through the hand-off files; they do not share code.
- The goal of the DSS report: a brief an accounting manager (AM) reads in seconds: **which Daily Sales Summaries (DSS) are still unapproved, and the likely reason**. Almost always one of two things needs a human; later an AI may assist once every rule is verified.

## Working agreements with the owner (follow these)
- Small clear commits; **new PR, never push to `main`**; merge only when the owner says so. Never deploy, publish or change repository settings.
- Report in plain words: what changed, test counts, what is **not proven**, follow-ups. Do not drift into licensing/updates/sync plumbing when the owner wants the product (the owner called this out twice).
- **Real names are fine in chat with the owner, never in anything committed.** `local-testing/` is git-ignored. Use invented values ("Sample Pier Grill", 12.50) in the repo. A test blocks GUID-shaped ids, so build fake ids at runtime.
- Facts, not opinions. Write UNKNOWN rather than guess. Never present an Unapproved day or a cash difference as the proven reason a DSS is unfinished; reasons are "likely". The Over/Short **sign is unproven**: show the number "as R365 gives it". Auto-approval stays **off**.
- Python 3.11+ standard library only; tests are `python -m unittest discover -s tests -t .` (430 pass; also run with `python -W error::ResourceWarning`). No pytest.

## State of this repository (main = b377816 plus later branches)
- `main` contains PR #3 (offline signed licences, several R365 connections, swappable data-source interface, owner-controlled signed updates) and PR #4 (the DSS export source, the brief report, `export inspect`).
- Open branches: `jbase-handoff` (this file and `docs/JBASE_HANDOFF.md`, not merged), `codex-sync` (Codex's log only, one file, not merged). Old branches `phase2-r365`, `phase3-licensing`, `phase4-dss-export` can be deleted.
- Key code: `dssreport/dss_export.py` (reads CSV/TSV/xlsx by heading name; classic and beta layouts), `dss_export_source.py`, `brief.py` + `data/reason_terms.toml` (the brief report, owner-editable wording), `rules.py`, `report.py`, `render.py`, `runner.py`, `settings_server.py` (local settings page with token + CSP), `dss_inspect.py` (`python -m dssreport export inspect FILE`: safe description with no names or amounts), `data/dss_export_aliases.toml` (editable heading list), `licence.py`/`updates.py` (done; leave alone).
- The report: only unapproved places, each "Ready to approve" or a *likely* reason ("Needs to balance: Over/Short -23.50"); all approved -> "Nothing outstanding to approve."; unclear status -> "Could not tell". The long report is still written as `report-full.html` / `email-full.txt` (`--full`).

## What is established about R365 (from the owner's real testing; details in the docs)
- OData did not expose approval status or over/short in earlier testing. The DSS list export does. Classic and beta CSV headings, `__count`, BOM, date/number formats are recorded in `docs/EXPORT_SOURCE.md`.
- UNKNOWN: Over/Short sign; whether beta "In Progress" equals classic "Unapproved"; one beta row missing unexplained; XLSX/TSV availability; row limits and paging; POS import health, receipt requirements, independent balancing.

## What Codex has done in jBase (from its log; I have not seen its code)
- Brief report in jBase matching the owner's preferred format (only unapproved, one short line, "Could not tell", exact "Nothing outstanding to approve."); table later changed to Instance | Location | Status | Likely needs.
- Active clients first; customers cannot appear as leads; hours/rate entry with credits persisted.
- **A free live path, outside this repo:** a Chrome extension pilot that reads the owner's already signed-in R365 classic DSS list (Approval Status, Location, Date, Over/Short, Steps Complete only), newest first, without saving a view or changing records. Verified live on both of the owner's instances (250 rows each, seven-date window; 12 unapproved found in one run). Weekday 6 AM check queues the same browser job but needs the app, browser and sign-in session open; an unattended run is still UNKNOWN. It never reads or copies credentials or cookies. "Open DSS day" links open the right day in R365.
- Later pilot versions (0.1.x to 0.1.29) added multi-instance selection, search by amount, and **local-only approval previews** for zero-difference days. **No real approval has been performed.** The owner describes eventual approval followed by a remaining-exceptions list as future scope.
- This changes the earlier assumption in this repo that fetching needs a manual download: the owner and Codex now do it through the browser extension with the owner's own sign-in. The standalone repo still reads exported files only, and it does not drive R365's pages.

## Open items and sensible next steps
1. Decide with the owner whether the standalone product needs the live path at all, or whether this repo's role is now reusable pieces (file reader, brief wording, inspect command) alongside jBase. Ask before building either.
2. Merge `jbase-handoff` (docs only) if the owner wants these files on `main`; do not merge `codex-sync` without checking it only changes `docs/SYNC_WITH_CODEX.md`.
3. Real-file verification of the unproven items above using `export inspect` output pasted by the owner.
4. Later and not started: entries needing coding (AM folder), local AI (Ollama-style) once rules are 100%, actual approval actions.

## Prompt to give the new Claude session
"Read docs/CLAUDE_HANDOFF.md in JayRohrs/dss-report (branch jbase-handoff), then docs/PROJECT_BRIEF.md and docs/SYNC_WITH_CODEX.md from branch codex-sync. Follow the working agreements in that file. Tell me in plain words what you understand the state to be and what you would do next; do not change anything until I answer."
