"""Leitura de tela confiável (F8a): árvore de acessibilidade (AT-SPI) da janela em foco -> OCR só da janela -> VLM com
conferência por zoom. Coordenadas sempre em pixels lógicos da tela (niri). Cache por dHash: tela igual não é reprocessada.
Uso direto (teste): python tela.py ler [id_janela] | python tela.py achar "texto" [id_janela]"""
import difflib
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import win_compat
GAP = 2                       # niri cfg/layout.kdl: gaps 2
EXCL_TOPO = True              # a zona exclusiva (barra do noctalia) fica no TOPO
TESSDATA = os.path.expanduser("~/.local/share/tessdata")   # tem por+eng e configs/ (tsv)
LIMITE_NOS, LIMITE_ITENS, LIMITE_T = 4000, 600, 0.9
LOG = "/tmp/friday-tela.log"

_lock = threading.RLock()
_cache = {}                   # (id, rect, fonte) -> {"dh", "t", "r"}
_ancora = {}                  # (id, tamanho, coluna) -> (dx, dy) quando a posição pelo niri é incerta

_CLICAVEIS = {"push button", "toggle button", "link", "menu item", "check menu item", "radio menu item", "page tab", "check box",
              "radio button", "list item", "combo box", "entry", "password text", "spin button", "icon", "table cell", "tree item",
              "menu", "slider", "button", "toolbar item"}
_TEXTO_ROLES = {"label", "static", "text", "paragraph", "heading", "entry", "link", "table cell", "list item", "caption", "section"}


def _log(**k):
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps(dict(k, ts=time.strftime("%H:%M:%S")), ensure_ascii=False)[:600] + "\n")
    except Exception:
        pass


def _nrm(t):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(t or "").lower()).encode("ascii", "ignore").decode()).strip()


# ------------------------------------------------------------------ janela e posição (niri)
def _niri(*a):
    try:
        return json.loads(subprocess.run(["niri", "msg", "-j", *a], capture_output=True, text=True, timeout=3).stdout or "null")
    except Exception:
        return None


def janela(jid=None):
    """janela pedida (ou em foco) com rect absoluto {x,y,w,h}; 'incerta' quando o niri não informa a posição (coluna rolada)."""
    if win_compat.IS_WINDOWS:
        w = win_compat.janela_em_foco()
        if not w or not w.get("id"):
            return None
        rect = w.get("rect", [0, 0, 1920, 1080])
        lo = {"x": 0, "y": 0, "width": 1920, "height": 1080}
        return {"id": w.get("id"), "app_id": str(w.get("app_id") or ""), "titulo": str(w.get("titulo") or ""), "pid": w.get("pid"),
                "rect": rect, "cap": rect, "tela": lo, "incerta": False, "foco": True,
                "chave_pos": (w.get("id"), rect[2], rect[3], ())}
    ws = _niri("windows") or []
    if jid is not None:
        w = next((x for x in ws if str(x.get("id")) == str(jid)), None)
    else:
        w = next((x for x in ws if x.get("is_focused")), None)
        if not w:                                          # foco numa camada (conversa/painel): janela ativa da área visível
            wss = _niri("workspaces") or []
            a = next((s for s in wss if s.get("is_focused")), None) or next((s for s in wss if s.get("is_active")), None)
            w = next((x for x in ws if a and x.get("id") == a.get("active_window_id")), None)
    if not w:
        return None
    outs = _niri("outputs") or {}
    sp = next((s for s in (_niri("workspaces") or []) if s.get("id") == w.get("workspace_id")), {})
    lo = (outs.get(sp.get("output")) or next(iter(outs.values()), {}) or {}).get("logical") or {"x": 0, "y": 0, "width": 1920, "height": 1080}
    L = w.get("layout") or {}
    ww, wh = L.get("window_size") or (lo["width"], lo["height"])
    off = L.get("window_offset_in_tile") or (0, 0)
    incerta = False
    if L.get("tile_pos_in_workspace_view"):                    # flutuante: o niri dá a posição
        x, y = L["tile_pos_in_workspace_view"]
    else:
        col, lin = (L.get("pos_in_scrolling_layout") or (1, 1))[:2]
        cols = {}
        for o in ws:
            Lo = o.get("layout") or {}
            if o.get("workspace_id") == w.get("workspace_id") and Lo.get("pos_in_scrolling_layout"):
                c, r = Lo["pos_in_scrolling_layout"][:2]
                cols.setdefault(c, {})[r] = Lo.get("tile_size") or Lo.get("window_size") or (0, 0)
        larg = {c: max(t[0] for t in rs.values()) for c, rs in cols.items()}
        total = sum(larg.values()) + GAP * (len(larg) + 1)
        if total <= lo["width"] + 1 or col == min(larg):           # cabe na tela (ou 1ª coluna): da esquerda p/ a direita
            x = GAP + sum(larg[c] + GAP for c in larg if c < col)
        elif col == max(larg):                                      # última coluna de uma faixa rolada: encostada à direita
            x = lo["width"] - GAP - larg[col]
        else:
            x, incerta = (lo["width"] - larg[col]) / 2, True
        rs = cols.get(col, {lin: (ww, wh)})
        area = sum(t[1] for t in rs.values()) + GAP * (len(rs) + 1)
        topo = (lo["height"] - area) if EXCL_TOPO else 0
        y = topo + GAP + sum(rs[r][1] + GAP for r in rs if r < lin)
    x, y = int(round(x + off[0] + lo["x"])), int(round(y + off[1] + lo["y"]))
    return {"id": w.get("id"), "app_id": str(w.get("app_id") or ""), "titulo": str(w.get("title") or ""), "pid": w.get("pid"),
            "rect": [x, y, int(ww), int(wh)], "cap": _cap([x, y, int(ww), int(wh)], lo), "tela": lo, "incerta": incerta, "foco": bool(w.get("is_focused")),
            "chave_pos": (w.get("id"), int(ww), int(wh), tuple(L.get("pos_in_scrolling_layout") or ()))}


