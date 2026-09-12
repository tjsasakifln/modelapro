; Inno Setup script.  It deliberately does not use a fake signing directive.
; The release operator supplies /DAppVersion and /DArtifactDir after a signed
; build has been authorized. Unsigned output remains a verification artifact.
#ifndef AppVersion
  #error AppVersion must be supplied (/DAppVersion=...)
#endif
#ifndef BundleDir
  #error BundleDir must be supplied (/DBundleDir=...)
#endif

[Setup]
AppName=MODELA PRO
AppVersion={#AppVersion}
AppPublisher=CONFENGE
DefaultDirName={autopf}\MODELA PRO
DefaultGroupName=MODELA PRO
OutputBaseFilename=MODELA-PRO-{#AppVersion}-win64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayName=MODELA PRO

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\MODELA PRO"; Filename: "{app}\MODELA-PRO.exe"
Name: "{autodesktop}\MODELA PRO"; Filename: "{app}\MODELA-PRO.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
