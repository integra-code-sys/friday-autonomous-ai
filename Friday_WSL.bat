@echo off
chcp 65001 >nul
title F.R.I.D.A.Y. — Execução Nativa Linux no Windows (WSL2 / WSLg)
cd /d "%~dp0"

echo ============================================================================
echo   F.R.I.D.A.Y. (Projeto Prometheus) — Modo WSL2 / WSLg
echo   Renderizacao Holografica Nativa Quickshell (1:1 com Linux Host)
echo ============================================================================
echo.

where wsl >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [AVISO] WSL2 nao encontrado neste sistema Windows.
    echo Para instalar o motor nativo Linux com aceleracao por GPU D3D12, execute:
    echo   install_wsl.bat
    echo.
    echo Iniciando no modo Nativo Windows Desktop (Mark 85 Stark HUD)...
    pause
    start "" Friday.bat
    exit /b 0
)

echo [1/3] Detectando caminho WSL da instalacao...
for /f "usebackq tokens=*" %%i in (`wsl wslpath -a "%~dp0"`) do set "WSL_DIR=%%i"
echo Caminho WSL: %WSL_DIR%

echo [2/3] Verificando servidor de graficos WSLg (Wayland / X11)...
wsl bash -c "if [ -z \"$WAYLAND_DISPLAY\" ] && [ -z \"$DISPLAY\" ]; then export DISPLAY=:0; fi"

echo [3/3] Iniciando F.R.I.D.A.Y. (Quickshell Mark 85 3D + Daemon Prometheus)...
echo.
wsl bash -c "cd '%WSL_DIR%' && if command -v qs >/dev/null 2>&1; then ./run.sh; else python3 daemon/prometheus.py; fi"

exit /b 0
