#!/usr/bin/env python3
"""Memória própria da F.R.I.D.A.Y.: repertório do PC + linha do tempo comprimida do que ela vê e faz.

memory/memoria.sqlite (0600):
  fatos(tipo, chave)  -> 1 linha por coisa conhecida (app, contato, pin, arquivo, rosto, objeto, janela, processo, função…)
                         resumo curto + dados JSON em zlib; repetir só atualiza visto_ult/vezes (dedupe = compressão).
  linha(t0, t1, tipo, resumo) -> estados consecutivos iguais viram UM intervalo (t0..t1); >7 dias vira resumo diário.
  busca (FTS5) sobre tipo/chave/resumo, sem acento.

Também escreve /tmp/friday-painel.json (fundo animado lê a cada 3 s).
CLI: memoria.py inventario | buscar <texto> | stats | painel
NÃO guarda: senhas, cookies, histórico de navegação, conteúdo de mensagens.
"""
import glob, json, os, re, sqlite3, subprocess, sys, threading, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import win_compat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEM = os.path.join(ROOT, "memory")
DB = os.path.join(MEM, "memoria.sqlite")
PAINEL = win_compat.get_painel_path()
HOME = os.path.expanduser("~")
CHROMIUM = os.path.join(HOME, ".config/chromium/Default")
_lock = threading.RLock()
_con = None


