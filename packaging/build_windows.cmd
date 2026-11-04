@echo off
rem Build the Windows program and installer. Run on Windows, from anywhere:  packaging\build_windows.cmd
rem Needs: Python 3.11+ (python.org) and, for the installer, Inno Setup 6 (winget install JRSoftware.InnoSetup).
setlocal EnableExtensions
cd /d "%~dp0.."
python -m venv .venv-build || goto :fail
call .venv-build\Scripts\activate.bat || goto :fail
python -m pip install -r packaging\requirements-build.txt || goto :fail
python -m PyInstaller --noconfirm --clean packaging\dss-report.spec || goto :fail
for /f %%V in ('python -c "import dssreport;print(dssreport.__version__)"') do set "VER=%%V"
where iscc >nul 2>&1 && (iscc /DAppVersion=%VER% packaging\installer.iss || goto :fail) || echo  Inno Setup not found: skipping the installer. The portable program is dist\dss-report.exe
echo.
echo  Portable program : dist\dss-report.exe
echo  Installer        : dist\installer\DSS-Report-Setup-%VER%.exe
exit /b 0
:fail
echo  Build failed.
exit /b 1
