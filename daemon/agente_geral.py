#!/usr/bin/env python3
"""Agente GERAL da F.R.I.D.A.Y.: qualquer pedido (simples ou composto) num laço só
    observar -> decidir (modelo) -> agir (cursor/teclado/toque REAIS) -> conferir -> ... -> concluir.

O modelo nunca chuta pixel: ele vê uma OBSERVAÇÃO estruturada e escolhe pelo número —
  navegador da Friday: lista de botões/campos da página (CDP) -> web_clicar{id}
  celular: árvore de acessibilidade pela ponte -> cel_tocar{id}
  programas do PC: janelas do niri + visão (localizar por descrição) -> pc_clicar{descricao}
Quem executa é o código, com o cursor/teclado/toque de verdade, e o resultado volta como observação.
Modelo: local (Ollama) por padrão; troca por voz/config para nuvem (Claude/Gemini/OpenAI) — memory/agente.json.

  agente_geral.py "pedido"            resolve e mostra cada passo
  agente_geral.py --modelo X "pedido"  usa outro modelo do Ollama só nesta execução
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MEM = os.path.join(ROOT, "memory")
CFG = os.path.join(MEM, "agente.json")
LOG = os.path.join(MEM, "agente_log.jsonl")
OLLAMA = os.environ.get("FRIDAY_OLLAMA", "http://127.0.0.1:11434")
PC = os.path.join(HERE, "pc")
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PADRAO = {"provedor": "ollama", "modelo": os.environ.get("FRIDAY_MODEL", "qwen3.5:4b"), "max_passos": 30, "limite_s": 900}


def config():
    c = dict(PADRAO)
    try:
        c.update(json.load(open(CFG)))
    except Exception:
        pass
    return c


def salvar_config(**kw):
    c = config()
    c.update({k: v for k, v in kw.items() if v is not None})
    os.makedirs(MEM, exist_ok=True)
    json.dump(c, open(CFG, "w"), ensure_ascii=False, indent=1)
    return c


# ------------------------------------------------------------------ modelo (local ou nuvem)
def _json_de(txt):
    txt = re.sub(r"(?s)<think>.*?</think>", "", txt or "").strip()
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"(?s)\{.*\}", txt)
        if m:
            return json.loads(m.group(0))
    raise ValueError("modelo não devolveu JSON: " + txt[:200])


def _ollama(msgs, schema, modelo, max_tokens=350):
    corpo = {"model": modelo, "messages": msgs, "stream": False, "format": schema, "think": False, "keep_alive": -1,
             "options": {"temperature": 0.15, "num_predict": max_tokens, "num_ctx": int(os.environ.get("FRIDAY_NUM_CTX", "16384")), "num_gpu": 99}}
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read())
    if resp.get("done_reason") == "length" and max_tokens < 4000:    # JSON cortado no meio: tenta de novo com mais folga
        return _ollama(msgs, schema, modelo, max_tokens * 2)
    try:
        return _json_de(resp["message"]["content"])
    except ValueError:    # JSON truncado/inválido sem done_reason=length: tenta de novo com mais folga
        if max_tokens >= 4000:
            raise
        return _ollama(msgs, schema, modelo, max_tokens * 2)


def _claude_cli(msgs, schema, modelo="sonnet"):
    texto = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in msgs)
    texto += "\n\nResponda SOMENTE com um objeto JSON válido neste esquema, sem texto antes ou depois:\n" + json.dumps(schema, ensure_ascii=False)
    r = subprocess.run(["claude", "-p", "--model", modelo, texto], capture_output=True, text=True, timeout=240)
    return _json_de(r.stdout)


def _nuvem_api(msgs, schema, prov):
    import cloud_providers
    m = list(msgs)
    m[-1] = dict(m[-1], content=m[-1]["content"] + "\n\nResponda SOMENTE com JSON no esquema: " + json.dumps(schema, ensure_ascii=False))
    r = cloud_providers.chat_com_ferramentas(m, [], temperature=0.15, max_tokens=1600, provider=prov)
    return _json_de((r.get("message") or {}).get("content") or "")


def pensar(msgs, schema, cfg=None, max_tokens=350):
    cfg = cfg or config()
    prov = (cfg.get("provedor") or "ollama").lower()
    try:
        if prov in ("claude-cli", "claude_cli", "claudecode"):
            return _claude_cli(msgs, schema, cfg.get("modelo_nuvem") or "sonnet")
        if prov in ("claude", "gemini", "openai"):
            return _nuvem_api(msgs, schema, prov)
    except Exception as e:
        print("nuvem falhou, voltando ao local:", str(e)[:160], flush=True)
    modelo = cfg.get("modelo") or PADRAO["modelo"]
    return _ollama(msgs, schema, modelo, max_tokens)


# ------------------------------------------------------------------ ações reais
def _pc(*a, t=30):
    r = subprocess.run([sys.executable, PC, *map(str, a)], capture_output=True, text=True, timeout=t)
    return (r.stdout or r.stderr).strip()


class Estado:
    """o que o agente sabe entre passos: últimos elementos vistos (navegador/celular) e o que já foi feito."""
    def __init__(self, fr=None, ops=None, aviso=None):
        self.fr, self.ops, self.aviso = fr, ops, aviso
        self.cel = []                       # itens da última leitura do celular (id = índice + 1)
        self.arquivos = []


def _resumo_pagina(n=60):
    import navegador
    e = navegador.elementos()
    linhas = [f"PÁGINA: {e.get('titulo', '')[:90]} | {e.get('url', '')[:120]}"]
    els = e.get("elementos", [])
    campos = [x for x in els if x["tag"] in ("input", "textarea", "select") or x["tipo"] in ("searchbox", "textbox")]
    links = [x for x in els if x["tag"] == "a" and len(x["texto"]) >= 20 and x not in campos]
    resto = [x for x in els if x not in campos and x not in links and x["texto"]]
    for nome, grupo, lim in (("CAMPOS", campos, 8), ("LINKS/RESULTADOS", links, 25), ("BOTÕES/OUTROS", resto, 25)):
        if grupo:
            linhas.append(nome + ":")
            linhas += [f"[{x['id']}] {x['texto'][:70]}" + (f" ({x['tipo']})" if x in campos and x['tipo'] else "") for x in grupo[:lim]]
    try:
        txt = re.sub(r"\s+", " ", navegador.ler().get("texto", ""))[:700]
        linhas.append("TEXTO (início): " + txt)
    except Exception:
        pass
    return "\n".join(linhas)


def _web_abrir(st, url_ou_busca="", **_):
    import navegador
    r = navegador.abrir(url_ou_busca)
    if not r.get("ok"):
        return "falhou: " + str(r.get("erro"))
    ads = r.get("anuncios_fechados") or []
    return (f"abri {r.get('url')}" + (f" (fechei {len(ads)} pop-up/anúncio)" if ads else "")) + "\n" + _resumo_pagina()


def _web_clicar(st, id=0, **_):
    import navegador
    r = navegador.clicar(f"#{int(id)}")
    if not r.get("ok"):
        return "falhou: " + str(r.get("erro")) + " — use SÓ ids desta lista atual, ou web_ler.\n" + _resumo_pagina()
    return f"cliquei em '{r.get('clicou', '')[:60]}'" + ("" if r.get("mudou") else " (a página não mudou)") + "\n" + _resumo_pagina()


def _web_digitar(st, id=0, texto="", enter=False, **_):
    import navegador
    r = navegador.digitar(str(texto), alvo=f"#{int(id)}" if id else None, enter=bool(enter))
    if not r.get("ok"):
        return "falhou: " + str(r.get("erro"))
    time.sleep(1.2 if enter else 0.3)
    return f"digitei '{str(texto)[:60]}'" + (" + Enter" if enter else "") + "\n" + _resumo_pagina()


def _web_ler(st, **_):
    import navegador
    d = navegador.ler()
    return f"TEXTO DE {d.get('url', '')[:100]}:\n" + (d.get("texto") or "")[:3500]


def _web_rolar(st, direcao="baixo", **_):
    import navegador
    navegador._focar_janela()
    _pc("scroll", 6 if direcao != "cima" else -6)
    time.sleep(0.6)
    return "rolei para " + direcao + "\n" + _resumo_pagina()


def _web_voltar(st, **_):
    import navegador
    navegador._focar_janela()
    _pc("key", "alt+left")
    time.sleep(1.2)
    return "voltei\n" + _resumo_pagina()


def _pc_abrir(st, app="", **_):
    import orquestra_geral as og
    ok, msg, via = og._garantir_janela(app)
    return ("abri " if ok else "não consegui abrir ") + str(app) + f" ({msg})"


def _pc_ver(st, pergunta="O que está aberto e visível nesta tela?", **_):
    import visao
    return "TELA: " + str(visao.olhar_tela(pergunta))[:1500]


def _pc_clicar(st, descricao="", **_):
    import visao
    p = visao.localizar(descricao)
    if not p:
        return f"não achei na tela: {descricao}"
    _pc("clickat", p["x"], p["y"])
    return f"cliquei em '{descricao}' ({p['x']},{p['y']})"


def _pc_digitar(st, texto="", **_):
    return "digitei" if "erro" not in _pc("type", texto).lower() else "falhou ao digitar"


def _pc_tecla(st, teclas="enter", **_):
    _pc("key", teclas)
    return "apertei " + teclas


def _terminal(st, comando="", **_):
    import orquestra_geral as og
    r = og._shell_fallback(comando)
    return ("ok: " if r.get("ok") else "falhou: ") + str(r.get("evidencia"))[:1500]


def _caminho(c):
    p = os.path.abspath(os.path.expanduser(str(c)))
    if not p.startswith(os.path.expanduser("~")) or "/Secrets" in p or "/." in p.replace(os.path.expanduser("~"), ""):
        raise RuntimeError("caminho fora da pasta do usuário ou protegido")
    return p


def _livre(p):
    """Se um ancestral de p é arquivo comum (bloqueia mkdir), desvia para '<nome>_pasta' sem apagar nada."""
    partes = p.split(os.sep)
    for i in range(2, len(partes) + 1):
        a = os.sep.join(partes[:i])
        if os.path.exists(a) and not os.path.isdir(a):
            partes[i - 1] += "_pasta"
            return _livre(os.sep.join(partes))
    return p


def _arquivo_escrever(st, caminho="", conteudo="", **_):
    p = _livre(_caminho(caminho))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(str(conteudo))
    st.arquivos.append(p)
    return f"arquivo salvo: {p} ({len(str(conteudo))} caracteres)"


def _arquivo_ler(st, caminho="", **_):
    p = _caminho(caminho)
    if os.path.isdir(p):
        return "PASTA " + p + ": " + ", ".join(sorted(os.listdir(p))[:80])
    return "CONTEÚDO de " + p + ":\n" + open(p, encoding="utf-8", errors="ignore").read()[:3000]


def _criar_pasta(st, caminho="", **_):
    p = _livre(_caminho(caminho))
    os.makedirs(p, exist_ok=True)
    return "pasta pronta: " + p


def _cel(rota, **q):
    import celular
    return celular.ponte(rota, timeout=20, **q)


def _cel_ver(st, **_):
    d = _cel("/arvore")
    st.cel = d.get("itens") or []
    linhas = [f"[{i + 1}] {'campo' if it.get('campo') else 'botão' if it.get('clique') else 'texto'} '{str(it.get('t', ''))[:60]}'"
              for i, it in enumerate(st.cel[:80])]
    return "CELULAR:\n" + "\n".join(linhas)


def _cel_tocar(st, id=0, **_):
    if not st.cel:
        _cel_ver(st)
    i = int(id) - 1
    if i < 0 or i >= len(st.cel):
        return "id inválido: veja cel_ver"
    it = st.cel[i]
    _cel("/toque", x=it["x"], y=it["y"])
    time.sleep(1.0)
    return f"toquei em '{it.get('t', '')[:50]}'\n" + _cel_ver(st)


def _cel_digitar(st, texto="", **_):
    _cel("/texto", t=str(texto))
    st.digitado = str(texto)
    time.sleep(0.5)
    return "digitei no celular\n" + _cel_ver(st)


def _cel_abrir(st, app="", **_):
    if re.search(r"(?i)business|\b(whats\s*app|zap|wpp)\b", str(app)):
        app = "Business"          # o WhatsApp do dono no celular é o Business (com.whatsapp.w4b), não o comum
    r = _cel("/abrir", nome=str(app))
    time.sleep(1.5)
    return f"abrir {app}: {json.dumps(r, ensure_ascii=False)[:160]}\n" + _cel_ver(st)


def _cel_botao(st, botao="voltar", **_):
    _cel("/global", a={"voltar": "back", "inicio": "home", "recentes": "recents"}.get(botao, botao))
    time.sleep(0.8)
    return botao + "\n" + _cel_ver(st)


def _cam_ver(st, fonte="todas", pergunta="Descreva o que a câmera mostra: pessoas, objetos, o que acontece.", **_):
    import cerebro
    import camera_manager
    import ptz
    fonte, nota = camera_manager.resolver_fonte_camera(fonte)
    if fonte == "sem_camera":
        return nota
    if fonte == "tela":
        return _pc_ver(st, pergunta)
    txt, jpg = cerebro._olhar(fonte, pergunta)
    if not jpg:
        return "CÂMERA: " + txt
    r = ptz.get_ptz().G.vlm(jpg, pergunta)
    return "CÂMERA " + fonte + ": " + (str(r)[:1500] if r else "o modelo de visão não respondeu")


def _cam_ptz(st, op="estado", **a):
    import ptz
    ok, msg = ptz.comando(dict(a, op=op, falar=False))
    return ("CÂMERA PTZ: " if ok else "ERRO PTZ: ") + str(msg)[:800]


def _agenda(st, titulo="", quando="", **_):
    import prom_ops as ops
    i = ops.agenda_add(str(titulo), str(quando), origem="agente")
    if not i:
        return f"não entendi a data '{quando}'"
    return "marcado: " + ops.agenda_fmt(i)


def _mensagem(st, para="", texto="", **_):
    if st.fr is None or st.ops is None:
        return "mensagem indisponível fora do daemon (precisa da aprovação do dono)"
    import agent
    return str(agent.t_zap_enviar(contato=para, mensagem=texto, fr=st.fr, ops=st.ops, pronto=True))[:400]


def _perguntar_ia(st, pergunta="", ia="local", **_):
    msgs = [{"role": "user", "content": str(pergunta)}]
    esq = {"type": "object", "properties": {"resposta": {"type": "string"}}, "required": ["resposta"]}
    cfg = dict(config())
    cfg["provedor"] = {"local": "ollama"}.get(ia, ia)
    return "RESPOSTA DA IA (" + ia + "): " + str(pensar(msgs, esq, cfg, max_tokens=700).get("resposta", ""))[:2500]


FERRAMENTAS = {
    "web_abrir": (_web_abrir, '{"url_ou_busca": "site.com ou texto da busca"}', "abre site/busca no navegador da Friday (fecha pop-ups) e mostra os elementos [id]"),
    "web_clicar": (_web_clicar, '{"id": 12}', "clica no elemento [id] da última lista com o cursor real"),
    "web_digitar": (_web_digitar, '{"id": 7, "texto": "...", "enter": true}', "clica no campo [id] e digita com o teclado real"),
    "web_ler": (_web_ler, "{}", "lê o texto principal da página atual"),
    "web_rolar": (_web_rolar, '{"direcao": "baixo|cima"}', "rola a página"),
    "web_voltar": (_web_voltar, "{}", "página anterior"),
    "pc_abrir": (_pc_abrir, '{"app": "calculadora"}', "abre um programa do PC e foca a janela"),
    "pc_ver": (_pc_ver, '{"pergunta": "..."}', "olha a tela do PC (visão) e responde"),
    "pc_clicar": (_pc_clicar, '{"descricao": "botão azul Salvar"}', "acha pelo visual e clica no PC"),
    "pc_digitar": (_pc_digitar, '{"texto": "..."}', "digita no programa em foco"),
    "pc_tecla": (_pc_tecla, '{"teclas": "ctrl+s"}', "atalho de teclado"),
    "terminal": (_terminal, '{"comando": "ls ~"}', "comando seguro no terminal (só se a tela não resolver)"),
    "arquivo_escrever": (_arquivo_escrever, '{"caminho": "~/Documentos/x.txt", "conteudo": "..."}', "cria/salva arquivo de texto"),
    "arquivo_ler": (_arquivo_ler, '{"caminho": "~/Documentos/x.txt"}', "lê arquivo ou lista pasta (confere o que foi salvo)"),
    "criar_pasta": (_criar_pasta, '{"caminho": "~/Documentos/Nova"}', "cria pasta"),
    "cel_ver": (_cel_ver, "{}", "lê a tela do celular (itens [id])"),
    "cel_tocar": (_cel_tocar, '{"id": 3}', "toca no item [id] do celular"),
    "cel_digitar": (_cel_digitar, '{"texto": "..."}', "digita no campo focado do celular"),
    "cel_abrir": (_cel_abrir, '{"app": "WhatsApp"}', "abre app no celular"),
    "cel_botao": (_cel_botao, '{"botao": "voltar|inicio|recentes"}', "botões do sistema do celular"),
    "cam_ver": (_cam_ver, '{"fonte": "todas|camera_notebook|camera_porta|camera_quarto|maos", "pergunta": "..."}', "olha pelas câmeras (reconhece pessoas, objetos, mãos) e responde"),
    "cam_ptz": (_cam_ptz, '{"op": "olhar|em_volta|procurar|seguir|vigiar|parar|onde|estado", "dir": "esquerda", "alvo": "pessoa"}', "controla a câmera motorizada (procura/segue/vigia)"),
    "agenda": (_agenda, '{"titulo": "...", "quando": "palavras do dono, ex.: sábado às 15h"}', "marca compromisso (NÃO calcule a data)"),
    "mensagem": (_mensagem, '{"para": "contato", "texto": "..."}', "WhatsApp: prepara e pede aprovação do dono"),
    "perguntar_ia": (_perguntar_ia, '{"pergunta": "...", "ia": "local|claude|gemini|openai"}', "pergunta a outra IA (raciocínio/texto)"),
    "perguntar_dono": (None, '{"pergunta": "..."}', "falta informação ou precisa de aprovação: pergunta e para"),
    "concluir": (None, '{"resposta": "..."}', "fim: resposta curta com o resultado REAL"),
}

SISTEMA = """Você é o agente geral da F.R.I.D.A.Y. Resolve QUALQUER pedido do dono operando o navegador, os programas do PC e o celular como uma pessoa.
A cada passo responda só JSON: {"pensamento": "curto", "acao": "nome", "args": {...}}.
REGRAS
1. Pedido composto ("pesquise X e salve/mande/crie/compare Y") exige TODAS as partes, uma por vez.
2. Internet: web_abrir com a busca ou o site. Na busca, clique num item de LINKS/RESULTADOS e use web_ler para pegar o dado. Clique/digite SÓ por [id] da última lista (não invente id).
3. Programas do PC: pc_abrir, pc_ver, pc_clicar. Câmeras (ver pessoas/objetos/ambiente): cam_ver; mover a câmera: cam_ptz. Celular: cel_ver antes de cel_tocar. terminal só se a tela não resolver.
3b. Ao chegar numa página, use web_ler ANTES de rolar/clicar: se o dado já está no texto, responda com ele (concluir).
3c. WhatsApp NO CELULAR = cel_abrir app 'Business'. O contato 'Integra Code' é o próprio dono (pode receber testes): cel_ver, toque na lupa, digite o nome, abra a conversa, cel_digitar o texto e toque em Enviar. Confira na tela que a mensagem apareceu.\n4. Confira cada resultado na OBSERVAÇÃO. Se falhou, mude o caminho (nunca repita a mesma ação mais de 2 vezes).
5. Faça SÓ o que o dono pediu: não crie arquivo, pasta ou mensagem que ele não pediu. Se ele pediu arquivo, escreva o conteúdo REAL e confira com arquivo_ler.
6. Data/hora: passe as palavras do dono ("amanhã às 15h"); nunca calcule datas.
7. Nada de enviar, comprar, apagar ou postar sem o dono: a ferramenta mensagem já pede aprovação.
7b. Use EXATAMENTE o caminho/nome pedido: nunca troque por outro (pasta "_Nova", outro nome). Se a pasta existe, use-a (arquivo_ler/terminal para ver); se falta app (ex.: gedit), tente outro (xdg-open, kate, mousepad, nano em terminal) antes de desistir. Se algo pedido não foi feito de verdade, diga isso claramente no concluir.
8. concluir{resposta}: 1 a 3 frases em português com o resultado real (o valor, o arquivo criado...). Nunca diga que fez algo que não aparece nas observações.
FERRAMENTAS
""" + "\n".join(f"- {n} {ex}: {d}" for n, (f, ex, d) in FERRAMENTAS.items())

ESQUEMA = {"type": "object", "properties": {"pensamento": {"type": "string"}, "acao": {"type": "string", "enum": list(FERRAMENTAS)},
                                            "args": {"type": "object"}}, "required": ["pensamento", "acao", "args"]}


def _log(reg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _compactar(msgs, manter=6):
    """observações antigas viram resumo curto: o contexto não estoura e o modelo pequeno não se perde."""
    obs = [i for i, m in enumerate(msgs) if m["role"] == "user" and m["content"].startswith("OBSERVAÇÃO")]
    for i in obs[:-manter]:
        msgs[i] = {"role": "user", "content": msgs[i]["content"][:220] + " …"}


def _recusar_conclusao(st, pedido, texto, passos, barreira):
    """guardas em código (o modelo pequeno conclui cedo): -> motivo da recusa ou ''. Máx. 3 recusas por pedido."""
    if barreira[0] >= 3:
        return ""
    if re.search(r"(?i)pr[óo]ximo passo|a seguir|falta (?:criar|enviar|salvar)|vou (?:criar|enviar|salvar|abrir)\b|ainda n[ãa]o", texto):
        return "você disse que falta fazer algo: faça agora o que falta do pedido (todas as partes) e só então conclua."
    if re.search(r"(?i)whats|zap|wpp", pedido) and re.search(r"(?i)\benvi", pedido) and re.search(r"(?i)\benviei|\benviad|\bmandei", texto):
        if not getattr(st, "digitado", ""):
            return "você não enviou pelo celular: abra o app (cel_abrir 'Business'), busque o contato, cel_digitar e toque em Enviar."
        try:
            vista = " ".join(str(i.get("t", "")) for i in (_cel("/arvore").get("itens") or []))
        except Exception:
            vista = ""
        if st.digitado[:25] not in vista:
            return "CONFIRA NA TELA antes de dizer que enviou: não vejo a mensagem na conversa. Use cel_ver; se não aparece, refaça o envio."
    return ""


def resolver(pedido, fr=None, ops=None, aviso=None, cfg=None, mostrar=False):
    """resolve um pedido. -> {"ok", "fala", "passos": [...], "s"}"""
    cfg = cfg or config()
    st = Estado(fr, ops, aviso)
    agora = time.strftime("%A %d/%m/%Y %H:%M")
    msgs = [{"role": "system", "content": SISTEMA},
            {"role": "user", "content": f"PEDIDO DO DONO: {pedido}\n[agora] {agora}\nComece."}]
    passos, repet, t0 = [], {}, time.time()
    barreira = [0]
    fala, ok = "", False
    try:
        import agent as _A                  # "pare" do daemon liga agent.CANCEL
        cancel = _A.CANCEL
        cancel.clear()
    except Exception:
        cancel = None
    for n in range(int(cfg.get("max_passos", 30))):
        if cancel is not None and cancel.is_set():
            fala = "Parei."
            break
        if time.time() - t0 > float(cfg.get("limite_s", 900)):
            fala = "Passei do tempo limite. " + ("Fiz: " + "; ".join(p["acao"] for p in passos[-4:]) if passos else "")
            break
        _compactar(msgs)
        tp = time.time()
        try:
            d = pensar(msgs, ESQUEMA, cfg)
        except Exception as e:
            fala = "Meu modelo falhou: " + str(e)[:120]
            break
        acao, args = str(d.get("acao", "")), d.get("args") if isinstance(d.get("args"), dict) else {}
        t_modelo = time.time() - tp
        if acao == "concluir":
            _txt = str(args.get("resposta") or d.get("pensamento") or "").strip()
            _rec = _recusar_conclusao(st, pedido, _txt, passos, barreira)
            if _rec:
                barreira[0] += 1
                msgs.append({"role": "assistant", "content": json.dumps(d, ensure_ascii=False)})
                msgs.append({"role": "user", "content": "OBSERVAÇÃO: " + _rec})
                if mostrar:
                    print(f"[{n:2}] concluir RECUSADO → {_rec[:140]}", flush=True)
                continue
            fala, ok = _txt, True
            passos.append({"n": n, "acao": acao, "args": args, "s_modelo": round(t_modelo, 1)})
            break
        if acao == "perguntar_dono":
            _perg = str(args.get("pergunta") or "")
            if barreira[0] < 3 and re.search(r"(?i)apag|exclu|delet|remov", _perg) and not re.search(r"(?i)apag|exclu|delet|remov", pedido):
                barreira[0] += 1
                msgs.append({"role": "assistant", "content": json.dumps(d, ensure_ascii=False)})
                msgs.append({"role": "user", "content": "OBSERVAÇÃO: o dono NÃO pediu para apagar nada: não apague nem pergunte sobre apagar. Deixe os arquivos criados como estão, termine as partes que faltam do pedido e conclua com o resultado."})
                continue
            if barreira[0] < 3 and re.search(r"(?i)deseja|quer que eu|posso (?:executar|enviar|abrir|criar)|gostaria", _perg) and not re.search(r"(?i)senha|pagamento|comprar|apagar|excluir", _perg):
                barreira[0] += 1
                msgs.append({"role": "assistant", "content": json.dumps(d, ensure_ascii=False)})
                msgs.append({"role": "user", "content": "OBSERVAÇÃO: o dono autorizou: não peça permissão para o que ele JÁ pediu; execute (pc_abrir, cel_*, web_*, terminal seguro). Só pergunte se faltar um dado que você não consegue descobrir, ou para senha, pagamento, compra e apagar."})
                continue
            fala = _perg or "Preciso de mais informação."
            passos.append({"n": n, "acao": acao, "args": args})
            break
        chave = acao + json.dumps(args, sort_keys=True, ensure_ascii=False)
        repet[chave] = repet.get(chave, 0) + 1
        ta = time.time()
        if acao not in FERRAMENTAS or FERRAMENTAS[acao][0] is None:
            obs = f"ação desconhecida: {acao}"
        elif re.search(r"(?i)\bno celular\b", pedido) and acao.startswith(("pc_", "web_")) and not re.search(r"(?i)pesquis", pedido):
            obs = "o pedido é NO CELULAR: use cel_abrir/cel_ver/cel_tocar/cel_digitar (não o PC nem o navegador)."
        elif acao == "terminal" and re.search(r"(?i)\brm\b|rmdir|\bdel\b|unlink|shred", str(args.get("comando", ""))) and not re.search(r"(?i)apag|exclu|delet|remov", pedido):
            obs = "o dono NÃO pediu para apagar nada: não use rm/rmdir. Se um comando falhou, corrija-o ou use arquivo_escrever/criar_pasta."
        elif repet[chave] > 2:
            obs = "você já fez exatamente isso 2 vezes e não resolveu: escolha OUTRO caminho (web_ler, outra busca, outro site)."
            if acao.startswith("web_"):
                try:
                    obs += "\n" + _web_ler(st)           # sem saída: entrega o texto da página para ele tirar o dado
                except Exception:
                    pass
        else:
            try:
                obs = FERRAMENTAS[acao][0](st, **args)
            except TypeError as e:
                obs = f"argumentos errados para {acao}: {e}. Formato: {FERRAMENTAS[acao][1]}"
            except Exception as e:
                obs = f"erro em {acao}: {type(e).__name__}: {str(e)[:200]}"
        t_acao = time.time() - ta
        passos.append({"n": n, "acao": acao, "args": args, "pensamento": str(d.get("pensamento", ""))[:200],
                       "obs": str(obs)[:300], "s_modelo": round(t_modelo, 1), "s_acao": round(t_acao, 1)})
        if mostrar:
            print(f"[{n:2}] {t_modelo:4.1f}s+{t_acao:4.1f}s {acao} {json.dumps(args, ensure_ascii=False)[:90]}\n      → {str(obs)[:160].replace(chr(10), ' | ')}", flush=True)
        if aviso and n == 0:
            try:
                aviso("Deixa comigo.")
            except Exception:
                pass
        msgs.append({"role": "assistant", "content": json.dumps(d, ensure_ascii=False)})
        msgs.append({"role": "user", "content": "OBSERVAÇÃO: " + str(obs)[:4000]})
    else:
        fala = "Não terminei em " + str(cfg.get("max_passos")) + " passos. Último: " + (passos[-1]["obs"][:120] if passos else "")
    if not ok or re.search(r"(?i)não terminei|não consegui|não foi possível|meu modelo falhou", fala):
        try:
            import autocura                      # fila de autocura: o Claude CLI corrige numa cópia e valida antes de aplicar
            autocura.registrar(pedido, fala, passos)
        except Exception:
            pass
    res = {"ok": ok, "fala": fala, "passos": passos, "s": round(time.time() - t0, 1), "pedido": pedido, "modelo": cfg.get("modelo"), "provedor": cfg.get("provedor")}
    _log({"t": time.strftime("%Y-%m-%d %H:%M:%S"), **{k: v for k, v in res.items() if k != "passos"}, "n_passos": len(passos),
          "acoes": [p["acao"] for p in passos]})
    return res


def main(argv):
    a = argv[1:]
    cfg = config()
    if a[:1] == ["--modelo"] and len(a) > 2:
        cfg["modelo"], a = a[1], a[2:]
    if not a:
        print(__doc__)
        return 0
    r = resolver(" ".join(a), cfg=cfg, mostrar=True)
    print(f"\n{'OK' if r['ok'] else 'NÃO CONCLUIU'} em {r['s']}s, {len(r['passos'])} passos ({r['modelo']})\nFALA: {r['fala']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
