# The guided first-run setup

Code: `dssreport/setup_wizard.py` (screens and checks), a few hook lines in `dssreport/settings_server.py`. Tests: `tests/test_setup_wizard.py`.

It opens by itself the first time (`python -m dssreport settings` with no connection saved) and any time from the "Start the guided setup" / "Run the guided setup again" link on the settings page. Plain words, large tap targets, one blue button per screen, and a "Your next step" box at the top of each screen.

| Screen | What it asks | What it does | Errors say what to do |
|---|---|---|---|
| 1 Your R365 | Name; start of the R365 web address (a label only: `samplegrill` from `samplegrill.restaurant365.net`; a pasted full address is cut down); a file or folder where the downloaded list is (or choose a file in the page); layout: classic, beta, or "not sure, find out for me" | Finds the newest real list in a folder (other files are ignored), reads it by heading name, keeps a copy in the program's folder, saves the connection. "Find out" uses `dss_inspect.layout_of` on the headings. A clear mismatch (said classic, headings are beta) is stopped; headings that show neither keep the person's answer. | empty/long/duplicate name, bad address, missing path, empty folder, folder without a list, a file that is not a list, licence limit |
| 2 Locations | Tick the places found in the file | Unticked places are saved as the connection's hide list. At least one must stay ticked. A posted name that is not in the file is ignored. | none ticked |
| 3 When | Build automatically (time, days) or only when "Run now" is pressed; prepare an email (off) and who to | Saves the schedule (Windows Task Scheduler on Windows only) and email settings; "send automatically" is never switched on here. Earlier schedule/email values are remembered so Undo can restore them. | no days, bad time, no address, bad address, features not in the licence |
| 4 Take a look | Demo, or my file | Builds the short report on screen (yesterday, as the morning run does). Nothing is emailed or saved as today's report. Places the file cannot settle appear under "Could not tell". The demo works with no connection and no licence. | nothing chosen |
| 5 All set | - | Summary, what happens next (when, the fresh file needed, email, read-only), and **Undo this setup** (removes the connection and its stored copy, restores schedule/email; the person's own file is never touched). | - |

A connection saved by the guide is a normal "R365 DSS export file" connection, so everything else in settings still applies. When it points at a folder or file, each report run first refreshes the program's copy from the newest list there (`dss_export_source.refresh_from_source_path`); if the folder is gone it quietly keeps the earlier copy and the report's own "file is old" wording applies.

Protections that still hold: every `/setup/...` page needs the per-run token, the Host and Origin checks, the same Content-Security-Policy (no scripts at all on these pages), `Cache-Control: no-store` and `X-Frame-Options: DENY`. No password is asked for or stored.

Not proven: the Windows schedule step on a real Windows computer; the layout detection beyond the two known heading rows; that the "start of the web address" matches a real tenant (it is only a label and nothing connects to it).
