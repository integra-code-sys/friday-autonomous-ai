#!/usr/bin/env python3
"""Navegador próprio da F.R.I.D.A.Y.: Chromium com perfil SEPARADO + CDP (o perfil do dono não aceita depurador).

O CDP só LÊ a página (onde está cada botão/campo, se há anúncio por cima, o texto). Quem age é o cursor e o
teclado REAIS (daemon/pc): move até o alvo, a própria página diz onde o cursor caiu (mousemove), corrige e só
então clica. Para tarefas fáceis a Friday continua no navegador do dono, por visão.

  navegador.py abrir URL | elementos | clicar TEXTO|#id | digitar TEXTO | anuncios | ler | estado | smoke
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("FRIDAY_NAV_PORT", "9333"))
PERFIL = os.path.expanduser("~/.local/share/friday/chromium-perfil")
PC = os.path.join(HERE, "pc")
_offset = None                     # (dx, dy): tela = página + offset; recalibra sozinho a cada clique


# ------------------------------------------------------------------ processo
def disponivel():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2).read()
        return True
    except Exception:
        return False


def garantir(url="about:blank"):
    """sobe o Chromium da Friday (127.0.0.1 apenas) se ainda não estiver no ar."""
    if disponivel():
        return True, "navegador da Friday já aberto"
    exe = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not exe:
        return False, "Chromium não encontrado"
    os.makedirs(PERFIL, exist_ok=True)
    subprocess.Popen([exe, f"--user-data-dir={PERFIL}", f"--remote-debugging-port={PORT}", "--remote-debugging-address=127.0.0.1",
                      "--ozone-platform=wayland", "--no-first-run", "--no-default-browser-check", "--deny-permission-prompts", "--password-store=gnome-libsecret",
                      "--class=friday-navegador", url],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        time.sleep(0.5)
        if disponivel():
            return True, "navegador da Friday aberto"
    return False, "o navegador não expôs o CDP a tempo"


def _abas():
    return [t for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=4)) if t.get("type") == "page"]


class Pagina:
    """conexão CDP com a aba ativa (a primeira 'page' da lista é a mais recente/ativa)."""
    def __init__(self, aba=None):
        from websockets.sync.client import connect
        abas = _abas()
        if not abas:
            raise RuntimeError("nenhuma aba aberta")
        self.aba = aba or abas[0]
        self.ws = connect(self.aba["webSocketDebuggerUrl"], max_size=2 ** 25, origin=None, open_timeout=5).__enter__()
        self._id = 0
        try:                                         # 19/10: alert/confirm/"sair da página?" congela a aba (todo evaluate = timeout 20 s)
            self.call("Page.handleJavaScriptDialog", accept=True)
        except Exception:
            pass                                     # "No dialog is showing" = normal

    def __enter__(self):
        return self

    def __exit__(self, *a):
        try:
            self.ws.close()
        except Exception:
            pass

    def call(self, metodo, **p):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": metodo, "params": p}))
        fim = time.time() + 20
        while time.time() < fim:
            m = json.loads(self.ws.recv(timeout=20))
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(m["error"].get("message", "erro CDP"))
                return m.get("result", {})
        raise TimeoutError(metodo)

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"].get("exception", {}).get("description", "erro JS"))[:300])
        return r.get("result", {}).get("value")


# ------------------------------------------------------------------ cursor/teclado reais
def _pc(*a, t=20):
    r = subprocess.run([sys.executable, PC, *map(str, a)], capture_output=True, text=True, timeout=t)
    if r.returncode != 0:
        raise RuntimeError(f"pc {a[0]}: {(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout.strip()


def _focar_janela():
    """traz a janela do navegador da Friday para frente (niri), pelo PID do processo do CDP."""
    try:
        ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=5).stdout)
        pids = set(map(int, subprocess.run(["pgrep", "-f", f"remote-debugging-port={PORT}"], capture_output=True, text=True).stdout.split()))
        for w in ws:
            if w.get("pid") in pids or w.get("app_id") == "friday-navegador":
                if not w.get("is_focused"):
                    subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(w["id"])], timeout=5)
                    time.sleep(0.35)
                return True
    except Exception:
        pass
    return False


# rastreia onde o cursor real está, em coordenadas da página (a página ouve o mousemove de verdade)
_JS_RASTRO = """(() => { if (!window.__fridayMouse) { window.__fridayMouse = {x:-1, y:-1, t:0};
  addEventListener('mousemove', e => { window.__fridayMouse = {x:e.clientX, y:e.clientY, t:Date.now()}; }, true); } return true; })()"""


def _onde_cursor(pg):
    return pg.js("window.__fridayMouse || {x:-1,y:-1,t:0}")


def _tela():
    try:
        o = next(iter(json.loads(subprocess.run(["niri", "msg", "--json", "outputs"], capture_output=True, text=True, timeout=5).stdout).values()))
        return int(o["logical"]["width"]), int(o["logical"]["height"])
    except Exception:
        return 1920, 1080


def _calibrar(pg):
    """no Wayland a página não sabe onde a janela está (screenX = 0): varre a tela com o cursor real até a
    página sentir o mousemove; daí tela - página = deslocamento exato."""
    global _offset
    W, H = _tela()
    pg.js("window.__fridayMouse = {x:-1, y:-1, t:0}")
    for sy in (H // 2, H // 3, 2 * H // 3):
        for sx in range(W - 120, 60, -160):           # da direita p/ a esquerda: o navegador da Friday costuma abrir à direita
            _pc("move", sx, sy)
            time.sleep(0.08)
            m = _onde_cursor(pg)
            if m.get("x", -1) >= 0:
                _offset = (sx - m["x"], sy - m["y"])
                return True
    return False


def _mover_ate(pg, x, y):
    """leva o cursor REAL ao ponto (x, y) da página: estima pela calibração, confere pelo mousemove e corrige."""
    global _offset
    pg.js(_JS_RASTRO)
    if _offset is None and not _calibrar(pg):
        return False
    for tentativa in range(4):
        if tentativa == 2 and not _calibrar(pg):       # janela mudou de lugar: recalibra uma vez
            return False
        sx, sy = int(round(x + _offset[0])), int(round(y + _offset[1]))
        pg.js("window.__fridayMouse = {x:-1, y:-1, t:0}")
        _pc("move", sx, sy)
        time.sleep(0.12)
        m = _onde_cursor(pg)
        if m.get("x", -1) < 0:
            _pc("move", sx + 3, sy + 3)            # mexe 3 px para a página registrar o mousemove
            time.sleep(0.12)
            m = _onde_cursor(pg)
            if m.get("x", -1) < 0:
                continue
            sx, sy = sx + 3, sy + 3
        _offset = (sx - m["x"], sy - m["y"])       # calibração real: tela - página
        if abs(m["x"] - x) <= 2 and abs(m["y"] - y) <= 2:
            return True
    return False


# ------------------------------------------------------------------ leitura da página
_JS_ELEMENTOS = r"""(() => {
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth
      && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
  const sel = 'a[href],button,input,textarea,select,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=option],[role=searchbox],[role=textbox],[contenteditable=true],[onclick],summary,label';
  const out = []; let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const topo = document.elementFromPoint(cx, cy);
    if (topo && topo !== el && !el.contains(topo) && !topo.contains(el)) continue;     // coberto por outra coisa
    const txt = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.title || el.alt || '').trim().replace(/\s+/g, ' ');
    el.setAttribute('data-friday', ++n);
    out.push({id: n, tag: el.tagName.toLowerCase(), tipo: el.type || el.getAttribute('role') || '', texto: txt.slice(0, 80),
              x: Math.round(cx), y: Math.round(cy), w: Math.round(r.width), h: Math.round(r.height)});
    if (out.length >= 150) break;
  }
  return {url: location.href, titulo: document.title, w: innerWidth, h: innerHeight, elementos: out};
})()"""

# camadas que cobrem a página (anúncio, cookie, newsletter, "assine") e o botão de fechar de cada uma
_JS_CAMADAS = r"""(() => {
  const W = innerWidth, H = innerHeight, res = [];
  const fechar = /^(×|✕|✖|x|fechar|close|pular|skip|pular anúncio|skip ad|não,? obrigad[oa]|agora não|no,? thanks|dispensar|dismiss|continuar no site|ok|entendi|aceitar|aceito|accept|accept all|aceitar todos|concordo|got it|prosseguir|continuar|fechar e continuar|permitir todos|rejeitar todos|recusar)$/i;
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (!(s.position === 'fixed' || s.position === 'sticky') || s.display === 'none' || s.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    const area = Math.max(0, Math.min(r.right, W) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, H) - Math.max(r.top, 0));
    const nome = (el.id + ' ' + el.className).toString().toLowerCase();
    const anuncio = /(^|[^a-z])(ad|ads|advert|banner|popup|pop-up|modal|overlay|interstitial|cookie|consent|newsletter|paywall|gdpr|lgpd)([^a-z]|$)/.test(nome) || el.querySelector('iframe[src*="doubleclick"],iframe[src*="googlesyndication"],iframe[id*="google_ads"]');
    const aviso = /cookie|consentimento|consent|lgpd|gdpr/i.test((el.innerText || '').slice(0, 600));
    if (area < W * H * 0.12 && !anuncio && !aviso) continue;
    if (el.tagName === 'HEADER' || el.tagName === 'NAV' || /header|navbar|topbar|menu/.test(nome) && !anuncio) continue;
    let btn = null;
    for (const b of el.querySelectorAll('button,a,[role=button],span,div,i,svg')) {
      const t = (b.innerText || b.getAttribute('aria-label') || b.title || '').trim();
      const rb = b.getBoundingClientRect();
      if (rb.width < 6 || rb.height < 6 || rb.width > 260) continue;
      if (fechar.test(t) || /close|fechar|dismiss/i.test((b.getAttribute('aria-label') || '') + ' ' + (b.className || '').toString())) { btn = b; break; }
    }
    if (!btn) {                                                             // 19/10: botão só-ícone (svg sem texto/rótulo) no canto de cima à direita
      for (const b of el.querySelectorAll('button,[role=button],a,svg,span,i,div')) {
        const rb = b.getBoundingClientRect(), t = (b.innerText || '').trim();
        if (rb.width >= 8 && rb.height >= 8 && rb.width <= 56 && rb.height <= 56 && t.length <= 1 && getComputedStyle(b).cursor === 'pointer'
            && r.right - rb.right <= 40 && rb.top - r.top <= 40) { btn = b; break; }
      }
    }
    const rb = btn && btn.getBoundingClientRect();
    if (res.some(o => o._el.contains(el))) continue;                        // já pego pela camada de fora
    res.push({_el: el, sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''), cobre: Math.round(100 * area / (W * H)), anuncio: !!anuncio, aviso,
              botao: btn ? {texto: (btn.innerText || btn.getAttribute('aria-label') || '').trim().slice(0, 30), x: Math.round(rb.left + rb.width / 2), y: Math.round(rb.top + rb.height / 2)} : null,
              _i: [...document.querySelectorAll('body *')].indexOf(el)});
    if (res.length >= 8) break;
  }
  return res.map(({_el, ...o}) => o);
})()"""

_JS_TEXTO = r"""(() => {
  const lixo = 'script,style,noscript,svg,nav,footer,aside,iframe,[role=banner],[role=navigation],[aria-hidden=true],.ad,.ads,.advert,[class*=cookie],[id*=cookie]';
  const raiz = document.querySelector('article') || document.querySelector('main') || document.body;
  const c = raiz.cloneNode(true); c.querySelectorAll(lixo).forEach(e => e.remove());
  return {url: location.href, titulo: document.title, texto: (c.innerText || '').replace(/\n{3,}/g, '\n\n').trim().slice(0, 20000)};
})()"""


def elementos():
    with Pagina() as pg:
        return pg.js(_JS_ELEMENTOS)


def ler():
    with Pagina() as pg:
        return pg.js(_JS_TEXTO)


def _esperar_carregar(pg, limite=15):
    fim = time.time() + limite
    while time.time() < fim:
        try:
            if pg.js("document.readyState") == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


# ------------------------------------------------------------------ ações (cursor/teclado reais)
def abrir(url):
    """abre a URL no navegador da Friday pela barra de endereço (ctrl+l, digita, Enter) e fecha anúncios."""
    ok, msg = garantir()
    if not ok:
        return {"ok": False, "erro": msg}
    if not re.match(r"^[a-z]+://", url):
        url = "https://" + url if "." in url and " " not in url else "https://www.google.com/search?q=" + urllib.request.quote(url)
    _focar_janela()
    _pc("key", "ctrl+l")
    _pc("type", url)
    _pc("key", "enter")
    time.sleep(0.8)
    with Pagina() as pg:
        _esperar_carregar(pg)
        fechados = _fechar_camadas(pg)
        return {"ok": True, "url": pg.js("location.href"), "titulo": pg.js("document.title"), "anuncios_fechados": fechados}


def _sumiu(pg, sel, limite=2.0):
    """espera a camada clicada sair (animação de fade) antes de olhar de novo: senão o 2º clique cai no conteúdo de baixo."""
    fim = time.time() + limite
    while time.time() < fim:
        if not any(c["sel"] == sel for c in (pg.js(_JS_CAMADAS) or [])):
            return True
        time.sleep(0.25)
    return False


def _fechar_camadas(pg, rodadas=3):
    fechados, clicadas = [], set()
    for _ in range(rodadas):
        camadas = [c for c in (pg.js(_JS_CAMADAS) or []) if c["sel"] not in clicadas]
        if not camadas:
            break
        for cm in camadas:
            b = cm.get("botao")
            if b and _mover_ate(pg, b["x"], b["y"]):
                _pc("click")
                clicadas.add(cm["sel"])
                fechados.append(f"{cm['sel']} ({b['texto'] or 'x'}) pelo botão" + ("" if _sumiu(pg, cm["sel"]) else " (não sumiu)"))
            elif cm.get("anuncio") or cm.get("cobre", 0) >= 40:
                # sem botão de fechar: esconde a camada (só a camada; o conteúdo da página continua)
                pg.js(f"(() => {{ const e = document.querySelectorAll('body *')[{cm['_i']}]; if (e) e.style.setProperty('display','none','important');"
                      " document.documentElement.style.overflow = 'auto'; document.body.style.overflow = 'auto'; })()")
                fechados.append(f"{cm['sel']} escondida (sem botão)")
        time.sleep(0.5)
    return fechados


def anuncios():
    with Pagina() as pg:
        _focar_janela()
        return _fechar_camadas(pg)


def _achar(pg, alvo):
    els = pg.js(_JS_ELEMENTOS)["elementos"]
    if str(alvo).startswith("#") and str(alvo)[1:].isdigit():
        return next((e for e in els if e["id"] == int(str(alvo)[1:])), None)
    a = alvo.lower().strip()
    exato = [e for e in els if e["texto"].lower() == a]
    if exato:
        return exato[0]
    parte = [e for e in els if a in e["texto"].lower()]
    return min(parte, key=lambda e: len(e["texto"])) if parte else None


def clicar(alvo):
    """clica num elemento pelo texto visível (ou #id da lista de elementos) com o cursor real; rola até ele se preciso."""
    _focar_janela()
    with Pagina() as pg:
        _fechar_camadas(pg, rodadas=1)
        el = _achar(pg, alvo)
        if not el:
            pg.js("scrollBy(0, innerHeight * 0.8)")
            time.sleep(0.4)
            el = _achar(pg, alvo)
        if not el:
            return {"ok": False, "erro": f"não achei '{alvo}' na página"}
        if not _mover_ate(pg, el["x"], el["y"]):
            return {"ok": False, "erro": "o cursor não chegou no alvo (janela coberta?)"}
        antes = pg.js("location.href + '|' + document.body.innerText.length")
        _pc("click")
        time.sleep(0.6)
        _esperar_carregar(pg, 8)
        try:
            depois = pg.js("location.href + '|' + document.body.innerText.length")
        except Exception:
            depois = "navegou"
        return {"ok": True, "clicou": el["texto"] or el["tag"], "mudou": antes != depois}


def digitar(texto, alvo=None, enter=False):
    """digita com o teclado real; se alvo for dado, clica no campo antes (texto do placeholder/rótulo ou #id)."""
    _focar_janela()
    if alvo:
        r = clicar(alvo)
        if not r.get("ok"):
            return r
    _pc("type", texto)
    if enter:
        _pc("key", "enter")
    return {"ok": True}


_JS_RESULTADOS = r"""(() => {
  const out = [];
  for (const h of document.querySelectorAll('a h3')) {
    const a = h.closest('a'); if (!a || !a.href) continue;
    const u = a.href, U = new URL(u);
    // o Google embrulha o resultado em /goto ou /url (redireciona p/ o site real ao abrir); o resto do domínio é dele mesmo
    if (/googleadservices|doubleclick/.test(U.hostname) || (/google\./.test(U.hostname) && !/^\/(goto|url)$/.test(U.pathname))) continue;
    const cite = (a.closest('[data-hveid]') || a.parentElement || a).querySelector('cite');
    if (a.closest('[data-text-ad],#tads,#bottomads,[aria-label*="núncio"],[aria-label*="Ads"]')) continue;   // anúncios pagos
    if (!out.some(o => o.url === u)) out.push({url: u, titulo: h.innerText.trim().slice(0, 120), site: cite ? cite.innerText.split(' ')[0].slice(0, 80) : ''});
    if (out.length >= 8) break;
  }
  return out;
})()"""


def resultados_busca(consulta, n=5):
    """pesquisa no Google pelo navegador da Friday (teclado real) e devolve os resultados ORGÂNICOS (sem anúncio pago)."""
    r = abrir(consulta)
    if not r.get("ok"):
        return []
    with Pagina() as pg:
        return (pg.js(_JS_RESULTADOS) or [])[:n]


def estado():
    if not disponivel():
        return {"aberto": False}
    with Pagina() as pg:
        return {"aberto": True, "url": pg.js("location.href"), "titulo": pg.js("document.title"), "abas": len(_abas())}


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 0
    cmd, resto = argv[1], " ".join(argv[2:])
    f = {"abrir": lambda: abrir(resto), "elementos": elementos, "clicar": lambda: clicar(resto), "digitar": lambda: digitar(resto),
         "anuncios": anuncios, "ler": ler, "estado": estado, "buscar": lambda: resultados_busca(resto), "garantir": lambda: garantir()}.get(cmd)
    if not f:
        print("comando desconhecido")
        return 2
    print(json.dumps(f(), ensure_ascii=False, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
