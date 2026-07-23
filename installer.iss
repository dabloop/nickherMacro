; Inno Setup script for Nickher Macro
;
; Deliberately a PER-USER install into %LOCALAPPDATA%\Programs. That choice
; matters for two reasons:
;
;   1. No UAC prompt, so friends can install it without an admin password.
;   2. The in-app updater replaces the exe in place. Installed under Program
;      Files that would need elevation and would simply fail; under LocalAppData
;      the user already owns the file.
;
; Presets and settings live in %APPDATA%\NickherMacro (see core/paths.py), so
; they survive both upgrades and uninstall.

#define AppName        "Nickher Macro"
#define AppExe         "NickherMacro.exe"
#define AppPublisher   "dabloop"
#define AppURL         "https://github.com/dabloop/nickherMacro"

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{8F3C1A64-2B7E-4D9A-9C31-7E5A2D8B4F60}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; Per-user install: no admin rights needed
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\NickherMacro
DisableProgramGroupPage=yes
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

OutputDir=dist
OutputBaseFilename=NickherMacro-Setup-{#AppVersion}
SetupIconFile=ncicon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startupicon"; Description: "Start Nickher Macro when I sign in"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; onedir build: ship the exe and its _internal\ folder of DLLs together.
Source: "dist\NickherMacro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the backup the updater leaves behind, if one is present.
Type: files; Name: "{app}\{#AppExe}.old"

[Code]
// The app must not be running, or the exe cannot be replaced.
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

// After a SILENT install (i.e. the in-app updater ran us), relaunch the app.
// The interactive install relaunches via the Finished-page checkbox instead.
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and WizardSilent() then
    Exec(ExpandConstant('{app}\{#AppExe}'), '', '', SW_SHOW, ewNoWait, ResultCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
    Exec('taskkill.exe', '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\NickherMacro');
    if DirExists(DataDir) then
      // Presets are the user's own work — never delete them without asking.
      if MsgBox('Also delete your saved macros and settings?' + #13#10 +
                DataDir, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
