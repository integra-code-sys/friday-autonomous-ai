@echo off
chcp 65001 >nul
title F.R.I.D.A.Y. Commercial Edition — Integra Code
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "daemon\auto_deps.py" >nul 2>&1
    echo Iniciando F.R.I.D.A.Y. Commercial Edition (Integra Code)...
    echo Central de Configuracao Web: http://127.0.0.1:8790/config
    start /B "" ".venv\Scripts\python.exe" "daemon\windows_wallpaper.py" >nul 2>&1
    ".venv\Scripts\python.exe" "daemon\prometheus.py"
) else (
    python "daemon\auto_deps.py" >nul 2>&1
    start /B "" python "daemon\windows_wallpaper.py" >nul 2>&1
    python "daemon\prometheus.py"
)