def _db():
    global _con
    if _con is None:
        novo = not os.path.exists(DB)
        _con = sqlite3.connect(DB, check_same_thread=False, timeout=10)
        _con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS fatos(tipo TEXT, chave TEXT, resumo TEXT, dados BLOB,
                visto_1 REAL, visto_ult REAL, vezes INTEGER DEFAULT 1, PRIMARY KEY(tipo, chave));
            CREATE TABLE IF NOT EXISTS linha(id INTEGER PRIMARY KEY, t0 REAL, t1 REAL, tipo TEXT, resumo TEXT);
            CREATE INDEX IF NOT EXISTS linha_t ON linha(t1);
            CREATE VIRTUAL TABLE IF NOT EXISTS busca USING fts5(tipo, chave, resumo, tokenize='unicode61 remove_diacritics 2');
        """)
        if novo:
            os.chmod(DB, 0o600)
    return _con


def _z(d):
    return zlib.compress(json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode(), 9) if d is not None else None


def _uz(b):
    try:
        return json.loads(zlib.decompress(b)) if b else None
    except Exception:
        return None


# ---------------------------------------------------------------- gravação
def gravar(tipo, chave, resumo="", dados=None, t=None):
    """upsert de um fato; devolve True se é novo."""
    chave = str(chave or "").strip()[:200]
    if not chave:
        return False
    t = t or time.time(); resumo = str(resumo or "")[:300]
    with _lock:
        c = _db()
        r = c.execute("SELECT resumo FROM fatos WHERE tipo=? AND chave=?", (tipo, chave)).fetchone()
        if r is None:
            c.execute("INSERT INTO fatos VALUES(?,?,?,?,?,?,1)", (tipo, chave, resumo, _z(dados), t, t))
            c.execute("INSERT INTO busca VALUES(?,?,?)", (tipo, chave, resumo))
        else:
            c.execute("UPDATE fatos SET visto_ult=?, vezes=vezes+1, resumo=COALESCE(NULLIF(?,''),resumo), dados=COALESCE(?,dados) "
                      "WHERE tipo=? AND chave=?", (t, resumo, _z(dados), tipo, chave))
            if resumo and resumo != r[0]:
                c.execute("DELETE FROM busca WHERE tipo=? AND chave=?", (tipo, chave))
                c.execute("INSERT INTO busca VALUES(?,?,?)", (tipo, chave, resumo))
        c.commit()
        return r is None


def evento(tipo, resumo, t=None):
    """linha do tempo: se o último evento do mesmo tipo tem o mesmo resumo e acabou há < 90 s, só estica o intervalo."""
    t = t or time.time(); resumo = str(resumo or "")[:240]
    if not resumo:
        return
    with _lock:
        c = _db()
        r = c.execute("SELECT id, resumo, t1 FROM linha WHERE tipo=? ORDER BY id DESC LIMIT 1", (tipo,)).fetchone()
        if r and r[1] == resumo and t - r[2] < 90:
            c.execute("UPDATE linha SET t1=? WHERE id=?", (t, r[0]))
        else:
            c.execute("INSERT INTO linha(t0,t1,tipo,resumo) VALUES(?,?,?,?)", (t, t, tipo, resumo))
        c.commit()


def compactar(dias=7):
    """eventos mais velhos que `dias` viram 1 fato 'dia' por data (top 12 resumos por tempo), e saem da linha."""
    lim = time.time() - dias * 86400
    with _lock:
        c = _db()
        rows = c.execute("SELECT t0, t1, tipo, resumo FROM linha WHERE t1 < ?", (lim,)).fetchall()
        if not rows:
            return 0
        por_dia = {}
        for t0, t1, tipo, res in rows:
            d = time.strftime("%Y-%m-%d", time.localtime(t0))
            k = f"{tipo}: {res}"
            por_dia.setdefault(d, {}); por_dia[d][k] = por_dia[d].get(k, 0) + max(1, t1 - t0)
        for d, m in por_dia.items():
            top = sorted(m.items(), key=lambda x: -x[1])[:12]
            gravar("dia", d, "; ".join(f"{k} ({int(s // 60)} min)" for k, s in top), dict(top))
        c.execute("DELETE FROM linha WHERE t1 < ?", (lim,))
        c.commit()
        return len(rows)


# ---------------------------------------------------------------- consulta
# manuais e ações do niri são em inglês: a busca em português também procura o equivalente
_PT_EN = {"fechar": "close", "janela": "window", "janelas": "window", "comprimir": "compress", "compactar": "compress zip", "converter": "convert",
          "vídeo": "video", "video": "video", "imagem": "image", "imagens": "image", "foto": "image photo", "áudio": "audio", "audio": "audio",
          "arquivo": "file", "arquivos": "file", "pasta": "directory folder", "rede": "network", "disco": "disk", "tela": "screen",
          "captura": "screenshot", "print": "screenshot", "senha": "password", "baixar": "download", "copiar": "copy", "mover": "move",
          "apagar": "delete remove", "excluir": "delete remove", "procurar": "search find", "buscar": "search find", "editar": "edit",
          "abrir": "open spawn", "terminal": "terminal", "volume": "volume", "som": "sound audio", "brilho": "brightness",
          "maximizar": "maximize", "tela cheia": "fullscreen", "cheia": "fullscreen", "coluna": "column", "área": "workspace",
          "workspace": "workspace", "focar": "focus", "esquerda": "left", "direita": "right", "cima": "up", "baixo": "down",
          "bloquear": "lock", "desligar": "power off", "reiniciar": "reboot restart", "texto": "text", "renomear": "rename",
          "processo": "process", "memória": "memory", "temperatura": "temperature sensors", "bateria": "battery", "wifi": "wifi wireless",
          "bluetooth": "bluetooth", "pdf": "pdf", "planilha": "spreadsheet", "documento": "document", "gravar": "record", "tocar": "play"}


def buscar(texto, n=8, tipo=None):
    pal = [p for p in re.findall(r"\w{3,}", (texto or "").lower())][:8]
    pal += [e for p in list(pal) for e in _PT_EN.get(p, "").split() if e not in pal]
    if not pal:
        return []
    q = " OR ".join(f'"{p}"*' for p in pal)
    sql = "SELECT tipo, chave, resumo FROM busca WHERE busca MATCH ?" + (" AND tipo=?" if tipo else "") + " ORDER BY rank LIMIT ?"
    with _lock:
        try:
            return _db().execute(sql, (q, tipo, n) if tipo else (q, n)).fetchall()
        except sqlite3.Error:
            return []


_RUIDO = {"processo", "janela", "objeto", "site", "sistema", "pedido", "conversa"}


def contexto(texto, n=5, limite=500):
    """bloco curto p/ prompt: o que a memória sabe sobre o pedido (sem tipos ruidosos)."""
    r = [x for x in buscar(texto, n * 3) if x[0] not in _RUIDO][:n]
    out = "\n".join(f"- [{t}] {k}: {s}"[:160] for t, k, s in r)
    return out[:limite]


def recente(n=8):
    with _lock:
        return _db().execute("SELECT t0, t1, tipo, resumo FROM linha ORDER BY t1 DESC LIMIT ?", (n,)).fetchall()


def stats():
    with _lock:
        c = _db()
        por = dict(c.execute("SELECT tipo, COUNT(*) FROM fatos GROUP BY tipo").fetchall())
        ev = c.execute("SELECT COUNT(*) FROM linha").fetchone()[0]
    return {"fatos": sum(por.values()), "por_tipo": por, "eventos": ev,
            "kb": round(os.path.getsize(DB) / 1024) if os.path.exists(DB) else 0}


# ---------------------------------------------------------------- inventário (repertório do PC)
def _sh(cmd, timeout=15):
    try:
        return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def inv_mapa():
    """reaproveita tools/map_pc.py (apps, pacotes, dev, serviços, arquivos, favoritos)."""
    p = os.path.join(MEM, "mapa_pc.json")
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 86400:
        _sh([sys.executable, os.path.join(ROOT, "tools", "map_pc.py")], timeout=300)
    try:
        d = json.load(open(p))
    except Exception:
        return 0
    n = 0
    for cmd, a in (d.get("apps") or {}).items():
        a = a if isinstance(a, dict) else {}
        n += gravar("app", a.get("nome") or cmd, f"comando {cmd} | {a.get('cat', '')} | {a.get('origem', '')}", a)
    for k, v in (d.get("arquivos") or {}).items():
        gravar("pasta", k, json.dumps(v, ensure_ascii=False)[:280])
    for k, v in (d.get("dev") or {}).items():
        gravar("dev", k, json.dumps(v, ensure_ascii=False)[:280])
    for f in (d.get("navegador") or {}).get("favoritos", [])[:500] if isinstance(d.get("navegador"), dict) else []:
        if isinstance(f, dict):
            gravar("favorito", f.get("url") or f.get("nome", ""), f"{f.get('nome', '')} ({f.get('pasta', '')})")
    return n


def inv_chromium():
    """pins do Chromium: abas fixadas, extensões fixadas na barra, apps web instalados, barra de favoritos, abas da última sessão."""
    n = 0
    try:
        pref = json.load(open(os.path.join(CHROMIUM, "Preferences")))
    except Exception:
        pref = {}
    for u in pref.get("pinned_tabs", []) or []:
        n += gravar("pin", u.get("url", u) if isinstance(u, dict) else u, "aba fixada")
    for a in (pref.get("toolbar") or {}).get("pinned_actions", []) or []:
        n += gravar("pin", a, "ação fixada na barra do Chromium")
    for e in (pref.get("extensions") or {}).get("pinned_extensions", []) or []:
        n += gravar("pin", e, "extensão fixada na barra")
    try:
        bm = json.load(open(os.path.join(CHROMIUM, "Bookmarks")))["roots"]["bookmark_bar"]["children"]
        for b in bm:
            if b.get("type") == "url":
                n += gravar("pin", b["url"], f"barra de favoritos: {b.get('name', '')}")
    except Exception:
        pass
    for f in glob.glob(os.path.join(HOME, ".local/share/applications/chrome-*.desktop")) + \
            glob.glob(os.path.join(HOME, ".local/share/applications/chromium-*.desktop")):
        txt = open(f, errors="ignore").read()
        m = re.search(r"^Name=(.*)$", txt, re.M)
        if m:
            n += gravar("pin", m.group(1), f"app web instalado ({os.path.basename(f)})")
    # abas abertas na última sessão (só domínio + título não ficam no SNSS de forma simples: guarda só o domínio)
    ses = sorted(glob.glob(os.path.join(CHROMIUM, "Sessions", "Session_*")), key=os.path.getmtime)
    if ses:
        raw = open(ses[-1], "rb").read()
        dom = {}
        for u in re.findall(rb"https?://[\x21-\x7e]{4,300}", raw):
            h = re.match(rb"https?://([^/:?#]+)", u)
            if h:
                d = h.group(1).decode(errors="ignore").lower()
                dom[d] = dom.get(d, 0) + 1
        for d, k in sorted(dom.items(), key=lambda x: -x[1])[:40]:
            gravar("site", d, f"aberto na última sessão do Chromium ({k} refs)")
    return n


_JS_CONTATOS = r"""(async()=>{
  const pane=document.querySelector('#pane-side'); if(!pane) return {ok:false, motivo:'lista de conversas não encontrada'};
  const vistos=new Map(); pane.scrollTop=0; await new Promise(r=>setTimeout(r,500));
  for(let i=0;i<200;i++){
    pane.querySelectorAll('[role="listitem"], div[role="row"]').forEach(r=>{
      const s=r.querySelector('span[title]'); if(!s) return; const nome=s.getAttribute('title');
      if(nome && !vistos.has(nome)) vistos.set(nome,{nome, grupo:!!r.querySelector('[data-icon*="group"]'),
        fixada:!!r.querySelector('[data-icon="pinned"],[data-testid="pinned"]')});
    });
    const antes=pane.scrollTop; pane.scrollTop+=pane.clientHeight*0.8; await new Promise(r=>setTimeout(r,350));
    if(pane.scrollTop===antes) break;
  }
  pane.scrollTop=0; return {ok:true, contatos:[...vistos.values()]};
})()"""


def inv_zap():
    """todas as conversas do WhatsApp (rola a lista do ZapZap via CDP). Só nomes, nunca mensagens."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import zap
        if not zap.available():
            return 0

        async def go():
            async with zap.CDP() as c:
                return await c.ev(_JS_CONTATOS)
        r = zap._run(go()) or {}
    except Exception as e:
        print("memória/zap:", e, flush=True)
        return 0
    n = 0
    for ct in r.get("contatos", []):
        n += gravar("contato", ct["nome"], ("grupo" if ct.get("grupo") else "contato") + " do WhatsApp" + (" (fixado)" if ct.get("fixada") else ""))
    return n


