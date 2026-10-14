import argparse
import sys
from datetime import date

from . import __version__
from .adapters.demo import write_demo_files
from .errors import DssError
from .runner import run_report


def _parse_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a date like 2026-03-13")


def _parser():
    p = argparse.ArgumentParser(prog="python -m dssreport",
                                description="Morning exception report for daily sales summaries.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="build the report")
    run.add_argument("--input", required=True,
                     help="'r365' (read-only, from your settings), 'demo', or a .csv/.json file/folder (demo and trials)")
    run.add_argument("--out", required=True, help="folder to write report.html and email.txt into")
    run.add_argument("--date", type=_parse_date, help="last business date to check (demo/files: latest in the data; r365: yesterday)")
    run.add_argument("--full", action="store_true", help="write the long report instead of the brief one")
    run.add_argument("--days", type=int, default=1, help="how many days to check, ending on --date (default 1)")
    run.add_argument("--rules", help="rules file (default: see README)")
    run.add_argument("--ai", action="store_true", help="ask the local model for a summary sentence")
    run.add_argument("--email", action="store_true", help="also create the email in Microsoft 365 (uses your settings)")
    sub.add_parser("settings", help="open the settings screen in your browser")
    sub.add_parser("scheduled-run", help="what the schedule runs (does nothing if not due)")
    sub.add_parser("run-now", help="run the R365 report for yesterday now and open it")
    sub.add_parser("forget-secrets", help="remove the saved R365 password and Microsoft 365 sign-in from this computer")
    upd = sub.add_parser("update", help="install an update file you were sent (checked here; nothing goes online)")
    upd.add_argument("action", choices=["install", "rollback", "status", "check", "download"],
                     help="check/download use the OPTIONAL online update list (off unless switched on in settings)")
    upd.add_argument("file", nargs="?", help="install: the update file; download: the version to fetch")
    sch = sub.add_parser("schedule", help="turn the Windows schedule on or off")
    sch.add_argument("action", choices=["install", "remove"])
    r365 = sub.add_parser("r365", help="read-only helpers for the R365 connection")
    r365.add_argument("action", choices=["test", "discover"],
                      help="test = check the sign-in; discover = list the entities and fields your tenant offers")
    r365.add_argument("--instance", help="the connection's name (default: the first one)")
    ex = sub.add_parser("export", help="the DSS export file source (read-only; nothing leaves this computer)")
    ex.add_argument("action", choices=["load", "inspect"],
                    help="load = keep a copy of a DSS list file you downloaded from R365; "
                         "inspect = describe a file (headings, counts, formats; no names or amounts) so it can be pasted safely")
    ex.add_argument("file")
    ex.add_argument("--instance", help="the connection's name (default: the first DSS export connection)")
    ex.add_argument("--expected-total", type=int, help="the total R365 shows on screen (\"... of N items\"), to notice a partial file")
    dx = sub.add_parser("demo-export", help="write made-up sample DSS list files (CSV, TSV, Excel) to try the export source")
    dx.add_argument("--out", required=True, help="folder to write into")
    demo = sub.add_parser("demo-data", help="write the made-up demo data as CSV and JSON files")
    demo.add_argument("--out", required=True, help="folder to write into")
    return p


def _run(args) -> int:
    result = run_report(args.input, args.out, end=args.date, days=args.days,
                        rules_path=args.rules, ai=args.ai, email=args.email,
                        style="full" if args.full else "brief")
    for note in result.notes:
        print(note, file=sys.stderr)
    print(result.report.headline)
    print(f"Wrote {result.html_path} and {result.text_path}")
    if result.email_outcome:
        print(result.email_outcome)
    return 0


def _run_now() -> int:
    from datetime import timedelta
    from .paths import reports_dir
    from .settings_server import serve
    from .state import load_state, save_state
    day = date.today() - timedelta(days=1)
    # No email is created here: the person looks at the report first, then chooses (see the page).
    result = run_report("r365", reports_dir() / day.isoformat(), end=day, email=False)
    for note in result.notes:
        print(note, file=sys.stderr)
    print(result.report.headline)
    state = load_state()
    state["last_report_dir"] = str(result.html_path.parent)
    save_state(state)
    return serve(path="/report")


def _update(args) -> int:
    from . import __release_date__, __version__
    from . import licence as lic
    from . import updates
    if args.action == "status":
        s = lic.current_status()
        print(f"Installed version {__version__} (released {__release_date__}).")
        print(s.message)
        if s.licence:
            print(f"Updates: {s.licence.updates_text()}.")
        print("An earlier version is saved and can be restored." if updates.has_backup() else "No earlier version is saved.")
    elif args.action in ("check", "download"):
        from . import update_check
        from .settings import load_settings
        s = load_settings()
        if not s.update_check_enabled:
            raise updates.UpdateError("Online update checking is switched off. Switch it on in settings first.")
        found = update_check.check(s.update_manifest_url, __version__)
        if args.action == "check":
            print("\n".join(f"Version {a.version} (released {a.release_date.isoformat()}) {a.notes}".rstrip() for a in found)
                  or "You have the newest version that is listed.")
        else:
            entry = next((a for a in found if a.version == args.file), None)
            if entry is None:
                raise updates.UpdateError("Say which listed version to download, for example: update download 0.4.0")
            path = update_check.download(s.update_manifest_url, entry, lic.current_status())
            print(f"Downloaded and checked: {path}. Install it with: update install \"{path}\"")
    elif args.action == "rollback":
        print(updates.rollback())
    else:
        if not args.file:
            raise updates.UpdateError("Say which update file to install, for example: update install my-update.dssupdate")
        print(updates.apply_update(args.file, lic.current_status()))
    return 0


def _export(args) -> int:
    if args.action == "inspect":
        from pathlib import Path as _Q
        from .dss_inspect import inspect
        from .errors import InputError as _IE
        f = _Q(args.file)
        if not f.is_file():
            raise _IE("That is not a file.")
        print(inspect(f.read_bytes(), f.name), end="")
        return 0
    from pathlib import Path as _P
    import os as _os
    from .dss_export_source import KIND, store_export
    from .errors import InputError
    from .settings import load_settings
    s = load_settings()
    pool = [i for i in s.instances if i.source_kind == KIND]
    wanted = (args.instance or "").strip().lower()
    inst = next((i for i in pool if not wanted or wanted in (i.name.lower(), i.id)), None)
    if inst is None:
        raise InputError("There is no DSS export connection" + (f" called '{args.instance}'" if args.instance else "")
                         + ". Add one in settings (source: R365 DSS export file).")
    src = _P(args.file)
    if not src.is_file():
        raise InputError("That is not a file.")
    data = src.read_bytes()                                  # read only: the file is never changed
    meta = store_export(inst, src.name, data, _os.stat(src).st_mtime, expected_total=args.expected_total)
    print(f"Kept a copy of {meta['original_name']} for {inst.name}: {meta['rows']} rows. "
          "Now run: python -m dssreport run --input r365 --out out/")
    return 0


def _forget() -> int:
    from .credstore import default_store
    from .graph import SESSION_KEY
    from .settings import load_settings
    store, s = default_store(), load_settings()
    for inst in s.instances:
        store.delete(inst.credential_key)
    store.delete(SESSION_KEY)
    print("Saved passwords and sign-ins were removed from this computer.")
    return 0


def _r365(args) -> int:
    from .credstore import default_store
    from .errors import InputError
    from .settings import load_settings
    from .sources import build_source
    settings = load_settings()
    if not settings.instances:
        raise InputError("No R365 connection is set up yet. Open settings and add one.")
    wanted = (args.instance or "").strip().lower()
    inst = next((i for i in settings.instances if not wanted or wanted in (i.name.lower(), i.id)), None)
    if inst is None:
        raise InputError(f"There is no connection called '{args.instance}'. "
                         f"You have: {', '.join(i.name for i in settings.instances)}.")
    source = build_source(inst, default_store())
    if args.action == "test":
        print(f"{inst.name}: {source.check_connection()}")
    else:
        print("\n".join(source.describe()))
    return 0


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "demo-data":
            for path in write_demo_files(args.out):
                print(f"Wrote {path}")
            return 0
        if args.command == "r365":
            return _r365(args)
        if args.command == "demo-export":
            from .dss_export_sample import write_samples
            for path in write_samples(args.out):
                print(f"Wrote {path}")
            print("Make a connection with the source 'R365 DSS export file' in settings, choose one of these, and press "
                  "'Check DSS export now'. Dates are relative to today, so they are fresh now and go stale tomorrow.")
            return 0
        if args.command == "export":
            return _export(args)
        if args.command == "settings":
            from .settings_server import serve
            return serve()
        if args.command == "scheduled-run":
            from .scheduler import scheduled_run
            from .settings import load_settings
            print(scheduled_run(load_settings()))
            return 0
        if args.command == "update":
            return _update(args)
        if args.command == "run-now":
            return _run_now()
        if args.command == "forget-secrets":
            return _forget()
        if args.command == "schedule":
            from . import scheduler
            from .settings import load_settings
            print(scheduler.install_task(load_settings()) if args.action == "install"
                  else scheduler.remove_task())
            return 0
        return _run(args)
    except DssError as exc:
        print(f"Problem: {exc}", file=sys.stderr)
        return 2