def _cap(rect, lo):
    """parte VISÍVEL da janela (flutuante pode sair da tela): é o que se captura/OCR"""
    x0, y0 = max(rect[0], lo["x"]), max(rect[1], lo["y"])
    x1, y1 = min(rect[0] + rect[2], lo["x"] + lo["width"]), min(rect[1] + rect[3], lo["y"] + lo["height"])
    return [x0, y0, max(x1 - x0, 1), max(y1 - y0, 1)]


# ------------------------------------------------------------------ captura + dHash
def capturar(rect):
    """captura o retângulo (escala 1) -> imagem BGR (numpy) ou None"""
    if win_compat.IS_WINDOWS:
        return win_compat.capturar_tela(rect)
    try:
        import cv2
        import numpy as np
        x, y, w, h = rect
        raw = subprocess.run(["grim", "-g", f"{x},{y} {w}x{h}", "-s", "1", "-t", "ppm", "-"], capture_output=True, timeout=5).stdout
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
    except Exception:
        return None


def dhash(img, n=16):
    """dHash n*n bits (mesma conta de agent._dhash)"""
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    s = cv2.resize(g, (n + 1, n), interpolation=cv2.INTER_AREA)
    return int("".join("1" if a > b else "0" for a, b in zip(s[:, :-1].flatten(), s[:, 1:].flatten())), 2)


def bits(a, b):
    return bin(a ^ b).count("1") if a is not None and b is not None else None


# ------------------------------------------------------------------ AT-SPI
_ATSPI = None


def _atspi():
    """módulo Atspi no próprio processo (o .venv tem gi); None -> usa o python do sistema num subprocesso"""
    global _ATSPI
    if _ATSPI is None:
        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
            try:
                Atspi.set_timeout(800, 2000)                 # app travado não segura o agente
            except Exception:
                pass
            _ATSPI = Atspi
        except Exception:
            _ATSPI = False
    return _ATSPI or None


