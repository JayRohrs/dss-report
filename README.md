Start the morning knowing which locations need a look. Every day, a reviewer opens the daily sales summaries and hunts for what's wrong. This tool does that first pass for you. It reads the day's data and flags missing POS imports, cash over or short, missing receipts, payment exceptions and unapproved entries. You get a short report in plain English, readable on your phone.

- **Honest about gaps** (missing data is shown as UNKNOWN, never "all clean")
- **Yours to control** (the review rules are in one readable file you can edit)
- **Private by design** (runs on your own computer, your data never leaves it)
- **Optional local AI** (a plain-language summary sentence is available, and the report is fully correct without it)

Setup and support are available separately.

All rights reserved — Jay Rohrs.

All restaurants, figures and names in this repository are made up demo data.

![Demo report on a phone](docs/screenshots/demo-report-390px.png)

Desktop view: [docs/screenshots/demo-report-1366px.png](docs/screenshots/demo-report-1366px.png)

## What it does not do

- It does not fix anything, post anything or change any data. It only reads and reports.
- It does not decide what is right. It applies the simple rules in `rules.toml` and shows its reasons.
- It does not connect to any accounting or POS system out of the box. It reads CSV or JSON files. A reviewer can have an adapter written for their own system (see [docs/ADAPTERS.md](docs/ADAPTERS.md)).
- It does not email the report. It writes a plain-text email body you can paste or send yourself.
- It does not check that the figures themselves are correct, only whether they trip a rule or are missing.

## Run the demo in 5 minutes

You need Python 3.11 or newer (nothing else to install).

1. Download or clone this folder and open a terminal in it.
2. Run: `python -m dssreport run --input demo --out out/`
3. Open `out/report.html` in your browser. The plain-text email is `out/email.txt`.

The demo has 3 made-up restaurants and 14 days of data with a few planted problems. By default the report covers the latest day. To see more of the planted problems, including a day with no data (shown as UNKNOWN):

`python -m dssreport run --input demo --out out/ --days 14`

Other options: `--date 2026-03-12` picks the last day to check; `--rules my-rules.toml` uses another rules file.

### Using your own data

Put a CSV or JSON file in a folder **outside this repository**, then run `python -m dssreport run --input /path/to/file.csv --out out/`. The columns are listed in [docs/ADAPTERS.md](docs/ADAPTERS.md) and an example is in `examples/demo/`. Blank means "not known" and is reported as UNKNOWN, never as zero.

### Changing the rules

Open `rules.toml` in any text editor. Change the cash limit, switch a rule off, or list locations that must report. A mistyped setting stops the run with a clear message instead of being ignored. A location with no data, or a blank value, is always shown as UNKNOWN. That cannot be switched off.

### Optional local summary sentence

Off by default. To use it, run a local model server that speaks the Ollama-style API on this computer, set `enabled = true` and the model name in the `[ai]` section of `rules.toml` (or add `--ai`). The model gets only counts and location names. Its sentence is checked against the computed facts (numbers, which locations, whether data is missing); if it disagrees, or the model is not running, a standard sentence is used and the report says so. Only `localhost` addresses are accepted.

### Running the tests

`python -m unittest` (49 tests, no extra software).

## Where your data stays

On your computer. The tool makes no network calls, has no analytics or tracking, and sends nothing anywhere. The only exception is the optional summary, which talks to a model server on the same computer. Reports are written to the folder you choose (`out/` by default, which is ignored by git).

## Security

See [SECURITY.md](SECURITY.md). **Never commit real data to this repository.** The `.gitignore` blocks common data files, but keep real files outside the repository to be safe.
