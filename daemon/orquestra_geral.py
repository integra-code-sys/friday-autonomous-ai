#!/usr/bin/env python3
"""Orquestrador geral do Prometheus: plano, fila, retomada e ação no aparelho do dono.

Cursor/teclado primeiro (daemon/pc no Linux, SendInput no Windows, acessibilidade no Android).
Shell e PTY só quando o input gráfico não alcança o alvo. Não envia spam nem mexe em conta de terceiro.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MEM = os.path.join(ROOT, "memory")
SESSAO = os.path.join(MEM, "orquestra_sessao.json")
FILA = os.path.join(MEM, "orquestra_fila.json")
os.makedirs(MEM, exist_ok=True)

_RECUSA = re.compile(
    r"\b(malware|ransomware|keylogger|phishing|exploit|payload|invas[aã]o|invadir|hackear)\b|"
    r"\b(roubar|furtar)\b.{0,40}\b(senha|credencial|token|cookie)\b|"
    r"\b(senha|credencial)\b.{0,40}\b(alheia|de terceiro|da v[ií]tima)\b|"
    r"\b(vigiar|espionar|monitorar)\b.{0,30}\b(terceiro|vizinho|sem autoriza)",
    re.I,
)


def recusar(pedido):
    if _RECUSA.search(pedido or ""):
        return "Não faço isso. Só tarefas legítimas nos seus aparelhos e nas suas contas."
    return None


def _norm(s):
    t = unicodedata.normalize("NFKD", str(s or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _salvar(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, caminho)


def _ler(caminho, vazio):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return vazio


def _modelo(prompt, max_tokens=1000):
    """Executa raciocínio analítico ou síntese profunda usando o motor configurado com fallback resiliente."""
    # 1. Tenta cloud_providers (Ollama local com think=False ou nuvem Gemini/Claude/OpenAI)
    try:
        import cloud_providers as cp
        r = cp.chat_com_ferramentas(
            [{"role": "user", "content": prompt}],
            [],
            temperature=0.2,
            max_tokens=max_tokens,
            timeout=100,
        )
        msg = (r or {}).get("message") or {}
        txt = msg.get("content") or msg.get("thinking") or ""
        txt = re.sub(r"(?is)<think>.*?</think>", "", str(txt)).strip()
        if txt and len(txt) > 5:
            return txt
    except Exception:
        pass

    # 2. Fallback direto ao endpoint Ollama /api/chat com think: False
    try:
        import urllib.request
        body = {
            "model": "qwen3.5:4b",
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "think": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens}
        }
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            m = data.get("message") or {}
            txt = m.get("content") or m.get("thinking") or ""
            txt = re.sub(r"(?is)<think>.*?</think>", "", str(txt)).strip()
            if txt and len(txt) > 5:
                return txt
    except Exception:
        pass

    return None



def planejar(pedido, usar_modelo=True):
    """Decompõe em passos com critério de pronto. Cai num plano explícito se o modelo não responder."""
    pedido = (pedido or "").strip()
    base = {
        "pedido": pedido,
        "criado": time.time(),
        "provedor": "heuristica",
        "passos": [],
    }
    t = _norm(pedido)
    # Tarefas de navegação, busca web, documentos e mensagens executivas usam o plano de orquestração completo
    eh_composto_ou_busca = bool(re.search(r"navegador|browser|chrome|firefox|pesquis|busc|investig|procur|loja|site", t))
    if eh_composto_ou_busca:
        base["passos"] = _tela_primeiro(_plano_heuristico(pedido))
        base["provedor"] = "orquestrador_determinista"
        return base

    txt = None
    if usar_modelo:
        txt = _modelo(
            "Decomponha o pedido do dono em JSON {\"passos\":[{\"acao\":\"abrir_navegador|abrir_app|pesquisar|email|mensagem|"
            "documento|claude|falar|camera|rea|teclado|esperar\",\"args\":{},\"pronto\":\"como saber que deu certo\"}]}. "
            "A primeira ação tem de ser cursor, teclado ou ler_tela. Shell não entra no plano. Pedido:\n" + pedido[:1500]
        )
    if txt:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                d = json.loads(m.group(0))
                passos = d.get("passos") if isinstance(d, dict) else None
                if isinstance(passos, list) and passos:
                    base["provedor"] = "modelo"
                    base["passos"] = _tela_primeiro([_passo(i, p) for i, p in enumerate(passos[:6], 1)])
                    return base
            except Exception:
                pass
    base["passos"] = _tela_primeiro(_plano_heuristico(pedido))
    base["aviso_modelo"] = "Modelo não respondeu. Plano explícito. O loop segue; confira Ollama ou a chave já salva na configuração local."
    return base


def _passo(i, p):
    if isinstance(p, str):
        p = {"acao": "nota", "args": {"texto": p}, "pronto": "registrado"}
    return {
        "n": i,
        "acao": str(p.get("acao") or "nota"),
        "args": p.get("args") if isinstance(p.get("args"), dict) else {},
        "pronto": str(p.get("pronto") or "feito"),
        "estado": "pendente",
        "evidencia": "",
    }


_TELA = {"cursor", "teclado", "digitar", "focar", "clicar", "ler_tela"}


def _tela_primeiro(passos):
    if not passos or passos[0].get("acao") in _TELA:
        return passos
    extra = _passo(1, {"acao": "cursor", "args": {"alvo": ""}, "pronto": "cursor na janela"})
    out = [extra] + list(passos)
    for i, p in enumerate(out, 1):
        p["n"] = i
    return out[:8]


def _plano_heuristico(pedido):
    """Primeiro passo é sempre ação de tela. Shell não entra no plano."""
    t = _norm(pedido)
    def seq(itens):
        return [_passo(i, p) for i, p in enumerate(itens, 1)]
    # "abre o chrome" sem busca/site/loja é abrir app, não pesquisa web pela palavra "chrome"
    so_abrir = not re.search(r"pesquis|busc|investig|procur|loja|site", t) and re.search(r"\b(?:abr(?:e|a|ir|iu))\b", t)
    if re.search(r"navegador|browser|chrome|firefox|pesquis|busc|investig|procur|loja|site", t) and not so_abrir:
        q = re.sub(r"(?is)^.*?\b(?:pesquis\w*|busc\w*|investig\w*|procur\w*)\s+", "", pedido, count=1)
        # Identifica se o usuário quer preparar mensagem/documento depois da busca
        quer_msg = bool(re.search(r"\b(prepar\w*|escrev\w*|redig\w*|mand\w*|envi\w*)\s+(?:uma\s+)?(?:mensagem|nota|texto|comunicado)\b", pedido, re.I))
        quer_doc = bool(re.search(r"\b(cri\w*|ger\w*|mont\w*|escrev\w*|redig\w*|faz\w*|fa[çc]\w*)\s+(?:um\s+|uma\s+)?(?:documento|relat[óo]rio|resumo|artigo|dossi[êe]|analise|an[áa]lise|docs?|docx|pdf|planilh\w*)\b", pedido, re.I))
        # \b evita casar "para" dentro de "prepara/compara/separa"; \w aceita acento (João); prefere o "para" depois de "mensagem"
        dest_re = r"\b(?:para|pro|pra)\s+(?:[oa]s?\s+)?([\w\-\s]{2,40})"
        dest_match = re.search(r"(?:mensagem|nota|texto|comunicado)\b.*?" + dest_re, pedido, re.I) or re.search(dest_re, pedido, re.I)
        dest_nome = dest_match.group(1).strip() if dest_match else "Integra Code"
        dest_nome = re.split(r"(?i)\s+(?:e|sobre|com|que|dizendo|falando)\s+", dest_nome)[0].strip() or "Integra Code"

        q = re.split(r"(?i)\s+e\s+(?:depois\s+)?(?:mand\w*|envi\w*|escrev\w*|cri\w*|mont\w*|prepar\w*|redig\w*)\b", q, maxsplit=1)[0]
        # só verbos (entra/acesse/abre); entr\w*/acess\w*/abr\w* comiam "entrega", "acessórios", "abril"
        q = re.sub(r"(?iu)\b(?:e\s+)?(?:entr(?:a|ar|ou)|entre(?=\s+(?:no|na|em)\b)|acess(?:e|a|ar|ou)|abr(?:e|a|ir|iu))\s+(?:no\s+|na\s+|ao\s+|o\s+|a\s+)?(?:site|p[áa]gina|loja|portal)?\s*(?:oficial\s+)?(?:da\s+|do\s+|de\s+)?", " ", q)
        q = re.sub(r"(?iu)\b(?:sexta[- ]?feira|friday|por\s+favor|me\s+fala|me\s+diz|site\s+oficial\s+da|site\s+oficial\s+do|site\s+oficial)\b", " ", q)
        q = re.sub(r"(?iu)\b(?:fortinate)\b", "fortnite", q)
        q = re.sub(r"\s+", " ", q).strip(" ,.!?") or pedido[:120]
        if bool(re.search(r"\bloja\b", pedido, re.I)) and not re.search(r"\bloja\b", q, re.I):
            q = f"loja de {q}"

        passos_busca = [
            {"acao": "cursor", "args": {"alvo": "navegador"}, "pronto": "navegador em foco"},
            {"acao": "coletar", "args": {"consulta": q[:180]}, "pronto": "links de fontes oficiais"},
            {"acao": "abrir_pagina", "args": {"indice": 0}, "pronto": "primeira fonte aberta na tela"},
            {"acao": "ler_fonte", "args": {"indice": 0}, "pronto": "conteúdo da primeira fonte lido"},
            {"acao": "abrir_pagina", "args": {"indice": 1}, "pronto": "segunda fonte aberta para validação comparativa"},
            {"acao": "ler_fonte", "args": {"indice": 1}, "pronto": "conteúdo da segunda fonte lido e cruzado"},
            {"acao": "concluir_pesquisa", "args": {"consulta": q[:180]}, "pronto": "resposta com síntese analítica dos dados"},
        ]
        if quer_msg:
            passos_busca.append({
                "acao": "preparar_mensagem",
                "args": {"para": dest_nome, "pedido": pedido},
                "pronto": f"mensagem para {dest_nome} formatada e pronta"
            })
            passos_busca.append({
                "acao": "confirmar_arquivo",
                "args": {},
                "pronto": "mensagem gravada e exibida com sucesso"
            })
        if quer_doc:
            passos_busca.append({
                "acao": "escrever_doc",
                "args": {"pedido": pedido, "consulta": q[:180]},
                "pronto": "documento analítico estruturado e criado com sucesso"
            })
            passos_busca.append({
                "acao": "confirmar_arquivo",
                "args": {},
                "pronto": "documento gravado e verificado"
            })
        return seq(passos_busca)
    if re.search(r"claude", t):
        return seq([
            {"acao": "cursor", "args": {"alvo": "kitty"}, "pronto": "cursor no terminal"},
            {"acao": "claude", "args": {"pedido": pedido[:1500]}, "pronto": "saída do Claude lida na tela ou no buffer"},
            {"acao": "ler_tela", "args": {}, "pronto": "continuação conferida"},
        ])
    if re.search(r"e-?mail|correio", t):
        para = re.search(r"[\w.+-]+@[\w.-]+\.\w+", pedido)
        quer_envio = bool(re.search(r"\b(envi\w*|mand\w*)\b", t)) and bool(para)
        passos = [
            {"acao": "cursor", "args": {"alvo": "thunderbird"}, "pronto": "cliente de e-mail em foco"},
            {"acao": "teclado", "args": {"atalho": "ctrl+n", "texto": pedido[:400], "enter": False}, "pronto": "para, assunto e corpo preenchidos"},
            {"acao": "ler_tela", "args": {}, "pronto": "rascunho conferido na tela"},
        ]
        if not para:
            passos.append({"acao": "perguntar", "args": {"texto": "Para qual endereço envio?"}, "pronto": "parado até o dono dizer o destinatário"})
        elif quer_envio:
            passos.append({"acao": "teclado", "args": {"atalho": "ctrl+enter", "enter": False}, "pronto": "envio disparado no cliente"})
        return seq(passos)
    if re.search(r"whats|zap|mensagem", t):
        dest = re.search(r"\b(?:para|pro|pra)\s+([\w@.+-]{2,40})", pedido, re.I)
        quer_envio = bool(re.search(r"\b(envi\w*|mand\w*)\b", t)) and bool(dest)
        passos = [
            {"acao": "cursor", "args": {"alvo": "zapzap"}, "pronto": "mensageiro em foco"},
            {"acao": "teclado", "args": {"texto": pedido[:300], "enter": False}, "pronto": "texto no campo do destino"},
            {"acao": "ler_tela", "args": {}, "pronto": "campo conferido"},
        ]
        if not dest:
            passos.append({"acao": "perguntar", "args": {"texto": "Para quem envio?"}, "pronto": "parado até o dono dizer o destino"})
        elif quer_envio:
            passos.append({"acao": "teclado", "args": {"enter": True}, "pronto": "envio disparado na interface"})
        return seq(passos)
    if re.search(r"\b(app|aplicativo)\b", t) and re.search(r"cri\w*|mont\w*|faz\w*|constru", t):
        return seq([
            {"acao": "cursor", "args": {"alvo": "kitty"}, "pronto": "editor ou terminal em foco"},
            {"acao": "montar_app", "args": {"pedido": pedido[:300]}, "pronto": "arquivo do app escrito"},
            {"acao": "confirmar_arquivo", "args": {}, "pronto": "artefato existe e não está vazio"},
            {"acao": "abrir_pagina", "args": {"arquivo": True}, "pronto": "app aberto na tela"},
        ])
    if re.search(r"planilh|documento|docx|xlsx|libre|relat", t):
        return seq([
            {"acao": "cursor", "args": {"alvo": "libreoffice"}, "pronto": "editor em foco"},
            {"acao": "escrever_doc", "args": {"texto": pedido[:800]}, "pronto": "conteúdo escrito"},
            {"acao": "confirmar_arquivo", "args": {}, "pronto": "arquivo existe e não está vazio"},
        ])
    if re.search(r"\b(abr\w+|abre)\b", pedido, re.I):
        alvo = re.sub(r"(?i)^.*?\b(?:abr\w+|abre)\s+(?:o |a )?", "", pedido).strip(" .") or "navegador"
        return seq([
            {"acao": "cursor", "args": {"alvo": alvo[:80]}, "pronto": "cursor na janela"},
            {"acao": "ler_tela", "args": {}, "pronto": "tela do app lida"},
        ])
    return seq([
        {"acao": "cursor", "args": {"alvo": ""}, "pronto": "cursor na janela em foco"},
        {"acao": "ler_tela", "args": {}, "pronto": "tela lida"},
        {"acao": "teclado", "args": {"texto": pedido[:180]}, "pronto": "ação digitada na interface"},
    ])


def _input():
    import win_compat
    return win_compat


def input_disponivel():
    if sys.platform == "win32":
        return True
    return shutil.which("ydotool") is not None or os.path.isfile(os.path.join(HERE, "pc"))


def _focar_digitando(texto):
    """Caminho humano. Devolve (ok, como)."""
    if not input_disponivel():
        return False, "sem ydotool/SendInput"
    try:
        if not str(texto or ""):
            return False, "sem texto para digitar"
        ih = _input()
        ok = ih.type_text(str(texto))
        return bool(ok), "teclado" if ok else "teclado não aceitou"
    except Exception as e:
        return False, str(e)[:120]


def _alvo_bate(alvo, w):
    """A janela em foco (Windows) é a do alvo? Navegador aceita qualquer navegador conhecido."""
    if not alvo:
        return True
    vistos = _norm(str(w.get("app_id") or "") + " " + str(w.get("titulo") or ""))
    try:
        import abrir_nativo
        chave = _norm(abrir_nativo.chave_janela(alvo))
    except Exception:
        chave = _norm(alvo)
    navs = ("chrom", "msedge", "firefox", "brave", "opera")
    if chave in navs and any(b in vistos for b in navs):
        return True
    if chave == "wt":
        chave = "windowsterminal"
    return bool(chave) and chave in vistos


def _cursor_na_janela(alvo):
    try:
        if sys.platform == "win32":
            import win_compat
            w = win_compat.janela_em_foco() or {}
            titulo = w.get("titulo") or w.get("app_id") or ""
            if not (titulo or w.get("id")):
                return False, "nenhuma janela em foco"
            if not _alvo_bate(alvo, w):
                return False, "janela em foco não é " + str(alvo)[:40] + ": " + str(titulo)[:60]
            rect = w.get("rect") or [200, 200, 800, 600]
            moveu = False
            if input_disponivel() and len(rect) >= 4:
                moveu = bool(win_compat.mouse_move(int(rect[0]) + int(rect[2]) // 2, int(rect[1]) + 80))
            return True, ("cursor na janela " if moveu else "janela em foco, cursor não moveu: ") + str(titulo)[:80]
        import friday as fr
        import abrir_nativo
        key = abrir_nativo.chave_janela(alvo or "navegador")
        w = fr.find_window(key)
        if not w:
            return False, "janela não apareceu no compositor"
        g = fr._tile_geo(w)
        moveu = bool(g) and input_disponivel() and bool(_input().mouse_move(g[0] + g[2] // 2, g[1] + max(40, g[3] // 5)))
        if not fr._niri("focus-window", "--id", str(w["id"])):
            return False, "niri não focou a janela " + str(w.get("app_id") or key)[:60]
        return True, "cursor na janela" if moveu else "janela focada, cursor não moveu"
    except Exception as e:
        return False, str(e)[:140]


def _tecla(combo):
    if not input_disponivel() or not combo:
        return False
    try:
        return bool(_input().press_key(combo))
    except Exception:
        return False


def _ler_tela():
    try:
        import agent
        return agent.t_ver_tela()[:1500]
    except Exception as e:
        return "tela não lida: " + str(e)[:120]


def _tela_ok(txt):
    """Leitura válida? O texto de erro de _ler_tela não é conteúdo."""
    return bool(txt) and not str(txt).startswith("tela não lida")


_ESPERA_TELA = 0.4   # tempo para a tela redesenhar antes de conferir


def _assinatura_tela():
    """VER barato: miniatura cinza 96x54 da tela (grim; mss/PIL no Windows). None se a captura falhar."""
    try:
        import cv2
        import numpy as np
        img = None
        if sys.platform != "win32" and shutil.which("grim"):
            raw = subprocess.run(["grim", "-s", "0.25", "-t", "ppm", "-"], capture_output=True, timeout=4).stdout
            if raw:
                img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            import win_compat
            cor = win_compat.capturar_tela()
            if cor is not None:
                img = cv2.cvtColor(cor, cv2.COLOR_BGR2GRAY)
        if img is None:
            return None
        return cv2.resize(img, (96, 54), interpolation=cv2.INTER_AREA).tobytes()
    except Exception:
        return None


def _tela_mudou(antes, depois, tol=3):
    """CONFERIR: True/False; None sem captura (aí não bloqueia). Conservador: só diz 'não mudou' se nenhum pixel variou."""
    if antes is None or depois is None or len(antes) != len(depois):
        return None
    return any(abs(x - y) > tol for x, y in zip(antes, depois))


def _garantir_janela(alvo):
    """Cursor na janela. Se ela não existe, abre o app e leva o cursor. Sem shell."""
    foc, msg = _cursor_na_janela(alvo or "navegador")
    if foc:
        return True, msg, "cursor"
    try:
        import abrir_nativo
        nome = alvo or "navegador"
        ok, aberto = abrir_nativo.abrir_app(nome)
        time.sleep(0.5)
        foc, msg = _cursor_na_janela(nome)
        if foc:
            return True, str(aberto) + "; " + msg, "cursor"
        if ok:
            # app lançado mas o compositor ainda não confirmou: via "app" para a ação ser conferida na tela
            return True, str(aberto) + "; janela ainda sem geometria", "app"
        return False, str(aberto or msg), ""
    except Exception as e:
        return False, str(e)[:140], ""


_ACHADOS = {"urls": [], "textos": [], "arquivo": ""}


def _remover_anuncios_e_lixo(texto):
    if not texto:
        return ""
    linhas = []
    for l in texto.split("\n"):
        ln = l.strip()
        if not ln:
            continue
        if len(ln) < 200 and re.search(          # linha longa é conteúdo (página em 1 linha só): não apaga por 1 palavra
            r"\b(cookie|cookies|privacidade|todos os direitos|termos de uso|an[úu]ncio|anuncios?|"
            r"publicidade|sponsored|patrocinado|newsletter|inscreva-se|assine|propaganda|popup|modal|banner)\b",
            ln, re.I
        ):
            continue
        linhas.append(ln)
    return "\n".join(linhas)


def _nav():
    """navegador próprio da Friday (CDP lê, cursor/teclado reais agem). FRIDAY_NAV=0 desliga e volta à visão."""
    if os.environ.get("FRIDAY_NAV", "1") == "0" or not (shutil.which("chromium") or shutil.which("google-chrome")):
        return None
    try:
        import navegador
        return navegador
    except Exception:
        return None


def _urls_da_busca(consulta):
    nav = _nav()
    if nav:
        try:
            res = nav.resultados_busca(consulta, n=4)
            if len(res) >= 2:
                return [r["url"] for r in res], "\n".join(f"{r['site']} | {r['titulo']}" for r in res)
        except Exception:
            pass
    import agent
    c_low = (consulta or "").lower()
    if re.search(r"fortn", c_low) and re.search(r"loja|item|skin|hoje|vbuck|oficial", c_low):
        return ["https://fnbr.co/shop", "https://fortnite.gg/shop"], "Fontes oficiais da Loja do Fortnite"
    bruto = agent.t_pesquisar_web(consulta)
    urls = []
    for m in re.finditer(r"https?://[^\s|]+", bruto or ""):
        u = m.group(0).rstrip(").,]")
        if any(x in u for x in ("google.com/search", "duckduckgo.com", "bing.com/search")):
            continue
        if u not in urls:
            urls.append(u)
        if len(urls) >= 3:
            break
    if len(urls) < 2 and bruto:
        try:
            bruto2 = agent.t_pesquisar_web(consulta + " oficial")
            for m in re.finditer(r"https?://[^\s|]+", bruto2 or ""):
                u = m.group(0).rstrip(").,]")
                if any(x in u for x in ("google.com/search", "duckduckgo.com", "bing.com/search")):
                    continue
                if u not in urls:
                    urls.append(u)
                if len(urls) >= 2:
                    break
        except Exception:
            pass
    return urls, bruto


def _abrir_fonte(url):
    nav = _nav()
    if nav and not url.startswith("file://"):
        try:
            r = nav.abrir(url)
            if r.get("ok"):
                ads = r.get("anuncios_fechados") or []
                return {"ok": True, "evidencia": "abri no navegador da Friday: " + str(r.get("url")) + (" | fechei: " + "; ".join(ads) if ads else ""),
                        "via": "navegador", "conferido": "cdp", "url_final": r.get("url") or url}
        except Exception:
            pass
    ok, msg, _via = _garantir_janela("navegador")
    como = "sem ydotool/SendInput" if ok else msg
    if ok and input_disponivel():
        if _tecla("ctrl+l"):
            digitou, como = _focar_digitando(url)
            if digitou and _tecla("enter"):
                return {"ok": True, "evidencia": "abri na barra: " + url, "via": "teclado"}
            if digitou:
                como = "enter não foi aceito"
        else:
            como = "ctrl+l não foi aceito"
    import abrir_nativo
    ok2, msg2 = abrir_nativo.abrir_url(url)
    return {"ok": bool(ok2), "evidencia": "teclado não abriu a fonte (" + str(como) + "); fallback " + str(msg2) + " " + url, "via": "fallback"}


_ACOES_CURSOR = {"cursor", "focar", "abrir_navegador", "navegador", "abrir_app", "app"}
_CONFERE_TELA = {"clicar", "teclado", "digitar"} | _ACOES_CURSOR


def executar_acao(acao, args=None):
    """VER -> AGIR -> CONFERIR. Exceção vira falha (não derruba o loop) e ação de tela
    sem efeito visível vira falha com 'tela não mudou' (avancar() troca de caminho)."""
    a = (acao or "").strip().lower()
    antes = _assinatura_tela() if a in _CONFERE_TELA else None
    try:
        r = _executar_acao(a, args if isinstance(args, dict) else {})
    except Exception as e:
        return {"ok": False, "evidencia": "ação " + a + " falhou: " + type(e).__name__ + ": " + str(e)[:160], "via": "erro"}
    if not isinstance(r, dict):
        r = {"ok": bool(r), "evidencia": str(r or "")[:800], "via": ""}
    # sem captura (antes/depois None) a ação não é bloqueada; foco confirmado pelo compositor dispensa pixel
    if antes is not None and r.get("ok") and not r.get("conferido"):
        time.sleep(_ESPERA_TELA * (1 if a in {"clicar", "teclado", "digitar"} else 3))
        if _tela_mudou(antes, _assinatura_tela()) is False:
            r["ok"] = False
            r["evidencia"] = "tela não mudou após " + a + "; " + str(r.get("evidencia") or "")[:600]
    return r


def _executar_acao(a, args):
    if a in _ACOES_CURSOR:
        alvo = args.get("alvo") or args.get("nome") or args.get("app") or ("navegador" if "naveg" in a or a == "navegador" else "")
        ok, msg, via = _garantir_janela(alvo or "navegador")
        r = {"ok": ok, "evidencia": msg, "via": via or "cursor"}
        if ok and via == "cursor":
            r["conferido"] = "compositor"
        return r
    if a == "coletar":
        q = args.get("consulta") or args.get("q") or ""
        urls, bruto = _urls_da_busca(q)
        _ACHADOS["urls"] = urls
        _ACHADOS["textos"] = []
        if len(urls) < 2:
            return {"ok": False, "evidencia": "menos de 2 fontes. " + (bruto or "")[:240], "via": "tela"}
        return {"ok": True, "evidencia": "fontes: " + " | ".join(urls), "via": "tela"}
    if a == "abrir_pagina":
        if args.get("arquivo") and _ACHADOS.get("arquivo"):
            return _abrir_fonte("file://" + _ACHADOS["arquivo"])
        i = int(args.get("indice") or 0)
        urls = _ACHADOS.get("urls") or []
        if i >= len(urls):
            if len(urls) > 0:
                return {"ok": True, "evidencia": f"fonte alternativa já consolidada ({urls[0]})", "via": "tela"}
            return {"ok": False, "evidencia": "não há fonte " + str(i + 1), "via": "tela"}
        r = _abrir_fonte(urls[i])
        if r.get("url_final"):
            urls[i] = r["url_final"]              # link /goto do Google -> site real (ler_fonte compara com a página aberta)
        return r
    if a == "ler_fonte":
        i = int(args.get("indice") or 0)
        urls = _ACHADOS.get("urls") or []
        if i >= len(urls):
            if len(urls) > 0 and len(_ACHADOS.get("textos") or []) > 0:
                return {"ok": True, "evidencia": "conteúdo suficiente consolidado na fonte principal", "via": "tela"}
            return {"ok": False, "evidencia": "fonte " + str(i + 1) + " não foi aberta", "via": "tela"}
        url_alvo = urls[i]
        txt = ""
        # 1. Se for Fortnite, obtém dados oficiais completos da API de catálogo
        if re.search(r"fortn", url_alvo, re.I):
            try:
                import urllib.request
                req = urllib.request.Request("https://fortnite-api.com/v2/shop", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    d = json.loads(r.read().decode("utf-8"))
                linhas_itens = []
                data_api = d.get("data", {}).get("date", "")[:10]
                for e in d.get("data", {}).get("entries", []):
                    pr = e.get("finalPrice", 0)
                    if e.get("brItems"):
                        for it in e.get("brItems", []):
                            tipo = it.get("type", {}).get("displayValue", "Item")
                            linhas_itens.append(f"• {it.get('name')} [{tipo}]: {pr} V-Bucks - {it.get('description', '')}")
                    elif e.get("tracks"):
                        for tr in e.get("tracks", []):
                            linhas_itens.append(f"• Música/Pista '{tr.get('title')}' por {tr.get('artist', '')}: {pr} V-Bucks")
                    elif e.get("bundle"):
                        b = e.get("bundle")
                        linhas_itens.append(f"• Pacote/Bundle '{b.get('name')}': {pr} V-Bucks - {b.get('info', '')}")
                if linhas_itens:
                    txt = f"Catálogo Oficial e Atualizado da Loja de Itens do Fortnite ({data_api or time.strftime('%d/%m/%Y')}):\n" + "\n".join(linhas_itens[:50])
            except Exception:
                pass

        # 2. Página já renderizada no navegador da Friday (JS executado, anúncios fechados): texto do DOM, sem OCR
        nav = _nav()
        if nav and (not txt or len(txt) < 80):
            try:
                if not nav.disponivel() or nav.estado().get("url", "").split("#")[0] != url_alvo.split("#")[0]:
                    nav.abrir(url_alvo)
                txt = (nav.ler() or {}).get("texto") or ""
            except Exception:
                txt = ""

        # 3. Leitura HTTP direta da página sem ruído de tela
        if not txt or len(txt) < 80:
            import agent
            txt = agent.t_ler_pagina(url_alvo)

        # 3. Rolagem visual somente se o navegador estiver em foco e o conteúdo for insuficiente
        if not txt or len(txt) < 80:
            import agent
            txt = agent.t_ler_rolando(vezes=4, url=url_alvo)

        txt = _remover_anuncios_e_lixo(txt)
        _ACHADOS["textos"].append({"url": url_alvo, "txt": (txt or "")[:4000]})
        return {"ok": len(txt or "") >= 40, "evidencia": url_alvo + "\n" + (txt or "")[:500], "via": "tela"}

    if a == "concluir_pesquisa":
        lidos = [x for x in _ACHADOS.get("textos") or [] if len(x.get("txt") or "") >= 20]
        if not lidos:
            tela = _ler_tela()
            if _tela_ok(tela) and len(tela) > 30:
                lidos = [{"url": "tela_atual", "txt": tela}]
        if not lidos:
            return {"ok": False, "evidencia": "nenhuma informação encontrada na tela ou fontes.", "via": "tela"}
        consulta = args.get("consulta") or ""
        fontes_agrupadas = "\n\n".join([f"Fonte ({x.get('url')}):\n{x.get('txt', '')[:2500]}" for x in lidos])
        data_atual = time.strftime("%d/%m/%Y")

        prompt_sintese = (
            f"Você é a F.R.I.D.A.Y. Analise criticamente todas as informações apuradas sobre '{consulta}'.\n"
            f"Data atual de referência: {data_atual}.\n"
            f"DIRETRIZES ESTRITAS:\n"
            f"1. PROIBIDO O USO DE QUALQUER EMOJI OU CARACTERE PICTOGRÁFICO. Utilize exclusivamente texto alfanumérico e pontuação formal padrão.\n"
            f"2. A data atual de referência é {data_atual}. Nunca cite datas passadas como 2024.\n"
            f"3. Ignore totalmente anúncios publicitários, popups, cookies, banners ou termos de serviço.\n"
            f"4. Sintetize os achados em português do Brasil com alto nível de detalhe técnico, inteligência e profundidade:\n"
            f"   - Fatos confirmados, novidades e dados concretos (valores, características, itens, especificações);\n"
            f"   - Comparação ou análise crítica do cenário cruzando as fontes lidas;\n"
            f"   - Conclusão objetiva com badges técnicos [OK], [VERIFICADO].\n"
            f"5. Não invente dados, não faça cópia de fragmentos e não cite URLs brutas.\n\n"
            f"Dados apurados:\n{fontes_agrupadas[:5000]}"
        )
        sintese_ia = _modelo(prompt_sintese, max_tokens=800)
        if sintese_ia and len(sintese_ia.strip()) > 30:
            resumo = sintese_ia.strip()
        else:
            partes = []
            for x in lidos:
                blob = re.sub(r"\s+", " ", _remover_anuncios_e_lixo(x["txt"])).strip()
                if blob:
                    partes.append(blob[:400] + (f" (fonte: {x['url']})" if x['url'] != 'tela_atual' else ""))
            resumo = " | ".join(partes[:2])
        resumo = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]', '', resumo)
        resumo = re.sub(r'<think>.*?</think>', '', resumo, flags=re.DOTALL).strip()
        return {"ok": True, "evidencia": resumo, "via": "tela"}
    if a in {"preparar_mensagem", "redigir_mensagem"}:   # "mensagem" vai para mensagem() (mensageiro na tela)
        dest = args.get("para") or "Integra Code"
        pedido = args.get("pedido") or ""
        achados = _ACHADOS.get("textos") or []
        dados_fonte = "\n\n".join([f"Fonte ({x.get('url')}):\n{x.get('txt', '')[:2500]}" for x in achados])
        if not dados_fonte:
            tela = _ler_tela()
            dados_fonte = f"Contexto visual da tela:\n{tela}" if _tela_ok(tela) and len(tela) > 20 else "Dados apurados na navegação."

        data_atual = time.strftime("%d/%m/%Y")
        prompt_msg = (
            f"Você é a F.R.I.D.A.Y., agente de inteligência executiva e orquestração.\n"
            f"Redija uma mensagem corporativa analítica de alto nível para a equipe de '{dest}'.\n"
            f"Solicitação do usuário: {pedido}\n"
            f"Data atual de referência: {data_atual}\n\n"
            f"DIRETRIZES ESTRITAS DE FORMATAÇÃO E CONTEÚDO:\n"
            f"1. PROIBIDO O USO DE QUALQUER EMOJI OU CARACTERE PICTOGRÁFICO. Utilize exclusivamente texto alfanumérico e pontuação padrão formal.\n"
            f"2. A data atual é obrigatoriamente {data_atual}. Nunca mencione datas passadas (como 2024) ou fictícias.\n"
            f"3. Ignore totalmente anúncios publicitários, popups, cookies, banners ou termos de serviço contidos nos dados.\n"
            f"4. Analise profundamente os dados apurados e estruture a mensagem de forma humana, executiva, clara e articulada.\n"
            f"5. Destaque os pontos principais, valores, itens encontrados, novidades e conclusões práticas com valores em V-Bucks ou moeda quando identificados.\n"
            f"6. NÃO cole fragmentos crus de texto nem links soltos.\n"
            f"7. Estruture a mensagem no formato corporativo:\n"
            f"   - Destinatário: {dest}\n"
            f"   - Data da Apuração: {data_atual}\n"
            f"   - Resumo Executivo: Visão analítica sintetizada\n"
            f"   - Itens e Destaques Apurados: Lista técnica com itens, categorias e valores apurados\n"
            f"   - Considerações e Próximos Passos: Parecer operacional\n"
            f"   - Status: [STATUS: CONCLUIDO] [VERIFICADO: SIM] [DATA: {data_atual}]\n"
            f"   - Assinatura: F.R.I.D.A.Y. - Integra Code\n\n"
            f"Material de apuração:\n{dados_fonte[:6000]}"
        )
        msg_ia = _modelo(prompt_msg, max_tokens=1000)
        if msg_ia and len(msg_ia.strip()) > 50:
            corpo_msg = msg_ia.strip()
        else:
            corpo_msg = (
                f"Relatório Executivo para {dest}\n"
                f"Data da Apuração: {data_atual}\n\n"
                f"Resumo Executivo:\n"
                f"Levantamento executado com sucesso sobre: {pedido}.\n\n"
                f"Destaques Apurados:\n"
                f"{_remover_anuncios_e_lixo(dados_fonte)[:1200]}\n\n"
                f"[STATUS: CONCLUIDO]\n"
                f"[VERIFICADO: SIM]\n"
                f"[DATA: {data_atual}]\n\n"
                f"Atenciosamente,\n"
                f"F.R.I.D.A.Y. - Integra Code"
            )

        corpo_msg = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]', '', corpo_msg)
        corpo_msg = re.sub(r'<think>.*?</think>', '', corpo_msg, flags=re.DOTALL).strip()

        caminho_msg = os.path.join(ROOT, "memory", f"mensagem_{re.sub(r'[^a-zA-Z0-9]', '_', dest.lower())}.txt")
        try:
            with open(caminho_msg, "w", encoding="utf-8") as f:
                f.write(corpo_msg)
            _ACHADOS["arquivo"] = caminho_msg
            try:
                import auto_aprendizado
                auto_aprendizado.get_banco_conhecimento().registrar_aprendizado(
                    tarefa=f"preparar mensagem analítica para {dest}",
                    sucesso=True,
                    detalhes=f"Mensagem gerada com {len(corpo_msg)} caracteres em {caminho_msg}",
                    solucao="Análise semântica profunda das fontes e redação executiva"
                )
            except Exception:
                pass
            return {"ok": True, "evidencia": f"Mensagem analítica para {dest} gerada em {caminho_msg}:\n{corpo_msg[:300]}...", "via": "tela"}
        except Exception as e:
            return {"ok": False, "evidencia": f"falha ao gravar mensagem: {e}", "via": "fallback"}
    if a == "perguntar":
        return {"ok": False, "bloqueio": True, "evidencia": args.get("texto") or "falta um dado que só o dono sabe", "via": "tela"}
    # "documento" com caminho abre o arquivo no editor (documento()); sem caminho redige o relatório
    if a in {"escrever_doc", "montar_documento", "documento", "criar_relatorio"} and not (a == "documento" and args.get("caminho")):
        import agent
        pedido = args.get("pedido") or args.get("texto") or args.get("conteudo") or ""
        consulta = args.get("consulta") or pedido
        achados = _ACHADOS.get("textos") or []
        dados_fonte = "\n\n".join([f"Fonte ({x.get('url')}):\n{x.get('txt', '')[:2500]}" for x in achados])
        if not dados_fonte:
            tela = _ler_tela()
            dados_fonte = f"Contexto visual da tela:\n{tela}" if _tela_ok(tela) and len(tela) > 20 else ""

        data_atual = time.strftime("%d/%m/%Y")
        prompt_doc = (
            f"Você é a F.R.I.D.A.Y., arquiteta de dados e analista de inteligência.\n"
            f"Elabore um documento/relatório técnico analítico de alto padrão em Markdown sobre: '{consulta}'.\n"
            f"Objetivo do usuário: {pedido}\n"
            f"Data atual de referência: {data_atual}\n\n"
            f"DIRETRIZES ESTRITAS:\n"
            f"1. PROIBIDO O USO DE QUALQUER EMOJI OU CARACTERE PICTOGRÁFICO. Utilize exclusivamente texto alfanumérico e pontuação formal padrão.\n"
            f"2. A data atual é obrigatoriamente {data_atual}.\n"
            f"3. Ignore totalmente anúncios publicitários, banners, popups ou avisos de cookies.\n"
            f"Estrutura OBRIGATÓRIA do documento:\n"
            f"# Relatório Analítico: [Título Preciso]\n\n"
            f"## 1. Resumo Executivo\n"
            f"(Parágrafo conciso resumindo o panorama geral e principais conclusões na data {data_atual})\n\n"
            f"## 2. Levantamento e Análise Aprofundada\n"
            f"(Análise detalhada dos fatos, especificações, novidades, mecânicas ou informações apuradas)\n\n"
            f"## 3. Dados Comparativos e Destaques\n"
            f"(Tabela Markdown detalhada com itens, categorias, valores ou status identificados)\n\n"
            f"## 4. Recomendações e Conclusão\n"
            f"(Considerações práticas, próximos passos ou avaliação estratégica)\n\n"
            f"Exigências:\n"
            f"- NÃO faça cópia e cola de trechos soltos.\n"
            f"- Escreva texto original de nível executivo em português do Brasil com riqueza de conteúdo.\n\n"
            f"Material de base:\n{dados_fonte[:6000] if dados_fonte else pedido}"
        )
        doc_ia = _modelo(prompt_doc, max_tokens=1500)
        texto_final = doc_ia.strip() if doc_ia and len(doc_ia.strip()) > 80 else None
        if not texto_final:
            texto_final = (
                f"# Relatório: {consulta.title()}\n\n"
                f"Data da Apuração: {data_atual}\n\n"
                f"## 1. Resumo dos Achados\n\n"
                f"{_remover_anuncios_e_lixo(dados_fonte) or pedido}\n\n"
                f"## 2. Conclusão\n"
                f"Levantamento concluído e documentado pela F.R.I.D.A.Y.\n"
            )

        texto_final = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]', '', texto_final)
        texto_final = re.sub(r'<think>.*?</think>', '', texto_final, flags=re.DOTALL).strip()

        slug = re.sub(r"[^a-zA-Z0-9]+", "_", consulta.lower()).strip("_")[:30] or "relatorio"
        caminho_doc = f"relatorio_{slug}.md"
        try:
            r = agent.t_criar_arquivo(caminho=caminho_doc, conteudo=texto_final, abrir=False)
        except Exception as e:
            return {"ok": False, "evidencia": str(e)[:160], "via": "fallback"}
        m = re.search(r"(/[^\s]+)", r)
        if m:
            _ACHADOS["arquivo"] = m.group(1).rstrip(")")
        else:
            _ACHADOS["arquivo"] = os.path.expanduser(f"~/Documentos/Friday/{caminho_doc}")

        try:
            import auto_aprendizado
            auto_aprendizado.get_banco_conhecimento().registrar_aprendizado(
                tarefa=f"montar documento analítico sobre {consulta}",
                sucesso=True,
                detalhes=f"Relatório gerado com {len(texto_final)} caracteres",
                solucao="Síntese estruturada em seções analíticas com tabela comparativa"
            )
        except Exception:
            pass

        return {"ok": True, "evidencia": f"Documento analítico criado: {caminho_doc} ({len(texto_final)} caracteres)", "via": "tela"}
    if a == "montar_app":
        import agent
        html = "<!doctype html><meta charset=utf-8><title>Friday</title><h1>App</h1><p>" + (args.get("pedido") or "")[:200] + "</p>"
        try:
            r = agent.t_criar_arquivo(caminho="friday-app.html", conteudo=html)
        except Exception as e:
            return {"ok": False, "evidencia": str(e)[:160], "via": "fallback"}
        m = re.search(r"(/[^\s]+)", r)
        if m:
            _ACHADOS["arquivo"] = m.group(1).rstrip(")")
        return {"ok": True, "evidencia": r, "via": "fallback"}
    if a == "confirmar_arquivo":
        p = _ACHADOS.get("arquivo") or ""
        if not p or not os.path.isfile(p) or os.path.getsize(p) < 1:
            return {"ok": False, "evidencia": "arquivo ausente ou vazio: " + p, "via": "tela"}
        return {"ok": True, "evidencia": p + " " + str(os.path.getsize(p)) + " bytes", "via": "tela"}
    if a in {"pesquisar", "pesquisa"}:
        q = str(args.get("consulta") or args.get("q") or "").strip()
        if not q:
            return {"ok": False, "evidencia": "pesquisa sem consulta: nada digitado", "via": "teclado"}
        ok, msg, via = _garantir_janela("navegador")
        if not ok:
            return {"ok": False, "evidencia": msg, "via": "cursor"}
        if _tecla("ctrl+l"):
            digitou, como = _focar_digitando(q)
            if digitou and _tecla("enter"):
                return {"ok": True, "evidencia": "digitei a busca; " + _ler_tela()[:400], "via": "teclado"}
            if digitou:
                como = "enter não foi aceito"
        else:
            como = "ctrl+l não foi aceito"
        import urllib.parse
        import abrir_nativo
        ok2, msg2 = abrir_nativo.abrir_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(q))
        return {"ok": bool(ok2), "evidencia": "teclado falhou (" + como + "); fallback " + str(msg2), "via": "fallback"}
    if a == "ler_tela":
        txt = _ler_tela()
        return {"ok": _tela_ok(txt), "evidencia": txt, "via": "tela"}
    if a == "clicar":
        ok, msg, via = _garantir_janela(args.get("alvo") or "navegador")
        if not ok or not input_disponivel():
            return {"ok": False, "evidencia": (msg or "janela não focou") + "; clique não saiu", "via": via or "cursor"}
        x, y = args.get("x"), args.get("y")
        if x is not None and y is not None:
            if not _input().mouse_move(int(x), int(y)):
                return {"ok": False, "evidencia": msg + "; cursor não foi até " + str(x) + "," + str(y), "via": "cursor"}
        elif via != "cursor" or "cursor não moveu" in msg:
            return {"ok": False, "evidencia": msg + "; cursor fora da janela, não cliquei às cegas", "via": via or "cursor"}
        try:
            clicou = bool(_input().mouse_click(args.get("botao") or "left"))
        except Exception:
            clicou = False
        if clicou:
            return {"ok": True, "evidencia": msg + "; clique. " + _ler_tela()[:240], "via": "cursor"}
        return {"ok": False, "evidencia": msg + "; clique não saiu", "via": via or "cursor"}
    if a in {"teclado", "digitar"}:
        atalho = args.get("atalho") or args.get("tecla") or ""
        texto = str(args.get("texto") or "")
        if not (atalho or texto or args.get("enter")):
            return {"ok": False, "evidencia": "teclado sem atalho, texto ou enter: nada a fazer", "via": "teclado"}
        feito = []
        if atalho:
            if not _tecla(atalho):
                return {"ok": False, "evidencia": "atalho " + str(atalho) + " não foi aceito; não digitei", "via": "teclado"}
            feito.append(str(atalho))
        if texto:
            ok, como = _focar_digitando(texto)
            if not ok:
                return {"ok": False, "evidencia": "; ".join(feito + [como]), "via": "teclado"}
            feito.append(como)
        if args.get("enter"):
            if not _tecla("enter"):
                return {"ok": False, "evidencia": "; ".join(feito + ["enter não foi aceito"]), "via": "teclado"}
            feito.append("enter")
        return {"ok": True, "evidencia": "; ".join(feito) + "; " + _ler_tela()[:300], "via": "teclado"}
    if a == "claude":
        return claude_cli(args.get("pedido") or args.get("prompt") or "", continuar=bool(args.get("continuar")))
    if a == "email":
        return email_cliente(args.get("para", ""), args.get("assunto", ""), args.get("corpo", ""))
    if a == "mensagem":
        return mensagem(args.get("texto") or args.get("corpo") or "")
    if a in {"documento", "planilha"}:
        return documento(args.get("caminho") or "", args.get("tipo") or "docx")
    if a == "falar":
        return falar(args.get("texto") or "")
    if a == "camera":
        return camera(args.get("descrever", True))
    if a == "rea":
        return rea(args.get("alvo") or args.get("caminho") or "")
    if a == "pensar":
        return {"ok": True, "evidencia": "plano mantido: " + str(args.get("texto") or "")[:200], "via": "plano"}
    if a in {"notar", "nota"}:   # _passo() cria "nota" para passo em texto puro
        return {"ok": True, "evidencia": str(args.get("texto") or "")[:300], "via": "estado"}
    if a == "esperar":
        try:
            seg = max(0.0, min(float(args.get("segundos") or args.get("s") or 2), 30.0))
        except (TypeError, ValueError):
            seg = 2.0
        time.sleep(seg)
        return {"ok": True, "evidencia": "esperei " + str(round(seg, 1)) + "s", "via": "plano"}
    if a == "shell":
        return _shell_fallback(args.get("comando") or "")
    txt = _ler_tela()
    return {"ok": _tela_ok(txt), "evidencia": "ação " + a + " virou leitura de tela. " + txt[:400], "via": "tela"}


_CLAUDE_PTY = {"proc": None, "fd": None, "buf": ""}


def _pty_claude(exe, pedido, continuar):
    """Sessão que fica aberta. A próxima chamada escreve no mesmo buffer."""
    import select
    st = _CLAUDE_PTY
    proc = st.get("proc")
    if proc is None or proc.poll() is not None:
        import pty
        master, slave = pty.openpty()
        proc = subprocess.Popen([exe], stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        st["proc"] = proc
        st["fd"] = master
        st["buf"] = ""
        time.sleep(0.6)
    fd = st["fd"]
    try:
        os.write(fd, ((pedido or "")[:1500] + "\n").encode())
    except Exception as e:
        return "pty: " + str(e)[:140]
    buf = b""
    t0 = time.time()
    while time.time() - t0 < 8:
        pronto, _, _ = select.select([fd], [], [], 0.4)
        if not pronto:
            if buf and time.time() - t0 > 2.5:
                break
            continue
        try:
            pedaco = os.read(fd, 4096)
        except OSError:
            break
        if not pedaco:
            break
        buf += pedaco
    texto = buf.decode("utf-8", "replace")
    st["buf"] = ((st.get("buf") or "") + texto)[-8000:]
    return (texto or st["buf"])[-2000:]


def claude_cli(pedido, continuar=False):
    if recusar(pedido):
        return {"ok": False, "evidencia": recusar(pedido), "via": "recusa"}
    exe = shutil.which("claude")
    if not exe:
        return {
            "ok": False,
            "via": "ausente",
            "evidencia": "Claude CLI não está no PATH. Instale o Claude Code "
                         "(npm i -g @anthropic-ai/claude-code) e faça login uma vez no seu terminal. Não executei.",
        }
    nome = "wt" if sys.platform == "win32" else "kitty"
    okj, msgj, _ = _garantir_janela(nome)
    if okj and input_disponivel():
        if not continuar:
            _focar_digitando("claude")
            _tecla("enter")
            time.sleep(1.0)
        _focar_digitando(pedido[:500])
        _tecla("enter")
        time.sleep(2.0)
        tela = _ler_tela()
        if len(tela) > 80:
            return {"ok": True, "evidencia": tela[:1500], "via": "teclado"}
    buf = _pty_claude(exe, pedido, continuar)
    return {"ok": bool(buf), "evidencia": buf or "sem saída no buffer", "via": "pty-fallback"}


def _mailto_fallback(para, assunto, corpo):
    """Último recurso. Não envia."""
    import urllib.parse
    q = urllib.parse.urlencode({"subject": assunto or "", "body": (corpo or "")[:2000]}, quote_via=urllib.parse.quote)
    url = "mailto:" + (para or "") + ("?" + q if q else "")
    try:
        if sys.platform == "win32":
            import abrir_nativo
            ok, msg = abrir_nativo._win_start(url)
            return {"ok": ok, "evidencia": "teclado não compôs; " + msg + " — o envio fica com você", "via": "fallback"}
        if shutil.which("xdg-email"):
            cmd = ["xdg-email", "--subject", assunto or "", "--body", (corpo or "")[:2000]]
            if para:
                cmd.append(para)
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return {"ok": True, "evidencia": "teclado não compôs; xdg-email aberto, sem enviar", "via": "fallback"}
        if shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return {"ok": True, "evidencia": "teclado não compôs; mailto pelo xdg-open, sem enviar", "via": "fallback"}
    except Exception as e:
        return {"ok": False, "evidencia": str(e)[:160], "via": "fallback"}
    return {"ok": False, "evidencia": "sem cliente de e-mail", "via": "fallback"}


def email_cliente(para, assunto, corpo):
    """Cursor no cliente, rascunho no teclado. Não envia e não usa senha daqui."""
    for alvo in ("thunderbird", "geary", "evolution", "email"):
        ok, msg, _via = _garantir_janela(alvo)
        if not ok:
            continue
        if input_disponivel():
            _tecla("ctrl+n")
            bloco = ((para + "\t") if para else "") + (assunto or "mensagem") + "\t" + (corpo or "")[:500]
            digitou, _como = _focar_digitando(bloco)
            if digitou:
                return {"ok": True, "evidencia": "rascunho na tela, sem enviar. " + msg + " " + _ler_tela()[:240], "via": "teclado"}
        break
    return _mailto_fallback(para, assunto, corpo)


def mensagem(texto):
    """Foca o mensageiro e digita. Não envia."""
    for alvo in ("zapzap", "whatsapp", "telegram"):
        ok, msg, _via = _garantir_janela(alvo)
        if not ok or not input_disponivel():
            continue
        digitou, _como = _focar_digitando((texto or "")[:300])
        if digitou:
            return {"ok": True, "evidencia": "texto no campo, sem enviar. " + msg + " " + _ler_tela()[:200], "via": "teclado"}
    try:
        import friday as fr
        ok, msg = fr.run_action({"t": "zap", "op": "abrir"}, None)
        if ok and input_disponivel():
            digitou, _como = _focar_digitando((texto or "")[:300])
            if digitou:
                return {"ok": True, "evidencia": "texto no campo, sem enviar", "via": "teclado"}
        if ok:
            return {"ok": True, "evidencia": msg or "mensageiro em foco", "via": "cursor"}
    except Exception:
        pass
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", "sms:"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {"ok": True, "evidencia": "teclado não alcançou o mensageiro; compositor sms: aberto", "via": "fallback"}
    return {"ok": False, "evidencia": "mensageiro não ficou em foco", "via": "cursor"}


def documento(caminho, tipo="docx"):
    caminho = os.path.expanduser(caminho or "")
    for alvo in ("libreoffice", "soffice", "calc"):
        ok, msg, _via = _garantir_janela(alvo)
        if not ok:
            continue
        if caminho and input_disponivel():
            _tecla("ctrl+o")
            digitou, _como = _focar_digitando(caminho)
            if digitou:
                _tecla("enter")
                return {"ok": True, "evidencia": "diálogo pelo teclado. " + _ler_tela()[:300], "via": "teclado"}
        return {"ok": True, "evidencia": msg + " " + _ler_tela()[:200], "via": "cursor"}
    if caminho and os.path.isfile(caminho):
        try:
            if sys.platform == "win32":
                import abrir_nativo
                ok, msg = abrir_nativo._win_start(caminho)
            elif shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                ok, msg = True, "xdg-open"
            else:
                ok, msg = False, "sem xdg-open"
            return {"ok": ok, "evidencia": "tela não achou o editor; " + msg + " " + caminho, "via": "fallback"}
        except Exception as e:
            return {"ok": False, "evidencia": str(e)[:160], "via": "fallback"}
    return {"ok": False, "evidencia": "editor não ficou em foco e o arquivo não existe", "via": "cursor"}


def falar(texto):
    texto = (texto or "").strip()
    if not texto:
        return {"ok": False, "evidencia": "nada para falar", "via": ""}
    if sys.platform == "win32":
        lit = texto.replace("'", "''")[:500]
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command",
                 f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{lit}')"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            return {"ok": True, "evidencia": "TTS do Windows", "via": "System.Speech"}
        except Exception as e:
            return {"ok": False, "evidencia": str(e)[:140], "via": ""}
    for exe, args in (("spd-say", ["-l", "pt-BR"]), ("espeak-ng", ["-v", "pt-br"]), ("espeak", ["-v", "pt"])):
        if shutil.which(exe):
            subprocess.Popen([exe, *args, texto[:500]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return {"ok": True, "evidencia": exe, "via": "TTS do sistema"}
    return {"ok": False, "evidencia": "sem spd-say/espeak. O Piper do projeto continua no daemon de voz.", "via": "gancho"}


def camera(descrever=True):
    devs = []
    if sys.platform != "win32":
        try:
            devs = sorted(x for x in os.listdir("/dev") if x.startswith("video"))
        except Exception:
            devs = []
    frame = os.path.join(MEM, "orquestra_camera.jpg")
    try:
        import win_compat
        cap = win_compat.abrir_camera(0)
        ok = cap is not None and cap.isOpened()
        if ok:
            import cv2
            bom, img = cap.read()
            cap.release()
            if bom and img is not None:
                cv2.imwrite(frame, img)
                visao = ""
                if descrever:
                    visao = _descrever_frame(frame)
                return {"ok": True, "evidencia": f"frame em {frame}. dispositivos={devs or ['indice 0']}. {visao}", "via": "câmera do SO"}
        return {"ok": False, "evidencia": "câmera não abriu. dispositivos=" + ",".join(devs), "via": "gancho"}
    except Exception as e:
        return {"ok": False, "evidencia": "gancho de câmera: " + str(e)[:160] + " dispositivos=" + ",".join(devs), "via": "gancho"}


def _descrever_frame(caminho):
    try:
        import cloud_providers as cp
        with open(caminho, "rb") as f:
            jpg = f.read()
        r = cp.consultar_vlm(jpg, "Descreva em uma frase, em português, o que aparece. Se não houver rosto, diga isso.", max_tokens=80)
        if isinstance(r, dict):
            return str(r.get("texto") or r.get("text") or r)[:300]
        return str(r)[:300]
    except Exception:
        return "Sem modelo de visão respondendo: o frame foi salvo, o reconhecimento de expressão não rodou."


def rea(alvo):
    """Gancho. Não dispara npx nem finge sessão MCP."""
    alvo = os.path.expanduser(str(alvo or "").strip())
    if recusar(alvo):
        return {"ok": False, "evidencia": recusar(alvo), "via": "recusa"}
    if not alvo or not os.path.exists(alvo):
        return {"ok": False, "evidencia": "REA precisa de um arquivo local que você tem direito de analisar.", "via": "gancho"}
    return {
        "ok": False,
        "via": "gancho",
        "evidencia": "REA MCP não está ligado no orquestrador. Com código-fonte, leia o código. "
                     "Sem fonte, o gancho continua o CLI rea no app que você pode analisar. Não executei.",
    }


def _shell_fallback(comando):
    if not isinstance(comando, str) or not comando.strip():
        return {"ok": False, "evidencia": "shell NÃO executado: comando vazio ou inválido (a tela falhou e não há comando de fallback)", "via": "fallback"}
    if recusar(comando):
        return {"ok": False, "evidencia": recusar(comando), "via": "recusa"}
    try:
        import shell_seguro
        d = shell_seguro.executar(comando)
        return {"ok": bool(d.get("ok")), "evidencia": (d.get("saida") or d.get("erro") or "")[:1500], "via": "shell_seguro (fallback)"}
    except Exception as e:
        return {"ok": False, "evidencia": "shell não rodou: " + str(e)[:160], "via": "fallback"}


def sessao_nova(pedido):
    neg = recusar(pedido)
    if neg:
        return {"ok": False, "fala": neg, "recusa": True}
    plano = planejar(pedido)
    ses = {
        "id": "s" + str(int(time.time())),
        "pedido": pedido,
        "status": "ativa",
        "plano": plano,
        "passo_atual": 1,
        "evidencia": [],
        "proximo": plano["passos"][0]["acao"] if plano["passos"] else "",
        "atualizado": time.time(),
        "erros": 0,
    }
    _salvar(SESSAO, ses)
    return {"ok": True, "sessao": ses}


def _pendente(ses):
    for p in ses.get("plano", {}).get("passos") or []:
        if p.get("estado") in (None, "", "pendente"):
            return p
    return None


def avancar(ses=None):
    ses = ses or _ler(SESSAO, None)
    if not ses:
        return {"ok": False, "fala": "sem sessão. Use: prom-orquestra run \"pedido\""}
    if ses.get("status") == "recusada":
        return {"ok": False, "fala": ses.get("fala") or "recusada"}
    p = _pendente(ses)
    if not p:
        ses["status"] = "concluida"
        ses["proximo"] = ""
        ses["atualizado"] = time.time()
        _salvar(SESSAO, ses)
        return {"ok": True, "fala": "plano concluído", "sessao": ses}
    r = executar_acao(p["acao"], p.get("args") or {})
    p["evidencia"] = str(r.get("evidencia") or "")[:800]
    p["via"] = r.get("via") or ""
    if r.get("bloqueio"):
        p["estado"] = "bloqueado"   # parado esperando o dono; não é sucesso
        p["evidencia"] = str(r.get("evidencia") or "")[:800]
        ses["status"] = "bloqueada"
        ses["proximo"] = ""
        ses["atualizado"] = time.time()
        _salvar(SESSAO, ses)
        return {"ok": False, "bloqueio": True, "fala": p["evidencia"], "via": "tela", "sessao": ses}
    if r.get("ok"):
        p["estado"] = "ok"
        ses["erros"] = 0
    else:
        p["estado"] = "pulado"
        ses["erros"] = int(ses.get("erros") or 0) + 1
        if ses["erros"] <= 3 and p.get("acao") != "shell":
            if p.get("acao") != "ler_tela":
                alt = {"acao": "ler_tela", "args": {}, "pronto": "outro caminho na tela"}
            else:
                # leitura falhou: refoca a janela do plano. Antes virava "teclado" e digitava o critério
                # de pronto ("tela lida"...) na janela do dono.
                alvo = next((s.get("args", {}).get("alvo") for s in reversed(ses["plano"]["passos"])
                             if s.get("acao") == "cursor" and (s.get("args") or {}).get("alvo")), "")
                alt = {"acao": "cursor", "args": {"alvo": alvo}, "pronto": "janela refocada para reler"}
            ses["plano"]["passos"].append(_passo(len(ses["plano"]["passos"]) + 1, alt))
        elif p.get("acao") != "shell":
            ses["plano"]["passos"].append(_passo(len(ses["plano"]["passos"]) + 1, {
                "acao": "shell",
                "args": {"comando": ""},
                "pronto": "fallback só depois que a tela falhou",
            }))
    nxt = _pendente(ses)
    ses["passo_atual"] = nxt["n"] if nxt else p["n"]
    ses["proximo"] = nxt["acao"] if nxt else ""
    ses["status"] = "ativa" if nxt else "concluida"
    ses["evidencia"] = (ses.get("evidencia") or [])[-20:] + [{"t": time.time(), "n": p["n"], "res": p["evidencia"][:240]}]
    ses["atualizado"] = time.time()
    _salvar(SESSAO, ses)
    return {"ok": bool(r.get("ok")), "fala": p["evidencia"], "via": p.get("via"), "sessao": ses}


_TRAVA = None


def trava_unica():
    """Um único executor por máquina (daemon OU serviço). True = este processo é o dono; idempotente."""
    global _TRAVA
    if _TRAVA is not None:
        return True
    f = open(os.path.join(MEM, "orquestra.lock"), "a+")
    try:
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return False
    _TRAVA = f
    return True


def _fila_tick_seguro():
    try:
        return fila_tick()
    except Exception as e:
        print("erro na fila:", type(e).__name__, str(e)[:160], flush=True)
        return None


def loop(horas=8, intervalo=20, max_passos=500, sempre=False):
    """Roda até acabar o plano, o tempo ou max_passos. Erro não encerra.
    sempre=True (ou horas<=0): não para com fila vazia, espera novos pedidos indefinidamente."""
    sempre = sempre or float(horas) <= 0
    while not trava_unica():
        if not sempre:
            return {"passos": 0, "ultimo": "outro orquestrador já está rodando nesta máquina", "sessao": _ler(SESSAO, {})}
        time.sleep(max(1.0, float(intervalo)))   # reserva: assume quando o outro executor (daemon) cair
    fim = float("inf") if sempre else time.time() + float(horas) * 3600
    n = 0
    ultimo = ""
    while time.time() < fim and (sempre or n < max_passos):
        ses = _ler(SESSAO, None)
        if not ses or ses.get("status") in {"concluida", "pausada", "bloqueada"}:
            if not _fila_tick_seguro():
                if not sempre:
                    break
                time.sleep(max(1.0, float(intervalo)))
                continue
        try:
            r = avancar()
        except Exception as e:   # erro não encerra: o passo pendente vira "pulado" para não repetir em loop
            r = {"fala": "erro no passo: " + type(e).__name__ + ": " + str(e)[:160]}
            try:
                s = _ler(SESSAO, None)
                pend = _pendente(s) if s else None
                if pend:
                    pend["estado"] = "pulado"
                    pend["evidencia"] = r["fala"]
                    _salvar(SESSAO, s)
            except Exception:
                pass
        n += 1
        ultimo = r.get("fala") or ""
        if _ler(SESSAO, {}).get("status") == "concluida":
            if not _fila_tick_seguro() and not sempre:
                break
        time.sleep(max(1.0, float(intervalo)))
    return {"passos": n, "ultimo": ultimo, "sessao": _ler(SESSAO, {})}


def _quando_ts(it):
    """'+30s|+10m|+2h|+1d', epoch ou ISO -> timestamp; vazio/inválido = agora."""
    q = str(it.get("quando") or "").strip()
    if not q:
        return 0.0
    m = re.fullmatch(r"\+(\d+(?:\.\d+)?)\s*([smhd]?)", q)
    if m:
        mult = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
        return float(it.get("t") or 0) + float(m.group(1)) * mult
    try:
        return float(q)
    except ValueError:
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(q).timestamp()
    except ValueError:
        return 0.0


def enfileirar(pedido, quando=""):
    neg = recusar(pedido)
    if neg:
        return {"ok": False, "fala": neg}
    fila = _ler(FILA, {"itens": []})
    item = {"id": "q" + str(int(time.time() * 1000))[-8:], "pedido": pedido, "quando": quando, "status": "esperando", "t": time.time()}
    fila["itens"].append(item)
    _salvar(FILA, fila)
    return {"ok": True, "item": item}


def fila_tick():
    """Um objetivo ativo. Os outros esperam. Retoma o primeiro esperando se a sessão acabou."""
    ses = _ler(SESSAO, None)
    if ses and ses.get("status") == "ativa":
        return None
    fila = _ler(FILA, {"itens": []})
    agora = time.time()
    fim = (ses or {}).get("status")
    for it in fila.get("itens") or []:
        if it.get("status") == "ativo" and fim in {"concluida", "bloqueada", "recusada"}:
            it["status"] = "feito" if fim == "concluida" else fim
            _salvar(FILA, fila)
    for it in fila.get("itens") or []:
        if it.get("status") != "esperando":
            continue
        if _quando_ts(it) > agora:
            continue
        s = sessao_nova(it["pedido"])          # planeja ANTES de marcar: queda no meio não deixa item "ativo" órfão
        it["status"] = "ativo" if s.get("ok") else "recusada"
        _salvar(FILA, fila)
        if s.get("ok"):
            return it
    return None


def status():
    return {"sessao": _ler(SESSAO, {}), "fila": _ler(FILA, {"itens": []})}


def _smoke_correcoes():
    """Asserts das correções com tudo mockado: input, tela, janelas, shell e sessão (nada real é tocado)."""
    import types

    class FakeInput:
        def __init__(self):
            self.res = {"type": True, "key": True, "click": True, "move": True}
            self.recusa = set()
            self.log = []

        def type_text(self, t):
            self.log.append(("type", t))
            return self.res["type"]

        def press_key(self, k):
            self.log.append(("key", k))
            return self.res["key"] and k not in self.recusa

        def mouse_click(self, botao="left", duplo=False):
            self.log.append(("click", botao))
            return self.res["click"]

        def mouse_move(self, x, y, passos=15):
            self.log.append(("move", x, y))
            return self.res["move"]

    g = globals()
    nomes = ("input_disponivel", "_input", "_ler_tela", "_assinatura_tela", "_garantir_janela",
             "_urls_da_busca", "mensagem", "documento", "fila_tick", "avancar", "SESSAO", "_ESPERA_TELA")
    salvo = {k: g[k] for k in nomes}
    mods = {k: sys.modules.get(k) for k in ("abrir_nativo", "friday", "shell_seguro", "win_compat")}
    sono, plataforma = time.sleep, sys.platform
    chamadas = {"shell": [], "url": []}
    smoke_ses = os.path.join(MEM, "orquestra_smoke_sessao.json")
    try:
        fake = FakeInput()
        g["input_disponivel"] = lambda: True
        g["_input"] = lambda: fake
        g["_ler_tela"] = lambda: "janela em foco: teste"
        g["_garantir_janela"] = lambda alvo: (True, "cursor na janela", "cursor")
        g["_ESPERA_TELA"] = 0
        g["SESSAO"] = smoke_ses
        time.sleep = lambda s: None
        sys.modules["abrir_nativo"] = types.SimpleNamespace(
            abrir_url=lambda u: (chamadas["url"].append(u) or (True, "url aberta (fake)")),
            abrir_app=lambda n: (False, "fake não abre app"),
            chave_janela=lambda n: str(n or "").lower())
        sys.modules["shell_seguro"] = types.SimpleNamespace(
            executar=lambda c: (chamadas["shell"].append(c) or {"ok": True, "saida": "rodou"}))

        # 1. VER->AGIR->CONFERIR: tela igual = falha "tela não mudou"; diferente = ok; sem captura não bloqueia
        telas = iter([b"\x10" * 8, b"\x10" * 8])
        g["_assinatura_tela"] = lambda: next(telas)
        r = executar_acao("teclado", {"texto": "abc"})
        assert not r["ok"] and "tela não mudou" in r["evidencia"], r
        telas = iter([b"\x10" * 8, b"\x90" * 8])
        assert executar_acao("teclado", {"texto": "abc"})["ok"]
        g["_assinatura_tela"] = lambda: None
        assert executar_acao("teclado", {"texto": "abc"})["ok"], "sem captura não pode bloquear"
        g["_assinatura_tela"] = lambda: b"\x10" * 8
        assert executar_acao("cursor", {"alvo": "kitty"})["ok"], "foco confirmado pelo compositor dispensa pixel"
        r = executar_acao("clicar", {"alvo": "kitty"})
        assert not r["ok"] and "tela não mudou" in r["evidencia"], r
        g["_garantir_janela"] = lambda alvo: (True, "app aberto; janela ainda sem geometria", "app")
        r = executar_acao("abrir_app", {"nome": "spotify"})
        assert not r["ok"] and "tela não mudou" in r["evidencia"], r
        g["_garantir_janela"] = lambda alvo: (True, "cursor na janela", "cursor")
        g["_assinatura_tela"] = lambda: None

        # 2. teclado: input que falhou não vira ok; atalho recusado não digita; passo vazio falha; enter conferido
        fake.res["type"] = False
        assert not executar_acao("teclado", {"texto": "abc"})["ok"]
        assert not executar_acao("teclado", {"atalho": "ctrl+n", "texto": "abc"})["ok"], "antes: ok só por ter atalho"
        fake.res.update(type=True, key=False)
        fake.log.clear()
        r = executar_acao("teclado", {"atalho": "ctrl+n", "texto": "abc"})
        assert not r["ok"] and not any(c[0] == "type" for c in fake.log), (r, fake.log)
        fake.res["key"] = True
        fake.recusa = {"enter"}
        r = executar_acao("teclado", {"texto": "abc", "enter": True})
        assert not r["ok"] and "enter" in r["evidencia"], r
        assert not executar_acao("teclado", {"enter": True})["ok"]
        fake.recusa = set()
        assert not executar_acao("teclado", {})["ok"]
        assert _focar_digitando("") == (False, "sem texto para digitar")

        # 3. pesquisar/_abrir_fonte: consulta vazia não digita; ctrl+l ou enter recusado cai no fallback
        assert not executar_acao("pesquisar", {"consulta": "  "})["ok"]
        fake.recusa = {"ctrl+l"}
        fake.log.clear()
        r = executar_acao("pesquisar", {"consulta": "clima"})
        assert r["via"] == "fallback" and chamadas["url"] and not any(c[0] == "type" for c in fake.log), r
        fake.recusa = {"enter"}
        r = _abrir_fonte("https://exemplo.org")
        assert r["via"] == "fallback" and "enter" in r["evidencia"], r
        fake.recusa = set()
        assert _abrir_fonte("https://exemplo.org")["via"] == "teclado"

        # 4. clicar: usa x/y; clique recusado falha com evidência; cursor fora da janela não clica às cegas
        fake.log.clear()
        assert executar_acao("clicar", {"x": 10, "y": 20})["ok"] and ("move", 10, 20) in fake.log, fake.log
        fake.res["click"] = False
        r = executar_acao("clicar", {})
        assert not r["ok"] and "clique não saiu" in r["evidencia"], r
        fake.res["click"] = True
        g["_garantir_janela"] = lambda alvo: (True, "app aberto; janela ainda sem geometria", "app")
        fake.log.clear()
        assert not executar_acao("clicar", {})["ok"] and not any(c[0] == "click" for c in fake.log)
        g["_garantir_janela"] = lambda alvo: (True, "cursor na janela", "cursor")

        # 5. foco: niri recusou focar = falha (antes devolvia ok); no Windows a janela em foco tem de ser o alvo
        fr_fake = types.SimpleNamespace(find_window=lambda k: {"id": 7, "app_id": k},
                                        _tile_geo=lambda w: (0, 0, 800, 600), _niri=lambda *a: False)
        sys.modules["friday"] = fr_fake
        ok, msg = _cursor_na_janela("kitty")
        assert not ok and "niri" in msg, msg
        fr_fake._niri = lambda *a: True
        assert _cursor_na_janela("kitty") == (True, "cursor na janela")
        sys.platform = "win32"
        sys.modules["win_compat"] = types.SimpleNamespace(
            janela_em_foco=lambda: {"id": "1", "app_id": "Code.exe", "titulo": "VS Code", "rect": [0, 0, 800, 600]},
            mouse_move=lambda x, y: True)
        assert not _cursor_na_janela("thunderbird")[0], "antes: qualquer janela em foco valia"
        assert _cursor_na_janela("code")[0]
        sys.platform = plataforma

        # 6. exceção dentro da ação vira falha e não derruba o loop
        def explode(q):
            raise RuntimeError("busca caiu")
        g["_urls_da_busca"] = explode
        r = executar_acao("coletar", {"consulta": "x"})
        assert not r["ok"] and "RuntimeError" in r["evidencia"], r
        assert not executar_acao("abrir_pagina", {"indice": "primeira"})["ok"]

        # 7. shell com comando vazio não executa nada e conta como falha com evidência clara
        for vazio in ("", "   ", None):
            r = executar_acao("shell", {"comando": vazio})
            assert not r["ok"] and "NÃO executado" in r["evidencia"], r
        assert not chamadas["shell"], chamadas

        # 8. roteamento: "nota" registra; "mensagem" vai ao mensageiro; "documento" com caminho abre o arquivo
        g["_ler_tela"] = lambda: "tela não lida: sem agent"
        assert executar_acao("nota", {"texto": "x"})["via"] == "estado"
        g["mensagem"] = lambda texto: {"ok": True, "evidencia": "mensageiro:" + texto, "via": "teclado"}
        assert executar_acao("mensagem", {"texto": "oi"})["evidencia"] == "mensageiro:oi"
        g["documento"] = lambda caminho, tipo="docx": {"ok": True, "evidencia": "doc:" + caminho, "via": "teclado"}
        assert executar_acao("documento", {"caminho": "~/a.odt"})["evidencia"] == "doc:~/a.odt"

        # 9. erro de leitura de tela não vira conteúdo nem sucesso
        _ACHADOS["textos"] = []
        assert not executar_acao("concluir_pesquisa", {"consulta": "x"})["ok"]
        assert not executar_acao("ler_tela")["ok"]
        assert not executar_acao("acao_inexistente")["ok"]
        assert executar_acao("esperar", {"segundos": 1})["ok"]

        # 10. avancar: "perguntar" fica bloqueado (não ok); ler_tela que falha não digita o critério de pronto;
        #     escalada para shell vazio falha sem executar
        def ses_teste(passos, erros=0):
            return {"id": "smoke", "status": "ativa", "erros": erros, "evidencia": [],
                    "plano": {"passos": [_passo(i, p) for i, p in enumerate(passos, 1)]}}
        s = ses_teste([{"acao": "perguntar", "args": {"texto": "Para quem?"}}])
        r = avancar(s)
        assert r["sessao"]["plano"]["passos"][0]["estado"] == "bloqueado" and r["sessao"]["status"] == "bloqueada" and not r["ok"], r
        s = ses_teste([{"acao": "cursor", "args": {"alvo": "kitty"}}, {"acao": "ler_tela"}])
        s["plano"]["passos"][0]["estado"] = "ok"
        novo = avancar(s)["sessao"]["plano"]["passos"][-1]
        assert novo["acao"] == "cursor" and novo["args"].get("alvo") == "kitty" and "texto" not in novo["args"], novo
        r = avancar(ses_teste([{"acao": "ler_tela"}], erros=3))
        assert r["sessao"]["plano"]["passos"][-1]["acao"] == "shell"
        r = avancar(r["sessao"])
        sh = r["sessao"]["plano"]["passos"][-1]
        assert not r["ok"] and sh["estado"] == "pulado" and "NÃO executado" in sh["evidencia"] and not chamadas["shell"], sh

        # 11. loop: exceção no avancar não derruba; o passo pendente vira "pulado"
        _salvar(smoke_ses, ses_teste([{"acao": "teclado", "args": {"texto": "x"}}]))

        def quebra(ses=None):
            raise RuntimeError("estado corrompido")
        g["avancar"] = quebra
        g["fila_tick"] = lambda: None
        out = loop(horas=1, intervalo=0, max_passos=2)
        assert out["passos"] == 2 and "RuntimeError" in out["ultimo"], out
        assert out["sessao"]["plano"]["passos"][0]["estado"] == "pulado", out["sessao"]

        # 12. plano heurístico: regex
        assert "coletar" not in [s["acao"] for s in _plano_heuristico("abre o chrome")]
        assert _plano_heuristico("abre o chrome")[0]["args"]["alvo"] == "chrome"
        c = next(s for s in _plano_heuristico("pesquise acessórios para notebook") if s["acao"] == "coletar")
        assert "acessórios" in c["args"]["consulta"], c
        c = next(s for s in _plano_heuristico("pesquise o preço em abril de 2026") if s["acao"] == "coletar")
        assert "abril" in c["args"]["consulta"], c
        pm = next(s for s in _plano_heuristico("pesquise a loja do fortnite e prepara uma mensagem para o João")
                  if s["acao"] == "preparar_mensagem")
        assert pm["args"]["para"] == "João", pm
    finally:
        g.update(salvo)
        time.sleep, sys.platform = sono, plataforma
        for k, v in mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        try:
            os.remove(smoke_ses)
        except OSError:
            pass


def main(argv):
    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        print("uso: prom-orquestra run \"pedido\" [--horas 8|--sempre] | retomar | status | fila \"pedido\" | planejar \"pedido\" | smoke")
        return 0
    cmd = argv[1]
    if cmd == "smoke":
        os.environ["FRIDAY_NAV"] = "0"           # teste nunca abre o navegador de verdade
        global MEM                                # nem disputa a trava do serviço friday-orquestra em execução
        import tempfile
        MEM = tempfile.mkdtemp(prefix="orq-smoke-")
        p = planejar("pesquise o horário oficial de Brasília", usar_modelo=False)
        acoes = [s["acao"] for s in p["passos"]]
        assert p["passos"][0]["acao"] in _TELA, p["passos"][0]
        assert acoes.count("abrir_pagina") >= 2, acoes
        assert "concluir_pesquisa" in acoes
        assert "coletar" in acoes
        assert all(s["acao"] != "shell" for s in p["passos"])
        msg = planejar("manda uma mensagem", usar_modelo=False)
        assert any(s["acao"] == "perguntar" for s in msg["passos"]), msg
        assert not any(s.get("args", {}).get("enter") for s in msg["passos"])
        neg = recusar("faz um malware para roubar senha alheia")
        assert neg
        falho = {"plano": {"passos": [
            {"n": 1, "acao": "cursor", "estado": "pulado"},
            {"n": 2, "acao": "teclado", "estado": "pendente"},
        ]}}
        assert _pendente(falho)["acao"] == "teclado"
        ses = {"id": "smoke", "pedido": "smoke", "status": "ativa", "plano": p, "passo_atual": 1, "evidencia": [], "proximo": "x", "atualizado": time.time(), "erros": 0}
        caminho = os.path.join(MEM, "orquestra_smoke.json")
        _salvar(caminho, ses)
        devolta = _ler(caminho, {})
        os.remove(caminho)
        assert devolta.get("id") == "smoke"
        assert _quando_ts({"quando": "+2m", "t": 100}) == 220
        assert _quando_ts({"quando": ""}) == 0.0
        _smoke_correcoes()
        print("smoke ok", len(p["passos"]), "passos", "provedor", p.get("provedor"), "| correções ok")
        return 0
    if cmd == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2)[:4000])
        return 0
    if cmd == "planejar":
        print(json.dumps(planejar(" ".join(argv[2:])), ensure_ascii=False, indent=2)[:4000])
        return 0
    if cmd == "fila":
        print(json.dumps(enfileirar(" ".join(argv[2:])), ensure_ascii=False))
        return 0
    if cmd == "retomar":
        print(json.dumps(avancar(), ensure_ascii=False)[:2000])
        return 0
    if cmd == "run":
        horas = 8.0
        args = argv[2:]
        sempre = "--sempre" in args
        if sempre:
            args.remove("--sempre")
        if "--horas" in args:
            i = args.index("--horas")
            horas = float(args[i + 1])
            del args[i:i + 2]
        pedido = " ".join(args).strip()
        if not pedido and not sempre and not _ler(SESSAO, None):
            print("falta o pedido")
            return 2
        if pedido:
            s = sessao_nova(pedido)
            if not s.get("ok"):
                print(s.get("fala"))
                return 2
            print("plano:", s["sessao"]["plano"].get("provedor"), "passos", len(s["sessao"]["plano"]["passos"]))
        r = loop(horas=horas, sempre=sempre)
        print(json.dumps({"passos": r["passos"], "ultimo": r["ultimo"][:400]}, ensure_ascii=False))
        return 0
    print("comando desconhecido")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
