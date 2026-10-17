@echo off
chcp 65001 >nul
title Instalador F.R.I.D.A.Y. Commercial Edition - Integra Code (Windows)
echo ============================================================================
echo   F.R.I.D.A.Y. (Projeto Prometheus) - Integra Code Commercial Edition
echo   Instalador Automatico de Dependencias para Windows 10 / 11
echo ============================================================================
echo.

set "INSTALL_DIR=%LOCALAPPDATA%\Friday"
echo [1/6] Copiando arquivos para %INSTALL_DIR%...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
xcopy /E /I /Y "%~dp0*" "%INSTALL_DIR%\" >nul

echo [2/6] Verificando Python 3.11+ e FFmpeg...
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Baixando e instalando Python 3.11 automaticamente via winget...
    winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
)
where ffmpeg >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Baixando e instalando FFmpeg automaticamente via winget...
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
)

echo [3/6] Criando ambiente virtual (.venv) e instalando pacotes...
cd /d "%INSTALL_DIR%"
if not exist ".venv" (
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements-win.txt

echo [4/6] Executando Auto-Instalador de Dependencias e Modelos (auto_deps.py)...
".venv\Scripts\python.exe" "daemon\auto_deps.py"

echo [5/6] Inicializando Banco de Dados Zero-State e Auditoria de Privacidade...
".venv\Scripts\python.exe" "daemon\memoria_zero.py" --init
".venv\Scripts\python.exe" "daemon\privacy_guard.py"

echo [6/6] Criando atalhos na Area de Trabalho...
powershell -NoProfile -Command "$ws=New-Object -COM WScript.Shell; $d=[Environment]::GetFolderPath('Desktop'); $s1=$ws.CreateShortcut($d+'\F.R.I.D.A.Y..lnk'); $s1.TargetPath='%INSTALL_DIR%\Friday.bat'; $s1.WorkingDirectory='%INSTALL_DIR%'; $s1.Save(); $s2=$ws.CreateShortcut($d+'\Configurar F.R.I.D.A.Y..lnk'); $s2.TargetPath='%INSTALL_DIR%\Friday_Config.bat'; $s2.WorkingDirectory='%INSTALL_DIR%'; $s2.Save(); if (Test-Path '%INSTALL_DIR%\Friday_WSL.bat') { $s3=$ws.CreateShortcut($d+'\F.R.I.D.A.Y. Nativo WSL.lnk'); $s3.TargetPath='%INSTALL_DIR%\Friday_WSL.bat'; $s3.WorkingDirectory='%INSTALL_DIR%'; $s3.Save(); }"

echo.
echo ============================================================================
echo   INSTALACAO INTEGRA CODE CONCLUIDA COM SUCESSO!
echo   - Atalho Area de Trabalho: F.R.I.D.A.Y. (Centro de Comando Stark Mark 85)
echo   - Atalho Alternativo: F.R.I.D.A.Y. Nativo WSL (1:1 com Linux Wayland)
echo   - Interface Holografica: http://127.0.0.1:8790/stark
echo   - Central de Configuracao: http://127.0.0.1:8790/config
echo ============================================================================
start "" "%INSTALL_DIR%\Friday.bat"
exit /b 0
