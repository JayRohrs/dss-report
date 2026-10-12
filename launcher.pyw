# Starts the program without a console window (used by the desktop shortcut and the schedule).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dssreport.cli import main  # noqa: E402

sys.exit(main())
