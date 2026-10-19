"""Executor de PLANOS da F.R.I.D.A.Y.: tarefas grandes e compostas ("pesquise X e monte uma apresentação", "desenvolva X").
O modelo local divide o pedido em etapas tipadas; cada etapa recebe o que as anteriores produziram (memória de trabalho),
o resultado é conferido (refaz 1x se falhar) e o andamento fica salvo em memory/planos/ para retomar.
Tipos: pesquisar | documento | programar | pc | resumir. "programar" usa o Claude CLI (via callback do daemon)."""
import json
import os
import re
import subprocess
import time

import threading
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
DIR = os.path.join(HERE, "..", "memory", "planos")
MAX_ETAPAS = 7
SKIP = threading.Event()

SYS_PLANO = """Você planeja tarefas para a F.R.I.D.A.Y., assistente que opera o PC do dono (pt-BR). Divida o pedido em ETAPAS executáveis, na ordem.
Tipos de etapa:
 ver        -> OLHAR pelas câmeras: o que ele segura na mão, o que mostra, o que há no ambiente (objetivo = a pergunta visual)
 ia         -> perguntar ao ChatGPT/Gemini/Claude/Perplexity do dono NO NAVEGADOR (objetivo = a pergunta completa; use quando ele citar uma dessas IAs)
 pesquisar  -> buscar e ler na internet (objetivo = o que descobrir, termos claros; ela já abre o navegador e pesquisa automaticamente, NÃO precisa de etapa "pc" antes só para abrir o navegador)
 zap        -> enviar mensagem no WhatsApp/ZapZap para um contato com o texto ou resultado apurado (objetivo = 'enviar mensagem no WhatsApp para [contato]: [resumo do que enviar]')
 email      -> enviar e-mail para um destinatário
 documento  -> criar arquivo no ONLYOFFICE (formato docx|xlsx|pptx). ATENÇÃO: NUNCA crie etapa de "documento" se o pedido for enviar mensagem, falar, avisar, mandar no WhatsApp/zap, e-mail, ou apenas responder. Use "documento" SOMENTE quando o dono pedir explicitamente as palavras "documento", "arquivo", "relatório", "docx", "planilha", "excel", "slides" ou "pptx".
 programar  -> escrever/alterar CÓDIGO, criar sistema/app/site/script (vai para o programador)
 pc         -> operar o PC: abrir apps específicos, clicar, tocar mídia, mexer em janelas
 resumir    -> sintetizar o que já foi apurado numa resposta falada ao dono

REGRAS:
- Se o dono pediu para pesquisar e mandar/enviar para alguém no zap/whatsapp: Etapa 1: "pesquisar", Etapa 2: "zap" (enviar mensagem no WhatsApp para o contato com os dados apurados). NUNCA crie documento!
- Não invente etapas redundantes: 1 a 3 etapas são suficientes para quase tudo.
- Se o pedido for no CELULAR do dono, use etapas "pc" e escreva "no celular" em cada objetivo.
- Arquivos, pastas, disco, processos ou programas do PC: etapa "pc" com objetivo "usar o terminal para ..." (ex.: "usar o terminal para listar ~/Downloads").
  NUNCA abra o navegador para ver arquivos locais.
EXEMPLO 1:
{{"titulo":"Pesquisar Fortnite e enviar WhatsApp","etapas":[{{"tipo":"pesquisar","objetivo":"site oficial da loja do fortnite itens e precos de hoje"}},{{"tipo":"zap","contato":"integra code","objetivo":"Enviar mensagem no WhatsApp para integra code com os itens e preços da loja"}}]}}
EXEMPLO 2:
{{"titulo":"Pesquisar IA e criar relatório","etapas":[{{"tipo":"pesquisar","objetivo":"pesquisar sobre novidades de inteligência artificial"}},{{"tipo":"documento","formato":"docx","objetivo":"criar documento docx sobre IA com as informações apuradas"}}]}}

Responda SÓ JSON: {{"titulo":"nome curto da tarefa","etapas":[{{"tipo":"pesquisar|zap|email|documento|programar|pc|ver|ia|resumir","objetivo":"...","formato":"docx|xlsx|pptx|"}}]}}
Contexto: {ctx}"""

SYS_DOC = """Você é a F.R.I.D.A.Y. e escreve o CONTEÚDO executivo de alta qualidade de um arquivo {formato} para o dono em pt-BR, baseado nas informações apuradas (não invente dados inexistentes; seja precisa, rica em detalhes e profissional).

Diretrizes de formatação:
- Em docx:
  * Use hierarquia clara de títulos: "# Título Principal", "## Seção Principal", "### Subseção".
  * DESTAQUE com **negrito** todos os termos-chave, datas, nomes próprios, métricas, porcentagens e conclusões cruciais.
  * Sempre que houver comparações, listas de atributos, métricas ou dados estruturados, inclua TABELAS em markdown (| Coluna 1 | Coluna 2 | ...).
  * Use listas com marcadores organizados: "- **Conceito/Item**: explicação detalhada".
  * Estruture com Introdução/Contexto, Análise/Detalhamento, Tabela Resumo/Comparativa (se aplicável), e Recomendações/Conclusão.
- Em xlsx:
  * Cada linha é uma linha da planilha com colunas separadas por " | ".
  * A 1ª linha DEVE ser o cabeçalho com nomes descritivos.
- Em pptx:
  * Cada "# " inicia um novo slide com título conciso.
  * Abaixo de cada slide, coloque 3 a 5 tópicos curtos em bullet points ("- **Ponto**: detalhe").

Responda ESTRITAMENTE JSON: {{"nome":"título descritivo do arquivo","conteudo":"..."}}"""


def _salvar(p):
    os.makedirs(DIR, exist_ok=True)
    try:
        json.dump(p, open(os.path.join(DIR, p["id"] + ".json"), "w"), ensure_ascii=False, indent=1)
    except Exception:
        pass


def ultimo_incompleto():
    try:
        arqs = sorted(f for f in os.listdir(DIR) if f.endswith(".json"))
        for f in reversed(arqs):
            p = json.load(open(os.path.join(DIR, f)))
            if p.get("estado") not in ("concluido", "cancelado"):
                return p
    except Exception:
        pass
    return None


def ultimo_concluido():
    try:
        arqs = sorted(f for f in os.listdir(DIR) if f.endswith(".json"))
        for f in reversed(arqs):
            p = json.load(open(os.path.join(DIR, f)))
            if p.get("estado") == "concluido" and any(e.get("resultado") for e in p.get("etapas", [])):
                return p
    except Exception:
        pass
    return None


