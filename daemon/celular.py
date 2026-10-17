"""Controle do CELULAR do dono pela F.R.I.D.A.Y., via VNC (app droidVNC-NG no Android, pelo Tailscale).
Ela vê (print + OCR em português), toca, arrasta, rola, digita e usa voltar/início — tudo rodando daqui do PC.
O dono acompanha: a tela do celular aparece no holograma com um anel marcando cada toque.
Config: memory/celular.json {"host": "100.125.114.10", "porta": 5900, "senha": "...", "pin": "..."} (0600).
PONTE (app F.R.I.D.A.Y. 2.1+, serviço de acessibilidade ativo): http://host:8791 com o token de memory/remoto.json —
acende a tela, desbloqueia tocando nos botões reais do PIN, voltar/início/notificações. O VNC continua para ver e tocar."""
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "..", "memory", "celular.json")
SHOT = "/tmp/friday-cel.png"
VIS = "/tmp/friday-cel-holo.png"
TESS = os.path.expanduser("~/.local/share/tessdata")
_lock = threading.RLock()
_cli = {"c": None, "t": 0.0}
_SENS = re.compile(r"\b(pagar|pague|pix|transferir|transfer[êe]ncia|confirmar pagamento|comprar|enviar dinheiro|excluir|apagar|deletar|"
                   r"senha|desinstalar|redefinir|formatar|sair da conta)\b", re.I)


def config():
    try:
        return json.load(open(CFG))
    except Exception:
        return {}


def salvar_config(host=None, senha=None, porta=None):
    c = config()
    if host:
        c["host"] = host
    if senha is not None:
        c["senha"] = senha
    if porta:
        c["porta"] = int(porta)
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    json.dump(c, open(CFG, "w"), indent=1)
    os.chmod(CFG, 0o600)
    desconectar()
    return c


# ------------------------------------------------------------------ ponte nativa (app F.R.I.D.A.Y. no celular)
PONTE_PORTA = 8791


def ponte(rota, timeout=12, **q):
    """chama a ponte do app no celular. Erro claro se o serviço de acessibilidade não estiver ativo."""
    c = config()
    if not c.get("host"):
        raise RuntimeError("celular não configurado (memory/celular.json)")
    try:
        tok = json.load(open(os.path.join(HERE, "..", "memory", "remoto.json")))["token"]
    except Exception:
        raise RuntimeError("sem token em memory/remoto.json")
    url = f"http://{c['host']}:{int(c.get('ponte_porta', PONTE_PORTA))}{rota}" + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={"X-Token": tok})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            dados = r.read()
            return dados if r.headers.get_content_type() == "image/jpeg" else json.loads(dados)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ponte do celular respondeu {e.code} (token do app diferente do PC? abra o app e reconecte)")
    except OSError:
        raise RuntimeError("ponte do celular inacessível: no celular, ative Acessibilidade → 'F.R.I.D.A.Y. · controle pelo PC' (app 2.1+)")


def pedir_local(texto, timeout=180):
    """pede à Friday LOCAL do celular (cérebro Qwen3 no próprio aparelho, app 4.0+) e devolve a fala final dela.
    Cada uma funciona sozinha; ligadas juntas, o PC usa isto para o que é do celular (apps, documentos, alarmes...)."""
    r = ponte("/pedir", timeout=timeout, t2=str(texto)[:2000])
    return str(r.get("resposta") or r.get("erro") or "sem resposta")


_pv = {"ok": False, "t": 0.0, "w": 0, "h": 0}


def ponte_ok(cache=20):
    """a ponte responde? (resultado guardado por alguns segundos: captura/toque consultam a cada ação)"""
    if time.time() - _pv["t"] < cache:
        return _pv["ok"]
    try:
        e = ponte("/estado", timeout=4)
        _pv.update(ok=bool(e.get("ok")), w=int(e.get("w") or 0), h=int(e.get("h") or 0))
    except Exception:
        _pv["ok"] = False
    _pv["t"] = time.time()
    return _pv["ok"]


def acordar():
    """acende a tela do celular (pela ponte); devolve o estado."""
    e = ponte("/acordar")
    time.sleep(0.6)
    return e


def manter_acesa(seg=600):
    """segura a tela acesa enquanto ela mexe no celular (some sozinha depois de seg)."""
    return ponte("/manter", s=int(seg))


