@echo off
chcp 65001 >nul
setlocal DisableDelayedExpansion
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\windows.ps1" %*
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
