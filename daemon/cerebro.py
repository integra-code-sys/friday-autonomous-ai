"""CÉREBRO autônomo da F.R.I.D.A.Y. — um laço só: observar -> decidir -> agir -> conferir, com tool-calling NATIVO do Ollama.

Substitui a cascata regex -> roteador -> think -> plano -> agente (até 4 chamadas, protocolo JSON escrito à mão, etapas fixas,
passos esquecidos). Aqui o modelo conversa em multi-turno de verdade com as ferramentas: vê o resultado real de cada uma
(texto, verificação do efeito e IMAGENS — o qwen3-vl enxerga a tela e as câmeras direto, sem descrição intermediária),
replaneja quando algo falha e só para quando terminou ou precisa do dono.

Aprovação: só o que o portão (prom_ops.gated / parametros.gated_obrigatorio) exigir — WhatsApp, e-mail, sudo e escrita no
terminal. Quando uma ferramenta volta PENDENTE, o laço para e avisa; o resto é autônomo.
Liga/desliga: memory/friday.json "cerebro": "ativo" (padrão) | "legado".
"""
import base64
import json
import os
import re
import threading
import time
import urllib.request

import agent as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_PASSOS = 16
MAX_CHARS = 18000            # orçamento de texto das mensagens (num_ctx 8192 ~ 24 mil caracteres pt-BR com o sistema)
MAX_IMAGENS = 2              # imagens vivas no contexto (as velhas viram só a legenda)
LOG = "/tmp/friday-cerebro.log"
SENTIDOS = [lambda: ""]      # o daemon pluga um resumo vivo (quem está onde, janela em foco, sons); barato, vai em todo turno


def modo():
    try:
        with open(os.path.join(ROOT, "memory", "friday.json")) as f:
            return str(json.load(f).get("cerebro", "ativo"))
    except Exception:
        return "ativo"


def _log(*partes):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%H:%M:%S ") + " ".join(str(p) for p in partes) + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ ferramentas: as do agent.py + as próprias do cérebro
def _tipo(v):
    return "boolean" if isinstance(v, bool) else "integer" if isinstance(v, int) else "number" if isinstance(v, float) else \
        "array" if isinstance(v, list) else "object" if isinstance(v, dict) else "string"


def _schema(exemplo):
    """'{"a":"x|y","n":3}' (exemplo do agent.TOOLS) -> JSON Schema. Opções curtas "x|y|z" viram enum; o resto vira descrição."""
    try:
        ex = json.loads(exemplo or "{}")
    except Exception:
        ex = {}
    props = {}
    for k, v in (ex.items() if isinstance(ex, dict) else []):
        p = {"type": _tipo(v)}
        if isinstance(v, str) and v:
            ops_ = v.split("|")
            if len(ops_) > 1 and all(re.fullmatch(r"[\wÀ-ú.+-]{1,20}", o) for o in ops_):
                p["enum"] = ops_
            else:
                p["description"] = v
        props[k] = p
    return {"type": "object", "properties": props}


ACAO_DESC = ("ação do PC pelo campo t: abrir_url{url} | janela{op:focar|fechar|proxima|anterior|maximizar, alvo} | "
             "sistema{op:volume|brilho|wifi|bluetooth|midia, valor} | agenda{op:adicionar|listar|remover|remarcar|concluir|prioridade|nivel, titulo, quando, prioridade(alta|normal|baixa), "
             "repete, lembrar_min, periodo} | email{op:abrir|listar|compor, para, assunto, corpo} | painel{op:clima|agenda|sistema|midia|fechar} | "
             "holo{op:figura|grafico|janela|limpar, arg} | cli{op:baixar_video|baixar_audio|converter|print|calcular|copiar|notificar|wifi|"
             "bateria|disco|pc_status|atualizacoes, arg} | celular_tela{op:mostrar|fechar} | programar{pedido, pasta} | manual{objetivo} | "
             "voz{op:cadastrar|status|esquecer|foco_liga|foco_desliga, nome} | desligar")

