@echo off
"%~dp0..\dss-report.exe" schedule off
echo.
"%~dp0..\dss-report.exe" status
pause