def desconectar():
    with _lock:
        try:
            if _cli["c"]:
                _cli["c"].disconnect()
        except Exception:
            pass
        _cli["c"] = None


def _c():
    """conexão VNC persistente (reconecta se caiu)."""
    from vncdotool import api
    with _lock:
        if _cli["c"] is not None:
            return _cli["c"]
        c = config()
        if not c.get("host"):
            raise RuntimeError("celular não configurado (memory/celular.json: host e senha do droidVNC-NG)")
        cli = api.connect(f"{c['host']}::{int(c.get('porta', 5900))}", password=c.get("senha") or None, timeout=15)
        _cli["c"], _cli["t"] = cli, time.time()
        return cli


def _faz(fn):
    """executa no cliente; se a conexão caiu, reconecta uma vez."""
    for tentativa in range(2):
        try:
            with _lock:
                return fn(_c())
        except Exception:
            desconectar()
            if tentativa:
                raise


def disponivel():
    try:
        _faz(lambda c: c.refreshScreen())
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ ver
def capturar():
    """print do celular. Pela ponte (captura do próprio Android) quando ativa — o droidVNC-NG congela no último quadro
    depois que a tela apaga; o print da ponte vem pela metade e é ampliado ao tamanho real (mesmas coordenadas do toque)."""
    for tentativa in range(3 if ponte_ok() else 0):      # o Android limita prints da acessibilidade (~1/s): espera e repete
        if tentativa:
            time.sleep(1.1)
        try:
            jpg = ponte("/tela", timeout=8)
            if isinstance(jpg, bytes) and len(jpg) > 1000:
                import io
                from PIL import Image
                im = Image.open(io.BytesIO(jpg)).convert("RGB")
                if _pv["w"] and _pv["h"]:
                    im = im.resize((_pv["w"], _pv["h"]))
                im.save(SHOT)
                return SHOT
        except Exception:
            pass                                       # tela protegida (FLAG_SECURE) ou limite de prints: cai p/ o VNC
    _faz(lambda c: c.captureScreen(SHOT))
    return SHOT


