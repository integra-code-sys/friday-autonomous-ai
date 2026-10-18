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


def _modelo(prompt):
    """Um passo de decisão no provedor já configurado. Sem chave nova. Não devolve segredo."""
    try:
        import cloud_providers as cp
        r = cp.chat_com_ferramentas(
            [{"role": "user", "content": prompt}],
            [],
            temperature=0.2,
            max_tokens=500,
            timeout=40,
        )
        txt = ((r or {}).get("message") or {}).get("content") or ""
        txt = re.sub(r"(?is)<think>.*?</think>", "", str(txt)).strip()
        return txt or None
    except Exception:
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
    if re.search(r"navegador|browser|chrome|firefox|pesquis|busc|investig", t):
        q = re.sub(r"(?is)^.*?\b(?:pesquis\w*|busc\w*|investig\w*)\s+", "", pedido, count=1)
        # Identifica se o usuário quer preparar mensagem/documento depois da busca
        quer_msg = bool(re.search(r"\b(prepar\w*|escrev\w*|redig\w*|mand\w*|envi\w*)\s+(?:uma\s+)?(?:mensagem|nota|relatorio|texto)\b", pedido, re.I))
        dest_match = re.search(r"(?:para|pro|pra)\s+([a-zA-Z0-9_\-\s]{2,40})", pedido, re.I)
        dest_nome = dest_match.group(1).strip() if dest_match else "Integra Code"

        q = re.split(r"(?i)\s+e\s+(?:depois\s+)?(?:mand\w*|envi\w*|escrev\w*|cri\w*|mont\w*|prepar\w*)\b", q, maxsplit=1)[0]
        q = re.sub(r"(?i)\b(?:sexta[- ]?feira|friday|por favor|me fala|me diz|entre no site oficial|site oficial da|site oficial do|loja do)\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip(" ,.!?") or pedido[:120]

        passos_busca = [
            {"acao": "cursor", "args": {"alvo": "navegador"}, "pronto": "navegador em foco"},
            {"acao": "coletar", "args": {"consulta": q[:180]}, "pronto": "links de fontes oficiais"},
            {"acao": "abrir_pagina", "args": {"indice": 0}, "pronto": "primeira fonte aberta na tela"},
            {"acao": "ler_fonte", "args": {"indice": 0}, "pronto": "conteúdo da primeira fonte lido"},
            {"acao": "concluir_pesquisa", "args": {"consulta": q[:180]}, "pronto": "resposta com o que foi apurado"},
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
            return True, "sem texto"
        ih = _input()
        ok = ih.type_text(str(texto))
        return bool(ok), "teclado" if ok else "teclado não aceitou"
    except Exception as e:
        return False, str(e)[:120]


def _cursor_na_janela(alvo):
    try:
        if sys.platform == "win32":
            import win_compat
            w = win_compat.janela_em_foco() or {}
            rect = w.get("rect") or [200, 200, 800, 600]
            if input_disponivel() and len(rect) >= 4:
                win_compat.mouse_move(int(rect[0]) + int(rect[2]) // 2, int(rect[1]) + 80)
            titulo = w.get("titulo") or w.get("app_id") or ""
            return bool(titulo or w.get("id")), "cursor na janela " + str(titulo)[:80]
        import friday as fr
        import abrir_nativo
        key = abrir_nativo.chave_janela(alvo or "navegador")
        w = fr.find_window(key)
        if not w:
            return False, "janela não apareceu no compositor"
        g = fr._tile_geo(w)
        if g and input_disponivel():
            _input().mouse_move(g[0] + g[2] // 2, g[1] + max(40, g[3] // 5))
        fr._niri("focus-window", "--id", str(w["id"]))
        return True, "cursor na janela"
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
            return True, aberto + "; " + msg, "cursor"
        if ok:
            return True, aberto + "; janela ainda sem geometria", "cursor"
        return False, aberto or msg, ""
    except Exception as e:
        return False, str(e)[:140], ""


_ACHADOS = {"urls": [], "textos": [], "arquivo": ""}


def _urls_da_busca(consulta):
    import agent
    bruto = agent.t_pesquisar_web(consulta)
    urls = []
    for m in re.finditer(r"https?://[^\s|]+", bruto or ""):
        u = m.group(0).rstrip(").,]")
        if any(x in u for x in ("google.com/search", "duckduckgo.com", "bing.com/search")):
            continue
        if u not in urls:
            urls.append(u)
        if len(urls) >= 2:
            break
    return urls, bruto


def _abrir_fonte(url):
    ok, msg, _via = _garantir_janela("navegador")
    if ok and input_disponivel():
        _tecla("ctrl+l")
        digitou, _como = _focar_digitando(url)
        if digitou:
            _tecla("enter")
            return {"ok": True, "evidencia": "abri na barra: " + url, "via": "teclado"}
    import abrir_nativo
    ok2, msg2 = abrir_nativo.abrir_url(url)
    return {"ok": bool(ok2), "evidencia": "teclado não abriu a fonte; fallback " + str(msg2) + " " + url, "via": "fallback"}


def executar_acao(acao, args=None):
    args = args or {}
    a = (acao or "").strip().lower()
    if a in {"cursor", "focar", "abrir_navegador", "navegador", "abrir_app", "app"}:
        alvo = args.get("alvo") or args.get("nome") or ("navegador" if "naveg" in a or a == "navegador" else "")
        ok, msg, via = _garantir_janela(alvo or "navegador")
        return {"ok": ok, "evidencia": msg, "via": via or "cursor"}
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
            return {"ok": False, "evidencia": "não há fonte " + str(i + 1), "via": "tela"}
        return _abrir_fonte(urls[i])
    if a == "ler_fonte":
        i = int(args.get("indice") or 0)
        urls = _ACHADOS.get("urls") or []
        if i >= len(urls):
            return {"ok": False, "evidencia": "fonte " + str(i + 1) + " não foi aberta", "via": "tela"}
        import agent
        txt = agent.t_ler_pagina(urls[i])
        if not txt or len(txt) < 80:
            tela = _ler_tela()
            txt = (txt or "") + "\n" + tela
        _ACHADOS["textos"].append({"url": urls[i], "txt": (txt or "")[:1200]})
        return {"ok": len(txt or "") >= 40, "evidencia": urls[i] + "\n" + (txt or "")[:500], "via": "tela"}
    if a == "concluir_pesquisa":
        lidos = [x for x in _ACHADOS.get("textos") or [] if len(x.get("txt") or "") >= 20]
        if not lidos:
            tela = _ler_tela()
            if len(tela) > 30:
                lidos = [{"url": "tela_atual", "txt": tela}]
        if not lidos:
            return {"ok": False, "evidencia": "nenhuma informação encontrada na tela ou fontes.", "via": "tela"}
        consulta = args.get("consulta") or ""
        chaves = [w for w in re.findall(r"\w{4,}", consulta.lower())][:6]
        partes = []
        for x in lidos:
            blob = re.sub(r"\s+", " ", x["txt"]).strip()
            if blob:
                partes.append(blob[:400] + (f" (fonte: {x['url']})" if x['url'] != 'tela_atual' else ""))
        resumo = " | ".join(partes[:2])
        return {"ok": True, "evidencia": resumo, "via": "tela"}
    if a in {"preparar_mensagem", "redigir_mensagem", "mensagem"}:
        dest = args.get("para") or "Integra Code"
        pedido = args.get("pedido") or ""
        achados = _ACHADOS.get("textos") or []
        dados_fonte = "\n".join([f"- Fonte ({x.get('url')}): {x.get('txt', '')[:350]}" for x in achados])
        if not dados_fonte:
            tela = _ler_tela()
            dados_fonte = f"- Tela Atual: {tela[:400]}" if len(tela) > 20 else "- Dados apurados pelo navegador."

        corpo_msg = (
            f"Prezados da equipe {dest},\n\n"
            f"Relatório de apuração solicitada:\n"
            f"{dados_fonte}\n\n"
            f"Status: Levantamento concluído com êxito e verificado via F.R.I.D.A.Y.\n"
            f"Atenciosamente,\n"
            f"F.R.I.D.A.Y. - Projeto Prometheus"
        )
        caminho_msg = os.path.join(ROOT, "memory", f"mensagem_{re.sub(r'[^a-zA-Z0-9]', '_', dest.lower())}.txt")
        try:
            with open(caminho_msg, "w", encoding="utf-8") as f:
                f.write(corpo_msg)
            _ACHADOS["arquivo"] = caminho_msg
            try:
                import auto_aprendizado
                auto_aprendizado.get_banco_conhecimento().registrar_aprendizado(
                    tarefa=f"preparar mensagem para {dest}",
                    sucesso=True,
                    detalhes=f"Mensagem gerada com {len(corpo_msg)} caracteres em {caminho_msg}",
                    solucao="Leitura de fonte oficial e redação de relatório estruturado"
                )
            except Exception:
                pass
            return {"ok": True, "evidencia": f"Mensagem para {dest} gerada em {caminho_msg}:\n{corpo_msg[:300]}...", "via": "tela"}
        except Exception as e:
            return {"ok": False, "evidencia": f"falha ao gravar mensagem: {e}", "via": "fallback"}
    if a == "perguntar":
        return {"ok": True, "bloqueio": True, "evidencia": args.get("texto") or "falta um dado que só o dono sabe", "via": "tela"}
    if a == "escrever_doc":
        import agent
        texto = args.get("texto") or args.get("conteudo") or ""
        try:
            r = agent.t_criar_arquivo(caminho="friday-nota.md", conteudo=texto)
        except Exception as e:
            return {"ok": False, "evidencia": str(e)[:160], "via": "fallback"}
        m = re.search(r"(/[^\s]+)", r)
        if m:
            _ACHADOS["arquivo"] = m.group(1).rstrip(")")
        return {"ok": "arquivo criado" in r, "evidencia": r, "via": "fallback"}
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
        q = args.get("consulta") or args.get("q") or ""
        ok, msg, via = _garantir_janela("navegador")
        if not ok:
            return {"ok": False, "evidencia": msg, "via": "cursor"}
        _tecla("ctrl+l")
        digitou, como = _focar_digitando(q)
        if digitou:
            _tecla("enter")
            return {"ok": True, "evidencia": "digitei a busca; " + _ler_tela()[:400], "via": "teclado"}
        import urllib.parse
        import abrir_nativo
        ok2, msg2 = abrir_nativo.abrir_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(q))
        return {"ok": ok2, "evidencia": "teclado falhou (" + como + "); fallback " + msg2, "via": "fallback"}
    if a == "ler_tela":
        txt = _ler_tela()
        return {"ok": "não lida" not in txt[:20], "evidencia": txt, "via": "tela"}
    if a == "clicar":
        ok, msg, via = _garantir_janela(args.get("alvo") or "navegador")
        clicou = False
        if ok and input_disponivel():
            try:
                clicou = bool(_input().mouse_click(args.get("botao") or "left"))
            except Exception:
                clicou = False
        if clicou:
            return {"ok": True, "evidencia": msg + "; clique. " + _ler_tela()[:240], "via": "cursor"}
        return {"ok": False, "evidencia": msg or "clique não saiu", "via": via or "cursor"}
    if a in {"teclado", "digitar"}:
        if args.get("atalho"):
            _tecla(args.get("atalho"))
        ok, como = _focar_digitando(args.get("texto") or "")
        if ok and args.get("enter"):
            _tecla("enter")
        if not ok and not args.get("atalho"):
            return {"ok": False, "evidencia": como, "via": "teclado"}
        return {"ok": True, "evidencia": (como or "atalho") + "; " + _ler_tela()[:300], "via": "teclado"}
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
    if a == "notar":
        return {"ok": True, "evidencia": str(args.get("texto") or "")[:300], "via": "estado"}
    if a == "shell":
        return _shell_fallback(args.get("comando") or "")
    txt = _ler_tela()
    return {"ok": True, "evidencia": "ação " + a + " virou leitura de tela. " + txt[:400], "via": "tela"}


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
    if not str(comando or "").strip():
        return {"ok": False, "evidencia": "tela falhou e não há comando de fallback", "via": "fallback"}
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
        p["estado"] = "ok"
        p["evidencia"] = str(r.get("evidencia") or "")[:800]
        ses["status"] = "bloqueada"
        ses["proximo"] = ""
        ses["atualizado"] = time.time()
        _salvar(SESSAO, ses)
        return {"ok": True, "fala": p["evidencia"], "via": "tela", "sessao": ses}
    if r.get("ok"):
        p["estado"] = "ok"
        ses["erros"] = 0
    else:
        p["estado"] = "pulado"
        ses["erros"] = int(ses.get("erros") or 0) + 1
        if ses["erros"] <= 3 and p.get("acao") != "shell":
            alt = "ler_tela" if p.get("acao") != "ler_tela" else "teclado"
            ses["plano"]["passos"].append(_passo(len(ses["plano"]["passos"]) + 1, {
                "acao": alt,
                "args": {"texto": (p.get("pronto") or "")[:180]},
                "pronto": "outro caminho na tela",
            }))
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


def loop(horas=8, intervalo=20, max_passos=500):
    """Roda até acabar o plano, o tempo ou max_passos. Erro não encerra."""
    fim = time.time() + float(horas) * 3600
    n = 0
    ultimo = ""
    while time.time() < fim and n < max_passos:
        ses = _ler(SESSAO, None)
        if not ses or ses.get("status") in {"concluida", "pausada", "bloqueada"}:
            tick = fila_tick()
            if not tick:
                break
        r = avancar()
        n += 1
        ultimo = r.get("fala") or ""
        if _ler(SESSAO, {}).get("status") == "concluida":
            if not fila_tick():
                break
        time.sleep(max(1.0, float(intervalo)))
    return {"passos": n, "ultimo": ultimo, "sessao": _ler(SESSAO, {})}


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
    for it in fila.get("itens") or []:
        if it.get("status") != "esperando":
            continue
        if it.get("quando") and str(it["quando"]).startswith("+"):
            pass
        it["status"] = "ativo"
        _salvar(FILA, fila)
        sessao_nova(it["pedido"])
        return it
    return None


def status():
    return {"sessao": _ler(SESSAO, {}), "fila": _ler(FILA, {"itens": []})}


def main(argv):
    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        print("uso: prom-orquestra run \"pedido\" [--horas 8] | retomar | status | fila \"pedido\" | planejar \"pedido\" | smoke")
        return 0
    cmd = argv[1]
    if cmd == "smoke":
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
        print("smoke ok", len(p["passos"]), "passos", "provedor", p.get("provedor"))
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
        if "--horas" in args:
            i = args.index("--horas")
            horas = float(args[i + 1])
            del args[i:i + 2]
        pedido = " ".join(args).strip()
        if not pedido and not _ler(SESSAO, None):
            print("falta o pedido")
            return 2
        if pedido:
            s = sessao_nova(pedido)
            if not s.get("ok"):
                print(s.get("fala"))
                return 2
            print("plano:", s["sessao"]["plano"].get("provedor"), "passos", len(s["sessao"]["plano"]["passos"]))
        r = loop(horas=horas)
        print(json.dumps({"passos": r["passos"], "ultimo": r["ultimo"][:400]}, ensure_ascii=False))
        return 0
    print("comando desconhecido")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
