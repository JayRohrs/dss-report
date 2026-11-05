# PyInstaller spec: one self-contained dss-report.exe (no Python needed on the owner's computer).
# Build with:  pyinstaller --noconfirm --clean packaging/dss-report.spec   (run from the repo root)
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "dssreport" / "data"), "dssreport/data"),
        (str(ROOT / "rules.toml"), "."),
    ],
    hiddenimports=["dssreport.desktop.cli", "dssreport.runner", "dssreport.graph"],
    excludes=["tkinter", "unittest", "tests", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="dss-report",
    console=True,          # owner-facing commands print messages; Task Scheduler runs it in the background
    upx=False,             # UPX-packed exes trigger more antivirus warnings
)
