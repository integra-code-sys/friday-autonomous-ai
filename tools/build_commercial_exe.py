#!/usr/bin/env python3
"""Gerador do Instalador Autônomo Comercial Windows (.exe) da F.R.I.D.A.Y.
Empacota daemon, memory (limpa/zero-state), models, shell e scripts em um executável auto-extraível 7z SFX.
"""
import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SFX_STUB = os.path.join(HERE, "sfx", "7z.sfx")
OUT_EXE = os.path.join(ROOT, "Instalador_Friday_Comercial_Windows.exe")

SFX_CONFIG = """;!@Install@!UTF-8!
Title="Instalador F.R.I.D.A.Y. Commercial Edition"
BeginPrompt="Deseja instalar a F.R.I.D.A.Y. Commercial Edition (Projeto Prometheus) neste computador Windows?"
RunProgram="install_windows.bat"
;!@InstallEnd@!
"""


def build():
    # Garante memória limpa antes de empacotar
    subprocess.run(["python3", os.path.join(ROOT, "daemon", "memoria_zero.py"), "--reset", "--nome", "Chefe"], check=True)

    with tempfile.TemporaryDirectory() as tmp:
        payload = os.path.join(tmp, "payload")
        os.makedirs(payload, exist_ok=True)

        for d in ("daemon", "memory", "models", "shell"):
            src = os.path.join(ROOT, d)
            if os.path.exists(src):
                shutil.copytree(src, os.path.join(payload, d), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.bak"))

        for f in ("install_windows.bat", "Friday.bat", "Friday_Config.bat", "start_friday_silent.vbs", "requirements-win.txt", "requirements.txt"):
            src = os.path.join(ROOT, f)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(payload, f))

        archive_7z = os.path.join(tmp, "payload.7z")
        subprocess.run(["7z", "a", "-t7z", "-mx=5", archive_7z, "."], cwd=payload, check=True, stdout=subprocess.DEVNULL)

        cfg_path = os.path.join(tmp, "config.txt")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(SFX_CONFIG)

        with open(OUT_EXE, "wb") as out:
            with open(SFX_STUB, "rb") as sfx:
                out.write(sfx.read())
            with open(cfg_path, "rb") as cfg:
                out.write(cfg.read())
            with open(archive_7z, "rb") as arc:
                out.write(arc.read())

    os.chmod(OUT_EXE, 0o755)
    print(f"[OK] Instalador Comercial Windows gerado: {OUT_EXE} ({os.path.getsize(OUT_EXE) / (1024*1024):.2f} MB)")


if __name__ == "__main__":
    build()
