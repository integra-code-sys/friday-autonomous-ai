@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" "http://127.0.0.1:8790/config"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "daemon\config_center.py" --status
) else (
    python "daemon\config_center.py" --status
)
pause
