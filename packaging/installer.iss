; Inno Setup 6 script: one DSS-Report-Setup.exe. Per-user install, no administrator rights.
; Build:  iscc /DAppVersion=0.3.0 packaging\installer.iss   (build_windows.cmd does this for you)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppName=DSS Report
AppVersion={#AppVersion}
AppPublisher=Jay Rohrs
DefaultDirName={localappdata}\DssReport
DefaultGroupName=DSS Report
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=DSS-Report-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
UninstallDisplayName=DSS Report

[Tasks]
; Off unless the owner ticks it.
Name: "dailyon"; Description: "Make the report every morning at 07:00 (you can switch this off any time)"; Flags: unchecked

[Files]
Source: "..\dist\dss-report.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\rules.toml"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "shortcuts\*.cmd"; DestDir: "{app}\shortcuts"; Flags: ignoreversion
Source: "..\docs\INSTALL_WINDOWS_OWNER.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Daily report - turn ON"; Filename: "{app}\shortcuts\Daily report ON.cmd"
Name: "{group}\Daily report - turn OFF"; Filename: "{app}\shortcuts\Daily report OFF.cmd"
Name: "{group}\Daily report - what is on?"; Filename: "{app}\shortcuts\Status.cmd"
Name: "{group}\Make yesterday's report now"; Filename: "{app}\shortcuts\Run now.cmd"
Name: "{group}\Open the run log"; Filename: "{app}\shortcuts\Open run log.cmd"
Name: "{group}\Install guide"; Filename: "{app}\INSTALL_WINDOWS_OWNER.md"

[Run]
Filename: "{app}\dss-report.exe"; Parameters: "schedule on"; Tasks: dailyon; Flags: runhidden

[UninstallRun]
; Remove the Windows task so nothing is left running after uninstall.
Filename: "{app}\dss-report.exe"; Parameters: "schedule off"; Flags: runhidden; RunOnceId: "RemoveDailyTask"
