#!/usr/bin/env python3
"""zap — ponte com o WhatsApp do ZapZap (Linux) via Chrome DevTools Protocol local (127.0.0.1:9223).

O ZapZap precisa estar rodando com o depurador local ligado (ver launch()). Tudo é local; nada passa por serviço externo.
- snapshot(): lista de conversas (nome, prévia, hora, não lidas) lida DIRETO da lista — não abre conversas, não gera "visto".
- read_chat(nome): abre a conversa e devolve as últimas mensagens (isso marca como lida; use com critério).
- send(nome, texto): abre a conversa e envia (a política `wa.send_chat` decide se precisa aprovação — chamada por prom_ops).
"""
import asyncio, json, os, re, shutil, subprocess, time, urllib.request

PORT = int(os.environ.get("PROMETHEUS_ZAP_PORT", "9223"))
APP = "com.rtosta.zapzap"

_JS_SNAPSHOT = r"""(()=>{
  const side=document.querySelector('#pane-side'); if(!side) return {ok:false, motivo:'lista de conversas ausente (QR/login?)'};
  const rows=[...side.querySelectorAll('[role="row"]')].filter(r=>r.querySelector('span[title]'));
  const timeRe=/^(\d{1,2}:\d{2}|ontem|hoje|domingo|segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|\d{1,2}\/\d{1,2}(\/\d{2,4})?)/i;
  const out=[];
  for(const r of rows){
    const t=r.querySelector('span[title]'); const nome=t.getAttribute('title')||t.textContent;
    const leaves=[...r.querySelectorAll('span,div')].filter(e=>e.children.length===0&&(e.textContent||'').trim());
    const texts=leaves.map(e=>e.textContent.trim());
    const hora=texts.find(x=>timeRe.test(x))||'';
    let nl=0; const al=[...r.querySelectorAll('[aria-label]')].map(e=>e.getAttribute('aria-label')).find(a=>/n[ãa]o lida/i.test(a));
    if(al){const m=al.match(/(\d+)/); nl=m?parseInt(m[1]):1;}
    const cand=texts.filter(x=>x!==nome&&x!==hora&&!/^\d+$/.test(x)&&!/^\(.*\)$/.test(x));
    const previa=cand.length?cand[cand.length-1]:'';
    out.push({id:r.getAttribute('data-testid')||'', nome, hora, previa:previa.slice(0,240), nao_lidas:nl,
              silenciada:!!r.querySelector('[data-icon="muted"],[data-testid="muted"]'), fixada:!!r.querySelector('[data-icon="pinned"],[data-testid="pinned"]')});
  }
  return {ok:true, titulo:document.title, chats:out};
})()"""

_JS_OPEN = r"""((nome)=>{
  const side=document.querySelector('#pane-side'); if(!side) return {ok:false, motivo:'sem lista'};
  const rows=[...side.querySelectorAll('[role="row"]')].filter(r=>r.querySelector('span[title]'));
  
  const clean = (s) => (s||'').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[@_\-\s\.]/g, '');
  const norm = (s) => (s||'').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  
  let n = (nome||'');
  n = n.replace(/^(?:(?:prepare|preparar)?\s*(?:para\s+)?(?:enviar|mandar)\s+(?:mensagem\s+)?(?:para|a|ao|pro)\s+)/i, '');
  n = n.replace(/^(?:o|a|meu|minha|ao|pro|para)\s+/i, '');
  n = n.replace(/\s+(?:no|pelo|via)\s+(?:zap(?:\s?zap)?|whatsapp).*$/i, '').trim();
  
  const nn = norm(n);
  const cn = clean(n);
  const ehDono = cn === 'integracode' || cn === 'integreacode' || cn === 'integra' || cn === 'integrea' || cn === 'eu' || cn === 'mim' || cn === 'voce' || cn === 'me';
  const wordsN = nn.split(/\s+/).filter(w => w.length >= 3);

  // pontua TODAS as conversas; empate entre nomes parecidos = ambíguo (não abre a errada; a Friday pergunta qual)
  const cands = [];
  for (const r of rows) {
    const rawTitle = r.querySelector('span[title]').getAttribute('title') || '';
    const t = norm(rawTitle);
    const ct = clean(rawTitle);
    const isYou = !!(r.querySelector('[data-testid="you-label"]') || r.querySelector('[data-testid="message-yourself-row"]'));
    let score = 0;
    if (ehDono && (isYou || ct.includes('integracode') || ct.includes('integreacode') || ct.includes('integra') || ct.includes('integrea'))) score = 101;
    else if (t === nn || ct === cn) score = 100;
    else if (t.includes(nn) || (nn.length >= 3 && nn.includes(t)) || ct.includes(cn) || (cn.length >= 4 && cn.includes(ct))) score = 85;
    else {
      const wordsT = t.split(/\s+/).filter(w => w.length >= 3);
      let common = 0;
      for (const w of wordsN) if (wordsT.some(wt => wt === w || wt.includes(w) || w.includes(wt))) common++;
      score = wordsN.length > 0 ? (common / wordsN.length) * 80 : 0;
      if (score < 35) score = 0;
    }
    if (score > 0) cands.push({r, nome: rawTitle, score});
  }
  cands.sort((a, b) => b.score - a.score);
  const best = cands.length ? cands[0].r : null;
  const bestScore = cands.length ? cands[0].score : 0;
  const lista = cands.slice(0, 4).map(c => ({nome: c.nome, score: Math.round(c.score)}));
  if (best && bestScore < 100 && cands.length > 1 && cands[1].score >= bestScore - 5 && cands[1].nome !== cands[0].nome)
    return {ok:false, motivo:'ambiguo', candidatos: lista};

  if(!best) return {ok:false, motivo:'conversa não encontrada na lista'};
  const title = best.querySelector('span[title]').getAttribute('title') || '';
  best.scrollIntoView({block: 'center'});              // fora da área visível o clique caía em outra conversa
  const b = best.getBoundingClientRect();
  return {
    ok: true,
    nome: title,
    score: Math.round(bestScore),
    x: b.x + b.width / 2,
    y: b.y + b.height / 2
  };
})"""


