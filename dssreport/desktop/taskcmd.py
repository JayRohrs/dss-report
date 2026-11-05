"""Windows Task Scheduler commands, built as argument lists so they can be tested on any computer.

The task runs `<program> daily-run` once a day at the chosen time. It runs as the signed-in user, with
no administrator rights (/RL LIMITED).
"""

import re
import subprocess
import sys
from typing import List

from ..errors import DssError

TASK_NAME = "DSS Report Daily"
_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _check_time(run_time: str) -> None:
    if not _TIME.fullmatch(run_time):
        raise DssError("The daily run time must look like 07:00 (24-hour clock).")


def program_command(exe_path: str, *args: str) -> str:
    """The single string Task Scheduler runs: the program (quoted, in case of spaces) plus arguments."""
    if '"' in exe_path:
        raise DssError("The program path must not contain a double quote.")
    return " ".join([f'"{exe_path}"', *args])


def create_command(exe_path: str, run_time: str, task_name: str = TASK_NAME) -> List[str]:
    _check_time(run_time)
    return ["schtasks", "/Create", "/TN", task_name, "/SC", "DAILY", "/ST", run_time,
            "/TR", program_command(exe_path, "daily-run"), "/RL", "LIMITED", "/F"]


def delete_command(task_name: str = TASK_NAME) -> List[str]:
    return ["schtasks", "/Delete", "/TN", task_name, "/F"]


def query_command(task_name: str = TASK_NAME) -> List[str]:
    return ["schtasks", "/Query", "/TN", task_name]


def one_line(cmd: List[str]) -> str:
    """The same command as text to paste into a Command Prompt."""
    return subprocess.list2cmdline(cmd)


def _run(cmd: List[str]):
    if sys.platform != "win32":
        raise DssError("The daily schedule uses Windows Task Scheduler, so it is only available on Windows.")
    return subprocess.run(cmd, capture_output=True, text=True)


def install(exe_path: str, run_time: str) -> str:
    r = _run(create_command(exe_path, run_time))
    if r.returncode != 0:
        raise DssError("Windows would not create the scheduled task: " + (r.stderr or r.stdout).strip())
    return f"The daily report is scheduled for {run_time} every day."


def remove() -> str:
    r = _run(delete_command())
    if r.returncode != 0 and "cannot find" not in (r.stderr + r.stdout).lower():
        raise DssError("Windows would not remove the scheduled task: " + (r.stderr or r.stdout).strip())
    return "The daily schedule is removed."


def exists() -> bool:
    return _run(query_command()).returncode == 0