def _frame(A, jan):
    """acha o frame AT-SPI da janela do niri: app pelo pid (ou nome ~ app_id) e frame pelo título"""
    d = A.get_desktop(0)
    nome_app = _nrm(jan["app_id"].split(".")[-1])
    tit = _nrm(jan["titulo"])
    apps = []
    for i in range(d.get_child_count()):
        a = d.get_child_at_index(i)
        if not a:
            continue
        try:
            pid, nm = a.get_process_id(), _nrm(a.get_name())
        except Exception:
            continue
        if pid == jan.get("pid") or (len(nm) >= 4 and len(nome_app) >= 4 and (nm in nome_app or nome_app in nm)):
            apps.append((pid != jan.get("pid"), a))
    best, sc = None, -1.0
    for _, a in sorted(apps, key=lambda z: z[0]):
        try:
            n = a.get_child_count()
        except Exception:
            continue
        for j in range(min(n, 40)):
            f = a.get_child_at_index(j)
            if not f:
                continue
            try:
                fn = _nrm(f.get_name())
                ativo = f.get_state_set().contains(A.StateType.ACTIVE)
            except Exception:
                continue
            s = (1.0 if fn and fn == tit else 0.9 if fn and (fn in tit or tit in fn) else
                 difflib.SequenceMatcher(None, fn, tit).ratio() * 0.8) + (0.15 if ativo else 0)
            if s > sc:
                best, sc = f, s
    return best


def _arvore(A, f, W, H):
    """nós visíveis do frame: papel, nome, texto, ações e retângulo RELATIVO à janela"""
    t0 = time.time()
    itens, pilha, vistos = [], [f], 0
    tem_doc = False
    S = A.StateType
    while pilha and vistos < LIMITE_NOS and len(itens) < LIMITE_ITENS and time.time() - t0 < LIMITE_T:
        n = pilha.pop()
        vistos += 1
        try:
            st = n.get_state_set()
            if n is not f and not st.contains(S.SHOWING):
                continue                                       # fora da tela: poda a subárvore
            papel = n.get_role_name() or ""
            nome = (n.get_name() or "").strip()
            filhos = n.get_child_count()
        except Exception:
            continue
        if papel in ("document web", "document frame"):
            tem_doc = True
        txt = ""
        if not nome and (filhos == 0 or papel == "entry") and papel in _TEXTO_ROLES:     # campo de senha nunca é lido
            try:
                ti = n.get_text_iface()
                k = ti.get_character_count() if ti else 0
                txt = ti.get_text(0, min(k, 160)).replace("￼", "").strip() if k else ""
            except Exception:
                txt = ""
        try:
            ai = n.get_action_iface()
            nac = ai.get_n_actions() if ai else 0
        except Exception:
            nac = 0
        if (nome or txt) and papel not in ("frame", "window"):
            try:
                e = n.get_extents(A.CoordType.WINDOW)
                x, y, w, h = e.x, e.y, e.width, e.height
            except Exception:
                x = y = w = h = -1
            if w > 0 and h > 0 and x + w > 0 and y + h > 0 and x < W and y < H:
                itens.append({"nome": nome[:80], "papel": papel, "texto": txt[:120], "x": x, "y": y, "w": w, "h": h,
                              "acao": bool(nac) or papel in _CLICAVEIS,
                              "estado": [s for s in ("focused", "checked", "selected", "pressed", "expanded")
                                         if st.contains(getattr(S, s.upper()))], "_no": n})
        try:
            for i in range(min(filhos, 300) - 1, -1, -1):
                c = n.get_child_at_index(i)
                if c:
                    pilha.append(c)
        except Exception:
            pass
    return itens, {"nos": vistos, "doc": tem_doc, "corte": time.time() - t0 >= LIMITE_T}