_JS_MSGS = r"""((n)=>{
  const rows = [...document.querySelectorAll('#main div[data-id]')].filter(e => !e.querySelector('div[data-id]'));
  const els = rows.length ? rows : [...document.querySelectorAll('[data-pre-plain-text]')];
  const out = [];
  for (const r of els.slice(-n)) {
    const pre = r.querySelector ? r.querySelector('[data-pre-plain-text]') : null;
    const meta = (pre ? pre.getAttribute('data-pre-plain-text') : (r.getAttribute ? r.getAttribute('data-pre-plain-text') : '')) || '';
    const m = meta.match(/^\[(.*?)\]\s*(.*?):\s*$/);
    let quando = m ? m[1] : '';
    let quem = m ? m[2] : '';

    const spanLabel = r.querySelector ? r.querySelector('span[aria-label]') : null;
    const aria = spanLabel ? (spanLabel.getAttribute('aria-label') || '').replace(':', '').trim() : '';
    if (!quem && aria && !aria.includes('Lida')) quem = aria;

    const rowEl = r.closest ? (r.closest('[class*="message-"]') || r) : r;
    const saida = !!(quem === 'Você' || (rowEl && /message-out/.test(rowEl.className)));

    const selectable = r.querySelectorAll ? [...r.querySelectorAll('span.selectable-text, span[dir]')].map(s => s.textContent).join(' ').trim() : '';
    const rawText = (r.innerText || r.textContent || '').trim();

    let tipo = 'texto';
    let doc = '';
    const docThumb = r.querySelector ? r.querySelector('div[data-testid="document-thumb"], [data-icon*="document"]') : null;
    if (docThumb) {
      tipo = 'documento';
      const t = docThumb.getAttribute('title') || '';
      const mTitle = t.match(/["“](.*?)["”]/);
      if (mTitle) doc = mTitle[1];
      else if (t) doc = t.replace(/^(?:Mostrar|Baixar)\s*/i, '').replace(/^["']|["']$/g, '').trim();
      if (!doc) {
        const mDoc = rawText.match(/([\w\-\.]+\.(?:pdf|docx?|xlsx?|pptx?|pfx|zip|png|jpe?g))/i);
        if (mDoc) doc = mDoc[1];
      }
    } else if (r.querySelector && r.querySelector('[data-icon="audio-play"],[data-icon="ptt-status"],[data-icon="audio-download"]')) {
      tipo = 'audio';
    }

    let txt = '';
    if (doc) {
      const extra = selectable ? selectable.replace(doc, '').trim() : '';
      txt = extra ? ('[Documento: ' + doc + '] ' + extra) : ('[Documento: ' + doc + ']');
    } else if (tipo === 'audio') {
      txt = selectable ? ('[Áudio] ' + selectable) : '[Mensagem de voz/áudio]';
    } else {
      txt = selectable || rawText;
    }

    if (!quando) {
      const mHora = rawText.match(/\b(\d{1,2}:\d{2})\b/);
      if (mHora) quando = mHora[1];
    }

    if (txt || doc || tipo !== 'texto') {
      out.push({quando, quem, saida, tipo, arquivo: doc, texto: txt.slice(0, 500)});
    }
  }
  const comp = !!document.querySelector('footer [contenteditable="true"], div[contenteditable="true"][data-tab]');
  return {ok: true, composer: comp, msgs: out};
})"""

