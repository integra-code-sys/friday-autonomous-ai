"""MODO DEV da F.R.I.D.A.Y.: eventos ao vivo de tudo que ela ouve, pensa e faz (painel QML shell/DevPanel.qml).

Evento (vai aos clientes LOCAIS do socket como {"type": "dev", ...}; nunca ao app do celular):
  {"t": epoch, "hora": "HH:MM:SS", "fonte": "voz|cerebro|claude|camera|tempo|sistema", "tipo": "...", "texto": "...", ...extras}
Fontes:
  - ganchos diretos: emitir(...) e claude(ev) (stream-json do Claude CLI, com diff de Edit/Write);
  - logs já existentes, lidos em tempo real (sem mexer em quem escreve): /tmp/friday-cerebro.log (pedido/passo/final),
    /tmp/friday-timing.log (STT/cérebro/latência), /tmp/friday-ptz.log (câmera), /tmp/friday-tts.log (voz).
Tudo passa por mascarar(): senhas, tokens, chaves e caminhos de Secrets/ não saem. Histórico em memory/dev/AAAA-MM-DD.jsonl.
"""
import collections, difflib, json, os, re, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "memory", "dev")
_buf = collections.deque(maxlen=400)
_lock = threading.Lock()
_sink = [None]                      # função(evento) que publica (definida pelo prometheus.py)
estado = {"on": False}

_SEGREDO = [
    (re.compile(r"(?i)\b(senha|password|passwd|token|api[_-]?key|secret|bearer|pin|authorization)\b(\s*[:=]\s*|\s+)(\S+)"), r"\1\2•••"),
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,}|hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9\-]{10,})"), "•••"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "•••"),                       # blobs longos (tokens/hashes)
    (re.compile(r"(?i)[^\s'\"]*/Secrets/[^\s'\"]*"), "[Secrets]"),
    (re.compile(r"(?i)\b(remoto|celular|voz_dono)\.json\b"), "[privado]"),
]


