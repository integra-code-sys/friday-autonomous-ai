"""Construtor No-Code da F.R.I.D.A.Y. (modo criação).

Fluxo: o dono pede por voz ("crie um botão de contato") -> o Claude CLI gera o elemento em segundo plano (HTML+CSS usando os
tokens do tema) -> o elemento entra na BIBLIOTECA visual -> o dono arrasta (mouse ou gestos) para a TELA de criação ->
"pode integrar" -> o Claude CLI incorpora a tela ao projeto escolhido (stack do projeto, ligações/rotas).

Servidor local: http://127.0.0.1:8765 (só loopback). Dados em memory/construtor/.
"""
import json, os, re, subprocess, threading, time, unicodedata, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "memory", "construtor")
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "construtor_web")
PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
MODEL = os.environ.get("PROMETHEUS_MODEL", "claude-sonnet-5-5")
_lock = threading.RLock()
_srv = {"httpd": None}
jobs = []                       # [{id, tipo, texto, estado, inicio, fim, msg}]
avisos = []                     # [{t, texto}] -> toasts na página
_sel = {"uid": None}            # item selecionado na página (voz: "o selecionado")
_notify = {"cb": None}          # cb(texto) -> fala/aviso no daemon

TEMA_PADRAO = {
    "nome": "Integra",
    "cores": {"primaria": "#1f6feb", "secundaria": "#8957e5", "fundo": "#0d1117", "superficie": "#161b22",
              "texto": "#e6edf3", "texto_suave": "#8b949e", "sucesso": "#2ea043", "alerta": "#d29922", "erro": "#f85149"},
    "fontes": {"titulo": "Inter, system-ui, sans-serif", "corpo": "Inter, system-ui, sans-serif", "mono": "JetBrains Mono, monospace"},
    "raio": "10px", "espaco": "16px", "sombra": "0 6px 24px rgba(0,0,0,.35)",
    "icones": "lucide",
}


def _p(*a):
    return os.path.join(DIR, *a)


def _rd(nome, padrao):
    try:
        with open(_p(nome)) as f:
            return json.load(f)
    except Exception:
        return padrao


def _wr(nome, dado):
    os.makedirs(os.path.dirname(_p(nome)), exist_ok=True)
    tmp = _p(nome + ".tmp")
    with open(tmp, "w") as f:
        json.dump(dado, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _p(nome))