_JS_FORWARD_FIND = r"""((filtro) => {
  const rows = [...document.querySelectorAll('#main div[data-id]')];
  const f = (filtro || '').toLowerCase().trim();
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    const text = row.innerText || '';
    const title = row.querySelector('[title]') ? row.querySelector('[title]').getAttribute('title') : '';
    const isDoc = !!row.querySelector('div[data-testid="document-thumb"], span[title*="."], [data-icon*="document"]');
    const match = !f ||
                  text.toLowerCase().includes(f) ||
                  title.toLowerCase().includes(f) ||
                  (f === 'pdf' && (isDoc || text.toLowerCase().includes('.pdf') || text.includes('PDF')));
    if (match) {
      row.scrollIntoView({block: 'center'});
      const btn = row.querySelector('div[aria-label="Encaminhar mídia"], [aria-label*="Encaminhar"]');
      let docName = '';
      const titleEl = row.querySelector('div[data-testid="document-thumb"], span[title*="."], [data-icon*="document"]');
      if (titleEl && titleEl.getAttribute('title')) {
        const t = titleEl.getAttribute('title') || '';
        const mTitle = t.match(/["“](.*?)["”]/);
        docName = mTitle ? mTitle[1] : t.replace(/^(?:Mostrar|Baixar)\s*/i, '').replace(/^["']|["']$/g, '').trim();
      } else {
        const m = text.match(/([\w\-\.]+\.(?:pdf|docx?|xlsx?|pptx?|pfx|zip|png|jpe?g))/i);
        if (m) docName = m[1];
      }
      return {
        ok: true,
        id: row.getAttribute('data-id'),
        docName: docName || (isDoc ? 'documento' : 'mensagem'),
        hasBtn: !!btn
      };
    }
  }
  return {ok: false, motivo: 'nenhum documento ou mensagem correspondente encontrado para encaminhar'};
})"""

_JS_FORWARD_CLICK = r"""((id) => {
  const row = document.querySelector('div[data-id*="' + id + '"]');
  if (!row) return false;
  let btn = row.querySelector('div[aria-label="Encaminhar mídia"], [aria-label*="Encaminhar"]');
  if (!btn) {
    row.scrollIntoView({block: 'center'});
    row.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
    btn = row.querySelector('[data-icon="down-context"], [aria-label="Abrir menu de contexto"]');
  }
  if (!btn) return false;
  btn.scrollIntoView({block: 'center'});
  btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
  btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
  btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  return true;
})"""

_JS_FORWARD_SEARCH_INPUT = r"""(() => {
  const m = document.querySelector('div[data-animate-modal-body="true"], [data-testid="forward-modal"], div[role="dialog"]');
  if (!m) return false;
  const inp = m.querySelector('input[type="text"], [contenteditable="true"]');
  if (!inp) return false;
  inp.focus();
  return true;
})()"""

_JS_FORWARD_SELECT_DEST = r"""((dest) => {
  const modal = document.querySelector('div[data-animate-modal-body="true"], [data-testid="forward-modal"], div[role="dialog"]');
  if (!modal) return {ok: false, motivo: 'modal de encaminhamento sumiu'};
  const items = [...modal.querySelectorAll('div[role="listitem"], div[data-testid*="list-item"]')];
  const norm = (s) => (s||'').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const d = norm(dest);
  const target = items.find(li => norm(li.innerText).includes(d));
  if (!target) return {ok: false, motivo: `destinatário "${dest}" não encontrado na busca de encaminhamento`};
  const clickable = target.querySelector('div[role="checkbox"], div[role="button"], [tabindex="0"]') || target;
  const b = clickable.getBoundingClientRect();
  return {ok: true, x: b.x + b.width / 2, y: b.y + b.height / 2};
})"""

_JS_FORWARD_SEND_BTN = r"""(() => {
  const sendBtn = document.querySelector('div[role="button"][aria-label="Enviar"], span[data-icon="send"], [data-testid="send"]');
  if (!sendBtn) return {ok: false, motivo: 'botão de enviar do encaminhamento não apareceu'};
  const btn = sendBtn.closest('div[role="button"]') || sendBtn;
  const b = btn.getBoundingClientRect();
  return {ok: true, x: b.x + b.width / 2, y: b.y + b.height / 2};
})()"""


_JS_FOCUS = r"""(()=>{
  const c=document.querySelector('footer [contenteditable="true"]')||document.querySelector('div[contenteditable="true"][data-tab="10"]')||
          [...document.querySelectorAll('div[contenteditable="true"]')].pop();
  if(!c) return false; c.focus(); return true;
})()"""