def mascarar(v):
    if isinstance(v, str):
        for rx, rep in _SEGREDO:
            v = rx.sub(rep, v)
        return v
    if isinstance(v, dict):
        return {k: ("•••" if re.search(r"(?i)senha|password|token|secret|key|pin", str(k)) else mascarar(x)) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [mascarar(x) for x in v]
    return v


def emitir(fonte, tipo, texto="", **extra):
    ev = {"t": round(time.time(), 3), "hora": time.strftime("%H:%M:%S"), "fonte": fonte, "tipo": tipo, "texto": str(texto)[:4000]}
    ev.update(extra)
    ev = mascarar(ev)
    with _lock:
        _buf.append(ev)
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(os.path.join(DIR, time.strftime("%Y-%m-%d") + ".jsonl"), "a") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass
    s = _sink[0]
    if s is not None:
        try:
            s(ev)
        except Exception:
            pass
    return ev


def historico(n=200):
    with _lock:
        return list(_buf)[-n:]


# ------------------------------------------------------------------ Claude CLI (stream-json)
def claude(ev, origem="claude"):
    """um evento do stream-json do `claude -p --output-format stream-json`: ferramenta, texto, resultado e diffs."""
    try:
        tp = ev.get("type")
        if tp == "system" and ev.get("subtype") == "init":
            emitir(origem, "inicio", f"sessão {str(ev.get('session_id', ''))[:8]} · modelo {ev.get('model', '?')}")
        elif tp == "assistant":
            for bl in ev.get("message", {}).get("content", []):
                if bl.get("type") == "tool_use":
                    inp = bl.get("input", {}) or {}
                    nome = bl.get("name", "?")
                    desc = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("url") or inp.get("description") or ""
                    extra = {}
                    if nome in ("Edit", "MultiEdit") and inp.get("file_path"):
                        partes = inp.get("edits") or [{"old_string": inp.get("old_string", ""), "new_string": inp.get("new_string", "")}]
                        diff = []
                        for p in partes[:6]:
                            diff += list(difflib.unified_diff(str(p.get("old_string", "")).splitlines(), str(p.get("new_string", "")).splitlines(),
                                                              lineterm="", n=1))[2:]
                        extra["diff"] = "\n".join(diff)[:3000]
                        emitir(origem, "edicao", f"{nome} {inp['file_path']}", **extra)
                        continue
                    if nome == "Write" and inp.get("file_path"):
                        cont = str(inp.get("content", ""))
                        emitir(origem, "edicao", f"Write {inp['file_path']} ({len(cont.splitlines())} linhas)", diff="+" + "\n+".join(cont.splitlines()[:40])[:3000])
                        continue
                    emitir(origem, "ferramenta", f"{nome}: {str(desc)[:300]}", args=json.dumps(inp, ensure_ascii=False)[:1500])
                elif bl.get("type") == "thinking" and str(bl.get("thinking", "")).strip():
                    emitir(origem, "pensamento", bl["thinking"].strip()[:2000])
                elif bl.get("type") == "text" and str(bl.get("text", "")).strip():
                    emitir(origem, "texto", bl["text"].strip()[:2000])
        elif tp == "user":
            for bl in ev.get("message", {}).get("content", []) if isinstance(ev.get("message", {}).get("content"), list) else []:
                if bl.get("type") == "tool_result":
                    c = bl.get("content")
                    if isinstance(c, list):
                        c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
                    emitir(origem, "resultado", str(c or "")[:1200], erro=bool(bl.get("is_error")))
        elif tp == "result":
            emitir(origem, "fim", str(ev.get("result") or ev.get("subtype") or "")[:1500],
                   custo=ev.get("total_cost_usd"), dur_s=round((ev.get("duration_ms") or 0) / 1000, 1), turnos=ev.get("num_turns"))
    except Exception:
        pass


# ------------------------------------------------------------------ logs existentes -> eventos
_REGRAS = {
    "/tmp/friday-cerebro.log": [
        (re.compile(r"^\S+ PEDIDO (.*)"), "cerebro", "pedido"),
        (re.compile(r"^\S+ passo (\d+ \([\d.]+s\)) -> (.*)"), "cerebro", "passo"),
        (re.compile(r"^\S+ FINAL (.*)"), "cerebro", "final"),
        (re.compile(r"^\S+ (.*)"), "cerebro", "nota"),
    ],
    "/tmp/friday-timing.log": [
        (re.compile(r"^\S+ (STT=.*)"), "voz", "ouvi"),
        (re.compile(r"^\S+ (cérebro=.*)"), "tempo", "cerebro"),
        (re.compile(r"^\S+ (LATÊNCIA.*)"), "tempo", "latencia"),
    ],
    "/tmp/friday-ptz.log": [(re.compile(r"^\S+ (.*)"), "camera", "ptz")],
    "/tmp/friday-tts.log": [(re.compile(r"^(.*)"), "voz", "tts")],
}


def _seguir(caminho, regras):
    f, ino, pos, primeira = None, None, 0, True
    while True:
        try:
            st = os.stat(caminho)
            if f is None or st.st_ino != ino or st.st_size < pos:          # abriu, rodou (rename) ou truncou
                if f:
                    f.close()
                f = open(caminho, "r", errors="replace")
                ino = st.st_ino
                if primeira:
                    f.seek(0, 2)                                            # 1ª vez: só o que vier daqui em diante
                    primeira = False
                pos = f.tell()                                              # arquivo novo após rodar: lê do começo
            linha = f.readline()
            if not linha:
                time.sleep(0.4)
                continue
            pos = f.tell()
            linha = linha.rstrip("\n")
            for rx, fonte, tipo in regras:
                m = rx.match(linha)
                if m:
                    emitir(fonte, tipo, " — ".join(g for g in m.groups() if g))
                    break
        except FileNotFoundError:
            time.sleep(2)
        except Exception:
            time.sleep(2)


def iniciar(sink):
    _sink[0] = sink
    for caminho, regras in _REGRAS.items():
        threading.Thread(target=_seguir, args=(caminho, regras), daemon=True, name="dev-" + os.path.basename(caminho)).start()
    emitir("sistema", "inicio", "MODO DEV pronto: eventos de voz, cérebro, Claude CLI, câmera e tempos")
