# The R365 DSS export (file) source

**The short version.** You download the Daily Sales Summary (DSS) list from Restaurant365 yourself, choose the downloaded file in this program, and it checks it. It is **read-only**: nothing is changed in R365, nothing is sent anywhere, and no sign-in or password is involved. This is the source that can run the two checks the program exists for, **"entry not approved"** and **"cash over or short"**.

## Why this source exists

The program was first designed to read R365 through its OData connector. The owner then tested real R365 instances and found that **OData does not expose DSS approval status or cash over/short at all**, so those two checks could never run against a real tenant that way. What does carry them is the DSS list export that an R365 user downloads from the DSS list (the Excel/CSV icon). So the export file is now the recommended source; the OData connector stays as an optional extra and is labelled as not providing approval or over/short.

## How to get the file from R365

1. In R365 open the **classic** Daily Sales Summary list.
2. Click the **Excel icon at the top right**, with **nothing ticked** in the list, so the export covers the whole list rather than selected rows.
3. Save the downloaded file somewhere you can find it (Downloads is fine). In the owner's testing the Excel icon actually downloads a **CSV** file; whether R365 can also give `.xlsx` or `.tsv` is not known, but all three are read.

R365's newer ("beta") DSS list has a slightly different layout and header wording, and the classic list is expected to go away. The program reads headings by **name**, not column position, and takes alternative wordings from a small list (below), so it copes with both. Both layouts' real headings are now known from the owner's testing (invented example rows in `tests/test_dss_export_real_layouts.py`):

- **Classic** (23 columns): `ApprovalStatus, Status, Location, LocationNumber, Name, Date, NetSales, TotalDeposit, OverShort, GuestCount, StepsComplete, CreatedBy, CreatedOn, ModifiedBy, ModifiedOn, DailySalesSummaryId, PaidoutTotal, __count, NewFileName, Attachment, AttachmentLinkType, FileLink, LogEntries`. There are two status columns; the program uses **ApprovalStatus** (Approved / Unapproved), not the plain `Status`. `__count` repeats the total number of rows on every row, so the program uses it as the file's own total and can tell if rows are missing.
- **Beta** (11 columns, starts with a byte-order mark): `Status, Location, Date, Attachments, Net Sales, Total Labor $, Total Labor Hours, Labor %, Total Deposit, Over/Short, Guest Count`. It has **no row count**, so completeness cannot be proven; the report says so and you may type the number of entries R365 shows into the **expected total** box to have it checked. Its status words include **In Progress**.
- Over/Short comes as e.g. `-12.5000` and dates as `9/29/2026 12:00:00 AM` (classic) or `09/29/2026` (beta); both are read.

## The brief report

The report only shows what is **still unapproved**, so it can be read in seconds.

- **Everything approved:** it says "Nothing outstanding to approve." and nothing else.
- **Unapproved places:** one row each, with a **likely reason** in plain accounting words, for example "Needs to balance: Over/Short -$23.50" or "POS import not received". If the export flags nothing else the row says **Ready to approve**. Approved places are not listed, even if they have a cash difference.
- **Could not tell:** places whose status cannot be established (no row, a blank or unclear status such as "In Progress", a file older than today, conflicting rows, or a file with no approval column) are listed under that heading. They are never counted as approved and never hidden.
- **Reasons are likely, not proven.** The export cannot say why a day is unfinished, so the report never states a cause, and nothing here approves anything.
- **Wording is the owner's to change.** The phrases live in `dssreport/data/reason_terms.toml`. Put a `reason_terms.toml` in your DssReport folder to change any of them without waiting for an update (a broken file is ignored, not fatal).
- The longer report is still written as `report-full.html` / `email-full.txt`; `--full` makes it the main report.
- Which places appear is your **"Only these locations"** list on each connection (and the hide list). There is no check for places that are missing from the file.

## Using it

1. In settings, **4. Restaurant365 connections**: add a connection, choose **"R365 DSS export file"** (no address, user name or password needed), tick **Use this connection** and save.
2. In **3. Check a DSS export** press **Choose file**, pick the file you downloaded, press **Check DSS export now**. The report opens on screen with the usual choices to email it or not.
3. Download a **fresh** file each morning. A file older than today cannot establish today's approval status (below).

Without the screen: `python -m dssreport export load <file>` keeps a copy for the connection, then `python -m dssreport run --input r365 --out out/` makes the report. To try it with made-up data: `python -m dssreport demo-export --out samples/` writes sample CSV, TSV and Excel files (a classic-style and a beta-style layout) with planted cases.