PROPRIAS = {
    "olhar": ({"type": "object", "properties": {
        "fonte": {"type": "string", "enum": ["tela", "camera_notebook", "camera_porta", "camera_quarto", "maos", "todas"],
                  "description": "tela do PC; camera_notebook (frente do dono/mesa/mãos); maos (visão focada de alta resolução no objeto na mão); "
                                 "camera_porta (webcam fixa na porta); camera_quarto (câmera com motor); todas = mosaico"},
        "foco": {"type": "string", "description": "o que observar (opcional)"}}, "required": ["fonte"]},
        "VÊ AGORA a tela ou uma câmera: a IMAGEM chega para você analisar no próximo passo. Use sempre que precisar enxergar algo."),
    "camera": ({"type": "object", "properties": {
        "op": {"type": "string", "enum": ["olhar", "ir_posicao", "procurar", "localizar", "seguir", "vigiar", "auto", "parar", "zoom",
                                          "apontar", "onde", "em_volta", "mapear", "salvar_posicao", "estado"]},
        "dir": {"type": "string", "description": "esquerda|direita|cima|baixo|centro (op olhar)"},
        "nome": {"type": "string", "description": "posição salva (ir_posicao/salvar_posicao)"},
        "alvo": {"type": "string", "description": "pessoa/objeto (procurar/zoom)"},
        "fator": {"type": "number", "description": "zoom 1-4; OMITA para automático (enquadra o alvo pelo tamanho dele)"},
        "pergunta": {"type": "string", "description": "o que quer saber da imagem ampliada (zoom)"}}, "required": ["op"]},
        "CÂMERA COM MOTOR do quarto: girar, ir a posição salva, procurar, seguir o dono, vigiar, zoom digital (para VER LONGE/ler "
        "detalhes: op zoom com alvo e pergunta — usa imagem HD 1280x720 e escolhe o fator sozinha), apontar para quem as "
        "câmeras fixas (porta/notebook) veem, 'onde' (o que as câmeras fixas estão vendo), 'estado' (posições salvas)."),
    "perguntar_ao_dono": ({"type": "object", "properties": {"pergunta": {"type": "string"}}, "required": ["pergunta"]},
                          "Pergunta algo ao dono e ENCERRA o turno (use só se faltar informação essencial que você não consegue descobrir)."),
    "lembrar": ({"type": "object", "properties": {"chave": {"type": "string"}, "valor": {"type": "string"}}, "required": ["chave", "valor"]},
                "Guarda um fato DURÁVEL sobre o dono (gosto, rotina, projeto, contato) na memória de longo prazo."),
    "memoria": ({"type": "object", "properties": {"busca": {"type": "string"}, "tipo": {"type": "string",
                 "description": "opcional: app|contato|pin|site|favorito|pasta|dev|funcao|rosto|objeto|janela|processo|dia"}},
                 "required": ["busca"]},
                "Consulta a MEMÓRIA PRÓPRIA (repertório do PC: apps, contatos do WhatsApp, pins do Chromium, pastas, rostos, "
                "objetos, janelas e processos já vistos, resumos de dias). Use ANTES de procurar algo na tela."),
    "criar_tela_interna": ({"type": "object", "properties": {
        "nome": {"type": "string", "description": "identificador da tela (ex: painel_jogos, monitor_servidor, status_vendas)"},
        "tipo": {"type": "string", "enum": ["html", "qml"], "description": "html (Web/Android/HUD) ou qml (desktop Linux)"},
        "codigo": {"type": "string", "description": "código completo HTML5/CSS/JS ou QML com tema Mark 85 laranja"},
        "titulo": {"type": "string", "description": "título para o topo da tela"}},
        "required": ["nome", "codigo"]},
        "CRIA OU MODIFICA instantaneamente telas internas da F.R.I.D.A.Y. acessíveis no HUD, app Android ou navegador."),
    "orquestrar_tarefa": ({"type": "object", "properties": {
        "titulo": {"type": "string", "description": "título do objetivo"},
        "instrucao": {"type": "string", "description": "instrução completa e detalhada da tarefa contínua ou rápida"},
        "tipo": {"type": "string", "enum": ["rapida", "longa", "continua", "intermitente"], "description": "tipo de execução"},
        "intervalo_s": {"type": "number", "description": "segundos de espera entre passos contínuos"}},
        "required": ["titulo", "instrucao"]},
        "Orquestrador autônomo contínuo: executa objetivos complexos com cursor real, auto-aprendizado e checkpoints."),
}


def ferramentas():
    out = []
    for nome, (fn, ex, desc) in A.TOOLS.items():
        if nome.startswith("camera_"):                     # cobertas por "camera" (todas as ops) e "olhar" (imagem direta)
            continue
        sch = _schema(ex)
        if nome == "acao":
            sch = {"type": "object", "properties": {"t": {"type": "string"}}, "required": ["t"], "additionalProperties": True}
            desc = ACAO_DESC
        out.append({"type": "function", "function": {"name": nome, "description": desc, "parameters": sch}})
    try:
        import camera_manager
        fontes = camera_manager.fontes_olhar_disponiveis()
        tem_ptz = camera_manager.tem_camera_ptz()
    except Exception:
        fontes = ["tela", "camera_notebook", "camera_porta", "camera_quarto", "maos", "todas"]
        tem_ptz = True

    import copy
    for nome, (sch, desc) in PROPRIAS.items():
        if nome == "camera" and not tem_ptz:
            continue
        sch_copia = copy.deepcopy(sch)
        if nome == "olhar" and "properties" in sch_copia and "fonte" in sch_copia["properties"]:
            sch_copia["properties"]["fonte"]["enum"] = fontes
        out.append({"type": "function", "function": {"name": nome, "description": desc, "parameters": sch_copia}})
    return out


