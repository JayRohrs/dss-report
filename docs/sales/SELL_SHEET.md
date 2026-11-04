# Morning DSS Check — one page

**What it does, in one sentence:** every morning it reads the Daily Sales Summary list you already download from Restaurant365 and tells you, in a few lines, which days are still unapproved and the likely reason.

## Who it is for

Accounting managers who review Daily Sales Summaries (DSS) for several restaurants in Restaurant365, and the owners of those groups who want to know every day is being looked at.

## What you feel in the first week

1. **A short list instead of a hunt.** You open one page that lists only the days still unapproved. When everything is approved it says exactly that: "Nothing outstanding to approve."
2. **The cash difference sits next to the day.** An unapproved day with a cash difference says so on the same line ("Needs to balance: Over/Short -$23.50"). A day with nothing flagged says "Ready to approve".
3. **Gaps are shown, not buried.** A restaurant with no row for the day, a file that is old, or a list that looks cut short is called out in plain words, so a quiet page never means "nobody looked".

Time saved: **UNKNOWN** (not measured; no figure is claimed).

## How it stays honest

- **"Could not tell" instead of guessing.** If a day's status is blank, unclear or contradicts itself, the day is listed under "Could not tell" with the reason. It is never counted as approved and never hidden.
- **It never approves anything.** There is no approve button and no automatic approval.
- **It never touches Restaurant365.** It only reads a file you downloaded. It does not sign in to R365, does not change a record, and does not change the file you gave it.
- **Reasons are "likely", not proven.** The export cannot say why a day is unfinished, so the report never states a cause as fact.

## What it needs

- A Windows computer for the reviewer (the installer fetches Python if it is missing).
- Someone in R365 who can download the Daily Sales Summary list (the Excel icon on the list).
- A fresh download each morning. A file older than today cannot show today's approval status, and the report says so.
- A licence file from Jay Rohrs.

## What it does not do yet

- It does not download the file for you. You save it and choose it.
- It does not show POS import status, missing receipts, payment exceptions, whether R365 thinks the books balance, or who approved a day. The export does not carry them.
- It has been tested only on **invented** files. A first check against a real export is still to be done.
- R365's newer list says "In Progress" where the older one says "Unapproved". Until checked on a real day, it is shown as "Could not tell".
- What the sign of the Over/Short number means in R365 is not yet confirmed, so it is shown exactly as given and flagged when the amount is above $5.00 either way.
- The Windows installer, schedule and email draft are written but not yet run on a real Windows computer or Microsoft account.

## Price, savings, results

| | |
|---|---|
| Price | **UNKNOWN** |
| Savings | **UNKNOWN** |
| Return on investment | **UNKNOWN** |
| Customer references | **None** |
| Support terms | **UNKNOWN** |

*An independent tool for Restaurant365 users. Not made, endorsed or supported by Restaurant365. Everything shown in demonstrations is invented. All rights reserved — Jay Rohrs.*