def inv_rostos():
    try:
        d = json.load(open(os.path.join(MEM, "people.json")))
    except Exception:
        return 0
    n = 0
    for pid, p in (d.get("pessoas") or {}).items():
        n += gravar("rosto", p.get("nome") or pid, f"pessoa conhecida ({len(p.get('faces', []))} amostras de rosto)", {"id": pid})
    return n


def inv_funcoes():
    """o que ela sabe fazer: ferramentas do agente + ações aprendidas."""
    n = 0
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import agent
        for nome, v in agent.TOOLS.items():
            desc = v[2] if isinstance(v, (tuple, list)) and len(v) > 2 else ""
            n += gravar("funcao", nome, str(desc)[:240])
    except Exception:
        pass
    try:
        for k, v in json.load(open(os.path.join(MEM, "aprendido.json"))).items():
            gravar("aprendido", k, json.dumps(v, ensure_ascii=False)[:240])
    except Exception:
        pass
    return n


def _lote(itens):
    """gravação em lote (1 transação): [(tipo, chave, resumo, dados)] -> quantos novos."""
    n, t = 0, time.time()
    with _lock:
        c = _db()
        for tipo, chave, resumo, dados in itens:
            chave, resumo = str(chave or "").strip()[:200], str(resumo or "")[:300]
            if not chave:
                continue
            r = c.execute("SELECT resumo FROM fatos WHERE tipo=? AND chave=?", (tipo, chave)).fetchone()
            if r is None:
                c.execute("INSERT INTO fatos VALUES(?,?,?,?,?,?,1)", (tipo, chave, resumo, _z(dados), t, t))
                c.execute("INSERT INTO busca VALUES(?,?,?)", (tipo, chave, resumo)); n += 1
            else:
                c.execute("UPDATE fatos SET visto_ult=?, resumo=?, dados=COALESCE(?,dados) WHERE tipo=? AND chave=?", (t, resumo, _z(dados), tipo, chave))
                if resumo != r[0]:
                    c.execute("DELETE FROM busca WHERE tipo=? AND chave=?", (tipo, chave))
                    c.execute("INSERT INTO busca VALUES(?,?,?)", (tipo, chave, resumo))
        c.commit()
    return n


