@echo off
chcp 65001 >nul
title Instalador F.R.I.D.A.Y. - Projeto Prometheus
cd /d "%~dp0"

:: 19/10: o instalador .exe extrai numa pasta temporária que é APAGADA no fim -> copia tudo para a pasta definitiva e instala de lá
set "DEST=%LOCALAPPDATA%\Friday"
if /i not "%~dp0"=="%DEST%\" (
    echo Copiando a F.R.I.D.A.Y. para %DEST% ...
    if not exist "%DEST%" mkdir "%DEST%"
    robocopy "%~dp0." "%DEST%" /E /NFL /NDL /NJH /NJS /NP >nul
    call "%DEST%\setup_windows.bat"
    exit /b %errorlevel%
)

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
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    if exist "C:\Program Files\Python311\python.exe" set PYTHON_CMD="C:\Program Files\Python311\python.exe"
    if exist "C:\Program Files\Python312\python.exe" set PYTHON_CMD="C:\Program Files\Python312\python.exe"
    if exist "C:\Program Files\Python310\python.exe" set PYTHON_CMD="C:\Program Files\Python310\python.exe"
)

if "%PYTHON_CMD%"=="" (
    echo [ERRO] Python 3 não foi detectado no sistema!
    echo Baixando instalador oficial do Python 3.11...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile 'python_installer.exe'"
    if exist python_installer.exe (
        echo Instalando Python com PATH ativado...
        start /wait python_installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
        del python_installer.exe >nul 2>nul
        if exist "C:\Program Files\Python311\python.exe" (
            set PYTHON_CMD="C:\Program Files\Python311\python.exe"
        ) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
            set PYTHON_CMD="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        ) else (
            set PYTHON_CMD=python
        )
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
    echo {"token": ""} > memory\remoto.json
)

:: Pares: descobertos sozinhos na rede (sync_mesh por UDP); nenhum IP fixo
if not exist "memory\peers.json" (
    echo {"peers": []} > memory\peers.json
)

:: Perfil padrão se não existir
if not exist "memory\profile.json" (
    (
        echo {
        echo   "nome": null,
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

:: 4b. IA local (Ollama + modelo), Claude Code CLI e papel de parede da Friday
echo.
echo [4b/6] Instalando IA local (Ollama + qwen3.5:4b), Claude Code e papel de parede...
where ollama >nul 2>nul
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile \"$env:TEMP\OllamaSetup.exe\""
    if exist "%TEMP%\OllamaSetup.exe" start /wait "" "%TEMP%\OllamaSetup.exe" /VERYSILENT /NORESTART
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
)
start /B "" ollama serve >nul 2>nul
timeout /t 5 /nobreak >nul
ollama pull qwen3.5:4b
if %errorlevel% neq 0 echo [AVISO] Modelo não baixado agora; a Friday tenta de novo ao iniciar.
where claude >nul 2>nul
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
)
if exist "%~dp0installer\wallpaper_friday.jpg" (
    powershell -NoProfile -Command "Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class W { [DllImport(\"user32.dll\", CharSet=CharSet.Unicode)] public static extern int SystemParametersInfo(int a, int b, string c, int d); }'; [W]::SystemParametersInfo(20, 0, \"$env:LOCALAPPDATA\Friday\installer\wallpaper_friday.jpg\", 3)"
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
echo e sincronizada no seu Windows (Visual Mark 85 1:1).
echo =======================================================
echo.
echo Iniciando F.R.I.D.A.Y. Centro de Comando Stark...
start "" Friday.bat
exit /b 0