def _limpa_contato(c):
    if not c:
        return ""
    c = re.sub(r"^(?:(?:prepare|preparar|favor|por favor|tente|escreva|escrever|envie|enviar|mande|mandar)?\s*(?:para\s+)?(?:uma\s+)?(?:mensagem\s+)?(?:para|a|ao|pro)\s+)", "", c, flags=re.I)
    c = re.sub(r"^(?:(?:o|a|meu|minha|um|uma)\s+)?(?:amig[oa]|contat[oa]|coleg[oa]|brother|parceir[oa]|irm[ãa]o)\b[:,]?\s*", "", c, flags=re.I)
    c = re.sub(r"^(?:para|ao|pro|a)\s+", "", c, flags=re.I)
    c = re.sub(r"\s+(?:no|pelo|via)\s+(?:zap(?:\s?zap)?|whatsapp)\b.*$", "", c, flags=re.I)
    c = re.sub(r"^[^\w@]+|[^\w]+$", "", c).strip()
    c = re.sub(r"^@+", "", c).strip()
    c = re.sub(r"\bintegrea\b", "integra", c, flags=re.I)
    return c


def _consulta_limpa(texto):
    """Tira o que foi falado em volta e fica com o assunto. Não pesquisa a frase inteira."""
    q = str(texto or "")
    q = re.sub(r"(?is)^.*?\b(?:pesquis\w*|busc\w*|procur\w*|investig\w*)\s+", "", q, count=1)
    q = re.split(r"(?i)\s+e\s+(?:depois\s+)?(?:mand\w*|envi\w*|escrev\w*|cri\w*|mont\w*|faz\w*|prepar\w*)\b", q, maxsplit=1)[0]
    q = re.sub(r"(?i)\s+e\s+me\s+(?:fala|diz|conta)\b.*$", "", q)
    q = re.sub(r"(?i)\b(?:sexta[- ]?feira|friday|por favor|me fala|me diz|me conta|quero saber|acessar o site oficial e)\b", " ", q)
    q = re.sub(r"(?i)^(?:sobre|por)\s+", "", q.strip())
    q = re.sub(r"\s+", " ", q).strip(" ,.!?")
    q = re.sub(r"(?i)\s+e$", "", q)
    cmd = re.compile(
        r"(?i)^\s*(?:e\s+)?(?:entr\w*|abr\w*|acesse|vai|pesquis\w*|busc\w*|procur\w*)\s+"
        r"(?:(?:no|na|ao|o|a)\s+)?(?:site|p[aá]gina|portal|navegador)?\s*(?:e\s+)?(?:pesquis\w*|busc\w*)?\s*(?:sobre|por)?\s*"
    )
    for _ in range(4):
        n = cmd.sub("", q).strip()
        if not n or n == q:
            break
        q = n
    q = re.sub(r"(?i)\bfortin[ae]te\b", "fortnite", q)
    return q[:90]


def _fatos_das_paginas(textos, consulta):
    """Frases que falam do assunto. Menu, cookie e texto sem as palavras da busca ficam de fora."""
    chaves = [w for w in re.findall(r"\w{4,}", (consulta or "").lower()) if w not in ("para", "sobre", "como", "quando", "onde", "qual")][:6]
    frases = []
    for bloco in textos:
        bloco = re.sub(r"(?i)^FONTE \S+\s*", "", bloco)
        for sent in re.split(r"(?<=[.!?])\s+", bloco):
            s = re.sub(r"\s+", " ", sent).strip()
            if len(s) < 40 or len(s) > 280:
                continue
            if re.search(r"cookie|javascript|privacidade|inscreva|aceitar|menu|newsletter|exibindo resultados|vou pesquisar", s, re.I):
                continue
            if chaves and not any(k in s.lower() for k in chaves):
                continue
            if s not in frases:
                frases.append(s)
            if len(frases) >= 4:
                break
    if not frases and chaves:
        blob = re.sub(r"\s+", " ", " ".join(textos))
        low = blob.lower()
        for k in chaves:
            i = low.find(k)
            if i >= 0:
                frases.append(blob[max(0, i - 80):i + 220].strip())
                break
    return " ".join(frases[:4])