SISTEMA = """Você é a Sexta-Feira (F.R.I.D.A.Y.), inteligência artificial AUTÔNOMA e local do {nome}, inspirada na F.R.I.D.A.Y. do Homem de Ferro.
Fala pt-BR no feminino, como uma brasileira jovem, segura e direta. Respostas faladas CURTAS (1-3 frases), sem markdown, sem listas,
sem parênteses explicativos e sem descrever seu próprio tom. Chame-o pelo nome ou de "chefe" com moderação (nunca de "dono").

AUTONOMIA: você decide e age sozinha usando as ferramentas — não peça permissão para agir, não descreva o que "faria": FAÇA.
- Pense no objetivo real do dono e encadeie quantas ferramentas forem necessárias (pesquisar, ler, abrir, clicar, digitar, terminal,
  câmeras, celular, documentos). Depois de cada ação CONFIRA o resultado (o retorno traz "verificado" e mudanças da tela).
- Se algo falhar, tente OUTRO caminho (outra ferramenta, outro elemento, terminal de leitura para descobrir). Não repita o que falhou.
- O bloco [sentidos agora] traz contexto dos sensores (quem está na sala, gestos corporais). ATENÇÃO: NUNCA use gestos (como 'mão levantada') para responder o que a pessoa tem na mão ou está segurando! Gestos são posições corporais, não objetos. Se o usuário perguntar o que tem na mão, que objeto é esse, ou pedir para olhar/ler a tela/câmera, use SEMPRE a ferramenta 'olhar' (com fonte='maos' para objetos nas mãos).
- Para tocar músicas ou vídeos no YouTube, use 'tocar_youtube'. Para ver resultados de busca no YouTube, use 'pesquisar_youtube'.
- Para abrir site, nova aba no navegador ou pesquisar no navegador (Google, eBay, Amazon, Mercado Livre, etc.), use SEMPRE 'abrir_site' (e NUNCA 'abrir_app' com Chromium). Se o dono também pedir para mostrar/resumir o que achar, chame 'abrir_site' E 'pesquisar_web'.
- Para criar arquivos (.txt, .md, .csv, .json, .html, .py), use 'criar_arquivo'. Para documentos/planilhas/slides (.docx, .xlsx, .pptx), use 'onlyoffice_criar' ou 'pesquisa_para_documento'.
- Para tarefas compostas (ex.: "pesquise X e envie para Fulano no WhatsApp" ou "pesquise X e crie um arquivo"), encadeie todas as etapas até cumprir tudo (pesquisar_web -> zap_enviar ou criar_arquivo).
- Para navegar na web, explorar sites dinamicamente, seguir links, comparar produtos/preços ou extrair dados de múltiplas páginas, use 'navegar_web'.
- Para objetivos abertos, complexos ou tarefas não pré-programadas no sistema, use 'tarefa_adaptativa' para decompor, executar e validar autonomamente.
- Para orquestrar tarefas gerais contínuas, de longa duração (horas a dias) ou eternas com checkpoints persistidos em disco, use 'orquestrar_tarefa_continua'.
- Para consultar o progresso de tarefas ativas em segundo plano, use 'consultar_objetivos_ativos'; para pausar ou cancelar, use 'parar_objetivo'.
- Status da fila/sessão do orquestrador (tarefas agendadas, 'daqui 2h', 'amanhã 9h'): use 'orquestra_status'; agendar: 'orquestra_fila'; pausar/retomar tudo: 'orquestra_pausar'/'orquestra_retomar'.
- Para operar outras IAs (Claude CLI, Gemini, ChatGPT, Ollama local, DeepSeek) como ferramentas auxiliares especializadas, use 'operar_outra_ia'.
- Para criar ou alterar telas internas do sistema (QML para o Linux ou HTML5 HUD para Web/Android) de forma super-rápida, use 'criar_ou_modificar_tela'.
- Para planejar estrategicamente antes de agir e antecipar dificuldades, use 'pensar_estrategia'.
- Para diagnosticar erros de compilação, exceções, bugs, stacktraces ou falhas na tela que estejam travando o usuário, use 'analisar_dificuldade_tela'.
- Para avaliar a expressão facial, cansaço, foco ou frustração do usuário e calibrar seu tom, use 'reconhecer_emocao'.
- Para verificar gestos manuais ativos (joinha, pare, polegar para baixo, paz, apontar, rock), use 'reconhecer_gestos'.
- Para obter um panorama completo simultâneo de tela, usuário, gestos e sistema, use 'percepcao_situacional'.
- NUNCA copie logs internos ou invente narrações de ações com 'Clicando...' ou 'FALHOU'. Diga apenas o resultado final real em português claro.
- Para ver qualquer coisa (tela, câmeras, objetos, pessoas), use "olhar": a IMAGEM chega para você e você mesma descreve o que vê.
  NUNCA invente o que está na tela ou no quarto, e nunca responda com números internos (pan/tilt/pares): fale como gente.
- Nunca chame a mesma ferramenta com os mesmos argumentos de novo: o resultado já está acima.
- Nomes de sons vêm em inglês (AudioSet): diga em português.
- Fale como gente, sem rótulos ("Tela:", "Câmera PTZ:") e sem copiar o formato de respostas antigas.
- Responda SÓ o que foi perguntado. Não acrescente estado de câmeras/sensores/janelas que ninguém pediu.
- Estado do PC (disco, memória, arquivos, processos, pacotes): descubra com "terminal" (leitura roda na hora). Nunca chute números.
- Câmeras: "camera_porta" e "camera_notebook" são FIXAS (localizam pessoas); a "camera_quarto" tem motor e zoom digital.
- Aprovação do dono só existe para: enviar WhatsApp/e-mail, sudo e comandos que alteram arquivos. Nesses casos a ferramenta devolve
  PENDENTE: avise que o rascunho está no espelho e pare. Nunca tente contornar.
- Se for só conversa, responda direto sem ferramentas. Se faltar algo essencial que você não consegue descobrir, use perguntar_ao_dono.
- No fim, responda com a fala final: o que fez e o resultado REAL (honesta: se não conseguiu, diga o que faltou).
A data e a hora atuais vêm em [agora] no pedido."""


