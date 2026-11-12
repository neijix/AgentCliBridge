; AgentCliBridge installer for Windows (Inno Setup 6). Built by build-exe.ps1, which passes the /D defines:
;   /DVersion=1.0.0            the release version (the snapshot archive's)
;   /DStageDir=<path>          the staged setup folder: setup.ps1, setup.sh and app\ (the snapshot)
;   /DOutDir=<path>            where agentclibridge-<version>-windows-all-setup.exe goes
;   /DSignToolName=<name>      optional: a Sign Tool defined on the command line (/S); unsigned without it
;
; This .exe installs nothing: it unpacks the setup folder agentclibridge-<version>-setup beside
; itself ({src}, normally the Downloads folder) and runs setup.ps1 there in a console. The wizard
; asks the install folder; everything the install writes goes under it. So: no Program Files or
; %LOCALAPPDATA%\Programs folder (CreateAppDir=no), no administrator (PrivilegesRequired=lowest),
; no Add/Remove Programs entry and no unins000.exe (Uninstallable=no), no registry, no shortcuts.
; The one thing Inno still writes outside {src} is its own %TEMP%\is-*.tmp (named in the README).
; Uninstalling is the install's uninstall.cmd (the wizard's --uninstall), not Inno's.

#ifndef Version
  #error Pass the version: ISCC /DVersion=1.0.0 ...
#endif
#ifndef StageDir
  #error Pass the staged setup folder: ISCC /DStageDir=C:\path\agentclibridge-1.0.0-setup ...
#endif
#ifndef OutDir
  #define OutDir "."
#endif

#define SetupFolder "agentclibridge-" + Version + "-setup"

[Setup]
AppName=AgentCliBridge
AppVersion={#Version}
AppPublisher=AgentCliBridge
PrivilegesRequired=lowest
Uninstallable=no
CreateAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=agentclibridge-{#Version}-windows-all-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
#ifdef SignToolName
SignTool={#SignToolName}
#endif

[Files]
; {src} is the folder the .exe was started from, not Inno's temporary copy of it. With CreateAppDir=no
; {app} is the Windows folder, so nothing here may use it.
Source: "{#StageDir}\*"; DestDir: "{src}\{#SetupFolder}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Run]
; A checked box on the last page: the wizard is interactive, so a silent run (/SILENT) only unpacks.
; No runhidden: powershell.exe gets its own console. -NoExit keeps it open after the wizard ends so a
; failure's message can be read.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -NoExit -File ""{src}\{#SetupFolder}\setup.ps1"""; WorkingDir: "{src}\{#SetupFolder}"; Description: "Run the AgentCliBridge setup wizard"; Flags: postinstall skipifsilent