The program keeps a **copy** of the file you chose in its own folder (`%LOCALAPPDATA%\DssReport\exports\<connection>\`). It never opens the file you chose for writing and never changes it. The scheduled morning run reads that stored copy, so a schedule only gives meaningful approval results if a fresh file was chosen that morning; otherwise the report says the file is old.

## What it reads

Headings are compared **ignoring capital letters, spaces and punctuation**, so `Over/Short`, `over short` and `OVER-SHORT` are the same; `#` counts as "number". Extra columns and a different order are fine. The heading row does not have to be on line 1 (title lines above it are skipped), and a trailing totals or "Total Records" line is understood.

| We need | Headings accepted (first match wins) | Used for |
|---|---|---|
| Location (required) | Location, Location Name, Store, Restaurant, Unit | which restaurant |
| Date (required) | Date, Business Date, DSS Date, Sales Date | which business day |
| Approval Status | Approval Status, DSS Status, Review Status, Status | the approval check |
| Over/Short | Over/Short, Cash Over/Short, Over (Short), Short/Over, Variance | the cash check |
| Net Sales | Net Sales, Net Sale, Total Net Sales | the "sales total is blank" check |
| Location Number, Total Deposit | Location Number / Location # ..., Total Deposit / Deposit Total ... | read, not used by any check |

The list lives in `dssreport/data/dss_export_aliases.toml` (documented in the file). **To teach the program a new wording you do not edit it**: put your own `dss_export_aliases.toml` in `%LOCALAPPDATA%\DssReport` with the same layout; its words are added to the shipped ones and survive updates.

If a column is missing the report says so in plain words (for example "This file has no Over/Short column, so the cash over/short check could not run.") and that check is listed under "Not checked". Nothing is guessed. If there is no Location or no Date column the file cannot be read and the message says which.

## Status words

| The file says | The program treats it as |
|---|---|
| `Approved` | approved |
| `Unapproved` | **not approved** (flagged "Entry is not approved") |
| `In Progress` (beta list) | **UNKNOWN**, the word is kept and shown. R365 shows the entry as still being worked on. |
| `Completed` (beta list) | **UNKNOWN**, the word is kept and shown. The entry is marked complete but the file does not say it was approved. |
| anything else | **UNKNOWN**, the word is kept and shown |
| blank | UNKNOWN |

`In Progress` and `Completed` are **never** turned into approved or unapproved by default.

**Per-connection override (advanced, off by default).** After you have checked a word against a known case in R365, you can give it a meaning for **that connection only**: in the connection's block, "Extra meanings for status words", one per line, for example `In Progress = not approved`. Only `approved` and `not approved` are allowed as meanings. `Approved` and `Unapproved` themselves cannot be redefined. Any other word stays UNKNOWN.

## Coverage and honesty

- **A day with no row** for a restaurant is **UNKNOWN**, never approved and never not approved. (A restaurant with no rows at all is not listed unless you add it under "Only these locations".)
- **Two rows for the same restaurant and day** that disagree (different status, over/short or net sales) become **UNKNOWN and are listed as a conflict**. Identical duplicates are merged.
- **Partial list.** If the file states how many entries it holds (a "Total Records: N" or "Showing x of N" line above or below the table) and fewer rows were read, the report says **"Partial list"**.
- **Freshness.** Each report shows `Source: DSS export file "<name>", dated <when the file was saved>, read <when it was checked>.` A file dated **before today** cannot establish today's approval status, so approval is shown as **UNKNOWN** (with the word the file had) and the report says so plainly. A file that does not say when it was downloaded is treated the same way. Over/short is still checked from an older file. The file's date comes from the file's own "last modified" time, which the settings page reads from your browser; if that is unavailable the report says the date is not known.
- **Unreadable cells.** A date that cannot be read sets that row aside and counts it. An Over/Short or Net Sales value that is not a number is shown as UNKNOWN with a count. Negative numbers written `-23.50`, `(23.50)` or `23.50-` are all understood. A dash on its own is not guessed to be zero.
- **Each connection is separate**: its own file, its own freshness, its own source line.

## What is not in the export (so it is UNKNOWN or not checked)

These are **not** in the export and are not checked from it: **POS import status**, anything equivalent to **missing receipts**, **payment exceptions**, **R365's own balancing flag**, and **who approved it and when**. They appear under "Not checked: ... the DSS export file does not contain what they need". The "payments add up to sales" check also cannot run from this file.

## Safety

- **No network, no credentials, no browser automation.** The reader only handles bytes it is given.
- **Never changes the file you chose**, and keeps only a copy.
- **Formulas and macros are ignored.** Excel cells are read as their stored values; formulas are never calculated; macro-enabled files (`.xlsm`) and old `.xls` files are refused; XML tricks (a DOCTYPE or entity) are refused; a text cell starting with `=` is just text.
- **Size limits.** Files over 20 MB, spreadsheets that unpack to far more than a DSS list could, and files with an absurd number of rows are refused.
- **Nothing silent.** Rows that cannot be read are counted and reported, never dropped quietly.
- **Row contents are never written to a log** or the console. The report itself is the only output.

## What is not proven

- **No real R365 file is stored here.** The headings and formats come from the owner's notes; every test uses made-up files ("Sample ..." restaurants, invented amounts).
- **The sign of Over/Short is not proven.** The report therefore says "Over/Short is -$23.50 as R365 gives it (limit $5.00 either way)" and never calls it over or short until one known entry confirms the convention.
- **"In Progress" (beta) and "Unapproved" (classic) are not proven to be the same thing.** Only one matching pair has been seen. In Progress is treated as UNKNOWN unless you say what it means for a connection.
- **One beta row was missing from a file with no explanation.** Without a row count in the beta layout this cannot be detected automatically; that is why the optional expected total exists.
- **An unapproved day or a cash difference is not shown as the reason a DSS is unfinished.** The export says what the status and the number are, not why. It also does not show POS import health, receipt coverage, whether the books balance, or whether R365 would approve the day automatically.
- Date order: R365 US exports are read month/day/year; a column that proves day-first is read that way, and a genuinely ambiguous column produces a plain warning.