def inv_pacotes():
    """todos os pacotes (pacman): os instalados de propósito com descrição; dependências só nome/versão. + flatpaks."""
    exp = set(_sh("pacman -Qeq", 20).split())
    desc, nome = {}, None
    for l in _sh("LC_ALL=C pacman -Qi " + " ".join(sorted(exp)), 60).splitlines() if exp else []:
        if l.startswith("Name"):
            nome = l.split(":", 1)[1].strip()
        elif l.startswith("Description") and nome:
            desc[nome] = l.split(":", 1)[1].strip()
    itens = []
    for l in _sh("pacman -Q", 20).splitlines():
        p_ = l.split()
        if len(p_) == 2:
            itens.append(("pacote", p_[0], (f"instalado pelo dono: {desc.get(p_[0], '')}" if p_[0] in exp else "dependência do sistema")
                          + f" (versão {p_[1]})", None))
    for l in _sh("flatpak list --app --columns=name,application,version", 20).splitlines():
        p_ = l.split("\t")
        if len(p_) >= 2:
            itens.append(("pacote", p_[1], f"app flatpak {p_[0]} {p_[2] if len(p_) > 2 else ''}".strip(), None))
    return _lote(itens)


def inv_comandos():
    """comandos do terminal que existem no PC, com a descrição do manual (seções 1 e 8)."""
    import shutil as _shu
    itens, vistos = [], set()
    for l in _sh("LC_ALL=pt_BR.UTF-8 man -k . 2>/dev/null", 60).splitlines():
        m = re.match(r"^(\S+)\s+\((1|8)[^)]*\)\s+-\s+(.*)$", l)
        if m and m.group(1) not in vistos and _shu.which(m.group(1)):
            vistos.add(m.group(1))
            itens.append(("comando", m.group(1), m.group(3), None))
    return _lote(itens)