def planejar(pedido, fr, ctx=""):
    ped_limpo = (pedido or "").strip()
    ped_lower = ped_limpo.lower()

    # Atalho Determinístico Composto: Pesquisar (+ entrar no site) + Zap/Mensagem
    m_zap = re.search(
        r"(?is)^\s*(?:sexta[- ]?feira[,:\s]*)?(?:por\s+favor[,:\s]*)?"
        r"(?:(?:entr\w*|abr\w*|vai)\s+(?:no\s+|na\s+|o\s+|a\s+)?navegador\s+(?:e\s+)?)?"
        r"(?:pesquis\w*|busc\w*|procur\w*)\s+"
        r"(?:(?:e\s+)?(?:entr\w*|acess\w*|abr\w*)\s+(?:no\s+|na\s+|ao\s+)?(?:site|p[áa]gina|loja|portal)?\s*)?"
        r"(?:sobre\s+|por\s+|o\s+que\s+[ée]\s+)?(.+?)\s+e\s+(?:depois\s+)?"
        r"(?:prepar\w*|escrev\w*|redij\w*|envi\w*|mand\w*)\s+.{0,80}?"
        r"(?:para|pro|pra|ao|à)\s+([@A-Za-zÀ-ÿ0-9][\wÀ-ÿ @.'+-]{1,40}?)"
        r"(?=\s+no\s+(?:whats(?:app)?|zap(?:zap)?)\b|\s+com\b|\s+dizendo\b|$)"
        r"(?:\s+no\s+(?:whats(?:app)?|zap(?:zap)?))?(?:\s+dizendo\s+(.+))?(?:\s+com\s+.+)?\s*$", ped_limpo)
    if m_zap:
        tema = m_zap.group(1).strip()
        contato = _limpa_contato(m_zap.group(2).strip())
        if not contato or re.fullmatch(r"[0-9+\s()-]{6,}", contato):
            contato = ""
        extra = (m_zap.group(3) or "").strip()
        tema_norm = re.sub(r"\bfortin[aei]te\b", "fortnite", tema, flags=re.I)
        deve_abrir = bool(re.search(r"\b(entr\w*|acess\w*|abr\w*)\s+(?:no\s+|na\s+|ao\s+)?(?:site|p[áa]gina|loja|portal)\b", ped_lower))
        if "fortnite" in tema_norm.lower():
            obj_pesq = "site oficial da loja do fortnite e itens à venda hoje"
        else:
            obj_pesq = f"acessar o site oficial e pesquisar sobre {tema_norm}" if deve_abrir else f"pesquisar {tema_norm}"
        et = [
            {"tipo": "pesquisar", "objetivo": obj_pesq},
            {"tipo": "zap", "contato": contato, "objetivo": f"Enviar mensagem no WhatsApp para {contato} com as informações apuradas" + (f": {extra}" if extra else "")}
        ]
        return {
            "id": time.strftime("%Y%m%d-%H%M%S"),
            "pedido": pedido,
            "titulo": f"Pesquisar {tema_norm} e preparar mensagem para {contato}"[:60],
            "etapas": [{**e, "estado": "pendente", "resultado": ""} for e in et],
            "estado": "executando",
            "inicio": time.time()
        }

    # Atalho Determinístico Composto: Pesquisar + Criar Documento/Relatório
    m_doc = re.search(
        r"(?is)^\s*(?:sexta[- ]?feira[,:\s]*)?(?:por\s+favor[,:\s]*)?(?:pesquis\w*|busc\w*|procur\w*)\s+"
        r"(?:sobre\s+|por\s+)?(.+?)\s+e\s+(?:depois\s+)?"
        r"(?:cri\w*|ger\w*|salv\w*|escrev\w*|mont\w*|fa[çc]\w*|faz\w*)\s+"
        r"(?:um\s+|uma\s+|num\s+|numa\s+)?(?:arquivo|documento|docs?|relat[óo]rio|resumo|nota|artigo|pdf|docx|txt|md)"
        r"(?:\s+(?:em\s+)?(pdf|docx|xlsx|pptx|txt|md))?"
        r"(?:\s+(?:chamado|com\s+nome)\s+([\w\-. ]+))?.*$", ped_limpo)
    if m_doc:
        tema = m_doc.group(1).strip()
        fmt = (m_doc.group(2) or ("pdf" if "pdf" in ped_lower else "docx")).lower().strip(".")
        tit = (m_doc.group(3) or f"Relatório {tema}").strip()
        et = [
            {"tipo": "pesquisar", "objetivo": f"pesquisar sobre {tema}"},
            {"tipo": "documento", "formato": fmt, "objetivo": f"criar {fmt} sobre {tema} chamado {tit} com as informações apuradas"}
        ]
        return {
            "id": time.strftime("%Y%m%d-%H%M%S"),
            "pedido": pedido,
            "titulo": f"Pesquisar {tema} e criar documento"[:60],
            "etapas": [{**e, "estado": "pendente", "resultado": ""} for e in et],
            "estado": "executando",
            "inicio": time.time()
        }

    d = fr.llm(SYS_PLANO.format(max=MAX_ETAPAS, ctx=ctx or "—"), pedido, None, True, 500, 0.2, 90)
    et = [e for e in (d or {}).get("etapas", []) if isinstance(e, dict) and e.get("tipo") in ("ver", "ia", "pesquisar", "zap", "email", "documento", "programar", "pc", "resumir")
          and str(e.get("objetivo", "")).strip()][:MAX_ETAPAS]
    if not et:
        et = [{"tipo": "pc", "objetivo": pedido}]
    mia = re.search(r"\b(chat\s*gpt|gemini|perplexity|claude)\b", pedido, re.I)
    if mia and not any(e["tipo"] == "ia" for e in et):     # ele pediu uma IA específica: a 1ª consulta é nela, não na web
        for e in et:
            if e["tipo"] == "pesquisar":
                e["tipo"] = "ia"; break
        else:
            et.insert(0, {"tipo": "ia", "objetivo": re.sub(r"^.*?para perguntar:\s*", "", pedido)})
    for e in et:
        if e["tipo"] == "ia":
            e["site"] = {"cha": "chatgpt", "gem": "gemini", "per": "perplexity", "cla": "claude"}.get((mia.group(1)[:3].lower() if mia else "cha"), "chatgpt")
    if not re.search(r"\b(celular|telefone|smartphone|meu cel|no cel)\b", pedido, re.I):     # o modelo inventava "no celular"
        for e in et:
            e["objetivo"] = re.sub(r"\s*\b(?:no|do|pelo)\s+celular\b\s*:?\s*", " ", e["objetivo"], flags=re.I).strip()
    
    # Se o pedido NÃO pediu explicitamente documento/planilha/slide, remove qualquer etapa "documento" inventada
    ped_lower = pedido.lower()
    pediu_doc = bool(re.search(r"\b(document\w*|docx|planilh\w*|xlsx|excel|slides?|apresenta[çc]\w*|pptx|relat[óo]rio|arquivo)\b", ped_lower))
    if not pediu_doc:
        for e in et:
            if e["tipo"] == "documento":
                if re.search(r"\b(zap|whatsapp|mensag\w*|amig\w*|contato|mandar|enviar|avise|avisar)\b", ped_lower):
                    e["tipo"] = "zap"
                else:
                    e["tipo"] = "resumir"
            e.pop("formato", None)
    else:
        for e in et:                                   # entregável de escritório é documento, não código
            fmt = str(e.get("formato") or "").lower().strip(".")
            if e["tipo"] in ("programar", "pc") and (fmt in ("docx", "xlsx", "pptx") and e["tipo"] == "programar"
                                                     or re.search(r"\b(planilh|apresenta[çc]|slides?|relat[óo]rio|documento|docx|xlsx|pptx)", e["objetivo"], re.I)):
                e["tipo"] = "documento"
                if fmt not in ("docx", "xlsx", "pptx"):
                    fmt = "xlsx" if re.search(r"planilh|xlsx", e["objetivo"], re.I) else "pptx" if re.search(r"apresenta|slide|pptx", e["objetivo"], re.I) else "docx"
                e["formato"] = fmt

    # Se o pedido é para enviar no zap/mensagem mas o modelo não incluiu a etapa zap, inclui no final
    _pede_msg = bool(re.search(
        r"\b(zap|whatsapp|msg|mensag\w*|prepare\s+uma\s+mensagem|preparar\s+uma\s+mensagem|escreva\s+uma\s+mensagem|"
        r"escrever\s+uma\s+mensagem|mande\s+uma\s+mensagem|mandar\s+uma\s+mensagem|envie\s+uma\s+mensagem|"
        r"enviar\s+uma\s+mensagem|mande\s+para|manda\s+para|enviar\s+para|envie\s+para|avise\s+para|avisar\s+para|"
        r"prepare\s+mensagem|preparar\s+mensagem|escreva\s+mensagem|escrever\s+mensagem)\b", ped_lower))
    if _pede_msg and not any(e["tipo"] == "zap" for e in et):
        m_alvo = re.search(r"(?:prepare|preparar|escreva|escrever|enviar|mandar|avise|avisar|mande|manda)?\s*(?:uma\s+)?(?:mensagem\s+)?(?:para|ao|pro)\s+([A-ZÀ-Úa-zà-ú0-9_ -]+?)(?::|\s+com\b|\s+dizendo|\s+sobre|\s+as\s+informa|\s+(?:no|pelo|via)\s+(?:zap(?:\s?zap)?|whatsapp)|$)", pedido, re.I)
        alvo = _limpa_contato(m_alvo.group(1).strip()) if m_alvo else "contato"
        et.append({"tipo": "zap", "contato": alvo, "objetivo": f"Enviar mensagem no WhatsApp para {alvo} com as informações apuradas"})

    for e in et:
        if e.get("tipo") in ("zap", "whatsapp"):
            c = _limpa_contato(e.get("contato") or "")
            if not c:
                m_c = re.search(r"(?:prepare|preparar|escreva|escrever|enviar|mandar|avise|avisar|mande|manda)?\s*(?:uma\s+)?(?:mensagem\s+)?(?:para|ao|pro)\s+([A-ZÀ-Úa-zà-ú0-9_ -]+?)(?::|\s+com\b|\s+dizendo|\s+sobre|\s+as\s+informa|\s+(?:no|pelo|via)\s+(?:zap(?:\s?zap)?|whatsapp)|$)", e.get("objetivo", ""), re.I)
                if m_c:
                    c = _limpa_contato(m_c.group(1).strip())
            if not c:
                m_c = re.search(r"(?:prepare|preparar|escreva|escrever|enviar|mandar|avise|avisar|mande|manda)?\s*(?:uma\s+)?(?:mensagem\s+)?(?:para|ao|pro)\s+([A-ZÀ-Úa-zà-ú0-9_ -]+?)(?::|\s+com\b|\s+dizendo|\s+sobre|\s+as\s+informa|\s+(?:no|pelo|via)\s+(?:zap(?:\s?zap)?|whatsapp)|$)", pedido, re.I)
                if m_c:
                    c = _limpa_contato(m_c.group(1).strip())
            if c and c.lower() not in ("amigo", "um amigo", "meu amigo", "alguém", "alguem", "um contato", "contato"):
                e["contato"] = c

    # Elimina etapa "pc" redundante de abrir navegador antes de pesquisar
    if len(et) >= 2 and et[0]["tipo"] == "pc" and re.search(r"\b(abrir|abre|iniciar|lan[çc]ar)\s+(?:o\s+)?(chromium|navegador|browser|chrome)\b", et[0]["objetivo"], re.I) and et[1]["tipo"] in ("pesquisar", "ia"):
        et.pop(0)

    junta = []                                     # passos de PC seguidos viram um só (o agente faz a sequência lendo a tela)
    for e in et:
        if junta and e["tipo"] == "pc" and junta[-1]["tipo"] == "pc":
            junta[-1]["objetivo"] += " e depois " + e["objetivo"][:1].lower() + e["objetivo"][1:]
        else:
            junta.append(e)
    et = junta
    return {"id": time.strftime("%Y%m%d-%H%M%S"), "pedido": pedido, "titulo": str((d or {}).get("titulo") or pedido)[:60],
            "etapas": [{**e, "estado": "pendente", "resultado": ""} for e in et], "estado": "executando", "inicio": time.time()}


