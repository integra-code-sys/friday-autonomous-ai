@echo off
chcp 65001 >nul
title Configurar F.R.I.D.A.Y. — Integra Code
cd /d "%~dp0"

rem Verifica se o backend ja esta rodando na porta 8790
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8790/api/ping' -TimeoutSec 1 -UseBasicParsing; exit 0 } catch { exit 1 }"
if %ERRORLEVEL% NEQ 0 (
    echo Iniciando o backend da F.R.I.D.A.Y. em segundo plano...
    if exist ".venv\Scripts\python.exe" (
        start /B "" ".venv\Scripts\python.exe" "daemon\prometheus.py" >nul 2>&1
    ) else (
        start /B "" python "daemon\prometheus.py" >nul 2>&1
    )
    timeout /t 3 /nobreak >nul
)

start "" "http://127.0.0.1:8790/config"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "daemon\config_center.py" --status
) else (
    python "daemon\config_center.py" --status
)
pause
