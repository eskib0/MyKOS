@echo off
setlocal
where pwsh.exe >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PS_EXE=pwsh.exe"
) else (
    set "PS_EXE=powershell.exe"
)
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0mykos.ps1" %*

