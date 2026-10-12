@echo off
rem Removes the DSS morning report from this computer: schedule, shortcuts, saved passwords and the program.
rem Your saved reports and settings are kept unless you answer Y at the end.
setlocal EnableExtensions
set "DEST=%LOCALAPPDATA%\DssReport"
set "PROG=%DEST%\program"
echo.
echo  Removing the DSS morning report...
for %%V in (3.13 3.12 3.11) do (
  if not defined PYEXE (
    for /f "usebackq delims=" %%P in (`py -%%V -c "import sys;print(sys.executable)" 2^>nul`) do set "PYEXE=%%P"
  )
)
if defined PYEXE if exist "%PROG%\launcher.pyw" (
  "%PYEXE%" "%PROG%\launcher.pyw" schedule remove
  "%PYEXE%" "%PROG%\launcher.pyw" forget-secrets
)
del "%USERPROFILE%\Desktop\DSS Report Settings.lnk" 2>nul
del "%USERPROFILE%\Desktop\DSS Report Run Now.lnk" 2>nul
if exist "%PROG%" rmdir /S /Q "%PROG%"
echo.
set /p ANS=" Also delete your saved reports and settings in %DEST%? (Y/N) "
if /I "%ANS%"=="Y" rmdir /S /Q "%DEST%"
echo.
echo  Done.
pause
