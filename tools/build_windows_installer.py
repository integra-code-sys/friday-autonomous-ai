#!/usr/bin/env python3
"""Script de empacotamento do Instalador Executável (.exe) da F.R.I.D.A.Y. para Windows.
Gera um instalador .exe autocontido e autônomo baseado no módulo oficial 7z.sfx (GUI Win32 PE32).

O instalador:
1. Extrai todos os arquivos da F.R.I.D.A.Y. (daemon, memory, models, shell, scripts).
2. Executa automaticamente o setup_windows.bat em segundo plano ou interface gráfica.
3. Cria o ambiente virtual Python (.venv) no Windows e instala todas as dependências.
4. Configura a rede mesh autônoma de 3 nós (Workstation Linux, PC Windows, Servidor).
5. Cria atalhos na Área de Trabalho e ativa a Inicialização Automática com o Windows.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SFX_BIN = os.path.join(HERE, "sfx", "7z.sfx")
OUTPUT_EXE = os.path.join(ROOT, "Instalador_Friday_Windows.exe")

# Backups e lixo que nunca vão para o instalador: *.bak, *.v12bak, *.v_agbak, *.f9bak, *.f9b2, face.frag.v2, assets.v1bak/...
LIXO = re.compile(r"(bak|\.v\d+|\.f9b2|\.pyc|\.tmp|\.log|\.sock)$")
# Dados pessoais do dono que moram fora de memory/: biometria de voz (embeddings) e APKs com ela embutida em assets/
PRIVADOS = {"voz_dono.json"}

# memory/ do instalador: SÓ templates limpos gerados aqui (os arquivos reais do dono nunca são copiados)
MEMORIA_LIMPA = {
    "remoto.json": {"token": ""},                  # remoto.config() gera um token exclusivo no 1º uso desta instalação
    "peers.json": {"peers": []},                   # sem IPs/IDs da rede do dono; sync_mesh descobre pares por UDP
    "profile.json": {"nome": None, "fatos": {}, "session": None, "ultima_vez": 0, "conversas": 0},
    "politica.json": {"regras_permanentes": []},   # prom_ops completa com DEFAULT_POLICY
    "habilidades.json": {"itens": []},
}


def _ignorar(_dir, nomes):
    """Filtro do copytree: backups, caches, APKs (o /apk do remoto.py serve o da pasta comercial) e dados privados."""
    return [n for n in nomes if n == "__pycache__" or LIXO.search(n) or n in PRIVADOS or n.endswith(".apk")]


def _token_real():
    """Token do dono (memory/remoto.json), só para comparação; nunca é impresso nem empacotado."""
    try:
        return (json.load(open(os.path.join(ROOT, "memory", "remoto.json"))).get("token") or "").encode()
    except Exception:
        return b""


def _copiar_sem_token(src, dest_dir):
    """Copia um script de raiz; se ele tiver o token real embutido (ex.: setup_windows.bat), grava a cópia com token vazio."""
    tok = _token_real()
    with open(src, "rb") as f:
        dados = f.read()
    if len(tok) >= 8 and tok in dados:
        print(f"  [AVISO] {os.path.basename(src)} tem o token real do dono embutido; empacotado com token vazio (corrija a origem)")
        with open(os.path.join(dest_dir, os.path.basename(src)), "wb") as f:
            f.write(dados.replace(tok, b""))
        shutil.copystat(src, os.path.join(dest_dir, os.path.basename(src)))
    else:
        shutil.copy2(src, dest_dir)


def _auditar(staging):
    """Barreira final: lista o que vazaria (token real, bancos, conversas, voz do dono). Vazio = pacote limpo."""
    tok = _token_real()
    problemas = []
    for base, _dirs, arqs in os.walk(staging):
        for n in arqs:
            p = os.path.join(base, n)
            rel = os.path.relpath(p, staging)
            if n in PRIVADOS or n.endswith((".sqlite", ".sqlite-wal", ".sqlite-shm", ".jsonl")) or LIXO.search(n):
                problemas.append(f"{rel}: arquivo privado/backup")
                continue
            if n.endswith(".apk"):
                try:
                    if any("voz_dono" in i for i in zipfile.ZipFile(p).namelist()):
                        problemas.append(f"{rel}: APK com assets/voz_dono.json")
                except zipfile.BadZipFile:
                    pass
            if len(tok) >= 8:
                with open(p, "rb") as f:
                    if tok in f.read():
                        problemas.append(f"{rel}: contém o token real do dono")
    try:
        if json.load(open(os.path.join(staging, "memory", "remoto.json"))).get("token"):
            problemas.append("memory/remoto.json: token não está vazio")
    except Exception:
        pass
    return problemas


def build(output_exe=OUTPUT_EXE):
    print("=======================================================")
    print("  GERADOR DO INSTALADOR WINDOWS (.EXE) - F.R.I.D.A.Y.")
    print("=======================================================")

    if not os.path.exists(SFX_BIN):
        print(f"[ERRO] Módulo SFX Windows não encontrado em {SFX_BIN}")
        return False
    if not shutil.which("7z"):
        print("[ERRO] 7-Zip (comando '7z') não encontrado no PATH.")
        return False
    output_exe = os.path.abspath(output_exe)
    oficial = output_exe == os.path.abspath(OUTPUT_EXE)   # saída customizada não sobrescreve os .exe do projeto

    work_dir = tempfile.mkdtemp(prefix="friday_win_build_")   # staging + payload + config num diretório privado
    staging_dir = os.path.join(work_dir, "staging")
    os.makedirs(staging_dir)
    try:
        print("\n[1/4] Coletando arquivos da aplicação...")

        # 1. Daemon (somente arquivos ativos, excluindo backups e cache)
        daemon_dest = os.path.join(staging_dir, "daemon")
        os.makedirs(daemon_dest, exist_ok=True)
        for py_file in glob.glob(os.path.join(ROOT, "daemon", "*.py")):
            if not LIXO.search(os.path.basename(py_file)):
                shutil.copy2(py_file, daemon_dest)
        # Copia a interface web, os quadros Mark 85 e o construtor No-Code (sem backups, APKs e biometria do dono)
        for sub in ("web", "construtor_web", "audio"):
            sub_src = os.path.join(ROOT, "daemon", sub)
            if os.path.exists(sub_src):
                print(f"  + daemon/{sub}")
                shutil.copytree(sub_src, os.path.join(daemon_dest, sub), dirs_exist_ok=True, ignore=_ignorar)
        # Copia o script de controle pc se existir
        pc_src = os.path.join(ROOT, "daemon", "pc")
        if os.path.exists(pc_src):
            shutil.copy2(pc_src, daemon_dest)
        # APK comercial limpo no caminho que o remoto.web_apk procura (/apk)
        apk_src = os.path.join(ROOT, "friday-commercial-github", "android", "friday-commercial.apk")
        if os.path.exists(apk_src):
            apk_dest = os.path.join(staging_dir, "friday-commercial-github", "android")
            os.makedirs(apk_dest, exist_ok=True)
            shutil.copy2(apk_src, apk_dest)

        # 2. Memory: templates limpos (nunca os arquivos reais: remoto.json tem o token do dono, peers/profile dados pessoais)
        mem_dest = os.path.join(staging_dir, "memory")
        os.makedirs(mem_dest, exist_ok=True)
        for nome, conteudo in MEMORIA_LIMPA.items():
            with open(os.path.join(mem_dest, nome), "w", encoding="utf-8") as f:
                json.dump(conteudo, f, ensure_ascii=False, indent=1)

        # 3. Modelos essenciais de visão e detecção
        models_dest = os.path.join(staging_dir, "models")
        os.makedirs(models_dest, exist_ok=True)
        modelos_essenciais = [
            "yunet.onnx",
            "palm_detection_mediapipe_2023feb.onnx",
            "handpose_estimation_mediapipe_2023feb.onnx",
            "pose_estimation_mediapipe_2023mar.onnx",
            "face_recognition_sface.onnx",
            "object_yolox.onnx"
        ]
        for m in modelos_essenciais:
            src = os.path.join(ROOT, "models", m)
            if os.path.exists(src):
                print(f"  + Modelo: {m} ({os.path.getsize(src) // 1024} KB)")
                shutil.copy2(src, models_dest)

        # 4. Shell / Interface
        shell_src = os.path.join(ROOT, "shell")
        shell_dest = os.path.join(staging_dir, "shell")
        if os.path.exists(shell_src):
            shutil.copytree(shell_src, shell_dest, ignore=_ignorar)

        # 5. Scripts principais de Windows (+ CLI prom-orquestra -> daemon/orquestra_geral.py)
        for script in ("Friday.bat", "Friday_WSL.bat", "install_wsl.bat", "install_windows.bat", "Friday_Config.bat", "start_friday_silent.vbs", "setup_windows.bat", "uninstall.bat", "requirements-win.txt", "run.sh", "prom-orquestra"):
            src = os.path.join(ROOT, script)
            if os.path.exists(src):
                _copiar_sem_token(src, staging_dir)

        # 6. Manual em Markdown para o usuário
        wp = os.path.join(ROOT, "installer", "wallpaper_friday.jpg")          # 19/10: setup_windows.bat aplica como papel de parede
        if os.path.exists(wp):
            os.makedirs(os.path.join(staging_dir, "installer"), exist_ok=True)
            shutil.copy2(wp, os.path.join(staging_dir, "installer"))

        readme_path = os.path.join(staging_dir, "LEIAME_WINDOWS.txt")
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write("""F.R.I.D.A.Y. - Projeto Prometheus (Versão Windows)
===================================================

