; -------------------------------------------------------------------------
; DRPS5 - Instalador Oficial de Windows (x86_64 e Intel/ARM)
; Compatible con Windows 10/11 x64 y Windows 11 ARM64 (Prism)
; -------------------------------------------------------------------------

Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel admin

; Nombre y archivo de salida
Name "DRPS5 - Pantalla Remota PS5"
OutFile "..\DRPS5_Setup.exe"

; Ruta de instalación por defecto
InstallDir "$PROGRAMFILES64\DRPS5"
InstallDirRegKey HKLM "Software\DRPS5" "InstallLocation"

; Incluir macros de Modern UI y arquitectura
!include "MUI2.nsh"
!include "x64.nsh"

; Configuración de iconos
!define MUI_ICON "..\DRPS5\app_icon.ico"
!define MUI_UNICON "..\DRPS5\app_icon.ico"
!define MUI_ABORTWARNING

; Interfaz gráfica del instalador
!define MUI_WELCOMEPAGE_TITLE "Bienvenido al Instalador de DRPS5"
!define MUI_WELCOMEPAGE_TEXT "Este asistente instalará DRPS5 - Pantalla Remota PS5 en su ordenador con Windows.$\r$\n$\r$\nCompatible nativamente con procesadores Intel/AMD x64 y procesadores ARM64 mediante Microsoft Prism.$\r$\n$\r$\nHaga clic en Siguiente para continuar."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

; Página final con opción de ejecutar
!define MUI_FINISHPAGE_RUN "$INSTDIR\DRPS5.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Iniciar DRPS5 ahora"
!insertmacro MUI_PAGE_FINISH

; Páginas del desinstalador
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; Idioma
!insertmacro MUI_LANGUAGE "Spanish"

; Verificación de sistema 64-bit y activación de modo 64-bit nativo
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "DRPS5 requiere una versión de Windows de 64 bits (x64 o ARM64)."
    Abort
  ${EndIf}
  ${DisableX64FSRedirection}
  SetRegView 64
FunctionEnd

; Sección principal de instalación
Section "DRPS5 Principal" SecCore
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; Archivos del núcleo de la aplicación
  File "..\DRPS5\DRPS5.exe"
  File "..\DRPS5\DRPS5_debug.bat"
  File "..\DRPS5\app_icon.ico"
  File "..\DRPS5\drps5.py"
  File "..\DRPS5\drps5_gui.py"
  File "..\DRPS5\drps5_stream.py"
  File "..\DRPS5\drps5_config.py"
  File "..\DRPS5\drps5_core.py"
  File "..\DRPS5\drps5_config.json"
  File "..\DRPS5\gamecontrollerdb.txt"

  ; Carpetas de recursos y entorno embebido
  File /r "..\DRPS5\gui"
  File /r "..\DRPS5\assets"
  File /r "..\DRPS5\pyremoteplay"
  File /r "..\DRPS5\runtime"

  ; Generar desinstalador
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Provisionar configuración con credenciales en el perfil del usuario
  SetShellVarContext current
  CreateDirectory "$PROFILE\.drps5"
  CopyFiles /SILENT "$INSTDIR\drps5_config.json" "$PROFILE\.drps5\drps5_config.json"

  ; Accesos directos para todos los usuarios
  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\DRPS5"
  CreateShortcut "$SMPROGRAMS\DRPS5\DRPS5.lnk" "$INSTDIR\DRPS5.exe" "" "$INSTDIR\app_icon.ico" 0
  CreateShortcut "$SMPROGRAMS\DRPS5\Diagnóstico DRPS5.lnk" "$INSTDIR\DRPS5_debug.bat" "" "$INSTDIR\DRPS5_debug.bat" 0
  CreateShortcut "$SMPROGRAMS\DRPS5\Desinstalar DRPS5.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0
  CreateShortcut "$DESKTOP\DRPS5.lnk" "$INSTDIR\DRPS5.exe" "" "$INSTDIR\app_icon.ico" 0

  ; Registro de Windows para Panel de Control (Programas y Características / Desinstalar aplicaciones)
  WriteRegStr HKLM "Software\DRPS5" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "DisplayName" "DRPS5 - Pantalla Remota PS5"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "DisplayIcon" "$INSTDIR\app_icon.ico,0"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "DisplayVersion" "1.2.0"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "Publisher" "DRPS5"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "EstimatedSize" 219592
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5" "NoRepair" 1

  ; Pre-autorizar DRPS5 en el Firewall de Windows de forma silenciosa para evitar alertas de sistema
  nsExec::Exec 'netsh advfirewall firewall add rule name="DRPS5 - Pantalla Remota PS5" dir=in action=allow program="$INSTDIR\DRPS5.exe" enable=yes profile=any'
  nsExec::Exec 'netsh advfirewall firewall add rule name="DRPS5 - Pantalla Remota PS5 (Outbound)" dir=out action=allow program="$INSTDIR\DRPS5.exe" enable=yes profile=any'
  nsExec::Exec 'netsh advfirewall firewall add rule name="DRPS5 - Runtime Python" dir=in action=allow program="$INSTDIR\runtime\python.exe" enable=yes profile=any'
  nsExec::Exec 'netsh advfirewall firewall add rule name="DRPS5 - Runtime PythonW" dir=in action=allow program="$INSTDIR\runtime\pythonw.exe" enable=yes profile=any'
SectionEnd

; Sección del desinstalador
Section "Uninstall"
  ${DisableX64FSRedirection}
  SetRegView 64

  ; Eliminar reglas de Firewall
  nsExec::Exec 'netsh advfirewall firewall delete rule name="DRPS5 - Pantalla Remota PS5"'
  nsExec::Exec 'netsh advfirewall firewall delete rule name="DRPS5 - Pantalla Remota PS5 (Outbound)"'
  nsExec::Exec 'netsh advfirewall firewall delete rule name="DRPS5 - Runtime Python"'
  nsExec::Exec 'netsh advfirewall firewall delete rule name="DRPS5 - Runtime PythonW"'

  SetShellVarContext all
  Delete "$DESKTOP\DRPS5.lnk"
  Delete "$SMPROGRAMS\DRPS5\DRPS5.lnk"
  Delete "$SMPROGRAMS\DRPS5\Diagnóstico DRPS5.lnk"
  Delete "$SMPROGRAMS\DRPS5\Desinstalar DRPS5.lnk"
  RMDir "$SMPROGRAMS\DRPS5"

  ; Eliminar archivos de la instalación
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\gui"
  RMDir /r "$INSTDIR\assets"
  RMDir /r "$INSTDIR\pyremoteplay"
  Delete "$INSTDIR\DRPS5.exe"
  Delete "$INSTDIR\DRPS5_debug.bat"
  Delete "$INSTDIR\app_icon.ico"
  Delete "$INSTDIR\drps5.py"
  Delete "$INSTDIR\drps5_gui.py"
  Delete "$INSTDIR\drps5_stream.py"
  Delete "$INSTDIR\drps5_config.py"
  Delete "$INSTDIR\drps5_core.py"
  Delete "$INSTDIR\drps5_config.json"
  Delete "$INSTDIR\gamecontrollerdb.txt"
  Delete "$INSTDIR\crash.log"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  ; Eliminar claves del registro de Windows (Panel de Control)
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DRPS5"
  DeleteRegKey HKLM "Software\DRPS5"
SectionEnd
