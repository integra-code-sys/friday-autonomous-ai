#!/usr/bin/env python3
"""Autocura da F.R.I.D.A.Y.: quando o agente falha, o Claude CLI do terminal propõe a correção numa CÓPIA (staging),
a bateria rápida valida a cópia e, só se melhorar sem quebrar nada, a correção entra no código real (com backup).

  autocura.py fila                 mostra falhas registradas
  autocura.py curar [N]            cura até N falhas da fila (padrão 3)
  autocura.py loop                 cura em segundo plano quando há falhas (a cada 5 min)
  autocura.py reverter ARQUIVO     volta o backup mais recente de ARQUIVO

Limites de segurança: só mexe em ALVOS (daemon/agente_geral.py, navegador.py, visao.py); nunca em memory/, Secrets,
chaves, git ou rede; todo arquivo alterado tem backup .v_autocurabak; falha na validação = descarta a cópia."""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MEM = os.path.join(ROOT, "memory")
DIR = os.path.join(MEM, "autocura")
FILA = os.path.join(DIR, "fila.jsonl")
LOG = os.path.join(DIR, "log.jsonl")
STAGE = os.path.join(DIR, "staging")
ALVOS = ["agente_geral.py", "navegador.py", "visao.py"]
SMOKE = ["quanto é 17 vezes 23?", "qual é a capital da Austrália?"]      # nunca podem regredir
PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable
os.makedirs(DIR, exist_ok=True)


def registrar(pedido, fala, passos=None, origem="agente"):
    """chamada pelo agente quando não conclui: entra na fila de cura (sem duplicar o mesmo pedido)."""
    try:
        vistos = {json.loads(l).get("pedido") for l in open(FILA)} if os.path.exists(FILA) else set()
        if pedido in vistos:
            return
        with open(FILA, "a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "pedido": pedido, "fala": str(fala)[:400], "origem": origem,
                                "acoes": [p.get("acao") for p in (passos or [])][-12:]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _fila():
    return [json.loads(l) for l in open(FILA)] if os.path.exists(FILA) else []


def _log(**r):
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), **r}, ensure_ascii=False) + "\n")


def _rodar_pedido(base, pedido, limite=420):
    """roda UM pedido no agente que está em `base`/daemon -> (ok, fala)."""
    cod = ("import sys,json;sys.path.insert(0,%r);import agente_geral as a;r=a.resolver(%s);"
           "print('@@'+json.dumps({'ok':r['ok'],'fala':r['fala']},ensure_ascii=False))") % (os.path.join(base, "daemon"), repr(pedido))
    try:
        o = subprocess.run([PY, "-W", "ignore", "-c", cod], capture_output=True, text=True, timeout=limite, cwd=base).stdout
        j = json.loads(o.rsplit("@@", 1)[1])
        fala = j["fala"]
        bom = j["ok"] and not any(x in fala.lower() for x in ("não terminei", "não consegui", "não foi possível", "meu modelo falhou"))
        return bom, fala
    except Exception as e:
        return False, "erro: " + str(e)[:150]


def _montar_staging():
    shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(STAGE)
    shutil.copytree(HERE, os.path.join(STAGE, "daemon"), ignore=shutil.ignore_patterns("__pycache__", "*bak*", "*.pyc"))
    os.symlink(MEM, os.path.join(STAGE, "memory"))
    return STAGE


def curar_uma(item):
    pedido, fala = item["pedido"], item["fala"]
    _log(evento="inicio", pedido=pedido)
    stg = _montar_staging()
    prompt = (
        "Você mantém o agente geral da F.R.I.D.A.Y. (daemon/agente_geral.py nesta cópia de trabalho). Este pedido FALHOU:\n"
        f"PEDIDO: {pedido}\nRESULTADO: {fala}\nAÇÕES: {item.get('acoes')}\n\n"
        "Descubra a causa raiz lendo daemon/agente_geral.py (e navegador.py/visao.py se preciso) e CORRIJA com a menor mudança possível, "
        "de forma GERAL (não faça um caso especial para este pedido). Altere somente arquivos dentro de daemon/ desta cópia. "
        "Não mexa em memory/, não faça git. Confira que `python3 -c 'import agente_geral'` roda. Responda com 1 frase do que mudou.")
    try:
        r = subprocess.run(["claude", "-p", prompt, "--model", "sonnet", "--permission-mode", "acceptEdits",
                            "--allowedTools", "Read", "Edit", "Grep", "Glob", "Bash(python3 -c *)", "Bash(grep *)", "Bash(sed -n *)"],
                           capture_output=True, text=True, timeout=900, cwd=stg)
        resumo = (r.stdout or r.stderr)[-300:]
    except Exception as e:
        _log(evento="claude_falhou", erro=str(e)[:200])
        return False
    mudou = [a for a in ALVOS if os.path.exists(os.path.join(stg, "daemon", a))
             and open(os.path.join(stg, "daemon", a), "rb").read() != open(os.path.join(HERE, a), "rb").read()]
    if not mudou:
        _log(evento="sem_mudanca", pedido=pedido, resumo=resumo)
        return False
    ok, f2 = _rodar_pedido(stg, pedido)
    if not ok:
        _log(evento="descartado_nao_resolveu", pedido=pedido, arquivos=mudou, fala=f2[:200])
        return False
    for p in SMOKE:
        o, _ = _rodar_pedido(stg, p, 120)
        if not o:
            _log(evento="descartado_regressao", pedido=pedido, smoke=p)
            return False
    ts = time.strftime("%Y%m%d%H%M%S")
    for a in mudou:                                           # aplica com backup
        shutil.copy2(os.path.join(HERE, a), os.path.join(HERE, f"{a}.v_autocurabak{ts}"))
        shutil.copy2(os.path.join(stg, "daemon", a), os.path.join(HERE, a))
    _log(evento="CURADO", pedido=pedido, arquivos=mudou, resumo=resumo, backup=ts)
    return True


def curar(n=3):
    feitos, restantes = 0, []
    for it in _fila():
        if feitos < n and curar_uma(it):
            feitos += 1
        else:
            restantes.append(it)
    with open(FILA, "w") as f:
        for it in restantes:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    return feitos


def reverter(arq):
    bks = sorted(x for x in os.listdir(HERE) if x.startswith(arq + ".v_autocurabak"))
    if not bks:
        print("sem backup")
        return
    shutil.copy2(os.path.join(HERE, bks[-1]), os.path.join(HERE, arq))
    print("revertido para", bks[-1])


if __name__ == "__main__":
    a = sys.argv[1:] or ["fila"]
    if a[0] == "fila":
        for it in _fila():
            print(it["t"], it["pedido"][:80], "→", it["fala"][:80])
    elif a[0] == "curar":
        print("curados:", curar(int(a[1]) if len(a) > 1 else 3))
    elif a[0] == "loop":
        while True:
            if _fila():
                curar(3)
            time.sleep(300)
    elif a[0] == "reverter" and len(a) > 1:
        reverter(a[1])
