@echo off
chcp 65001 >nul
title Instalador do Motor Nativo Linux para Windows (WSL2 / WSLg)
cd /d "%~dp0"

echo ============================================================================
echo   INSTALADOR DO MOTOR NATIVO LINUX (WSL2 + WSLg) — F.R.I.D.A.Y.
echo   Configura o subsistema Linux para rodar o Quickshell e o Prometheus
echo   com 100%% de paridade gráfica e funcional com o host Linux.
echo ============================================================================
echo.

where wsl >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [1/3] Habilitando e Instalando o WSL2 no Windows...
    wsl --install -d Ubuntu --no-launch
    echo.
    echo O WSL foi configurado. Caso o Windows peca reinicio, reinicie o computador
    echo e execute este instalador novamente.
) else (
    echo [1/3] WSL2 ja detectado no Windows.
)

echo [2/3] Instalando dependencias graficas e pacotes no ambiente WSL...
wsl -d Ubuntu -e bash -c "sudo apt update && sudo apt install -y python3 python3-pip python3-venv git curl libgl1-mesa-dri mesa-utils wayland-protocols"

echo [3/3] Criando atalho na Area de Trabalho: F.R.I.D.A.Y. (Motor Nativo WSL)
powershell -NoProfile -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\FRIDAY_Nativo_WSL.lnk');$s.TargetPath='%~dp0Friday_WSL.bat';$s.WorkingDirectory='%~dp0';$s.Save()"

echo.
echo ============================================================================
echo   CONFIGURACAO WSLg CONCLUIDA!
echo   Voce pode iniciar a F.R.I.D.A.Y. com o visual e funcao 100%% nativos Linux
echo   clicando no atalho 'FRIDAY_Nativo_WSL' ou executando Friday_WSL.bat
echo ============================================================================
pause
exit /b 0
