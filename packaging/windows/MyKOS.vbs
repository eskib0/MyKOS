' ==============================================================================
' MyKOS Windows Silent Launcher
' Inicia el Gateway en segundo plano (sin ventana negra) y abre la interfaz web
' ==============================================================================
Option Explicit

Dim WshShell, fso, scriptDir, cmdPath, port

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
cmdPath = scriptDir & "\bin\mykos.cmd"

' 1. Arrancar el Gateway en segundo plano (0 = ventana oculta, True = esperar arranque)
WshShell.Run """" & cmdPath & """ start", 0, True

' 2. Abrir la interfaz web en el navegador por defecto
WshShell.Run """" & cmdPath & """ open", 0, False

Set WshShell = Nothing
Set fso = Nothing