_ACAO_PT = {"close-window": "fechar janela", "kill": "fechar encerrar matar app travado", "fullscreen": "tela cheia", "maximize": "maximizar", "focus-workspace": "ir para área de trabalho",
            "move-column-to-workspace": "mover janela para área de trabalho", "focus-column-left": "focar janela à esquerda",
            "focus-column-right": "focar janela à direita", "screenshot": "captura de tela print", "spawn": "abrir programa",
            "toggle-overview": "visão geral", "quit": "sair da sessão", "power-off": "desligar monitores", "volume": "volume som",
            "brightness": "brilho", "lock": "bloquear tela", "consume": "juntar janelas", "expel": "separar janela",
            "move-column": "mover janela", "set-column-width": "largura da janela", "floating": "janela flutuante", "kitty": "terminal",
            "launcher": "lançador de apps", "clipboard": "área de transferência"}


def inv_atalhos():
    """atalhos de teclado do niri (o que cada combinação faz)."""
    itens = []
    for f in glob.glob(os.path.join(HOME, ".config/niri/cfg/*.kdl")) + [os.path.join(HOME, ".config/niri/config.kdl")]:
        txt = "\n".join(l for l in (open(f, errors="ignore").read() if os.path.exists(f) else "").splitlines() if not l.strip().startswith("//"))
        for m in re.finditer(r'^\s*([A-Za-z0-9_+\-]+\+[A-Za-z0-9_\-]+|XF86\w+|Print)\b[^{\n]*\{\s*([^}]*)\}', txt, re.M):
            acao_ = re.sub(r"\s+", " ", m.group(2)).strip(" ;")[:160]
            pt_ = " ".join(dict.fromkeys(v for k, v in _ACAO_PT.items() if k in acao_.lower()))
            tit_ = re.search(r'hotkey-overlay-title="([^"]*)"', m.group(0))
            itens.append(("atalho", m.group(1), (tit_.group(1) + ": " if tit_ else "") + acao_ + (f" ({pt_})" if pt_ else ""),
                          {"arquivo": os.path.basename(f)}))
    return _lote(itens)


_IGN = re.compile(r"/(node_modules|\.git|dist|build|\.venv[^/]*|__pycache__|models|\.cache|vendor|target|\.next)(/|$)|bak|\.min\.")
_EXT = (".py", ".js", ".ts", ".tsx", ".qml", ".md", ".json", ".toml", ".html", ".sh", ".luau", ".css", ".sql", ".yaml", ".yml")


