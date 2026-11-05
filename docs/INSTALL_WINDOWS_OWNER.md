# Installing the DSS morning report on your Windows computer

This is for a restaurant owner on a Windows desktop. No technical knowledge is needed. It takes about 5 minutes.

**What it does:** it reads your Daily Sales Summary information and makes a short report of what needs a look.
It runs on your own computer. **It never sends an email by itself.** Everything optional is **off** until you switch it on.

## 1. Install

1. Double-click **DSS-Report-Setup** (the file you were sent).
2. If Windows says "Windows protected your PC", click **More info**, then **Run anyway**. This appears because the
   program is new and not yet "signed"; it is normal for this first version.
3. Click **Next** through the screens. There is one tick-box: *"Make the report every morning at 07:00"*.
   It starts **unticked**. Tick it only if you want the morning report now; you can switch it on or off later.
4. Click **Install**, then **Finish**. You do not need an administrator or a password.

## 2. See your first report

Open the **Start** menu, find **DSS Report**, and click **Make yesterday's report now**. A black window shows
what happened and where the report is saved. The report is in the folder
`C:\Users\<your name>\AppData\Local\DssReport\reports\` (a folder for each day; open **report.html**).

At first it uses **made-up demo data**, so you can see what the report looks like. Setup help for using your own
Restaurant365 file is available separately.

## 3. The morning schedule (optional)

In the Start menu, under **DSS Report**:

* **Daily report - turn ON** - makes the report every morning at 07:00 (if the computer is on).
* **Daily report - turn OFF** - stops it.
* **Daily report - what is on?** - shows ON or OFF for the schedule and for the email draft.

The black window always tells you the current setting. If the computer is off at 07:00 that morning's report
is skipped; use **Make yesterday's report now** when you sit down.

## 4. The log

**Open the run log** (Start menu, **DSS Report**) shows one line each time the program ran, skipped, or hit a
problem, for example `ran for 2026-11-02: ...` or `skipped: the daily run is switched off`.
The file is `C:\Users\<your name>\AppData\Local\DssReport\daily-run.log`; you can open it in Notepad.

## 5. Email draft (optional, off, never sent)

If you want the report waiting in your Outlook **Drafts** folder each morning, someone needs to set up the
Microsoft 365 connection once (instructions: GRAPH_PERMISSIONS.md). Even then, the program only **creates a draft**.
You read it and press Send yourself. It cannot send for you.

## 6. Removing it

Windows **Settings > Apps > Installed apps > DSS Report > Uninstall**. This also removes the morning schedule.
Your saved reports and settings stay in the folder above until you delete that folder.

## If something goes wrong

Open the run log and read the last line; it says in plain words what happened. If the report says something is
**UNKNOWN**, it means the information was missing, not that everything is fine.

*All restaurants and figures in the demo are made up. This is an independent tool for Restaurant365 users and is
not made or endorsed by Restaurant365.*