def _slug(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "tela"


# ---------------- estado ----------------
def biblioteca():
    return _rd("biblioteca.json", [])


def tema():
    t = _rd("tema.json", None)
    if not t:
        t = TEMA_PADRAO; _wr("tema.json", t)
    return t


def config():
    return _rd("config.json", {"tela": "inicio", "projeto": ""})


def tela(nome=None):
    nome = nome or config()["tela"]
    return _rd(os.path.join("telas", _slug(nome) + ".json"), {"nome": nome, "largura": 1280, "altura": 800, "itens": []})


def salvar_tela(t):
    with _lock:
        _wr(os.path.join("telas", _slug(t["nome"]) + ".json"), t)


def estado():
    with _lock:
        return {"biblioteca": biblioteca(), "tema": tema(), "tela": tela(), "config": config(),
                "telas": sorted(f[:-5] for f in os.listdir(_p("telas")) if f.endswith(".json")) if os.path.isdir(_p("telas")) else [],
                "jobs": jobs[-12:], "projetos": projetos(), "selecao": _sel["uid"], "avisos": avisos[-8:]}


def projetos():
    try:
        return [{"nome": p["nome"], "caminho": p["caminho"]} for p in json.load(open(os.path.join(ROOT, "memory", "projetos.json")))["projetos"]
                if p.get("arquivos", 0) > 0][:60]
    except Exception:
        return []


def _css_vars(t=None):
    t = t or tema()
    v = [f"--cor-{k.replace('_', '-')}: {c};" for k, c in t["cores"].items()]
    v += [f"--fonte-{k}: {c};" for k, c in t["fontes"].items()]
    v += [f"--raio: {t['raio']};", f"--espaco: {t['espaco']};", f"--sombra: {t['sombra']};"]
    return ":root{" + "".join(v) + "}"


# ---------------- Claude CLI ----------------
def _claude(prompt, cwd=None, timeout=240, edit=False):
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", MODEL, "--effort", "low"]
    if edit:
        cmd += ["--permission-mode", "acceptEdits"]          # só edita arquivos do projeto (sem comandos arbitrários)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd or DIR)
    try:
        return json.loads(r.stdout).get("result", "")
    except Exception:
        return r.stdout or r.stderr


def _json_do_texto(s):
    s = s or ""
    dec = json.JSONDecoder()
    for i in [m.start() for m in re.finditer(r"\{", s)][:20]:
        try:
            d, _ = dec.raw_decode(s[i:])
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    return None


def _job(tipo, texto, fn):
    j = {"id": uuid.uuid4().hex[:8], "tipo": tipo, "texto": texto[:120], "estado": "gerando", "inicio": time.time(), "fim": 0, "msg": ""}
    with _lock:
        jobs.append(j); del jobs[:-30]

    def run():
        try:
            j["msg"] = fn() or "pronto"
            j["estado"] = "pronto"
        except Exception as e:
            j["estado"], j["msg"] = "erro", str(e)[:200]
        j["fim"] = time.time()
        avisos.append({"t": time.time(), "texto": ("✔ " if j["estado"] == "pronto" else "✖ ") + j["msg"][:160]}); del avisos[:-20]
        if _notify["cb"]:
            try:
                _notify["cb"](("Pronto: " if j["estado"] == "pronto" else "Falhou: ") + j["msg"][:160])
            except Exception:
                pass
    threading.Thread(target=run, daemon=True, name="construtor-" + tipo).start()
    return j


def criar_elemento(pedido):
    """gera um elemento curto (HTML+CSS com tokens) via Claude CLI e coloca na biblioteca."""
    def fn():
        t = tema()
        prompt = (
            "Você gera UM componente de interface para um construtor visual No-Code. Responda SOMENTE um JSON válido, sem texto fora dele:\n"
            '{"nome":"nome curto em pt-BR","categoria":"botao|formulario|cartao|navegacao|texto|midia|secao|outro",'
            '"largura":px,"altura":px,"html":"...","css":"...","js":""}\n'
            "Regras: HTML semântico e acessível; CSS com escopo pela classe raiz `.c-<slug>` (nada global); use SEMPRE as variáveis do tema "
            "(var(--cor-primaria), var(--cor-fundo), var(--cor-superficie), var(--cor-texto), var(--cor-texto-suave), var(--fonte-titulo), "
            "var(--fonte-corpo), var(--raio), var(--espaco), var(--sombra)); ícones como SVG inline (estilo Lucide, stroke=currentColor); "
            "textos em pt-BR; sem imagens externas; componente se adapta a 100% da largura/altura da caixa; js opcional e curto, sem rede. "
            f"Largura/altura sugeridas para o palco 1280x800.\nTema atual: {json.dumps(t, ensure_ascii=False)}\nPedido: {pedido}")
        d = _json_do_texto(_claude(prompt))
        if not d or not d.get("html"):
            d = _json_do_texto(_claude(prompt + "\nIMPORTANTE: devolva apenas o objeto JSON, com aspas escapadas corretamente."))
        if not d or not d.get("html"):
            raise RuntimeError("o Claude não devolveu um componente válido")
        el = {"id": uuid.uuid4().hex[:8], "nome": str(d.get("nome") or pedido)[:50], "categoria": d.get("categoria", "outro"),
              "largura": int(d.get("largura") or 320), "altura": int(d.get("altura") or 120),
              "html": d["html"], "css": d.get("css", ""), "js": d.get("js", ""), "pedido": pedido, "criado": time.time()}
        with _lock:
            b = biblioteca(); b.append(el); _wr("biblioteca.json", b)
        return f"{el['nome']} está na biblioteca."
    return _job("elemento", pedido, fn)


def _achar(nome, itens, chave="nome"):
    import difflib
    a = _slug(nome).replace("-", " ")
    best, sc = None, 0.0
    for it in itens:
        b = _slug(it.get(chave, "")).replace("-", " ")
        s = 1.0 if a == b else 0.9 if (a and (a in b or b in a)) else difflib.SequenceMatcher(None, a, b).ratio()
        if s > sc:
            best, sc = it, s
    return best if sc >= 0.5 else None


def colocar(nome, x=None, y=None):
    """põe um elemento da biblioteca na tela atual (próximo espaço livre se x/y não vierem)."""
    with _lock:
        el = _achar(nome, biblioteca()) if nome else (biblioteca() or [None])[-1]
        if not el:
            return None
        t = tela()
        if x is None:
            fundo = max([i["y"] + i["h"] for i in t["itens"]] or [0])
            x, y = 40, min(fundo + 24, t["altura"] - el["altura"])
        t["itens"].append({"uid": uuid.uuid4().hex[:8], "el": el["id"], "x": int(x), "y": int(y),
                           "w": el["largura"], "h": el["altura"], "z": len(t["itens"]) + 1})
        salvar_tela(t)
        return el["nome"]


PRIMITIVOS = {
    "titulo": ("Título", 520, 64, '<h1 class="p-tit">Título da seção</h1>',
               '.p-tit{margin:0;font:700 40px/1.15 var(--fonte-titulo);color:var(--cor-texto)}'),
    "texto": ("Texto", 480, 90, '<p class="p-txt">Escreva aqui um parágrafo curto explicando o valor do produto.</p>',
              '.p-txt{margin:0;font:400 16px/1.6 var(--fonte-corpo);color:var(--cor-texto-suave)}'),
    "botao": ("Botão", 180, 48, '<button class="p-bt">Começar</button>',
              '.p-bt{width:100%;height:100%;border:0;border-radius:var(--raio);background:var(--cor-primaria);color:#fff;font:600 15px var(--fonte-corpo);cursor:pointer;box-shadow:var(--sombra)}.p-bt:hover{filter:brightness(1.1)}'),
    "caixa": ("Caixa", 360, 220, '<div class="p-box"></div>',
              '.p-box{width:100%;height:100%;background:var(--cor-superficie);border-radius:var(--raio);box-shadow:var(--sombra)}'),
    "imagem": ("Imagem", 360, 220, '<div class="p-img"><span>imagem</span></div>',
               '.p-img{width:100%;height:100%;display:grid;place-items:center;border-radius:var(--raio);background:repeating-linear-gradient(45deg,var(--cor-superficie) 0 12px,transparent 12px 24px);border:1px dashed var(--cor-texto-suave);color:var(--cor-texto-suave);font:500 13px var(--fonte-corpo)}'),
    "divisor": ("Divisor", 600, 12, '<hr class="p-hr">', '.p-hr{margin:5px 0;border:0;border-top:1px solid var(--cor-texto-suave);opacity:.35}'),
    "campo": ("Campo de texto", 320, 64, '<label class="p-cp"><span>Nome</span><input placeholder="Digite aqui"></label>',
              '.p-cp{display:flex;flex-direction:column;gap:6px;font:500 13px var(--fonte-corpo);color:var(--cor-texto-suave)}.p-cp input{height:40px;border-radius:var(--raio);border:1px solid #ffffff22;background:var(--cor-superficie);color:var(--cor-texto);padding:0 12px;font:inherit}'),
}


def primitivo(tipo, svg=None, nome=None):
    """cria NA HORA um elemento básico (sem Claude) — ou um ícone (svg) — e devolve o elemento."""
    if svg:
        el = {"nome": nome or "Ícone", "categoria": "icone", "largura": 48, "altura": 48,
              "html": f'<span class="p-ico">{svg}</span>',
              "css": ".p-ico{display:grid;place-items:center;width:100%;height:100%;color:var(--cor-primaria)}.p-ico svg{width:100%;height:100%}"}
    else:
        if tipo not in PRIMITIVOS:
            raise ValueError("tipo desconhecido")
        n, w, h, html, css = PRIMITIVOS[tipo]
        el = {"nome": n, "categoria": "basico", "largura": w, "altura": h, "html": html, "css": css}
    el.update(id=uuid.uuid4().hex[:8], js="", pedido=tipo, criado=time.time())
    with _lock:
        b = biblioteca(); b.append(el); _wr("biblioteca.json", b)
    return el


def refinar(uid, pedido):
    """o Claude ajusta o elemento de UM item da tela (nova versão na biblioteca; o item passa a usar a versão nova)."""
    with _lock:
        t = tela()
        it = next((i for i in t["itens"] if i["uid"] == uid), None)
        el = next((e for e in biblioteca() if it and e["id"] == it["el"]), None)
    if not it or not el:
        raise ValueError("selecione um elemento na tela primeiro")

    def fn():
        prompt = ("Ajuste este componente conforme o pedido, mantendo as regras (escopo pela classe raiz, variáveis do tema, pt-BR, SVG inline). "
                  'Responda SOMENTE o JSON {"nome","categoria","largura","altura","html","css","js"}.\n'
                  f"Componente atual: {json.dumps({k: el[k] for k in ('nome', 'categoria', 'largura', 'altura', 'html', 'css', 'js')}, ensure_ascii=False)}\n"
                  f"Tamanho atual na tela: {it['w']}x{it['h']}\nPedido: {pedido}")
        d = _json_do_texto(_claude(prompt))
        if not d or not d.get("html"):
            raise RuntimeError("o Claude não devolveu um componente válido")
        novo = {"id": uuid.uuid4().hex[:8], "nome": str(d.get("nome") or el["nome"])[:50], "categoria": d.get("categoria", el["categoria"]),
                "largura": int(d.get("largura") or it["w"]), "altura": int(d.get("altura") or it["h"]), "html": d["html"],
                "css": d.get("css", ""), "js": d.get("js", ""), "pedido": f"{el.get('pedido', '')} + {pedido}", "criado": time.time(), "base": el["id"]}
        with _lock:
            b = biblioteca(); b.append(novo); _wr("biblioteca.json", b)
            t2 = tela()
            for i in t2["itens"]:
                if i["uid"] == uid:
                    i["el"] = novo["id"]
            salvar_tela(t2)
        return f"{novo['nome']} ajustado."
    return _job("ajuste", pedido, fn)


def _sel_item():
    t = tela()
    return t, next((i for i in t["itens"] if i["uid"] == _sel["uid"]), None)


def acao_selecionado(acao):
    with _lock:
        t, it = _sel_item()
        if not it:
            return "Selecione um elemento na tela primeiro."
        if acao == "apagar":
            t["itens"] = [i for i in t["itens"] if i["uid"] != it["uid"]]; _sel["uid"] = None
        elif acao == "duplicar":
            n = dict(it, uid=uuid.uuid4().hex[:8], x=it["x"] + 20, y=it["y"] + 20, z=max(i.get("z", 1) for i in t["itens"]) + 1)
            t["itens"].append(n); _sel["uid"] = n["uid"]
        elif acao == "centralizar":
            it["x"] = (t["largura"] - it["w"]) // 2
        elif acao == "frente":
            it["z"] = max(i.get("z", 1) for i in t["itens"]) + 1
        elif acao == "tras":
            it["z"] = min(i.get("z", 1) for i in t["itens"]) - 1
        salvar_tela(t)
    return {"apagar": "Apagado.", "duplicar": "Duplicado.", "centralizar": "Centralizado.", "frente": "Trouxe para frente.", "tras": "Mandei para trás."}[acao]


DISPOSITIVOS = {"desktop": (1280, 800), "notebook": (1440, 900), "tablet": (768, 1024), "celular": (390, 844)}


def remover_ultimo():
    with _lock:
        t = tela()
        if not t["itens"]:
            return False
        t["itens"].pop(); salvar_tela(t); return True


def nova_tela(nome):
    with _lock:
        c = config(); c["tela"] = nome; _wr("config.json", c)
        if not os.path.exists(_p("telas", _slug(nome) + ".json")):
            salvar_tela({"nome": nome, "largura": 1280, "altura": 800, "itens": []})


def definir_projeto(nome):
    p = _achar(nome, projetos())
    if not p:
        return None
    with _lock:
        c = config(); c["projeto"] = p["caminho"]; _wr("config.json", c)
    return p["nome"]


def alterar_tema(pedido):
    def fn():
        prompt = ("Ajuste o tema de design conforme o pedido. Responda SOMENTE o JSON completo do tema (mesmas chaves), cores em hex, "
                  "fontes como pilhas CSS (Google Fonts populares permitidas).\n"
                  f"Tema atual: {json.dumps(tema(), ensure_ascii=False)}\nPedido: {pedido}")
        d = _json_do_texto(_claude(prompt))
        if not d or "cores" not in d:
            raise RuntimeError("tema inválido")
        with _lock:
            _wr("tema.json", d)
        return "tema atualizado."
    return _job("tema", pedido, fn)


def exportar_html(t=None):
    """monta a tela como HTML autônomo (posições absolutas no palco) — base para a integração."""
    t = t or tela()
    lib = {e["id"]: e for e in biblioteca()}
    css, corpo, js = [_css_vars()], [], []
    vistos = set()
    for it in sorted(t["itens"], key=lambda i: i.get("z", 0)):
        e = lib.get(it["el"])
        if not e:
            continue
        if e["id"] not in vistos:
            css.append(e.get("css", "")); vistos.add(e["id"])
            if e.get("js"):
                js.append(e["js"])
        if it.get("oculto"):
            continue
        corpo.append(f'<div class="slot" data-el="{e["nome"]}" style="left:{it["x"]}px;top:{it["y"]}px;width:{it["w"]}px;height:{it["h"]}px;z-index:{it.get("z", 1)}">{it.get("html") or e["html"]}</div>')
    fams = sorted({f.split(",")[0].strip(" '\"") for f in tema()["fontes"].values()} - {"system-ui", "Inter"} | {"Inter"})
    gf = "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?" + "&".join("family=" + f.replace(" ", "+") + ":wght@400;500;600;700" for f in fams) + "&display=swap\">"
    html = ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">" + gf +
            f"<title>{t['nome']}</title><style>body{{margin:0;background:{t.get('fundo') or 'var(--cor-fundo)'};color:var(--cor-texto);font-family:var(--fonte-corpo)}}"
            f".palco{{position:relative;width:{t['largura']}px;height:{t['altura']}px;margin:0 auto}}.slot{{position:absolute}}"
            + "\n".join(css) + "</style></head><body><div class=\"palco\">" + "\n".join(corpo) + "</div><script>" + "\n".join(js) + "</script></body></html>")
    os.makedirs(_p("export"), exist_ok=True)
    arq = _p("export", _slug(t["nome"]) + ".html")
    with open(arq, "w") as f:
        f.write(html)
    return arq


