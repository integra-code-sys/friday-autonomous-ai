; Instalador real da F.R.I.D.A.Y. (Inno Setup 6). Não é zip autoextraível.
; Build, na máquina Windows, com o Inno Setup instalado:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\Friday.iss
; No Linux, se wine e iscc existirem:
;   wine "C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe" installer/Friday.iss
; Saída: installer\output\Friday_Setup-2.3.1.exe

#define AppVer "2.3.1"

[Setup]
AppId={{A7B3E1C4-9D20-4F6A-8C11-0F1D2A3B4C5D}
AppName=F.R.I.D.A.Y.
AppVersion={#AppVer}
AppPublisher=Integra Code
DefaultDirName={localappdata}\Friday
DefaultGroupName=F.R.I.D.A.Y.
DisableProgramGroupPage=no
OutputDir=output
OutputBaseFilename=Friday_Setup-{#AppVer}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Friday.ico
SetupLogging=yes

[Files]
Source: "..\daemon\*"; DestDir: "{app}\daemon"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.bak,*.pyc,__pycache__\*,*.v*bak"
Source: "..\shell\*"; DestDir: "{app}\shell"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.bak"
Source: "..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.bak"
Source: "..\requirements-win.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Friday.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Friday_Config.bat"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\start_friday_silent.vbs"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\Friday.ico"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "pos_instalar.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\F.R.I.D.A.Y."; Filename: "{app}\Friday.bat"; WorkingDir: "{app}"; IconFilename: "{app}\Friday.ico"
Name: "{group}\Desinstalar F.R.I.D.A.Y."; Filename: "{uninstallexe}"
Name: "{autodesktop}\F.R.I.D.A.Y."; Filename: "{app}\Friday.bat"; WorkingDir: "{app}"; IconFilename: "{app}\Friday.ico"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "FridayPrometheus"; ValueData: "wscript.exe ""{app}\start_friday_silent.vbs"""; Flags: uninsdeletevalue

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\pos_instalar.ps1"" -Destino ""{app}"""; StatusMsg: "Preparando o backend Python..."; Flags: waituntilterminated
Filename: "{app}\Friday.bat"; Description: "Iniciar a F.R.I.D.A.Y. agora"; Flags: nowait postinstall skipifsilent
