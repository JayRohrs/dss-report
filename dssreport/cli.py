import argparse
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .adapters import build_adapter
from .adapters.demo import write_demo_files
from .config import Config, load_config
from .errors import DssError, InputError
from .render import render_html, render_text
from .report import build_report
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
                     help="'demo', a .csv/.json file, or a folder of them")
    run.add_argument("--out", required=True, help="folder to write report.html and email.txt into")
    run.add_argument("--date", type=_parse_date, help="last business date to check (default: latest in the data)")
    run.add_argument("--days", type=int, default=1, help="how many days to check, ending on --date (default 1)")
    run.add_argument("--rules", default="rules.toml", help="rules file (default rules.toml)")
    run.add_argument("--ai", action="store_true", help="ask the local model for a summary sentence")
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
    adapter = build_adapter(args.input)
    records = adapter.load()
    for w in adapter.warnings:
        print(f"Warning: {w}", file=sys.stderr)
    report = build_report(records, cfg, end=args.date, days=args.days, source_name=adapter.name,
                          unmapped=frozenset(adapter.unmapped))
    if args.ai or cfg.ai_enabled:
        note = add_summary(report, cfg)
        if note:
            print(f"Note: {note}", file=sys.stderr)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(render_html(report), encoding="utf-8")
    (out / "email.txt").write_text(render_text(report), encoding="utf-8")
    print(report.headline)
    print(f"Wrote {out / 'report.html'} and {out / 'email.txt'}")
    return 0


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "demo-data":
            for path in write_demo_files(args.out):
                print(f"Wrote {path}")
            return 0
        return _run(args)
    except DssError as exc:
        print(f"Problem: {exc}", file=sys.stderr)
        return 2
