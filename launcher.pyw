# Starts the program without a console window (used by the desktop shortcuts and the schedule).
# If something goes wrong it shows a plain message box, because there is no console to read.
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dssreport.cli import main  # noqa: E402


def _box(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text[:1500], "DSS morning report", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    args = sys.argv[1:]
    err = io.StringIO()
    keep = sys.stderr
    sys.stderr = err
    try:
        code = main(args)
    except Exception as exc:  # last resort: never a silent failure
        code, _ = 1, err.write(f"Something unexpected went wrong: {type(exc).__name__}. See the run log.\n")
    finally:
        sys.stderr = keep
    if code != 0 and args[:1] != ["scheduled-run"]:
        _box(err.getvalue() or "The program stopped without a message.")
    sys.exit(code)