def inv_projetos(max_arq=6000):
    """projetos do Workspace (stack, README) + arquivos de código mais recentes (só caminho, tamanho e data)."""
    itens, arqs = [], []
    raizes = sorted(glob.glob(os.path.join(HOME, "Workspace/Projetos/Sistemas/*")) + glob.glob(os.path.join(HOME, "Workspace/Projetos/Scripts/*"))
                    + [os.path.join(HOME, "Workspace/Projeto Prometheus")])
    for r in raizes:
        if not os.path.isdir(r):
            continue
        stack = [s for s, f in (("Node", "package.json"), ("Python", "requirements.txt"), ("Python", "pyproject.toml"),
                                ("Cloudflare Worker", "wrangler.toml"), ("git", ".git")) if glob.glob(os.path.join(r, "**", f), recursive=False) or os.path.exists(os.path.join(r, f))]
        rd = next((p for p in (os.path.join(r, "README.md"), os.path.join(r, "CLAUDE.md")) if os.path.exists(p)), None)
        resumo = re.sub(r"\s+", " ", re.sub(r"[#>*`]", "", open(rd, errors="ignore").read(600))).strip()[:220] if rd else ""
        itens.append(("projeto", os.path.basename(r), f"{' + '.join(dict.fromkeys(stack)) or 'pasta'} em {r}. {resumo}", {"caminho": r}))
        for dp, dns, fns in os.walk(r):
            dns[:] = [d for d in dns if not _IGN.search("/" + d + "/")]
            if dp.count(os.sep) - r.count(os.sep) > 4:
                dns[:] = []
            for f in fns:
                p_ = os.path.join(dp, f)
                if f.endswith(_EXT) and not _IGN.search(p_):
                    try:
                        st = os.stat(p_)
                        arqs.append((st.st_mtime, p_, st.st_size, os.path.basename(r)))
                    except OSError:
                        pass
    for mt, p_, sz, proj in sorted(arqs, reverse=True)[:max_arq]:
        itens.append(("arquivo", p_.replace(HOME, "~"), f"código do projeto {proj}, {sz // 1024} KB, alterado {time.strftime('%d/%m/%Y', time.localtime(mt))}", None))
    return _lote(itens)


def inv_pessoais():
    """documentos, downloads, imagens, músicas e vídeos do dono (nome, tipo, tamanho, data; nunca o conteúdo)."""
    itens = []
    for pasta in ("Documentos", "Documents", "Downloads", "Imagens", "Músicas", "Vídeos", "Área de trabalho", "Workspace/Documentos",
                  "Workspace/Memoria", "Workspace/DEMOs", "Workspace/Dist"):
        base = os.path.join(HOME, pasta)
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if not d.startswith(".") and d != "node_modules"]
            if dp.count(os.sep) - base.count(os.sep) > 3:
                dns[:] = []
            for f in fns:
                if f.startswith("."):
                    continue
                p_ = os.path.join(dp, f)
                try:
                    st = os.stat(p_)
                except OSError:
                    continue
                ext = os.path.splitext(f)[1].lower().lstrip(".") or "sem extensão"
                itens.append(("documento", p_.replace(HOME, "~"), f"{ext}, {max(1, st.st_size // 1024)} KB, em {pasta}, de {time.strftime('%d/%m/%Y', time.localtime(st.st_mtime))}", None))
    return _lote(itens)


def inv_conversas():
    """pedidos que o dono já fez (memory/conversas.jsonl) -> fatos 'pedido' (dedupe por texto) + resumo por dia."""
    itens, por_dia = [], {}
    try:
        linhas = open(os.path.join(MEM, "conversas.jsonl"), errors="ignore").read().splitlines()
    except Exception:
        return 0
    for l in linhas:
        try:
            j = json.loads(l)
        except Exception:
            continue
        txt = re.sub(r"\s+", " ", str(j.get("text") or "")).strip()
        if j.get("role") not in ("usuario", "user") or len(txt) < 8:
            continue
        d = time.strftime("%d/%m/%Y", time.localtime(j.get("t", 0)))
        itens.append(("pedido", txt[:200], f"o dono pediu em {d} às {time.strftime('%H:%M', time.localtime(j.get('t', 0)))}", None))
        por_dia.setdefault(d, []).append(txt[:60])
    for d, ps in por_dia.items():
        itens.append(("conversa", d, f"{len(ps)} pedidos; ex.: " + " | ".join(ps[:5]), None))
    return _lote(itens)