def _arvore_janela(jan):
    """[itens], info — no processo (gi do .venv) ou no python do sistema"""
    W, H = jan["rect"][2], jan["rect"][3]
    A = _atspi()
    if A:
        with _lock:
            f = _frame(A, jan)
            if not f:
                return [], {"nos": 0, "doc": False, "sem_frame": True}
            return _arvore(A, f, W, H)
    try:                                                      # sem gi aqui: coleta no python do sistema e devolve JSON
        p = subprocess.run(["/usr/bin/python3", os.path.join(HERE, "tela.py"), "_arvore", json.dumps(jan)],
                           capture_output=True, text=True, timeout=6)
        d = json.loads(p.stdout or "{}")
        return d.get("itens", []), d.get("info", {})
    except Exception as e:
        return [], {"erro": str(e)[:80]}


# ------------------------------------------------------------------ OCR só da janela (por+eng)
def _ocr(img, rect):
    """linhas de texto da captura (posição relativa a ela); sem o filtro x1<=390 do manual.py"""
    import cv2
    try:                                                      # 1º OCR pt-BR (PP-OCRv5 latin: acentos certos); tesseract é a reserva
        import ocr_pt
        ls = ocr_pt.linhas(img)
        if ls is not None:
            return [{"nome": d["t"][:80], "papel": "ocr", "texto": "", "x": d["x0"], "y": d["y0"], "w": d["x1"] - d["x0"],
                     "h": d["y1"] - d["y0"], "acao": False, "estado": []} for d in ls if len(re.findall(r"[^\W_]", d["t"])) >= 2]
    except Exception:
        pass
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return []
    env = dict(os.environ, OMP_THREAD_LIMIT="1")             # 1 thread: medido 2,5 s contra 4,6 s com OpenMP (por+eng, janela cheia)
    if os.path.isdir(TESSDATA):
        env["TESSDATA_PREFIX"] = TESSDATA
    try:
        r = subprocess.run(["tesseract", "stdin", "-", "--psm", "11", "-l", "por+eng", "tsv"], input=buf.tobytes(),
                           capture_output=True, timeout=40, env=env)
        out = r.stdout.decode("utf-8", "ignore")
    except Exception:
        return []
    linhas = {}
    for row in out.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            conf = float(c[10])
        except ValueError:
            continue
        if conf < 45:
            continue
        x, y, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        d = linhas.setdefault((c[2], c[3], c[4]), {"w": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h})
        d["w"].append(c[11].strip()); d["x1"] = max(d["x1"], x + w); d["y1"] = max(d["y1"], y + h)
    itens = []
    for d in linhas.values():
        t = " ".join(d["w"])
        if len(re.findall(r"[^\W_]", t)) >= 2:                # descarta lixo de ícone ("¢«", "[=]")
            itens.append({"nome": t[:80], "papel": "ocr", "texto": "", "x": d["x0"], "y": d["y0"], "w": d["x1"] - d["x0"],
                          "h": d["y1"] - d["y0"], "acao": False, "estado": []})
    return itens


# ------------------------------------------------------------------ leitura
def _absolutos(itens, origem, fonte):
    X, Y = origem[:2]
    for i in itens:
        i["fonte"] = fonte
        i["ax"], i["ay"] = X + i["x"], Y + i["y"]
        i["cx"], i["cy"] = X + i["x"] + i["w"] // 2, Y + i["y"] + i["h"] // 2
    return itens


