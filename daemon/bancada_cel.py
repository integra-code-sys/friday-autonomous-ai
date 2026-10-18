#!/usr/bin/env python3
"""Bancada do agente geral NO CELULAR (ponte de acessibilidade) + WhatsApp (contato 'integra code').
  bancada_cel.py            roda tudo     |   bancada_cel.py ID [ID...]   só esses
Cada tarefa vai direto no agente_geral.resolver; a conferência é a resposta + a tela do celular. Resultado em memory/bancada/cel_*.json"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TAREFAS = [
    {"id": "cel_config", "pedido": "no celular, abra as Configurações e me diga qual é a versão do Android",
     "ok": lambda r: bool(re.search(r"\b1[0-9]\b|android", r, re.I)) and not re.search(r"(?i)não consegui|não terminei|não foi possível", r)},
    {"id": "cel_pesq", "pedido": "no celular, abra o Chrome, pesquise a capital da França e me diga a resposta",
     "ok": lambda r: bool(re.search(r"paris", r, re.I))},
    {"id": "zap_pesq", "pedido": "pesquise a altura do Monte Everest e envie a resposta por WhatsApp para o contato Integra Code (WhatsApp Business do celular)",
     "ok": lambda r: bool(re.search(r"8[.,]?8[4-5]\d|enviei|enviada|aprova", r, re.I))},
    {"id": "zap_doc", "pedido": "pesquise 3 dicas de produtividade, crie um documento com elas em ~/Documentos/FridayTeste e envie o documento por WhatsApp para o contato Integra Code (WhatsApp Business do celular)",
     "ok": lambda r: bool(re.search(r"enviei|enviado|enviada|aprova", r, re.I))},
    {"id": "zap_ler", "pedido": "no celular, abra o WhatsApp, leia a última mensagem do contato Integra Code (WhatsApp Business do celular) e me diga o que ela diz",
     "ok": lambda r: len(r) > 20 and not re.search(r"(?i)não consegui|não terminei|falhou|não foi possível", r)},
]


def main(ids):
    import agente_geral
    res = []
    for t in TAREFAS:
        if ids and t["id"] not in ids:
            continue
        print("→", t["id"], t["pedido"], flush=True)
        t0 = time.time()
        try:
            r = agente_geral.resolver(t["pedido"], mostrar=True)
            fala = str(r.get("fala", ""))
            ok = bool(t["ok"](fala))
        except Exception as e:
            fala, ok = "ERRO " + type(e).__name__ + ": " + str(e)[:200], False
        print(f"  {'OK' if ok else 'FALHA'} {time.time() - t0:5.1f}s | {fala[:200]!r}", flush=True)
        res.append({"id": t["id"], "ok": ok, "s": round(time.time() - t0, 1), "fala": fala[:400]})
    os.makedirs(os.path.join(ROOT, "memory", "bancada"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "memory", "bancada", "cel_" + time.strftime("%Y-%m-%d_%H%M") + ".json"), "w"), ensure_ascii=False, indent=1)
    print(f"{sum(r['ok'] for r in res)}/{len(res)} OK")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
