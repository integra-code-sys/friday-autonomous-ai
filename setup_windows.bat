@echo off
chcp 65001 >nul
title Instalador F.R.I.D.A.Y. - Projeto Prometheus
cd /d "%~dp0"

echo =======================================================
echo     INSTALADOR F.R.I.D.A.Y. - PROJETO PROMETHEUS
echo             Configuração do Nó Windows
echo =======================================================
echo.

:: 1. Verificação do Python
echo [1/6] Verificando instalação do Python...
set PYTHON_CMD=
where python >nul 2>nul
if %errorlevel% equ 0 set PYTHON_CMD=python
if "%PYTHON_CMD%"=="" (
    where py >nul 2>nul
    if %errorlevel% equ 0 set PYTHON_CMD=py -3
)

if "%PYTHON_CMD%"=="" (
    echo [ERRO] Python 3 não foi detectado no sistema!
    echo Baixando instalador oficial do Python 3.11...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile 'python_installer.exe'"
    if exist python_installer.exe (
        echo Instalando Python com PATH ativado...
        start /wait python_installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
        del python_installer.exe >nul 2>nul
        set PYTHON_CMD=python
    ) else (
        echo [ERRO] Por favor, instale o Python 3.10+ manualmente marcando 'Add Python to PATH' e execute este instalador novamente.
        pause
        exit /b 1
    )
)

echo Python detectado: %PYTHON_CMD%

:: 2. Criação do Ambiente Virtual (.venv)
echo.
echo [2/6] Configurando ambiente virtual Python isolado...
if not exist ".venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERRO] Falha ao criar ambiente virtual .venv.
        pause
        exit /b 1
    )
)
echo Ambiente virtual pronto.

:: 3. Instalação de Dependências
echo.
echo [3/6] Instalando dependências de IA, visão, áudio e automação Windows...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>nul
.venv\Scripts\python.exe -m pip install -r requirements-win.txt
if %errorlevel% neq 0 (
    echo [AVISO] Algumas dependências opcionais podem ter falhado. Continuando...
)

:: 4. Configuração Inicial do Cluster Mesh de 3 Nós
echo.
echo [4/6] Configurando Sincronização Mesh com Workstation e Servidor...
if not exist "memory" mkdir memory

:: Token compartilhado do cluster
if not exist "memory\remoto.json" (
    echo {"token": "Td-_gIVHwGPxgWuB5_cV2kQu"} > memory\remoto.json
)

:: Pares estáticos pré-configurados (Workstation Linux LAN, Tailscale e Servidor AnyDesk)
if not exist "memory\peers.json" (
    (
        echo {
        echo   "peers": [
        echo     {"host": "192.168.15.7", "port": 8790, "alias": "Workstation Linux LAN"},
        echo     {"host": "192.168.15.11", "port": 8790, "alias": "Workstation Linux Wi-Fi"},
        echo     {"host": "100.110.230.55", "port": 8790, "alias": "Workstation Linux Tailscale"},
        echo     {"host": "1577000126", "port": 8790, "alias": "Servidor AnyDesk"}
        echo   ]
        echo }
    ) > memory\peers.json
)

:: Perfil padrão se não existir
if not exist "memory\profile.json" (
    (
        echo {
        echo   "nome": "Iann",
        echo   "fatos": {},
        echo   "autonomia": true,
        echo   "voice": true,
        echo   "camera": true
        echo }
    ) > memory\profile.json
)

:: Agenda padrão se não existir
if not exist "memory\agenda.json" (
    echo {"itens": []} > memory\agenda.json
)

:: Tarefas padrão se não existir
if not exist "memory\tarefas.json" (
    echo {"itens": []} > memory\tarefas.json
)

:: 5. Criação de Atalhos (Área de Trabalho e Inicialização Automática)
echo.
echo [5/6] Criando atalhos e registrando inicialização automática no Windows...
set CURRENT_DIR=%CD%
set DESKTOP_PATH=%USERPROFILE%\Desktop
set STARTUP_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set PROGRAMS_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%DESKTOP_PATH%\F.R.I.D.A.Y. - Projeto Prometheus.lnk'); $s.TargetPath = '%CURRENT_DIR%\Friday.bat'; $s.WorkingDirectory = '%CURRENT_DIR%'; $s.Description = 'F.R.I.D.A.Y. - Assistente de IA Autônoma'; $s.Save()"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP_PATH%\Friday_Prometheus_Autostart.lnk'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%CURRENT_DIR%\start_friday_silent.vbs\"'; $s.WorkingDirectory = '%CURRENT_DIR%'; $s.Description = 'F.R.I.D.A.Y. Background Daemon'; $s.Save()"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%PROGRAMS_PATH%\F.R.I.D.A.Y. - Projeto Prometheus.lnk'); $s.TargetPath = '%CURRENT_DIR%\Friday.bat'; $s.WorkingDirectory = '%CURRENT_DIR%'; $s.Description = 'F.R.I.D.A.Y. - Assistente de IA Autônoma'; $s.Save()"

echo Atalhos criados com sucesso:
echo - Área de Trabalho: F.R.I.D.A.Y. - Projeto Prometheus
echo - Inicialização com o Windows: Ativado (Inicia automaticamente ao ligar o PC)

:: 6. Conclusão
echo.
echo [6/6] Instalação concluída com sucesso!
echo =======================================================
echo A F.R.I.D.A.Y. está pronta para rodar de forma autônoma
echo e sincronizada no seu Windows.
echo =======================================================
echo.
set /p INICIAR="Deseja iniciar a F.R.I.D.A.Y. agora? (S/N): "
if /i "%INICIAR%"=="S" (
    start Friday.bat
)
exit /b 0
