# Two-minute live demo — word for word

Aim: the owner sees, in two minutes, one real-looking morning list, one honest "Could not tell", and hears what the tool will never do. Everything on screen is invented.

## Before you start (do this the same morning, about five minutes)

Sample files go stale at midnight, because the tool refuses to treat an old file as today's. So make them fresh.

```bash
python -m dssreport demo-export --out samples/
```

1. Open settings (`python -m dssreport settings`). Make sure one connection called "Sample Group A", of kind "R365 DSS export file", is ticked "Use this connection". A licence file must be loaded, or the connection will not run. Licence for demonstrations: **UNKNOWN** (confirm yours is loaded before the meeting).
2. Have the `samples` folder open in a second window, with `sample-dss-classic.csv` and `sample-dss-beta-style.csv` visible.
3. Do one dry run. Then reset by choosing the classic file again.

The wording on screen below was copied from the build of 2026-11-02. If the report wording has changed since, read your own screen and keep the meaning.

## The script

| Time | On screen | You say |
|---|---|---|
| 0:00 – 0:15 | The `samples` folder with the two files. | "Every morning someone opens each restaurant's Daily Sales Summary and hunts for what is still unapproved. This does that first look for you. This is the list you already download from Restaurant365. These files are invented." |
| 0:15 – 0:35 | Settings page, section "Check a DSS export". Press **Choose file**, pick `sample-dss-classic.csv`. | "No password, no sign-in to R365. You choose the file you downloaded. That is all it ever sees." |
| 0:35 – 0:50 | Press **Check DSS export now**. The report opens. | "One press." |
| 0:50 – 1:15 | The report. Point at the line: **Sample Hill Bistro — Needs to balance: Over/Short -$23.50**. | "One restaurant is still unapproved, and the likely reason is on the same line: the cash difference. It says 'likely' because the file cannot tell us why, only what it shows. The number is exactly as Restaurant365 gives it. It is flagged because the amount is above five dollars either way. What the sign means we have not yet confirmed, so it shows the number and does not claim a direction." |
| 1:15 – 1:35 | Point at **Could not tell: Sample Park Diner — No data for this day**. | "This is the part I care about most. One restaurant has no row for the day. It does not say 'fine'. It says 'Could not tell'. If it does not know, it says so." |
| 1:35 – 1:50 | Go back to Choose file, pick `sample-dss-beta-style.csv`, press Check. The list shows several "Could not tell" lines with the plain-words status note. | "Restaurant365's newer list says 'In Progress' where the old one said 'Unapproved'. We have not yet proven those mean the same thing, so it lists them as 'Could not tell' instead of guessing. You decide, once, after checking a real day." |
| 1:50 – 2:00 | The foot of the report: "Likely reasons only, taken from the export. Nothing was approved or sent." | "And it never approves anything and never changes Restaurant365. It reads a file and writes a page. Questions?" |

## If something goes wrong

| What happens | What to say or do |
|---|---|
| "File is older than today" appears | "That is the tool refusing to treat an old file as today's. Good." Make the samples again and choose the file again. |
| The report shows different restaurants or amounts | Say nothing about it; the samples are invented and wording may differ. Read what is on screen. |
| The settings page will not open | Open `report.html` from a demo run instead: `python -m dssreport run --input demo --out out/`. Do not read out its Over/Short wording: it states a direction, and what the sign means in real files is not yet confirmed. |
| Asked "does it work on our real data?" | "It has been tested on invented files that follow the layouts we have seen. A first check on your real download is the next step, and I would want you in the room for it." |

## Do not say

- Any amount of time or money saved, or any price. All are **UNKNOWN**.
- That Restaurant365 supports or endorses it.
- That it has been tested on anyone's real data, or on a Windows computer, or with a real email account. It has not.
- That it can approve, fix or post anything. It cannot.
- That a cash difference is the reason a day is unapproved. It is only a likely reason.
