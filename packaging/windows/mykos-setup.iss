; ==============================================================================
; Script de Inno Setup 6 para MyKOS Ecosystem (Instalador Oficial de Windows)
; Genera: dist\MyKOS-Setup-1.0.0.exe (Instalador para usuario, sin requerir admin)
; ==============================================================================

#define MyAppName "MyKOS"
#define MyAppFullName "MyKOS Ecosystem"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Ruben (eskib0)"
#define MyAppURL "https://github.com/eskib0/MyKOS"
#define MyAppExeName "MyKOS.vbs"

[Setup]
AppId={{E6F74D42-9D9B-4A1C-9E7D-3D32F425786C}
AppName={#MyAppFullName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\MyKOS
DefaultGroupName=MyKOS
AllowNoIcons=yes
OutputDir=..\..\dist
OutputBaseFilename=MyKOS-Setup-{#MyAppVersion}
SetupIconFile=..\assets\mykos.ico
UninstallDisplayIcon={app}\packaging\assets\mykos.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableDirPage=no
DisableProgramGroupPage=no
ChangesEnvironment=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "addtopath"; Description: "Añadir comando 'mykos' al PATH del usuario"; GroupDescription: "Configuración del sistema:"; Flags: checkedonce

[Files]
; Lanzador silencioso de Windows
Source: "MyKOS.vbs"; DestDir: "{app}"; Flags: ignoreversion

; Archivos principales del ecosistema
Source: "..\..\version.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

; Scripts y ejecutables de la consola
Source: "..\..\bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

; Gateway (Node.js runtime, plugins y SPA frontend)
Source: "..\..\gateway\*"; DestDir: "{app}\gateway"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "gateway\app\data\*.log,gateway\app\data\*.json,gateway\app\data\*.bak*,gateway\app\data\oauth\*,gateway\app\data\media\*,gateway\app\data\uploads\*,*.tmp,*.pyc,__pycache__"

; Aplicaciones de escritorio (Monitor, Analizador)
Source: "..\..\apps\*"; DestDir: "{app}\apps"; Flags: ignoreversion recursesubdirs createallsubdirs

; Documentación y recursos gráficos
Source: "..\..\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\*"; DestDir: "{app}\packaging\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

; Runtimes portables embebidos (si se compila en modo Full/Offline)
#if DirExists("..\..\runtime")
Source: "..\..\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
; Acceso directo en el Escritorio (arranca silencioso y abre el navegador)
Name: "{autodesktop}\MyKOS"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\MyKOS.vbs"""; IconFilename: "{app}\packaging\assets\mykos.ico"; Tasks: desktopicon

; Accesos directos en el Menú Inicio
Name: "{autoprograms}\MyKOS\MyKOS"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\MyKOS.vbs"""; IconFilename: "{app}\packaging\assets\mykos.ico"
Name: "{autoprograms}\MyKOS\Detener MyKOS"; Filename: "{app}\bin\mykos.cmd"; Parameters: "stop"; IconFilename: "{app}\packaging\assets\mykos.ico"
Name: "{autoprograms}\MyKOS\Consola CLI MyKOS"; Filename: "powershell.exe"; Parameters: "-NoExit -ExecutionPolicy Bypass -File ""{app}\bin\mykos.ps1"" status"; IconFilename: "{app}\packaging\assets\mykos.ico"
Name: "{autoprograms}\MyKOS\{cm:UninstallProgram,MyKOS}"; Filename: "{uninstallexe}"

[Registry]
; Registrar en el PATH de usuario si la tarea está marcada
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}\bin"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}\bin'))

[Run]
; Ejecutar MyKOS al terminar la instalación si el usuario lo desea
Filename: "{sys}\wscript.exe"; Parameters: """{app}\MyKOS.vbs"""; Description: "{cm:LaunchProgram,MyKOS}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Parar el servidor antes de desinstalar
Filename: "{app}\bin\mykos.cmd"; Parameters: "stop"; Flags: runhidden

[Code]
// Función Pascal para no duplicar el PATH si ya existe
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + UpperCase(Param) + ';', ';' + UpperCase(OrigPath) + ';') = 0;
end;