def inv_saber():
    """lições aprendidas, episódios (receitas que deram certo), habilidades, projetos e serviços ativos do sistema."""
    itens = []
    try:
        for i, l in enumerate(json.load(open(os.path.join(MEM, "licoes.json")))):
            t_ = l if isinstance(l, str) else (l.get("licao") or l.get("texto") or json.dumps(l, ensure_ascii=False))
            itens.append(("licao", str(t_)[:200], "lição aprendida com um erro", None))
    except Exception:
        pass
    try:
        c = sqlite3.connect(os.path.join(MEM, "episodios.sqlite"))
        for pedido, passos, resultado in c.execute("SELECT pedido, passos, resultado FROM ep"):
            itens.append(("episodio", str(pedido)[:200], f"deu certo: {str(passos)[:150]} -> {str(resultado)[:100]}", None))
    except Exception:
        pass
    for f in ("habilidades.json", "projetos.json"):
        try:
            for k, v in json.load(open(os.path.join(MEM, f))).items():
                itens.append((f.split(".")[0][:-1] if f.startswith("projetos") else "habilidade", k, json.dumps(v, ensure_ascii=False)[:280], None))
        except Exception:
            pass
    for l in _sh("systemctl list-units --type=service --state=running --no-legend --plain", 10).splitlines() + \
            _sh("systemctl --user list-units --type=service --state=running --no-legend --plain", 10).splitlines():
        p_ = l.split(None, 4)
        if len(p_) >= 5:
            itens.append(("servico", p_[0], p_[4][:200], None))
    return _lote(itens)


def inventario(zap_tambem=True):
    r = {"mapa": inv_mapa(), "chromium": inv_chromium(), "rostos": inv_rostos(), "funcoes": inv_funcoes(),
         "pacotes": inv_pacotes(), "comandos": inv_comandos(), "atalhos": inv_atalhos(), "projetos": inv_projetos(),
         "pessoais": inv_pessoais(), "conversas": inv_conversas(), "saber": inv_saber()}
    if zap_tambem:
        r["zap"] = inv_zap()
    gravar("sistema", "inventario", f"último inventário {time.strftime('%d/%m %H:%M')}", r)
    return r


# ---------------------------------------------------------------- observação contínua (chamada pelo daemon)
def _janela():
    if win_compat.IS_WINDOWS:
        f = win_compat.janela_em_foco()
        return f.get("app_id") or "", f.get("titulo") or ""
    try:
        w = json.loads(_sh(["niri", "msg", "-j", "focused-window"], 3) or "null") or {}
        return w.get("app_id") or "", w.get("title") or ""
    except Exception:
        return "", ""


def _processos(n=6):
    if win_compat.IS_WINDOWS:
        return win_compat.obter_processos(n)
    out = _sh(f"ps -eo comm,%cpu,rss --sort=-%cpu --no-headers | head -{n}", 4)
    return [l.split() for l in out.splitlines() if len(l.split()) == 3]


def observar(pessoas=(), objetos=(), estado=""):
    """1 passo (o daemon chama a cada ~15 s): janela em foco, processos, quem/o que as câmeras veem."""
    t = time.time()
    app, tit = _janela()
    if app:
        gravar("janela", app, tit[:200])
        evento("tela", f"{app}: {tit[:120]}", t)
    for comm, cpu, rss in _processos():
        try:
            if float(cpu) >= 5:
                gravar("processo", comm, f"{cpu}% CPU, {int(rss) // 1024} MB")
        except ValueError:
            pass
    pes = sorted(set(p for p in pessoas if p))
    for p in pes:
        gravar("rosto", p, "")
    for o in objetos:
        gravar("objeto", o, "visto pelas câmeras")
    evento("presenca", ", ".join(pes) if pes else "ninguém", t)
    if estado:
        evento("friday", estado, t)


# ---------------------------------------------------------------- dados do painel de fundo
_clima = {"t": 0, "v": None}


def _clima_atual():
    if time.time() - _clima["t"] < 1800:
        return _clima["v"]
    _clima["t"] = time.time()
    try:
        import urllib.request
        j = json.loads(urllib.request.urlopen("https://wttr.in/?format=j1&lang=pt", timeout=8).read())
        c = j["current_condition"][0]
        area = j.get("nearest_area", [{}])[0].get("areaName", [{}])[0].get("value", "")
        _clima["v"] = {"temp": c.get("temp_C"), "sensacao": c.get("FeelsLikeC"), "umidade": c.get("humidity"),
                       "desc": (c.get("lang_pt") or [{}])[0].get("value") or c["weatherDesc"][0]["value"], "local": area,
                       "dias": [{"data": d["date"][5:], "max": d["maxtempC"], "min": d["mintempC"]} for d in j.get("weather", [])[:3]]}
    except Exception:
        pass
    return _clima["v"]


