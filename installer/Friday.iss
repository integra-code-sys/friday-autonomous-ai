; Instalador nativo oficial da F.R.I.D.A.Y. - Projeto Prometheus
; Desenvolvido para Integra Code com instalador gráfico Inno Setup 7
; Gera executável genuíno de instalação com wizard visual, atalhos e configuração de ambiente.

#define AppVer "2.3.1"
#define AppName "F.R.I.D.A.Y. - Projeto Prometheus"
#define AppPublisher "Integra Code"
#define AppURL "https://github.com/loqiann/friday-commercial"

[Setup]
AppId={{A7B3E1C4-9D20-4F6A-8C11-0F1D2A3B4C5D}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\FRIDAY-Prometheus
DefaultGroupName=F.R.I.D.A.Y.
AllowNoIcons=yes
OutputDir=..\friday-commercial-github
OutputBaseFilename=Setup_Friday
SetupIconFile=..\Friday.ico
UninstallDisplayIcon={app}\Friday.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=no
DisableProgramGroupPage=yes
SetupLogging=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Iniciar a F.R.I.D.A.Y. automaticamente ao ligar o computador"; GroupDescription: "Inicialização Automática"

[Files]
Source: "..\daemon\*"; DestDir: "{app}\daemon"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.bak,*.pyc,__pycache__\*,*.v*bak"
Source: "..\shell\*"; DestDir: "{app}\shell"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.bak,*.v*bak"
Source: "..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.bak,*.v*bak,tools\dist\*,dist\*,innosetup\*,sfx\*,*.zip,*.apk"
Source: "..\memory\*"; DestDir: "{app}\memory"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.sock,*.tmp,*.log,*.jsonl"
Source: "..\requirements-win.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup_windows.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Friday.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Friday_Config.bat"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\start_friday_silent.vbs"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\Friday.ico"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\friday.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\TERMS_OF_USE.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\PRIVACY_POLICY.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "pos_instalar.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\F.R.I.D.A.Y."; Filename: "{app}\Friday.bat"; WorkingDir: "{app}"; IconFilename: "{app}\Friday.ico"
Name: "{group}\Configurar F.R.I.D.A.Y."; Filename: "{app}\Friday_Config.bat"; WorkingDir: "{app}"; IconFilename: "{app}\Friday.ico"
Name: "{group}\Desinstalar F.R.I.D.A.Y."; Filename: "{uninstallexe}"
Name: "{autodesktop}\F.R.I.D.A.Y."; Filename: "{app}\Friday.bat"; WorkingDir: "{app}"; IconFilename: "{app}\Friday.ico"; Tasks: desktopicon
Name: "{userstartup}\Friday_Prometheus_Autostart"; Filename: "wscript.exe"; Parameters: """{app}\start_friday_silent.vbs"""; WorkingDir: "{app}"; Tasks: autostart

[Registry]
Root: HKCU; Subkey: "Software\IntegraCode\Friday"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\IntegraCode\Friday"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletevalue

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"

[Run]
Filename: "{app}\setup_windows.bat"; Description: "Configurar ambiente virtual e dependências Python"; Flags: waituntilterminated
Filename: "{app}\Friday.bat"; Description: "Iniciar a F.R.I.D.A.Y. Centro de Comando Stark agora"; Flags: nowait postinstall skipifsilent unchecked