Como Usar:
1. Este pacote foi instalado de forma 100% autônoma.
2. Para iniciar a Friday com console visível: dê dois cliques em 'Friday.bat'.
3. Para rodar em segundo plano: dê dois cliques em 'start_friday_silent.vbs'.
4. A Friday já inicia automaticamente com o Windows através do atalho em Inicializar.

Sincronização Mesh de 3 Nós:
- Este nó Windows sincroniza automaticamente com a Workstation Linux e com o Servidor.
- Quando qualquer um dos nós é desligado e religado, os dados (agenda, conversas,
  fatos da memória, tarefas e lições) são unificados automaticamente sem perder nada.
""")

        problemas = _auditar(staging_dir)
        if problemas:
            print("[ERRO] Dados privados no pacote, build abortado:")
            for p in problemas:
                print("  -", p)
            return False

        print("\n[2/4] Compactando pacote da aplicação com 7-Zip LZMA2...")
        archive_7z = os.path.join(work_dir, "friday_app_payload.7z")

        # Compacta a pasta de staging usando 7z
        cmd_7z = ["7z", "a", "-t7z", "-m0=lzma2", "-mx=6", "-mfb=64", "-md=32m", "-ms=on", archive_7z, f"{staging_dir}/*"]
        r = subprocess.run(cmd_7z, capture_output=True, text=True)
        if r.returncode != 0:
            print("[ERRO] Falha ao compactar arquivos:", r.stderr)
            return False

        sz_mb = os.path.getsize(archive_7z) / (1024 * 1024)
        print(f"  Pacote compactado com sucesso: {sz_mb:.1f} MB")

        print("\n[3/4] Gerando cabeçalho de configuração SFX...")
        sfx_config = os.path.join(work_dir, "sfx_config.txt")
        with open(sfx_config, "w", encoding="utf-8") as f:
            f.write(""";!@Install@!UTF-8!
