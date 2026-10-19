#!/usr/bin/env python3
"""Bancada de testes do agente geral da F.R.I.D.A.Y.: pedidos reais (simples e compostos) pelo MESMO caminho da voz
(socket do daemon), com conferência do resultado de verdade (resposta, arquivo, janela, agenda) e tempo.

  bancada.py                 roda tudo
  bancada.py lista           mostra as tarefas
  bancada.py ID [ID...]      roda só essas (ex.: conta capital everest)
Resultado: tabela no terminal + memory/bancada/AAAA-MM-DD_HHMM.json (compara rodadas)."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOCK = os.environ.get("XDG_RUNTIME_DIR", "/tmp") + "/prometheus.sock"
CAIXA = os.path.expanduser("~/Documentos/FridayTeste")          # tudo que a bancada cria fica aqui
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def pedir(texto, limite=240):
    """manda o pedido como se fosse falado/digitado e junta as respostas até o 'done' do daemon."""
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(limite)
    s.connect(SOCK)
    s.sendall((json.dumps({"type": "chat", "text": texto, "files": []}) + "\n").encode())
    falas, eventos, t0 = [], [], time.time()
    trabalhou = False                     # o daemon só manda "done" no caminho do Claude CLI: fim = voltou a "idle" depois de trabalhar
    try:
        for linha in s.makefile():
            try:
                ev = json.loads(linha)
            except Exception:
                continue
            tp = ev.get("type")
            if tp == "text" and ev.get("role") != "user":
                falas.append(str(ev.get("text") or ""))
            elif tp not in ("audio", "mouth", "level", "vu"):
                eventos.append(tp + (":" + str(ev.get("state")) if tp == "state" else ""))
            if tp == "state":
                if ev.get("state") in ("thinking", "speaking", "listening_busy", "working"):
                    trabalhou = True
                elif ev.get("state") == "idle" and trabalhou and falas:
                    break
            if tp == "done" or time.time() - t0 > limite:
                break
    except socket.timeout:
        falas.append("[TEMPO ESGOTADO]")
    finally:
        s.close()
    return "\n".join(falas), eventos, time.time() - t0


def _janelas():
    try:
        return json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=5).stdout)
    except Exception:
        return []


def _arquivo_com(pasta, padrao, depois):
    """algum arquivo novo (mtime > depois) na pasta cujo conteúdo case com o padrão."""
    if not os.path.isdir(pasta):
        return None
    for raiz, _, nomes in os.walk(pasta):
        for n in nomes:
            p = os.path.join(raiz, n)
            if os.path.getmtime(p) < depois:
                continue
            try:
                txt = open(p, encoding="utf-8", errors="ignore").read() if not n.endswith(".docx") else _docx(p)
            except Exception:
                continue
            if re.search(padrao, txt, re.I | re.S):
                return p
    return None


def _docx(p):
    import zipfile
    return re.sub(r"<[^>]+>", " ", zipfile.ZipFile(p).read("word/document.xml").decode("utf-8", "ignore"))


def _nega(resp):
    return re.search(r"não consegui|não foi possível|não sei|erro|falhou|tempo esgotado|indisponível", resp, re.I)


# ------------------------------------------------------------------ tarefas
def _agenda_amanha_15(ctx):
    import prom_ops as ops
    alvo = time.mktime(time.strptime(time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400)) + " 15:00", "%Y-%m-%d %H:%M"))
    for i in ops.agenda_all():
        if "dentista de teste" in (i.get("titulo") or "").lower() and i.get("criado", 0) >= ctx["t0"] - 5:
            ctx["agenda_id"] = i["id"]
            return abs(float(i.get("inicio", 0)) - alvo) < 60, "marcou " + time.strftime("%d/%m %H:%M", time.localtime(i["inicio"]))
    return False, "nada na agenda"


def _limpa_agenda(ctx):
    if ctx.get("agenda_id"):
        import prom_ops as ops
        ops.agenda_remover(ctx["agenda_id"])


def _calc_aberta(ctx):
    for _ in range(20):
        for w in _janelas():
            if re.search(r"calc|qalculate", (w.get("app_id") or "") + " " + (w.get("title") or ""), re.I):
                ctx["janela"] = w["id"]
                return True, "janela " + (w.get("app_id") or "")
        time.sleep(1)
    return False, "nenhuma calculadora aberta"


def _fecha_janela(ctx):
    if ctx.get("janela"):
        subprocess.run(["niri", "msg", "action", "close-window", "--id", str(ctx["janela"])], timeout=5)


def _hora_certa(resp, ctx):
    h = time.localtime(ctx["t0"]).tm_hour
    ext = ["meia-noite", "uma", "duas", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "meio-dia",
           "treze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove", "vinte", "vinte e uma", "vinte e duas", "vinte e três"]
    ok = re.search(rf"\b0?{h}\s*(h\b|:|horas|e\s+\d)", resp) or re.search(rf"\b0?{h % 12 or 12}\s*(h\b|:|horas|e\s+\d)", resp) or ext[h] in resp.lower()
    return bool(ok), "hora esperada ~" + str(h)


TAREFAS = [
    # id, tipo, pedido, conferência(resp, ctx) -> (ok, motivo) ; opcional: limpar(ctx)
    {"id": "conta", "tipo": "simples", "pedido": "quanto é 17 vezes 23?",
     "ok": lambda r, c: (bool(re.search(r"\b391\b", r)), "esperado 391")},
    {"id": "capital", "tipo": "simples", "pedido": "qual é a capital da Austrália?",
     "ok": lambda r, c: (bool(re.search(r"canberra", r, re.I)), "esperado Canberra")},
    {"id": "hora", "tipo": "simples", "pedido": "que horas são?", "ok": _hora_certa},
    {"id": "iphone", "tipo": "pesquisa", "pedido": "pesquise em que ano foi lançado o primeiro iPhone",
     "ok": lambda r, c: (bool(re.search(r"\b2007\b", r)), "esperado 2007")},
    {"id": "dolar", "tipo": "pesquisa", "pedido": "qual a cotação do dólar hoje?",
     "ok": lambda r, c: (bool(re.search(r"\b[3-7][,.]\d{2}", r)) and not _nega(r), "valor R$ x,xx")},
    {"id": "clima", "tipo": "pesquisa", "pedido": "como está o tempo em São Paulo agora?",
     "ok": lambda r, c: (bool(re.search(r"°|graus|chuv|sol|nublad|garoa|tempo", r, re.I)) and not _nega(r), "clima com dado")},
    {"id": "g1", "tipo": "navegacao", "pedido": "abra o site do g1 e me diga qual é a manchete principal",
     "ok": lambda r, c: (len(r) > 30 and not _nega(r), "manchete lida")},
    {"id": "calc", "tipo": "app", "pedido": "abra a calculadora", "ok": lambda r, c: _calc_aberta(c), "limpar": _fecha_janela},
    {"id": "pasta", "tipo": "arquivo", "pedido": f"crie uma pasta chamada TesteFriday dentro de {CAIXA}",
     "ok": lambda r, c: (os.path.isdir(os.path.join(CAIXA, "TesteFriday")), "pasta existe?")},
    {"id": "agenda", "tipo": "agenda", "pedido": "marque na agenda amanhã às 15h dentista de teste",
     "ok": lambda r, c: _agenda_amanha_15(c), "limpar": _limpa_agenda},
    {"id": "everest", "tipo": "composta", "pedido": f"pesquise a altura do Monte Everest e salve a resposta num arquivo everest.txt em {CAIXA}",
     "ok": lambda r, c: (bool(_arquivo_com(CAIXA, r"8[.,]?8[4-5]\d", c["t0"])), "arquivo com 8.84x m")},
    {"id": "populacao", "tipo": "composta", "pedido": "pesquise a população do Brasil e a da Argentina e me diga qual é maior e a diferença aproximada",
     "ok": lambda r, c: (bool(re.search(r"brasil", r, re.I) and re.search(r"\d", r)) and not _nega(r), "comparação com números")},
    {"id": "dicas", "tipo": "composta", "pedido": f"pesquise 3 dicas de produtividade e crie um documento com elas em {CAIXA}",
     "ok": lambda r, c: (bool(_arquivo_com(CAIXA, r"(?:.*\n){2,}|1.*2.*3", c["t0"])), "documento novo com as dicas")},
    {"id": "rascunho", "tipo": "mensagem", "pedido": "escreva uma mensagem curta para o João dizendo que vou me atrasar 10 minutos, mas não envie",
     "ok": lambda r, c: (bool(re.search(r"atras", r, re.I)) and not re.search(r"\benviei\b|\benviada\b", r, re.I), "rascunho sem envio")},
]


def pedir_agente(texto, limite=600):
    """mesmo pedido direto no agente geral novo (agente_geral.resolver), sem passar pelo daemon."""
    import agente_geral
    t0 = time.time()
    r = agente_geral.resolver(texto, mostrar=True)
    return r.get("fala") or "", [p["acao"] for p in r.get("passos", [])], time.time() - t0


def rodar(ids=None, agente=False):
    os.makedirs(CAIXA, exist_ok=True)
    res = []
    for t in TAREFAS:
        if ids and t["id"] not in ids:
            continue
        ctx = {"t0": time.time()}
        print(f"→ {t['id']:<10} {t['pedido'][:70]}", flush=True)
        try:
            resp, evs, dt = (pedir_agente if agente else pedir)(t["pedido"])
            ok, motivo = t["ok"](resp, ctx)
        except Exception as e:
            resp, evs, dt, ok, motivo = "", [], time.time() - ctx["t0"], False, f"erro da bancada: {e}"
        try:
            if t.get("limpar"):
                t["limpar"](ctx)
        except Exception:
            pass
        res.append({"id": t["id"], "tipo": t["tipo"], "ok": bool(ok), "s": round(dt, 1), "motivo": motivo,
                    "resposta": resp[:600], "eventos": (evs if agente else sorted(set(evs)))[:30]})
        print(f"  {'OK   ' if ok else 'FALHA'} {dt:6.1f}s  {motivo} | {resp[:140]!r}", flush=True)
        time.sleep(2)
    shutil.rmtree(CAIXA, ignore_errors=True)
    n_ok = sum(r["ok"] for r in res)
    print(f"\nRESULTADO: {n_ok}/{len(res)} ok · tempo médio {sum(r['s'] for r in res) / max(1, len(res)):.1f}s")
    for tp in sorted({r["tipo"] for r in res}):
        g = [r for r in res if r["tipo"] == tp]
        print(f"  {tp:<10} {sum(r['ok'] for r in g)}/{len(g)}")
    pasta = os.path.join(ROOT, "memory", "bancada")
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, time.strftime("%Y-%m-%d_%H%M") + ("_agente" if agente else "_daemon") + ".json")
    json.dump({"quando": time.strftime("%Y-%m-%d %H:%M"), "caminho": "agente_geral" if agente else "daemon", "ok": n_ok, "total": len(res), "tarefas": res}, open(arq, "w"), ensure_ascii=False, indent=1)
    print("salvo em", arq)
    return res


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "lista":
        for t in TAREFAS:
            print(f"{t['id']:<10} {t['tipo']:<10} {t['pedido']}")
        sys.exit(0)
    ag = "--agente" in a
    a = [x for x in a if x != "--agente"]
    rodar(set(a) or None, agente=ag)
