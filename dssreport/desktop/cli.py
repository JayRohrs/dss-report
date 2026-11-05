"""Command line for the packaged program (dss-report.exe). Plain commands, plain messages.

  dss-report.exe status             show what is switched on
  dss-report.exe schedule on|off    switch the daily run on/off (creates/removes the Windows task)
  dss-report.exe daily-run          what Task Scheduler runs (does nothing if the schedule is off)
  dss-report.exe run-now            make yesterday's report now, whatever the switch says
  dss-report.exe draft on|off       switch the Microsoft 365 draft step on/off
  dss-report.exe draft-signin       sign in to Microsoft 365 (asks for draft permission only)
  dss-report.exe set KEY VALUE      change one setting (run_time, source, draft_to, graph_client_id ...)
  dss-report.exe log                show the run log
"""

import argparse
import dataclasses
import sys
import time
from typing import List, Optional

from ..errors import DssError
from . import daily, settings as st, taskcmd


def program_path() -> str:
    """The program Task Scheduler should start: the packaged exe."""
    if not getattr(sys, "frozen", False):
        raise DssError("The daily schedule is set up from the installed dss-report.exe "
                       "(see docs/BUILD_WINDOWS.md), not from the source code.")
    return sys.executable


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dss-report", description="DSS exception report (desktop)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sch = sub.add_parser("schedule")
    sch.add_argument("action", choices=["on", "off"])
    sub.add_parser("daily-run")
    sub.add_parser("run-now")
    dr = sub.add_parser("draft")
    dr.add_argument("action", choices=["on", "off"])
    sub.add_parser("draft-signin")
    se = sub.add_parser("set")
    se.add_argument("key")
    se.add_argument("value")
    sub.add_parser("log")
    return p


def _onoff(flag: bool) -> str:
    return "ON" if flag else "OFF"


def _status() -> int:
    s = st.load()
    print(f"Daily report schedule : {_onoff(s.daily_run_enabled)} (at {s.run_time})")
    print(f"Data source           : {s.source}")
    print(f"Draft email           : {_onoff(s.draft_email_enabled)}"
          + (f" (addressed to {s.draft_to}; never sent by this program)" if s.draft_email_enabled else ""))
    print(f"Settings file         : {st.settings_file()}")
    print(f"Run log               : {daily.log_file()}")
    return 0


def _set(key: str, value: str) -> int:
    s = st.load()
    fields = {f.name: f for f in dataclasses.fields(st.DesktopSettings)}
    if key not in fields:
        raise DssError(f"Unknown setting '{key}'. Choose from: " + ", ".join(sorted(fields)))
    if fields[key].type is bool:
        raise DssError(f"'{key}' is an on/off setting; use the 'schedule' or 'draft' commands.")
    setattr(s, key, value)
    st.save(s)
    print(f"{key} saved.")
    if key == "run_time" and s.daily_run_enabled:
        print(taskcmd.install(program_path(), s.run_time))
    return 0


def _draft_signin() -> int:
    from ..credstore import default_store
    from ..graph import GraphClient
    from .draftmail import sign_in_scopes
    s = st.load()
    client = GraphClient(default_store())
    dc = client.start_signin(s.graph_client_id, s.graph_tenant, sign_in_scopes())
    print(f"Open {dc.verification_uri} and enter the code {dc.user_code}.")
    print("Permission asked for: create drafts in your mailbox. This program cannot send mail.")
    while client.finish_signin(s.graph_client_id, s.graph_tenant, dc) == "pending":
        time.sleep(max(dc.interval, 1))
    print("Signed in.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            return _status()
        if args.command == "schedule":
            s = st.load()
            if args.action == "on":
                msg = taskcmd.install(program_path(), s.run_time)
                s.daily_run_enabled = True
            else:
                msg = taskcmd.remove()
                s.daily_run_enabled = False
            st.save(s)
            print(msg)
            return 0
        if args.command == "daily-run":
            return daily.daily_run(st.load())
        if args.command == "run-now":
            return daily.daily_run(st.load(), manual=True)
        if args.command == "draft":
            s = st.load()
            s.draft_email_enabled = args.action == "on"
            st.save(s)
            print(f"Draft email is now {_onoff(s.draft_email_enabled)}. Drafts are never sent by this program.")
            return 0
        if args.command == "draft-signin":
            return _draft_signin()
        if args.command == "set":
            return _set(args.key, args.value)
        if args.command == "log":
            p = daily.log_file()
            print(p.read_text(encoding="utf-8") if p.exists() else "The run log is empty so far.")
            return 0
    except DssError as exc:
        print(f"Problem: {exc}", file=sys.stderr)
        return 2
    return 0