def integrar(instrucao=""):
    """o Claude CLI incorpora a tela ao projeto (na stack dele), fazendo as ligações."""
    c = config()
    if not c.get("projeto") or not os.path.isdir(c["projeto"]):
        raise ValueError("defina o projeto antes (diga: o projeto é <nome>)")
    t = tela()
    arq = exportar_html(t)
    mapa = [{"elemento": e["nome"], "x": i["x"], "y": i["y"], "w": i["w"], "h": i["h"]}
            for i in t["itens"] for e in biblioteca() if e["id"] == i["el"]]

    def fn():
        prompt = (
            f"Integre a tela '{t['nome']}' criada no construtor visual a este projeto. Arquivo de referência (HTML autônomo, posições "
            f"absolutas num palco 1280x800): {arq}\nLayout: {json.dumps(mapa, ensure_ascii=False)}\n"
            f"Tema (tokens): {json.dumps(tema(), ensure_ascii=False)}\n"
            "Faça: (1) descubra a stack e o padrão de telas/rotas do projeto lendo só o necessário; (2) recrie a tela no padrão do projeto, "
            "com layout RESPONSIVO (flex/grid) que respeite a disposição visual, reaproveitando componentes/estilos existentes; "
            "(3) registre os tokens do tema como variáveis CSS do projeto se ainda não existirem; (4) faça as ligações (rota/menu/handlers "
            "óbvios, ex.: botão de contato -> formulário/rota de contato existente); (5) não rode deploy, não mexa em segredos (.env/Secrets). "
            f"Instrução extra do dono: {instrucao or 'nenhuma'}\nNo fim, responda em 1-2 frases em pt-BR o que criou e onde.")
        return _claude(prompt, cwd=c["projeto"], timeout=900, edit=True)[:400]
    return _job("integrar", t["nome"], fn)


