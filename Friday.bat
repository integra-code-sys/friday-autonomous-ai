@echo off
chcp 65001 >nul
title F.R.I.D.A.Y. — Centro de Comando Stark (Mark 85)
cd /d "%~dp0"

echo ============================================================================
echo   Iniciando F.R.I.D.A.Y. Commercial Edition — Centro de Comando Stark
echo   Interface Holografica Mark 85: http://127.0.0.1:8790/stark
echo   Central de Configuracao: http://127.0.0.1:8790/config
echo ============================================================================

rem Inicia o HUD holografico Mark 85 em modo aplicativo nativo (sem bordas, tela cheia)
start /B "" powershell -NoProfile -Command "Start-Sleep -Seconds 2; if (Get-Command msedge -ErrorAction SilentlyContinue) { Start-Process msedge '--app=http://127.0.0.1:8790/stark --start-fullscreen' } elseif (Get-Command chrome -ErrorAction SilentlyContinue) { Start-Process chrome '--app=http://127.0.0.1:8790/stark --start-fullscreen' } else { Start-Process 'http://127.0.0.1:8790/stark' }"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "daemon\auto_deps.py" >nul 2>&1
    ".venv\Scripts\python.exe" "daemon\prometheus.py"
) else (
    python "daemon\auto_deps.py" >nul 2>&1
    python "daemon\prometheus.py"
)