def _memoria(p, limite=3500):
    partes = [f"[{i + 1}. {e['tipo']}: {e['objetivo'][:80]}]\n{e['resultado']}" for i, e in enumerate(p.get("etapas", [])) if e.get("estado") == "ok" and e.get("resultado")]
    mem = "\n\n".join(partes)[-limite:]
    if not mem.strip() and re.search(r"\b(anterior|anteriores|j[aá] apurad|dados de antes|da pesquisa anterior|do que pesquisou|com base no que|com o que voc[eê])\b", p.get("pedido", ""), re.I):
        # se o plano atual começou citando dados anteriores, puxa do último concluído
        u = ultimo_concluido()
        if u and u.get("id") != p.get("id"):
            u_partes = [f"[{i + 1}. {e['tipo']}: {e['objetivo'][:80]}]\n{e['resultado']}" for i, e in enumerate(u.get("etapas", [])) if e.get("resultado")]
            mem = "\n\n".join(u_partes)[-limite:]
    return mem


def _falhou(r):
    return (not r) or bool(re.match(r"\W*(n[ãa]o consegui|falhou|erro|n[ãa]o achei|n[ãa]o encontrei|nenhum (dado|resultado|fato|informa)|"
                                     r"n[ãa]o h[áa] (dados|informa)|as fontes (fornecidas )?n[ãa]o)", str(r), re.I)
                          or bool(re.search(r"n[ãa]o (?:é possível|consigo|consegui) (?:identificar|ver)|n[ãa]o est[áa] vis[íi]vel na c[âa]mera.*n[ãa]o est[áa] vis[íi]vel|"
                                            r"n[ãa]o consegui ver nada", str(r)[:400], re.I)))


_PROMESSA = re.compile(r"\b(vou (?:seguir|tentar|fazer|abrir|continuar)|em breve|pronto para (?:acessar|come[çc]ar)|aguarde)\b", re.I)


def _verificar(e, r, ag=None, ops=None):
    """F6: verificação POSITIVA por tipo de etapa -> (ok, evidência). Antes só se procurava frase negativa (_falhou),
    e o plano saía 'concluido' com "vou seguir com o login... em breve" ou sem o documento pedido."""
    if _falhou(r):
        return False, "resultado negativo: " + str(r)[:80]
    tipo, txt = e.get("tipo"), str(r or "")
    if tipo == "documento":                          # arquivo existe e tem conteúdo
        m = re.search(r"(/[^\n:]+?\.(?:docx|xlsx|pptx|md))\b", txt)
        if ag is not None and hasattr(ag, "v_arquivo"):
            return ag.v_arquivo(m.group(1) if m else "")
        return (bool(m and os.path.exists(m.group(1))), "arquivo " + (m.group(1) if m else "não citado"))
    if tipo == "pesquisar":                          # fontes lidas > 0
        n = e.get("fontes")
        if isinstance(n, int) and n >= 2:
            return True, f"{n} fontes lidas"
        if isinstance(n, int):
            return False, f"só {n} página; não fecho na primeira"
        return (len(txt) >= 80 and "fonte:" in txt.lower(), "busca direta, sem duas fontes" if len(txt) < 80 else "texto sem duas fontes")
    if tipo in ("zap", "whatsapp", "email"):         # aprovação criada (ou envio automático)
        if re.search(r"\benviad[ao]\b|^Enviado", txt, re.I):
            return True, "enviado"
        acoes = ("wa.send_chat",) if tipo != "email" else ("mail.send",)
        try:
            it = [i for i in ops.approvals() if i.get("acao") in acoes and float(i.get("criado", 0)) >= e.get("inicio", 0) - 1]
        except Exception:
            it = None
        if it:
            return True, f"aprovação {it[-1]['id']} criada"
        if it is None or tipo == "email":            # sem acesso às aprovações / e-mail aberto no compositor: fica o resultado
            return True, "sem aprovação para conferir"
        return False, "nenhuma aprovação foi criada"
    if tipo == "pc":                                 # o agente confirmou com evidência e não só prometeu
        if e.get("verificado") is False:
            return False, "o agente não confirmou o resultado"
        if _PROMESSA.search(txt):
            return False, "prometeu em vez de fazer: " + txt[:60]
        return True, "; ".join(e.get("evidencias") or []) or "sem verificação negativa"
    if tipo in ("resumir", "ia"):
        return (len(txt) >= 40, f"{len(txt)} caracteres")
    return True, ""


