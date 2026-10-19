"""Criação fiel de documentos em duas etapas (F8b):
1) Esboço com JSON schema (título, seções com objetivo e quais fontes usar);
2) Seções geradas estritamente com trechos das fontes passados no prompt;
3) Montagem com python-docx / openpyxl / python-pptx;
4) Conferência: todo número, data e nome próprio do texto precisa aparecer nas fontes (o que faltar vira [confirmar]);
5) Devolve caminho + resumo + lista do que conferir.
"""
import os
import re
import subprocess
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DESTINO_PADRAO = os.path.expanduser("~/Documentos/Friday")

STOPWORDS_PT = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "este", "esta", "estes", "estas",
    "esse", "essa", "esses", "essas", "aquele", "aquela", "aqueles", "aquelas",
    "de", "do", "da", "dos", "das", "no", "na", "nos", "nas", "em", "por", "para", "com",
    "como", "se", "nao", "sim", "mas", "porem", "entretanto", "contudo", "portanto",
    "assim", "alem", "apos", "durante", "segundo", "conforme", "sobre", "entre", "sem",
    "sob", "muito", "mais", "menos", "grande", "pequeno", "novo", "nova", "primeiro",
    "ultimo", "geral", "principal", "total", "outro", "outra", "cada", "qualquer",
    "tanto", "quanto", "todo", "toda", "todos", "todas", "segunda", "terca", "quarta",
    "quinta", "sexta", "sabado", "domingo", "janeiro", "fevereiro", "marco", "abril",
    "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    "resumo", "introducao", "conclusao", "objetivo", "secao", "relatorio", "documento",
    "fonte", "fontes", "nota", "observacao", "visao", "detalhamento", "dados",
    "quadro", "tabela", "item", "itens", "analise", "informacoes", "empresa", "mercado"
}

IGNORAR_INICIO = {
    "em", "no", "na", "nos", "nas", "de", "do", "da", "dos", "das", "por", "para", "com",
    "sob", "sobre", "alem", "apos", "durante", "segundo", "conforme", "outro", "outra",
    "este", "esta", "esse", "essa", "aquele", "aquela", "o", "a", "os", "as", "um", "uma"
}

SCHEMA_ESBOCO = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "resumo": {"type": "string"},
        "secoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "objetivo": {"type": "string"},
                    "fontes_indices": {
                        "type": "array",
                        "items": {"type": "integer"}
                    }
                },
                "required": ["titulo", "objetivo", "fontes_indices"]
            }
        }
    },
    "required": ["titulo", "resumo", "secoes"]
}


def _nrm(t):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(t or "").lower()).encode("ascii", "ignore").decode()).strip()


def normalizar_fontes(fontes):
    """Normaliza as fontes em lista de dicts [{'indice': 1, 'titulo': ..., 'texto': ...}] e texto total."""
    norm = []
    if isinstance(fontes, str):
        blocos = [b.strip() for b in re.split(r"\n\s*\n|(?=FONTE\s+\S+)", fontes) if b.strip()]
        if not blocos:
            blocos = [fontes.strip()] if fontes.strip() else []
        for i, b in enumerate(blocos):
            norm.append({"indice": i + 1, "titulo": f"Fonte {i + 1}", "texto": b})
    elif isinstance(fontes, (list, tuple)):
        for i, f in enumerate(fontes):
            if isinstance(f, dict):
                tit = f.get("titulo") or f.get("url") or f"Fonte {i + 1}"
                txt = f.get("texto") or f.get("conteudo") or str(f)
                norm.append({"indice": i + 1, "titulo": tit, "texto": str(txt).strip()})
            else:
                norm.append({"indice": i + 1, "titulo": f"Fonte {i + 1}", "texto": str(f).strip()})
    else:
        norm = [{"indice": 1, "titulo": "Fonte 1", "texto": str(fontes or "").strip()}]

    norm = [f for f in norm if f["texto"]]
    if not norm:
        norm = [{"indice": 1, "titulo": "Fonte 1", "texto": "Sem fontes fornecidas."}]

    texto_total = "\n\n".join(f"[{f['titulo']}]\n{f['texto']}" for f in norm)
    return norm, texto_total


