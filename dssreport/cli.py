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
    run.add_argument("--days", type=int, default=1, help="how many days to check, ending on --date (default 1)")
    run.add_argument("--rules", help="rules file (default: see README)")
    run.add_argument("--ai", action="store_true", help="ask the local model for a summary sentence")
    run.add_argument("--email", action="store_true", help="also create the email in Microsoft 365 (uses your settings)")
    sub.add_parser("settings", help="open the settings screen in your browser")
    sub.add_parser("scheduled-run", help="what the schedule runs (does nothing if not due)")
    sub.add_parser("run-now", help="run the R365 report for yesterday now and open it")
    sub.add_parser("forget-secrets", help="remove the saved R365 password and Microsoft 365 sign-in from this computer")
    sch = sub.add_parser("schedule", help="turn the Windows schedule on or off")
    sch.add_argument("action", choices=["install", "remove"])
    r365 = sub.add_parser("r365", help="read-only helpers for the R365 connection")
    r365.add_argument("action", choices=["test", "discover"],
                      help="test = check the sign-in; discover = list the entities and fields your tenant offers")
    demo = sub.add_parser("demo-data", help="write the made-up demo data as CSV and JSON files")
    demo.add_argument("--out", required=True, help="folder to write into")
    return p


def _run(args) -> int:
    result = run_report(args.input, args.out, end=args.date, days=args.days,
                        rules_path=args.rules, ai=args.ai, email=args.email)
    for note in result.notes:
        print(note, file=sys.stderr)
    print(result.report.headline)
    print(f"Wrote {result.html_path} and {result.text_path}")
    if result.email_outcome:
        print(result.email_outcome)
    return 0


def _run_now() -> int:
    import webbrowser
    from datetime import timedelta
    from .paths import reports_dir
    from .settings import load_settings
    day = date.today() - timedelta(days=1)
    result = run_report("r365", reports_dir() / day.isoformat(), end=day,
                        email=load_settings().email_enabled)
    for note in result.notes:
        print(note, file=sys.stderr)
    print(result.report.headline)
    if result.email_outcome:
        print(result.email_outcome)
    webbrowser.open(result.html_path.as_uri())
    return 0


def _forget() -> int:
    from .credstore import default_store
    from .graph import SESSION_KEY
    from .r365 import credential_name
    from .settings import load_settings
    store, s = default_store(), load_settings()
    if s.r365_username:
        store.delete(credential_name(s.r365_username))
    store.delete(SESSION_KEY)
    print("Saved passwords and sign-ins were removed from this computer.")
    return 0


def _r365(args) -> int:
    from .credstore import default_store
    from .r365 import check_connection, discover
    from .settings import load_settings
    settings, store = load_settings(), default_store()
    if args.action == "test":
        print(check_connection(settings, store))
    else:
        print("\n".join(discover(settings, store)))
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
        if args.command == "settings":
            from .settings_server import serve
            return serve()
        if args.command == "scheduled-run":
            from .scheduler import scheduled_run
            from .settings import load_settings
            print(scheduled_run(load_settings()))
            return 0
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