# ---------------- HTTP ----------------
class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/estado"):
            return self._send(200, estado())
        if self.path.startswith("/api/export"):
            arq = exportar_html()
            return self._send(200, open(arq, "rb").read(), "text/html")
        nome = "index.html" if self.path in ("/", "") else os.path.basename(self.path.split("?")[0])
        f = os.path.join(WEB, nome)
        if os.path.isfile(f):
            ct = {"html": "text/html", "js": "text/javascript", "css": "text/css"}.get(nome.rsplit(".", 1)[-1], "application/octet-stream")
            return self._send(200, open(f, "rb").read(), ct)
        self._send(404, {"erro": "não achei"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"erro": "json inválido"})
        p = self.path
        try:
            if p == "/api/tela":
                with _lock:
                    t = tela(); t["itens"] = d.get("itens", t["itens"])
                    if d.get("dispositivo") in DISPOSITIVOS:
                        t["largura"], t["altura"] = DISPOSITIVOS[d["dispositivo"]]; t["dispositivo"] = d["dispositivo"]
                    if d.get("fundo") is not None:
                        t["fundo"] = str(d["fundo"])[:30]
                    salvar_tela(t)
                return self._send(200, {"ok": True})
            if p == "/api/log":
                with open("/tmp/construtor-web.log", "a") as fh:
                    fh.write(time.strftime("%H:%M:%S ") + str(d.get("m", ""))[:500] + "\n")
                return self._send(200, {"ok": True})
            if p == "/api/selecao":
                _sel["uid"] = d.get("uid"); return self._send(200, {"ok": True})
            if p == "/api/primitivo":
                return self._send(200, primitivo(str(d.get("tipo", "")), d.get("svg"), d.get("nome")))
            if p == "/api/refinar":
                return self._send(200, refinar(str(d.get("uid") or _sel["uid"]), str(d.get("pedido", ""))))
            if p == "/api/acao":
                return self._send(200, {"msg": acao_selecionado(str(d.get("acao", "")))})
            if p == "/api/renomear_elemento":
                with _lock:
                    b = biblioteca()
                    for e in b:
                        if e["id"] == d.get("id"):
                            e["nome"] = str(d.get("nome", e["nome"]))[:50]
                    _wr("biblioteca.json", b)
                return self._send(200, {"ok": True})
            if p == "/api/elemento":
                return self._send(200, criar_elemento(str(d.get("pedido", ""))))
            if p == "/api/colocar":
                return self._send(200, {"ok": bool(colocar(str(d.get("nome", "")), d.get("x"), d.get("y")))})
            if p == "/api/remover_elemento":
                with _lock:
                    b = [e for e in biblioteca() if e["id"] != d.get("id")]; _wr("biblioteca.json", b)
                return self._send(200, {"ok": True})
            if p == "/api/tema":
                if isinstance(d.get("tema"), dict):
                    with _lock:
                        _wr("tema.json", d["tema"])
                    return self._send(200, {"ok": True})
                return self._send(200, alterar_tema(str(d.get("pedido", ""))))
            if p == "/api/tela_nova":
                nova_tela(str(d.get("nome") or "tela")); return self._send(200, {"ok": True})
            if p == "/api/projeto":
                return self._send(200, {"ok": bool(definir_projeto(str(d.get("nome", ""))))})
            if p == "/api/integrar":
                return self._send(200, integrar(str(d.get("instrucao", ""))))
        except Exception as e:
            return self._send(400, {"erro": str(e)[:200]})
        self._send(404, {"erro": "rota"})


