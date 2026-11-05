"""The daily run: build yesterday's report, write a log line, and (only if switched on) leave a draft.

Nothing here sends email. The optional draft step goes through draftmail.DraftMailer, which can only
create a draft in the person's Microsoft 365 Drafts folder.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from ..errors import DssError
from ..paths import app_dir, reports_dir
from .settings import DesktopSettings

LOG_NAME = "daily-run.log"
STATE_NAME = "daily-state.json"


def log_file() -> Path:
    return app_dir() / LOG_NAME


def log(message: str, now: Optional[datetime] = None) -> None:
    now = now or datetime.now()
    p = log_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(f"{now:%Y-%m-%d %H:%M} {message}\n")


def _state() -> dict:
    try:
        d = json.loads((app_dir() / STATE_NAME).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    p = app_dir() / STATE_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def default_mailer(s: DesktopSettings):
    from ..credstore import default_store
    from .draftmail import DraftMailer
    return DraftMailer(default_store(), s.graph_client_id, s.graph_tenant)


def daily_run(s: DesktopSettings, now: Optional[datetime] = None, manual: bool = False,
              runner: Optional[Callable] = None, mailer_factory: Callable = default_mailer) -> int:
    """Returns 0 when nothing went wrong (including 'switched off' and 'already ran today'), else 1."""
    now = now or datetime.now()
    if not manual and not s.daily_run_enabled:
        log("skipped: the daily run is switched off", now)
        return 0
    day: date = now.date() - timedelta(days=1)
    state = _state()
    if not manual and state.get("last_report_day") == day.isoformat():
        log(f"skipped: the report for {day} was already made", now)
        return 0
    if runner is None:
        from ..runner import run_report as runner
    out_dir = reports_dir() / day.isoformat()
    try:
        result = runner(s.source, out_dir, end=day, days=1, email=False)
    except DssError as exc:
        log(f"FAILED for {day}: {exc}", now)
        return 1
    headline = result.report.headline
    if getattr(result, "all_failed", False):
        log(f"NOTHING CHECKED for {day}: {headline}", now)
        return 1
    draft_note, code = "no draft requested", 0
    if s.draft_email_enabled:
        try:
            html = Path(result.html_path).read_bytes()
            text = Path(result.text_path).read_text(encoding="utf-8")
            mailer_factory(s).create_draft(
                s.draft_to, f"DSS exception report {day} (draft)", text,
                f"DSS-report-{day}.html", html)
            draft_note = f"draft left in Drafts for {s.draft_to} (not sent)"
        except DssError as exc:
            draft_note, code = f"draft FAILED: {exc}", 1
    state["last_report_day"] = day.isoformat()
    _save_state(state)
    log(f"ran for {day}: {headline} | {draft_note} | folder: {out_dir}", now)
    if s.open_report_after_run and not code:
        _open(result.html_path)
    return code


def _open(path) -> None:
    import webbrowser
    webbrowser.open(Path(path).resolve().as_uri())
