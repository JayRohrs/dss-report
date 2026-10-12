"""One place that does a whole run: read data, build report, write files, optionally email."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from .adapters import build_adapter
from .config import Config, load_config
from .paths import resolve_rules_path
from .render import render_html, render_text
from .report import Report, build_report
from .state import load_state, note_seen, save_state
from .summary import add_summary


@dataclass
class RunResult:
    report: Report
    html_path: Path
    text_path: Path
    notes: List[str] = field(default_factory=list)   # plain-words things the person should know
    email_outcome: str = ""


def load_rules(explicit=None) -> Config:
    path = resolve_rules_path(explicit)
    if path.exists() or explicit:
        return load_config(path)
    return Config()


def run_report(input_spec: str, out_dir, end: Optional[date] = None, days: int = 1,
               rules_path=None, ai: bool = False, late_note: str = "",
               email: bool = False, adapter=None) -> RunResult:
    cfg = load_rules(rules_path)
    adapter = adapter or build_adapter(input_spec, cfg)
    notes: List[str] = []
    if adapter.needs_window:
        # Live source: always an explicit day (yesterday by default) so a missing latest
        # day shows as UNKNOWN instead of quietly shifting the window.
        end = end or date.today() - timedelta(days=1)
        adapter.set_window(end - timedelta(days=max(days, 1) - 1), end)
    records = adapter.load()
    notes += [f"Warning: {w}" for w in adapter.warnings]
    report = build_report(records, cfg, end=end, days=days, source_name=adapter.name,
                          unmapped=frozenset(adapter.unmapped))
    report.late_note = late_note
    if adapter.needs_window and not cfg.include:
        report.scope_note = ("Only locations that sent rows for these days are shown. A restaurant that "
                             "sent nothing at all is not listed unless you add it under "
                             "\"Only these locations\" in settings.")
    if ai or cfg.ai_enabled:
        note = add_summary(report, cfg)
        if note:
            notes.append(f"Note: {note}")
    if adapter.needs_window and records:
        # for the show/hide list in settings only; never used as "expected"
        save_state(note_seen(load_state(), {r.location for r in records}))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html, text = render_html(report), render_text(report)
    (out / "report.html").write_text(html, encoding="utf-8")
    (out / "email.txt").write_text(text, encoding="utf-8")
    result = RunResult(report, out / "report.html", out / "email.txt", notes)
    if email:
        result.email_outcome = send_email(text, html, notes)
    return result


def send_email(text: str, html: str, notes: List[str]) -> str:
    """Never raises: a failed email must not lose the report. The outcome is shown to the person."""
    from .credstore import default_store
    from .errors import DssError
    from .graph import deliver_email
    from .settings import load_settings
    settings = load_settings()
    if not settings.email_enabled:
        return ""
    subject = text.splitlines()[0].removeprefix("Subject: ")
    body = "\n".join(text.splitlines()[2:])
    try:
        return deliver_email(subject, body, html, settings, default_store())
    except DssError as exc:
        msg = f"The email was NOT created: {exc} The report itself was saved."
        notes.append(msg)
        return msg