def iniciar(notify=None):
    if notify:
        _notify["cb"] = notify
    if _srv["httpd"]:
        return URL
    os.makedirs(_p("telas"), exist_ok=True)
    tema()
    try:
        h = ThreadingHTTPServer(("127.0.0.1", PORT), _H)
    except OSError:
        return URL                               # já está no ar (outro processo: o daemon)
    h.daemon_threads = True
    _srv["httpd"] = h
    threading.Thread(target=h.serve_forever, daemon=True, name="construtor-http").start()
    return URL


def fechar_janela():
    """fecha a janela do construtor (o servidor fica no ar, é leve)."""
    try:
        ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=3).stdout or "[]")
        for w in ws:
            if "Construtor F.R.I.D.A.Y." in (w.get("title") or "") or "127.0.0.1_8765" in (w.get("app_id") or "").replace(":", "_"):
                subprocess.run(["niri", "msg", "action", "close-window", "--id", str(w["id"])], capture_output=True, timeout=3)
    except Exception:
        pass


def abrir_janela():
    """abre o construtor no Chromium como janela de app (sem barra), visível — reaproveita a janela se já existir."""
    iniciar()
    try:
        ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=3).stdout or "[]")
        w = next((w for w in ws if "Construtor F.R.I.D.A.Y." in (w.get("title") or "")), None)
        if w:
            subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(w["id"])], capture_output=True, timeout=3)
            return
    except Exception:
        pass
    subprocess.Popen(["chromium", "--force-renderer-accessibility", f"--app={URL}", "--new-window"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(20):                         # niri: maximiza a coluna do construtor (palco 1280x800 legível)
        time.sleep(0.4)
        try:
            ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=3).stdout or "[]")
        except Exception:
            ws = []
        w = next((w for w in ws if "Construtor F.R.I.D.A.Y." in (w.get("title") or "")), None)
        if w:
            subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(w["id"])], capture_output=True, timeout=3)
            if ((w.get("layout") or {}).get("tile_size") or [0])[0] < 1500:      # maximize-column alterna: só se estiver estreita
                subprocess.run(["niri", "msg", "action", "maximize-column"], capture_output=True, timeout=3)
            break