_JS_OWNER = r"""((n)=>{
  const els=[...document.querySelectorAll('#main div[data-id]')].filter(e=>!e.querySelector('div[data-id]'));
  const out=[];
  for(const e of els.slice(-n)){
    const audio=!!e.querySelector('[data-icon="audio-play"],[data-icon="ptt-status"],[data-icon="audio-download"]');
    const t=e.querySelector('[data-pre-plain-text]');
    const txt=t?[...t.querySelectorAll('span.selectable-text, span[dir]')].map(s=>s.textContent).join(' ').trim():'';
    out.push({id:e.getAttribute('data-id'), audio, texto:txt.slice(0,800)});
  }
  return {ok:true, msgs:out};
})"""

_JS_AUDIO = r"""(async (id)=>{
  const row=[...document.querySelectorAll('#main div[data-id]')].find(e=>e.getAttribute('data-id')===id);
  if(!row) return {ok:false, motivo:'mensagem não encontrada'};
  const ic=row.querySelector('[data-icon="audio-download"]'); if(ic){(ic.closest('button,[role=button]')||ic).click(); await new Promise(r=>setTimeout(r,2500));}
  const pl=row.querySelector('[data-icon="audio-play"]'); if(!pl) return {ok:false, motivo:'sem botão de play'};
  (pl.closest('button,[role=button]')||pl).click();
  let a=null; for(let i=0;i<30&&!(a&&a.src);i++){await new Promise(r=>setTimeout(r,200)); a=document.querySelector('audio');}
  if(!a||!a.src) return {ok:false, motivo:'áudio não carregou'};
  try{ a.muted=true; }catch(e){}
  const b=await (await fetch(a.src)).blob();
  try{ a.pause(); }catch(e){}
  const data=await new Promise(res=>{const f=new FileReader(); f.onload=()=>res(f.result.split(',')[1]); f.readAsDataURL(b);});
  return {ok:true, mime:b.type, b64:data};
})"""


class CDP:
    def __init__(self):
        self.ws = None
        self._id = 0

    async def __aenter__(self):
        import websockets
        tg = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=4))
        page = next((t for t in tg if t.get("type") == "page" and "whatsapp" in t.get("url", "")), None)
        if not page:
            raise RuntimeError("página do WhatsApp não encontrada no ZapZap")
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=2 ** 24, origin=None)
        return self

    async def __aexit__(self, *a):
        if self.ws:
            await self.ws.close()

    async def call(self, method, **params):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            m = json.loads(await asyncio.wait_for(self.ws.recv(), 15))
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(m["error"].get("message", "erro CDP"))
                return m.get("result", {})

    async def ev(self, js, arg=None):
        expr = f"({js})({json.dumps(arg)})" if arg is not None and js.lstrip().startswith("((") else js
        r = await self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


def available():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2).read()
        return True
    except Exception:
        return False


def launch():
    """sobe o ZapZap com o depurador LOCAL (127.0.0.1) — sem --remote-allow-origins para páginas web não conseguirem se conectar."""
    if available():
        return True, "já em execução com depurador"
    if not shutil.which("flatpak"):
        return False, "flatpak ausente"
    subprocess.Popen(["flatpak", "run", f"--env=QTWEBENGINE_REMOTE_DEBUGGING_PORT={PORT}",
                      f"--env=QTWEBENGINE_CHROMIUM_FLAGS=--remote-debugging-port={PORT}", APP],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        time.sleep(1)
        if available():
            return True, "ZapZap iniciado"
    return False, "ZapZap não expôs o depurador a tempo"


def _run(coro):
    return asyncio.run(coro)


async def _snapshot():
    async with CDP() as c:
        return await c.ev(_JS_SNAPSHOT)


def snapshot():
    """-> {"ok":bool, "chats":[{nome, previa, hora, nao_lidas, silenciada, fixada}], ...}"""
    try:
        return _run(_snapshot())
    except Exception as e:
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"[:160]}


def ensure_running():
    if available():
        return True
    # Se o ZapZap estiver rodando sem porta de depuração, encerra para reiniciar com depurador
    try:
        subprocess.run(["pkill", "-f", "zapzap"], capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "QtWebEngineProcess.*zapzap"], capture_output=True, timeout=5)
    except Exception:
        pass
    time.sleep(1)
    ok, _ = launch()
    return ok