def linhas(caminho=None):
    """OCR (tesseract português+inglês) da tela do celular: [{'t','x','y'}] em coordenadas do celular."""
    caminho = caminho or capturar()
    from PIL import Image, ImageOps
    im = Image.open(caminho).convert("L")
    k = max(1.0, 1100 / im.size[0])                     # o droidVNC-NG manda a tela reduzida: amplia p/ o OCR e devolve em coords do celular
    big = "/tmp/friday-cel-ocr.png"
    ImageOps.autocontrast(im.resize((int(im.size[0] * k), int(im.size[1] * k)), Image.LANCZOS)).save(big)
    env = dict(os.environ, TESSDATA_PREFIX=TESS) if os.path.isdir(TESS) else None
    r = subprocess.run(["tesseract", big, "-", "--psm", "11", "-l", "por+eng", "tsv"], capture_output=True, text=True, timeout=60, env=env)
    grupos = {}
    for row in r.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            if float(c[10]) < 45:
                continue
        except ValueError:
            continue
        x, y, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        d = grupos.setdefault((c[2], c[3], c[4]), {"w": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h})
        d["w"].append(c[11].strip()); d["x1"] = max(d["x1"], x + w); d["y1"] = max(d["y1"], y + h)
    out = [{"t": " ".join(d["w"])[:70], "x": int((d["x0"] + d["x1"]) / 2 / k), "y": int((d["y0"] + d["y1"]) / 2 / k)}
           for d in grupos.values() if len(" ".join(d["w"])) >= 2]
    out.sort(key=lambda z: (z["y"] // 20, z["x"]))
    return out


def tamanho():
    from PIL import Image
    if not os.path.exists(SHOT):
        capturar()
    return Image.open(SHOT).size


def mostrar(x=None, y=None, titulo="CELULAR"):
    """projeta a tela do celular no holograma do PC, com um anel onde ela tocou (o dono acompanha).
    App 2.3+: vídeo ao vivo a 60 fps (celtela); app antigo/sem transmissão: print estático como antes."""
    try:
        import celtela
        celtela.mostrar(x, y)
        return
    except Exception:
        pass
    try:
        from PIL import Image, ImageDraw
        im = Image.open(SHOT).convert("RGB")
        if x is not None:
            d = ImageDraw.Draw(im)
            r = max(18, im.size[0] // 22)
            d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 138, 31), width=max(4, r // 5))
            d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(143, 233, 255))
        im.save(VIS)
        from prom_ops import holo_show
        holo_show({"kind": "imagem", "src": "file://" + VIS + "?" + str(time.time()), "titulo": titulo, "tamanho": "mao", "ttl": 120})
    except Exception:
        pass


# ------------------------------------------------------------------ agir
def tocar(x, y, ver=True):
    """ver=False: não tira print depois (holograma ao vivo já mostra; não pesa no celular a cada toque)."""
    x, y = int(x), int(y)
    if ponte_ok():
        ponte("/toque", x=x, y=y)
    else:
        _faz(lambda c: (c.mouseMove(x, y), c.mousePress(1)))
    if not ver:
        mostrar(x, y); return f"toquei em {x},{y}"
    time.sleep(0.8)
    capturar(); mostrar(x, y)
    return f"toquei em {x},{y}"


def segurar(x, y, ms=900, ver=True):
    x, y = int(x), int(y)
    if ponte_ok():
        ponte("/toque", x=x, y=y, ms=int(ms))
    else:
        _faz(lambda c: (c.mouseMove(x, y), c.mouseDown(1)))
        time.sleep(ms / 1000)
        _faz(lambda c: c.mouseUp(1))
    if not ver:
        mostrar(x, y); return f"segurei em {x},{y}"
    time.sleep(0.6); capturar(); mostrar(x, y)
    return f"segurei em {x},{y}"


def arrastar(x0, y0, x1, y1, passos=14, ver=True):
    def go(c):
        c.mouseMove(int(x0), int(y0)); c.mouseDown(1)
        for i in range(1, passos + 1):
            c.mouseMove(int(x0 + (x1 - x0) * i / passos), int(y0 + (y1 - y0) * i / passos))
            time.sleep(0.015)
        c.mouseUp(1)
    if ponte_ok():
        ponte("/arrastar", x0=int(x0), y0=int(y0), x1=int(x1), y1=int(y1), ms=350)
    else:
        _faz(go)
    if not ver:
        mostrar(int(x1), int(y1)); return "arrastei"
    time.sleep(0.8); capturar(); mostrar(int(x1), int(y1))
    return "arrastei"


def rolar(n=3):
    """n>0 desce o conteúdo (dedo sobe), n<0 sobe. Arraste no meio da tela (mais confiável que a roda no Android)."""
    w, h = tamanho()
    for _ in range(min(abs(int(n)), 6)):
        if n > 0:
            arrastar(w // 2, int(h * 0.72), w // 2, int(h * 0.32))
        else:
            arrastar(w // 2, int(h * 0.32), w // 2, int(h * 0.72))
        time.sleep(0.3)
    return f"rolei {n}"


def tecla(nome, ver=True):
    """voltar | inicio | recentes | notificacoes | enter | apagar | tab. Pela ponte (ações globais do Android) quando ativa;
    senão droidVNC-NG: Esc = voltar, Home = tela inicial."""
    glob = {"voltar": "voltar", "back": "voltar", "inicio": "inicio", "início": "inicio", "home": "inicio", "recentes": "recentes",
            "notificacoes": "notificacoes", "notificações": "notificacoes", "rapidas": "rapidas"}.get(str(nome).lower().strip())
    if glob and ponte_ok():
        r = ponte("/global", a=glob)
        if ver:
            time.sleep(0.8); capturar()
        mostrar()
        return f"tecla {nome}" if r.get("ok") else f"tecla {nome} falhou: {r.get('erro', '')}"
    mapa = {"voltar": "esc", "back": "esc", "inicio": "home", "início": "home", "home": "home", "enter": "enter",
            "apagar": "bsp", "backspace": "bsp", "tab": "tab"}
    k = mapa.get(str(nome).lower().strip())
    if not k:
        raise ValueError("tecla do celular: voltar|inicio|enter|apagar|tab")
    _faz(lambda c: c.keyPress(k))
    time.sleep(0.8); capturar()
    if k == "home":                                    # neste launcher, Home já na tela inicial abre a busca: fecha com voltar
        if any(re.search(r"pesquisar contatos|pesquisar apps|search apps", l["t"], re.I) for l in linhas(SHOT)):
            _faz(lambda c: c.keyPress("esc")); time.sleep(0.8); capturar()
    mostrar()
    return f"tecla {nome}"


def digitar(texto, enter=False):
    """digita no campo em foco do celular (keysyms Latin-1/Unicode: acentos inclusos)."""
    def go(c):
        for ch in str(texto):
            cp = ord(ch)
            if ch == "\n":
                c.keyPress("enter")
            elif ch == " ":
                c.keyPress("space")
            else:
                c.keyPress(ch)                             # o vncdotool converte o caractere no keysym (acentos inclusos)
            time.sleep(0.03)
        if enter:
            c.keyPress("enter")
    _faz(go)
    time.sleep(0.6); capturar(); mostrar()
    return f"digitei: {str(texto)[:60]}"


def tocar_texto(texto):
    """acha o texto na tela do celular (OCR) e toca nele. Recusa ações sensíveis (pagar, pix, apagar, senha...)."""
    import difflib
    alvo = str(texto).strip()
    if _SENS.search(alvo):
        raise PermissionError("ação sensível no celular (pagamento/apagar/senha): isso fica com o dono")
    L = linhas()
    a = alvo.lower()
    best, sc = None, 0.0
    for l in L:
        t = l["t"].lower()
        s = 1.0 if a == t else (0.92 if a in t else difflib.SequenceMatcher(None, a, t).ratio())
        if s > sc:
            best, sc = l, s
    if not best or sc < 0.6:
        raise LookupError(f"não achei '{alvo}' na tela do celular")
    tocar(best["x"], best["y"])
    return f"toquei em '{best['t']}' ({best['x']},{best['y']})"


def abrir_app(nome):
    """abre um app pelo nome: gaveta + Home -> busca universal do launcher ("Pesquisar contatos e aplicativos")
    -> digita o nome -> toca no app. Se a busca não aparecer, tenta a gaveta (deslizar para cima)."""
    if ponte_ok():                                     # app 2.2+: abre pelo sistema, sem depender do launcher
        try:
            r = ponte("/abrir", nome=nome)
            if not r.get("ok"):                        # nome falado != rótulo do app (ex.: Configurações = "Configurar" na Moto)
                import difflib
                import unicodedata
                n = lambda t: "".join(ch for ch in unicodedata.normalize("NFD", t.lower()) if ch.isalnum())
                sin = {"configuracoes": "configurar", "ajustes": "configurar", "definicoes": "configurar", "zap": "whatsapp",
                       "camera": "camera", "galeria": "fotos", "navegador": "chrome", "email": "gmail", "musica": "spotify"}
                alvo = sin.get(n(nome), n(nome))
                rotulos = [x["nome"] for x in ponte("/apps").get("apps", [])]
                melhor = max(rotulos, key=lambda r_: difflib.SequenceMatcher(None, alvo, n(r_)).ratio(), default="")
                if melhor and difflib.SequenceMatcher(None, alvo, n(melhor)).ratio() >= 0.6:
                    r = ponte("/abrir", nome=melhor)
            if r.get("ok"):
                time.sleep(1.5); capturar(); mostrar()
                return f"abri {r.get('app', nome)}"
        except Exception:
            pass
    for _ in range(2):
        _faz(lambda c: c.keyPress("esc")); time.sleep(0.4)
    w0, h0 = tamanho()
    arrastar(w0 // 2, int(h0 * 0.85), w0 // 2, int(h0 * 0.25)); time.sleep(1.2)    # abre a gaveta (por categorias, no launcher Moto)
    L = linhas(SHOT)
    titulo = next((l for l in L if h0 * 0.08 < l["y"] < h0 * 0.6 and l["x"] < w0 * 0.5 and len(l["t"]) >= 4 and l["t"][0].isupper()), None)
    if titulo:                                                   # a lupa fica na mesma linha do título da categoria, à direita
        tocar(int(w0 * 0.69), titulo["y"]); time.sleep(1.2)
    capturar()
    L = linhas(SHOT)
    campo = next((l for l in L if re.search(r"pesquisar|buscar|search", l["t"], re.I)), None)
    if campo:
        tocar(campo["x"], campo["y"]); time.sleep(0.6)
        digitar(nome); time.sleep(1.8)
        L = linhas()
        h = tamanho()[1]
        import difflib
        cand = [l for l in L if l["y"] > campo["y"] + 15 and difflib.SequenceMatcher(None, nome.lower(), l["t"].lower()).ratio() >= 0.6
                or (nome.lower() in l["t"].lower() and l["y"] > campo["y"] + 15)]
        if cand:
            alvo = cand[0]
            tocar(alvo["x"], max(alvo["y"] - int(h * 0.03), 0))        # o nome fica sob o ícone: toca um pouco acima (no ícone)
            return f"abri {alvo['t']}"
    w, h = tamanho()
    arrastar(w // 2, int(h * 0.85), w // 2, int(h * 0.25)); time.sleep(1.2)
    try:
        return tocar_texto(nome)
    except LookupError:
        raise LookupError(f"não achei o app '{nome}' no celular")


def tela_apagada(caminho=None):
    """tela em repouso = o Android entrega imagem (quase) toda preta ao VNC; nada a fazer até alguém acender a tela."""
    from PIL import Image, ImageStat
    im = Image.open(caminho or capturar()).convert("L").resize((64, 140))
    st = ImageStat.Stat(im)
    return st.mean[0] < 6 and st.stddev[0] < 6


def bloqueado(L=None):
    """tela de bloqueio: relógio grande + avisos típicos, ou o teclado do PIN."""
    L = L if L is not None else linhas()
    txt = " ".join(l["t"] for l in L).lower()
    return bool(re.search(r"insira o pin|digite o pin|enter pin|desbloque|deslize para|swipe up|chamada de emergência|emergency", txt))


def desbloquear():
    """acende e desbloqueia. 1º pela ponte (toca nos botões reais do PIN pela acessibilidade); senão pelo VNC:
    desliza para cima e toca nos dígitos achados pelo OCR (ou digita + Enter)."""
    pin = str(config().get("pin") or "")
    if not pin:
        raise RuntimeError("sem PIN configurado")
    if ponte_ok():
        r = ponte("/desbloquear", timeout=30, pin=pin)
        if r.get("ok"):
            time.sleep(0.8); capturar()
            return "desbloqueado"
        if not r.get("tela", True):
            return "não consegui acender a tela pela ponte"
    w, h = tamanho()
    arrastar(w // 2, int(h * 0.85), w // 2, int(h * 0.3)); time.sleep(1.2)
    L = linhas()
    dig = {}
    for l in L:
        t = l["t"].strip()
        if re.fullmatch(r"\d", t) and l["y"] > h * 0.4:        # teclas do PIN: um dígito por linha, na metade de baixo
            dig.setdefault(t, l)
    if all(d in dig for d in set(pin)):
        for d in pin:
            _faz(lambda c, p=dig[d]: (c.mouseMove(p["x"], p["y"]), c.mousePress(1)))
            time.sleep(0.25)
    else:
        digitar(pin)
    _faz(lambda c: c.keyPress("enter"))
    time.sleep(1.5); capturar()
    return "desbloqueado" if not bloqueado() else "tentei desbloquear, mas a tela de bloqueio continua"


def ver():
    """resumo da tela do celular para o agente: tamanho + linhas de texto com posição (desbloqueia sozinha se precisar)."""
    try:                                                   # estado REAL pela ponte: com a tela apagada o droidVNC-NG
        e = ponte("/estado", timeout=4)                    # entrega o último quadro antigo (não fica preto)
    except Exception:
        e = None
    if e is not None and (not e.get("tela") or e.get("bloqueado")):
        if not e.get("tela"):
            e = acordar()
        if e.get("bloqueado") and config().get("pin"):
            desbloquear()
        try:
            manter_acesa(600)
        except Exception:
            pass
        time.sleep(1.0)
    elif e is None and tela_apagada():
        if not ponte_ok():
            raise RuntimeError("a tela do celular está APAGADA e a ponte do app não responde: no celular, ative Acessibilidade → "
                               "'F.R.I.D.A.Y. · controle pelo PC' (app F.R.I.D.A.Y. 2.1+)")
        e = acordar()
        if e.get("bloqueado") and config().get("pin"):
            desbloquear()
        try:
            manter_acesa(600)
        except Exception:
            pass
        time.sleep(0.5)
        if tela_apagada():
            raise RuntimeError("pedi para acender a tela, mas o VNC continua preto (droidVNC-NG parado?)")
    L = linhas()
    if bloqueado(L) and config().get("pin"):
        desbloquear()
        L = linhas()
    mostrar()
    w, h = tamanho()
    return f"celular {w}x{h}\ntexto visível:\n" + "\n".join(f"{l['t']} @{l['x']},{l['y']}" for l in L[:50])
