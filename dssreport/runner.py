"""One place that does a whole run: read data, build the report, write the files, optionally email."""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Union

from . import licence as lic
from .adapters import build_adapter
from .config import Config, load_config
from .credstore import default_store, redact
from .errors import ConnectionFailed, DssError, InputError
from .paths import resolve_rules_path
from .render import multi_subject, render_html, render_text
from .report import MultiReport, Report, Section, build_multi_report, build_report, window
from .rules import PAYMENTS_TOTAL
from .settings import load_settings
from .sources import build_source
from .state import load_state, note_seen, save_state
from .summary import add_summary

SCOPE_NOTE = ("Only locations that sent rows for these days are shown. A restaurant that sent nothing at all "
              "is not listed unless you add it under \"Only these locations\" in settings.")


@dataclass
class RunResult:
    report: Union[Report, MultiReport]
    html_path: Path
    text_path: Path
    notes: List[str] = field(default_factory=list)   # plain-words things the person should know
    email_outcome: str = ""

    @property
    def all_failed(self) -> bool:
        return isinstance(self.report, MultiReport) and self.report.all_failed


def load_rules(explicit=None) -> Config:
    path = resolve_rules_path(explicit)
    if path.exists() or explicit:
        return load_config(path)
    return Config()


def _apply_licence_to_rules(cfg: Config, status: lic.LicenceStatus) -> None:
    """Rules the licence does not include are skipped and shown as such (never silently)."""
    if not status.has(lic.F_OPTIONAL_RULES):
        cfg.not_licensed.add(PAYMENTS_TOTAL)


def run_report(input_spec: str, out_dir, end: Optional[date] = None, days: int = 1,
               rules_path=None, ai: bool = False, late_note: str = "",
               email: bool = False, adapter=None, only_instance: Optional[str] = None) -> RunResult:
    cfg = load_rules(rules_path)
    notes: List[str] = []
    if input_spec == "r365":
        status = lic.current_status()
        _apply_licence_to_rules(cfg, status)
        report = _build_r365_report(cfg, status, end, days, notes, only_instance)
    else:
        status = lic.demo_status()           # made-up/trial data is never blocked by a licence
        _apply_licence_to_rules(cfg, status)
        adapter = adapter or build_adapter(input_spec, cfg)
        records = adapter.load()
        notes += [f"Warning: {w}" for w in adapter.warnings]
        report = build_report(records, cfg, end=end, days=days, source_name=adapter.name,
                              unmapped=frozenset(adapter.unmapped))
    report.late_note = late_note
    report.licence_line = status.message
    report.licence_problem = status.state not in (lic.OK, lic.DEMO)
    report.licence_notice = status.notice
    if ai or cfg.ai_enabled:
        _add_summary(report, cfg, status, notes)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html, text = render_html(report), render_text(report)
    (out / "report.html").write_text(html, encoding="utf-8")
    (out / "email.txt").write_text(text, encoding="utf-8")
    result = RunResult(report, out / "report.html", out / "email.txt", notes)
    if email:
        result.email_outcome = send_email(text, html, notes)
    return result


def _add_summary(report, cfg: Config, status: lic.LicenceStatus, notes: List[str]) -> None:
    try:
        status.require(lic.F_LOCAL_AI)
    except DssError as exc:
        notes.append(f"Note: {exc}")
        return
    if isinstance(report, MultiReport):
        flat = report.flat()
        flat.headline = report.headline
        note = add_summary(flat, cfg, failed=len(report.failed_sections))
        report.summary_sentence, report.summary_source = flat.summary_sentence, flat.summary_source
    else:
        note = add_summary(report, cfg)
    if note:
        notes.append(f"Note: {note}")


# ------------------------------------------------------------------ the live source: R365 instances