_JS_HEADER = r"""((alvo)=>{
  const norm = (s) => (s||'').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  const h = document.querySelector('#main header');
  if (!h) return {ready: false, certo: false};
  const comp = document.querySelector('footer [contenteditable="true"]');
  const tit = h.querySelector('span[title]') ? h.querySelector('span[title]').getAttribute('title') : '';
  const txt = norm(tit || h.innerText || '');
  const a = norm(alvo);
  const certo = !!a && (txt === a || txt.startsWith(a) || norm(h.innerText).split('\n')[0].trim() === a || norm(h.innerText).startsWith(a));
  return {ready: !!comp, certo, header: (h.innerText || '').slice(0, 100)};
})"""

_JS_CLICA_TITULO = r"""((t)=>{
  const s = [...document.querySelectorAll('#pane-side span[title]')].find(e => e.getAttribute('title') === t);
  if (!s) return false;
  const row = s.closest('[role="row"]') || s; row.scrollIntoView({block: 'center'});
  const el = row.querySelector('[tabindex]') || row;
  for (const ev of ['mousedown', 'mouseup', 'click']) el.dispatchEvent(new MouseEvent(ev, {bubbles: true}));
  return true;
})"""


async def _open_chat(c, nome):
    """Localiza a conversa e clica via eventos nativos do CDP para garantir a troca real de chat no React."""
    res = await c.call("Runtime.evaluate", expression=f"({_JS_OPEN})({json.dumps(nome)})", returnByValue=True)
    r = res.get("result", {}).get("value")
    if r and r.get("motivo") == "ambiguo":
        return r                                       # nomes parecidos: quem chamou pergunta ao dono qual (não abre a errada)
    if not r or not r.get("ok"):
        # Se não encontrou nas conversas visíveis, busca no campo de pesquisa do WhatsApp
        try:
            sf = await c.call("Runtime.evaluate", expression="""(()=>{
                const s = document.querySelector('#side [contenteditable="true"], [data-testid="chat-list-search"], div[data-tab="3"]');
                if (!s) return false;
                s.focus();
                return true;
            })()""", returnByValue=True)
            if sf.get("result", {}).get("value"):
                await c.call("Input.insertText", text=nome)
                await asyncio.sleep(0.6)
                res2 = await c.call("Runtime.evaluate", expression=f"({_JS_OPEN})({json.dumps(nome)})", returnByValue=True)
                r2 = res2.get("result", {}).get("value")
                if r2 and r2.get("ok"):
                    r = r2
        except Exception:
            pass

    if not r or not r.get("ok"):
        return r or {"ok": False, "motivo": "conversa não encontrada na lista"}
    # 16/10: só esperava a caixa de texto ficar pronta — se o clique errava, a conversa que JÁ estava aberta (a do próprio
    # dono, dos testes) recebia a mensagem e o log dizia "enviado a <contato>". Agora o CABEÇALHO tem que ser o contato.
    alvo = r.get("nome") or ""
    for tentativa in range(3):
        if tentativa == 0 and r.get("x") is not None:
            x, y = r.get("x"), r.get("y")
            await c.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
            await c.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
        else:                                          # reserva: clique pelo próprio elemento da linha (sem coordenada)
            await c.call("Runtime.evaluate", expression=f"({_JS_CLICA_TITULO})({json.dumps(alvo)})", returnByValue=True)
        for _ in range(25):
            await asyncio.sleep(0.1)
            check = await c.call("Runtime.evaluate", expression=f"({_JS_HEADER})({json.dumps(alvo)})", returnByValue=True)
            ch = check.get("result", {}).get("value") or {}
            if ch.get("certo") and ch.get("ready"):
                return {"ok": True, "nome": alvo, "header": ch.get("header")}
    return {"ok": False, "motivo": f"não consegui abrir a conversa de {alvo} (aberta: {str(ch.get('header') or '?')[:40]}); não enviei nada"}


async def _read(nome, n):
    async with CDP() as c:
        r = await _open_chat(c, nome)
        if not r.get("ok"):
            return r
        await asyncio.sleep(0.5)
        res = await c.call("Runtime.evaluate", expression=f"({_JS_MSGS})({int(n)})", returnByValue=True)
        out = res.get("result", {}).get("value") or {"ok": False}
        out["conversa"] = r.get("nome")
        return out


def read_chat(nome, n=15):
    try:
        return _run(_read(nome, n))
    except Exception as e:
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"[:160]}


