import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from . import __version__
from .adapters import build_adapter
from .adapters.demo import write_demo_files
from .config import Config, load_config
from .errors import DssError, InputError
from .render import render_html, render_text
from .report import build_report
from .state import known_locations, load_state, remember_locations, save_state
from .summary import add_summary


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
                     help="'r365' (read-only, from your R365 settings), 'demo', or a .csv/.json file/folder (demo and trials)")
    run.add_argument("--out", required=True, help="folder to write report.html and email.txt into")
    run.add_argument("--date", type=_parse_date, help="last business date to check (default: latest in the data)")
    run.add_argument("--days", type=int, default=1, help="how many days to check, ending on --date (default 1)")
    run.add_argument("--rules", default="rules.toml", help="rules file (default rules.toml)")
    run.add_argument("--ai", action="store_true", help="ask the local model for a summary sentence")
    r365 = sub.add_parser("r365", help="read-only helpers for the R365 connection")
    r365.add_argument("action", choices=["test", "discover"],
                      help="test = check the sign-in; discover = list the entities and fields your tenant offers")
    demo = sub.add_parser("demo-data", help="write the made-up demo data as CSV and JSON files")
    demo.add_argument("--out", required=True, help="folder to write into")
    return p


def _run(args) -> int:
    rules = Path(args.rules)
    if rules.exists() or args.rules != "rules.toml":
        cfg = load_config(rules)
    else:
        print("Note: rules.toml not found here, using built-in default rules.", file=sys.stderr)
        cfg = Config()
    adapter = build_adapter(args.input, cfg)
    end = args.date
    if adapter.needs_window:
        # From a live source we always ask for an explicit day (yesterday by default),
        # so a missing latest day shows up as UNKNOWN instead of quietly shifting the window.
        end = end or date.today() - timedelta(days=1)
        adapter.set_window(end - timedelta(days=max(args.days, 1) - 1), end)
    records = adapter.load()
    state = None
    if adapter.needs_window:
        # A location that sent nothing at all can't be seen in the data. Remember the ones
        # we have seen before so a silent location shows up as UNKNOWN instead of vanishing.
        state = load_state()
        cfg.expected = sorted(set(cfg.expected) | set(known_locations(state)))
    for w in adapter.warnings:
        print(f"Warning: {w}", file=sys.stderr)
    report = build_report(records, cfg, end=end, days=args.days, source_name=adapter.name,
                          unmapped=frozenset(adapter.unmapped))
    if args.ai or cfg.ai_enabled:
        note = add_summary(report, cfg)
        if note:
            print(f"Note: {note}", file=sys.stderr)
    if state is not None:
        remember_locations(state, {r.location for r in records})
        save_state(state)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(render_html(report), encoding="utf-8")
    (out / "email.txt").write_text(render_text(report), encoding="utf-8")
    print(report.headline)
    print(f"Wrote {out / 'report.html'} and {out / 'email.txt'}")
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
        if args.command == "r365":
            return _r365(args)
        if args.command == "demo-data":
            for path in write_demo_files(args.out):
                print(f"Wrote {path}")
            return 0
        return _run(args)
    except DssError as exc:
        print(f"Problem: {exc}", file=sys.stderr)
        return 2
