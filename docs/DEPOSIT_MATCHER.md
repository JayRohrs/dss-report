# Deposit matcher

A helper that lines up the deposit each place is expected to make (the **Total Deposit** in the Daily Sales Summary list) with the lines on a bank export, and explains each place in plain words: matched, needs a look, or cannot tell. It reads two files, changes nothing and sends nothing.

## Using it
- **By hand:** Settings > section 9 > *Open the deposit matcher*, choose a bank file (.csv or .ofx) and, if no DSS list is kept by a connection, the DSS list. Or run `python -m dssreport demo-deposits --out <folder>` for made-up files to try.
- **Automatically:** in Settings section 9 give a bank file or a folder the bank exports land in. The existing daily schedule (`dss-report.exe schedule on`, or the classic schedule) checks for a **new** bank file each run, matches it and keeps the result. Open the screen to see it. A bank file already checked is not checked again.
- Each row has **Looks right**, **Flag** and **Draft a note**. A note is text to copy, or a Microsoft 365 *draft* (same draft-only path as the report email). Nothing is sent.

## What it never does
It never guesses. "Matched" means: same amount to the cent, inside the date window, and no other place or day could equally be the answer. Near misses, swapped digits, split deposits, one deposit for two days, duplicate bank lines, and ambiguous amounts are shown with their reasons, never matched. A comma in an amount follows the same rule as the DSS export: `1,234.50` reads, `23,50` is not read.

## Assumptions (shown on screen, kept in one place)
`dssreport/data/deposit_matcher.toml`, overridable by `deposit_matcher.toml` in the DssReport folder: Over/Short sign (unknown), timing window, near-miss size, split/combined limits, decimal comma, place hints. Wording lives in `reason_terms.toml` under `[deposits]`.

Not known yet: the Over/Short sign, how R365's fields map to a bank deposit, and what a real bank export looks like. Test with a real, known day before relying on a match.
