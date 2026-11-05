"""Entry point for the packaged program (dss-report.exe)."""
import sys

from dssreport.desktop.cli import main

if __name__ == "__main__":
    sys.exit(main())