# ---------------- voz (modo criação) ----------------
_RX_CRIAR = re.compile(r"\b(?:crie|cria|criar|gere|gera|gerar|fa[çc]a|faz|monte|desenhe)\s+(?:um|uma|o|a|uns|umas)?\s*(.{3,})", re.I)
_RX_COLOCAR = re.compile(r"\b(?:coloque|coloca|colocar|ponha|p[õo]e|adicione|adiciona|arraste|insira)\s+(?:o|a|um|uma)?\s*(.{2,}?)(?:\s+na\s+tela.*)?$", re.I)
_RX_TEMA = re.compile(r"\b(cor|cores|fonte|fontes|tema|paleta|escuro|claro|arredondad)", re.I)
_RX_INTEGRAR = re.compile(r"\b(integr|incorpor|junta\w* ao projeto|manda\w* pro projeto|finaliz\w* a tela|pode ligar)", re.I)
_RX_PROJETO = re.compile(r"\bprojeto\s+(?:[ée]\s+(?:o\s+|a\s+)?|ser[áa]\s+(?:o\s+|a\s+)?)?(.{3,})$", re.I)
_RX_NOVA = re.compile(r"\bnova\s+tela\s*(?:chamada|de|do|da)?\s*(.*)$", re.I)
_RX_DESFAZ = re.compile(r"\b(desfa[çz]a|desfazer|tira o [úu]ltimo|remove o [úu]ltimo)\b", re.I)


