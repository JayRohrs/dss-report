"""Optional schedule: weekdays by default, one time of day.

The computer does the waking (Windows Task Scheduler, set up by `schedule install`); this file decides
WHAT to do when woken, so it can be tested anywhere:
  * run once for the most recent slot that has not run yet;
  * if the slot is more than `schedule_late_after_minutes` old (computer was off), say so in the report.
The Windows task fires at the chosen time AND when the user signs in, with "run as soon as possible
after a missed start" turned on, so a missed run happens once on the next start.
"""

import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from . import licence as lic
from .errors import DssError
from .paths import app_dir, log_path, reports_dir
from .settings import Settings
from .state import load_state, save_state

TASK_NAME = "DssReportMorning"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class Decision:
    run: bool
    reason: str
    slot: Optional[datetime] = None
    late: bool = False
    late_note: str = ""


def due_slot(now: datetime, s: Settings) -> Optional[datetime]:
    hh, mm = (int(x) for x in s.schedule_time.split(":"))
    for back in range(8):
        d = now.date() - timedelta(days=back)
        slot = datetime(d.year, d.month, d.day, hh, mm)
        if slot <= now and d.weekday() in s.schedule_weekdays:
            return slot
    return None


def decide(now: datetime, s: Settings, state: dict) -> Decision:
    if not s.schedule_enabled:
        return Decision(False, "The schedule is switched off.")
    slot = due_slot(now, s)
    if slot is None:
        return Decision(False, "No scheduled time has come round yet.")
    if state.get("last_slot", "") >= slot.isoformat():
        return Decision(False, f"The {slot:%a %H:%M} report has already run.", slot)
    behind = now - slot
    late = behind > timedelta(minutes=s.schedule_late_after_minutes)
    note = ""
    if late:
        note = (f"Late: this report was due {slot:%A %H:%M} but the computer was not able to run it "
                f"until {now:%A %H:%M} (it was probably off). It was run once, on start-up.")
    return Decision(True, "Due.", slot, late, note)


def report_day(now: datetime) -> date:
    """The business day being reviewed: the last finished day."""
    return now.date() - timedelta(days=1)


def log(message: str, now: Optional[datetime] = None) -> None:
    now = now or datetime.now()
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(f"{now:%Y-%m-%d %H:%M} {message}\n")


def scheduled_run(settings: Settings, now: Optional[datetime] = None, input_spec: str = "r365",
                  rules_path=None, runner=None) -> str:
    """What the scheduler calls. Returns a plain sentence. Records the outcome in the state/log."""
    from . import runner as runner_mod
    run = runner or runner_mod.run_report
    now = now or datetime.now()
    if not lic.current_status().has(lic.F_SCHEDULE):
        return "The automatic schedule is not included in your licence, so nothing was run. " + lic.current_status().message
    state = load_state()
    d = decide(now, settings, state)
    if not d.run:
        return d.reason
    day = report_day(now)
    try:
        result = run(input_spec, reports_dir() / day.isoformat(), end=day, days=1,
                     rules_path=rules_path, late_note=d.late_note, email=settings.email_enabled)
    except DssError as exc:
        state["last_error"] = f"{now.isoformat(timespec='minutes')} {exc}"
        save_state(state)
        log(f"FAILED for {day}: {exc}", now)
        return f"The scheduled report could not be made: {exc}"
    state["last_report_dir"] = str(reports_dir() / day.isoformat())
    if getattr(result, "all_failed", False):
        # the report (listing every connection as "could not connect") was saved so it can be seen,
        # but nothing was checked, so the slot is not marked done and the next wake-up tries again
        state["last_error"] = f"{now.isoformat(timespec='minutes')} {result.report.headline}"
        save_state(state)
        log(f"NOTHING CHECKED for {day}: {result.report.headline}", now)
        return result.report.headline
    state["last_slot"] = d.slot.isoformat()
    state["last_run_at"] = now.isoformat(timespec="minutes")
    state["last_headline"] = result.report.headline
    state.pop("last_error", None)
    save_state(state)
    log(f"ran for {day}{' (LATE)' if d.late else ''}: {result.report.headline} "
        f"| email: {result.email_outcome or 'not requested'}", now)
    return result.report.headline


# ------------------------------------------------------------ Windows Task Scheduler

def task_xml(s: Settings, pythonw: str, launcher: str, workdir: str) -> str:
    hh, mm = s.schedule_time.split(":")
    days = "".join(f"<{DAYS[d]}/>" for d in sorted(set(s.schedule_weekdays)))
    start = datetime.now().strftime("%Y-%m-%d") + f"T{hh}:{mm}:00"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Morning exception report (DSS). Runs on your computer only.</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek><DaysOfWeek>{days}</DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>
    </CalendarTrigger>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(pythonw)}</Command>
      <Arguments>"{escape(launcher)}" scheduled-run</Arguments>
      <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def install_task(s: Settings) -> str:
    lic.current_status().require(lic.F_SCHEDULE)
    if sys.platform != "win32":
        raise DssError("Automatic scheduling is set up through Windows Task Scheduler, "
                       "so it is only available on Windows.")
    launcher = Path(__file__).resolve().parent.parent / "launcher.pyw"
    xml = app_dir() / "task.xml"
    xml.parent.mkdir(parents=True, exist_ok=True)
    xml.write_text(task_xml(s, _pythonw(), str(launcher), str(app_dir())), encoding="utf-16")
    r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml), "/F"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise DssError("Windows would not create the scheduled task: " + (r.stderr or r.stdout).strip())
    return f"Scheduled for {s.schedule_time} on the days you picked, and once at sign-in if a run was missed."


def remove_task() -> str:
    if sys.platform != "win32":
        return "Nothing to remove (not Windows)."
    subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
    return "The scheduled task was removed."
