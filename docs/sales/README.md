# Morning DSS Check — start here

This folder is for someone seeing the tool for the first time.

| File | Read it when |
|---|---|
| [SELL_SHEET.md](SELL_SHEET.md) | You want the one-page summary to hand over |
| [DEMO_SCRIPT.md](DEMO_SCRIPT.md) | You are about to show it live (two minutes, word for word) |
| [OWNER_FAQ.md](OWNER_FAQ.md) | An owner asks about privacy, passwords or updates |

## What it is

Every morning, you download the Daily Sales Summary list from Restaurant365 and give the file to this tool. It shows you only the days still unapproved, with the likely reason beside each. If everything is approved it says "Nothing outstanding to approve."

It only reads. It never approves anything, never signs in to R365 and never changes the file you give it.

## Try it in five minutes with invented data

You need Python 3.11 or newer.

```bash
python -m dssreport demo-export --out samples/
```

This writes made-up Daily Sales Summary files into a folder called `samples`.

```bash
python -m dssreport settings
```

This opens the settings page in your browser. Then:

1. Add a connection and choose **R365 DSS export file**. Tick **Use this connection** and save. This needs a licence file from Jay Rohrs, loaded under **Licence**.
2. Under **Check a DSS export**, press **Choose file** and pick `sample-dss-classic.csv` from the `samples` folder.
3. Press **Check DSS export now**. The report opens.

No licence yet? Look at a built-in demo report instead (it has no connection to any file):

```bash
python -m dssreport run --input demo --out out/
```

Then open `out/report.html`.

## Using it for real

1. In R365, open the Daily Sales Summary list and click the Excel icon at the top right, with nothing ticked. Save the file.
2. Choose it in settings and press **Check DSS export now**. Download a **fresh** file each morning; a file older than today cannot show today's approval status.

## What the words mean

| You see | It means |
|---|---|
| **Ready to approve** | The day is not approved and the file flags nothing else. A person still approves it in R365. |
| **Needs to balance: Over/Short -$23.50** | The day is not approved and the file shows a cash difference. The number is exactly as R365 gives it, flagged when the amount is above $5.00 either way. What its sign means is not yet confirmed. |
| **Could not tell** | The status is blank, unclear, contradictory, missing for that day, or the file is old. The reason is written beside it. It is never counted as approved. |
| **Partial list** | The file says it holds more entries than were read. Some days may be missing. |
| **Nothing outstanding to approve.** | Everything in the file is approved. |

Every reason is "likely", never proven.

## If something looks wrong

- **"This file is dated ... older than today"**: download the list again.
- **"This file has no ... column"**: the message says which check could not run. The inspect command prints the file's headings, with no names or amounts: `python -m dssreport export inspect <your file>`.
- **"In Progress" shown as Could not tell**: R365's newer list uses it. Check one known day in R365; if it means not approved, you can say so for that connection in settings.

## What it cannot do yet

See the last section of [SELL_SHEET.md](SELL_SHEET.md). The longer technical story is in [../EXPORT_SOURCE.md](../EXPORT_SOURCE.md) and [../R365_OPEN_QUESTIONS.md](../R365_OPEN_QUESTIONS.md).
