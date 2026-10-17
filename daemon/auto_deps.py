#!/usr/bin/env python3
"""Instalador Automático de Dependências e Auto-Diagnóstico — F.R.I.D.A.Y. Commercial Edition.
Desenvolvido por Integra Code (https://github.com/integracode).

Garante que todas as dependências de Python, binários de sistema (ffmpeg, captura de tela, áudio, ADB),
modelos neurais ONNX e bancos de dados Zero-State estejam instalados e funcionais antes de iniciar.
Tudo é executado 100% localmente na máquina do usuário, sem telemetria externa.
"""
import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODELS_DIR = os.path.join(ROOT, "models")
if HERE not in sys.path:
    sys.path.insert(0, HERE)

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

# Mapeamento: (modulo_import, pacote_pip, obrigatorio)
PACOTES_PYTHON_BASE = [
    ("numpy", "numpy>=1.26.0", True),
    ("scipy", "scipy>=1.11.0", True),
    ("cv2", "opencv-python>=4.8.0", True),
    ("onnxruntime", "onnxruntime>=1.16.0", True),
    ("aiohttp", "aiohttp>=3.9.0", True),
    ("faster_whisper", "faster-whisper>=1.0.0", True),
    ("edge_tts", "edge-tts>=6.1.9", True),
    ("psutil", "psutil>=5.9.0", True),
    ("PIL", "Pillow>=10.0.0", True),
    ("pyperclip", "pyperclip>=1.8.2", False),
    ("yt_dlp", "yt-dlp>=2024.0.0", False),
]

PACOTES_PYTHON_WINDOWS = [
    ("pyautogui", "pyautogui>=0.9.54", True),
    ("mss", "mss>=9.0.1", True),
    ("sounddevice", "sounddevice>=0.4.6", True),
]

# Modelos ONNX leves incluídos/requeridos para visão local rápida (faces, mãos, objetos)
MODELOS_ESSENCIAIS = {
    "yunet.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface_2021dec.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def detectar_adb():
    """Localiza o binário ADB no PATH ou no SDK local do usuário."""
    adb_path = shutil.which("adb")
    if adb_path:
        return adb_path
    candidatos = [
        os.path.expanduser("~/.local/android/sdk/platform-tools/adb"),
        os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
        "/opt/android-sdk/platform-tools/adb",
    ]
    if IS_WINDOWS:
        local_app = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
        candidatos.append(os.path.join(local_app, "Android", "Sdk", "platform-tools", "adb.exe"))
    for c in candidatos:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


def detectar_distro_linux():
    """Identifica o gerenciador de pacotes no Linux (pacman, apt, dnf)."""
    if not IS_LINUX:
        return None
    if shutil.which("pacman"):
        return "pacman"
    if shutil.which("apt-get"):
        return "apt"
    if shutil.which("dnf"):
        return "dnf"
    return "generico"


def verificar_pacotes_python():
    """Retorna o status de cada pacote Python necessário."""
    lista = list(PACOTES_PYTHON_BASE)
    if IS_WINDOWS:
        lista.extend(PACOTES_PYTHON_WINDOWS)
    instalados = []
    faltando = []
    for mod_name, pip_spec, obrigatorio in lista:
        ok = importlib.util.find_spec(mod_name) is not None
        item = {"modulo": mod_name, "pip": pip_spec, "obrigatorio": obrigatorio, "instalado": ok}
        if ok:
            instalados.append(item)
        else:
            faltando.append(item)
    return {
        "todos_obrigatorios_ok": all(not x["obrigatorio"] for x in faltando),
        "instalados": instalados,
        "faltando": faltando,
    }


def garantir_pacotes_python(auto_install=True, silencioso=False):
    """Instala automaticamente quaisquer pacotes Python faltantes via pip."""
    status = verificar_pacotes_python()
    if not status["faltando"] or not auto_install:
        return status

    a_instalar = [x["pip"] for x in status["faltando"]]
    if not silencioso:
        print(f"[AUTO-DEPS] Instalando pacotes Python ausentes: {', '.join(a_instalar)}", flush=True)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + a_instalar
    try:
        subprocess.run(cmd, check=True, timeout=600)
    except Exception as e:
        if not silencioso:
            print(f"[AUTO-DEPS] Aviso ao instalar pacotes via pip: {e}", flush=True)
    return verificar_pacotes_python()


def verificar_binarios_sistema():
    """Verifica ferramentas de sistema (ffmpeg, captura de tela, ollama, adb)."""
    bins = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "curl": shutil.which("curl") is not None,
        "ollama": shutil.which("ollama") is not None,
        "adb": detectar_adb() is not None,
    }
    if IS_LINUX:
        bins["grim"] = shutil.which("grim") is not None
        bins["wl_copy"] = shutil.which("wl-copy") is not None
    return bins