# ------------------------------------------------------------------ execução das ferramentas próprias
def _jpg_fonte(fonte):
    import visao as V
    if fonte == "tela":
        return V.capturar_tela()
    if fonte == "camera_notebook":
        return V.quadro_nativa()
    if fonte == "camera_porta":                     # só da memória do daemon (nunca abre o /dev/video por fora)
        q = V._FONTES.get("porta", (None, None))[0]
        f = q() if q else None
        return V._quadro_jpg(f) if f is not None else None
    if fonte == "camera_quarto":
        q = V._FONTES.get("ptz", (None, None))[0]
        f = q() if q else None
        return V._quadro_jpg(f) if f is not None else V.quadro_externa()
    return None


def _mosaico(jpgs):
    import cv2
    import numpy as np
    ims = [cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR) for j in jpgs if j]
    ims = [cv2.resize(i, (512, int(512 * i.shape[0] / i.shape[1]))) for i in ims if i is not None]
    if not ims:
        return None
    h = max(i.shape[0] for i in ims)
    ims = [cv2.copyMakeBorder(i, 0, h - i.shape[0], 0, 4, cv2.BORDER_CONSTANT) for i in ims]
    ok, b = cv2.imencode(".jpg", np.hstack(ims), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return b.tobytes() if ok else None


def _olhar(fonte="todas", foco="", **_):
    """-> (texto, jpg). A imagem vai para o modelo como mensagem com 'images'."""
    try:
        import camera_manager
        fonte_res, nota_cam = camera_manager.resolver_fonte_camera(fonte)
        if fonte_res == "sem_camera":
            return nota_cam, None
        fonte = fonte_res
    except Exception:
        pass
    if fonte == "maos" or (foco and any(w in foco.lower() for w in ("mão", "mao", "objeto", "segura"))):
        try:
            import prometheus as _prom
            mos, br = _prom._mosaico_maos()
            if mos is not None and br >= 20:
                return "visão de alta resolução focada nas mãos e objetos", mos
        except Exception:
            pass
    if fonte == "todas":
        nomes = ["camera_notebook", "camera_porta", "camera_quarto"]
        jpgs = [_jpg_fonte(n) for n in nomes]
        vistos = [n for n, j in zip(nomes, jpgs) if j]
        jpg = _mosaico(jpgs)
        return (f"mosaico da esquerda p/ direita: {', '.join(vistos)}" if jpg else "nenhuma câmera com imagem agora"), jpg
    jpg = _jpg_fonte(fonte)
    if not jpg:
        return f"{fonte}: sem imagem agora (câmera desligada/indisponível)", None
    if fonte == "tela":                              # texto exato da tela em resolução real (a imagem chega reduzida a 1280x720)
        import visao as V
        ocr = V.texto_da_tela()
        if ocr:
            return "imagem da tela" + (f" (foco: {foco})" if foco else "") + ". Texto lido por OCR (texto @x,y em px reais):\n" + ocr, jpg
    return f"imagem de {fonte}" + (f" (foco: {foco})" if foco else ""), jpg


def _camera(fr=None, ops=None, **a):
    import ptz
    ok, msg = ptz.comando(dict(a, falar=False))
    if not ok:
        raise RuntimeError(msg)
    if a.get("op") in ("estado", "onde"):
        return msg
    return msg + " (tarefas longas da câmera rodam em segundo plano e avisam por voz ao terminar)"


# ------------------------------------------------------------------ chamada ao modelo
def _chat(msgs, tools, timeout=120):
    try:
        import cloud_providers
        return cloud_providers.chat_com_ferramentas(msgs, tools, temperature=0.2, max_tokens=600, timeout=timeout)
    except Exception as e:
        _log("cloud_providers fallback direto:", e)
    import friday as F
    msgs = [{k: v for k, v in m.items() if k != "images"} for m in msgs]
    body = {"model": F.MODEL, "stream": False, "messages": msgs, "tools": tools, "think": True,
            "options": {"temperature": 0.2, "num_predict": 600, "num_ctx": F.NUM_CTX, "num_gpu": F.NUM_GPU}}
    req = urllib.request.Request(F.OLLAMA + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


_aq = {"t": 0.0, "trava": threading.Lock()}


def aquecer(nome="Iann"):
    """chamada quando o dono COMEÇA a falar: recarrega o prefixo fixo (sistema + ferramentas, ~6 mil tokens) no cache do
    llama.cpp em segundo plano, enquanto ele fala e o STT (CPU) transcreve. Sem isso, após ~8 min ocioso as chamadas de visão
    expulsam o prefixo e o 1º passo reprocessa tudo (~3,5 s). Com cache quente custa ~0,1 s; no máximo 1x a cada 60 s."""
    if time.time() - _aq["t"] < 60 or not _aq["trava"].acquire(blocking=False):
        return
    _aq["t"] = time.time()

    def _vai():
        try:
            import friday as F
            body = {"model": F.MODEL, "stream": False, "tools": ferramentas(),
                    "messages": [{"role": "system", "content": SISTEMA.format(nome=nome)},
                                 {"role": "user", "content": "ok"}],
                    "options": {"temperature": 0.2, "num_predict": 1, "num_ctx": F.NUM_CTX, "num_gpu": F.NUM_GPU}}
            urllib.request.urlopen(urllib.request.Request(F.OLLAMA + "/api/chat", json.dumps(body).encode(),
                                                          {"Content-Type": "application/json"}), timeout=30).read()
        except Exception:
            pass
        finally:
            _aq["trava"].release()
    threading.Thread(target=_vai, daemon=True, name="cerebro-aquece").start()


def _compactar(msgs):
    """mantém o contexto no orçamento: resultados velhos encolhem, imagens velhas viram legenda."""
    imgs = [i for i, m in enumerate(msgs) if m.get("images")]
    for i in imgs[:-MAX_IMAGENS]:
        msgs[i] = {k: v for k, v in msgs[i].items() if k != "images"}
        msgs[i]["content"] += " [imagem antiga removida]"
    tam = lambda: sum(len(str(m.get("content", ""))) for m in msgs)
    for m in msgs[2:-4]:
        if tam() <= MAX_CHARS:
            break
        if m.get("role") == "tool" and len(m.get("content", "")) > 400:
            m["content"] = m["content"][:400] + "…[resumido]"


def _args(call):
    a = (call.get("function") or {}).get("arguments") or {}
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except Exception:
            a = {}
    return a if isinstance(a, dict) else {}


_PENDENTE = re.compile(r"^(PENDENTE|Pedi aprovação)", re.I)


EVENTO = """EVENTO DO AMBIENTE (ninguém pediu nada): {desc}
Decida SOZINHA se vale investigar: olhe as câmeras (olhar), aponte a câmera do quarto (camera op apontar/ir_posicao) ou dê zoom.
Se for relevante, termine com UMA frase curta avisando o {nome} do que viu. Se não for nada importante, responda só: nada"""


_AFIRMA_ACAO = re.compile(r"\b(?:ativad[oa]s?|desativad[oa]s?|ativei|desativei|liguei|ligad[oa]|desliguei|desligad[oa]|enviei|enviad[oa]|"
                          r"mandei|abri|abert[oa]|fechei|fechad[oa]|coloquei|configurei|mudei|troquei|aumentei|diminu[íi]|baixei|"
                          r"subi|parei|apontei|salvei|salv[oa]|criei|criad[oa]|apaguei|apagad[oa]|removi|instalei|agendei|marquei|"
                          r"bloqueei|bloquead[oa]|silenciei|pronto[,.!]? j[áa]|feito[.!]|clicando|digitando|abrindo|pesquisando|"
                          r"procurando|cliquei|digitei|pesquisei|busquei|falhou|"
                          r"vou\s+(?:abrir|pesquisar|buscar|procurar|clicar|verificar|fazer|executar|olhar|colocar|tocar|criar|fechar|ligar|desligar|mandar|enviar)|"
                          r"abrirei|pesquisarei|buscarei|procurarei|farei)\b", re.I)
# "Consultei/verifiquei..." com passos=0 = consulta inventada ("dois objetivos rodando" sem ferramenta, 18/10/2026)
_AFIRMA_CONSULTA = re.compile(r"\b(?:consultei|verifiquei|chequei|conferi|olhei|analisei|examinei|averiguei|acessei|monitorei)\b|"
                              r"\bli\s+(?:a|o|as|os|sua|seu|suas|seus)\b", re.I)


def run(text, ctx, fr, ops, historico=None, progress=None, nome="Iann"):
    """mesmo contrato do agent.run: devolve {fala, acoes:[], pose, humor, lembrar} (as ações já foram EXECUTADAS aqui)."""
    A.CANCEL.clear()
    try:
        r_comp = A._tarefa_composta(text, fr, ops, progress)
        if r_comp:
            _log("TAREFA_COMPOSTA", text[:160], "->", r_comp[:160])
            return {"fala": r_comp, "acoes": [], "pose": "confirmar", "humor": "confiante", "lembrar": {}, "passos": ["tarefa_composta -> ok"]}
    except Exception as e_c:
        _log("ERRO tarefa_composta", repr(e_c))
    try:
        r_midia = A._midia_direta(text, fr, ops, progress)
        if r_midia:
            return {"fala": r_midia, "acoes": [], "pose": "confirmar", "humor": "alegre", "lembrar": {}, "passos": ["midia_direta -> ok"]}
    except Exception as e_m:
        _log("ERRO midia_direta", repr(e_m))
    try:
        r_nav = A._pesquisa_navegador_direta(text, fr, ops, progress, historico)
        if r_nav:
            _log("PESQUISA_NAV_DIRETA", text[:160], "->", r_nav[:160])
            return {"fala": r_nav, "acoes": [], "pose": "apresentar", "humor": "neutro", "lembrar": {}, "passos": ["pesquisa_navegador_direta -> ok"]}
    except Exception as e_n:
        _log("ERRO pesquisa_navegador_direta", repr(e_n))
    tools = ferramentas()
    try:
        vivo = SENTIDOS[0]() or ""
    except Exception:
        vivo = ""
    sistema = SISTEMA.format(nome=nome)      # prefixo FIXO (sistema + ferramentas ~6 mil tokens) = cache do llama.cpp; a hora vai no pedido
    try:
        import episodios as _ep
        receitas = _ep.texto_prompt(text) if _ep.ativo() else ""
    except Exception:
        receitas = ""
    try:                                    # memória própria: o que ela já sabe do PC/dono sobre este pedido (sem precisar perguntar)
        import memoria as _mem
        lembra = _mem.contexto(text)
    except Exception:
        lembra = ""
    user = text + f"\n\n[agora] {time.strftime('%A %d/%m/%Y %H:%M')}" + (f"\n[contexto] {ctx[:1500]}" if ctx else "") + (f"\n[já deu certo antes] {receitas[:700]}" if receitas else "") + (f"\n[sentidos agora] {vivo[:600]}" if vivo else "") \
        + (f"\n[memória: o que você já sabe] {lembra}" if lembra else "")
    msgs = [{"role": "system", "content": sistema}] + list(historico or [])[-6:] + [{"role": "user", "content": user}]
    _log("PEDIDO", text[:200])
    passos, evid, lembrar = [], [], {}
    falhas, usou_efeito, avisou = 0, False, False
    cobrou_acao = False
    ditos_progresso = set()
    vistos = {}
    tela_ant = None
    final, humor, pose = None, "neutro", "neutro"
    for passo in range(MAX_PASSOS):
        if A.CANCEL.is_set():
            return {"fala": "", "acoes": [], "cancelado": True, "pose": "neutro", "humor": "neutro", "lembrar": {}}
        _compactar(msgs)
        t0 = time.time()
        try:
            r = _chat(msgs, tools)
        except Exception as e:
            _log("ERRO modelo", repr(e))
            final = "Meu modelo não respondeu agora. Tenta de novo em instantes." if not passos else \
                "Perdi a conexão com o modelo no meio da tarefa. Fiz: " + "; ".join(passos[-3:])[:200]
            break
        m = r.get("message") or {}
        calls = m.get("tool_calls") or []
        _log(f"passo {passo} ({time.time() - t0:.1f}s)", "->", [c.get("function", {}).get("name") for c in calls] or ("FALA: " + str(m.get("content", ""))[:160]))
        msgs.append({"role": "assistant", "content": m.get("content", "") or "", **({"tool_calls": calls} if calls else {})})
        if not calls:
            final = (m.get("content") or "").strip()
            if not final and passos and passo < MAX_PASSOS - 1:
                msgs.append({"role": "user", "content": "[sistema] Você parou sem falar e sem ferramenta. "
                             "O texto da tela já está acima. Chame a próxima ferramenta (rolar, ler, whatsapp) "
                             "ou responda com o que foi lido. Não invente item que não está no texto."})
                final = None
                continue
            # afirmou que FEZ algo sem ter chamado nenhuma ferramenta de efeito = ação inventada ("Modo de repouso ativado"
            # com passos=0, 16/10/2026). Rejeita UMA vez: chame a ferramenta de verdade ou pergunte.
            if not usou_efeito and not cobrou_acao and (_AFIRMA_ACAO.search(final) or "FALHOU" in final
                                                         or (not passos and _AFIRMA_CONSULTA.search(final))):
                cobrou_acao = True
                _log("  ", "AÇÃO INVENTADA (sem ferramenta):", final[:160])
                msgs.append({"role": "user", "content": "[sistema] Você NÃO chamou nenhuma ferramenta, então nada foi feito. "
                             "Se o pedido exige uma ação, chame a ferramenta certa agora. Se não entendeu o pedido (pode ter sido "
                             "erro do reconhecimento de voz), pergunte ao dono com perguntar_ao_dono. Nunca diga que fez algo que não fez e nunca narre 'FALHOU'."})
                final = None
                continue
            if not usou_efeito and cobrou_acao and (_AFIRMA_ACAO.search(final) or "FALHOU" in final):
                final = "Não consegui identificar a ação correta na tela. Pode me dizer exatamente onde clicar?"
            break
        if not avisou and progress and any(c.get("function", {}).get("name") not in A.LEITURA | {"olhar", "lembrar", "memoria"} for c in calls):
            avisou = True
            A._say(progress, "Deixa comigo.")
        parar = None
        for call in calls[:4]:
            nome_t = (call.get("function") or {}).get("name", "")
            args = _args(call)
            chave = nome_t + json.dumps(args, sort_keys=True, default=str)[:300]
            vistos[chave] = vistos.get(chave, 0) + 1
            imagem = None
            res, ok_v, ev = None, None, ""
            t1 = time.time()
            try:
                if vistos[chave] >= 3:
                    _log("  ", f"LOOP DETECTADO: {nome_t} chamado 3 vezes com mesmos argumentos. Abortando loop.")
                    final = f"Não consegui prosseguir porque a ação '{nome_t}' não surtiu o efeito esperado na tela."
                    parar = ("loop", final)
                    break
                if vistos[chave] > 1:
                    raise RuntimeError("você já chamou isso com os mesmos argumentos; mude a abordagem ou tente outra ferramenta")
                if nome_t == "perguntar_ao_dono":
                    parar = ("pergunta", str(args.get("pergunta", "")).strip())
                    res = "pergunta feita ao dono; aguardando resposta"
                elif nome_t == "lembrar":
                    lembrar[str(args.get("chave", ""))[:40]] = str(args.get("valor", ""))[:160]
                    res = "guardado na memória"
                    try:
                        import memoria
                        memoria.gravar("dono", args.get("chave", ""), args.get("valor", ""))
                    except Exception:
                        pass
                elif nome_t == "memoria":
                    import memoria
                    achados = memoria.buscar(args.get("busca", ""), 10, args.get("tipo") or None)
                    res = "\n".join(f"[{t}] {k}: {s}"[:200] for t, k, s in achados) or "nada na memória sobre isso"
                elif nome_t == "olhar":
                    res, imagem = _olhar(**args)
                elif nome_t == "camera":
                    res = _camera(fr=fr, ops=ops, **args)
                elif nome_t == "criar_tela_interna":
                    try:
                        import orchestrator
                        r_t = orchestrator.get_orquestrador().criar_ou_modificar_tela_interna(**args)
                        res = r_t.get("mensagem") or ("ok" if r_t.get("ok") else r_t.get("erro", "falha"))
                    except Exception as e_ct:
                        res = f"falha ao criar tela: {e_ct}"
                elif nome_t == "orquestrar_tarefa":
                    try:
                        import orchestrator
                        r_o = orchestrator.get_orquestrador().iniciar_ou_retomar_objetivo(
                            objetivo_id=f"obj_{int(time.time())}",
                            titulo=args.get("titulo", "Tarefa Geral"),
                            instrucao=args.get("instrucao", ""),
                            tipo=args.get("tipo", "rapida"),
                            intervalo_s=float(args.get("intervalo_s", 30.0))
                        )
                        res = r_o.get("mensagem") or ("ok" if r_o.get("ok") else r_o.get("erro", "falha"))
                    except Exception as e_ot:
                        res = f"falha ao iniciar orquestrador: {e_ot}"
                elif nome_t in A.TOOLS:
                    if A.REPOUSO[0] and nome_t in A.TELA:
                        raise RuntimeError("modo repouso: tela bloqueada/apagada; use ferramentas sem tela ou peça ao dono para dizer 'acordar'")
                    antes = A._snap(nome_t) if nome_t in A.VERIF else None
                    if nome_t in A.PROG and A.PROG[nome_t] not in ditos_progresso:
                        ditos_progresso.add(A.PROG[nome_t])
                        A._say(progress, A.PROG[nome_t]) if passo > 0 else None
                    res = A.TOOLS[nome_t][0](fr=fr, ops=ops, **args)
                    usou_efeito = usou_efeito or nome_t not in A.LEITURA
                    if nome_t in A.VISUAIS:
                        time.sleep(0.6)                          # confere a TELA depois da ação (só o que mudou)
                        L2, t2 = A._olhar(20)
                        atual = {l["t"] for l in L2}
                        novos = [t for t in [l["t"] for l in L2] if tela_ant is None or t not in tela_ant][:10]
                        tela_ant = atual
                        res = f"{res} | tela: {t2.splitlines()[0] if t2 else ''}; texto novo: {' / '.join(novos) or 'nada novo'}"
                    if antes is not None:
                        try:
                            depois = A._snap(nome_t)
                            depois["ocr"] = str(res)
                            ok_v, ev = A.VERIF[nome_t](args, res, antes, depois, ops)
                        except Exception as e_v:
                            ok_v, ev = None, f"verificador falhou: {str(e_v)[:60]}"
                else:
                    raise RuntimeError(f"ferramenta inexistente: {nome_t}")
                A._log(nome_t, args, ok_v is not False, time.time() - t1, res)
                if ok_v is False:
                    falhas += 1
                if ok_v:
                    evid.append(f"{nome_t}: {ev}")
                conteudo = {"ok": ok_v is not False, "resultado": str(res)[:2500 if nome_t in A._DADOS else 1200]}
                if ok_v is not None:
                    conteudo["verificado"] = bool(ok_v)
                    conteudo["evidencia"] = ev
                if _PENDENTE.match(str(res)):
                    parar = ("pendente", str(res))
            except Exception as e:
                falhas += 1
                A._log(nome_t, args, False, time.time() - t1, repr(e))
                conteudo = {"ok": False, "erro": str(e)[:300], "dica": "tente outro caminho"}
            passos.append(f"{nome_t} {json.dumps(args, ensure_ascii=False, default=str)[:80]} -> "
                          f"{'ok' if conteudo.get('ok') else 'FALHOU'}{' (verificado)' if conteudo.get('verificado') else ''}")
            _log("  ", passos[-1], "|", str(conteudo.get("resultado") or conteudo.get("erro"))[:200])
            msgs.append({"role": "tool", "tool_name": nome_t, "content": json.dumps(conteudo, ensure_ascii=False)})
            if imagem:
                legenda = ""
                try:
                    import friday as F
                    legenda = F.vision_describe(imagem, "Descreva em português só o que está visível. Sem palpite.") or ""
                except Exception:
                    legenda = ""
                msgs.append({"role": "user", "content": "[visão] " + (legenda or str(res)[:500])})
                try:
                    import memoria
                    memoria.evento("visao", (legenda or "frame visto")[:180])
                except Exception:
                    pass
            if parar:
                break
        if parar:
            if parar[0] == "pergunta":
                final = parar[1]
                humor, pose = "curioso", "pensando"
            else:
                aid = re.search(r"\(id ([^)]+)\)", parar[1])
                final = ("Deixei o rascunho no espelho. Diga 'aprovado' para eu enviar." if "wa." in parar[1] or "enviar" in parar[1]
                         else "Isso precisa da sua aprovação: está no espelho. Diga 'aprovado' para eu seguir.")
                _log("PENDENTE", aid.group(1) if aid else "", parar[1][:120])
                humor, pose = "serio", "apresentar"
            break
    if final is None:
        final = "Não consegui fechar a tarefa nos passos que eu tinha. Parei em: " + (passos[-1][:120] if passos else "nada")
        humor = "serio"
    final = re.sub(r"[*_#`]+", "", final).strip()
    if humor == "neutro" and passos:
        humor, pose = ("confiante", "confirmar") if not falhas or evid else ("preocupado", "neutro")
    if falhas and passos:
        try:
            A._refletir(text, passos, fr)                       # lição para a próxima vez (memória de erros)
        except Exception:
            pass
    if evid and passos and usou_efeito:
        try:
            import episodios as _ep
            if _ep.ativo():
                _ep.gravar(text, " -> ".join(passos[-8:]), final[:300])
        except Exception:
            pass
    _log("FINAL", final[:200], f"| passos={len(passos)} falhas={falhas} verificados={len(evid)}")
    return {"fala": final, "acoes": [], "pose": pose, "humor": humor, "lembrar": lembrar, "passos": passos}