def _agenda(n=6):
    try:
        it = json.load(open(os.path.join(MEM, "agenda.json"))).get("itens", [])
    except Exception:
        return []
    agora = time.time() - 3600
    vivos = sorted((i for i in it if not i.get("removido") and (i.get("fim") or i.get("inicio") or 0) >= agora), key=lambda i: i.get("inicio", 0))
    return [{"hora": time.strftime("%d/%m %H:%M", time.localtime(i.get("inicio", 0))), "titulo": i.get("titulo", ""),
             "tipo": i.get("tipo", ""), "feito": bool(i.get("feito")), "prioridade": i.get("prioridade", 2),
             "fonte": i.get("fonte", "pc")} for i in vivos[:n]]


def _agenda_nivel():
    try:
        import prom_ops
        return prom_ops.agenda_nivel()
    except Exception:
        return {}


def _tarefas(n=5):
    try:
        it = json.load(open(os.path.join(MEM, "tarefas.json"))).get("itens", [])
    except Exception:
        return []
    abertas = [i for i in it if i.get("estado") not in ("cancelada", "concluida", "feita")]
    return [{"texto": i.get("texto", "")[:80], "estado": i.get("estado", "")} for i in abertas[-n:]]


def painel():
    s = stats()
    if win_compat.IS_WINDOWS:
        rede = win_compat.obter_nome_rede()
        disco = win_compat.obter_uso_disco()
        seg = win_compat.obter_uptime_segundos()
    else:
        rede = _sh("nmcli -t -f NAME,DEVICE connection show --active | head -1", 3)
        disco = _sh("df --output=pcent / | tail -1", 3).strip()
        try:
            seg = int(float(open("/proc/uptime").read().split()[0]))
        except Exception:
            seg = win_compat.obter_uptime_segundos()
    up = f"{seg // 86400}d {seg % 86400 // 3600}h {seg % 3600 // 60}min" if seg >= 86400 else f"{seg // 3600}h {seg % 3600 // 60}min"
    d = {"t": time.time(), "clima": _clima_atual(), "agenda": _agenda(), "agenda_nivel": _agenda_nivel(), "tarefas": _tarefas(),
         "recente": [{"h": time.strftime("%H:%M", time.localtime(t1)), "tipo": tp, "txt": r[:90]} for t0, t1, tp, r in recente(7)],
         "memoria": s, "rede": rede.split(":")[0] if rede else "LAN", "disco": disco, "uptime": up,
         "processos": [{"nome": p[0], "cpu": p[1]} for p in _processos(5)]}
    tmp = PAINEL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, PAINEL)
    return d


def thread(obter_cena=None):
    """laço do daemon: painel a cada 3 s, observação a cada 15 s, inventário 1x/dia (zap incluso), compactação 1x/dia."""
    ult_obs = ult_inv = ult_cmp = 0
    while True:
        try:
            now = time.time()
            if now - ult_obs > 15:
                ult_obs = now
                pes, objs, est = obter_cena() if obter_cena else ((), (), "")
                observar(pes, objs, est)
            if now - ult_inv > 86400:
                ult_inv = now
                r = _db().execute("SELECT visto_ult FROM fatos WHERE tipo='sistema' AND chave='inventario'").fetchone()
                if not r or now - r[0] > 86400:
                    threading.Thread(target=inventario, daemon=True, name="inventario").start()
            if now - ult_cmp > 86400:
                ult_cmp = now; compactar()
            painel()
        except Exception as e:
            print("memória:", e, flush=True)
        time.sleep(3)


if __name__ == "__main__":
    a = sys.argv[1:] or ["stats"]
    if a[0] == "inventario":
        print(json.dumps(inventario(), ensure_ascii=False))
    elif a[0] == "buscar":
        for r in buscar(" ".join(a[1:]), 15):
            print(" | ".join(r))
    elif a[0] == "painel":
        print(json.dumps(painel(), ensure_ascii=False, indent=1)[:2000])
    else:
        print(json.dumps(stats(), ensure_ascii=False))