Title="F.R.I.D.A.Y. - Centro de Comando Stark (Mark 85)"
BeginPrompt="Deseja instalar e iniciar a F.R.I.D.A.Y. (Projeto Prometheus) no seu computador Windows?\\n\\nO sistema configurará a IA local com visual holográfico Mark 85 idêntico ao Linux, sincronização autônoma multi-nó e iniciará a assistente imediatamente."
Progress="yes"
RunProgram="setup_windows.bat"
;!@InstallEnd@!
""")

        print("\n[4/4] Montando executável instalador final (.exe)...")
        os.makedirs(os.path.dirname(output_exe), exist_ok=True)
        with open(output_exe, "wb") as out_f:
            # 1. Módulo SFX executável PE32
            with open(SFX_BIN, "rb") as sfx_f:
                shutil.copyfileobj(sfx_f, out_f)
            # 2. Configuração de extração
            with open(sfx_config, "rb") as cfg_f:
                shutil.copyfileobj(cfg_f, out_f)
            # 3. Payload 7z
            with open(archive_7z, "rb") as pld_f:
                shutil.copyfileobj(pld_f, out_f)

        setup_exe = None
        if oficial:
            # Copia como Setup_Friday.exe para facilidade de acesso
            setup_exe = os.path.join(ROOT, "Setup_Friday.exe")
            shutil.copy2(output_exe, setup_exe)

            # Sincroniza também na pasta comercial para commit e releases
            com_dir = os.path.join(ROOT, "friday-commercial-github")
            if os.path.exists(com_dir):
                shutil.copy2(output_exe, os.path.join(com_dir, "Instalador_Friday_Windows.exe"))
                shutil.copy2(output_exe, os.path.join(com_dir, "Setup_Friday.exe"))

        exe_size_mb = os.path.getsize(output_exe) / (1024 * 1024)
        print(f"\n[SUCESSO] Instalador gerado com êxito:")
        print(f"  Instalador Principal: {output_exe}")
        if setup_exe:
            print(f"  Setup Alternativo:    {setup_exe}")
        print(f"  Tamanho: {exe_size_mb:.2f} MB")
        print("=======================================================")
        return True
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Gera o instalador .exe (7z SFX) da F.R.I.D.A.Y. para Windows.")
    ap.add_argument("--saida", default=os.environ.get("FRIDAY_INSTALLER_OUT", OUTPUT_EXE),
                    help="caminho do .exe gerado (padrão: Instalador_Friday_Windows.exe na raiz, que também é copiado "
                         "para Setup_Friday.exe e friday-commercial-github/; outro caminho não toca nesses arquivos)")
    ok = build(ap.parse_args().saida)
    sys.exit(0 if ok else 1)
