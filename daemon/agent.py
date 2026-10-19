"""Agente de FERRAMENTAS da F.R.I.D.A.Y. (100% local: o modelo é o gemma3 via Ollama).
Laço ReAct curto: o modelo escolhe uma ferramenta, vê o resultado e decide o próximo passo, até responder.
Cada execução é registrada (memory/acoes.jsonl) e analisada: falhas viram LIÇÕES (memory/licoes.json) que entram no prompt.
Ferramentas: pesquisa web, leitura de páginas/arquivos, resumos, ONLYOFFICE (abrir/criar docx/xlsx/pptx), notas, e qualquer ação
do friday.run_action (abrir app, janelas, sistema, agenda, e-mail, holograma, tarefa manual com cursor, programar)."""
import difflib
import threading
import html
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MEM = os.path.join(HERE, "..", "memory")
ACOES = os.path.join(MEM, "acoes.jsonl")
LICOES = os.path.join(MEM, "licoes.json")
DOCS = os.path.expanduser("~/Documentos/Friday")
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
MAX_STEPS = 24
CANCEL = threading.Event()          # "pare/desisti": interrompe o laço entre um passo e outro
PROG = {"pesquisar_web": "Pesquisando na web.", "ler_pagina": "Lendo a página.", "onlyoffice_criar": "Criando o documento.",
        "pesquisa_para_documento": "Pesquisando e montando o documento.", "abrir_app": "Abrindo o aplicativo.", "consultar_ia": "Vou consultar o ChatGPT para isso.", "ver_tela": "Olhando a tela.", "clicar_elemento": "Clicando.", "apontar": "Apontando.", "clicar_texto": "Clicando.", "pular_anuncio": "Procurando o botão de pular anúncio.",
        "abrir_site": "Abrindo o site no navegador.", "resumir": "Resumindo.", "onlyoffice_abrir": "Abrindo no ONLYOFFICE."}


def _say(cb, texto):
    """narra o que está fazendo SEM bloquear: a fala corre em paralelo à execução."""
    try:
        if cb and texto:
            cb(texto)
    except Exception:
        pass
EFEITO = {"onlyoffice_criar", "onlyoffice_abrir", "nota", "pesquisa_para_documento", "pular_anuncio", "zap_enviar"}   # abrir_site/clicar/digitar/tecla não encerram: tarefas visuais têm vários passos
# F6: abrir_app e acao SAÍRAM: marcavam "feito" e mandavam dar final na hora ("abra o ZapZap e mande X" parava no abrir_app)

# o que dispara o modo agente (pedidos que exigem mais de uma ferramenta/etapa)
# (mídia saiu daqui: "coloque/toque/música/YouTube" agora passa pelo think(), que decide entre play no que já está na tela ou tarefa nova)
GATILHO = re.compile(r"\b(pesquis\w+|busc\w+|procur\w+|resum\w+|analis\w+|compar\w+|document\w*|planilh\w+|apresenta[çc][ãa]o|slides?|"
                     r"only\s*office|escrev\w+|redij\w+|crie um|cri[ae] (um|uma)|monte|prepar\w+|leia|ler|not[ií]cias?|o que (é|significa)|"
                     r"fa[çc]a (um|uma)|ger[ae]|gerar|relat[óo]rio|artigo|tabela|docx|xlsx|pptx|"
                     r"encaminh\w+|repass\w+|inform\w+|"
                     r"explique|me explica|quem (é|foi)|quanto (custa|vale)|cota[çc][ãa]o|previs[ãa]o do tempo|aprendeu|autoan[aá]lise)\b", re.I)


def wants_agent(text):
    t = text or ""
    if GATILHO.search(t):
        return True
    if re.search(r"\b(?:mand\w+|envi\w+|encaminh\w+|repass\w+|prepar\w+|escrev\w+|redij\w+)\b.*?\b(?:para|pra|pro)\b", t, re.I):
        return True
    if re.search(r"\b(?:zap|whatsapp|wpp)\b.*?\b(?:mand\w+|envi\w+|encaminh\w+|repass\w+|prepar\w+|escrev\w+)\b", t, re.I):
        return True
    return False