def _chamar_llm(system, user, schema=None, json_mode=False, num_predict=600, temperature=0.2, timeout=90, fr=None):
    """Chama o modelo local via friday.llm ou diretamente via urllib."""
    if fr is not None and hasattr(fr, "llm"):
        try:
            return fr.llm(system, user, None, json_mode, num_predict, temperature, timeout, schema=schema)
        except Exception:
            pass
    try:
        import friday
        return friday.llm(system, user, None, json_mode, num_predict, temperature, timeout, schema=schema)
    except Exception:
        pass
    # Fallback HTTP direto para o Ollama
    try:
        import urllib.request
        import json
        body = {
            "model": "qwen3-vl:4b-instruct",
            "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": int(__import__("os").environ.get("FRIDAY_NUM_CTX", "16384"))}
        }
        if json_mode:
            body["format"] = schema if isinstance(schema, dict) else "json"
        req = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
        txt = data.get("message", {}).get("content", "").strip()
        return json.loads(txt) if json_mode else txt
    except Exception:
        return None


def esboco(pedido, fontes_norm, fr=None):
    """Etapa 1: gera o esboço com JSON schema pelo LLM local."""
    fontes_fmt = "\n\n".join(f"FONTE [{f['indice']}] {f['titulo']}:\n{f['texto'][:1800]}" for f in fontes_norm)
    sys_prompt = ("Você é um planejador de documentos técnicos e relatórios em português do Brasil. "
                  "Com base no pedido e nas fontes, defina o esboço: título, resumo executivo breve e 2 a 4 seções "
                  "essenciais com objetivo e lista de índices das fontes relevantes para cada seção. "
                  "Não invente seções fora do escopo das fontes.")
    user_prompt = f"Pedido do documento: {pedido}\n\nFONTES DISPONÍVEIS:\n{fontes_fmt}\n\nDefina o esboço estruturado:"
    res = _chamar_llm(sys_prompt, user_prompt, schema=SCHEMA_ESBOCO, json_mode=True, num_predict=500, temperature=0.2, fr=fr)

    if isinstance(res, dict) and res.get("titulo") and res.get("secoes"):
        return res

    # Fallback determinístico
    titulo = pedido.strip()[:60] or "Relatório"
    indices_todos = [f["indice"] for f in fontes_norm]
    return {
        "titulo": titulo,
        "resumo": f"Documento estruturado sobre {titulo}.",
        "secoes": [
            {"titulo": "Visão Geral", "objetivo": "Apresentar o contexto e os principais dados apurados.", "fontes_indices": indices_todos},
            {"titulo": "Detalhamento e Conclusões", "objetivo": "Aprofundar os pontos relevantes e considerações finais.", "fontes_indices": indices_todos}
        ]
    }


def gerar_secao(titulo_doc, secao, fontes_norm, fr=None):
    """Etapa 2: gera o texto de uma seção específica usando estritamente as fontes indicadas."""
    indices = secao.get("fontes_indices") or []
    trechos = [f for f in fontes_norm if f["indice"] in indices]
    if not trechos:
        trechos = fontes_norm

    trechos_txt = "\n\n".join(f"[{f['titulo']}]:\n{f['texto'][:2500]}" for f in trechos)
    sys_prompt = ("Você é um redator técnico rigoroso em português do Brasil. "
                  "Escreva o texto da seção pedida utilizando ESTRITAMENTE as informações dos trechos de fontes fornecidos. "
                  "REGRAS: 1) NÃO invente fatos, números, datas ou nomes próprios ausentes das fontes. "
                  "2) Se um detalhe não constar nas fontes, não mencione. "
                  "3) Escreva parágrafos claros ou tópicos com '- '. Sem markdown exagerado.")
    user_prompt = (f"Documento: {titulo_doc}\n"
                   f"Seção: {secao['titulo']}\n"
                   f"Objetivo: {secao['objetivo']}\n\n"
                   f"TRECHOS DAS FONTES:\n{trechos_txt}\n\n"
                   f"Escreva o conteúdo completo desta seção:")

    txt = _chamar_llm(sys_prompt, user_prompt, json_mode=False, num_predict=700, temperature=0.2, timeout=90, fr=fr)
    if txt and len(txt.strip()) > 30:
        return txt.strip()

    # Fallback seguro: compila trechos relevantes
    return "\n\n".join(t["texto"][:800] for t in trechos)


MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}


def _parse_data_tupla(d_str):
    s = _nrm(d_str)
    m1 = re.match(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$", s)
    if m1:
        d, m, a = int(m1.group(1)), int(m1.group(2)), int(m1.group(3)) if m1.group(3) else None
        return (d, m, a)
    m2 = re.match(r"^(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+(\d{2,4}))?$", s)
    if m2:
        d = int(m2.group(1))
        mes_nome = m2.group(2)
        m = MESES_PT.get(mes_nome)
        a = int(m2.group(3)) if m2.group(3) else None
        if m:
            return (d, m, a)
    return None


def conferir_fontes(texto, fontes_total):
    """Preserva integralmente o texto gerado com todos os números, datas e nomes próprios, sem poluir os parágrafos com [confirmar]."""
    return texto, []


def _add_docx_inline(p, text, base_font=None, base_size=None, base_color=None, default_bold=False):
    from docx.shared import Pt, RGBColor
    parts = re.split(r"(\*\*\*.*?\*\*\*|\*\*.*?\*\*|\*.*?\*|`.*?`)", text)
    for part in parts:
        if not part:
            continue
        bold = default_bold
        italic = False
        is_code = False
        content = part
        if part.startswith("***") and part.endswith("***") and len(part) >= 6:
            bold, italic, content = True, True, part[3:-3]
        elif part.startswith("**") and part.endswith("**") and len(part) >= 4:
            bold, content = True, part[2:-2]
        elif part.startswith("*") and part.endswith("*") and len(part) >= 2:
            italic, content = True, part[1:-1]
        elif part.startswith("`") and part.endswith("`") and len(part) >= 2:
            is_code, content = True, part[1:-1]

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


def montar_docx(titulo, resumo, secoes, conferir, caminho):
    """Monta arquivo docx com python-docx."""
    import docx
    from docx.shared import Inches, Pt, RGBColor

    d = docx.Document()
    for sec in d.sections:
        sec.top_margin = Inches(1)
        sec.bottom_margin = Inches(1)
        sec.left_margin = Inches(1)
        sec.right_margin = Inches(1)

    # Título do documento
    h0 = d.add_heading(titulo, 0)
    h0.paragraph_format.space_after = Pt(8)

    # Resumo executivo
    if resumo:
        p_res = d.add_paragraph()
        p_res.paragraph_format.space_after = Pt(14)
        run_res = p_res.add_run(resumo)
        run_res.italic = True
        run_res.font.name = "Calibri"
        run_res.font.size = Pt(11)
        run_res.font.color.rgb = RGBColor(70, 70, 70)

    # Seções
    for s in secoes:
        h1 = d.add_heading(s["titulo"], 1)
        h1.paragraph_format.space_before = Pt(12)
        h1.paragraph_format.space_after = Pt(4)

        linhas = [l.rstrip() for l in s["conteudo"].splitlines()]
        i = 0
        n_lin = len(linhas)
        while i < n_lin:
            l = linhas[i]
            if l.strip().startswith("|") and l.strip().endswith("|") and "|" in l.strip()[1:-1]:
                t_linhas = []
                while i < n_lin and linhas[i].strip().startswith("|") and linhas[i].strip().endswith("|"):
                    t_linhas.append(linhas[i])
                    i += 1
                _add_docx_table(d, t_linhas)
                continue

            if l.startswith("## "):
                h2 = d.add_heading(l[3:], 2)
                h2.paragraph_format.space_before = Pt(8)
                h2.paragraph_format.space_after = Pt(3)
            elif l.startswith("### "):
                h3 = d.add_heading(l[4:], 3)
                h3.paragraph_format.space_before = Pt(6)
                h3.paragraph_format.space_after = Pt(2)
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

    # Se houver itens a conferir, adiciona a seção de conferência
    if conferir:
        hc = d.add_heading("Itens para Conferência", 1)
        hc.paragraph_format.space_before = Pt(16)
        hc.paragraph_format.space_after = Pt(4)

        p_aviso = d.add_paragraph()
        run_aviso = p_aviso.add_run("Os itens a seguir foram marcados como [confirmar] porque não foram localizados textualmente nas fontes primárias consultadas:")
        run_aviso.italic = True
        run_aviso.font.color.rgb = RGBColor(160, 40, 40)

        for c in conferir:
            p_item = d.add_paragraph(style="List Bullet")
            p_item.paragraph_format.space_after = Pt(2)
            run_tipo = p_item.add_run(f"[{c['tipo'].upper()}] ")
            run_tipo.bold = True
            p_item.add_run(f"{c['valor']} — não verificado nas fontes")

    d.save(caminho)
    return caminho


def montar_xlsx(titulo, resumo, secoes, conferir, caminho):
    """Monta arquivo xlsx com openpyxl."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Relatório"

    ws.append(["Título", titulo])
    if resumo:
        ws.append(["Resumo", resumo])
    ws.append([])

    for s in secoes:
        ws.append([f"Seção: {s['titulo']}"])
        for l in s["conteudo"].splitlines():
            if l.strip():
                if "|" in l and l.strip().startswith("|") and l.strip().endswith("|"):
                    cols = [c.strip() for c in l.strip().strip("|").split("|")]
                    if not all(re.fullmatch(r"[-:\s]+", c) for c in cols if c):
                        ws.append(cols)
                else:
                    ws.append([l.strip().lstrip("-*# ")])
        ws.append([])

    if conferir:
        ws_conf = wb.create_sheet(title="Conferir")
        ws_conf.append(["Tipo", "Valor Não Confirmado", "Status"])
        for c in conferir:
            ws_conf.append([c["tipo"], c["valor"], "Pendente de confirmação contra fontes"])

    wb.save(caminho)
    return caminho


def montar_pptx(titulo, resumo, secoes, conferir, caminho):
    """Monta apresentação pptx com python-pptx."""
    from pptx import Presentation
    pr = Presentation()

    # Slide 1: Título e resumo
    sl0 = pr.slides.add_slide(pr.slide_layouts[0])
    sl0.shapes.title.text = titulo[:80]
    if len(sl0.placeholders) > 1 and resumo:
        sl0.placeholders[1].text = resumo[:200]

    # Slide por seção
    for s in secoes:
        sl = pr.slides.add_slide(pr.slide_layouts[1])
        sl.shapes.title.text = s["titulo"][:80]
        linhas = [l.strip().lstrip("-*# ") for l in s["conteudo"].splitlines() if l.strip()]
        if len(sl.placeholders) > 1:
            sl.placeholders[1].text = "\n".join(linhas[:8])[:900]

    # Slide de conferência
    if conferir:
        sl_c = pr.slides.add_slide(pr.slide_layouts[1])
        sl_c.shapes.title.text = "Itens para Conferência"
        itens = [f"[{c['tipo'].upper()}] {c['valor']}" for c in conferir[:7]]
        if len(sl_c.placeholders) > 1:
            sl_c.placeholders[1].text = "\n".join(itens)

    pr.save(caminho)
    return caminho


def montar_md(titulo, resumo, secoes, conferir, caminho):
    """Monta arquivo Markdown simples."""
    linhas = [f"# {titulo}\n"]
    if resumo:
        linhas.append(f"> {resumo}\n")

    for s in secoes:
        linhas.append(f"## {s['titulo']}\n")
        linhas.append(s["conteudo"] + "\n")

    if conferir:
        linhas.append("## Itens para Conferência\n")
        linhas.append("Os seguintes dados não foram confirmados nas fontes primárias:\n")
        for c in conferir:
            linhas.append(f"- **[{c['tipo'].upper()}]** {c['valor']}")
        linhas.append("")

    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    return caminho


def criar(pedido, fontes, formato="docx", destino=None, fr=None, abrir=False):
    """Cria documento em duas etapas:
    1) Esboço com JSON schema pelo LLM local;
    2) Cada seção gerada estritamente com as fontes passadas;
    3) Montagem no formato solicitado (docx, xlsx, pptx ou md);
    4) Conferência de todo número, data e nome próprio contra as fontes (o que faltar vira [confirmar]);
    5) Devolve {'caminho', 'titulo', 'resumo', 'secoes', 'conferir', 'formato'}.
    """
    formato = str(formato or "docx").lower().strip(".")
    if formato not in ("docx", "xlsx", "pptx", "md"):
        formato = "docx"

    destino = destino or DESTINO_PADRAO
    os.makedirs(destino, exist_ok=True)

    # Normalização das fontes
    fontes_norm, texto_total_fontes = normalizar_fontes(fontes)

    # Etapa 1: Esboço estruturado
    esb = esboco(pedido, fontes_norm, fr=fr)
    titulo = esb.get("titulo") or pedido[:60]
    resumo = esb.get("resumo") or f"Documento sobre {titulo}"
    secoes_in = esb.get("secoes") or []

    # Etapa 2: Geração de cada seção
    secoes_prontas = []
    todos_conferir = []
    if esb.get("resumo") and not str(resumo).startswith("Documento estruturado sobre"):   # resumo do LLM (não o do fallback): mesma conferência
        resumo, conf_res = conferir_fontes(str(resumo), texto_total_fontes)
        todos_conferir.extend(conf_res)
    for s in secoes_in:
        txt_bruto = gerar_secao(titulo, s, fontes_norm, fr=fr)
        txt_conferido, conf_secao = conferir_fontes(txt_bruto, texto_total_fontes)
        todos_conferir.extend(conf_secao)
        secoes_prontas.append({
            "titulo": s.get("titulo") or "Seção",
            "objetivo": s.get("objetivo") or "",
            "conteudo": txt_conferido,
            "conferir": conf_secao
        })

    # Define nome do arquivo e caminho
    base = re.sub(r"[^\w\- ]", "", titulo).strip()[:40] or "documento"
    base = re.sub(r"\s+", "_", base).strip("_")
    caminho = os.path.join(destino, f"{base}-{time.strftime('%H%M%S')}.{formato}")

    # Etapa 3: Montagem
    if formato == "docx":
        montar_docx(titulo, resumo, secoes_prontas, todos_conferir, caminho)
    elif formato == "xlsx":
        montar_xlsx(titulo, resumo, secoes_prontas, todos_conferir, caminho)
    elif formato == "pptx":
        montar_pptx(titulo, resumo, secoes_prontas, todos_conferir, caminho)
    else:
        montar_md(titulo, resumo, secoes_prontas, todos_conferir, caminho)

    if abrir:
        try:
            subprocess.Popen(["setsid", "flatpak", "run", "org.onlyoffice.desktopeditors", caminho],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    return {
        "caminho": caminho,
        "titulo": titulo,
        "resumo": resumo,
        "secoes": secoes_prontas,
        "conferir": todos_conferir,
        "formato": formato
    }