def _dedup(itens):
    vistos, out = set(), []
    for i in sorted(itens, key=lambda z: (not z["acao"], z["w"] * z["h"])):
        k = (_nrm(i["nome"] or i["texto"])[:40], i["cx"] // 12, i["cy"] // 12)
        if k in vistos:
            continue
        vistos.add(k)
        out.append(i)
    out.sort(key=lambda z: (z["cy"] // 14, z["cx"]))
    return out


def _ancorar(jan, at, oc):
    """posição incerta (coluna rolada): acha o deslocamento casando um nó AT-SPI com uma linha do OCR da TELA inteira"""
    k = jan["chave_pos"]
    if k in _ancora:
        return _ancora[k]
    try:
        import manual
        L = manual.screen_lines()
    except Exception:
        return None
    nomes = {}
    for i in at:
        n = _nrm(i["nome"])
        if len(n) >= 5:
            nomes.setdefault(n, i)
    for l in L:
        i = nomes.get(_nrm(l["t"]))
        if i:
            d = (l["x"] - (i["x"] + i["w"] // 2), l["y"] - (i["y"] + i["h"] // 2))
            _ancora[k] = d
            return d
    return None


def ler(janela_id=None, ocr=None, usar_cache=True):
    """lê a janela (em foco por padrão). Devolve {janela, fonte, itens[{nome,papel,texto,cx,cy,...}], t, dh, cache}.
    AT-SPI primeiro; se vier vazia/pobre (app sem acessibilidade ou página web sem a árvore), OCR do retângulo da janela."""
    t0 = time.time()
    jan = janela(janela_id)
    if not jan:
        return {"janela": None, "fonte": "nenhuma", "itens": [], "t": round(time.time() - t0, 3), "dh": None}
    img = capturar(jan["cap"]) if jan["foco"] or janela_id is None else None
    dh = dhash(img) if img is not None else None
    ck = (jan["id"], tuple(jan["rect"]), jan["titulo"], bool(ocr))
    c = _cache.get(ck)
    # só o OCR (caro) usa o cache: AT-SPI é barata e um 'estado' velho (marcado/selecionado) enganaria o efeito() do clique
    if usar_cache and c and c["r"]["fonte"] != "atspi" and dh is not None and bits(c["dh"], dh) <= 3 and time.time() - c["t"] < 30:
        r = dict(c["r"], t=round(time.time() - t0, 3), cache=True)
        return r
    at, info = _arvore_janela(jan)
    if jan["incerta"] and at:
        d = _ancorar(jan, at, None)
        if d:
            jan["rect"][0] += d[0]; jan["rect"][1] += d[1]
            jan["incerta"], jan["cap"] = False, _cap(jan["rect"], jan["tela"])
            img = capturar(jan["cap"])
    _absolutos(at, jan["rect"], "atspi")
    navegador = re.search(r"chrom|firefox|brave|vivaldi|edge", jan["app_id"], re.I)
    pobre = len([i for i in at if i["nome"] or i["texto"]]) < 5 or (navegador and not info.get("doc"))
    fonte = "atspi"
    itens = at
    if (pobre or ocr) and ocr is not False and img is not None:
        oc = _absolutos(_ocr(img, jan["cap"]), jan["cap"], "ocr")
        itens = at + oc if at else oc
        fonte = "atspi+ocr" if at else "ocr"
    itens = _dedup(itens)
    r = {"janela": {k: jan[k] for k in ("id", "app_id", "titulo", "rect", "cap", "incerta")}, "fonte": fonte, "itens": itens,
         "t": round(time.time() - t0, 3), "dh": dh, "info": {k: v for k, v in info.items()}, "cache": False}
    if dh is not None:
        if len(_cache) > 8:
            _cache.clear()
        _cache[ck] = {"dh": dh, "t": time.time(), "r": r}
    _log(op="ler", app=jan["app_id"], fonte=fonte, n=len(itens), t=r["t"], nos=info.get("nos"))
    return r


def texto(r, n=45):
    """leitura em texto p/ o prompt do agente: [papel] nome @x,y"""
    if not r or not r.get("janela"):
        return "nenhuma janela em foco"
    j = r["janela"]
    linhas = []
    for i in r["itens"][:n]:
        p = "" if i["papel"] in ("ocr", "label", "static", "text") else f"[{i['papel']}] "
        linhas.append(f"{p}{(i['nome'] or i['texto'])[:70]} @{i['cx']},{i['cy']}")
    return f"leitura ({r['fonte']}, {r['t']} s) de {j['app_id']} — {j['titulo'][:60]}:\n" + "\n".join(linhas)


def linhas(r):
    """itens no formato antigo do manual.screen_lines (t, x, y, x0, x1) p/ _visivel/_find"""
    return [{"t": (i["nome"] or i["texto"])[:60], "x": i["cx"], "y": i["cy"], "x0": i["ax"], "x1": i["ax"] + i["w"]}
            for i in (r or {}).get("itens", []) if (i["nome"] or i["texto"])]


# ------------------------------------------------------------------ localizar + verificar
def _pontua(alvo, itens):
    q = re.search(r"['\"“‘]([^'\"”’]{2,})['\"”’]", alvo)    # "the text or button 'Enviar'" -> Enviar
    a = _nrm(q.group(1) if q else alvo)
    melhor, sc = None, 0.0
    for i in itens:
        t = _nrm(i["nome"] or i["texto"])
        if not t:
            continue
        is_whole_word = bool(re.search(r"\b" + re.escape(a) + r"\b", t))
        if a == t:
            s = 1.0
        elif is_whole_word and len(a) >= 2:
            s = 0.92
        elif len(a) >= 6 and a in t:
            s = 0.75
        elif len(t) >= 4 and re.search(r"\b" + re.escape(t) + r"\b", a):
            s = 0.7
        else:
            ratio = difflib.SequenceMatcher(None, a, t).ratio()
            min_r = 0.82 if len(a) <= 5 else 0.70
            s = ratio if ratio >= min_r else 0.0
        if a in t and a != t:
            s -= min(0.1, (len(t) - len(a)) / 400)          # entre vários que contêm o alvo, o mais curto
        s += 0.03 if i["acao"] else 0
        if s > sc:
            melhor, sc = i, s
    return (melhor, sc) if sc >= 0.65 else (None, sc)


def localizar(alvo, janela_id=None, vlm=True):
    """acha o alvo na janela: AT-SPI (nome exato/fuzzy) -> OCR -> VLM com conferência por zoom (grudado no item mais próximo).
    Devolve {x, y, nome, fonte, score, _no?} ou None."""
    t0 = time.time()
    r = ler(janela_id)
    if not r.get("janela"):
        return None
    i, sc = _pontua(alvo, r["itens"])
    if not i and r["fonte"] == "atspi":                        # AT-SPI rica mas sem o alvo: OCR da janela também
        r2 = ler(janela_id, ocr=True)
        i, sc = _pontua(alvo, [x for x in r2["itens"] if x["fonte"] == "ocr"])
        r = r2
    if i:
        out = {"x": i["cx"], "y": i["cy"], "nome": i["nome"] or i["texto"], "fonte": i["fonte"], "score": round(sc, 2),
               "papel": i["papel"], "_no": i.get("_no"), "estado": i.get("estado", []), "dh": r.get("dh"), "t": round(time.time() - t0, 3)}
        _log(op="localizar", alvo=alvo[:60], fonte=out["fonte"], nome=out["nome"][:60], x=out["x"], y=out["y"], score=out["score"], t=out["t"])
        return out
    if not vlm:
        _log(op="localizar", alvo=alvo[:60], fonte=None, score=round(sc, 2), t=round(time.time() - t0, 3))
        return None
    jan = r["janela"]
    try:                                                       # sem texto/nome: visão local na janela recortada, conferida por zoom
        import cv2
        import visao
        img = capturar(jan["cap"])
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88]) if img is not None else (False, None)
        p = visao.localizar(alvo, jpg.tobytes(), jan["cap"][2], jan["cap"][3]) if ok else None
    except Exception:
        p = None
    if not p:
        _log(op="localizar", alvo=alvo[:60], fonte=None, t=round(time.time() - t0, 3))
        return None
    x, y = jan["cap"][0] + p["x"], jan["cap"][1] + p["y"]
    perto = min(r["itens"], key=lambda z: abs(z["cx"] - x) + abs(z["cy"] - y), default=None)
    if perto and (perto["ax"] <= x <= perto["ax"] + perto["w"] and perto["ay"] <= y <= perto["ay"] + perto["h"]
                  or abs(perto["cx"] - x) + abs(perto["cy"] - y) <= 40):
        x, y = perto["cx"], perto["cy"]                        # gruda no centro do item real mais próximo
    out = {"x": x, "y": y, "nome": alvo, "fonte": "vlm", "score": None, "papel": "", "dh": r.get("dh"), "t": round(time.time() - t0, 3)}
    _log(op="localizar", alvo=alvo[:60], fonte="vlm", x=x, y=y, t=out["t"])
    return out


def estado():
    """foto rápida antes de uma ação: dHash da tela (escala 1/4) + janela em foco"""
    try:
        import cv2
        import numpy as np
        raw = subprocess.run(["grim", "-s", "0.25", "-t", "ppm", "-"], capture_output=True, timeout=4).stdout
        dh = dhash(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE))
    except Exception:
        dh = None
    w = _niri("focused-window") or {}
    return {"dh": dh, "foco": (w.get("id"), w.get("title"))}


def _estados_no(no):
    A = _atspi()
    try:
        with _lock:
            st = no.get_state_set()
        return [s for s in ("focused", "checked", "selected", "pressed", "expanded") if st.contains(getattr(A.StateType, s.upper()))]
    except Exception:
        return None


def efeito(antes, alvo=None, espera=1.5, minimo=4):
    """o clique teve efeito? (foco/título mudou, dHash mudou >= minimo bits, ou o estado do nó AT-SPI mudou) -> (bool, evidência)"""
    t_fim = time.time() + espera
    while True:
        time.sleep(0.25)
        d = estado()
        if d["foco"] != antes.get("foco"):
            return True, "a janela em foco/título mudou"
        b = bits(antes.get("dh"), d["dh"])
        if b is not None and b >= minimo:
            return True, f"a tela mudou ({b} bits)"
        if alvo and alvo.get("_no") is not None:
            e = _estados_no(alvo["_no"])
            if e is not None and e != alvo.get("estado"):
                return True, f"o elemento mudou de estado ({', '.join(e) or 'nenhum'})"
        if time.time() >= t_fim:
            return False, f"a tela não mudou ({b} bits)" if b is not None else "sem captura para conferir"


# ------------------------------------------------------------------ detector de dificuldades e erros na tela
_PADROES_DIFICULDADE = [
    # (regex, tipo, severidade, sugestao_template)
    (re.compile(r"Traceback \(most recent call last\):.*?(?:\n[^\n]+){1,6}", re.DOTALL | re.I),
     "Exceção Python / Stacktrace", "alta", "Identificar a exceção no final da pilha e aplicar a correção no código."),
    (re.compile(r"(?:ModuleNotFoundError|No module named ['\"]?([a-zA-Z0-9_\-]+)['\"]?)", re.I),
     "Módulo Python Ausente", "alta", "Instalar o módulo faltante no ambiente virtual (pip install)."),
    (re.compile(r"(?:SyntaxError|IndentationError):\s*([^\n]+)", re.I),
     "Erro de Sintaxe / Indentação", "alta", "Revisar a linha com a sintaxe incorreta ou identação inconsistente."),
    (re.compile(r"(?:NullPointerException|FATAL EXCEPTION|AndroidRuntime:[^\n]+)", re.I),
     "Crash / Exceção Android / Java", "alta", "Verificar objeto nulo ou chamada de método em referência inválida."),
    (re.compile(r"(?:Uncaught TypeError:[^\n]+|ReferenceError:[^\n]+|Cannot read properties of (?:undefined|null))", re.I),
     "Exceção JavaScript / TypeScript", "alta", "Checar verificação condicional (optional chaining '?.' ou guard clause)."),
    (re.compile(r"(?:npm ERR![^\n]+|yarn error[^\n]+|pnpm ERR![^\n]+)", re.I),
     "Falha de Dependência / Pacote Node", "alta", "Verificar package.json, versão do Node ou rodar limpeza de cache e reinstall."),
    (re.compile(r"(?:Build FAILED|Compilation error|error\[E\d+\]|ninja: build stopped: subcommand failed)", re.I),
     "Falha de Compilação / Build", "alta", "Analisar as mensagens do compilador para corrigir tipos ou dependências ausentes."),
    (re.compile(r"(?:Segmentation fault|Falha de segmentação|core dumped)", re.I),
     "Falha Crítica de Memória / Segfault", "alta", "Verificar ponteiros inválidos, estouro de buffer ou incompatibilidade de biblioteca binária."),
    (re.compile(r"(?:command not found|comando não encontrado|not recognized as an internal or external command)", re.I),
     "Comando Não Encontrado no Terminal", "media", "Verificar se o binário está instalado ou adicionado ao PATH do sistema."),
    (re.compile(r"(?:Permission denied|Permissão negada|EACCES)", re.I),
     "Erro de Permissão de Acesso", "media", "Conferir permissões de arquivo (chmod/chown) ou permissão de execução."),
    (re.compile(r"(?:Connection refused|ETIMEDOUT|NetworkError|404 Not Found|500 Internal Server Error|502 Bad Gateway)", re.I),
     "Erro de Rede / Serviço HTTP", "media", "Verificar se o serviço ou servidor de destino está ativo e acessível na rede."),
    (re.compile(r"(?:Campo obrigatório|Invalid email|Valor inválido|Preencha este campo)", re.I),
     "Validação de Formulário Pendente", "baixa", "Preencher ou corrigir os campos destacados no formulário.")
]


def detectar_dificuldades(leitura_tela=None, janela_id=None):
    """Analisa o conteúdo textual e semântico da tela para identificar falhas,
    erros de código, compilação quebrada ou dificuldades do usuário.
    -> {"tem_dificuldade": bool, "severidade": str, "tipo": str, "resumo": str, "detalhes": str, "sugestao": str}
    """
    if leitura_tela is None:
        try:
            leitura_tela = ler(janela_id)
        except Exception as e:
            return {"tem_dificuldade": False, "severidade": "baixa", "tipo": "none",
                    "resumo": f"Não foi possível ler a tela agora: {e}", "detalhes": "", "sugestao": ""}

    itens = (leitura_tela or {}).get("itens", [])
    textos = []
    for it in itens:
        t = (it.get("nome") or it.get("texto") or "").strip()
        if t and len(t) > 2:
            textos.append(t)

    corpo_tela = "\n".join(textos)
    if not corpo_tela:
        return {"tem_dificuldade": False, "severidade": "baixa", "tipo": "none",
                "resumo": "Tela sem texto legível detectado.", "detalhes": "", "sugestao": ""}

    for regex, tipo, sev, sugestao in _PADROES_DIFICULDADE:
        m = regex.search(corpo_tela)
        if m:
            detalhe = m.group(0).strip()
            # Trunca detalhe para caber no contexto
            if len(detalhe) > 300:
                detalhe = detalhe[:300] + "..."
            resumo = f"Detectado na tela: {tipo} ({detalhe.splitlines()[0][:100]})"
            return {
                "tem_dificuldade": True,
                "severidade": sev,
                "tipo": tipo,
                "resumo": resumo,
                "detalhes": detalhe,
                "sugestao": sugestao,
                "app": (leitura_tela.get("janela") or {}).get("app_id", "janela")
            }

    return {
        "tem_dificuldade": False,
        "severidade": "baixa",
        "tipo": "none",
        "resumo": "Nenhuma dificuldade, erro de compilação ou falha detectada na tela ativa.",
        "detalhes": "",
        "sugestao": ""
    }


# ------------------------------------------------------------------ CLI de teste / coleta no python do sistema
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ler"
    if cmd == "_arvore":
        jan = json.loads(sys.argv[2])
        A = _atspi()
        f = _frame(A, jan) if A else None
        it, info = _arvore(A, f, jan["rect"][2], jan["rect"][3]) if f else ([], {"sem_frame": True})
        for i in it:
            i.pop("_no", None)
        print(json.dumps({"itens": it, "info": info}, ensure_ascii=False))
    elif cmd == "ler":
        r = ler(sys.argv[2] if len(sys.argv) > 2 else None)
        print(texto(r, 60))
        print(json.dumps({"fonte": r["fonte"], "n": len(r["itens"]), "t": r["t"], "info": r.get("info"), "janela": r["janela"]}, ensure_ascii=False))
    elif cmd == "achar":
        p = localizar(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None, vlm="--vlm" in sys.argv)
        if p:
            p.pop("_no", None)
        print(json.dumps(p, ensure_ascii=False))