_RX_SEL = re.compile(r"\b(?:o|a|esse|essa|este|esta)\s+(?:selecionad[oa]|elemento|item|bot[ãa]o|cart[ãa]o)\b", re.I)
_RX_DISP = re.compile(r"\b(?:tela|vers[ãa]o|modo|ver)\s+(?:de\s+|do\s+|no\s+|em\s+)?(celular|tablet|desktop|notebook|computador)\b", re.I)


def comando_voz(txt):
    """interpreta uma fala no modo criação. Devolve a resposta falada ou None (não é do construtor)."""
    t = (txt or "").strip()
    m = _RX_DISP.search(t)
    if m:
        dv = {"computador": "desktop"}.get(m.group(1).lower(), m.group(1).lower())
        with _lock:
            tl = tela(); tl["largura"], tl["altura"] = DISPOSITIVOS[dv]; tl["dispositivo"] = dv; salvar_tela(tl)
        return f"Palco no formato {dv}."
    if re.search(r"\b(apag|delet|remov|exclu)\w*", t, re.I) and _RX_SEL.search(t):
        return acao_selecionado("apagar")
    if re.search(r"\bduplic\w*|\bcopi\w*", t, re.I):
        return acao_selecionado("duplicar")
    if re.search(r"\bcentraliz\w*", t, re.I):
        return acao_selecionado("centralizar")
    if re.search(r"\b(traga|trazer|traz)\w*\s+(pra|para a?)\s+frente", t, re.I):
        return acao_selecionado("frente")
    if re.search(r"\b(mande|manda|leve|leva)\w*\s+(pra|para)\s+tr[áa]s", t, re.I):
        return acao_selecionado("tras")
    if _sel["uid"] and _RX_SEL.search(t) and re.search(r"\b(deix|mud|troc|aument|diminu|ajust|coloq|ponh|tir|adicion|fa[çz]a)\w*", t, re.I):
        try:
            refinar(_sel["uid"], t)
            return "Ajustando o elemento selecionado."
        except ValueError as e:
            return str(e).capitalize() + "."
    if _RX_INTEGRAR.search(t):
        try:
            integrar(t)
            return "Integrando a tela ao projeto em segundo plano. Aviso quando terminar."
        except ValueError as e:
            return str(e).capitalize() + "."
    m = _RX_NOVA.search(t)
    if m:
        nova_tela(m.group(1).strip(" .") or "tela " + time.strftime("%H%M"))
        return "Tela nova aberta."
    m = _RX_PROJETO.search(t)
    if m and not _RX_CRIAR.search(t):
        n = definir_projeto(m.group(1).strip(" ."))
        return f"Projeto definido: {n}." if n else "Não achei esse projeto na lista."
    if _RX_DESFAZ.search(t):
        return "Tirei o último elemento da tela." if remover_ultimo() else "A tela já está vazia."
    m = _RX_COLOCAR.search(t)
    if m:
        n = colocar(m.group(1).strip(" ."))
        return f"Coloquei {n} na tela. Arraste para posicionar." if n else "Não achei esse elemento na biblioteca."
    if _RX_TEMA.search(t) and re.search(r"\b(mud|troqu|alter|use|deix|coloc)", t, re.I):
        alterar_tema(t)
        return "Ajustando o tema."
    m = _RX_CRIAR.search(t)
    if m:
        criar_elemento(m.group(1).strip(" ."))
        return "Gerando. Vai aparecer na biblioteca em instantes."
    return None