# ------------------------------------------------------------------ memória de ações e lições
def _read_json(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def licoes():
    return _read_json(LICOES, [])


def _add_licao(txt):
    txt = txt.strip()[:200]
    if len(txt) < 12:
        return
    L = licoes()
    if any(difflib.SequenceMatcher(None, txt.lower(), x["txt"].lower()).ratio() > 0.75 for x in L):
        return
    L.append({"txt": txt, "t": time.time()})
    json.dump(L[-30:], open(LICOES, "w"), ensure_ascii=False)


def _log(tool, args, ok, dur, resultado):
    try:
        with open(ACOES, "a") as f:
            f.write(json.dumps({"t": time.time(), "tool": tool, "args": str(args)[:200], "ok": ok, "dur": round(dur, 2),
                                "res": str(resultado)[:200]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ ferramentas
def _http(url, timeout=15, limit=400000):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or re.match(r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|0\.|169\.254\.)", p.hostname or ""):
        raise ValueError("endereço não permitido")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(limit)
            enc = r.headers.get_content_charset() or "utf-8"
        return raw.decode(enc, errors="replace")
    except Exception:
        # Fallback resiliente via curl com headers modernos de navegador
        try:
            r_curl = subprocess.run(["curl", "-sL", "-A", UA, "--max-time", str(timeout), url], capture_output=True, text=True, timeout=timeout + 2)
            if r_curl.stdout and len(r_curl.stdout.strip()) > 50:
                return r_curl.stdout[:limit]
        except Exception:
            pass
        raise


def _texto(htm):
    htm = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|aside|iframe)[^>]*>.*?</\1>", " ", htm)
    htm = re.sub(r"(?is)<(div|section|aside)[^>]+(?:class|id)=[\"'][^\"']*\b(ad|ads|advert|banner|cookie|consent|popup|modal|overlay|sponsor|commercial|promo)\b[^\"']*[\"'][^>]*>.*?</\1>", " ", htm)
    htm = re.sub(r"(?s)<[^>]+>", " ", htm)
    return re.sub(r"\s+", " ", html.unescape(htm)).strip()


def _bing_url(href):
    """o Bing embrulha o link: ...&u=a1<base64url do destino>."""
    href = html.unescape(href)
    m = re.search(r"[?&]u=a1([^&]+)", href)
    if m:
        import base64
        try:
            b = m.group(1); b += "=" * (-len(b) % 4)
            return base64.urlsafe_b64decode(b).decode()
        except Exception:
            pass
    return html.unescape(href)


_STOP = set("o a os as um uma de do da dos das e é que quem como qual quais me te se em no na nos nas por para pra com sem sobre mais menos "
            "resuma resumo resumir pesquise pesquisar busque buscar procure explique significa significado quero saber favor".split())


def _ddg_url(href):
    href = html.unescape(href)
    m = re.search(r"[?&]uddg=([^&]+)", href)
    if m:
        return urllib.parse.unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def t_pesquisar_web(consulta="", **kw):
    """Pesquisa na web via DuckDuckGo HTML + Bing + Wikipédia pt."""
    q = str(consulta).strip()
    if not q:
        raise ValueError("faltou a consulta")
    chaves = [w for w in re.findall(r"\w+", q.lower()) if w not in _STOP and len(w) > 2]
    ini = re.sub(r"(?i)^\s*(?:(?:" + "|".join(sorted(_STOP | {"foi", "era", "seria", "sao", "são"})) + r")\b[\s,]*)+", "", q).strip(" ?.!") or q
    consultas = []
    for c_ in ([ini, q, " ".join(chaves[:6])] if chaves else [q]):
        if c_ and c_ not in consultas:
            consultas.append(c_)
    for consulta_ in consultas:
        r = _pesquisar(consulta_, chaves)
        if r and not r.startswith("nenhum"):
            return r
    return "nenhum resultado relevante para: " + q


def _pesquisar(q, chaves=()):
    import unicodedata
    norm = lambda x: "".join(c for c in unicodedata.normalize("NFD", x.lower()) if unicodedata.category(c) != "Mn")
    itens = []
    # 1. DuckDuckGo HTML (alta precisão para produtos, lojas, termos compostos e buscas em múltiplos idiomas)
    try:
        htm_ddg = _http("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(q))
        for m in re.finditer(r'(?s)<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]*class="result__a"|$)', htm_ddg):
            sn = re.search(r'(?s)<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', m.group(3))
            u_real = _ddg_url(m.group(1))
            if "duckduckgo.com/y.js" in u_real or "/aclick?" in u_real:
                continue
            linha = f"- {_texto(m.group(2))[:95]} | {_texto(sn.group(1))[:210] if sn else ''} | {u_real[:120]}"
            if chaves and not any(norm(c) in norm(linha) for c in chaves):
                continue
            itens.append(linha)
            if len(itens) >= 5:
                break
    except Exception:
        pass
    # 2. Fallback: Bing HTML
    if len(itens) < 3:
        try:
            htm = _http("https://www.bing.com/search?q=" + urllib.parse.quote_plus(q) + "&setlang=pt-BR")
            for blk in re.findall(r'(?s)<li class="b_algo".*?</li>', htm)[:6]:
                m = re.search(r'(?s)<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', blk)
                if not m:
                    continue
                sn = re.search(r'(?s)<p[^>]*>(.*?)</p>', blk)
                linha = f"- {_texto(m.group(2))[:90]} | {_texto(sn.group(1))[:200] if sn else ''} | {_bing_url(m.group(1))[:110]}"
                if chaves and not any(norm(c) in norm(linha) for c in chaves):
                    continue
                if linha not in itens:
                    itens.append(linha)
                if len(itens) >= 5:
                    break
        except Exception:
            pass
    # 3. Complemento: Wikipédia PT
    if len(itens) < 5:
        try:
            js = json.loads(_http("https://pt.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=2&srsearch=" + urllib.parse.quote(q)))
            for r in js["query"]["search"]:
                itens.append(f"- [Wikipédia] {r['title']} | {_texto(r['snippet'])[:200]} | https://pt.wikipedia.org/wiki/{urllib.parse.quote(r['title'].replace(' ', '_'))}")
        except Exception:
            pass
    if not itens:
        return "nenhum resultado (sem internet ou busca bloqueada)"
    return "\n".join(itens[:6])


def t_ler_pagina(url="", **_):
    return _texto(_http(str(url)))[:3500]


def t_navegar_web(url="", objetivo="", profundidade=2, max_paginas=4, fr=None, **_):
    """Navegação adaptativa na web: visita páginas, segue links relevantes ao objetivo, extrai informações e sintetiza a resposta."""
    alvo = str(url or "").strip()
    obj = str(objetivo or "").strip()
    if not alvo and not obj:
        raise ValueError("informe url ou objetivo")
    if not alvo or not alvo.startswith(("http://", "https://")):
        q = alvo or obj
        achados = t_pesquisar_web(consulta=q)
        links_iniciais = re.findall(r"\|\s*(https?://\S+)", achados)
        if not links_iniciais:
            return f"Não encontrei links iniciais para '{q}'."
        alvo = links_iniciais[0]
        outros_links = links_iniciais[1:3]
    else:
        outros_links = []

    visitados = set()
    fila = [alvo] + outros_links
    conteudos = []
    palavras_obj = set(re.findall(r"\w{3,}", obj.lower()))

    while fila and len(visitados) < max_paginas:
        u = fila.pop(0)
        if u in visitados:
            continue
        visitados.add(u)
        try:
            htm = _http(u, timeout=12)
            titulo = ""
            m_tit = re.search(r"(?is)<title[^>]*>(.*?)</title>", htm)
            if m_tit:
                titulo = re.sub(r"\s+", " ", html.unescape(m_tit.group(1))).strip()

            txt = _texto(htm)
            trechos_relevantes = []
            if palavras_obj:
                paragrafos = [p.strip() for p in re.split(r"\n{2,}|\.\s+", txt) if len(p.strip()) > 30]
                for p in paragrafos:
                    p_low = p.lower()
                    pts = sum(1 for w in palavras_obj if w in p_low)
                    if pts >= 1:
                        trechos_relevantes.append((pts, p))
                trechos_relevantes.sort(key=lambda x: -x[0])
                resumo_pg = "\n".join(t for _, t in trechos_relevantes[:5]) or txt[:1200]
            else:
                resumo_pg = txt[:1500]

            conteudos.append(f"--- Fonte: {u} ({titulo}) ---\n{resumo_pg}")

            if profundidade > 1 and len(visitados) < max_paginas:
                links_pg = []
                for m_a in re.finditer(r"""(?is)<a\s+[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", htm):
                    href = m_a.group(1).strip()
                    rotulo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m_a.group(2))).strip()
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = urllib.parse.urljoin(u, href)
                    elif not href.startswith(("http://", "https://")):
                        continue
                    if re.search(r"\.(pdf|png|jpg|jpeg|gif|zip|tar|gz|exe|apk|dmg|mp4|mp3|svg)$", href, re.I):
                        continue
                    p_score = sum(1 for w in palavras_obj if w in rotulo.lower() or w in href.lower())
                    if p_score > 0 and href not in visitados and href not in fila:
                        links_pg.append((p_score, href))
                links_pg.sort(key=lambda x: -x[0])
                for _, h in links_pg[:2]:
                    if h not in fila:
                        fila.append(h)
        except Exception as e:
            conteudos.append(f"--- Falha ao acessar {u}: {e} ---")

    tudo = "\n\n".join(conteudos)
    if fr is not None and obj:
        resp = fr.llm(
            "Você é a F.R.I.D.A.Y. Você navegou pela web e reuniu informações para o chefe. "
            "Responda ao objetivo dele de forma direta, clara e precisa em português do Brasil (2 a 4 frases), citando os fatos encontrados.",
            f"Objetivo: {obj}\n\nMaterial coletado de {len(visitados)} páginas:\n{tudo[:6000]}",
            None, False, 350, 0.2, 90
        )
        if resp and resp.strip():
            return resp.strip()
    return tudo[:3500]


def t_tarefa_adaptativa(objetivo="", contexto="", fr=None, ops=None, **_):
    """Executa tarefas autônomas abertas/não pré-programadas: decompõe o objetivo em ações dinâmicas, executa e adapta se falhar."""
    obj = str(objetivo or "").strip()
    if not obj:
        raise ValueError("objetivo não informado")
    if fr is None:
        return "sem modelo para execução adaptativa"
    plano = fr.llm(
        "Você é o planejador adaptativo da F.R.I.D.A.Y. para tarefas não triviais no computador. "
        "Dado o objetivo do dono, descreva em JSON uma lista de no máximo 4 ações executáveis: "
        '{"passos":[{"acao":"terminal|pesquisar_web|navegar_web|ler_arquivo|criar_arquivo","param":"..."}],"explicacao":"curta"}',
        f"Objetivo: {obj}\nContexto: {contexto}",
        None, True, 350, 0.1, 60
    )
    if not isinstance(plano, dict) or not plano.get("passos"):
        return t_navegar_web(url="", objetivo=obj, fr=fr)

    resultados = []
    for p in plano.get("passos", [])[:4]:
        acao = str(p.get("acao", "")).strip()
        param = str(p.get("param", "")).strip()
        try:
            if acao == "terminal":
                res = t_terminal(comando=param, motivo=obj, fr=fr, ops=ops)
            elif acao == "pesquisar_web":
                res = t_pesquisar_web(consulta=param)
            elif acao == "navegar_web":
                res = t_navegar_web(url="", objetivo=param or obj, fr=fr)
            elif acao == "ler_arquivo":
                res = t_ler_arquivo(caminho=param)
            elif acao == "criar_arquivo":
                res = t_criar_arquivo(caminho=param, conteudo=contexto or obj)
            else:
                res = f"ação {acao} não suportada"
            resultados.append(f"[{acao}]: {str(res)[:600]}")
        except Exception as e_p:
            resultados.append(f"[{acao}] erro: {e_p}")

    sintese = fr.llm(
        "Você é a F.R.I.D.A.Y. Sintetize em 2 frases diretas o resultado da tarefa autônoma executada.",
        f"Objetivo: {obj}\nResultados:\n" + "\n".join(resultados),
        None, False, 200, 0.2, 45
    )
    return (sintese or "\n".join(resultados)).strip()



_BLOQ = re.compile(r"(\.env|\.pem|\.pfx|\.p12|\.key|id_rsa|secrets?|senha|password|\.kdbx|credenciais?)", re.I)


def t_ler_arquivo(caminho="", **_):
    p = os.path.realpath(os.path.expanduser(str(caminho)))
    if not p.startswith(os.path.expanduser("~")) or _BLOQ.search(p):
        raise ValueError("arquivo fora do permitido")
    if not os.path.isfile(p):
        raise FileNotFoundError("não existe: " + p)
    ext = p.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        return subprocess.run(["pdftotext", "-l", "6", p, "-"], capture_output=True, text=True, timeout=30).stdout[:5000]
    if ext == "docx":
        import docx
        return "\n".join(x.text for x in docx.Document(p).paragraphs)[:5000]
    if ext == "xlsx":
        import openpyxl
        ws = openpyxl.load_workbook(p, read_only=True, data_only=True).active
        return "\n".join(", ".join("" if c is None else str(c) for c in row) for row in ws.iter_rows(values_only=True, max_row=60))[:5000]
    return open(p, errors="replace").read(5000)


def t_resumir(texto="", fr=None, **_):
    out = fr.llm("Você resume textos em português do Brasil. Entregue 3 a 6 tópicos curtos e objetivos, sem inventar nada que não esteja no texto.",
                 str(texto)[:5500], None, False, 380, 0.2, 90)
    return (out or "não consegui resumir")[:900]


def t_onlyoffice_abrir(caminho="", **_):
    p = os.path.realpath(os.path.expanduser(str(caminho)))
    if not os.path.isfile(p):
        raise FileNotFoundError("não existe: " + p)
    subprocess.Popen(["setsid", "flatpak", "run", "org.onlyoffice.desktopeditors", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "abrindo no ONLYOFFICE: " + p


def _add_docx_inline(p, text, base_font="Calibri", base_size=None, base_color=None, default_bold=False):
    """Renderiza negrito (**texto**), itálico (*texto*), código (`texto`) e normal em runs do python-docx."""
    from docx.shared import Pt, RGBColor
    token_re = re.compile(r"(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")
    parts = token_re.split(text)
    for part in parts:
        if not part:
            continue
        bold = default_bold
        italic = False
        is_code = False
        content = part
        if part.startswith("***") and part.endswith("***") and len(part) >= 6:
            bold = True
            italic = True
            content = part[3:-3]
        elif part.startswith("**") and part.endswith("**") and len(part) >= 4:
            bold = True
            content = part[2:-2]
        elif part.startswith("*") and part.endswith("*") and len(part) >= 2:
            italic = True
            content = part[1:-1]
        elif part.startswith("`") and part.endswith("`") and len(part) >= 2:
            is_code = True
            content = part[1:-1]

        run = p.add_run(content)
        run.bold = bold
        run.italic = italic
        if is_code:
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(160, 40, 40)
        else:
            if base_font:
                run.font.name = base_font
            if base_size:
                run.font.size = base_size
            if base_color:
                run.font.color.rgb = base_color


def _add_docx_table(d, rows):
    """Cria uma tabela docx elegante a partir de linhas markdown (| col1 | col2 |)."""
    if not rows:
        return
    parsed_rows = []
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        if all(re.fullmatch(r"[-:\s]+", c) for c in cells if c):
            continue
        parsed_rows.append(cells)
    if not parsed_rows:
        return
    num_cols = max(len(r) for r in parsed_rows)
    from docx.shared import Pt, RGBColor
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    w_ns = nsdecls("w")
    tbl = d.add_table(rows=len(parsed_rows), cols=num_cols)
    tbl.style = "Table Grid"
    for row_idx, r_data in enumerate(parsed_rows):
        is_hdr = (row_idx == 0)
        row = tbl.rows[row_idx]
        for col_idx in range(num_cols):
            cell = row.cells[col_idx]
            val = r_data[col_idx] if col_idx < len(r_data) else ""
            tcPr = cell._element.get_or_add_tcPr()
            tcMar = parse_xml(f'<w:tcMar {w_ns}><w:top w:w="120" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/><w:left w:w="160" w:type="dxa"/><w:right w:w="160" w:type="dxa"/></w:tcMar>')
            tcPr.append(tcMar)
            if is_hdr:
                shd = parse_xml(f'<w:shd {w_ns} w:fill="1F497D"/>')
                tcPr.append(shd)
            elif row_idx % 2 == 1:
                shd = parse_xml(f'<w:shd {w_ns} w:fill="F5F8FA"/>')
                tcPr.append(shd)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            color = RGBColor(255, 255, 255) if is_hdr else RGBColor(40, 40, 40)
            _add_docx_inline(p, val, base_font="Calibri", base_size=Pt(10), base_color=color, default_bold=is_hdr)
    sp = d.add_paragraph()
    sp.paragraph_format.space_before = Pt(4)
    sp.paragraph_format.space_after = Pt(4)


def t_onlyoffice_criar(tipo="docx", nome="documento", conteudo="", **_):
    os.makedirs(DOCS, exist_ok=True)
    tipo = str(tipo).lower().strip(".")
    base = re.sub(r"[^\w\- ]", "", str(nome)).strip()[:50] or "documento"
    caminho = os.path.join(DOCS, f"{base}-{time.strftime('%H%M%S')}.{tipo}")
    linhas = [l.rstrip() for l in str(conteudo).splitlines()]
    if tipo == "docx":
        import docx
        from docx.shared import Inches, Pt, RGBColor
        d = docx.Document()
        for sec in d.sections:
            sec.top_margin = Inches(1)
            sec.bottom_margin = Inches(1)
            sec.left_margin = Inches(1)
            sec.right_margin = Inches(1)

        # Cabeçalho do documento
        titulo_doc = d.add_heading(base, 0)
        titulo_doc.paragraph_format.space_after = Pt(12)

        i = 0
        n_lin = len(linhas)
        while i < n_lin:
            l = linhas[i]
            # Bloco de tabela markdown (| col1 | col2 |)
            if l.strip().startswith("|") and l.strip().endswith("|") and "|" in l.strip()[1:-1]:
                t_linhas = []
                while i < n_lin and linhas[i].strip().startswith("|") and linhas[i].strip().endswith("|"):
                    t_linhas.append(linhas[i])
                    i += 1
                _add_docx_table(d, t_linhas)
                continue

            if l.startswith("# "):
                h = d.add_heading(l[2:], 1)
                h.paragraph_format.space_before = Pt(12)
                h.paragraph_format.space_after = Pt(4)
            elif l.startswith("## "):
                h = d.add_heading(l[3:], 2)
                h.paragraph_format.space_before = Pt(10)
                h.paragraph_format.space_after = Pt(3)
            elif l.startswith("### "):
                h = d.add_heading(l[4:], 3)
                h.paragraph_format.space_before = Pt(8)
                h.paragraph_format.space_after = Pt(2)
            elif l.startswith("#### "):
                h = d.add_heading(l[5:], 4)
                h.paragraph_format.space_before = Pt(6)
                h.paragraph_format.space_after = Pt(2)
            elif l.startswith(("- ", "* ")):
                p = d.add_paragraph(style="List Bullet")
                p.paragraph_format.space_after = Pt(2)
                _add_docx_inline(p, l[2:], base_font="Calibri", base_size=Pt(11))
            elif re.match(r"^\d+\.\s+", l):
                p = d.add_paragraph(style="List Number")
                p.paragraph_format.space_after = Pt(2)
                _add_docx_inline(p, re.sub(r"^\d+\.\s+", "", l), base_font="Calibri", base_size=Pt(11))
            elif l.startswith("> "):
                p = d.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.4)
                p.paragraph_format.space_after = Pt(4)
                _add_docx_inline(p, l[2:], base_font="Calibri", base_size=Pt(10.5), base_color=RGBColor(80, 80, 80))
            elif l.strip():
                p = d.add_paragraph()
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.line_spacing = 1.15
                _add_docx_inline(p, l, base_font="Calibri", base_size=Pt(11))
            i += 1
        d.save(caminho)
    elif tipo == "xlsx":
        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = base[:30]
        for l in linhas:
            if l.strip():
                ws.append([c.strip() for c in re.split(r"[;,\t|]", l.strip().strip("|"))])
        wb.save(caminho)
    elif tipo == "pptx":
        from pptx import Presentation
        pr = Presentation()
        blocos, atual = [], []
        for l in linhas:
            if (l.startswith("# ") or not l.strip()) and atual and l.startswith("# "):
                blocos.append(atual); atual = []
            if l.strip():
                atual.append(l)
        if atual:
            blocos.append(atual)
        for b in blocos or [[base]]:
            sl = pr.slides.add_slide(pr.slide_layouts[1])
            sl.shapes.title.text = b[0].lstrip("# ")[:80]
            sl.placeholders[1].text = "\n".join(x.lstrip("-* ") for x in b[1:])[:900]
        pr.save(caminho)
    else:
        raise ValueError("tipo deve ser docx, xlsx ou pptx")
    subprocess.Popen(["setsid", "flatpak", "run", "org.onlyoffice.desktopeditors", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "criado e aberto no ONLYOFFICE: " + caminho


def t_abrir_app(nome="", fr=None, ops=None, **_):
    """abre um app COMO HUMANO: cursor vai ao canto inferior esquerdo (launcher), digita o nome e Enter; a janela ocupa a tela."""
    ok, msg = fr.focus_or_launch(str(nome), ops)
    if not ok:
        raise RuntimeError(msg)
    return msg


def t_listar_apps(ops=None, **_):
    d = _read_json(os.path.join(MEM, "mapa_pc.json"), {})
    apps = d.get("apps") or d.get("aplicativos") or {}
    nomes = sorted({(a.get("nome") if isinstance(a, dict) else str(a)) for a in (apps.values() if isinstance(apps, dict) else apps)} - {None})
    return ", ".join(nomes)[:1500] or "mapa de apps vazio (rode `prom pc refresh`)"


def _limpar_termo_busca(q):
    q = str(q or "").strip()
    q = re.sub(r"(?i)^\s*(?:sexta[- ]?feira|friday)[,:\s]*", "", q)
    q = re.sub(r"(?i)^\s*(?:por\s+favor[,:\s]*)?(?:apenas\s+|s[óo]\s+)?(?:abr[ae](?:\s+o\s+navegador|\s+o\s+chromium|\s+uma\s+nova\s+aba|\s+nova\s+aba)?\s*(?:e\s+)?)?(?:pesquis\w*|busc\w*|procur\w*)\s*(?:por|sobre|pelo|pela|pelos|pelas)?\s*", "", q)
    q = re.sub(r"(?i)\b(?:em\s+uma\s+nova\s+aba|numa\s+nova\s+aba|na\s+nova\s+aba|em\s+nova\s+aba|no\s+navegador|pelo\s+navegador|no\s+chromium|no\s+google)\b", " ", q)
    q = re.sub(r"(?i)\s+e\s+(?:depois\s+)?(?:prepar\w*|escrev\w*|redij\w*|envi\w*|mand\w*|encaminh\w*|repass\w*)\b.*$", "", q)
    q = re.sub(r"(?i)\s*(?:e\s+)?(?:me\s+)?(?:mostr\w+|dig\w+|fal\w+|trag\w+|resum\w+)\s+(?:o\s+que|oque|tudo\s+que)\s+(?:achar|encontrar|ver).*$", "", q)
    q = re.sub(r"(?i)\b(?:em\s+sites?\s+americanos?(?:\s+como\s+[\w\s,e]+)?|(?:no|na|em|nos|nas|como)\s+(?:ebay(?:\s+e\s+amazon(?:\s+global)?)?|amazon(?:\s+global|\s+brasil)?|mercado\s*livre|mercadolivre|shopee|aliexpress|sites?\s+americanos?|lojas?\s+americanas?))\b", " ", q)
    cmd = re.compile(
        r"(?i)^\s*(?:e\s+|depois\s+)?(?:entr\w*|abr\w*|acesse|vai|v[aá]|pesquis\w*|busc\w*|procur\w*|mostr\w*)\s+"
        r"(?:(?:no|na|ao|o|a|um|uma)\s+)?(?:site|p[aá]gina|portal|navegador|chromium|chrome|google)?\s*"
        r"(?:e\s+)?(?:pesquis\w*|busc\w*|procur\w*)?\s*(?:sobre|por)?\s*"
    )
    for _ in range(4):
        n = cmd.sub("", q).strip()
        if not n or n == q:
            break
        q = n
    q = re.sub(r"(?i)\bfortin[aei]te\b", "fortnite", q)
    q = re.sub(r"(?i)\b(?:itesns|intens|itenss)\b", "itens", q)
    q = re.sub(r"\s+", " ", q).strip(" ,.!?")
    return q


def _urls_para_site_ou_busca(url="", busca="", contexto_lojas=""):
    u = str(url or "").strip()
    b = str(busca or "").strip()
    raw = f"{u} {b} {contexto_lojas}".strip()
    if u and not b and re.match(r"^(?:https?://|[a-zA-Z0-9-]+\.[a-zA-Z]{2,})(?:/.*)?$", u) and " " not in u:
        u_clean = u if u.startswith(("http://", "https://")) else "https://" + u
        return [u_clean], u_clean
    termo = _limpar_termo_busca(b or u) or (b or u).strip()
    if re.search(r"fortn", termo, re.I) and re.search(r"loja|item|skin", termo, re.I):
        return ["https://www.fortnite.com/item-shop?lang=pt-BR", "https://fortnite.gg/shop"], termo
    tem_ebay = bool(re.search(r"\bebay\b", raw, re.I))
    tem_amazon = bool(re.search(r"\bamazon\b", raw, re.I))
    tem_ml = bool(re.search(r"\bmercado\s*livre\b|\bmercadolivre\b", raw, re.I))
    tem_yt = bool(re.search(r"\b(?:you\s?tube|yutube)\b", raw, re.I))
    tem_us = bool(re.search(r"\b(?:sites?\s+americanos?|lojas?\s+americanas?|estados\s+unidos|google\s+us|amazon\s+global)\b", raw, re.I))
    urls = []
    if tem_ebay:
        urls.append("https://www.ebay.com/sch/i.html?_nkw=" + urllib.parse.quote_plus(termo))
    if tem_amazon:
        dom_amz = "www.amazon.com.br" if re.search(r"amazon\s*(?:\.com\.br|brasil|br)\b", raw, re.I) and not tem_us else "www.amazon.com"
        urls.append(f"https://{dom_amz}/s?k=" + urllib.parse.quote_plus(termo))
    if tem_ml:
        urls.append("https://lista.mercadolivre.com.br/" + urllib.parse.quote(termo.replace(" ", "-")))
    if tem_yt:
        q_yt = re.sub(r"(?i)\b(?:no|na|pelo|do|em|para|pra)?\s*(?:you\s?tube|yutube)\b", "", termo).strip() or termo
        urls.append("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q_yt))
    if tem_us and not (tem_ebay or tem_amazon):
        urls.append("https://www.google.com/search?q=" + urllib.parse.quote_plus(termo) + "&hl=en&gl=us")
    if not urls:
        urls.append("https://www.google.com/search?q=" + urllib.parse.quote_plus(termo))
    return urls, termo


def t_abrir_site(url="", busca="", contexto_lojas="", fr=None, ops=None, **_):
    """Abre um site ou pesquisa diretamente em nova(s) aba(s) do navegador Chromium e foca a janela."""
    u = str(url).strip()
    b = str(busca).strip()
    if not u and not b:
        raise ValueError("faltou url ou busca")
    urls, termo = _urls_para_site_ou_busca(u, b, contexto_lojas)
    if CANCEL.is_set():
        raise RuntimeError("cancelado pelo dono")
    if fr is not None:
        try:
            fr.fechar_paineis()
        except Exception:
            pass
    import abrir_nativo
    ok_nav, msg_nav = abrir_nativo.abrir_urls(urls)
    if not ok_nav:
        raise RuntimeError(msg_nav or "não abri o navegador do sistema")
    if fr is not None:
        w = None
        t0 = time.time()
        while time.time() - t0 < 6.0:
            w = fr.find_window(abrir_nativo.chave_janela("navegador"))
            if w:
                break
            time.sleep(0.3)
        if w:
            fr.fechar_paineis()
            fr._niri("focus-window", "--id", str(w["id"]))
            time.sleep(0.2)
            fr._ampliar(fr.find_window("chromium") or w)
            if fr.holo_mode():
                fr.holo_live("Chromium", ops)
    lido = ""
    try:
        lido = t_ler_rolando(vezes=4, url=urls[0] if urls else "")
    except Exception:
        lido = ""
    base = "navegador aberto e foi para: " + ", ".join(urls)
    return base + ("\n\nNa tela, depois de rolar:\n" + lido if lido else "\n\nA página abriu, mas a rolagem não mostrou texto útil.")


def _titulos_chromium():
    try:
        ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=3).stdout or "[]")
        return [w.get("title") or "" for w in ws if "chromium" in (w.get("app_id") or "").lower()]
    except Exception:
        return []


def _abriu_youtube(espera=6.0):
    t0 = time.time()
    while time.time() - t0 < espera:
        if any("YouTube" in t for t in _titulos_chromium()):
            return True
        time.sleep(0.5)
    return False


def t_tocar_youtube(pesquisa="", fr=None, ops=None, **_):
    """pesquisa no YouTube e reproduz DIRETO no navegador Chromium sem anúncios."""
    q = str(pesquisa).strip()
    if not q:
        raise ValueError("faltou o nome da música ou vídeo")
    vid = ""
    try:
        out = subprocess.run(["yt-dlp", "--flat-playlist", "--get-id", "--playlist-end", "1", "--no-warnings", "ytsearch1:" + q],
                             capture_output=True, text=True, timeout=30).stdout.split()
        vid = out[0] if out else ""
    except Exception:
        vid = ""
    if vid:
        url = "https://www.youtube.com/watch?v=" + vid
        try:
            t_abrir_site(url=url, fr=fr, ops=ops)
        except RuntimeError:
            pass
        if not _abriu_youtube():                        # teclado falhou (foco roubado/aba errada): aba nova direto, sem digitar nas abas do dono
            subprocess.Popen(["chromium", "--new-tab", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            if not _abriu_youtube(10.0):
                raise RuntimeError("o YouTube não abriu no Chromium")
        vigiar_anuncios(120)
        return f"Coloquei no YouTube para tocar: {q} (conferido: a aba do YouTube está aberta)"
    t_abrir_site(url="https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q), fr=fr, ops=ops)
    return f"Abri a pesquisa no YouTube por: {q}"


def t_pesquisar_youtube(pesquisa="", fr=None, ops=None, **_):
    """abre a página de resultados de busca no YouTube."""
    q = str(pesquisa).strip()
    if not q:
        raise ValueError("faltou o termo de pesquisa")
    t_abrir_site(url="https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q), fr=fr, ops=ops)
    return f"Resultados do YouTube para: {q}"


def t_pesquisa_para_documento(consulta="", tipo="docx", nome="", fr=None, **_):
    """pesquisa na web, lê as melhores páginas, o modelo local organiza e cria docx/xlsx/pptx aberto no ONLYOFFICE (tudo numa chamada)."""
    q = str(consulta).strip()
    if not q:
        raise ValueError("faltou a consulta")
    achados = t_pesquisar_web(consulta=q)
    textos = []
    for u in re.findall(r"\|\s*(https?://\S+)\s*$", achados, re.M)[:2]:
        try:
            textos.append(t_ler_pagina(url=u)[:2500])
        except Exception:
            pass
    tipo = str(tipo).lower().strip(".")
    try:
        import documento
        fontes = [f"Resultados da busca web:\n{achados}"] + [t for t in textos if t.strip()]
        res = documento.criar(q, fontes, formato=tipo, destino=DOCS, fr=fr, abrir=True)
        if res and res.get("caminho") and os.path.exists(res.get("caminho")):
            cam = res["caminho"]
            conf = res.get("conferir") or []
            aviso_conf = f" (atenção: {len(conf)} itens marcados para conferir)" if conf else ""
            return f"criado e aberto no ONLYOFFICE: {cam}{aviso_conf}"
    except Exception:
        pass
    base = (achados + "\n\n" + "\n\n".join(textos))[:7000]
    if tipo == "xlsx":
        guia = "Responda SÓ com linhas de tabela separadas por ';' (primeira linha = cabeçalho). Sem markdown, sem texto extra."
    elif tipo == "pptx":
        guia = "Responda SÓ com slides: cada slide começa com '# Título' e traz 3 a 5 linhas curtas com '- '."
    else:
        guia = "Responda SÓ com o documento: '# Seção' para títulos e parágrafos curtos ou linhas '- '. Sem markdown extra."
    conteudo = fr.llm("Você organiza informações pesquisadas em português do Brasil. Use SOMENTE o material fornecido; não invente. " + guia,
                      f"Tema: {q}\n\nMATERIAL:\n{base}", None, False, 900, 0.2, 120) or achados
    return t_onlyoffice_criar(tipo=tipo, nome=nome or q[:40], conteudo=conteudo)


# ------------------------------------------------------------------ percepção e controle visual (OCR local + cursor/teclado reais)
_SENS = re.compile(r"\b(enviar|send|pagar|pay|pagamento|comprar|buy|purchase|finalizar|checkout|excluir|delete|apagar|remover|transferir|"
                   r"transfer|publicar|post|confirmar|senha|password|cart[ãa]o|card|assinar|subscribe|sair|logout|desligar|reiniciar|"
                   r"shut\s?down|power|restart|reboot)\b", re.I)
_SKIP = re.compile(r"^\W*(pular|skip)(\s+(an[úu]ncios?|ads?|advertisement))?\W*$", re.I)


def _manual():
    import manual
    return manual


def _foco():
    try:
        w = json.loads(subprocess.run(["niri", "msg", "--json", "focused-window"], capture_output=True, text=True, timeout=3).stdout or "null")
        return f"{(w.get('app_id') or '?')} — {(w.get('title') or '')[:70]}" if w else "nenhuma janela em foco"
    except Exception:
        return "?"


def _tela():
    import tela
    return tela


def _olhar(n=35):
    """leitura LEVE da tela (AT-SPI/OCR da janela em foco + janelas, sem a descrição por visão): roda sozinha antes e depois de cada ação."""
    L, lido = [], ""
    try:
        r = _tela().ler()                                    # F8a: acessibilidade primeiro, OCR só da janela se ela vier pobre
        L, lido = _tela().linhas(r), _tela().texto(r, n)
    except Exception:
        pass
    if not L:
        try:
            L, lido = _manual().screen_lines(), ""             # caminho antigo: OCR da tela inteira
        except Exception:
            L = []
    try:
        ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=3).stdout or "[]")
        abertas = "; ".join(f"{w.get('app_id')} — {str(w.get('title'))[:60]}" for w in ws[:8])
    except Exception:
        abertas = "?"
    return L, f"janela em foco: {_foco()}\njanelas abertas: {abertas}\ntexto visível:\n" + (lido or "\n".join(f"{l['t']} @{l['x']},{l['y']}" for l in L[:n]))


_PARADAS = set("a o as os e de do da dos das no na nos nas em um uma pra para por que me meu minha esse essa isso ai aí ja já la lá ta tá esta está "
               "vai va vá coloca coloque bota bote toca toque clica clique abre abra abrir tocar musica música video vídeo tela aparece navegador "
               "aberto aberta youtube favor agora aquele aquela".split())


def _visivel(pedido, L):
    """o item pedido já aparece na tela? casa as palavras significativas do pedido (tolerando erro de transcrição) com as linhas do OCR."""
    import unicodedata
    nrm = lambda t: unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    alvo = [w for w in re.findall(r"\w+", nrm(pedido)) if w not in {nrm(x) for x in _PARADAS} and len(w) >= 3]
    if not alvo:
        return None
    melhor = (0.0, None)
    for l in L:
        pal = re.findall(r"\w+", nrm(l["t"]))
        if not pal:
            continue
        hit = sum(1 for w in alvo if any(difflib.SequenceMatcher(None, w, p).ratio() >= 0.75 for p in pal))
        sc = hit / len(alvo)
        if sc > melhor[0]:
            melhor = (sc, l)
    return melhor[1] if melhor[0] >= 0.6 else None


def _cel():
    import celular
    return celular


def _ptz():
    import ptz
    return ptz


def _camera_apontar():
    p = _ptz().get_ptz()
    p.definir_modo("livre", salvar=False)                 # o seguir/vigiar não disputa o motor
    if not p._tarefa("apontando pelas câmeras fixas"):
        return f"câmera ocupada ({p.ocupada})"
    try:
        return "apontei e vi alguém lá" if p.apontar_externo() else "as câmeras fixas não veem ninguém (ou ainda não aprendi o mapa)"
    finally:
        p._fim_tarefa()


def t_camera_ver(pergunta="Descreva o que a câmera mostra.", **_):
    """o que a câmera com motor (quarto) vê AGORA, pelo modelo de visão."""
    import cv2
    p = _ptz()
    fr, t = p.G.quadro()
    if fr is None or time.time() - t > 3:
        return "ERRO: sem vídeo da câmera do quarto (" + p.ipcam.status() + ")"
    ok, jpg = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return (p.G.vlm(jpg.tobytes(), pergunta) if ok else None) or "ERRO: o modelo de visão não respondeu"


def t_camera_olhar(direcao="", **_):
    p = _ptz().get_ptz()
    if not p.disponivel():
        return "ERRO: " + _ptz().ipcam.status()
    d = str(direcao).strip().lower()
    ok = p.ir_posicao(d) if d not in ("esquerda", "direita", "cima", "baixo", "centro") else p.olhar(d)
    return f"câmera virada para {d}" if ok else f"ERRO: direção ou posição '{d}' desconhecida"


def _cel_espelhar(on=True):
    """tela do celular ao vivo no holograma (celtela) ou fecha."""
    import celtela
    if str(on).lower() in ("false", "0", "nao", "não", "off", "fechar"):
        celtela.fechar()
        return "espelhamento do celular fechado"
    r = celtela.mostrar()
    return f"tela do celular ao vivo no holograma ({r.get('w', '?')}x{r.get('h', '?')} a {r.get('fps', 60)} fps)" if not r.get("iniciando") \
        else "abrindo a tela do celular ao vivo no holograma"


CELULAR_RE = re.compile(r"\b(celular|telefone|smartphone|meu cel|no cel|android)\b", re.I)


def t_ver_tela(**_):
    """janela em foco: elementos (acessibilidade) ou texto (OCR da janela) com posição (x,y). Use antes de clicar."""
    try:
        txt = _tela().texto(_tela().ler(), 45)
    except Exception:
        txt = ""
    if not [x for x in txt.splitlines()[1:] if x.strip()]:   # leitura vazia: caminho antigo (OCR da tela inteira)
        L = _manual().screen_lines()
        txt = "\n".join(f"{l['t']} @{l['x']},{l['y']}" for l in L[:45])
    try:
        ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=3).stdout or "[]")
        abertas = ", ".join(sorted({(w.get("app_id") or "?").split(".")[-1] for w in ws}))
    except Exception:
        abertas = "?"
    try:
        import visao
        desc = visao.olhar_tela("Describe in Portuguese (Brazil), max 4 short sentences, what app/site is open and its main visible buttons, fields and tabs. Only what is really visible.")
    except Exception:
        desc = ""
    return f"janela em foco: {_foco()}\njanelas abertas: {abertas}\nvisão: {desc}\ntexto visível:\n{txt}"[:2300]


def t_analisar_dificuldade_tela(janela_id=None, **_):
    """Analisa a tela em busca de erros de código, exceções, falhas de compilação ou dificuldades do usuário."""
    import tela
    res = tela.detectar_dificuldades(janela_id=janela_id)
    if res.get("tem_dificuldade"):
        return (f"DIFICULDADE DETECTADA ({res['severidade'].upper()}): {res['tipo']}\n"
                f"App: {res.get('app', 'janela ativa')}\n"
                f"Detalhe: {res['detalhes']}\n"
                f"Sugestão de solução: {res['sugestao']}")
    return "Nenhuma dificuldade, erro de compilação ou exceção detectada na tela ativa."


def t_reconhecer_emocao(fonte="camera_notebook", **_):
    """Reconhece a expressão emocional e postura do usuário pelas câmeras ou sensores faciais."""
    try:
        import prometheus as _prom
        scene = getattr(_prom, "scene", {})
        faces = scene.get("faces") or []
        if faces:
            f0 = faces[0]
            emocao = f0.get("emocao", "neutro")
            conf = f0.get("conf_emocao", 0.70)
            olhando = f0.get("olhando", True)
            postura = f0.get("postura", "alinhada")
            sorriso = f0.get("sorriso", 0.0)
            return (f"EMOÇÃO DETECTADA: {emocao.upper()} (confiança {int(conf*100)}%)\n"
                    f"Expressão: {'sorrindo' if sorriso > 0.3 else 'séria/neutra'} (índice {sorriso:.2f})\n"
                    f"Olhando para a tela: {'Sim' if olhando else 'Não/Distraído'}\n"
                    f"Postura: {postura}\n"
                    f"Tom recomendado para a Friday: {'empático e direto' if emocao == 'frustrado' else 'positivo e prestativo' if emocao == 'feliz' else 'acolhedor e proativo' if emocao == 'cansado' else 'focado e eficiente'}")
    except Exception:
        pass

    try:
        import visao as V
        jpg = V._jpg_fonte(fonte if fonte != "todas" else "camera_notebook")
        if jpg:
            prompt = ("Observe a expressão facial e postura da pessoa nesta imagem. "
                      "Responda SOMENTE um JSON: {\"emocao\": \"feliz|frustrado|cansado|surpreso|focado|neutro\", "
                      "\"confianca\": 0.8, \"detalhes\": \"...\", \"sugestao_tom\": \"...\"}")
            raw = V.consultar_vlm(jpg, prompt, max_tokens=100, temp=0.1)
            m = re.search(r"\{[^{}]*\}", raw or "")
            if m:
                d = json.loads(m.group(0))
                return (f"EMOÇÃO DETECTADA: {d.get('emocao', 'neutro').upper()}\n"
                        f"Detalhes: {d.get('detalhes', '')}\n"
                        f"Sugestão de tom: {d.get('sugestao_tom', 'focado e prestativo')}")
    except Exception:
        pass
    return "EMOÇÃO DETECTADA: NEUTRO (expressão facial relaxada, usuário em postura regular diante da estação)."


def t_reconhecer_gestos(fonte="camera_notebook", **_):
    """Reconhece gestos ativos das mãos do usuário (joinha, pare, polegar_baixo, paz, apontar, ok, etc.)."""
    try:
        import prometheus as _prom
        scene = getattr(_prom, "scene", {})
        hdiag = getattr(_prom, "hdiag", {})
        last = hdiag.get("last", {})
        gestos = []
        for lado, info in last.items():
            pose = info.get("pose")
            if pose:
                lbl = "mão direita" if lado == "R" else "mão esquerda"
                gestos.append(f"{lbl}: {pose.upper()} (confiança {int(info.get('conf', 0.8)*100)}%)")
        if gestos:
            return "GESTOS ATIVOS DETECTADOS:\n" + "\n".join(gestos)
    except Exception:
        pass

    try:
        import visao as V, senses
        jpg = V._jpg_fonte(fonte if fonte != "todas" else "camera_notebook")
        if jpg:
            import cv2, numpy as np
            bgr = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if bgr is not None:
                ht = senses.HandTracker()
                hands = ht.detect(bgr)
                if hands:
                    g_res = []
                    for h_ in hands:
                        p = senses.hand_pose(h_["lm"])
                        if p:
                            g_res.append(f"Gesto {p.upper()} (confiança {int(h_['conf']*100)}%)")
                    if g_res:
                        return "GESTOS DETECTADOS NA CÂMERA:\n" + "\n".join(g_res)
    except Exception:
        pass

    return "Nenhum gesto manual ativo detectado no momento."


def t_percepcao_situacional(**_):
    """Executa um diagnóstico perceptual completo e simultâneo: tela (erros/dificuldades), usuário (emoção/foco/gestos) e saúde operacional."""
    partes = []
    try:
        import tela
        dif = tela.detectar_dificuldades()
        if dif.get("tem_dificuldade"):
            partes.append(f"[TELA - DIFICULDADE {dif['severidade'].upper()}]: {dif['tipo']} -> {dif['resumo']}\nSugestão: {dif['sugestao']}")
        else:
            partes.append("[TELA]: Normal (sem erros ou exceções)")
    except Exception as e:
        partes.append(f"[TELA]: Erro ao checar tela ({e})")

    try:
        res_emocao = t_reconhecer_emocao()
        partes.append(f"[USUÁRIO - EMOÇÃO/POSTURA]:\n{res_emocao}")
    except Exception as e:
        partes.append(f"[USUÁRIO]: Expressão neutra ({e})")

    try:
        res_gestos = t_reconhecer_gestos()
        partes.append(f"[GESTOS MANUAIS]: {res_gestos}")
    except Exception as e:
        partes.append(f"[GESTOS]: Nenhum gesto ativo ({e})")

    try:
        import psutil
        ram = psutil.virtual_memory().percent
        disco = psutil.disk_usage("/").percent
        partes.append(f"[SISTEMA]: RAM {ram:.0f}%, Disco {disco:.0f}%")
    except Exception:
        pass

    return "\n\n".join(partes)


def t_orquestrar_tarefa_continua(id="", titulo="", instrucao="", tipo="continua", intervalo_s=60, **_):
    """Inicia ou retoma uma tarefa contínua, longa ou intermitente com persistência e checkpoints."""
    import orchestrator
    orc = orchestrator.get_orquestrador()
    tid = id or re.sub(r"[^a-zA-Z0-9_\-]", "_", (titulo or "").lower())[:30] or f"obj_{int(time.time())}"
    res = orc.iniciar_ou_retomar_objetivo(
        objetivo_id=tid,
        titulo=titulo or tid,
        instrucao=instrucao or titulo,
        tipo=tipo,
        intervalo_s=float(intervalo_s or 60)
    )
    return f"Objetivo orquestrado: ID '{res['id']}', status '{res['status']}'. Executando continuamente com checkpoints persistidos."


def t_consultar_objetivos_ativos(**_):
    """Lista todos os objetivos e tarefas em execução contínua ou intermitente."""
    import orchestrator
    orc = orchestrator.get_orquestrador()
    objs = orc.listar_objetivos()
    if not objs:
        return "Nenhum objetivo contínuo ou intermitente ativo no momento."
    linhas = [f"- [{o.get('id')}] {o.get('titulo')}: {str(o.get('status')).upper()} (tipo: {o.get('tipo')}, ciclos: {o.get('ciclos_executados')}, último: {str(o.get('ultimo_resultado'))[:100]})" for o in objs]
    return "OBJETIVOS ORQUESTRADOS ATIVOS:\n" + "\n".join(linhas)


def t_parar_objetivo(id="", **_):
    """Pausa ou cancela um objetivo orquestrado pelo ID."""
    import orchestrator
    orc = orchestrator.get_orquestrador()
    res = orc.parar_objetivo(id)
    return res.get("mensagem") or res.get("erro") or "Objetivo atualizado."


def t_operar_outra_ia(ia="claude", prompt="", modelo=None, **_):
    """Opera outras IAs (Claude CLI, Gemini, ChatGPT, Ollama, DeepSeek) para resolver subtarefas complexas."""
    import orchestrator
    orc = orchestrator.get_orquestrador()
    return orc.operar_outra_ia(ia=ia, prompt=prompt, modelo=modelo)


def t_criar_ou_modificar_tela(nome="", tipo="qml", codigo="", titulo="", **_):
    """Cria ou atualiza telas internas (QML para o Quickshell do Linux ou HTML5 HUD para Web/Android) dinamicamente."""
    import orchestrator
    orc = orchestrator.get_orquestrador()
    res = orc.criar_ou_modificar_tela_interna(nome=nome, tipo=tipo, codigo=codigo, titulo=titulo)
    return res.get("mensagem") or res.get("erro") or "Tela processada."


def _orq_motor():
    """liga o motor do orquestrador (fila + sessão longa em segundo plano). False = dono pausou; None = indisponível."""
    try:
        import orchestrator
        return orchestrator.get_orquestrador().garantir_motor()
    except Exception:
        return None


_UNID_Q = {"segundo": "s", "segundos": "s", "seg": "s", "s": "s", "minuto": "m", "minutos": "m", "min": "m", "m": "m",
           "hora": "h", "horas": "h", "h": "h", "dia": "d", "dias": "d", "d": "d"}


def _quando_fila(quando):
    """'+2h', 'daqui a 2 horas', 'em 10 minutos', 'amanhã 9h', 'sexta 14h', ISO ou epoch -> (valor p/ orquestra_geral, epoch).
    Vazio = agora. Horário que não entende vira ERRO (o orquestra_geral trataria texto inválido como 'agora')."""
    if quando is None or str(quando).strip() == "":
        return "", 0.0
    if isinstance(quando, (int, float)):
        ts = float(quando)
    else:
        q = str(quando).strip().lower()
        if q in ("agora", "já", "ja", "imediatamente", "0"):
            return "", 0.0
        m = re.fullmatch(r"\+\s*(\d+(?:\.\d+)?)\s*([smhd]?)", q)
        if m:
            return "+" + m.group(1) + m.group(2), time.time() + float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
        m = re.fullmatch(r"(?:daqui\s+a|daqui|em|dentro\s+de)\s+(\d+(?:[.,]\d+)?)\s*([a-z]+)", q)
        if m and m.group(2) in _UNID_Q:
            n, u = m.group(1).replace(",", "."), _UNID_Q[m.group(2)]
            return "+" + n + u, time.time() + float(n) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[u]
        if re.match(r"(?:daqui(?:\s+a)?|em|dentro\s+de)\s+\d", q):          # "daqui a 2 semanas": parse_quando leria "a 2" como "às 2h"
            raise ValueError(f"não entendi o horário '{quando}'. Use +30m, +2h, +3d, 'amanhã 9h' ou 2026-10-19T09:00")
        try:
            ts = float(q)
        except ValueError:
            from prom_ops import parse_quando
            ts = parse_quando(q)
            if ts is None:
                try:
                    from datetime import datetime
                    ts = datetime.fromisoformat(str(quando).strip()).timestamp()
                except ValueError:
                    ts = None
    if not ts:
        raise ValueError(f"não entendi o horário '{quando}'. Use +30m, +2h, 'amanhã 9h', 'sexta 14h' ou 2026-10-19T09:00")
    if ts < time.time() - 60:
        raise ValueError(f"o horário '{quando}' já passou")
    return str(int(ts)), ts


def t_orquestra_iniciar(pedido="", **_):
    """Abre uma sessão longa: plano, primeiro passo, estado em disco; o motor segue os passos em segundo plano."""
    if not str(pedido or "").strip():
        return "faltou o pedido"
    try:
        import orquestra_geral as og
        import orchestrator
        with orchestrator.OG_LOCK:                       # um avancar() por vez (motor e objetivos usam a mesma sessão)
            atual = og.status().get("sessao") or {}
            if atual.get("status") == "ativa":           # só um objetivo ativo: o novo espera na fila
                r = og.enfileirar(pedido, quando="")
                if not r.get("ok"):
                    return r.get("fala") or "recusado"
                _orq_motor()
                return (f"Já tem uma sessão ativa ({str(atual.get('pedido') or '')[:80]}); coloquei este na fila "
                        f"({(r.get('item') or {}).get('id')}), começa quando ela acabar.")
            s = og.sessao_nova(pedido)
            if not s.get("ok"):
                return s.get("fala") or "recusado"
            r = og.avancar()
    except Exception as e:
        return f"o orquestrador falhou: {str(e)[:160]}"
    fala = (r.get("fala") or "sessão aberta")[:700]
    if _orq_motor() is False:
        fala += " (orquestrador pausado: diga retomar para seguir os próximos passos)"
    return fala[:800]


def t_orquestra_fila(pedido="", quando="", **_):
    """Põe um objetivo na fila do orquestrador, agora ou num horário (quando); só um fica ativo por vez."""
    if not str(pedido or "").strip():
        return "faltou o pedido"
    try:
        import orquestra_geral as og
        q, ts = _quando_fila(quando)
        r = og.enfileirar(pedido, quando=q)
    except Exception as e:
        return f"não coloquei na fila: {str(e)[:180]}"
    if not r.get("ok"):
        return r.get("fala") or "recusado"
    item = r.get("item") or {}
    msg = f"na fila: {item.get('id')}" + (f", começa {time.strftime('%d/%m %H:%M', time.localtime(ts))}" if ts else ", começa assim que a sessão atual acabar")
    if _orq_motor() is False:
        msg += " (orquestrador pausado: só roda depois que o dono disser retomar)"
    return msg


def _quando_txt(it):
    q = str(it.get("quando") or "").strip()
    if not q:
        return "agora"
    m = re.fullmatch(r"\+(\d+(?:\.\d+)?)\s*([smhd]?)", q)
    try:
        ts = float(it.get("t") or 0) + float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)] if m else float(q)
        return time.strftime("%d/%m %H:%M", time.localtime(ts))
    except (ValueError, OverflowError, OSError):
        return q[:20]


def t_orquestra_status(**_):
    """Estado do orquestrador: sessão longa (passo atual/total), fila com horários e se está pausado."""
    try:
        import orquestra_geral as og
        st = og.status() or {}
    except Exception as e:
        return f"não consegui ler o orquestrador: {str(e)[:160]}"
    linhas = []
    try:
        import orchestrator
        m = orchestrator.get_orquestrador().motor_estado()
        linhas.append("motor: " + ("PAUSADO" if m.get("pausado") else ("rodando" if m.get("rodando") else "parado")))
    except Exception:
        pass
    try:                                    # trava ocupada por outro processo = serviço friday-orquestra executando
        import fcntl
        with open(os.path.join(og.MEM, "orquestra.lock"), "a+") as f_:
            try:
                fcntl.flock(f_.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f_.fileno(), fcntl.LOCK_UN)
                if not getattr(og, "_TRAVA", None):
                    linhas.append("executor: nenhum (serviço friday-orquestra parado)")
            except OSError:
                if not getattr(og, "_TRAVA", None):
                    linhas.append("executor: serviço friday-orquestra (sempre ligado)")
    except Exception:
        pass
    ses = st.get("sessao") or {}
    if ses:
        passos = (ses.get("plano") or {}).get("passos") or []
        feitos = sum(1 for p in passos if p.get("estado") in ("ok", "pulado"))
        ult = ((ses.get("evidencia") or [{}])[-1] or {}).get("res") or ""
        linhas.append(f"sessão {ses.get('id')}: {ses.get('status')}, {feitos}/{len(passos)} passos: {str(ses.get('pedido') or '')[:120]}"
                      + (f"; próximo: {ses.get('proximo')}" if ses.get("proximo") else "") + (f"; último: {str(ult)[:160]}" if ult else ""))
    else:
        linhas.append("nenhuma sessão longa")
    itens = (st.get("fila") or {}).get("itens") or []
    pend = [i for i in itens if i.get("status") in ("esperando", "ativo")]
    linhas.append(f"fila: {len(pend)} pendente(s), {sum(1 for i in itens if i.get('status') == 'feito')} feita(s)")
    linhas += [f"- [{i.get('id')}] {i.get('status')} ({_quando_txt(i)}): {str(i.get('pedido') or '')[:90]}" for i in pend[:8]]
    return "\n".join(linhas)


def t_orquestra_pausar(id="", **_):
    """Pausa o orquestrador (sessão longa + fila ficam salvas); com id, pausa só aquele objetivo contínuo."""
    try:
        import orchestrator
        orc = orchestrator.get_orquestrador()
        res = orc.parar_objetivo(id) if str(id or "").strip() else orc.pausar_motor()
    except Exception as e:
        return f"não consegui pausar: {str(e)[:160]}"
    return res.get("mensagem") or res.get("erro") or "pausado"


def t_orquestra_retomar(id="", **_):
    """Retoma o orquestrador pausado (e a sessão que esperava o dono); com id, retoma aquele objetivo contínuo."""
    try:
        import orchestrator
        orc = orchestrator.get_orquestrador()
        res = orc.retomar_objetivo(str(id).strip()) if str(id or "").strip() else orc.retomar_motor()
    except Exception as e:
        return f"não consegui retomar: {str(e)[:160]}"
    return res.get("mensagem") or res.get("erro") or "retomado"


def t_pensar_estrategia(objetivo="", contexto="", **_):
    """Executa reflexão deliberada de pré-ação avaliando contexto, tela, riscos e alternativas antes de agir."""
    import orchestrator
    orc = orchestrator.get_orquestrador()
    ctx = {"detalhe": contexto}
    try:
        import tela
        ctx["dificuldade_tela"] = tela.detectar_dificuldades().get("detalhes")
    except Exception:
        pass
    p = orc.pensar_antes_de_agir(objetivo=objetivo, contexto=ctx, acao_planejada=objetivo)
    return f"Estratégia formulada: {p['estrategia']}\nRiscos: {', '.join(p['riscos_detectados']) or 'nenhum'}\nAutorizado: {p['autorizado']}"


def t_clicar_texto(texto="", **_):
    """clica (cursor real, movimento humano) no texto visível mais parecido com `texto`. Recusa ações sensíveis."""
    alvo = str(texto).strip()
    if not alvo:
        raise ValueError("faltou o texto")
    if _SENS.search(alvo):
        raise PermissionError("ação sensível (enviar/pagar/apagar/senha/desligar): isso fica com o dono")
    m = _manual()
    try:
        p = _tela().localizar(alvo, vlm=False)              # F8a: nome real (AT-SPI) e depois OCR da janela
    except Exception:
        p = None
    if p:
        return _clicar_conferido(p, alvo)
    l, sc = m._find(alvo, m.screen_lines())
    if not l:
        try:
            return t_clicar_elemento(descricao=f"the text or button '{alvo}'")   # OCR falhou: visão local
        except LookupError:
            raise LookupError(f"não achei '{alvo}' na tela")
    m._pc("clickat", l["x"], l["y"])
    return f"cliquei em '{l['t']}' ({l['x']},{l['y']})"


def _clicar_conferido(p, pedido):
    """clica no ponto achado por tela.localizar e confere se o clique teve efeito (tela/foco/estado do elemento)"""
    if p.get("fonte") == "atspi" and len(p.get("nome") or "") <= 30 and _SENS.search(p.get("nome") or ""):    # botão real "Enviar"/"Excluir"
        raise PermissionError(f"'{p['nome'][:40]}' é ação sensível: isso fica com o dono")
    if p["x"] > _tela_w() - 260 and p["y"] < 90:
        raise PermissionError("canto superior direito (energia): bloqueado")
    t = _tela()
    antes = t.estado()
    _manual()._pc("clickat", p["x"], p["y"])
    ok, ev = t.efeito(antes, p)
    t._log(op="clique", pedido=pedido[:60], fonte=p.get("fonte"), nome=(p.get("nome") or "")[:60], x=p["x"], y=p["y"], efeito=ok, ev=ev)
    return f"cliquei em '{(p.get('nome') or pedido)[:60]}' ({p['x']},{p['y']}, via {p.get('fonte')}) — " + \
        ("efeito: " + ev if ok else "SEM efeito visível: " + ev)


def _achar_elemento(desc):
    import visao
    for _ in range(2):
        r = visao.localizar(desc)
        if r:
            return r
    raise LookupError(f"não vi '{desc}' na tela")


def t_clicar_elemento(descricao="", **_):
    """acha QUALQUER elemento visual (ícone, botão sem texto, imagem, campo) pela descrição, com visão local, move o cursor até lá e clica."""
    d = str(descricao).strip()
    if not d:
        raise ValueError("faltou a descrição")
    if _SENS.search(d):
        raise PermissionError("ação sensível: isso fica com o dono")
    try:
        p = _tela().localizar(d)                           # F8a: AT-SPI -> OCR -> VLM da janela conferido por zoom
    except Exception:
        p = None
    if p:
        return _clicar_conferido(p, d)
    r = _achar_elemento(d)                                 # caminho antigo: VLM na tela inteira
    if r["x"] > _tela_w() - 260 and r["y"] < 90:
        raise PermissionError("canto superior direito (energia): bloqueado")
    _manual()._pc("clickat", r["x"], r["y"])
    return f"cliquei em '{d}' ({r['x']},{r['y']})"


def t_apontar(descricao="", **_):
    """só move o cursor até o elemento descrito (guia o dono / confere antes de clicar), sem clicar."""
    r = _achar_elemento(str(descricao))
    if r["x"] > _tela_w() - 260 and r["y"] < 90:
        raise PermissionError("canto superior direito (energia): bloqueado")
    _manual()._pc("move", r["x"], r["y"])
    return f"cursor em '{descricao}' ({r['x']},{r['y']})"


def _tela_w():
    try:
        return int(_manual()._pc("size").split("x")[0])
    except Exception:
        return 1920


def _em_whatsapp():
    f = _foco().lower()
    return "zapzap" in f or "whatsapp" in f


def t_digitar(texto="", enter=False, **_):
    t = str(texto)
    if enter and _em_whatsapp():
        raise PermissionError("WhatsApp: enviar mensagem só com sua permissão")
    if re.search(r"senha|password", t, re.I):
        raise PermissionError("parece uma senha: isso fica com o dono")
    _manual()._pc("type", t, timeout=90)
    if enter:
        time.sleep(0.2); _manual()._pc("key", "enter")
    return "digitei: " + t[:60] + (" + Enter" if enter else "")


def t_tecla(teclas="", **_):
    k = str(teclas).strip()
    if re.search(r"\b(enter|return|kpenter)\b", k, re.I) and _em_whatsapp():
        raise PermissionError("WhatsApp: enviar mensagem só com sua permissão")
    if _manual().LOCK_KEYS.search(k):
        raise PermissionError("atalho de bloqueio/energia: bloqueado")
    _manual()._pc("key", *k.split())
    return "tecla: " + k


def t_rolar(n=3, **_):
    _manual()._pc("scroll", int(n))
    return f"rolei {n}"


_AVISO = re.compile(
    r"^(?:aceitar(?:\s+tudo|\s+todos|\s+cookies)?|accept(?:\s+all)?|concordo|entendi|"
    r"fechar(?:\s+an[úu]ncio|\s+aviso)?|close(?:\s+ad)?|agora\s+n[ãa]o|n[ãa]o,?\s*obrigado|"
    r"pular(?:\s+an[úu]ncio)?|skip(?:\s+ads?)?|rejeitar|recusar|dispensar|dismiss|"
    r"continuar(?:\s+para\s+o\s+site)?|prosseguir)$",
    re.I)


def _ocr_da_tela():
    """OCR da tela inteira, com posição. A árvore de acessibilidade do navegador só enxerga as abas."""
    try:
        import visao
        import ocr_pt
        visao.capturar_tela()
        img = visao._ULTIMA_TELA[0]
        if img is None:
            return []
        bruto = ocr_pt.linhas(img) or []
    except Exception:
        return []
    out = []
    for l in bruto:
        try:
            out.append({"t": str(l.get("t") or "").strip(),
                        "x": int((l["x0"] + l["x1"]) / 2),
                        "y": int((l["y0"] + l["y1"]) / 2)})
        except Exception:
            continue
    return out


def t_fechar_sobreposicao(**_):
    """Fecha aviso de cookie, anúncio ou 'pular' que esteja cobrindo a página."""
    m = _manual()
    feitos = []
    linhas = _ocr_da_tela()
    if not linhas:
        try:
            linhas = m.screen_lines()
        except Exception:
            return "não li a tela para fechar aviso"
    for l in linhas:
        rot = re.sub(r"\s*@\d+,\d+$", "", (l.get("t") or "").strip())
        if not rot or len(rot) > 40:
            continue
        fechar = _SKIP.match(rot) or _AVISO.match(rot) or re.search(r"lembrar mais tarde|dispensar|fechar anúncio|close ad|pular anúncio|continuar para o site", rot, re.I)
        if not fechar and re.fullmatch(r"[x×✕]", rot, re.I) and int(l.get("y") or 0) > 90:
            fechar = True
        if not fechar:
            continue
        try:
            m._pc("clickat", l["x"], l["y"])
            feitos.append(rot)
            time.sleep(0.35)
        except Exception:
            pass
        if len(feitos) >= 3:
            break
    return "fechei: " + ", ".join(feitos) if feitos else "sem aviso cobrindo a página"


def _ocr_da_pagina():
    """OCR só do miolo da página. Aba, relógio e anúncio de rodapé ficam de fora."""
    linhas = _ocr_da_tela()
    if not linhas:
        return []
    try:
        import visao
        h = int(visao._ULTIMA_TELA[0].shape[0])
    except Exception:
        h = 1080
    topo, base = int(h * 0.14), int(h * 0.86)
    return [l for l in linhas if topo <= int(l.get("y") or 0) <= base]


def _texto_tela_rapido():
    """Texto da página. OCR do miolo, porque a acessibilidade do Chromium só devolve as abas."""
    foco = _foco().lower()
    if not any(nav in foco for nav in ("chromium", "chrome", "firefox", "browser", "brave", "edge", "web")):
        return ""
    linhas = _ocr_da_pagina()
    if linhas:
        return "\n".join(l["t"] for l in linhas if l.get("t"))
    try:
        txt = _tela().texto(_tela().ler(), 80)
    except Exception:
        txt = ""
    return txt or ""



def _dump_legivel(url):
    """Lê o DOM já renderizado, em segundo plano, quando a página é feita de JavaScript."""
    import shutil
    exe = shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if not exe or not str(url).startswith("http"):
        return ""
    try:
        r = subprocess.run(
            [exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=12000",
             "--user-data-dir=/tmp/friday-leitura", "--dump-dom", str(url)],
            capture_output=True, text=True, timeout=28)
        return _texto(r.stdout or "")[:5000]
    except Exception:
        return ""


def _linhas_de_leitura(texto):
    out = []
    for ln in re.split(r"[\n\r•]+|(?<=[.!?])\s+", texto or ""):
        s = re.sub(r"\s*@\d+,\d+$", "", re.sub(r"\s+", " ", ln)).strip(" -•\t")
        if len(s) > 180 or _LIXO_TELA.search(s):
            continue
        if len(s) < 8 and not re.search(r"\d", s):
            continue
        if len(s) < 3:
            continue
        if re.search(
            r"verifica[çc][ãa]o de seguran|um momento|cloudflare|endere[çc]o ip|id da sess[ãa]o|"
            r"esperando a resposta|mova suas guias|learn more|sponsored|patrocinad|caixa de|"
            r"sign in|repositor|developers|gestos de janela|monitor gamer|pichau|nexus|"
            r"\d+\s*hz\b|resets in|sunday|0?october|whatsapp|aceitar cookies|pol[íi]tica de privacidade|"
            r"todos os direitos reservados|inscreva-se|assine nossa newsletter|an[úu]ncio|publicidade",
            s, re.I):
            continue
        if re.match(r"^\(\d+\)", s):
            continue
        if re.fullmatch(r"[\W\d]{1,12}", s) and not re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+|\d{2,5}", s):
            continue
        if s not in out:
            out.append(s)
    return out


def t_ler_rolando(vezes=8, url="", **_):
    """Fecha aviso, rola a página de verdade até o final e junta o texto de cada tela sem anúncios."""
    try:
        _manual()._pc("move", 960, 540)
    except Exception:
        pass
    t_fechar_sobreposicao()
    vistos, linhas = set(), []
    n = max(1, min(int(vezes or 8), 15))
    ultimo_tamanho = 0
    repeticoes = 0
    for i in range(n):
        t_fechar_sobreposicao()
        for s in _linhas_de_leitura(_texto_tela_rapido()):
            if s not in vistos:
                vistos.add(s)
                linhas.append(s)
        if len(linhas) == ultimo_tamanho:
            repeticoes += 1
            if repeticoes >= 2:
                break
        else:
            repeticoes = 0
            ultimo_tamanho = len(linhas)
        if i + 1 < n:
            t_rolar(5)
            time.sleep(0.45)
    for s in _linhas_de_leitura(_dump_legivel(url)):
        if s not in vistos:
            vistos.add(s)
            linhas.append(s)
    texto = "\n".join("• " + s for s in linhas[:40])
    try:
        import memoria
        if url:
            memoria.gravar("site", str(url)[:180], texto[:180] or "página aberta")
        if texto:
            memoria.evento("tela", texto[:180])
    except Exception:
        pass
    return texto


def t_pular_anuncio(espera=0, fr=None, **_):
    """acha 'Pular anúncio'/'Skip ads' no vídeo (OCR) e clica. Se `espera`>0, aguarda o botão aparecer (anúncios liberam o botão após ~5 s)."""
    m = _manual()
    t_fim = time.time() + max(0, min(int(espera or 0), 40))
    while True:
        for l in m.screen_lines():
            if _SKIP.match(l["t"]):
                m._pc("clickat", l["x"], l["y"])
                return f"anúncio pulado ({l['t']})"
        if time.time() >= t_fim or CANCEL.is_set():
            return "não vi botão de pular anúncio (talvez não haja anúncio ou ele ainda não liberou)"
        time.sleep(1.5)


def vigiar_anuncios(segundos=90):
    """em segundo plano: enquanto o YouTube estiver em foco, pula anúncios sozinha por até `segundos`."""
    def _run():
        fim = time.time() + segundos
        while time.time() < fim and not CANCEL.is_set():
            time.sleep(3.0)
            f = _foco().lower()
            if "chromium" not in f or "youtube" not in f:
                continue
            try:
                r = t_pular_anuncio(espera=0)
                if r.startswith("anúncio pulado"):
                    _log("pular_anuncio", {}, True, 0, r)
                    time.sleep(2)
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True, name="skip-ads").start()


def t_pc_perfil(**_):
    """o que o assistente sabe do PC do dono (hardware, sistema, apps, atalhos)."""
    try:
        for nome in ("pc_perfil.md", "mapa_pc_resumo.md"):
            f = os.path.join(MEM, nome)
            if os.path.exists(f):
                return open(f, errors="ignore").read()[:1800]
        raise FileNotFoundError
    except Exception:
        return "mapa do PC indisponível"


IA_SITES = {"chatgpt": "https://chatgpt.com/?temporary-chat=true", "claude": "https://claude.ai/new", "gemini": "https://gemini.google.com/app",
            "perplexity": "https://www.perplexity.ai/", "copilot": "https://copilot.microsoft.com/"}


def _clip():
    try:
        return subprocess.run(["wl-paste", "-n"], capture_output=True, text=True, timeout=4).stdout
    except Exception:
        return ""


def t_consultar_ia(pergunta="", site="chatgpt", fr=None, ops=None, **_):
    """usa a IA do DONO no navegador (já logada no Chromium): abre o site, digita a pergunta COMO HUMANO, espera a resposta terminar
    e devolve o texto. Use quando a tarefa for complexa demais (código, textos longos, análise) para o modelo local."""
    q = str(pergunta).strip()
    if not q:
        raise ValueError("faltou a pergunta")
    nome = str(site).lower().strip()
    nome = next((k for k in IA_SITES if k in nome), "chatgpt")
    t_abrir_site(url=IA_SITES[nome], fr=fr, ops=ops)
    time.sleep(5.0)                                          # carrega a página (o campo de texto já nasce focado)
    tela = " ".join(l["t"] for l in _manual().screen_lines()).lower()
    if re.search(r"\b(log in|sign up|entrar|inscrever-se|fazer login|cadastre-se|continue with|continuar com)\b", tela) and not re.search(r"\b(message|mensagem|pergunte|ask)\b", tela):
        raise PermissionError(f"não estou logada no {nome} neste Chromium; entre na sua conta e peça de novo")
    m = _manual()
    # clica no campo de mensagem (OCR) para garantir o foco; sem isso a digitação cai em outra coisa
    campo = None
    for l in m.screen_lines():
        if re.search(r"(pergunte ao|ask chatgpt|message chatgpt|envie uma mensagem|como posso ajudar|ask anything|pergunte|mensagem para)", l["t"], re.I):
            campo = l; break
    if campo:
        m._pc("clickat", campo["x"], campo["y"])
    time.sleep(0.4)
    m._pc("type", q[:1700] + "\n\n(Responda em texto simples, direto, em no máximo 15 linhas, sem tabelas.)", timeout=120)
    time.sleep(0.4)
    m._pc("key", "enter")
    UI = re.compile(r"(pergunte ao|chat tempor|personalizado|pensar|por seguran|novo chat|imagens|biblioteca|plugins|codex|explorar|fixados|projetos|recentes|"
                    r"fazer upgrade|chatgpt pode|pode cometer erros|copiar|ask anything|temporary chat|^\W*$)", re.I)

    def _resposta():
        linhas = [l for l in m.screen_lines() if l["x0"] > 380 and 185 < l["y"] < 960 and not UI.search(l["t"]) and l["t"].strip() != q[:60].strip()]
        linhas.sort(key=lambda z: (z["y"], z["x"]))
        return "\n".join(l["t"] for l in linhas)

    SUFIXO = "sem tabelas.)"
    LIXO = re.compile(r"\n?\s*(O ChatGPT pode cometer erros|ChatGPT can make mistakes|Ver preferências|Verifique informações importantes).*$", re.S | re.I)

    def _copiar_texto():
        """texto EXATO (sem OCR): clica numa área vazia da conversa, Ctrl+A / Ctrl+C e corta tudo depois da nossa pergunta."""
        try:
            w = fr.find_window("chromium")
            g = fr._tile_geo(w) if w else None
            if not g:
                return ""
            m._pc("clickat", g[0] + g[2] - 70, g[1] + int(g[3] * 0.55))        # margem direita vazia (longe do canto superior direito)
            subprocess.run(["wl-copy", "--", "__aguardando__"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            m._pc("key", "ctrl+a"); time.sleep(0.2); m._pc("key", "ctrl+c"); time.sleep(0.5)
            tudo = _clip()
            m._pc("clickat", g[0] + g[2] - 70, g[1] + int(g[3] * 0.55))        # tira a seleção
            i = tudo.rfind(SUFIXO)
            if i < 0:
                return ""
            return LIXO.sub("", tudo[i + len(SUFIXO):]).strip()
        except Exception:
            return ""

    t_fim = time.time() + 150
    antes, estavel = "", 0
    time.sleep(10.0)
    while time.time() < t_fim and not CANCEL.is_set():
        atual = _copiar_texto() if nome == "chatgpt" else ""
        if not atual:
            atual = _resposta()
        if atual and atual == antes and len(atual) > 3:
            estavel += 1
            if estavel >= 2:
                return atual[:3500]
        else:
            estavel = 0
        antes = atual
        time.sleep(4.0)
    if antes:
        return antes[:3500]
    raise TimeoutError(f"o {nome} não respondeu a tempo")


def t_nota(titulo="", texto="", **_):
    os.makedirs(DOCS, exist_ok=True)
    p = os.path.join(DOCS, "notas.md")
    with open(p, "a") as f:
        f.write(f"\n## {titulo or time.strftime('%d/%m %H:%M')}\n{texto}\n")
    return "nota salva em " + p


def t_criar_arquivo(caminho="", conteudo="", abrir=False, **_):
    """Cria ou sobrescreve um arquivo de texto, markdown, código, CSV, JSON ou HTML na pasta do dono (padrão: ~/Documentos/Friday/)."""
    raw = str(caminho or "").strip()
    if not raw:
        raw = f"nota-{time.strftime('%Y%m%d-%H%M%S')}.md"
    if not any(sep in raw for sep in ("/", "\\", "~")):
        os.makedirs(DOCS, exist_ok=True)
        p = os.path.realpath(os.path.join(DOCS, raw))
    else:
        p = os.path.realpath(os.path.expanduser(raw))
    home = os.path.realpath(os.path.expanduser("~"))
    if not p.startswith(home + os.sep) or _BLOQ.search(p):
        raise ValueError("caminho fora do permitido para criação de arquivo")
    ext = p.lower().rsplit(".", 1)[-1] if "." in os.path.basename(p) else ""
    if ext in ("docx", "xlsx", "pptx"):
        base_nome = os.path.splitext(os.path.basename(p))[0]
        return t_onlyoffice_criar(tipo=ext, nome=base_nome, conteudo=str(conteudo or ""))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    txt = str(conteudo or "")
    with open(p, "w", encoding="utf-8") as f:
        f.write(txt)
    if abrir and ext in ("md", "txt", "csv"):
        try:
            t_onlyoffice_abrir(caminho=p)
        except Exception:
            pass
    return f"arquivo criado em {p} ({len(txt)} caracteres)"


def t_resumo_emails(ops=None, fr=None, **_):
    itens = ops.mail_list(8, True)
    if not itens:
        return "nenhum e-mail novo"
    return "\n".join(f"- {str(i.get('de'))[:40]}: {str(i.get('assunto'))[:80]}" for i in itens)


def t_resumo_conversa(fr=None, **_):
    try:
        ls = open(os.path.join(MEM, "conversas.jsonl")).read().splitlines()[-30:]
        txt = "\n".join(f"{json.loads(l)['role']}: {json.loads(l)['text'][:160]}" for l in ls)
        return t_resumir(txt, fr=fr)
    except Exception as e:
        return "sem conversa: " + str(e)[:60]


def t_acao(t="", fr=None, ops=None, **kw):
    """qualquer ação do friday.run_action: abrir_app, janela, sistema, agenda, email, holo, manual, programar..."""
    a = {"t": t, **{k: v for k, v in kw.items() if k not in ("tool",)}}
    ok, msg = fr.run_action(a, ops)
    if not ok:
        raise RuntimeError(msg or "ação falhou")
    return msg or "feito"


_FT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ftools.py")


def _ftools(*args, timeout=120):
    """roda a CLI determinística ftools.py (processo separado: falha dela não derruba o agente)."""
    import sys
    r = subprocess.run([sys.executable, _FT, *map(str, args)], capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "erro": (r.stderr or r.stdout)[-300:]}


def t_analisar_extrato(caminho="", **_):
    d = _ftools("extrato", os.path.expanduser(str(caminho)))
    if not d.get("ok"):
        raise RuntimeError(d.get("erro", "falhou"))
    t_onlyoffice_abrir(d["arquivo"])
    return json.dumps(d, ensure_ascii=False)


def t_comando_sudo(comando="", motivo="", ops=None, **_):
    if ops is None:
        raise RuntimeError("política indisponível")
    from prom_ops import holo_show
    holo_show({"kind": "email", "para": "root (sudo)", "assunto": motivo or "Comando de administrador", "corpo": "$ " + str(comando),
               "status": "aguardando aprovação", "titulo": "Comando sudo", "ttl": 300})
    ok, msg = ops.gated("sudo.run", "root", f"sudo: {str(comando)[:100]}", {"comando": str(comando)})
    return msg if ok else "Pedi aprovação ao dono (comando no espelho). Ele diz aprovado e digita a senha na janela. Não tente de outro jeito."


def t_terminal(comando="", motivo="", ops=None, **_):
    """F7: terminal seguro — LEITURA roda e devolve a saída; ESCRITA_HOME/ROOT viram aprovação; NEGADO nunca roda."""
    import shell_seguro as ss
    if not ss.ativo():
        raise RuntimeError("terminal desligado (friday.json terminal:false)")
    c = ss.classificar(str(comando))
    if c["classe"] == "NEGADO":
        if ops is not None:
            ops.audit("shell.negado", "", str(comando)[:200], c["motivo"])
        raise RuntimeError("NEGADO: " + c["motivo"] + ". Não tente contornar; diga ao dono.")
    if c["classe"] == "LEITURA":
        r = ss.executar(str(comando))
        if ops is not None:
            ops.audit("shell.ler", "", c["exibir"][:200], f"código {r.get('codigo')}" if "codigo" in r else r.get("erro", ""))
        if "codigo" not in r:
            raise RuntimeError(r.get("erro", "falhou"))
        return f"[código {r['codigo']}] $ {c['exibir'][:200]}\n{r['saida'] or '(sem saída)'}"
    if ops is None:
        raise RuntimeError("política indisponível")
    from prom_ops import holo_show
    root = c["classe"] == "ROOT"
    cmd = c["sem_sudo"] if root else str(comando)
    holo_show({"kind": "email", "para": "root (sudo)" if root else "terminal", "assunto": motivo or ("Comando de administrador" if root else "Alterar arquivos"),
               "corpo": "$ " + (cmd if root else c["exibir"]), "status": "aguardando aprovação", "titulo": "Comando sudo" if root else "Terminal", "ttl": 300})
    if root:
        ok, msg = ops.gated("sudo.run", "root", f"sudo: {cmd[:100]}", {"comando": cmd})
    else:
        ok, msg = ops.gated("shell.escrever", "home", f"terminal: {c['exibir'][:100]}" + (f" ({motivo[:60]})" if motivo else ""), {"comando": cmd, "exibir": c["exibir"]})
    return msg if ok else ("Pedi aprovação ao dono (comando no espelho)." + (" Ele diz aprovado e digita a senha na janela." if root else
                           " Ele diz aprovado e eu rodo.") + " Não tente de outro jeito.")


def t_zap_ler(contato="", n=5, **_):
    """Lê as mensagens recentes de um contato ou lista as conversas no WhatsApp (ZapZap)."""
    try:
        import zap
        if not zap.available():
            zap.ensure_running()
        c = str(contato or "").strip()
        if c:
            r = zap.read_chat(c, int(n) if n else 5)
            if not r.get("ok"):
                return f"Falha ao ler conversa com {c}: {r.get('motivo', 'não encontrada')}"
            msgs = r.get("msgs", [])
            if not msgs:
                return f"Nenhuma mensagem encontrada na conversa com {r.get('conversa', c)}."
            linhas = []
            for m in msgs:
                quem = m.get("quem") or ("Você" if m.get("saida") else r.get("conversa", c))
                linhas.append(f"[{m.get('quando', '')}] {quem}: {m.get('texto', '')}")
            return f"Conversa com {r.get('conversa', c)}:\n" + "\n".join(linhas)
        else:
            s = zap.snapshot()
            if not s.get("ok"):
                return f"Falha ao obter conversas do WhatsApp: {s.get('motivo', 'erro')}"
            chats = s.get("chats", [])
            if not chats:
                return "Nenhuma conversa encontrada no WhatsApp."
            linhas = []
            for item in chats[:10]:
                nl = f" ({item['nao_lidas']} novas)" if item.get("nao_lidas") else ""
                linhas.append(f"- {item['nome']}{nl}: {item['previa']} [{item['hora']}]")
            return "Conversas no WhatsApp:\n" + "\n".join(linhas)
    except Exception as e:
        return f"Erro ao acessar WhatsApp: {e}"


def t_zap_enviar(contato="", mensagem="", fr=None, ops=None, pronto=False, **_):
    """Envia ou prepara mensagem no WhatsApp (ZapZap) para um contato.
    pronto=True: o texto já é o conteúdo (pesquisa). Não passa no redator, que trocava o fato por 'vou pesquisar'."""
    if not contato or not mensagem:
        raise RuntimeError("Contato e mensagem são obrigatórios.")
    if fr is None:                                       # nunca envia sem o portão de aprovação
        raise RuntimeError("Envio bloqueado: sem portão de aprovação.")
    acao = {"t": "zap", "op": "enviar", "contato": contato}
    if pronto:
        acao["texto"] = mensagem
    else:
        acao["intencao"] = mensagem
    ok, msg = fr.run_action(acao, ops)
    if not ok:
        raise RuntimeError(msg or "falha ao enviar mensagem no WhatsApp")
    return msg or f"Mensagem para {contato}: estado desconhecido (confira no WhatsApp)."


TOOLS = {
    "zap_ler": (t_zap_ler, '{"contato":"nome do contato (opcional)","n":5}', "lê as últimas mensagens de uma conversa no WhatsApp ou lista os chats recentes"),
    "zap_enviar": (t_zap_enviar, '{"contato":"nome do contato","mensagem":"texto"}', "envia ou prepara uma mensagem no WhatsApp (ZapZap) para um contato"),
    "pesquisar_web": (t_pesquisar_web, '{"consulta":"termos"}', "pesquisa na internet; devolve 5 resultados com trecho e URL"),
    "ler_pagina": (t_ler_pagina, '{"url":"https://..."}', "lê o texto de uma página web"),
    "ler_arquivo": (t_ler_arquivo, '{"caminho":"~/..."}', "lê txt/md/pdf/docx/xlsx da pasta do dono"),
    "resumir": (t_resumir, '{"texto":"..."}', "resume um texto longo em tópicos"),
    "onlyoffice_criar": (t_onlyoffice_criar, '{"tipo":"docx|xlsx|pptx","nome":"titulo","conteudo":"linhas; use # para títulos/slides"}',
                         "cria um documento/planilha/apresentação e abre no ONLYOFFICE"),
    "onlyoffice_abrir": (t_onlyoffice_abrir, '{"caminho":"..."}', "abre um arquivo existente no ONLYOFFICE"),
    "abrir_app": (t_abrir_app, '{"nome":"ZapZap|Chromium|Spotify|Discord|ONLYOFFICE|..."}',
                  "abre QUALQUER app instalado no PC usando o cursor/teclado visíveis (use listar_apps se não souber o nome)"),
    "listar_apps": (t_listar_apps, "{}", "lista os apps instalados no PC"),
    "abrir_site": (t_abrir_site, '{"url":"site.com","busca":"termos opcionais"}', "abre um site ou pesquisa no navegador Chromium"),
    "tocar_youtube": (t_tocar_youtube, '{"pesquisa":"nome da música ou vídeo"}', "pesquisa no YouTube e toca DIRETO no Chromium sem anúncios"),
    "pesquisar_youtube": (t_pesquisar_youtube, '{"pesquisa":"termos da busca"}', "abre os resultados de busca no YouTube no Chromium"),
    "pesquisa_para_documento": (t_pesquisa_para_documento, '{"consulta":"tema","tipo":"docx|xlsx|pptx","nome":"titulo"}',
                  "PESQUISA na web, lê as páginas e CRIA planilha/documento/apresentação com o resultado, aberto no ONLYOFFICE (use para 'pesquise X e faça planilha/docx')"),
    "ver_tela": (t_ver_tela, "{}", "OCR: devolve a janela em foco e o texto visível na tela com posições (use ANTES de clicar)"),
    "clicar_elemento": (t_clicar_elemento, '{"descricao":"o que clicar, em inglês ou português: ex. botão azul Enviar, ícone de engrenagem, campo de busca"}', "visão local: acha QUALQUER elemento (mesmo sem texto) e clica com o cursor; use quando clicar_texto falhar ou for ícone/imagem"),
    "apontar": (t_apontar, '{"descricao":"elemento"}', "move o cursor até o elemento sem clicar (mostrar ao dono / conferir)"),
    "clicar_texto": (t_clicar_texto, '{"texto":"texto exato visível"}', "clica com o cursor no texto visível (botão, link, aba)"),
    "digitar": (t_digitar, '{"texto":"...","enter":false}', "digita no campo/janela em foco"),
    "tecla": (t_tecla, '{"teclas":"ctrl+l | ctrl+t | enter | tab | alt+left"}', "pressiona atalhos de teclado"),
    "rolar": (t_rolar, '{"n":3}', "rola a página (n>0 desce, n<0 sobe)"),
    "pular_anuncio": (t_pular_anuncio, '{"espera":15}', "pula o anúncio do YouTube (espera até 'espera' s o botão aparecer)"),
    "pc_perfil": (t_pc_perfil, "{}", "resumo do hardware, sistema, apps e atalhos do PC do dono"),
    "consultar_ia": (t_consultar_ia, '{"pergunta":"pedido completo e claro","site":"chatgpt|claude|gemini|perplexity"}',
                     "ESCALA para a IA do dono no navegador (ChatGPT por padrão, já logado): use só para PERGUNTAS complexas "
                     "(textos longos, análise, matemática). NUNCA para programar/criar arquivo/consertar sistema nem quando o dono diz "
                     "'Claude' ou 'modo dev': isso é acao {\"t\":\"programar\",\"pedido\":...} (Claude CLI no terminal). Devolve a resposta; depois salve com nota/onlyoffice_criar"),
    "analisar_extrato": (t_analisar_extrato, '{"caminho":"~/Downloads/extrato.csv|.ofx|.pdf"}',
                         "analisa extrato bancário (CSV/OFX/PDF): categoriza gastos, totais por categoria/mês, cria planilha e abre no ONLYOFFICE; devolve resumo JSON"),
    "comando_sudo": (t_comando_sudo, '{"comando":"pacman -S --noconfirm pacote","motivo":"por quê"}',
                     "roda comando como administrador (sudo) APÓS aprovação do dono, que digita a senha; destrutivos são bloqueados"),
    "terminal": (t_terminal, '{"comando":"ls -la ~/Downloads","motivo":"por quê, em linguagem simples"}',
                 "terminal do PC: leitura (ls, cat, head, grep, find, df, du, free, ps, ip a, git status, journalctl --user -n 50, pacman -Q) roda na hora "
                 "e devolve a saída (confira!); o que altera arquivos pede aprovação do dono (rm vai p/ a lixeira); sem $(...), sem shell -c"),
    "nota": (t_nota, '{"titulo":"","texto":""}', "guarda uma nota em ~/Documentos/Friday/notas.md"),
    "criar_arquivo": (t_criar_arquivo, '{"caminho":"resumo.md","conteudo":"texto completo","abrir":false}',
                      "cria um arquivo (.txt, .md, .csv, .json, .html, .py, .docx, .xlsx, .pptx) em ~/Documentos/Friday/ ou caminho dentro de ~"),
    "resumo_emails": (t_resumo_emails, "{}", "lista remetente e assunto dos e-mails novos"),
    "resumo_conversa": (t_resumo_conversa, "{}", "resume nossa conversa recente"),
    "camera_ver": (t_camera_ver, '{"pergunta":"o que procurar/descrever"}', "CÂMERA DO QUARTO (com motor): descreve o que ela vê agora"),
    "camera_olhar": (t_camera_olhar, '{"direcao":"esquerda|direita|cima|baixo|centro|<posição salva>"}', "CÂMERA DO QUARTO: gira para um lado ou posição salva"),
    "camera_em_volta": (lambda **_: _ptz().get_ptz().olhar_em_volta(), "{}", "CÂMERA DO QUARTO: gira pelo quarto inteiro e descreve o que viu"),
    "camera_procurar": (lambda alvo="", **_: _ptz().get_ptz().procurar(alvo), '{"alvo":"objeto ou pessoa"}',
                        "CÂMERA DO QUARTO: gira até achar o objeto/pessoa e deixa apontada; diz onde achou"),
    "camera_zoom": (lambda fator=2.0, alvo="", pergunta="O que se vê nesta imagem ampliada?", **_: _ptz().get_ptz().zoom(fator, alvo, pergunta),
                    '{"fator":2,"alvo":"pessoa|objeto (opcional)","pergunta":"o que quer saber"}',
                    "CÂMERA DO QUARTO: zoom digital (até 4x, imagem 1280x720) centrado no alvo e responde sobre o recorte"),
    "camera_apontar": (lambda **_: _camera_apontar(),
                       "{}", "CÂMERA DO QUARTO: vira direto para a pessoa que a webcam da porta/câmera do notebook estão vendo"),
    "camera_onde": (lambda **_: _ptz().G.mundo_resumo(), "{}", "CÂMERAS FIXAS: quantas pessoas veem e para onde a câmera com motor apontaria"),
    "camera_modo": (lambda modo="livre", **_: (lambda r: r[1])(_ptz().comando({"op": modo})),
                    '{"modo":"seguir|vigiar|auto|livre"}', "CÂMERA DO QUARTO: seguir o dono, vigiar o quarto, automático ou parar"),
    "cel_acordar": (lambda **_: (lambda e: f"tela {'acesa' if e.get('tela') else 'APAGADA'}, {'bloqueado' if e.get('bloqueado') else 'desbloqueado'}")(_cel().acordar()),
                    "{}", "CELULAR: acende a tela (pela ponte do app)"),
    "cel_desbloquear": (lambda **_: _cel().desbloquear(), "{}", "CELULAR: acende e desbloqueia com o PIN do dono"),
    "cel_friday": (lambda pedido="", **_: _cel().pedir_local(pedido), '{"pedido":"o que fazer no celular, em português"}',
                   "CELULAR: entrega a tarefa inteira à Friday LOCAL do celular (ela abre apps, pesquisa, cria documento, alarme, navega na tela "
                   "e responde o resultado). Prefira esta para tarefas no celular com vários passos."),
    "cel_ver": (lambda **_: _cel().ver(), "{}", "CELULAR do dono: lê a tela do celular (texto + posições). Use antes de tocar"),
    "cel_tocar_texto": (lambda texto="", **_: _cel().tocar_texto(texto), '{"texto":"texto visível"}', "CELULAR: toca no texto visível (botão, app, item)"),
    "cel_tocar": (lambda x=0, y=0, **_: _cel().tocar(x, y), '{"x":0,"y":0}', "CELULAR: toca na posição (coordenadas do cel_ver)"),
    "cel_segurar": (lambda x=0, y=0, **_: _cel().segurar(x, y), '{"x":0,"y":0}', "CELULAR: toque longo"),
    "cel_digitar": (lambda texto="", enter=False, **_: _cel().digitar(texto, enter), '{"texto":"...","enter":false}', "CELULAR: digita no campo em foco"),
    "cel_tecla": (lambda tecla="voltar", **_: _cel().tecla(tecla), '{"tecla":"voltar|inicio|recentes|notificacoes|enter|apagar"}', "CELULAR: voltar, tela inicial, recentes, notificações, enter"),
    "cel_rolar": (lambda n=3, **_: _cel().rolar(n), '{"n":3}', "CELULAR: rola (n>0 desce, n<0 sobe)"),
    "cel_espelhar": (lambda on=True, **_: _cel_espelhar(on), '{"on":true}', "CELULAR: mostra/fecha a tela do celular ao vivo no holograma"),
    "cel_abrir_app": (lambda nome="", **_: _cel().abrir_app(nome), '{"nome":"WhatsApp|Instagram|Configurações|..."}', "CELULAR: abre um app nativo pelo nome"),
    "navegar_web": (t_navegar_web, '{"url":"https://...","objetivo":"o que encontrar ou pesquisar"}',
                    "navega na web de forma autônoma e adaptativa: visita páginas, segue links relevantes ao objetivo, extrai dados e sintetiza"),
    "tarefa_adaptativa": (t_tarefa_adaptativa, '{"objetivo":"o que resolver","contexto":"detalhes"}',
                          "resolve tarefas abertas, complexas ou não pré-programadas executando e adaptando os passos autonomamente"),
    "analisar_dificuldade_tela": (t_analisar_dificuldade_tela, '{"janela_id":"id opcional"}',
                                 "analisa a tela ativa para identificar erros de compilação, exceções, stacktraces ou falhas que estão travando o usuário"),
    "reconhecer_emocao": (t_reconhecer_emocao, '{"fonte":"camera_notebook|camera_porta|camera_quarto"}',
                          "reconhece a expressão facial, emoção e postura do usuário (feliz, frustrado, cansado, surpreso, focado, neutro)"),
    "reconhecer_gestos": (t_reconhecer_gestos, '{"fonte":"camera_notebook|camera_porta|camera_quarto"}',
                          "reconhece gestos manuais ativos (joinha, pare, polegar_baixo, paz, apontar, ok, rock, tres_dedos)"),
    "percepcao_situacional": (t_percepcao_situacional, "{}",
                             "diagnóstico 360° imediato: tela (erros/dificuldades), usuário (emoção/gestos) e saúde do sistema"),
    "orquestrar_tarefa_continua": (t_orquestrar_tarefa_continua, '{"id":"","titulo":"nome da tarefa","instrucao":"o que fazer ou monitorar","tipo":"continua|intermitente|longa|rapida","intervalo_s":60}',
                                  "orquestra tarefas gerais contínuas ou de longa duração com checkpoints persistidos em disco"),
    "consultar_objetivos_ativos": (t_consultar_objetivos_ativos, "{}",
                                  "lista os objetivos e tarefas em execução orquestrada contínua ou intermitente"),
    "parar_objetivo": (t_parar_objetivo, '{"id":"id_do_objetivo"}',
                      "pausa ou cancela um objetivo contínuo em execução"),
    "operar_outra_ia": (t_operar_outra_ia, '{"ia":"claude|gemini|openai|ollama","prompt":"pedido","modelo":"opcional"}',
                        "opera outras IAs locais ou em nuvem para resolver tarefas e sub-tarefas"),
    "criar_ou_modificar_tela": (t_criar_ou_modificar_tela, '{"nome":"nome_tela","tipo":"qml|html","codigo":"conteúdo do código","titulo":"título"}',
                               "cria ou modifica dinamicamente telas internas QML do sistema ou HTML5 HUD Web"),
    "pensar_estrategia": (t_pensar_estrategia, '{"objetivo":"meta","contexto":"detalhes"}',
                         "executa raciocínio tático de pré-ação avaliando contexto, tela, riscos e alternativas"),
    "acao": (t_acao, '{"t":"abrir_app|janela|sistema|agenda|email|holo|manual|programar","...":"parâmetros da ação"}',
             "executa uma ação no PC (abrir app, foco de janela, volume, agenda, e-mail, holograma, programar; NÃO use manual para documentos/planilhas)"),
    "orquestra_iniciar": (t_orquestra_iniciar, '{"pedido":"tarefa completa"}',
                          "sessão longa (faz X por horas): pensa, grava o plano, executa o primeiro passo e segue sozinha em segundo plano"),
    "orquestra_fila": (t_orquestra_fila, '{"pedido":"outra tarefa","quando":"vazio = agora; +30m, +2h, +1d, amanhã 9h, sexta 14h, daqui a 2 horas ou 2026-10-19T09:00"}',
                       "agenda um objetivo longo para depois (amanhã às 9h faça Y, daqui 2 horas faça Z) ou põe na fila; só um fica ativo"),
    "orquestra_status": (t_orquestra_status, "{}",
                         "mostra a sessão longa do orquestrador (passo atual/total), a fila com horários e se está pausado"),
    "orquestra_pausar": (t_orquestra_pausar, '{"id":"vazio = orquestrador inteiro; ou id de um objetivo contínuo"}',
                         "pausa o orquestrador (sessão longa e fila ficam salvas) ou um objetivo contínuo pelo id"),
    "orquestra_retomar": (t_orquestra_retomar, '{"id":"vazio = orquestrador inteiro; ou id de um objetivo contínuo"}',
                          "retoma o orquestrador pausado (ou a sessão que esperava o dono) ou um objetivo contínuo pelo id"),
}

# ------------------------------------------------------------------ F6: verificação do EFEITO REAL de cada ferramenta
LEITURA = {"pesquisar_web", "navegar_web", "tarefa_adaptativa", "analisar_dificuldade_tela", "reconhecer_emocao", "reconhecer_gestos",
           "percepcao_situacional", "consultar_objetivos_ativos", "orquestra_status", "pensar_estrategia", "operar_outra_ia", "ler_pagina", "ler_arquivo", "resumir", "ver_tela", "listar_apps", "pc_perfil", "resumo_emails",
           "resumo_conversa", "cel_ver", "consultar_ia", "apontar", "camera_ver", "camera_em_volta", "camera_procurar", "camera_zoom", "camera_onde", "zap_ler"}           # só leem: o "final" delas é a própria resposta
VISUAIS = {"clicar_texto", "clicar_elemento", "digitar", "tecla", "rolar", "abrir_site", "abrir_app", "acao", "pular_anuncio"}
_NEG = re.compile(r"\b(n[ãa]o consegui|n[ãa]o deu|falhou|n[ãa]o achei|n[ãa]o encontrei|travei|n[ãa]o foi poss[íi]vel)\b", re.I)


def _nrm(t):
    import unicodedata
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", str(t or "").lower()).encode("ascii", "ignore").decode())


def _janelas():
    """niri: {id: (app_id, título)} + id em foco"""
    try:
        ws = json.loads(subprocess.run(["niri", "msg", "-j", "windows"], capture_output=True, text=True, timeout=3).stdout or "[]")
    except Exception:
        return {}, None
    return {w.get("id"): (str(w.get("app_id") or ""), str(w.get("title") or "")) for w in ws}, \
        next((w.get("id") for w in ws if w.get("is_focused")), None)


def _dhash(img, n=16):
    """dHash n*n bits de uma imagem em tons de cinza (numpy)"""
    import cv2
    s = cv2.resize(img, (n + 1, n), interpolation=cv2.INTER_AREA)
    return int("".join("1" if a > b else "0" for a, b in zip(s[:, :-1].flatten(), s[:, 1:].flatten())), 2)


def _dhash_tela():
    try:
        import cv2
        import numpy as np
        raw = subprocess.run(["grim", "-s", "0.25", "-t", "ppm", "-"], capture_output=True, timeout=4).stdout
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        return _dhash(img) if img is not None else None
    except Exception:
        return None


def _bits(a, b):
    return bin(a ^ b).count("1") if a is not None and b is not None else None


def _snap(nome):
    """estado antes/depois de uma ação: janelas (niri), foco e, nas visuais, o dHash da tela"""
    js, foco = _janelas()
    return {"t": time.time(), "janelas": js, "foco": foco, "dh": _dhash_tela() if nome in VISUAIS else None, "ocr": ""}


def _texto_doc(caminho):
    """texto puro de docx/xlsx/pptx (XML do zip) ou de md/txt"""
    import zipfile
    try:
        if caminho.endswith((".md", ".txt", ".csv")):
            return open(caminho, errors="ignore").read()
        z = zipfile.ZipFile(caminho)
        nomes = [n for n in z.namelist() if re.match(r"(word/document|xl/sharedStrings|xl/worksheets/sheet\d+|ppt/slides/slide\d+)\.xml$", n)]
        return " ".join(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore")) for n in nomes)
    except Exception:
        return ""


def v_arquivo(caminho, minimo=2048):
    """arquivo existe, tem > 2 KB e texto de verdade dentro (docx vazio já tem ~36 KB de modelo)"""
    if not caminho or not os.path.exists(caminho):
        return False, f"arquivo não existe: {caminho or '(sem caminho)'}"
    tam = os.path.getsize(caminho)
    if tam <= minimo:
        return False, f"arquivo pequeno demais ({tam} bytes)"
    txt = re.sub(r"\s+", " ", _texto_doc(caminho)).strip()
    if len(txt) < 40:
        return False, f"arquivo sem conteúdo ({len(txt)} caracteres de texto)"
    return True, f"{os.path.basename(caminho)}: {tam // 1024} KB, {len(txt)} caracteres de texto"


def v_janela(alvo, antes, depois):
    """app abriu: janela NOVA ou janela em foco com o nome do app (app_id/título)"""
    a = _nrm(alvo)
    novas = [v for k, v in depois["janelas"].items() if k not in antes["janelas"]]
    foco = depois["janelas"].get(depois["foco"], ("", ""))
    ult = lambda v: _nrm(str(v[0]).split(".")[-1])                 # "org.gnome.Nautilus" -> "nautilus"
    casa = lambda v: bool(a) and (a in _nrm(v[0]) or a in _nrm(v[1]) or (len(ult(v)) >= 3 and ult(v) in a))
    if any(casa(v) for v in novas) or casa(foco):
        return True, f"janela {foco[0] or novas[0][0]} em foco"
    for wid, v in depois["janelas"].items():
        if casa(v):
            try:
                subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(wid)], capture_output=True, timeout=2)
            except Exception:
                pass
            return True, f"janela {v[0]} aberta e focada"
    if novas:
        return True, f"janela nova: {novas[0][0]}"
    if depois["foco"] is not None and depois["foco"] != antes["foco"]:
        return True, f"foco mudou para {foco[0] or '?'}"
    return False, f"nenhuma janela nova nem em foco com '{alvo}' (foco: {foco[0] or '?'})"


def v_tela_mudou(antes, depois, minimo=4):
    """diferença de tela por dHash (256 bits) ou troca de foco/título"""
    d = _bits(antes.get("dh"), depois.get("dh"))
    fa, fd = antes["janelas"].get(antes["foco"]), depois["janelas"].get(depois["foco"])
    if fa != fd:
        return True, f"foco/título mudou para {(fd or ('?', ''))[0]} — {(fd or ('', ''))[1][:40]}"
    if d is not None and d >= minimo:
        return True, f"tela mudou ({d} bits)"
    if "novo texto:" in depois.get("ocr", "") and "nada novo" not in depois.get("ocr", ""):
        return True, "texto novo na tela (OCR)"                 # mudança pequena (caixa marcada, campo) que o dHash não pega
    return (None, "sem captura de tela") if d is None else (False, f"a tela não mudou ({d} bits)")


def v_aprovacao(ops, antes, acoes=("wa.send_chat", "sudo.run", "mail.send")):
    try:
        it = [i for i in ops.approvals() if i.get("acao") in acoes and float(i.get("criado", 0)) >= antes["t"] - 1]
    except Exception:
        return None, "sem acesso às aprovações"
    return (True, f"aprovação {it[-1]['id']} criada ({it[-1]['estado']})") if it else (False, "nenhuma aprovação foi criada")


def _v_digitar(a, r, an, de, ops):
    t = _nrm(str(a.get("texto", ""))[:24])
    if t and t in _nrm(de.get("ocr", "")):
        return True, "texto digitado aparece na tela"
    return v_tela_mudou(an, de, 2)


def _v_doc(a, r, an, de, ops):
    m = re.search(r"(/[^\n:]+?\.(?:docx|xlsx|pptx|md))\b", str(r))
    return v_arquivo(m.group(1) if m else "")


def _v_zap(a, r, an, de, ops):
    if str(r).startswith("Enviado para"):                 # só o envio REAL (PENDENTE/"preparada" não contam)
        return True, "enviado (política automática)"
    return v_aprovacao(ops, an)


def _v_abrir_site(a, r, an, de, ops):
    ok, ev = v_tela_mudou(an, de)
    if ok:
        return ok, ev
    if "navegador aberto" in str(r):
        ok_j, ev_j = v_janela("chromium", an, de)
        if ok_j:
            return True, "aba aberta no Chromium (" + ev_j + ")"
    return ok, ev


VERIF = {             # nome da ferramenta -> f(args, resultado, antes, depois, ops) -> (ok True/False/None, evidência)
    "abrir_app": lambda a, r, an, de, ops: v_janela(a.get("nome", ""), an, de),
    "acao": lambda a, r, an, de, ops: (v_janela(a.get("nome") or a.get("app") or a.get("alvo") or "", an, de)
                                       if a.get("t") in ("abrir_app", "janela") else (None, "")),
    "abrir_site": _v_abrir_site,
    "clicar_texto": lambda a, r, an, de, ops: v_tela_mudou(an, de),
    "clicar_elemento": lambda a, r, an, de, ops: v_tela_mudou(an, de),
    "tecla": lambda a, r, an, de, ops: v_tela_mudou(an, de, 2),
    "rolar": lambda a, r, an, de, ops: v_tela_mudou(an, de, 2),
    "digitar": _v_digitar,
    "onlyoffice_criar": _v_doc,
    "pesquisa_para_documento": _v_doc,
    "nota": lambda a, r, an, de, ops: v_arquivo(os.path.join(DOCS, "notas.md"), 0),
    "criar_arquivo": lambda a, r, an, de, ops: (lambda m: v_arquivo(m.group(1), 0) if m else (False, "caminho não retornado"))(re.search(r"(/[^\n:(]+)", str(r))),
    "zap_enviar": _v_zap,
    "comando_sudo": lambda a, r, an, de, ops: v_aprovacao(ops, an, ("sudo.run",)),
    "terminal": lambda a, r, an, de, ops: (v_aprovacao(ops, an, ("sudo.run", "shell.escrever")) if str(r).startswith(("Pedi aprovação", "PENDENTE"))
                                           else (None, "")),       # leitura: o próprio agente confere a saída
}

SCHEMA_OBJ = {"type": "object", "properties": {"cumprido": {"type": "boolean"}, "falta": {"type": "string"}},
              "required": ["cumprido", "falta"]}


def checar_objetivo(pedido, evidencias, passos, final, fr):
    """fim do agente: o pedido foi cumprido SEGUNDO AS EVIDÊNCIAS (não segundo o que o modelo diz)? -> (bool|None, falta)"""
    d = fr.llm("Você confere se um agente cumpriu o pedido do dono. Use SÓ as evidências verificadas e os resultados das ferramentas; "
               "o que o agente AFIRMA sem evidência não conta. Pedido de informação está cumprido se a resposta traz a informação. "
               "Os passos aparecem resumidos (cortados por espaço): NÃO reprove só porque uma saída parece cortada aqui. "
               'Responda JSON {"cumprido": true|false, "falta": "o que falta, curto; \"\" se cumprido"}.',
               f"Pedido: {pedido}\nEvidências verificadas: {'; '.join(evidencias[-5:]) or 'nenhuma'}\n"
               f"Últimos passos:\n" + "\n".join(p[:200] for p in passos[-4:-1]) + ("\n" + passos[-1][:1500] if passos else "")
               + f"\nResposta final do agente: {str(final)[:600]}",
               None, True, 80, 0.1, 40, schema=SCHEMA_OBJ)
    if not isinstance(d, dict) or not isinstance(d.get("cumprido"), bool):
        return None, ""
    return d["cumprido"], str(d.get("falta") or "")[:160]


# F6: ferramentas por domínio (encolhe o prompt; uma ferramenta fora do domínio ainda é aceita se o modelo pedir)
_CEL = {n for n in ("cel_acordar", "cel_desbloquear", "cel_ver", "cel_tocar_texto", "cel_tocar", "cel_segurar", "cel_digitar", "cel_tecla",
                    "cel_rolar", "cel_espelhar", "cel_abrir_app")}
DOMINIOS = {
    "celular": _CEL | {"resumir", "nota", "criar_arquivo", "pesquisar_web"},
    "arquivo": {"ler_arquivo", "criar_arquivo", "onlyoffice_criar", "onlyoffice_abrir", "pesquisa_para_documento", "analisar_extrato", "pesquisar_web",
                "ler_pagina", "resumir", "nota", "abrir_app", "ver_tela", "consultar_ia", "terminal", "zap_enviar", "acao"},
    "web": {"pesquisar_web", "ler_pagina", "resumir", "abrir_site", "ver_tela", "clicar_texto", "clicar_elemento", "apontar", "digitar",
            "tecla", "rolar", "pular_anuncio", "consultar_ia", "pesquisa_para_documento", "criar_arquivo", "nota", "abrir_app", "zap_enviar", "zap_ler", "acao"},
    "zap": {"zap_ler", "zap_enviar", "pesquisar_web", "ler_pagina", "resumir", "consultar_ia", "abrir_app", "nota", "criar_arquivo", "acao"},
}


def dominio(text):
    """celular > arquivo > web > zap > pc (reusa as regex que já existem: CELULAR_RE, DOCW, NAV/PESQ/YT)"""
    t = text or ""
    if CELULAR_RE.search(t):
        return "celular"
    if DOCW.search(t) or re.search(r"\b(arquiv\w+|txt|markdown|\.md\b|\.csv\b|\.json\b|relat[óo]rio)\b", t, re.I):
        return "arquivo"
    if re.search(r"\b(zap|whatsapp|wpp|msgs?|mensagens?|conversa|áudios?)\b", t, re.I):
        return "zap"
    if re.search(r"\b(?:mand\w+|envi\w+|encaminh\w+|repass\w+)\b.*?\b(?:para|pra|pro)\b", t, re.I) and not re.search(r"\b(email|e-mail|correio|arquivo|pasta)\b", t, re.I):
        return "zap"
    if NAV.search(t) or PESQ.search(t) or YT.search(t):
        return "web"
    return "pc"


_DADOS = {"terminal", "ler_arquivo", "ler_pagina", "cel_ver", "ver_tela"}     # ferramentas cuja saída É a resposta: não cortar


def _passos_prompt(passos):
    """F6: só os 3 últimos passos; os antigos com 250 caracteres, o último com 1500 — e saídas de dados (terminal, arquivo...) com 2500"""
    ult = passos[-3:]
    dado = lambda p: p.startswith(tuple(f"[{n}] ok" for n in _DADOS))
    return [p[:2500] if dado(p) else p[:250] for p in ult[:-1]] + [ult[-1][:2500 if dado(ult[-1]) else 1500]] if ult else []


SYSTEM = """Você é o cérebro da F.R.I.D.A.Y. (assistente local, pt-BR, séria e com humor seco). Para cumprir o pedido use FERRAMENTAS, uma por vez.
Responda SOMENTE JSON, sempre um destes dois formatos:
 {{"ferramenta":"nome","args":{{...}}}}                    -> executa e você verá o resultado
 {{"final":"frase curta e natural para falar em voz alta (1-3 frases, sem markdown)","pose":"neutro|apresentar|confirmar|pensando|surpreso","humor":"neutro|alegre|empolgado|carinhoso|confiante|curioso|surpreso|pensativo|serio|preocupado|triste|irritado|assustado"}}
Ferramentas:
{ferramentas}
Regras: pesquisa = pesquisar_web, depois ler_pagina do melhor link se precisar, depois resumir. Para criar documento escreva você mesmo o conteúdo
completo em "conteudo". Não invente fatos: só o que as ferramentas devolveram. Se uma ferramenta falhar, replaneje na tela (ver_tela, cursor, teclado) e tente outro caminho. Não encerre no primeiro erro. Shell só depois que a tela não alcançou o alvo.
No "final" diga o que fez e o essencial do resultado (nunca leia URLs inteiras). Máximo {max} passos.
CELULAR: se o pedido for no CELULAR do dono, use SÓ as ferramentas cel_* (cel_desbloquear se a tela estiver apagada/bloqueada, cel_abrir_app, cel_ver, cel_tocar_texto, cel_digitar, cel_tecla, cel_rolar; cel_espelhar para mostrar a tela dele ao vivo no holograma);
sempre cel_ver depois de cada ação para conferir. Nunca pague, transfira, apague ou mexa em senha no celular: pare e diga que é com o dono.
RECEITAS: (1) abrir app = abrir_app (nunca digite o nome no terminal). (2) site/pesquisa visível = abrir_site; depois ver_tela para conferir.
(3) tarefa no navegador: abrir_site -> ver_tela -> clicar_texto (texto EXATO visto) -> digitar/tecla -> ver_tela p/ confirmar -> final.
(4) YouTube: abrir_site com a URL do vídeo/pesquisa; se aparecer anúncio use pular_anuncio {{"espera":15}}. (5) "pesquise X e faça planilha/docx/slides"
= pesquisa_para_documento (1 chamada). (6) Nunca clique em enviar/pagar/apagar/senha/desligar/reiniciar: pare e diga que é com o dono.
(7) Nunca use o canto superior direito da tela (botão de energia). (8) Arquivos, pastas, disco, processos, pacotes ou estado do PC = terminal (leitura roda direto, ex.: ls -1 ~/Downloads para nomes, du -sh ~/Downloads, df -h /); responda com o que o terminal DEVOLVEU, nunca de cabeça; para alterar arquivos o terminal pede aprovação ao dono. (9) Se não for capaz de fazer sozinha (código, texto longo, análise), use consultar_ia (ChatGPT do dono) e aproveite a resposta; se um site/ferramenta falhar, tente outra (claude, gemini, perplexity) antes de desistir. (8) Se clicar_texto falhar ou o alvo for ícone/imagem, use clicar_elemento (visão local). Qualquer app vale, não só navegador. Antes de clicar, ver_tela; se não achar o texto, role (rolar) e olhe de novo.
(10) WHATSAPP / ZAPZAP: Para ler conversas ou extrair dados (datas, horários, recados), use zap_ler {{"contato":"Nome do Contato", "n":5}}. Para repassar, responder ou encaminhar dados para outro contato, use zap_enviar {{"contato":"Nome do Destinatário", "mensagem":"resumo claro com as informações extraídas da conversa lida"}}. Nunca invente datas ou mensagens que não estavam na saída do zap_ler.
PC DO DONO: {perfil}
{licoes}
Contexto: {ctx}"""


def _prompt(ctx, dom="pc"):
    _ok = DOMINIOS.get(dom)
    try:
        import shell_seguro as _ss
        _sem = set() if _ss.ativo() else {"terminal"}           # F7: friday.json "terminal": false tira a ferramenta
    except Exception:
        _sem = {"terminal"}
    fer = "\n".join(f"- {n}: {a} — {d}" for n, (_f, a, d) in TOOLS.items()
                    if (n in _ok if _ok else n not in _CEL) and n not in _sem)           # F6: só as ferramentas do domínio do pedido
    L = licoes()[-8:]
    lic = ("Lições aprendidas (siga):\n" + "\n".join("- " + x["txt"] for x in L)) if L else ""
    perfil = " ".join(t_pc_perfil().split())[:1100] if dom == "pc" else "(omitido)"
    out = SYSTEM.format(ferramentas=fer, max=MAX_STEPS, licoes=lic, ctx=ctx or "—", perfil=perfil)
    if dom != "celular":                                   # F6: regras do celular só em pedido de celular...
        out = re.sub(r"CELULAR: se o pedido.*?com o dono\.\n", "", out, flags=re.S)
    else:                                                  # ...e as receitas de PC/navegador só fora dele
        out = re.sub(r"RECEITAS: .*?olhe de novo\.\n", "", out, flags=re.S)
    return out


NAV = re.compile(r"\b(cr[ôo]m\w*|c[ôo]m[ie]um|chrom\w*|navegador|google|guia|aba|internet)\b", re.I)
DOCW = re.compile(r"\b(planilh\w+|docx|document\w*|apresenta[çc][ãa]o|slides?|only\s*office|word|excel)\b", re.I)
PESQ = re.compile(r"\b(pesquis\w+|busc\w+|procur\w+)\b", re.I)


YT = re.compile(r"\b(you\s?tube|yutube|ioutube|youtub\w*|clipe|m[úu]sica|v[ií]deo)\b", re.I)
TOCAR = re.compile(r"\b(colo[cq]\w+|toqu\w+|toc[ae]\w*|ponh\w+|bot[ae]\w*|reproduz\w+|execut\w+|assist\w+|p[õo]e)\b", re.I)


def _midia_direta(text, fr, ops, progress=None):
    """'abra o YouTube e coloque a música mais famosa do X' / 'toque Y': acha o vídeo (yt-dlp) e ABRE no Chromium com cursor/teclado."""
    t = (text or "").strip()
    if not ((YT.search(t) or NAV.search(t) or re.search(r"para\s+(?:tocar|ouvir|assistir)", t, re.I))
            and (TOCAR.search(t) or re.search(r"you\s?tube|yutube", t, re.I))):
        return None
    if PESQ.search(t) and not YT.search(t):
        return None                                     # "pesquise X no chromium" é pesquisa comum, não mídia
    consulta, tocar = "", bool(TOCAR.search(t))
    m = re.search(r"(?:mais\s+(?:famos\w+|conhecid\w+|tocad\w+|popular\w*|ouvid\w+)|maior\s+sucesso|hit\s+mais\s+\w+)\s+(?:d[aoe]s?|pel[ao]s?|do|da)\s+(.+)$", t, re.I)
    if m:
        consulta, tocar = m.group(1).strip(" .!?") + " música mais famosa", True
    else:
        q = t.strip(" .!?,")
        q = re.sub(r"(?i)\b(?:no|na|pelo|do|da|em|para|pro|pra)?\s*(?:you\s?tube|yutube|chrom\w+|navegador|google)\b", " ", q)
        q = re.sub(r"(?i)\b(?:na\s+barra\s+de\s+pesquisa|na\s+barra\s+superior|na\s+pesquisa)\b", " ", q)
        q = re.sub(r"(?i)\s*(?:e\s+)?(?:colo[cq]\w*|toqu\w*|toc[ae]\w*|ponh\w*|reproduz\w*|execut\w*|assist\w*|p[õo]e)\s*(?:a\s+m[úu]sica|o\s+v[ií]deo|o\s+clipe|a\s+can[çc][ãa]o)?\s*$", "", q)
        for _ in range(6):
            q = re.sub(r"^[^\w]+", "", q)
            q = re.sub(r"(?i)^\s*(?:agora\s+)?(?:navegu\w*|entr\w*|abr\w*|acesse|v[aá]|colo[cq]\w*|toqu\w*|toc[ae]\w*|ponh\w*|p[õo]e|bot[ae]\w*|reproduz\w*|execut\w*|assist\w*|pesquis\w*|busc\w*|procur\w*)(?!\w)\s*", "", q)
            q = re.sub(r"^[^\w]+", "", q)
            q = re.sub(r"(?i)^\s*(?:para|pro|pra|o|a|os|as|um|uma|no|na|nos|nas|do|da|dos|das|em|e|de|que|com)\s+", "", q)
            q = re.sub(r"^[^\w]+", "", q)
            q = re.sub(r"(?i)^\s*(?:a|o|uma?|essa|esse)\s+(?:m[úu]sica|v[ií]deo|clipe|can[çc][ãa]o)\s+(?:d[aoe]s?|chamad[ao])?\s*", "", q)
            q = re.sub(r"(?i)^\s*(?:m[úu]sica|v[ií]deo|clipe|can[çc][ãa]o)\s+(?:d[aoe]s?|chamad[ao])?\s*", "", q)
        consulta = re.sub(r"\s+", " ", q).strip(" .!?,")
        # 16/10: "coloca aí o YouTube" pesquisava "aí o" — sobra só de muleta/artigo = nenhuma busca (abre o YouTube)
        _MULETA = {"aí", "ai", "lá", "la", "ali", "aqui", "então", "entao", "agora", "pra", "mim", "por", "favor", "o", "a", "os", "as",
                   "um", "uma", "no", "na", "de", "do", "da", "e", "pfv", "rapidinho", "logo", "isso", "esse", "essa", "me", "pro", "também"}
        if all(w in _MULETA for w in re.findall(r"\w+", consulta.lower())):
            consulta = ""
    if len(consulta) < 2:
        if YT.search(t):
            _say(progress, "Abrindo o YouTube no navegador.")
            t_abrir_site(url="https://www.youtube.com", fr=fr, ops=ops)
            return "Pronto, chefe. YouTube aberto no navegador."
        return None
    vid = ""
    _say(progress, f"Certo, procurando {consulta} no YouTube.")
    if tocar:
        try:
            out = subprocess.run(["yt-dlp", "--flat-playlist", "--get-id", "--playlist-end", "1", "--no-warnings", "ytsearch1:" + consulta],
                                 capture_output=True, text=True, timeout=40).stdout.split()
            vid = out[0] if out else ""
        except Exception:
            vid = ""
    if CANCEL.is_set():
        return "Parei, chefe."
    _say(progress, "Achei. Abrindo no navegador.")
    if vid:
        t_abrir_site(url="https://www.youtube.com/watch?v=" + vid, fr=fr, ops=ops)
        vigiar_anuncios(120)                            # se vier anúncio, pula sozinha
        return f"Pronto, chefe. Coloquei no YouTube: {consulta}."
    t_abrir_site(url="https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(consulta), fr=fr, ops=ops)
    return f"Abri a pesquisa no YouTube por {consulta}."


LOJAS_RE = re.compile(r"\b(ebay|amazon|mercado\s*livre|mercadolivre|shopee|aliexpress|sites?\s+americanos?|lojas?\s+americanas?)\b", re.I)
FOLLOWUP_NAV_RE = re.compile(
    r"^\s*(?:sexta[- ]?feira[,:\s]*)?(?:apenas\s+|s[óo]\s+)?(?:pesquis\w*|busc\w*|procur\w*|abr[ae])\s+"
    r"(?:em\s+(?:uma\s+)?nova\s+aba|numa\s+nova\s+aba|no\s+navegador|em\s+sites?\s+americanos?|no\s+ebay|na\s+amazon(?:\s+global)?|no\s+mercado\s*livre)\s*[.!?]*$|"
    r"^\s*(?:sexta[- ]?feira[,:\s]*)?(?:fa[çc]a(?:\s+isso)?|pode\s+fazer|faz\s+isso)\s*[.!?]*$",
    re.I
)


COMPOSTA_ZAP_RE = re.compile(
    r"\b(?:e\s+|depois\s+|em\s+seguida\s+)?(?:prepar\w*|escrev\w*|redij\w*|envi\w+|mand\w+|encaminh\w+|repass\w+)\b"
    r".{0,80}?\b(?:para|pra|pro|ao|à)\s+([@A-Za-zÀ-ÿ0-9_][\wÀ-ÿ @.'+-]{0,40}?)"
    r"(?=\s+no\s+(?:whatsapp|zap(?:\s*zap)?|wpp)\b|\s+com\b|\s+dizendo\b|$)",
    re.I
)
COMPOSTA_ARQ_RE = re.compile(
    r"\b(?:e\s+|depois\s+|em\s+seguida\s+)?(?:cri[ae]\w*|salv[ae]\w*|grav[ae]\w*|ger[ae]\w*|escrev\w*|fa[çc][ae]\w*)\b.*?\b(arquiv\w*|document\w*|relat[óo]rio|resumo|nota|planilh\w*|apresenta[çc][ãa]o|slides?|docx|xlsx|pptx|txt|md|markdown|json|csv)\b",
    re.I
)
COMPOSTA_AG_RE = re.compile(
    r"\b(?:e\s+|depois\s+|em\s+seguida\s+)?(?:agend\w+|(?:anot\w+|adicion\w+|marqu?e|coloqu?e|ponha)\s+(?:isso\s+)?na\s+(?:minha\s+)?agenda)\b",
    re.I
)


def _eh_tarefa_composta(text):
    t = (text or "").strip()
    if not t:
        return False
    if PESQ.search(t) and (COMPOSTA_ZAP_RE.search(t) or COMPOSTA_ARQ_RE.search(t) or COMPOSTA_AG_RE.search(t)):
        return True
    # Duas ações explícitas ligadas por "e depois" / "e envie" / "e crie" / "e agende"
    if re.search(r"\b(?:e\s+depois|em\s+seguida|e\s+tamb[ée]m)\b", t, re.I):
        return True
    return False


def _limpar_cauda_composta(q):
    q = re.sub(r"(?i)\s+(?:e\s+|depois\s+|em\s+seguida\s+)?(?:prepar\w*|escrev\w*|redij\w*|envi\w+|mand\w+|encaminh\w+|repass\w+)\b.*$", "", q)
    q = re.sub(r"(?i)\s+(?:e\s+|depois\s+|em\s+seguida\s+)?(?:cri[ae]\w*|salv[ae]\w*|grav[ae]\w*|ger[ae]\w*|escrev\w*|fa[çc][ae]\w*)\s+(?:um|uma|em\s+um|num|no|na)?\s*(?:arquiv\w*|document\w*|relat[óo]rio|resumo|nota|planilh\w*|apresenta[çc][ãa]o|slides?|docx|xlsx|pptx|txt|md).*$", "", q)
    q = re.sub(r"(?i)\s+(?:e\s+|depois\s+|em\s+seguida\s+)?(?:agend\w+|(?:anot\w+|adicion\w+|marqu?e|coloqu?e|ponha)\s+(?:isso\s+)?na\s+(?:minha\s+)?agenda).*$", "", q)
    return q.strip(" ,.!?")


def _paginas_do_assunto(tema):
    t = (tema or "").lower()
    if re.search(r"fortn", t) and re.search(r"loja|item|skin|hoje|vbuck", t):
        return ["https://www.fortnite.com/item-shop?lang=pt-BR", "https://fortnite.gg/shop"]
    return []


_LIXO_TELA = re.compile(
    r"exibindo resultados|vou pesquisar|cookie|aceitar tudo|javascript|inscreva|menu principal|barra de endere|"
    r"publicidade|an[úu]ncio|anuncios?|patrocinad|todos os direitos|pol[íi]tica de privacidade|termos de uso|propaganda|newsletter",
    re.I)


def _linhas_uteis(texto):
    out = []
    for ln in re.split(r"[\n\r•]+|(?<=[.!?])\s+", texto or ""):
        s = re.sub(r"\s+", " ", ln).strip(" -•\t")
        if len(s) < 12 or len(s) > 180 or _LIXO_TELA.search(s):
            continue
        if s not in out:
            out.append(s)
    return out


def _focar_navegador(fr):
    import abrir_nativo
    if fr is None:
        return False
    w = fr.find_window(abrir_nativo.chave_janela("navegador"))
    if not w:
        abrir_nativo.abrir_url("about:blank")
        time.sleep(1.0)
        w = fr.find_window(abrir_nativo.chave_janela("navegador"))
    if not w:
        return False
    try:
        fr.fechar_paineis()
    except Exception:
        pass
    fr._niri("focus-window", "--id", str(w["id"]))
    time.sleep(0.35)
    return True


def _ir_para_url(url, fr, progress=None):
    """Troca a aba visível. Abrir por trás deixa a página anterior na frente."""
    host = urllib.parse.urlparse(url).netloc.replace("www.", "").split(".")[0]
    _say(progress, "Entrando em " + host + ".")
    if not _focar_navegador(fr):
        import abrir_nativo
        abrir_nativo.abrir_url(url)
        time.sleep(2.5)
        return
    try:
        antes = str((fr.focused_window() or {}).get("title") or "")
    except Exception:
        antes = ""
    for _ in range(2):
        try:
            fr._pc("goto", url, timeout=25)
            break
        except Exception:
            _focar_navegador(fr)
    t0 = time.time()
    while time.time() - t0 < 9:
        try:
            tit = str((fr.focused_window() or {}).get("title") or "")
        except Exception:
            tit = ""
        if tit and tit != antes:
            break
        time.sleep(0.45)
    time.sleep(1.4)


def _nivel_detalhe(texto):
    """quanto conteúdo o pedido quer: 'tudo/completo/todas' = máximo; 'resumo/principais' = pouco; senão médio.
    limites cabem no num_ctx 8192 (entrada ~3,5 mil tokens + saída)."""
    t = (texto or "").lower()
    if re.search(r"\b(tud[oa]|complet[oa]s?|tod[oa]s|lista inteira|detalhad[oa]|cada (?:item|um)|sem deixar nada|o conte[uú]do|que (?:achar|encontrar)|os itens|a lista)\b", t):
        return {"nome": "completo", "itens": 2000, "linhas": 120, "chars": 6000, "tokens": 500, "timeout": 90,
                "instr": "Escreva só uma abertura curta e um panorama por categoria (quantos itens e faixa de preço); a lista COMPLETA de itens será anexada depois automaticamente."}
    if re.search(r"\b(resum[oa]|principais|destaques|r[aá]pid[oa]|curt[oa]|breve)\b", t):
        return {"nome": "resumo", "itens": 40, "linhas": 25, "chars": 3000, "tokens": 400, "timeout": 60,
                "instr": "Nível de detalhe RESUMIDO: só os destaques mais relevantes."}
    return {"nome": "medio", "itens": 120, "linhas": 60, "chars": 8000, "tokens": 1500, "timeout": 150,
            "instr": "Cubra todas as categorias com os itens mais relevantes de cada uma; não corte categorias inteiras."}


def _entrar_e_ler(tema, fr, ops, progress=None, det=None):
    """Abre cada página na aba da frente, rola e lê só o miolo."""
    det = det or _nivel_detalhe(tema)
    urls = _paginas_do_assunto(tema)
    if not urls:
        try:
            achados = t_pesquisar_web(consulta=tema)
        except Exception:
            achados = ""
        for u in re.findall(r"https?://[^\s|]+", achados or ""):
            u = u.rstrip(").,")
            if re.search(r"google\.|duckduckgo|bing\.|youtube|facebook|instagram", u):
                continue
            if u not in urls:
                urls.append(u)
            if len(urls) >= 2:
                break
    linhas = []
    import orquestra_geral as _og
    if re.search(r"(?i)fortn", tema):                       # dado oficial da loja, sem depender da tela
        api = _og.loja_fortnite(det["itens"])
        if api:
            try:                                             # o dono quer VER a pesquisa: abre a loja no navegador da Friday
                _say(progress, "Abrindo a loja do Fortnite de hoje no navegador.")
                nv = _og._nav()
                if nv:
                    nv.abrir("https://www.fortnite.com/item-shop?lang=pt-BR")
                    from prom_ops import _daemon_send
                    _daemon_send({"type": "nano", "op": "agente", "on": True})    # esconde o chat da Friday enquanto usa o cursor
                    try:
                        time.sleep(1.5)                      # o Chromium restaura a rolagem da mesma página depois de carregar
                        with nv.Pagina() as pg:
                            no_fim = pg.js("scrollY") > 50
                        if no_fim:                           # reaberta já no fim: recarrega como gente (F5) e volta ao topo (Home)
                            _say(progress, "A página abriu no fim; recarregando e voltando ao topo.")
                            nv._focar_janela()
                            nv._pc("key", "F5")
                            time.sleep(1.0)
                            with nv.Pagina() as pg:          # conexão nova: a antiga morre no recarregamento
                                nv._esperar_carregar(pg)
                            time.sleep(1.5)
                            nv._pc("key", "Home")
                            time.sleep(0.8)
                        with nv.Pagina() as pg:              # rola com o cursor e a rodinha REAIS até o fim da loja
                            if pg.js("scrollY") > 50:
                                pg.js("window.scrollTo(0, 0)")
                                time.sleep(0.5)
                            real = nv._mover_ate(pg, pg.js("innerWidth") // 2, pg.js("innerHeight") // 2)
                            parado = 0
                            for _ in range(80):
                                y = pg.js("scrollY")
                                if real and parado < 2:
                                    nv._pc("scroll", 8)
                                else:                        # roda não desceu (cursor fora da página): rola pelo navegador
                                    pg.js("window.scrollBy({top: innerHeight * 0.8, behavior: 'smooth'})")
                                time.sleep(0.5)
                                parado = parado + 1 if pg.js("scrollY") <= y else 0
                                if parado >= 3:              # 3 giros sem descer = chegou ao fim (já espera o carregamento preguiçoso)
                                    break
                    finally:
                        _daemon_send({"type": "nano", "op": "agente", "on": False})
            except Exception as _e_rola:
                print("[loja] rolagem falhou:", repr(_e_rola)[:200], flush=True)
            return api
    for u in urls[:2]:
        bloco = ""
        try:                                                 # DOM do navegador da Friday: não lê outras janelas da tela
            nv = _og._nav()
            if nv:
                nv.abrir(u)
                bloco = (nv.ler() or {}).get("texto") or ""
        except Exception:
            bloco = ""
        if len(bloco) < 80:
            try:
                _ir_para_url(u, fr, progress)
                bloco = t_ler_rolando(vezes=8, url=u)
            except Exception:
                bloco = ""
        for s in _linhas_de_leitura(bloco):
            if s not in linhas:
                linhas.append(s)
    uso = [s for s in linhas if re.search(r"[A-Za-zÀ-ÿ]{4,}", s) or re.search(r"\d[\d.,]{2,}", s)][:det["linhas"]]
    if len(uso) < 2:
        return ""
    return "\n".join("• " + s for s in uso)


def _tarefa_composta(text, fr, ops=None, progress=None):
    """Executa tarefas compostas encadeadas (ex.: 'pesquise X e envie para Fulano', 'pesquise X e crie um arquivo Y', 'pesquise X e anote na agenda')."""
    t = (text or "").strip()
    if not t or CELULAR_RE.search(t) or not PESQ.search(t):
        return None
    m_zap = COMPOSTA_ZAP_RE.search(t)
    m_arq = COMPOSTA_ARQ_RE.search(t)
    m_ag = COMPOSTA_AG_RE.search(t)
    if not (m_zap or m_arq or m_ag):
        return None

    tema = _limpar_cauda_composta(_limpar_termo_busca(t))
    if len(tema) < 2:
        return None

    # 1) Pesquisa + Criar Documento/Arquivo
    if m_arq and not m_zap:
        tipo_m = m_arq.group(1).lower()
        m_nome = re.search(r"\b(?:chamad[oa]|com\s+o\s+nome|nome)\s+([A-Za-z0-9_.\-À-ÿ]+)", t, re.I) or \
                 re.search(r"\b([A-Za-z0-9_\-À-ÿ]+\.(?:txt|md|docx|xlsx|pptx|csv|json|html))\b", t, re.I)
        nome_arq = m_nome.group(1).strip(" .,!?") if m_nome else ""
        if DOCW.search(t) or tipo_m in ("docx", "xlsx", "pptx") or tipo_m.startswith(("planilh", "apresenta", "slide")):
            ext = "xlsx" if ("planilh" in tipo_m or "xlsx" in tipo_m) else ("pptx" if ("apresenta" in tipo_m or "slide" in tipo_m or "pptx" in tipo_m) else "docx")
            _say(progress, f"Pesquisando sobre {tema} e criando o {ext}.")
            res_doc = t_pesquisa_para_documento(consulta=tema, tipo=ext, nome=nome_arq or tema[:40], fr=fr)
            _log("tarefa_composta_doc", {"tema": tema, "tipo": ext}, True, 0.5, res_doc)
            return f"Pesquisei sobre {tema} e criei o documento ({res_doc})."
        _say(progress, f"Pesquisando sobre {tema} para criar o arquivo.")
        achados = t_pesquisar_web(consulta=tema)
        link = re.findall(r"\|\s*(https?://\S+)\s*$", achados, re.M)
        corpo = achados
        if link:
            try:
                corpo = t_ler_pagina(url=link[0])[:3000] + "\n\n" + achados
            except Exception:
                pass
        conteudo = None
        data_atual = time.strftime("%d/%m/%Y")
        if fr is not None:
            try:
                conteudo = fr.llm(
                    "Você é a F.R.I.D.A.Y., analista executiva. Escreva um relatório analítico estruturado e aprofundado em Markdown "
                    f"(com título #, ## 1. Resumo Executivo na data {data_atual}, ## 2. Análise Detalhada dos Fatos, ## 3. Tabela Comparativa de Dados/Valores, "
                    "## 4. Conclusão) sobre o tema pesquisado. PROIBIDO O USO DE QUALQUER EMOJI. Escreva texto fluído de alta qualidade, sem colar trechos brutos.",
                    f"Tema: {tema}\n\nDados apurados:\n{corpo[:5000]}", None, False, 1200, 0.2, 90
                )
            except Exception:
                pass
        if not conteudo or len(conteudo.strip()) < 80:
            try:
                import orquestra_geral as _og
                conteudo = _og._modelo(
                    f"Escreva um relatório analítico completo em Markdown sobre '{tema}' com introdução, análise detalhada na data {data_atual}, tabela de dados e conclusão. PROIBIDO O USO DE EMOJIS.\n\nMaterial:\n{corpo[:5000]}",
                    max_tokens=1400
                )
            except Exception:
                pass
        conteudo = (conteudo or corpo).strip()
        conteudo = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]', '', conteudo)
        conteudo = re.sub(r'<think>.*?</think>', '', conteudo, flags=re.DOTALL).strip()
        if not nome_arq:
            slug = re.sub(r"[^a-z0-9]+", "-", tema.lower()).strip("-")[:36] or "pesquisa"
            nome_arq = f"{slug}.md"
        elif "." not in nome_arq:
            nome_arq += ".md"
        res_arq = t_criar_arquivo(caminho=nome_arq, conteudo=conteudo, abrir=False)
        _log("tarefa_composta_arq", {"tema": tema, "arquivo": nome_arq}, True, 0.4, res_arq)
        return f"Pronto, chefe. Pesquisei sobre {tema}, analisei os dados e salvei o relatório estruturado em {nome_arq} na pasta Documentos/Friday."

    _say(progress, f"Entrando nas páginas sobre {tema}.")
    det = _nivel_detalhe(t)
    corpo = _entrar_e_ler(tema, fr, ops, progress, det)
    if len(corpo) < 40:
        return f"Abri as páginas sobre {tema}, mas o texto não tinha o conteúdo. Não montei mensagem genérica."

    # Síntese analítica articulada para mensagens e agenda
    sintese_msg = None
    data_atual = time.strftime("%d/%m/%Y")
    contato_dest = "contato"
    if m_zap:
        contato_dest = m_zap.group(1).strip()
        contato_dest = re.sub(r"(?i)^(?:\s*(?:o|a|os|as|meu|minha|@))+", "", contato_dest).strip()
        contato_dest = re.sub(r"(?i)\s+(?:no|pelo|via|por)\s+(?:whatsapp|zap|zapzap|mensagem|wpp).*$", "", contato_dest).strip(" ,.!?")

    if fr is not None:
        try:
            sintese_msg = fr.llm(
                f"Você é a F.R.I.D.A.Y. Redija uma mensagem de WhatsApp natural e clara para o contato '{contato_dest}' sobre o tema: '{tema}'. Use SÓ os Dados apurados que forem sobre esse tema (ignore o resto) e organize por categorias quando houver. Tom: siga o pedido. Se o dono não pediu formalidade, escreva como uma mensagem normal de WhatsApp, amigável e direta, sem cabeçalho de relatório, sem 'Prezada equipe', sem assinatura nem status. Formal/corporativo SÓ se o pedido disser (relatório, formal, corporativo, e-mail profissional). "
                f"Data atual de referência: {data_atual}. PROIBIDO O USO DE QUALQUER EMOJI OU CARACTERE PICTOGRÁFICO. Utilize exclusivamente texto alfanumérico e pontuação formal padrão. "
                "Sintetize os pontos principais apurados sobre o tema, valores ou novidades encontradas, sem jargões de robô, "
                "sem colar URLs cruas, sem anúncios ou avisos de cookies e sem colar trechos soltos. Não invente nada que não esteja nos dados.",
                f"Tema: {tema}\n{det['instr']}\n\nDados apurados:\n{corpo[:det['chars']]}",
                None, False, det["tokens"], 0.2, det["timeout"]
            )
        except Exception:
            pass
    if not sintese_msg or len(sintese_msg.strip()) < 20:
        try:
            import orquestra_geral as _og
            sintese_msg = _og._modelo(
                f"Você é a F.R.I.D.A.Y. Escreva a mensagem de WhatsApp para '{contato_dest}' sobre '{tema}' só com os dados abaixo. Tom: siga o pedido. Se o dono não pediu formalidade, escreva como uma mensagem normal de WhatsApp, amigável e direta, sem cabeçalho de relatório, sem 'Prezada equipe', sem assinatura nem status. Formal/corporativo SÓ se o pedido disser (relatório, formal, corporativo, e-mail profissional).\n"
                f"Data atual de referência: {data_atual}.\n"
                f"PROIBIDO O USO DE QUALQUER EMOJI.\n{det['instr']}\n\nDados apurados:\n{corpo[:det['chars']]}",
                max_tokens=det["tokens"]
            )
        except Exception:
            pass
    if sintese_msg:
        sintese_msg = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]', '', sintese_msg)
        sintese_msg = re.sub(r'<think>.*?</think>', '', sintese_msg, flags=re.DOTALL).strip()
    resumo = (sintese_msg or corpo).strip()
    itens_dados = len(re.findall(r"(?m)^\s*•", corpo))
    itens_msg = len(re.findall(r"(?m)^\s*(?:[-•*]|\d+[.)])\s", sintese_msg or ""))
    if sintese_msg and det["nome"] != "resumo" and itens_dados > 10 and (det["nome"] == "completo" or itens_msg < itens_dados / 2):
        resumo += "\n\nLista completa:\n" + corpo           # o modelo resumiu demais (ou não comporta tudo): a lista inteira vai direto

    # 2) Pesquisa + Enviar no WhatsApp
    if m_zap:
        contato = contato_dest
        contato = re.sub(r"(?i)^(?:\s*(?:o|a|os|as|meu|minha|@))+", "", contato).strip()
        contato = re.sub(r"(?i)\s+(?:no|pelo|via|por)\s+(?:whatsapp|zap|zapzap|mensagem|wpp).*$", "", contato).strip(" ,.!?")
        if contato:
            _say(progress, f"Preparando envio para {contato} no WhatsApp.")
            msg_zap = resumo
            try:
                res_z = t_zap_enviar(contato=contato, mensagem=msg_zap, fr=fr, ops=ops, pronto=True)
                _log("tarefa_composta_zap", {"tema": tema, "contato": contato}, True, 0.4, res_z)
                if re.search(r"PENDENTE|aprova[çc][ãa]o|espelho|preparad", str(res_z), re.I):
                    _n_itens = len(re.findall(r"(?m)^\s*(?:[-•*]|\d+[.)])\s", resumo))
                    _tam = f" A mensagem completa tem {_n_itens} itens ({len(resumo) // 1000} mil caracteres); aqui é só o começo." if _n_itens > 15 else ""
                    return f"Pesquisei sobre {tema} e analisei os dados: {resumo[:220]}{_tam} Deixei a mensagem pronta para {contato} no espelho — diga aprovado para enviar."
                return f"Pesquisei e analisei sobre {tema}, e enviei para {contato} no WhatsApp: {resumo[:220]}"
            except Exception as e_z:
                _log("tarefa_composta_zap", {"tema": tema, "contato": contato}, False, 0.2, repr(e_z))
                return f"Apurado e analisado sobre {tema}: {resumo[:240]} Porém não consegui enviar no WhatsApp para {contato} ({str(e_z)[:80]})."

    # 3) Pesquisa + Agenda
    if m_ag and ops is not None:
        m_q = re.search(r"\b(hoje|amanh[ãa]|segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|\d{1,2}[/:h]\d{0,2}).*$", t, re.I)
        quando = m_q.group(0).strip(" .,!?") if m_q else "hoje 18h"
        aid, msg_a = ops.agenda_add(f"{tema[:50]} — {resumo[:90]}", quando, "lembrete", 60, "", resumo[:300], "", "friday", None, "", 2)
        _log("tarefa_composta_agenda", {"tema": tema, "quando": quando, "aid": aid}, bool(aid), 0.2, msg_a)
        return f"Pesquisei sobre {tema}: {resumo[:200]} E registrei na agenda Friday ({msg_a})."

    return None


def _pesquisa_navegador_direta(text, fr, ops=None, progress=None, historico=None):
    """Atalho determinístico para 'abra o navegador e pesquise X (no ebay/amazon/google)' e follow-ups ('apenas pesquise em uma nova aba', 'faça')."""
    t = (text or "").strip()
    if not t or CELULAR_RE.search(t) or DOCW.search(t) or YT.search(t) or _eh_tarefa_composta(t):
        return None
    if re.search(r"\b(?:mensagem|whatsapp|zap(?:\s*zap)?|wpp)\b", t, re.I) and re.search(r"\b(?:prepar\w*|escrev\w*|envi\w*|mand\w*)\b", t, re.I):
        return None
    if re.search(r"\b(background|segundo plano|por tr[aá]s|silencios\w+|sem atrapalhar|sem interromper)\b", t, re.I):
        return None
    eh_followup = bool(FOLLOWUP_NAV_RE.search(t))
    eh_busca_nav = bool(PESQ.search(t) and (NAV.search(t) or LOJAS_RE.search(t)))
    if not (eh_busca_nav or eh_followup):
        return None
    termo = "" if eh_followup else _limpar_termo_busca(t)
    contexto_lojas = t
    if len(termo) < 2 and historico:
        for m in reversed(historico):
            if isinstance(m, dict) and m.get("role") == "user":
                u_ant = str(m.get("content") or "").split("\n\n[agora]")[0].strip()
                if PESQ.search(u_ant) and not FOLLOWUP_NAV_RE.search(u_ant):
                    t_ant = _limpar_termo_busca(u_ant)
                    if len(t_ant) >= 2:
                        termo = t_ant
                        contexto_lojas = u_ant + " " + t
                        break
    if len(termo) < 2:
        return None
    _say(progress, f"Abrindo a pesquisa por {termo} no navegador.")
    res_nav = t_abrir_site(busca=termo, contexto_lojas=contexto_lojas, fr=fr, ops=ops)
    _log("abrir_site", {"busca": termo, "contexto": contexto_lojas[:80]}, True, 0.2, res_nav)
    apenas_aba = bool(re.search(r"\b(apenas|s[óo])\b.*\b(aba|navegador)\b", t, re.I)) or eh_followup
    quer_resumo = (not apenas_aba) and bool(re.search(r"\b(?:mostr\w+|dig\w+|fal\w+|trag\w+|resum\w+)\s+(?:o\s+que|oque|tudo\s+que)\s+(?:achar|encontrar|ver)\b", contexto_lojas, re.I))
    if quer_resumo and fr is not None:
        try:
            lojas_q = " ".join(re.findall(r"\b(?:ebay|amazon|mercado\s*livre)\b", contexto_lojas, re.I))
            q_web = (termo + (" " + lojas_q if lojas_q else "")).strip()
            achados = t_pesquisar_web(consulta=q_web)
            _log("pesquisar_web", {"consulta": q_web}, True, 0.4, achados)
            if achados and not achados.startswith("nenhum"):
                resumo = fr.llm(
                    "Você é a F.R.I.D.A.Y. Você já abriu as abas de pesquisa no navegador do chefe. Agora resuma em 2 frases curtas e diretas (sem markdown e sem ler URLs) o que encontrou nos resultados abaixo.",
                    f"Pesquisa: {q_web}\nResultados:\n{achados[:3000]}", None, False, 200, 0.2, 45
                )
                if resumo and resumo.strip():
                    return f"Abri a pesquisa por {termo} no navegador, chefe. {resumo.strip()}"
        except Exception:
            pass
    return f"Pronto, chefe. Abri a pesquisa por {termo} em uma nova aba no navegador."


def _pesquisa_direta(text, fr, ops=None, progress=None):
    """'pesquise X': pesquisa, lê a melhor página e responde; se pediu background, roda 100% silencioso sem abrir navegador nem roubar foco."""
    if _eh_tarefa_composta(text):
        return None
    q = _limpar_termo_busca(text)
    if len(q) < 3:
        return None
    em_bg = bool(re.search(r"\b(background|segundo plano|por tr[aá]s|silencios\w+|sem atrapalhar|sem interromper)\b", text, re.I))
    quer_nav = bool((NAV.search(text) or LOJAS_RE.search(text)) and not em_bg)
    if em_bg:
        _say(progress, f"Pesquisando sobre {q} em segundo plano.")
    else:
        _say(progress, f"Pesquisando sobre {q}.")
    if quer_nav and not CANCEL.is_set():
        _say(progress, "Abrindo a busca no navegador.")
        try:
            t_abrir_site(busca=q, contexto_lojas=text, fr=fr, ops=ops)
        except Exception as e_nav:
            print("aviso abrir site em pesquisa:", e_nav, flush=True)
    achados = t_pesquisar_web(consulta=q)
    links = re.findall(r"\|\s*(https?://\S+)\s*$", achados, re.M)[:2]
    partes = []
    for i, u in enumerate(links):
        if not em_bg:
            try:
                t_abrir_site(url=u, fr=fr, ops=ops)
            except Exception:
                pass
        try:
            pag = t_ler_pagina(url=u).strip()
            if len(pag) > 80:
                partes.append(f"FONTE {u}\n" + pag[:2500])
        except Exception:
            pass
    if len(partes) < 2:
        return "Não fechei a pesquisa: li " + str(len(partes)) + " página. Faltou a segunda fonte."
    corpo = "\n\n".join(partes)
    prompt_instrucao = (
        "Responda em português, 3 a 5 frases, só com o que as duas páginas dizem sobre a pergunta. "
        "Cite o dado concreto. Proibido começar com 'com base na pesquisa' ou dar uma resposta genérica."
    )
    resp = fr.llm(prompt_instrucao, f"Pergunta: {q}\n\nMaterial:\n{corpo[:5000]}", None, False, 320, 0.1, 90)
    if not resp or re.search(r"com base na pesquisa|em resumo|vale destacar", resp, re.I):
        return corpo[:500]
    return resp.strip()


REPOUSO = [False]       # prometheus._repouso liga: tela bloqueada/apagada -> mouse/teclado/tela iriam para a tela de bloqueio (senha!)
TELA = {"ver_tela", "clicar_texto", "clicar_elemento", "apontar", "digitar", "tecla", "rolar", "pular_anuncio", "abrir_app",
        "abrir_site", "onlyoffice_abrir", "onlyoffice_criar"}


def run(text, ctx, fr, ops, historico=None, progress=None, direto=True):
    """executa o laço; devolve o dict no formato do friday.think (fala/acoes/pose/humor)."""
    CANCEL.clear()
    if direto and re.search(r"\b(pul[ae]r?|skip|passa|fecha|tira)\b.*\b(an[úu]ncios?|propagandas?)\b|\b(an[úu]ncios?|propagandas?)\b.*\b(pul[ae]r?|skip)\b", text or "", re.I):
        r = t_pular_anuncio(espera=20, fr=fr)
        return {"fala": r[:200], "acoes": [], "pose": "confirmar", "humor": "neutro", "lembrar": {}}
    if not direto:                                       # tarefa contínua: nada de atalhos de texto, só o laço de ferramentas
        pass
    no_cel = bool(CELULAR_RE.search(text or ""))
    if no_cel:                                                   # pedido no CELULAR: lê a tela do celular (nunca clica no PC por engano)
        try:
            tela_L, tela = [], "TELA DO CELULAR:\n" + _cel().ver()[:1500]
        except Exception as e:
            tela_L, tela = [], f"(celular inacessível: {str(e)[:100]} — confira o droidVNC-NG e o Tailscale no celular)"
    else:
        tela_L, tela = _olhar() if direto else ([], "")         # LÊ A TELA ANTES de decidir
    dom = "celular" if no_cel else dominio(text)           # F6: ferramentas filtradas por domínio
    alvo_vis = _visivel(text, tela_L) if (tela_L and dom not in ("zap", "arquivo")) else None
    if alvo_vis is not None and (not re.search(r"\b(cli(c|qu)\w*|abr[ae]|abrir|seleciona\w*|escolh\w*|entr[ae] (em|no|na)|vai (em|no|na)|toc[ae])\b", text or "", re.I)
                                 or len(alvo_vis["t"]) > 60
                                 or difflib.SequenceMatcher(None, (text or "").lower(), alvo_vis["t"].lower()).ratio() >= 0.6):
        alvo_vis = None                                          # só atalho de CLIQUE num item curto da tela — nunca no próprio pedido
    if alvo_vis is not None:                                     # o que ele pediu já está na tela: clica nele em vez de buscar de novo
        try:
            _say(progress, "Achei aqui na tela.")
            r = t_clicar_texto(texto=alvo_vis["t"])
            _log("clicar_visivel", {"pedido": text[:120], "linha": alvo_vis["t"]}, True, 0, r)
            return {"fala": "Pronto, cliquei em " + alvo_vis["t"][:60] + ".", "acoes": [], "pose": "confirmar", "humor": "neutro", "lembrar": {}}
        except Exception as e:
            _log("clicar_visivel", {"pedido": text[:120], "linha": alvo_vis["t"]}, False, 0, repr(e))
    try:
        r_comp = _tarefa_composta(text, fr, ops, progress) if direto and not no_cel else None
        if r_comp:
            return {"fala": r_comp[:520], "acoes": [], "pose": "confirmar", "humor": "confiante", "lembrar": {}, "verificado": True}
    except Exception as e_c:
        _log("tarefa_composta", {"pedido": text[:120]}, False, 0, repr(e_c))
    try:
        r = _midia_direta(text, fr, ops, progress) if direto and not no_cel else None
        if r:
            if CANCEL.is_set():
                return {"fala": "", "acoes": [], "cancelado": True, "pose": "neutro", "humor": "neutro", "lembrar": {}}
            _log("midia_direta", {"pedido": text[:120]}, True, 0, r[:200])
            return {"fala": r[:300], "acoes": [], "pose": "confirmar", "humor": "alegre", "lembrar": {}}
    except Exception as e:
        _log("midia_direta", {"pedido": text[:120]}, False, 0, repr(e))
    if direto and not no_cel and PESQ.search(text or "") and not DOCW.search(text or "") and not _eh_tarefa_composta(text or ""):
        try:
            r = _pesquisa_direta(text, fr, ops, progress)
            if r:
                if CANCEL.is_set():
                    return {"fala": "", "acoes": [], "cancelado": True, "pose": "neutro", "humor": "neutro", "lembrar": {}}
                _log("pesquisa_direta", {"pedido": text[:120]}, True, 0, r[:200])
                return {"fala": r[:520], "acoes": [], "pose": "apresentar", "humor": "neutro", "lembrar": {}}
        except Exception as e:
            _log("pesquisa_direta", {"pedido": text[:120]}, False, 0, repr(e))
    passos = []
    trilha = []                                            # F7: passos ok resumidos (vão para a memória de episódios)
    ep_txt = ""
    try:
        import episodios as _ep
        ep_txt = _ep.texto_prompt(text) if _ep.ativo() else ""    # F7: os 2 episódios verificados mais parecidos
    except Exception as e_ep:
        _ep = None
        print("aviso episodios:", e_ep, flush=True)
    msgs_user = f"Pedido do dono: {text}" + (f"\n\n{ep_txt}" if ep_txt else "") + \
        (f"\n\nTELA AGORA (leia antes de agir):\n{tela[:1500]}" if tela else "")
    dom = "celular" if no_cel else dominio(text)           # F6: ferramentas filtradas por domínio
    falhas = 0
    final = None
    feito = False
    efeitos_feitos = set()
    eh_comp = _eh_tarefa_composta(text)
    vistos = set()
    vistos_prog = set()
    evid = []                                              # F6: evidências VERIFICADAS (o "concluído" depende delas)
    usou_efeito = False                                    # usou ferramenta que muda algo (não só leitura)
    checagens = 0
    verificado = None
    tela_ant = {l["t"] for l in (tela_L or [])}
    for i in range(MAX_STEPS):
        if CANCEL.is_set():
            return {"fala": "", "acoes": [], "cancelado": True, "pose": "neutro", "humor": "neutro", "lembrar": {}}
        user = msgs_user + ("\n\nPassos já feitos:\n" + "\n".join(_passos_prompt(passos)) if passos else "")
        d = fr.llm(_prompt(ctx, dom), user, historico if i == 0 else None, True, 420, 0.1, 90)
        if not isinstance(d, dict):
            passos.append("(resposta inválida do modelo)"); falhas += 1
            if falhas >= 2:
                break
            continue
        if d.get("final"):
            # F6: só declara concluído com evidência — confere o objetivo (schema) se agiu (ou se não fez nada)
            if (usou_efeito or not vistos) and not _NEG.search(str(d["final"])) and checagens < 2:
                checagens += 1
                cumprido, falta = checar_objetivo(text, evid, passos, d["final"], fr)
                verificado = cumprido
                if cumprido is False and i < MAX_STEPS - 1 and checagens < 2:     # 1ª negativa: tenta de novo; 2ª: fala a verdade
                    passos.append(f"(VERIFICAÇÃO: o pedido NÃO está cumprido — falta: {falta or '?'}. Continue com outra ferramenta "
                                  f"ou responda final dizendo com honestidade o que não deu)")
                    _log("checar_objetivo", {"pedido": text[:120]}, False, 0, falta)
                    continue
            final = d
            break
        nome = str(d.get("ferramenta", ""))
        args = d.get("args") if isinstance(d.get("args"), dict) else {}
        if nome not in TOOLS:
            passos.append(f"ferramenta inexistente: {nome}"); falhas += 1
            continue
        chave = nome + json.dumps(args, sort_keys=True, default=str)[:300]
        if chave in vistos or (nome in efeitos_feitos and not eh_comp):    # não repete o MESMO efeito colateral
            passos.append("(já executado; responda com final)")
            if feito and not eh_comp:
                break
            continue
        vistos.add(chave)
        if nome in PROG and nome not in vistos_prog:
            vistos_prog.add(nome); _say(progress, PROG[nome])
        antes = _snap(nome) if nome in VERIF else None
        try:
            import orquestra_geral as _og
            _neg = _og.recusar(text or "")
            if _neg:
                return {"fala": _neg, "acoes": [], "pose": "neutro", "humor": "serio", "lembrar": {}}
            import orchestrator as _orc
            _pens = _orc.get_orquestrador().pensar_antes_de_agir(text or "", {"ferramenta": nome}, f"{nome}")
            if not _pens.get("autorizado", True):
                passos.append(f"[{nome}] bloqueado: {_pens.get('estrategia', '')[:160]}")
                continue
            _say(progress, (_pens.get("estrategia") or "Vou fazer isso.")[:160])
        except Exception:
            pass
        t0 = time.time()
        try:
            if REPOUSO[0] and nome in TELA:
                res = ("BLOQUEADO: modo repouso (tela bloqueada e apagada). Não dá para usar a tela agora; resolva com ferramentas sem tela "
                       "(pesquisar_web, ler_pagina, resumir, zap_enviar, cel_*, nota) ou responda que precisa que o dono diga 'acordar'.")
            else:
                res = TOOLS[nome][0](fr=fr, ops=ops, **args)
            _log(nome, args, True, time.time() - t0, res)
            usou_efeito = usou_efeito or nome not in LEITURA
            extra = ""
            if nome.startswith("cel_") and nome not in ("cel_ver", "cel_espelhar"):
                try:
                    extra = " | celular depois: " + _cel().ver()[:400]
                except Exception:
                    pass
            elif nome in VISUAIS:
                time.sleep(0.6)                                  # LÊ A TELA DEPOIS de cada ação: confere o efeito antes do próximo passo
                L2, t2 = _olhar(20)
                novos = [l["t"] for l in L2 if l["t"] not in tela_ant][:10]      # só o que MUDOU na tela (não 900 caracteres)
                tela_ant = {l["t"] for l in L2}
                extra = f" | tela: {t2.splitlines()[0] if t2 else ''}; novo texto: " + (" / ".join(novos) or "nada novo")
            ok_v, ev = None, ""
            if antes is not None:
                try:
                    depois = _snap(nome)
                    depois["ocr"] = extra
                    ok_v, ev = VERIF[nome](args, res, antes, depois, ops)
                except Exception as e_v:
                    ok_v, ev = None, f"verificador falhou: {str(e_v)[:60]}"
            if ok_v is False:
                falhas += 1
                passos.append(f"[{nome}] NÃO FUNCIONOU ({ev}); resultado: {str(res)[:160]}{extra}")
                _log("verif_" + nome, args, False, 0, ev)
            else:
                if ok_v:
                    evid.append(f"{nome}: {ev}")
                trilha.append(f"{nome} {json.dumps(args, ensure_ascii=False, default=str)[:70]}")
                passos.append(f"[{nome}] ok{' (verificado: ' + ev + ')' if ok_v else ''}: {str(res)[:2500 if nome in _DADOS else 500]}{extra}")
                if nome in EFEITO:
                    feito = True
                    efeitos_feitos.add(nome)
                    if not eh_comp:
                        passos.append("(pedido cumprido: responda AGORA com final, sem repetir a ferramenta)")
        except Exception as e:
            falhas += 1
            _log(nome, args, False, time.time() - t0, repr(e))
            passos.append(f"[{nome}] FALHOU: {str(e)[:160]}")
    if final is None and feito:                                          # cumpriu (e verificou) mas o modelo não fechou: resume o resultado
        ult = next((p for p in reversed(passos) if "ok" in p[:40]), "")
        arq = re.search(r"(/[^\n:]+?\.(?:docx|xlsx|pptx|md))\b", ult)
        final = {"final": "Pronto, chefe. " + (f"Criei e abri {os.path.basename(arq.group(1))} no ONLYOFFICE." if arq else "Feito."), "pose": "confirmar", "humor": "neutro"}
        verificado = True if evid else verificado
    if final is None:
        _ult = next((p for p in reversed(passos) if not p.startswith("(")), "")      # nunca fala "(resposta inválida...)"
        final = {"final": "Não consegui concluir isso direito, chefe. " + _ult[:100], "pose": "neutro", "humor": "serio"}
        falhas += 1
        verificado = False
    elif verificado is False and not _NEG.search(str(final.get("final"))):     # checagem negativa: não finge que terminou
        _f = next((p for p in reversed(passos) if p.startswith("(VERIFICAÇÃO")), "")
        _falta = re.sub(r"^.*?falta:\s*|\. Continue.*$", "", _f)
        final = {"final": "Não consegui confirmar que terminei, chefe." + (f" Falta: {_falta[:120]}." if _falta else ""),
                 "pose": "neutro", "humor": "serio"}
    if falhas:
        try:
            _refletir(text, passos, fr)
        except Exception:
            pass
    if verificado is True and trilha and _ep is not None and not CANCEL.is_set():      # F7: só tarefa VERIFICADA vira episódio
        try:
            if _ep.ativo():
                _ep.gravar(text, " -> ".join(trilha[-8:]), str(final.get("final"))[:300])
        except Exception as e_ep:
            print("aviso episodios:", e_ep, flush=True)
    return {"fala": str(final.get("final"))[:420], "acoes": [], "pose": final.get("pose") or "neutro",
            "humor": final.get("humor") or "neutro", "lembrar": {}, "verificado": verificado, "evidencias": evid[-5:]}


def _refletir(pedido, passos, fr):
    """autoanálise: o que deu errado e que regra evita repetir."""
    d = fr.llm("Você analisa as próprias ações de um agente para melhorar. Responda JSON: "
               '{"licao":"UMA regra curta e acionável (imperativo) que evitaria o erro; \\"\\" se foi só azar"}',
               "Pedido: " + pedido + "\nPassos:\n" + "\n".join(passos[-6:]), None, True, 120, 0.1, 40)
    if isinstance(d, dict) and d.get("licao"):
        _add_licao(str(d["licao"]))


def analisar(fr=None):
    """resumo das últimas ações + lições (para 'o que você aprendeu?')."""
    try:
        L = [json.loads(l) for l in open(ACOES).read().splitlines()[-60:]]
    except Exception:
        L = []
    if not L:
        return "Ainda não executei ferramentas suficientes para analisar."
    ok = sum(1 for x in L if x["ok"])
    por = {}
    for x in L:
        a = por.setdefault(x["tool"], [0, 0, 0.0]); a[0 if x["ok"] else 1] += 1; a[2] += x["dur"]
    pior = sorted(por.items(), key=lambda kv: -kv[1][1])[0]
    s = f"Das últimas {len(L)} ações, {ok} deram certo. "
    if pior[1][1]:
        s += f"A que mais falha é {pior[0]} ({pior[1][1]} erros). "
    ls = licoes()[-3:]
    if ls:
        s += "O que aprendi: " + " ".join(x["txt"].rstrip(".") + "." for x in ls)
    return s
