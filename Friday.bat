@echo off
chcp 65001 >nul
title F.R.I.D.A.Y. — Centro de Comando Stark (Mark 85)
cd /d "%~dp0"

echo ============================================================================
echo   Iniciando F.R.I.D.A.Y. Commercial Edition — Centro de Comando Stark
echo   Interface Holografica Mark 85: http://127.0.0.1:8790/stark
echo   Central de Configuracao: http://127.0.0.1:8790/config
echo ============================================================================

rem Aguarda a porta 8790 estar ativa e abre o HUD Stark Mark 85 em tela cheia nativa (1:1 com o Linux)
start /B "" powershell -NoProfile -Command "$p=8790; for ($i=0; $i -lt 35; $i++) { try { $t=New-Object System.Net.Sockets.TcpClient('127.0.0.1', $p); if ($t.Connected) { $t.Close(); break; } } catch {}; Start-Sleep -Seconds 1 }; if (Get-Command msedge -ErrorAction SilentlyContinue) { Start-Process msedge '--app=http://127.0.0.1:8790/stark --start-fullscreen' } elseif (Get-Command chrome -ErrorAction SilentlyContinue) { Start-Process chrome '--app=http://127.0.0.1:8790/stark --start-fullscreen' } else { Start-Process 'http://127.0.0.1:8790/stark' }"

if not exist "%LOCALAPPDATA%\Friday" mkdir "%LOCALAPPDATA%\Friday"
set "FRIDAY_LOG=%LOCALAPPDATA%\Friday\backend.log"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "daemon\prometheus.py" >> "%FRIDAY_LOG%" 2>&1
) else (
    python "daemon\prometheus.py" >> "%FRIDAY_LOG%" 2>&1
)
if errorlevel 1 (
    echo.
    echo O backend nao subiu. Veja %FRIDAY_LOG%
    pause
)