async def _send(nome, texto):
    async with CDP() as c:
        r = await _open_chat(c, nome)
        if not r.get("ok"):
            return r
        await asyncio.sleep(0.5)
        res = await c.call("Runtime.evaluate", expression=_JS_FOCUS, returnByValue=True)
        if not res.get("result", {}).get("value"):
            return {"ok": False, "motivo": "caixa de mensagem não encontrada"}
        async def _tecla(key, code, vk, mods=0):
            for typ in ("keyDown", "keyUp"):
                await c.call("Input.dispatchKeyEvent", type=typ, key=key, code=code, modifiers=mods, windowsVirtualKeyCode=vk)
        _JS_LEN = "(()=>{const c=document.querySelector('footer [contenteditable=\"true\"]');return c?c.innerText.trim().length:-1})()"
        _JS_SEL = ("(()=>{const c=document.querySelector('footer [contenteditable=\"true\"]');if(!c)return false;c.focus();"
                   "const r=document.createRange();r.selectNodeContents(c);const s=getSelection();s.removeAllRanges();s.addRange(r);return true})()")
        async def _limpar():                            # Ctrl+A no WhatsApp não pega texto de muitas linhas: seleciona o campo todo
            for _ in range(6):
                if (await c.call("Runtime.evaluate", expression=_JS_LEN, returnByValue=True)).get("result", {}).get("value") == 0:
                    return True
                await c.call("Runtime.evaluate", expression=_JS_SEL, returnByValue=True)
                await _tecla("Backspace", "Backspace", 8)
                await asyncio.sleep(0.5)
            return False
        if not await _limpar():                         # rascunho velho ia junto ("todos os itens...Oi, equipe")
            return {"ok": False, "motivo": "não consegui limpar o rascunho do campo; não enviei"}
        # cola o bloco (como Ctrl+V): "\n" digitado vira Enter e ENVIA só o pedaço; Shift+Enter faz o WhatsApp
        # continuar a lista e duplicar "•". Colar mantém as linhas e não reformata.
        _JS_COLAR = ("((t)=>{const c=document.querySelector('footer [contenteditable=\"true\"]');if(!c)return false;c.focus();"
                     "const dt=new DataTransfer();dt.setData('text/plain',t);"
                     "c.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));return true})")
        _JS_TXT = "(()=>{const c=document.querySelector('footer [contenteditable=\"true\"]');return c?c.innerText:''})()"
        _norm = lambda t: re.sub(r"\s+", "", t).replace("•", "-")     # o campo exibe "- " de lista como "•"
        no_campo = ""
        for _tent in range(3):                          # logo após enviar a parte anterior o campo ainda está ocupado: espera e cola de novo
            await c.call("Runtime.evaluate", expression=f"{_JS_COLAR}({json.dumps(texto)})", returnByValue=True)
            for _ in range(10):
                await asyncio.sleep(0.5)
                no_campo = (await c.call("Runtime.evaluate", expression=_JS_TXT, returnByValue=True)).get("result", {}).get("value") or ""
                if _norm(no_campo) == _norm(texto):
                    break
            if _norm(no_campo) == _norm(texto) or not await _limpar():
                break
            await asyncio.sleep(1.5)
        if _norm(no_campo) != _norm(texto):             # 3ª trava: o campo não tem EXATAMENTE a mensagem aprovada -> não envia
            await _limpar()
            return {"ok": False, "motivo": f"o texto no campo não bateu com a mensagem aprovada ({len(no_campo)} de {len(texto)} caracteres); apaguei e não enviei"}
        chk = await c.call("Runtime.evaluate", expression=f"({_JS_HEADER})({json.dumps(r.get('nome') or '')})", returnByValue=True)
        if not (chk.get("result", {}).get("value") or {}).get("certo"):     # 2ª trava: a conversa mudou no meio -> apaga e NÃO envia
            for typ in ("keyDown", "keyUp"):
                await c.call("Input.dispatchKeyEvent", type=typ, key="a", code="KeyA", modifiers=2, windowsVirtualKeyCode=65)
            for typ in ("keyDown", "keyUp"):
                await c.call("Input.dispatchKeyEvent", type=typ, key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
            return {"ok": False, "motivo": f"a conversa aberta não é {r.get('nome')}; apaguei o rascunho e não enviei"}
        # Clica no botão Enviar nativo do WhatsApp (suporta mensagens com múltiplas linhas sem falhar)
        res_btn = await c.call("Runtime.evaluate", expression="""(()=>{
            const footer = document.querySelector('footer');
            if (!footer) return false;
            const btn = footer.querySelector('button[aria-label="Enviar"], [data-testid="send"], span[data-icon="send"], [data-icon="send"]');
            if (btn) {
                const el = btn.closest('button') || btn;
                el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                el.click();
                return true;
            }
            return false;
        })()""", returnByValue=True)
        clicked = bool(res_btn.get("result", {}).get("value"))
        if not clicked:
            for typ in ("keyDown", "keyUp"):
                await c.call("Input.dispatchKeyEvent", type=typ, key="Enter", code="Enter", windowsVirtualKeyCode=13,
                             nativeVirtualKeyCode=13, text="\r" if typ == "keyDown" else "")
        await asyncio.sleep(0.5)
        return {"ok": True, "conversa": r.get("nome")}


def send(nome, texto):
    try:
        for _ in range(3):                              # ocupado/lento != fechado: reiniciar no meio reenviava a fila (loop)
            if available():
                break
            time.sleep(2)
        else:
            if subprocess.run(["pgrep", "-f", "/app/bin/zapzap"], capture_output=True).returncode != 0:
                ensure_running()
        if not available():
            return {"ok": False, "motivo": "ZapZap não respondeu ao depurador; não enviei"}
        partes, atual = [], ""                          # colar aceita ~30 mil caracteres numa mensagem só; divide só acima de 60 mil
        for linha in (texto or "").split("\n"):
            if atual and len(atual) + len(linha) + 1 > 60000:
                partes.append(atual.rstrip("\n"))
                atual = ""
            atual += linha + "\n"
        if atual.strip():
            partes.append(atual.rstrip("\n"))
        r = {"ok": False, "motivo": "mensagem vazia"}
        for i, parte in enumerate(partes or [texto]):
            r = _run(_send(nome, parte))
            if not r.get("ok"):
                if i:
                    r["motivo"] = f"enviei {i} de {len(partes)} partes; a parte {i + 1} falhou: " + str(r.get("motivo", ""))
                return r
            time.sleep(2.5)                             # deixa o WhatsApp terminar de enviar a parte antes da próxima
        if len(partes) > 1:
            r["partes"] = len(partes)
        return r
    except Exception as e:
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"[:160]}


def _zap_em_foco():
    """janela do ZapZap em foco no niri (document.hasFocus() do WebEngine dá sempre true)."""
    try:
        import subprocess
        w = json.loads(subprocess.run(["niri", "msg", "-j", "focused-window"], capture_output=True, text=True, timeout=2).stdout or "null")
        return bool(w) and "zap" in (w.get("app_id") or "").lower()
    except Exception:
        return False


async def _owner(nome, n, audio_id=None, numero=""):
    async with CDP() as c:
        if audio_id is None:
            # dono usando o WhatsApp (janela em foco ou clique/tecla < 90 s): NÃO troca de conversa — antes, a cada 10 s,
            # ela abria a conversa de comandos e arrancava ele da conversa em que estava (15/10)
            uso = await c.ev("""(()=>{ if(!window.__fridayUso){ window.__fridayUso=1; window.__fridayUlt=Date.now();
                const f=()=>{window.__fridayUlt=Date.now()}; ['pointerdown','keydown','wheel'].forEach(e=>addEventListener(e,f,true)); }
                return Date.now()-window.__fridayUlt < 90000; })()""")
            if uso or _zap_em_foco():
                return {"ok": False, "motivo": "dono usando o WhatsApp"}
            r = await _open_chat(c, nome)
            if not r.get("ok"):
                if not numero:
                    return r
                # a conversa consigo mesmo não aparece na lista: abre pelo número (deep link do WhatsApp Web)
                await c.call("Page.navigate", url=f"https://web.whatsapp.com/send?phone={numero}")
                for _ in range(40):
                    await asyncio.sleep(1)
                    try:
                        ok = await c.call("Runtime.evaluate", returnByValue=True,
                                          expression="!!document.querySelector('#main footer [contenteditable=\"true\"], #main [data-pre-plain-text]')")
                    except Exception:
                        continue
                    if ok.get("result", {}).get("value"):
                        break
                else:
                    return {"ok": False, "motivo": "não abriu a conversa pelo número"}
            await asyncio.sleep(0.5)
            res = await c.call("Runtime.evaluate", expression=f"({_JS_OWNER})({int(n)})", returnByValue=True)
        else:
            res = await c.call("Runtime.evaluate", expression=f"({_JS_AUDIO})({json.dumps(audio_id)})",
                               returnByValue=True, awaitPromise=True)
        return res.get("result", {}).get("value") or {"ok": False, "motivo": "sem retorno"}


def owner_msgs(nome, n=12, numero=""):
    """últimas mensagens da conversa do dono (id estável, se é áudio, texto). Abre a conversa."""
    try:
        return _run(_owner(nome, n, None, numero))
    except Exception as e:
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"[:160]}


def fetch_audio(msg_id, dest):
    """baixa o áudio (mensagem de voz) da conversa aberta para `dest`; devolve {"ok":bool,...}."""
    import base64
    try:
        r = _run(_owner("", 0, msg_id))
        if r.get("ok"):
            open(dest, "wb").write(base64.b64decode(r["b64"]))
            return {"ok": True, "arquivo": dest}
        return r
    except Exception as e:
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"[:160]}


async def _forward(de, para, filtro="", apenas_testar=False):
    async with CDP() as c:
        # 1. Abre conversa de origem
        r = await _open_chat(c, de)
        if not r.get("ok"):
            return {"ok": False, "motivo": f"não foi possível abrir conversa de origem ({de}): {r.get('motivo')}"}
        await asyncio.sleep(0.5)

        # 2. Localiza a mensagem/documento
        msg_info = await c.ev(_JS_FORWARD_FIND, filtro)
        if not msg_info or not msg_info.get("ok"):
            return msg_info or {"ok": False, "motivo": f"documento/mensagem não encontrado para filtro: {filtro}"}

        # 3. Clica no botão de encaminhar
        clicou = await c.ev(_JS_FORWARD_CLICK, msg_info["id"])
        if not clicou:
            return {"ok": False, "motivo": "não foi possível acionar o botão de encaminhar na mensagem"}

        await asyncio.sleep(1.0)

        # 4. Foca no campo de busca do modal
        modal_ok = await c.ev(_JS_FORWARD_SEARCH_INPUT)
        if not modal_ok:
            return {"ok": False, "motivo": "modal de encaminhamento não apareceu"}

        await c.call("Input.insertText", text=para)
        await asyncio.sleep(0.8)

        # 5. Seleciona o destinatário
        sel = await c.ev(_JS_FORWARD_SELECT_DEST, para)
        if not sel or not sel.get("ok"):
            for typ in ("rawKeyDown", "keyUp"):
                await c.call("Input.dispatchKeyEvent", type=typ, windowsVirtualKeyCode=27, key="Escape", code="Escape")
            return sel or {"ok": False, "motivo": f"contato {para} não encontrado na lista de encaminhamento"}

        await c.call("Input.dispatchMouseEvent", type="mousePressed", x=sel["x"], y=sel["y"], button="left", clickCount=1)
        await c.call("Input.dispatchMouseEvent", type="mouseReleased", x=sel["x"], y=sel["y"], button="left", clickCount=1)
        await asyncio.sleep(0.8)

        # 6. Verifica botão de enviar
        btn = await c.ev(_JS_FORWARD_SEND_BTN)
        if not btn or not btn.get("ok"):
            for typ in ("rawKeyDown", "keyUp"):
                await c.call("Input.dispatchKeyEvent", type=typ, windowsVirtualKeyCode=27, key="Escape", code="Escape")
            return btn or {"ok": False, "motivo": "botão enviar não ficou disponível no modal de encaminhamento"}

        if apenas_testar:
            for typ in ("rawKeyDown", "keyUp"):
                await c.call("Input.dispatchKeyEvent", type=typ, windowsVirtualKeyCode=27, key="Escape", code="Escape")
            await asyncio.sleep(0.4)
            for typ in ("rawKeyDown", "keyUp"):
                await c.call("Input.dispatchKeyEvent", type=typ, windowsVirtualKeyCode=27, key="Escape", code="Escape")
            return {"ok": True, "teste": True, "de": r.get("nome", de), "para": para, "doc": msg_info.get("docName", "")}

        # 7. Dispara envio
        await c.call("Input.dispatchMouseEvent", type="mousePressed", x=btn["x"], y=btn["y"], button="left", clickCount=1)
        await c.call("Input.dispatchMouseEvent", type="mouseReleased", x=btn["x"], y=btn["y"], button="left", clickCount=1)

        for _ in range(15):
            await asyncio.sleep(0.3)
            fechou = await c.ev("!document.querySelector('div[data-animate-modal-body=\"true\"], [data-testid=\"forward-modal\"], div[role=\"dialog\"]')")
            if fechou:
                break

        return {"ok": True, "de": r.get("nome", de), "para": para, "doc": msg_info.get("docName", "")}


def forward(de, para, filtro="", apenas_testar=False):
    """Encaminha documento, mídia ou mensagem de um contato para outro no WhatsApp Web."""
    try:
        for _ in range(3):
            if available():
                break
            time.sleep(2)
        else:
            if subprocess.run(["pgrep", "-f", "/app/bin/zapzap"], capture_output=True).returncode != 0:
                ensure_running()
        if not available():
            return {"ok": False, "motivo": "ZapZap não respondeu ao depurador"}
        return _run(_forward(de, para, filtro, apenas_testar=apenas_testar))
    except Exception as e:
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"[:160]}


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if a[:1] == ["launch"]:
        print(launch())
    elif a[:1] == ["chats"]:
        r = snapshot()
        print(json.dumps(r, ensure_ascii=False, indent=1)[:4000])
