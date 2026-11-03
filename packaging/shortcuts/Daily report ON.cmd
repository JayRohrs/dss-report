@echo off
"%~dp0..\dss-report.exe" schedule on
echo.
"%~dp0..\dss-report.exe" status
pause