def _ddg(q, n=4):
    """busca no DuckDuckGo HTML (sem chave): devolve as URLs dos resultados orgânicos."""
    import html as _h, urllib.parse as up, urllib.request as ur
    req = ur.Request("https://html.duckduckgo.com/html/?kl=br-pt&q=" + up.quote(q), headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"})
    pg = ur.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
    out = []
    _TIT.clear()
    for h, tit in re.findall(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', pg, re.S):
        u = up.parse_qs(up.urlparse(_h.unescape(h)).query).get("uddg", [None])[0]
        if u and u not in out and not re.search(r"youtube|facebook|instagram|tiktok|duckduckgo\.com/y\.js", u):
            out.append(u)
            _TIT[u] = re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", "", tit))).strip()
    return out[:n]


_TIT = {}          # url -> título do resultado (é o que o cursor procura na tela: fonte grande, o OCR lê bem)


def _chromium_em_foco(ag, fr):
    """garante o Chromium em foco ANTES de digitar/rolar/atalho. Sem isso a URL já foi parar no terminal do dono."""
    for _ in range(3):
        if "chromium" in ag._foco().lower():
            return True
        w = fr.find_window("chromium")
        if not w:
            return False
        fr._niri("focus-window", "--id", str(w["id"]))
        time.sleep(0.6)
    return "chromium" in ag._foco().lower()


def _ver_no_navegador(q, urls, ag, fr, ops=None, progress=None):
    """pesquisa VISÍVEL: abre a busca no Chromium, leva o cursor até o MELHOR resultado, clica e
    rola a página suavemente para leitura visual. Rápido e responsivo."""
    import difflib, urllib.parse as up
    if not urls:
        return
    direto = not re.search(r"google\.|duckduckgo|bing\.", urls[0])
    if not direto:
        try:
            ag.t_abrir_site(url="https://duckduckgo.com/?kl=br-pt&q=" + up.quote(q), fr=fr, ops=ops)
            time.sleep(1.2)
        except Exception:
            return
    m = ag._manual()
    for u in urls[:2]:
        dom = up.urlparse(u).netloc.replace("www.", "")
        if progress:
            progress(f"Abrindo {dom.split('.')[0]}.")
        alvo = (_TIT.get(u) or dom)[:35]
        clicou = False
        for tentativa in range(2):
            try:
                linhas = [x for x in m.screen_lines() if x["y"] > 230 and x["x"] < 1300
                          and difflib.SequenceMatcher(None, x["t"].lower(), q.lower()).ratio() < 0.85]
                l, sc = m._find(alvo, linhas)
            except Exception:
                l, sc = None, 0
            if l and sc >= 0.55 and _chromium_em_foco(ag, fr):
                m._pc("clickat", l["x"], l["y"])
                time.sleep(1.2)
                clicou = True
                break
            if tentativa == 0 and _chromium_em_foco(ag, fr):
                m._pc("move", 960, 520)
                ag.t_rolar(n=4)
                time.sleep(0.5)
        if not clicou:
            try:
                ag.t_abrir_site(url=u, fr=fr, ops=ops)
            except Exception:
                if _chromium_em_foco(ag, fr):
                    fr._pc("goto", u, timeout=15)
            time.sleep(1.5)
        else:
            time.sleep(1.2)
        _ler_ate_o_fim(ag, fr, m, max_rolagens=3)


def _ler_ate_o_fim(ag, fr, m, max_rolagens=5):
    """rola a página de forma visível e natural como quem lê (rápido e suave, sem travar)."""
    if not _chromium_em_foco(ag, fr):
        return
    m._pc("move", 960, 520)
    for _ in range(max_rolagens):
        if ag.CANCEL.is_set() or not _chromium_em_foco(ag, fr):
            return
        ag.t_rolar(n=3)
        time.sleep(0.4)


def _etapa(e, p, fr, ag, ops, ctx, programar, progress, visivel=True, ver=None):
    mem = _memoria(p)
    tipo, obj = e["tipo"], e["objetivo"]
    if tipo == "ver":                                # tela + câmeras (nativa/mãos + externa/ambiente)
        try:
            import visao
            if re.search(r"\b(tela|janela|monitor|app|c[óo]digo|janelas|aberto)\b", obj, re.I):
                return visao.olhar_tela(obj)
            if re.search(r"\b(m[ãa]o|m[ãa]os|segur|teclado|mesa|nativa|frontal)\b", obj, re.I):
                return visao.olhar_camera_nativa(obj)
            if re.search(r"\b(sala|quarto|ambiente|externa|ao redor)\b", obj, re.I):
                return visao.olhar_camera_externa(obj)
            if ver is not None:
                r_v = ver(obj)
                if r_v and not _falhou(r_v):
                    return r_v
            return visao.olhar_tudo(obj)
        except Exception as e_v:
            if ver is not None:
                return ver(obj)
            return f"Não consegui acessar os sensores de visão: {str(e_v)[:80]}"
    if tipo == "ia":                                 # pergunta de verdade à IA do dono no navegador (ela vê o ChatGPT digitando/respondendo)
        obj_ia = re.sub(r"^(?:buscar|pesquisar|perguntar|pergunte|pesquise)\s+(?:a[oa]|no|na|para o)?\s*(?:(?:chat\s*gpt|gemini|perplexity|claude)\s*:?\s*)?"
                        r"(?:informa[çc][õo]es\s+)?(?:sobre\s+)?", "", obj, flags=re.I).strip(" '\"")
        obj_ia = re.sub(r",?\s*usando (?:o )?(?:chat\s*gpt|gemini|perplexity|claude)\b.*$", "", obj_ia, flags=re.I)
        return ag.t_consultar_ia(pergunta=obj_ia + (f"\n\nContexto: {mem[-800:]}" if mem else ""), site=e.get("site", "chatgpt"), fr=fr, ops=ops)
    if tipo == "pesquisar":                          # várias fontes: busca, lê as 3 melhores e consolida os FATOS (com fonte)
        try:
            q = _consulta_limpa(obj)
            if len(q) < 3:
                q = re.sub(r"[\"'\n]+", " ", obj).strip()[:90]
            urls = []
            if re.search(r"fortn", q, re.I) and re.search(r"loja|item|skin", q, re.I):
                urls = ["https://www.fortnite.com/item-shop?lang=pt-BR", "https://fortnite.gg/shop"]
            try:
                if not urls:
                    urls = _ddg(q, 5)
            except Exception:
                urls = []
            try:
                lista = ag.t_pesquisar_web(consulta=q)
                extras = [u.rstrip(").,") for u in re.findall(r"https?://\S+", lista) if not re.search(r"youtube|facebook|instagram|tiktok|duckduckgo\.com", u)]
                for u in extras:
                    if u not in urls:
                        urls.append(u)
            except Exception:
                pass
            is_dinamico = bool(re.search(r"\b(loja|item|itens|skin|skins|pre[çc]o|oferta|promo[çc]|cota[çc]|hoje|atual)\b", obj, re.I))
            if is_dinamico:
                # Remove sites de enciclopédia/história geral que não refletem a loja diária
                urls = [u for u in urls if not re.search(r"wikipedia\.org|fandom\.com|wikia\.com", u, re.I)]
                if re.search(r"fort[i]?n[ai]?te", obj, re.I):
                    if re.search(r"oficial", obj, re.I):
                        urls.sort(key=lambda u: 0 if re.search(r"fortnite\.com|epicgames\.com", u, re.I) else (1 if re.search(r"fortnite\.gg", u, re.I) else 2))
                    else:
                        urls.sort(key=lambda u: 0 if re.search(r"fortnite\.gg", u, re.I) else (1 if re.search(r"fortnite\.com|epicgames\.com", u, re.I) else 2))
            if urls and visivel:
                _ver_no_navegador(q, urls[:3], ag, fr, ops=ops, progress=progress)       # o dono VÊ: busca no Chromium, cursor clica em cada fonte
            textos = []
            for u in urls:
                try:
                    txt = ag.t_ler_pagina(url=u).strip()
                    if len(txt) > 150:
                        textos.append(f"FONTE {u}\n" + txt[:4000])
                        if len(textos) >= 3:
                            break
                except Exception:
                    pass
            if len(textos) < 2:
                try:
                    tela = ag.t_ver_tela()
                    if tela and len(tela) > 80:
                        textos.append("FONTE tela\n" + tela[:4000])
                except Exception:
                    pass
            e["fontes"] = len(textos)
            fatos = _fatos_das_paginas(textos, q)
            if len(textos) < 2 or len(fatos) < 40:
                return "falhou: li " + str(len(textos)) + " página(s) e o texto não cobre o assunto. Não fecho na primeira nem invento."
            if is_dinamico:
                p_sys = ("Extraia só o que está nos textos: itens, preços e o que está à venda. "
                         "Sem introdução, sem história do jogo, sem frase genérica. Se o texto não tiver o dado, não invente.")
            else:
                p_sys = ("Responda em português, 3 a 5 frases, só com fatos que estão nos textos e que respondem o objetivo. "
                         "Cite o dado concreto (nome, número, data). Proibido: 'com base na pesquisa', 'em resumo', 'é importante destacar'. "
                         "Se o texto não tiver a resposta, diga o que a página realmente diz.")
            r = fr.llm(p_sys, f"Objetivo: {obj}\nConsulta: {q}\n\n" + "\n\n".join(textos), None, False, 500, 0.1, 90)
            chaves = [w for w in re.findall(r"\w{4,}", fatos.lower())][:8]
            ancora = sum(1 for w in chaves if w in (r or "").lower())
            if not r or _falhou(r) or ancora < 2 or re.search(r"com base na pesquisa|em resumo|vale destacar|é importante", r, re.I):
                return fatos
            return r.strip()
        except Exception:
            pass
        e["fontes"] = "direta"
        r = ag._pesquisa_direta("pesquise " + obj, fr, ops, None)
        if _falhou(r):
            r = ag.run("pesquise e leia sobre: " + obj, ctx, fr, ops, None, None, direto=False).get("fala", "")
        return r
    if tipo == "documento":
        fmt = (e.get("formato") or "docx").lower().strip(".") if (e.get("formato") or "docx").lower().strip(".") in ("docx", "xlsx", "pptx") else "docx"
        if not mem.strip():
            # Não cria arquivo vazio se não houver dados apurados
            return "falhou: nenhuma informação foi apurada para preencher o documento."
        try:
            import documento
            destino = getattr(ag, "DOCS", os.path.expanduser("~/Documentos/Friday"))
            res = documento.criar(p["pedido"], mem, formato=fmt, destino=destino, fr=fr, abrir=True)
            if res and res.get("caminho") and os.path.exists(res.get("caminho")):
                cam = res["caminho"]
                conf = res.get("conferir") or []
                aviso_conf = f" ({len(conf)} itens para conferir)" if conf else ""
                return f"arquivo criado: criado e aberto no ONLYOFFICE: {cam}{aviso_conf}"
        except Exception:
            pass
        d = fr.llm(SYS_DOC.format(formato=fmt), f"Pedido: {p['pedido']}\nObjetivo deste arquivo: {obj}\n\nInformações apuradas:\n{mem}",
                   None, True, 1600, 0.3, 180)
        conteudo = str((d or {}).get("conteudo", "")).strip() if isinstance(d, dict) else ""
        # Verifica se o conteúdo gerado não é vazio ou apenas um cabeçalho/sustenido sem texto
        linhas_uteis = [l.strip() for l in conteudo.splitlines() if l.strip() and not re.fullmatch(r"#+", l.strip())]
        if not linhas_uteis:
            # Fallback seguro: usa as informações apuradas estruturadas
            conteudo = f"# {p.get('titulo') or 'Relatório'}\n\n" + mem
            linhas_uteis = [l.strip() for l in conteudo.splitlines() if l.strip()]
        if not linhas_uteis:
            return "falhou: não consegui escrever o conteúdo do documento."
        nome = re.sub(r"[\s_-]*\d{6,8}[\s_-]*", " ", str((d or {}).get("nome") or p["titulo"])).strip()
        nome = re.sub(r"[^\w\- ]", "", nome).strip() or "relatorio"
        return "arquivo criado: " + ag.t_onlyoffice_criar(tipo=fmt, nome=nome, conteudo=conteudo)
    if tipo in ("zap", "whatsapp"):
        contato = _limpa_contato(e.get("contato") or "")
        if not contato:
            m = re.search(r"(?:para|ao|pro)\s+([A-ZÀ-Úa-zà-ú0-9_ ,-]+?)(?::|\s+com\b|\s+dizendo|\s+sobre|\s+as\s+informa|\s+(?:no|pelo|via)\s+(?:zap|whatsapp)|$)", obj, re.I)
            if m:
                contato = _limpa_contato(m.group(1).strip())
            if not contato or contato.lower() in ("amigo", "um amigo", "meu amigo", "alguém", "alguem", "um contato", "contato"):
                m_ped = re.search(r"(?:para|a(?:o)?|pro)\s+([A-ZÀ-Úa-zà-ú0-9_ ,-]+?)\s+(?:no|pelo|via|pelo\s+aplicativo)\s+(?:zap|whatsapp)", p.get("pedido", ""), re.I)
                if m_ped:
                    contato = _limpa_contato(m_ped.group(1).strip())
        contato = _limpa_contato(contato)

        # Se contato for genérico como "amigo", "um amigo", "alguém", tenta achar contato recente no zap
        if not contato or contato.lower() in ("amigo", "um amigo", "meu amigo", "alguém", "alguem", "um contato", "contato"):
            try:
                import zap
                s = zap.snapshot()
                if s.get("ok") and s.get("chats"):
                    achado = None
                    for c in s["chats"]:
                        if c["nome"].lower() in p.get("pedido", "").lower() or c["nome"].lower() in obj.lower():
                            achado = c["nome"]
                            break
                    if achado:
                        contato = achado
            except Exception:
                pass
        if not contato or re.fullmatch(r"[0-9+\s()-]{6,}", contato or ""):
            return "Para quem eu escrevo? Me diz o nome do contato. Não uso um número que você não falou."

        txt_msg = e.get("mensagem") or ""
        if not txt_msg:
            txt_msg = fr.llm("Você é a F.R.I.D.A.Y. Com base nas informações apuradas, elabore uma mensagem em pt-BR clara, concisa e direta para enviar pelo WhatsApp ao contato. Sem cabeçalhos ou markdown exagerado.",
                             f"Objetivo: {obj}\n\nInformações apuradas:\n{mem}", None, False, 250, 0.3, 60)
        txt_msg = (txt_msg or mem or obj).strip()
        if re.search(r"vou pesquisar|exibindo resultados|sites como|youtube", txt_msg, re.I):
            txt_msg = (mem or "").strip()
        if not txt_msg or re.search(r"vou pesquisar|exibindo resultados", txt_msg, re.I):
            return "falhou: a pesquisa não entrou na página. Não montei mensagem genérica."

        ok, msg = fr.run_action({"t": "zap", "op": "enviar", "contato": contato, "texto": txt_msg}, ops)
        if not ok and _falhou(msg):
            return f"falhou: {msg}"
        return msg or f"Mensagem para {contato} preparada no WhatsApp."
    if tipo == "email":
        dest = e.get("para") or ""
        if not dest:
            m = re.search(r"(?:para|ao|pro)\s+([A-Za-z0-9@._ -]+?)(?::|\s+com\b|\s+dizendo|\s+sobre|$)", obj, re.I)
            if m:
                dest = m.group(1).strip()
            else:
                m_ped = re.search(r"(?:para|a(?:o)?|pro)\s+([A-Za-z0-9@._ -]+?)\s+(?:por|via|no)?\s*e-?mail", p.get("pedido", ""), re.I)
                if m_ped:
                    dest = m_ped.group(1).strip()
        dest = dest.strip(" ,.:-") or "destinatário"
        assunto = e.get("assunto") or p.get("titulo") or "Informações"
        corpo = e.get("corpo") or ""
        if not corpo:
            corpo = fr.llm("Elabore um e-mail formal e claro em pt-BR com base nas informações apuradas.",
                           f"Objetivo: {obj}\n\nInformações:\n{mem}", None, False, 300, 0.3, 60)
        corpo = (corpo or mem or obj).strip()
        ok, msg = fr.run_action({"t": "email", "op": "compor", "para": dest, "assunto": assunto, "corpo": corpo}, ops)
        if not ok and _falhou(msg):
            return f"falhou: {msg}"
        return msg or f"E-mail para {dest} preparado."
    if tipo == "programar":
        if programar is None:
            return "Não consegui acionar o programador."
        programar(obj + (f"\n\nContexto já apurado (use se ajudar):\n{mem[-2500:]}" if mem else ""))
        return "programação enviada ao Claude CLI (acompanha no holograma; ele avisa ao terminar)"
    if tipo == "resumir":
        r = fr.llm("Resuma em pt-BR, falado, 3-5 frases, só o que está nas informações.", f"Pedido: {p['pedido']}\n\n{mem}", None, False, 350, 0.3, 90)
        return r or "Não consegui resumir."
    res_ag = ag.run(obj + (f"\n(Informações das etapas anteriores: {mem[-1200:]})" if mem else ""), ctx, fr, ops, None, progress)
    e["verificado"], e["evidencias"] = res_ag.get("verificado"), res_ag.get("evidencias") or []    # F6: _verificar usa
    return res_ag.get("fala") or ""                  # sem fala não é "Concluído com sucesso"


def frase_final(p, falar=None):
    """frase final montada SÓ pelas etapas que terminaram ok (pulada, falha ou não feita nunca vira "pronto").
    falar(pedido, apurado, max_tokens) -> fala natural (LLM) ou None."""
    ets = p.get("etapas") or []
    n = len(ets)
    feitas = [e for e in ets if e.get("estado") == "ok"]
    puladas = [e for e in ets if e.get("estado") == "pulado"]
    falhas = [e for e in ets if e.get("estado") == "falhou"]
    faltam = [e for e in ets if e.get("estado") not in ("ok", "pulado", "falhou")]
    res = lambda e: str(e.get("resultado") or "")
    nat = lambda e, mx: ((falar(p.get("pedido", ""), res(e)[:2000], mx) if falar else None) or "").strip()
    arqs = re.findall(r"(/[^\n:]+?\.(?:docx|xlsx|pptx|md))\b", " ".join(res(e) for e in feitas))     # só arquivo de etapa que deu certo
    arq = f"O arquivo é {os.path.basename(arqs[-1])}, já aberto no ONLYOFFICE." if arqs else ""
    if not n:
        return "Não consegui montar as etapas dessa tarefa."
    if not feitas and not falhas and not faltam:
        return "Pulei " + ("a etapa" if n == 1 else f"as {n} etapas") + " a pedido, então não fiz nada."
    if n == 1:
        e = ets[0]
        if e.get("estado") == "ok":
            if e.get("tipo") == "pesquisar":
                return res(e)[:500]
            return (nat(e, 200) if e.get("tipo") == "ia" else "") or res(e)[:500]
        if falhas and res(e) and not re.match(r"\W*(falhou|erro)\b", res(e), re.I):
            return res(e)[:500]                          # "não consegui achar..." já é frase dela (sem erro cru)
        return f"Não consegui: {str(e.get('objetivo', 'a tarefa'))[:60]}."
    if len(feitas) == n:
        ult = ets[-1]
        final = f"Pronto, terminei: {p.get('titulo', 'a tarefa')}." + (" " + arq if arq else "")
        if not arqs:
            if ult.get("tipo") == "resumir":
                final += " " + res(ult)[:350]
            elif ult.get("tipo") in ("zap", "whatsapp"):
                final = f"Pronto, chefe. Pesquisei as informações e preparei a mensagem no WhatsApp. {res(ult)}"
            elif ult.get("tipo") == "email":
                final = f"Pronto, chefe. Preparei o e-mail. {res(ult)}"
            elif ult.get("tipo") == "pesquisar":
                final = res(ult)[:500] or final
        return final.strip()
    obj = lambda l: "; ".join(str(e.get("objetivo", ""))[:50] for e in l)
    partes = [f"Fiz {len(feitas)} de {n} etapas."]
    if arq:
        partes.append(arq)
    if puladas:
        partes.append(f"Pulei: {obj(puladas)}.")
    if falhas:
        partes.append(f"Não consegui: {obj(falhas)}.")
    if faltam:
        partes.append(f"Ficaram sem fazer: {obj(faltam)}.")
    if falhas or faltam:
        partes.append("Diga 'retome a tarefa' para eu tentar de novo.")
    return " ".join(partes)


def executar(pedido, fr, ag, ops, ctx="", programar=None, progress=None, aviso=None, plano=None, ver=None):
    """roda o plano inteiro (bloqueante: chamar em thread). progress(texto) = fala curta; aviso(dict) = painel/holograma."""
    p = plano or planejar(pedido, fr, ctx)
    _salvar(p)
    n = len(p["etapas"])
    say = (lambda t: progress(t)) if progress else (lambda t: None)
    if n > 1 and not plano:
        say(f"Certo. Dividi em {n} etapas: " + "; ".join(e["objetivo"][:40] for e in p["etapas"][:4]) + ".")
    SKIP.clear()
    for i, e in enumerate(p["etapas"]):
        if e["estado"] == "ok":
            continue
        if ag.CANCEL.is_set():
            p["estado"] = "cancelado"; _salvar(p)
            if aviso:                                   # interface/app fecham o progresso (senão fica "executando")
                aviso({"titulo": p["titulo"], "etapa": i + 1, "total": n, "objetivo": "cancelado",
                       "etapas": [(x["objetivo"][:50], x["estado"]) for x in p["etapas"]], "fim": True})
            return p
        if SKIP.is_set():
            SKIP.clear()
            e["estado"] = "pulado"
            e["resultado"] = "etapa pulada a pedido do usuário"
            _salvar(p)
            if aviso:
                aviso({"titulo": p["titulo"], "etapa": i + 1, "total": n, "objetivo": "pulado", "etapas": [(x["objetivo"][:50], x["estado"]) for x in p["etapas"]]})
            say(f"Etapa {i + 1} pulada.")
            continue
        if aviso:
            aviso({"titulo": p["titulo"], "etapa": i + 1, "total": n, "objetivo": e["objetivo"], "etapas": [(x["objetivo"][:50], x["estado"]) for x in p["etapas"]]})
        if n > 1:
            say(f"Etapa {i + 1} de {n}: {e['objetivo'][:70]}.")
        e["estado"] = "executando"; _salvar(p)
        r, ok_v, ev = "", False, ""
        for tentativa in range(2):                       # confere o resultado (verificação POSITIVA); se falhou, tenta de novo com outra abordagem
            if SKIP.is_set() or ag.CANCEL.is_set():
                break
            e["inicio"] = time.time()
            try:
                r = _etapa(e, p, fr, ag, ops, ctx, programar, progress if n == 1 else None, ver=ver)
            except Exception as ex:
                r = f"falhou: {str(ex)[:120]}"
            try:
                ok_v, ev = _verificar(e, r, ag, ops)
            except Exception as ex:
                ok_v, ev = not _falhou(r), f"verificação falhou: {str(ex)[:60]}"
            if ok_v or ag.CANCEL.is_set() or SKIP.is_set():
                break
            e["objetivo"] += " (tente outra abordagem; a anterior falhou: " + str(ev or r)[:80] + ")"
        if SKIP.is_set():
            SKIP.clear()
            e["estado"] = "pulado"
            e["resultado"] = "etapa pulada a pedido do usuário"
            _salvar(p)
            say(f"Pulei a etapa {i + 1}, chefe.")
            continue
        e["resultado"] = str(r)[:2500]
        e["estado"] = "ok" if ok_v else "falhou"
        e["evidencia"] = str(ev)[:200]
        _salvar(p)
        if e["estado"] == "falhou" and i < n - 1:          # as próximas dependem desta: para e avisa (nada de documento sobre "nada")
            break
    ok = [e for e in p["etapas"] if e["estado"] in ("ok", "pulado")]
    p["estado"] = "concluido" if len(ok) == n else "parcial"
    _nat = lambda ped, ap, mx: fr.llm(f"Responda falado, em pt-BR, 2 a {4 if mx >= 200 else 3} frases naturais, só com o essencial para o pedido. Sem listas, links ou fontes.",
                                      f"Pedido: {ped}\n\nApurado:\n{ap}", None, False, mx, 0.3, 60)
    if n > 1 and p["estado"] != "concluido" and any(e["tipo"] == "ver" and e["estado"] == "falhou" for e in p["etapas"]):
        p["final"] = "Não consegui ver o objeto pelas câmeras. Mostre ele mais perto da câmera e me peça de novo."
        _salvar(p)
        if aviso:
            aviso({"titulo": p["titulo"], "etapa": n, "total": n, "objetivo": "parado", "etapas": [(x["objetivo"][:50], x["estado"]) for x in p["etapas"]], "fim": True})
        return p
    p["final"] = frase_final(p, _nat)
    _salvar(p)
    if aviso:
        aviso({"titulo": p["titulo"], "etapa": n, "total": n, "objetivo": "concluído" if p["estado"] == "concluido" else "parcial",
               "etapas": [(x["objetivo"][:50], x["estado"]) for x in p["etapas"]], "fim": True})
    return p
