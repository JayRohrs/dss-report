# Building the Windows program and installer

For whoever builds the release (Jay). Owners do not need this; they use the installer
([INSTALL_WINDOWS_OWNER.md](INSTALL_WINDOWS_OWNER.md)).

## What you get

| File | What it is |
|---|---|
| `dist\dss-report.exe` | The whole program in **one file**, Python included. Portable: copy it anywhere and run it. |
| `dist\installer\DSS-Report-Setup-<version>.exe` | One-file installer wrapping the exe. Per-user, no administrator rights, Start-menu entries, optional daily schedule. |

## Build command

On a Windows computer with [Python 3.11+](https://www.python.org/downloads/) (and, for the installer,
[Inno Setup 6](https://jrsoftware.org/isinfo.php): `winget install JRSoftware.InnoSetup`), from the repository folder:

```
packaging\build_windows.cmd
```

It does exactly this (you can run the lines yourself):

```
python -m venv .venv-build
.venv-build\Scripts\activate.bat
python -m pip install -r packaging\requirements-build.txt
python -m PyInstaller --noconfirm --clean packaging\dss-report.spec
iscc /DAppVersion=0.3.0 packaging\installer.iss
```

Tools (all widely used and open): **PyInstaller 6.11.1** (pinned in `packaging\requirements-build.txt`) for the
single exe and **Inno Setup 6** for the installer. If Inno Setup is not installed the script still produces the
portable exe and says so.

## Files

* `packaging\entry.py` - starts `dssreport.desktop.cli`.
* `packaging\dss-report.spec` - PyInstaller spec (bundles `dssreport\data` and `rules.toml`).
* `packaging\installer.iss` - Inno Setup script. The "make the report every morning" tick is **unticked by default**.
* `packaging\shortcuts\*.cmd` - the Start-menu ON / OFF / status / run-now / log shortcuts.

## Commands the exe understands

```
dss-report.exe status            what is switched on (everything optional starts OFF)
dss-report.exe schedule on|off   daily run on/off: creates or removes the Windows scheduled task
dss-report.exe daily-run         what the scheduled task runs; does nothing if the schedule is off
dss-report.exe run-now           make yesterday's report now, whatever the switch says
dss-report.exe draft on|off      Microsoft 365 draft step on/off (see GRAPH_PERMISSIONS.md)
dss-report.exe draft-signin      sign in to Microsoft 365 (draft permission only)
dss-report.exe set KEY VALUE     run_time, source, draft_to, graph_client_id, graph_tenant
dss-report.exe log               print the run log
```

Settings live in `%LOCALAPPDATA%\DssReport\desktop_settings.json`; the run log is
`%LOCALAPPDATA%\DssReport\daily-run.log`; reports are in `%LOCALAPPDATA%\DssReport\reports\<date>\`.

## The one-line schedule setup command

`dss-report.exe schedule on` runs this for you (Task Scheduler, as the signed-in user, no admin rights):

```
schtasks /Create /TN "DSS Report Daily" /SC DAILY /ST 07:00 /TR "\"C:\Users\<you>\AppData\Local\DssReport\dss-report.exe\" daily-run" /RL LIMITED /F
```

`schedule off` runs `schtasks /Delete /TN "DSS Report Daily" /F`. The uninstaller also removes the task.

Known limits: if the computer is off at the chosen time, that day's run is skipped (use "Make yesterday's report
now"); a console window flashes briefly while the scheduled run works.

## What has and has not been checked

* Checked (automated tests, any OS): command construction, settings defaults, the daily run, the draft-only guarantee.
* Checked on Linux only: the PyInstaller spec builds a single-file program that runs `status` and a demo run.
* **Not yet run on Windows:** the `.exe` build, the Inno Setup installer, the real Task Scheduler task and a real
  Microsoft 365 draft. Please try the installer on a clean Windows desktop before release. The exe is unsigned, so
  Windows SmartScreen will warn; code signing is not set up.

Made-up data only: nothing here uses a real tenant, account or credential.
