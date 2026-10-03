; Invoke through scripts/windows/build.ps1. No tasks, account access or app launch
; occur during installation. AppId stays stable across upgrades.
#ifndef AppVersion
  #error AppVersion must be supplied
#endif
#ifndef SourceRoot
  #error SourceRoot must be supplied
#endif
#ifndef OutputRoot
  #error OutputRoot must be supplied
#endif

[Setup]
AppId={{C5B931AB-AF09-44E4-877C-4C60C4F1B419}
AppName=SWU Checkin
AppVersion={#AppVersion}
AppPublisher=MatchAll
VersionInfoCompany=MatchAll
VersionInfoDescription=SWU Checkin Installer
AppPublisherURL=https://github.com/Maximora-byte/swu-checkin
DefaultDirName={localappdata}\Programs\SWUCheckin
DefaultGroupName=SWU Checkin
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
LicenseFile={#SourceRoot}\LICENSE
OutputDir={#OutputRoot}
OutputBaseFilename=SWUCheckin-{#AppVersion}-win-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\SWUCheckin.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=no

[Files]
Source: "{#SourceRoot}\dist\windows\SWUCheckin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{userprograms}\SWU Checkin"; Filename: "{app}\SWUCheckin.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\SWU Checkin"; Filename: "{app}\SWUCheckin.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[UninstallRun]
; Exact application-owned task only. schtasks reports an absent task as a
; nonzero exit; uninstall can continue. Never remove legacy/unrelated tasks.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""SWUCheckin-Desktop"" /F"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSWUCheckinDesktopTask"

; Deliberately no [Run], task registration, or removal of user settings.