def _build_r365_report(cfg: Config, status: lic.LicenceStatus, end: Optional[date], days: int,
                       notes: List[str], only_instance: Optional[str] = None) -> Union[Report, MultiReport]:
    settings = load_settings()
    instances = [i for i in settings.enabled_instances if only_instance in (None, i.id)]
    if not instances:
        raise InputError("No R365 connection is set up yet. Open settings and add one.")
    # From a live source we always ask for an explicit day (yesterday by default), so a missing latest
    # day shows as UNKNOWN instead of quietly shifting the window.
    end = end or date.today() - timedelta(days=1)
    dates = window([], end, days)
    allowed = status.instances_allowed
    from . import dss_export_source as _d, r365 as _r  # noqa: F401  (registers the built-in kinds)
    from .sources import SOURCE_KINDS
    needs_store = any(SOURCE_KINDS[i.source_kind].needs_credentials for i in instances if i.source_kind in SOURCE_KINDS)
    try:
        store = default_store() if needs_store else None
        store_problem = ""
    except DssError as exc:
        store, store_problem = None, str(exc)
    state = load_state()
    sections: List[Section] = []
    for idx, inst in enumerate(instances):
        if idx >= allowed:
            why = (status.message if status.state != lic.OK else
                   f"Licence: over limit. Your licence allows {allowed} connection"
                   f"{'' if allowed == 1 else 's'}; this one was not connected.")
            sections.append(Section(inst.name, error=f"not connected: {why}"))
            continue
        kind_cls = SOURCE_KINDS.get(inst.source_kind)
        if store is None and (kind_cls is None or kind_cls.needs_credentials):
            sections.append(Section(inst.name, error=f"could not connect: {store_problem}"))
            continue
        icfg = replace(cfg, include=inst.include or cfg.include,
                       ignore=sorted(set(cfg.ignore) | set(inst.hidden)))
        try:
            source = build_source(inst, store, include=icfg.include)
            source.set_window(dates[0], dates[-1])
            records = source.load()
            why = "not in the export file" if not source.needs_credentials else "needs mapping"
            report = build_report(records, icfg, end=end, days=days, source_name=source.name,
                                  unmapped=frozenset(source.unmapped), unmapped_why=why)
            _describe_source(report, source)
            notes += [f"Warning ({inst.name}): {w}" for w in source.warnings]
            if not icfg.include:
                report.scope_note = SCOPE_NOTE
            if records:
                note_seen(state, inst.id, {r.location for r in records})
            sections.append(Section(inst.name, report=report))
        except ConnectionFailed as exc:
            sections.append(Section(inst.name, error=f"could not connect: {exc}"))
        except DssError as exc:
            sections.append(Section(inst.name, error=f"could not read its data: {exc}"))
    save_state(state)
    if len(sections) == 1 and sections[0].report is not None:
        return sections[0].report             # one connection that worked: the familiar single-report layout
    return build_multi_report(sections, cfg, dates, source_name="Restaurant365 (read-only), "
                              f"{len(instances)} connection{'' if len(instances) == 1 else 's'}")


def _describe_source(report: Report, source) -> None:
    """Carry a file source's own statements (what file, how old, what is missing) into the report."""
    line = getattr(source, "source_line", "")
    if line:
        report.source_line = line
        report.source_warnings = list(getattr(source, "source_warnings", []))
    text = getattr(source, "unmapped_text", "")
    if text:
        report.needs_mapping_text = text
        report.rules_note = [n.replace("NEEDS MAPPING (not checked; see docs/R365_OPEN_QUESTIONS.md)",
                                       "NOT IN THE EXPORT FILE (not checked)") for n in report.rules_note]


def send_email(text: str, html: str, notes: List[str]) -> str:
    """Never raises: a failed email must not lose the report. The outcome is shown to the person."""
    from .graph import deliver_email
    settings = load_settings()
    if not settings.email_enabled:
        return ""
    subject = text.splitlines()[0].removeprefix("Subject: ")
    body = "\n".join(text.splitlines()[2:])
    try:
        lic.current_status().require(lic.F_EMAIL)
        return deliver_email(subject, body, html, settings, default_store())
    except DssError as exc:
        msg = f"The email was NOT created: {exc} The report itself was saved."
        notes.append(msg)
        return msg
