#!/usr/bin/env python3
"""Roda o catálogo de 50 tarefas compostas (memory/bancada/catalogo.json) no agente geral.
  bancada_cat.py linux|android [N]     (N = quantas, padrão todas)   ·   resultado: memory/bancada/cat_<plataforma>_*.json
Falhas vão para a fila da autocura (autocura.py). 'concluiu' = o agente terminou o pedido sem frase de desistência;
a conferência objetiva de cada tarefa está no campo 'verificacao' do catálogo."""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
FALHA = re.compile(r"(?i)não terminei|não consegui|não foi possível|meu modelo falhou|erro")


def main(plat, n):
    import agente_geral
    cat = json.load(open(os.path.join(ROOT, "memory", "bancada", "catalogo.json")))[plat][:n]
    res = []
    for t in cat:
        pedido = t["pedido"] + (" (no celular)" if plat == "android" and "no celular" not in t["pedido"].lower() else "")
        t0 = time.time()
        try:
            r = agente_geral.resolver(pedido)
            ok = bool(r["ok"]) and not FALHA.search(r["fala"])
            fala = r["fala"]
        except Exception as e:
            ok, fala = False, "ERRO " + str(e)[:150]
        print(f"{t['id']} {'OK ' if ok else 'FALHA'} {time.time() - t0:5.0f}s {fala[:110]!r}", flush=True)
        res.append({"id": t["id"], "ok": ok, "s": round(time.time() - t0), "fala": fala[:300]})
        json.dump(res, open(os.path.join(ROOT, "memory", "bancada", f"cat_{plat}_{time.strftime('%Y%m%d')}.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{sum(r['ok'] for r in res)}/{len(res)} concluídas")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 50)
