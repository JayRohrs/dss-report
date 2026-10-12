@echo off
rem ============================================================================
rem  DSS morning report - one-file Windows setup. Double-click this file.
rem  It: finds Python 3.11+ (installs it with Windows' own winget if missing),
rem  copies the program to your user folder, makes two desktop shortcuts, and
rem  opens the settings screen. It needs no administrator rights and sends nothing
rem  anywhere (the only download is Python itself, from winget, if you don't have it).
rem ============================================================================
setlocal EnableExtensions
title DSS morning report - setup
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\DssReport"
set "PROG=%DEST%\program"

echo.
echo  DSS morning report - setup
echo  --------------------------
echo.

if not exist "%SRC%dssreport\__init__.py" (
  echo  Please keep this file inside the downloaded folder, next to the "dssreport" folder,
  echo  and double-click it again.
  goto :fail
)

rem ---- 1. Python 3.11 or newer -------------------------------------------------
call :findpython
if defined PYEXE goto :havepython

echo  Python 3.11 or newer was not found on this computer.
where winget >nul 2>&1
if errorlevel 1 goto :nowinget
echo  Installing Python 3.12 for your user only (Windows will ask you to confirm).
winget install --id Python.Python.3.12 -e --source winget --scope user --accept-package-agreements --accept-source-agreements
call :findpython
if defined PYEXE goto :havepython
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PYEXE goto :havepython
echo.
echo  Python was installed but could not be found yet. Close this window and double-click
echo  this file once more.
goto :fail

:nowinget
echo.
echo  Please install Python 3.12 first from https://www.python.org/downloads/
echo  (on the first screen tick "Add python.exe to PATH"), then double-click this file again.
goto :fail

:havepython
for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PYW=%PYDIR%pythonw.exe"
if not exist "%PYW%" set "PYW=%PYEXE%"
echo  Using Python at %PYEXE%

rem ---- 2. Copy the program (never touches your settings or saved reports) -------
if not exist "%PROG%" mkdir "%PROG%"
robocopy "%SRC%dssreport" "%PROG%\dssreport" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copyfail
copy /Y "%SRC%launcher.pyw" "%PROG%\" >nul
copy /Y "%SRC%r365_mapping.example.toml" "%PROG%\" >nul
copy /Y "%SRC%README.md" "%PROG%\" >nul
if exist "%SRC%docs" robocopy "%SRC%docs" "%PROG%\docs" /E /XD screenshots /NFL /NDL /NJH /NJS /NP >nul
if not exist "%DEST%\r365_mapping.toml" copy "%SRC%r365_mapping.example.toml" "%DEST%\r365_mapping.toml" >nul

rem ---- 3. Desktop shortcuts -------------------------------------------------------
set "PYW=%PYW%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$q=[char]34; $d=[Environment]::GetFolderPath('Desktop'); $w=New-Object -ComObject WScript.Shell; $a=$w.CreateShortcut($d+'\DSS Report Settings.lnk'); $a.TargetPath=$env:PYW; $a.Arguments=$q+$env:PROG+'\launcher.pyw'+$q+' settings'; $a.WorkingDirectory=$env:DEST; $a.Save(); $b=$w.CreateShortcut($d+'\DSS Report Run Now.lnk'); $b.TargetPath=$env:PYW; $b.Arguments=$q+$env:PROG+'\launcher.pyw'+$q+' run-now'; $b.WorkingDirectory=$env:DEST; $b.Save()"
if errorlevel 1 echo  (Could not create the desktop shortcuts. You can still open "%PROG%\launcher.pyw" settings.)

rem ---- 4. First run: open the settings screen ---------------------------------------
echo.
echo  Done. Two shortcuts are now on your desktop:
echo    "DSS Report Settings"  - change what is checked, connect to R365, email, schedule
echo    "DSS Report Run Now"   - make yesterday's report and open it
echo.
echo  Opening the settings screen now...
start "" "%PYW%" "%PROG%\launcher.pyw" settings
echo.
pause
exit /b 0

:copyfail
echo.
echo  Copying the program failed. Close other programs using the folder %PROG% and try again.
goto :fail

:fail
echo.
pause
exit /b 1

:findpython
set "PYEXE="
for %%V in (3.13 3.12 3.11) do (
  if not defined PYEXE (
    for /f "usebackq delims=" %%P in (`py -%%V -c "import sys;print(sys.executable)" 2^>nul`) do set "PYEXE=%%P"
  )
)
exit /b 0