def instalar_dependencias_sistema(dry_run=False):
    """Instala automaticamente dependências de sistema operacional quando ausentes."""
    bins = verificar_binarios_sistema()
    faltando = [k for k, ok in bins.items() if not ok and k in ("ffmpeg", "curl", "grim")]
    if not faltando:
        return {"ok": True, "acao": "nenhuma_necessaria", "binarios": bins}

    cmd = None
    if IS_WINDOWS:
        if shutil.which("winget"):
            cmd = ["winget", "install", "-e", "--id", "Gyan.FFmpeg", "--accept-package-agreements", "--accept-source-agreements"]
    elif IS_LINUX:
        ger = detectar_distro_linux()
        if ger == "pacman":
            pacotes = ["ffmpeg", "curl"] + (["grim", "wl-clipboard"] if not bins.get("grim") else [])
            cmd = ["sudo", "pacman", "-S", "--needed", "--noconfirm"] + pacotes
        elif ger == "apt":
            pacotes = ["ffmpeg", "curl"] + (["grim", "wl-clipboard"] if not bins.get("grim") else [])
            cmd = ["sudo", "apt-get", "install", "-y"] + pacotes
        elif ger == "dnf":
            pacotes = ["ffmpeg", "curl"] + (["grim", "wl-clipboard"] if not bins.get("grim") else [])
            cmd = ["sudo", "dnf", "install", "-y"] + pacotes

    if dry_run or not cmd:
        return {"ok": True, "modo": "dry_run" if dry_run else "manual", "comando_sugerido": cmd, "faltando": faltando}

    try:
        subprocess.run(cmd, check=False, timeout=300)
    except Exception as e:
        return {"ok": False, "erro": str(e), "comando": cmd}
    return {"ok": True, "acao": "instalado", "binarios": verificar_binarios_sistema()}


def verificar_modelos():
    """Verifica se os modelos ONNX locais estão presentes em models/."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(os.path.join(MODELS_DIR, "whisper"), exist_ok=True)
    presentes = {}
    for arq in ("yunet.onnx", "sface_2021dec.onnx", "yolox_nano.onnx", "hand_landmark_full.tflite", "palm_detection_full.tflite"):
        p = os.path.join(MODELS_DIR, arq)
        presentes[arq] = os.path.exists(p) and os.path.getsize(p) > 1024
    return {
        "diretorio": MODELS_DIR,
        "modelos": presentes,
        "todos_essenciais_ok": all(presentes.get(k, False) for k in MODELOS_ESSENCIAIS),
    }


def garantir_modelos(auto_download=True):
    """Baixa modelos ONNX essenciais caso algum não esteja presente."""
    st = verificar_modelos()
    if st["todos_essenciais_ok"] or not auto_download:
        return st
    for arq, url in MODELOS_ESSENCIAIS.items():
        dest = os.path.join(MODELS_DIR, arq)
        if not os.path.exists(dest) or os.path.getsize(dest) <= 1024:
            try:
                print(f"[AUTO-DEPS] Baixando modelo neural {arq}...", flush=True)
                urllib.request.urlretrieve(url, dest + ".tmp")
                os.replace(dest + ".tmp", dest)
            except Exception as e:
                print(f"[AUTO-DEPS] Falha ao baixar {arq}: {e}", flush=True)
    return verificar_modelos()


def relatorio_completo():
    """Gera relatório completo de prontidão do sistema."""
    py_st = verificar_pacotes_python()
    bin_st = verificar_binarios_sistema()
    mod_st = verificar_modelos()
    return {
        "ok": py_st["todos_obrigatorios_ok"] and mod_st["todos_essenciais_ok"],
        "empresa": "Integra Code",
        "sistema": {
            "os": sys.platform,
            "release": platform.release(),
            "python": sys.version.split()[0],
            "arquitetura": platform.machine(),
        },
        "python_deps": py_st,
        "binarios": bin_st,
        "modelos": mod_st,
    }


def bootstrap_completo(auto_install_python=True, auto_download_models=True):
    """Executa toda a cadeia de verificação e auto-reparo antes de iniciar o daemon."""
    garantir_pacotes_python(auto_install=auto_install_python, silencioso=False)
    garantir_modelos(auto_download=auto_download_models)
    try:
        import memoria_zero
        memoria_zero.inicializar_do_zero(forcar=False)
    except Exception as e:
        print(f"[AUTO-DEPS] Aviso ao inicializar memória: {e}", flush=True)
    return relatorio_completo()


def main():
    parser = argparse.ArgumentParser(description="Instalador Automático de Dependências — F.R.I.D.A.Y. (Integra Code)")
    parser.add_argument("--check", action="store_true", help="Apenas verifica dependências e imprime JSON")
    parser.add_argument("--install-all", action="store_true", help="Instala pacotes Python, binários de sistema e modelos ONNX")
    parser.add_argument("--dry-run", action="store_true", help="Simula instalação de pacotes de sistema sem executar sudo")
    args = parser.parse_args()

    if args.install_all:
        instalar_dependencias_sistema(dry_run=args.dry_run)
        res = bootstrap_completo(auto_install_python=not args.dry_run, auto_download_models=not args.dry_run)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.check:
        print(json.dumps(relatorio_completo(), indent=2, ensure_ascii=False))
        return

    res = bootstrap_completo()
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
