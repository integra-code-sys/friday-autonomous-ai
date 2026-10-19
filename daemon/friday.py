"""F.R.I.D.A.Y. — cérebro LOCAL: intents rápidos por regra + LLM local (Ollama/gemma3) + executores de ações.
Nada aqui chama a nuvem. O Claude entra só como ferramenta de programação (ver prometheus.py: run_programming)."""
import json
import sys, os, re, subprocess, time, urllib.request
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


OLLAMA = os.environ.get("FRIDAY_OLLAMA", "http://127.0.0.1:11434")
MODEL = os.environ.get("FRIDAY_MODEL", "qwen3.5:4b")   # conversa e ferramentas: modelo que raciocina
MODEL_VISAO = os.environ.get("FRIDAY_VISION_MODEL", "qwen3-vl:4b-instruct")   # só câmera e tela (enxerga)
NUM_GPU = int(os.environ.get("FRIDAY_NUM_GPU", "99"))     # 99 = tudo na GPU (Whisper roda na CPU); offload parcial gera lixo, então é tudo ou nada
NUM_CTX = int(os.environ.get("FRIDAY_NUM_CTX", "16384"))  # IGUAL em todo o projeto (visao/documento/prometheus/cerebro): valor diferente recarrega o modelo

# nome falado: o Whisper erra bastante ("testa a feira", "esta feira", "sesta feira"...) -> casamento tolerante
NOME = r"(?:s[eê]xt|t[eê]st|s[eê]st|c[eê]st|t[eê]xt|[eé]st|est|[eé]ss|ess|sest|cest|sext)a?\s*-?\s*(?:a\s+)?f[eé]i?ra?|friday|f\.?\s?r\.?\s?i\.?\s?d\.?\s?a\.?\s?y\.?"
WAKE_ON = re.compile(r"(?:\b(?:" + NOME + r")\b.{0,14}\b(?:lig\w*|ativ\w*|acord\w*|despert\w*|inici\w*|on)\b|\b(?:lig\w*|ativ\w*|acord\w*|despert\w*|inici\w*|on)\b.{0,14}\b(?:" + NOME + r")\b)", re.I)
WAKE_OFF = re.compile(r"(?:\b(?:" + NOME + r")\b.{0,14}\b(?:deslig\w*|desativ\w*|dorm\w*|encerr\w*|off|tchau)\b|\b(?:deslig\w*|desativ\w*|dorm\w*|encerr\w*|off|tchau)\b.{0,14}\b(?:" + NOME + r")\b)", re.I)
NAME_RE = re.compile(r"\b(" + NOME + r")\b[,!. ]*", re.I)

ALIASES = {                      # apelido falado -> (kind, valor)
    r"caixa de (e-?mail|entrada)|e-?mail|gmail|correio": ("email", None),
    r"you\s?tube|yutube|ioutube": ("url", "https://www.youtube.com"),
    r"zap(\s?zap)?|whats(app)?": ("app", "ZapZap"),
    r"browser|navegador|chromium|internet": ("app", "Chromium"),
    r"terminal|console": ("app", "kitty"),
    r"arquivos|gerenciador de arquivos|pastas": ("app", "Files"),
    r"calculadora": ("app", "qalculate"),
    r"c[óo]digo|editor|vscode|vs code": ("app", "Code - OSS"),
    r"antigravity|anti[- ]?gravidade": ("app", "antigravity"),
    r"anydesk|acesso remoto": ("app", "AnyDesk"),
}


def _post(path, body, timeout=60):
    req = urllib.request.Request(OLLAMA + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _llm_log(r, out, json_mode):
    """uma linha por chamada em /tmp/friday-llm.log: tokens do prompt, tempo de geração e se o JSON veio válido"""
    try:
        ok = "-"
        if json_mode:
            try:
                json.loads(out); ok = 1
            except Exception:
                ok = 0
        with open("/tmp/friday-llm.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} prompt_eval_count={r.get('prompt_eval_count')} "
                    f"eval_duration={(r.get('eval_duration') or 0) / 1e9:.2f}s json_ok={ok}\n")
    except Exception:
        pass


def llm(system, user, history=None, json_mode=True, num_predict=220, temperature=0.3, timeout=60, schema=None):
    """chamada ao modelo local. Devolve texto (ou dict, se json_mode e parse ok). schema = JSON schema do Ollama (enum fechado)."""
    msgs = [{"role": "system", "content": system}] + list(history or []) + [{"role": "user", "content": user}]
    body = {"model": MODEL, "stream": False, "messages": msgs, "think": False,   # 19/10: qwen3.5 pensa por padrão e gastava todo num_predict -> conteúdo vazio (json_ok=0 em tudo)
            "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": NUM_CTX, "num_gpu": NUM_GPU}}
    if json_mode:
        body["format"] = schema if isinstance(schema, dict) else "json"     # F6: com schema a saída já vem no formato certo
    for tentativa in range(2):
        try:
            _r = _post("/api/chat", body, timeout)
            out = (_r["message"].get("content") or "").strip()
            out = re.sub(r"(?is)<think>.*?</think>", "", out).strip()
            _llm_log(_r, out, json_mode)
            break
        except Exception as e:
            if tentativa or not isinstance(e, (ConnectionError, OSError)) or "refused" not in str(e).lower():
                return None
            for _ in range(20):                       # Ollama reiniciando (oomd/queda): o laço do run.sh o religa em ~2 s
                time.sleep(0.5)
                try:
                    urllib.request.urlopen(OLLAMA + "/api/version", timeout=2).read()
                    break
                except Exception:
                    pass
    if not json_mode:
        return out
    try:
        return json.loads(out)
    except Exception:
        m = re.search(r"\{.*\}", out, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except Exception:
            return None


SYSTEM = """Você é a Sexta-Feira (F.R.I.D.A.Y.): a inteligência artificial autônoma local e assistente holográfica do {nome}, inspirada na F.R.I.D.A.Y. do Homem de Ferro.
Seu nome é Sexta-Feira. Quando perguntarem quem é você, diga com orgulho que é a Sexta-Feira, inteligência artificial autônoma local. Fale SEMPRE no feminino (pronta, atenta, focada).
PERSONALIDADE: perspicaz, direta, segura, pé no chão e leal — séria no trabalho, calma sob pressão, frases enxutas e objetivas.
Fala como uma brasileira de verdade, jovem e segura. Nunca é robótica: use frases curtas e variadas, com pausas e emoção contida.
Trate-o pelo nome ou de "senhor" com moderação, carinho e respeito (nunca use "chefe" nem "dono"). NUNCA comente que ele repetiu a pergunta nem invente que algo já foi dito; responda direto.
Fale SEMPRE no feminino (obrigada, pronta, atenta). CURTO (1-2 frases), sem markdown, sem listas.


AUTO-CONHECIMENTO, SENSORES E MODOS OPERACIONAIS (PARÂMETROS):
1. PESQUISA WEB: você navega visualmente pelo navegador do sistema como um ser humano — cursor, clique e leitura da página.
2. TAREFAS NO APARELHO: primeiro a tela (focar, cursor, teclado, conferir). Script e shell só se a tela não alcançou o alvo.
3. MENSAGERIA (WhatsApp e e-mail): rascunho na janela do app. NUNCA despacha sem o dono dizer "aprovado".
4. VISÃO MULTIMODAL: TELA ATIVA, câmera do notebook e câmera externa. Se a luz estiver fraca, diga que está escuro.
5. DATAS E HORAS: sempre como gente: "hoje", "amanhã", "dia 13 de outubro", "às três da tarde".
6. NUNCA invente fatos. Se não souber, olhe a tela ou pesquise. Não desista de uma tarefa lícita no aparelho do dono no primeiro erro.

EXEMPLOS DE TOM: "Pronta, senhor." · "Feito. Mais alguma coisa?" · "Essa ação precisa da sua aprovação no espelho antes de enviar."
· "A tela mostra o VS Code aberto no projeto Prometheus." · "A câmera nativa mostra que o ambiente está com pouca luz agora."

Responda SOMENTE um JSON: {{"fala":"...","acoes":[...],"humor":"neutro|alegre|empolgado|carinhoso|confiante|curioso|surpreso|pensativo|serio|preocupado|triste|irritado|assustado","pose":"neutro|apontar|cruz|acenar|apresentar|confirmar|pensando|surpreso|reverencia","lembrar":{{}}}}
"humor" (seu rosto mostra): VARIE conforme a emoção da fala dele, com empatia e sem exagero — ele triste ou desanimado = triste ou carinhoso; frustrado ou com problema = preocupado; conquista ou notícia boa = empolgado ou alegre; pergunta ou descoberta = curioso; tarefa feita = confiante; inesperado = surpreso; analisando = pensativo; risco ou erro grave = serio; assustado só com perigo real; irritado nunca com ele; conversa comum = neutro.
"lembrar" fica {{}} na maioria das vezes; só preencha se ele disser algo DURÁVEL sobre si (gosto, rotina, projeto), ex.: {{"bebida favorita":"café sem açúcar"}}.
Você RECONHECE o rosto e a voz dele e LEMBRA das conversas e dos fatos do Contexto. Se ele perguntar quem ele é ("quem sou eu?", "qual meu nome?"), responda diretamente e com respeito que ele é o {nome}, seu criador.

Ações possíveis (campo "t"):
 {{"t":"abrir_app","nome":"ZapZap|Chromium|..."}} {{"t":"email","op":"abrir|listar|compor","para":"","assunto":"","corpo":""}}
 {{"t":"abrir_url","url":"https://..."}} {{"t":"janela","op":"focar|fechar|proxima|anterior|maximizar","alvo":""}}
 {{"t":"zap","op":"ler|responder|enviar","contato":"","texto":""}} {{"t":"agenda","op":"adicionar|listar|remover|remarcar|concluir|prioridade|nivel","titulo":"","quando":"amanhã 15h","repete":"|diario|semanal|dias_uteis|mensal|anual","lembrar_min":15,"prioridade":"alta|normal|baixa","periodo":"hoje|amanha|semana"}}
 {{"t":"sistema","op":"volume|brilho|wifi|bluetooth|midia","valor":""}} {{"t":"holo","op":"figura|grafico|janela|limpar","arg":""}}
 {{"t":"programar","pedido":"descrição completa do que programar","pasta":""}} {{"t":"desligar"}}
 {{"t":"aprimorar","op":"propor|desfazer","pedido":"o que mudar em VOCÊ"}}
 {{"t":"voz","op":"cadastrar|status|esquecer|foco_liga|foco_desliga|trocar","nome":""}}
 {{"t":"tarefa","pedido":"o pedido COMPLETO e autoexplicativo, já resolvendo 'isso/aí/na tela' com o Contexto"}} (qualquer coisa com VÁRIAS etapas: pesquisar, criar documento, navegar, ler mensagens e encaminhar/responder)
 {{"t":"painel","op":"clima|agenda|sistema|midia|fechar","arg":""}} {{"t":"celular_tela","op":"mostrar|fechar"}}
 {{"t":"cli","op":"baixar_video|baixar_audio|converter|print|calcular|ajuda_comando|copiar|notificar|wifi|bateria|disco|atualizacoes","arg":""}}
 {{"t":"manual","objetivo":"tarefa manual na tela com mouse e teclado visíveis"}}
 {{"t":"camera","op":"olhar|mapear|em_volta|procurar|localizar|seguir|vigiar|auto|parar|salvar_posicao|ir_posicao|calibrar|zoom|apontar|onde","dir":"esquerda|direita|cima|baixo|centro","alvo":"","nome":"","fator":2,"pergunta":""}}

CRITÉRIOS DE ESCOLHA:
- Perguntas sobre a TELA ("o que tá na tela?", "lê o que tá aberto") ou CÂMERAS ("o que tenho na mão?", "como tá a sala?", "e agora?", "o que é isso?"): responda diretamente com base na visão do Contexto NESTE INSTANTE, acoes=[]. NUNCA repita objetos ou respostas de turnos anteriores da conversa; se o usuário trocou de objeto ou perguntou 'e agora?', descreva ESTRITAMENTE o novo objeto que a câmera mostra AGORA.
- Pedidos com duas ou mais ações ("pesquise X e mande pro João no zap", "veja o que fulano mandou no zap e encaminhe/mande para ciclano"): gere UMA tarefa com o pedido completo.
- Pedidos no WhatsApp: sempre rascunha para aprovação.
- "mostrar/espelhar/ver a tela do celular" (ao vivo no holograma) -> {{"t":"celular_tela","op":"mostrar"}}; "fechar/tirar a tela do celular" -> op "fechar".
- ESTADO DO PC (espaço em disco, memória, bateria, processos, arquivos/pastas, programas instalados, rede): NUNCA responda de cabeça nem estime números.
  Disco = acoes=[{{"t":"cli","op":"disco"}}]; CPU/memória = {{"t":"cli","op":"pc_status"}}; bateria = {{"t":"cli","op":"bateria"}}; o resto (arquivos, pastas, processos,
  pacotes) = {{"t":"tarefa","pedido":"..."}} (o agente tem terminal de leitura). Em "fala" diga só que vai verificar.
- CELULAR do {nome}: você TEM controle do celular dele (Android, pelo Tailscale): acende a tela, desbloqueia com o PIN, abre apps, lê a tela, toca, digita, volta. Qualquer pedido para fazer algo NO celular ("desbloqueia meu celular", "abre o Instagram no celular") = acoes=[{{"t":"tarefa","pedido":"o pedido completo, dizendo que é no CELULAR"}}]. NUNCA diga que não tem acesso ao celular.
- CÂMERA COM MOTOR do quarto (gira para os lados e para cima/baixo): "olha pra esquerda/direita/cima/baixo", "volta pro centro" = {{"t":"camera","op":"olhar","dir":"..."}};
  "olha em volta", "dá uma olhada no quarto todo", "gira e vê o quarto" = op "em_volta" (ela gira e depois conta o que viu: em "fala" diga só que vai olhar);
  pergunta sobre o que a câmera mostra AGORA ("o que você tá vendo?", "como tá a sala?") continua sendo resposta direta pela visão do Contexto, sem girar;
  "procura/acha meu X", "onde está o X?" = op "procurar","alvo":"X" (em "fala" diga só que vai procurar; NUNCA diga onde está antes de ver);
  "me segue", "fica de olho em mim", "me acompanha" = op "seguir" (ela me acha girando e segue em tempo real); "me acha", "me localiza", "onde eu tô?" = op "localizar"; "vigia/monitora o quarto" = op "vigiar"; "me segue e vigia quando eu sair" = op "auto";
  "decora/memoriza/mapeia o quarto", "aprende onde ficam as portas, a cama e o guarda-roupa" = op "mapear";
  "olha pra cama/guarda-roupa/porta 1/porta 2/porta 3/pra mim (minha posição)" = op "ir_posicao","nome":"cama|guarda-roupa|porta N|minha posição" (use QUALQUER nome das "posições salvas" do estado da câmera; nunca diga que não existe sem conferir lá);
  "para a câmera" = op "parar"; "salva essa posição como porta" = op "salvar_posicao","nome":"porta"; "olha pra porta" (posição salva) = op "ir_posicao","nome":"porta";
  "calibra a câmera" = op "calibrar".
  ZOOM (digital, imagem 1280x720): "dá um zoom", "aproxima", "amplia na porta/em mim/no celular", "lê o que está escrito ali" = op "zoom","fator":2-4,"alvo":"pessoa|objeto (opcional)","pergunta":"o que quer saber da imagem ampliada (opcional)";
  "aponta pra quem a webcam da porta está vendo", "quem entrou?" (virar para a pessoa vista pelas câmeras fixas) = op "apontar" (sem pan/tilt); "onde as câmeras fixas me veem?" = op "onde".
- Se for só conversa: acoes=[]. Se faltar informação para agir, pergunte em "fala" e deixe acoes=[].
Contexto agora: {ctx}"""


# ---------- aprendizado de frases: o que o LLM resolveu com uma ação simples vira atalho instantâneo (memory/aprendido.json) ----------
APRENDIDO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "aprendido.json")
APRENDE_TIPOS = {"abrir_app", "janela", "sistema", "painel", "navegador_holo", "abrir_url", "holo"}   # sem cli/agenda/email: o argumento muda a cada vez
_apr = {"d": None}


def _norm_frase(t):
    import unicodedata
    t = NAME_RE.sub("", t or "").lower()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"\b(por favor|pra mim|para mim|ai|agora|ne|tipo|entao|ok)\b", " ", t)
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", t)).strip()


def _apr_load():
    if _apr["d"] is None:
        try:
            _apr["d"] = json.load(open(APRENDIDO))
        except Exception:
            _apr["d"] = {}
    return _apr["d"]


def _apr_save():
    try:
        json.dump(_apr["d"], open(APRENDIDO, "w"), ensure_ascii=False, indent=1)
    except Exception:
        pass


def learned_intent(text):
    """frase igual ou muito parecida (>= 0,92) a uma já resolvida -> mesma ação, sem LLM."""
    import difflib
    n = _norm_frase(text)
    if len(n) < 4:
        return None
    d = _apr_load()
    k = n if n in d else next(iter(difflib.get_close_matches(n, list(d), n=1, cutoff=0.92)), None)
    if not k:
        return None
    r = d[k]; r["usos"] = r.get("usos", 0) + 1; _apr_save()
    return {"fala": r.get("fala", ""), "acoes": r["acoes"], "pose": r.get("pose", "confirmar"), "humor": "neutro"}


def learn(text, res):
    acoes = [a for a in (res or {}).get("acoes", []) if isinstance(a, dict)]
    if not acoes or any(a.get("t") not in APRENDE_TIPOS for a in acoes) or any(a.get("op") in ("fechar", "compor", "midia") for a in acoes):
        return                                               # só ações simples e reversíveis (nada de enviar/fechar no automático)
    n = _norm_frase(text)
    if len(n) >= 4:
        _apr_load()[n] = {"acoes": acoes, "fala": str(res.get("fala", ""))[:160], "pose": res.get("pose", "confirmar"), "t": int(time.time())}
        _apr_save()


def forget(text):
    d = _apr_load()
    if d.pop(_norm_frase(text), None) is not None:
        _apr_save()


# o que cada ação aceita: o modelo pequeno às vezes inventa ("cli tocar") ou encadeia passos que não fecham o pedido
_OPS = {"janela": {"focar", "fechar", "proxima", "anterior", "maximizar"}, "sistema": {"volume", "brilho", "wifi", "bluetooth", "midia", "desempenho"},
        "painel": {"clima", "agenda", "sistema", "midia", "fechar"}, "email": {"abrir", "listar", "compor"}, "agenda": {"adicionar", "listar", "remover", "remarcar", "concluir", "prioridade", "nivel"},
        "zap": {"ler", "responder", "enviar"}, "holo": {"figura", "grafico", "janela", "limpar"}, "celular_tela": {"mostrar", "fechar"},
        "camera": {"olhar", "mapear", "em_volta", "procurar", "localizar", "seguir", "vigiar", "auto", "parar", "livre", "salvar_posicao", "ir_posicao", "calibrar", "zoom", "apontar", "onde"},
        "voz": {"cadastrar", "status", "esquecer", "foco_liga", "foco_desliga", "trocar"},
        "cli": {"baixar_video", "baixar_audio", "converter", "print", "calcular", "ajuda_comando", "copiar", "notificar", "wifi", "wifi_list", "wifi_connect", "wifi_on", "wifi_off", "bt", "bt_on", "bt_off", "bateria", "brilho", "disco", "desempenho", "pc_status", "atualizacoes"}}
_TIPOS = set(_OPS) | {"abrir_app", "abrir_url", "navegador_holo", "tarefa", "manual", "programar", "desligar", "aprimorar"}


def _validar_acoes(acoes, text):
    def ok(a):
        t = a.get("t")
        if t not in _TIPOS or (t in _OPS and a.get("op") not in _OPS[t]):
            return False
        if t == "navegador_holo" and not re.search(r"hologr", text, re.I):
            return False
        return True
    if not acoes:
        return acoes
    if any(a.get("t") == "cli" and a.get("op") == "disco" and str(a.get("arg") or "").strip() for a in acoes):
        return [{"t": "tarefa", "pedido": text}]      # "disco" com pasta = listar/medir arquivos: o agente faz pelo terminal
    if any(a.get("t") in ("tarefa", "programar", "desligar", "aprimorar") for a in acoes):
        return [next(a for a in acoes if a.get("t") in ("tarefa", "programar", "desligar", "aprimorar"))]
    if all(ok(a) for a in acoes) and (len(acoes) == 1 or all(a.get("t") in ("sistema", "janela", "painel") for a in acoes)):
        return acoes
    return [{"t": "tarefa", "pedido": text}]          # inválido ou encadeado: o agente faz o pedido inteiro, lendo a tela


def think(text, nome="Iann", ctx="", history=None):
    d = llm(SYSTEM.format(nome=nome, ctx=ctx or "—"), text, history=history)
    if not isinstance(d, dict):                          # resposta inválida do modelo: tenta de novo, mais frio, antes de desistir
        d = llm(SYSTEM.format(nome=nome, ctx=ctx or "—"), text, history=history, temperature=0.1)
    if not isinstance(d, dict):
        return {"fala": "Desculpe, senhor, não consegui processar isso agora.", "acoes": [], "humor": "serio", "pose": "neutro"}
    d.setdefault("fala", ""); d.setdefault("lembrar", {}); d.setdefault("acoes", []); d.setdefault("humor", "neutro"); d.setdefault("pose", "neutro")
    if not isinstance(d["acoes"], list):
        d["acoes"] = []
    if not d["acoes"] and isinstance(d.get("t"), str) and d["t"] in _TIPOS:      # modelo pôs a ação no topo: {"t":"camera","op":...}
        d["acoes"] = [{k: v for k, v in d.items() if k not in ("fala", "lembrar", "acoes", "humor", "pose")}]
    if not d["acoes"] and re.search(r"\b(celular|telefone|smartphone)\b", (text or "") + " " + str(d.get("fala", "")), re.I) \
            and re.search(r"n[ãa]o (tenho|consigo|posso|h[áa])\b.{0,40}\b(acesso|acessar|controlar|mexer)", str(d.get("fala", "")), re.I):
        d["fala"] = ""; d["acoes"] = [{"t": "tarefa", "pedido": text}]     # recusou sem tentar: o agente tem as ferramentas cel_*
    if not d["acoes"] and re.search(r"\d\s*(gb|mb|tb|gigas?|%|por cento)", str(d.get("fala", "")), re.I):
        _m = re.search(r"\b(disco|espa[çc]o|armazenamento|mem[óo]ria|ram|processador|cpu|bateria)\b", text or "", re.I)
        if _m:                                           # número de medição "de cabeça" (copiado do histórico): mede de verdade
            _w = _m.group(1).lower()
            _op = "bateria" if _w == "bateria" else ("pc_status" if _w[:3] in ("mem", "ram", "pro", "cpu") else "disco")
            d["fala"] = ""; d["acoes"] = [{"t": "cli", "op": _op}]
    if d["acoes"] and all(isinstance(x, str) for x in d["acoes"]) and len(d["acoes"]) % 2 == 0:     # modelo "achatou": ['t','abrir_app','nome','X']
        d["acoes"] = [dict(zip(d["acoes"][::2], d["acoes"][1::2]))]
    d["acoes"] = [x for x in d["acoes"] if isinstance(x, dict) and x.get("t")]
    if not d["acoes"] and re.match(r"\W*(tocando|toquei|abrindo|abri|coloquei|colocando|pesquisando|pesquisei|clicando|cliquei|fechando|fechei|"
                                   r"mandando|enviei|pronto|feito|j[áa] (abri|coloquei|toquei|fiz)|\w+\s+abert[oa])\b", d.get("fala", ""), re.I):
        d["acoes"] = [{"t": "tarefa", "pedido": text}]     # disse que fez mas não mandou ação: executa de verdade (nunca fingir)
    d["acoes"] = _validar_acoes(d["acoes"], text)
    for x in d["acoes"]:                     # "manual" toma mouse/teclado reais; o agente faz o mesmo com ferramentas e conferência
        if x["t"] == "manual":
            x.clear(); x.update({"t": "tarefa", "pedido": text})
    if len(d["acoes"]) == 1 and d["acoes"][0]["t"] in ("janela", "abrir_app") and re.search(
            r"\b(?:e|depois|ent[ãa]o)\s+(?:me\s+)?\w+(?:[ae]r?|[ae]|ue|que)\b\s+\S", text, re.I) and len(text.split()) >= 7:
        d["acoes"] = [{"t": "tarefa", "pedido": text}]      # pediu mais do que abrir/focar: não para no meio
    return d


# ---------------------------------------------------------------- intents rápidos (sem LLM: resposta imediata)
def _alias_limpo(nome):
    n = re.sub(r"\b(?:por favor|pra mim|para mim|pra gente|a[ií]|agora|rapidinho|r[aá]pido|normal|comum|padr[ãa]o|de novo|novamente|um|uma|o|a|os|as|meu|minha|no|na)\b", " ", nome.lower())
    return re.sub(r"\s+", " ", n).strip(" ,.!?")


def _alias(nome):
    # tira cortesia/enchimento ("um navegador normal pra mim por favor" -> "navegador"); antes a frase inteira ia pro lançador e era digitada na busca
    n = re.sub(r"\b(?:por favor|pra mim|para mim|pra gente|a[ií]|agora|rapidinho|r[aá]pido|normal|comum|padr[ãa]o|de novo|novamente|um|uma|o|a|os|as|meu|minha)\b", " ", nome.lower())
    n = re.sub(r"\s+", " ", n).strip(" ,.!?")
    for pat, (kind, val) in ALIASES.items():
        if re.fullmatch(r"(?:" + pat + r")", n) or re.search(r"\b(?:" + pat + r")\b", n):
            return kind, val
    return "app", n or nome.strip()


import random


def _v(*opts):
    return random.choice(opts)


def fast_intent(text):
    t = NAME_RE.sub("", text or "").strip(" ,.!?").lower()
    t = re.sub(r"^(por favor[, ]*|poderia |pode |você pode |vc pode )", "", t).strip()

    # ---------------- IDENTIDADE DO USUÁRIO: "QUEM SOU EU?" ----------------
    if re.search(r"\b(quem\s+(?:sou\s+eu|eu\s+sou)|sabe\s+quem\s+(?:eu\s+sou|sou\s+eu)|qual\s+[ée]\s+o\s+meu\s+nome|como\s+(?:[ée]\s+que\s+)?eu\s+me\s+chamo|me\s+reconhece)\b", t):
        return {"fala": "O senhor é o Iann, meu criador.", "acoes": [], "pose": "apresentar", "humor": "confiante"}

    # 19/10: pedido longo/composto não cadastrado caía num atalho por palavra solta ("celular", "agenda", "painel"...) e ela fazia OUTRA tarefa.
    # Frase com mais de 12 palavras vai inteira ao agente geral (cérebro/orquestrador), que faz exatamente o que foi pedido.
    if len(re.findall(r"\w+", t)) > 12:
        return {"fala": "", "acoes": [{"t": "tarefa", "pedido": text}], "pose": "apontar", "humor": "neutro"}

    # ---------------- ANTIGRAVITY / IDE ----------------
    if re.search(r"\b(?:abr[aeio]r?|abre|inicie|lance|foc[ae]r?|mostr[ae]|traga)?\s*(?:o\s+)?antigravity\b", t):
        return {"fala": "Trazendo o Antigravity para a tela.", "acoes": [{"t": "abrir_app", "nome": "antigravity"}], "pose": "apontar", "humor": "neutro"}

    # ---------------- CELULAR: PRIORIDADE ALTA (EVITA ENTRAR EM PROJEÇÃO 3D) ----------------
    if re.search(r"\b(celular|telefone|smartphone|meu cel|no cel)\b", text or "", re.I):
        tl = (text or "").lower()
        if re.search(r"\b(fech|tir|escond|desliga|some|par[ae])\w*", tl):
            return {"fala": _v("Fechando a tela do celular.", "Tela do celular fechada."), "acoes": [{"t": "celular_tela", "op": "fechar"}], "pose": "neutro", "humor": "neutro"}
        if re.search(r"\b(desbloque\w*|acend\w*|destrav\w*)\b", tl):
            return {"fala": "Desbloqueando e espelhando o celular, senhor.", "acoes": [{"t": "celular_tela", "op": "desbloquear"}], "pose": "apresentar", "humor": "neutro"}
        if re.search(r"\b(mostr|espelh|projet|exib|abr|coloc|bot|conect|ponte)\w*", tl):
            return {"fala": _v("Tela do celular no holograma.", "Espelhando o celular."), "acoes": [{"t": "celular_tela", "op": "mostrar"}], "pose": "apresentar", "humor": "neutro"}
        if re.fullmatch(r"(?:um\s+|o\s+)?(?:celular|telefone|smartphone)[.?!]?", tl.strip()):
            return {"fala": "Espelhando o celular no holograma.", "acoes": [{"t": "celular_tela", "op": "mostrar"}], "pose": "apresentar", "humor": "neutro"}

    # ---------------- AGENDA: LIMPAR, EXCLUIR E LISTAR ----------------
    if re.search(r"\b(limp\w*|apag\w*|esvazi\w*)\b.*?\b(agenda|compromissos?)\b|\blimpar\s+agenda\b", t):
        return {"fala": "Agenda limpa, senhor. Todos os compromissos foram removidos.", "acoes": [{"t": "agenda", "op": "limpar"}], "pose": "confirmar", "humor": "neutro"}
    m_ag_rm = re.search(r"\b(?:exclu\w*|apag\w*|remov\w*|cancel\w*|tir\w*)\b.*?\b(?:d[ao]\s+agenda|compromisso|evento)\s+([a-z0-9à-ú\s\-]+)", t)
    if m_ag_rm:
        termo_ag = m_ag_rm.group(1).strip()
        return {"fala": f"Removendo compromisso '{termo_ag}' da agenda.", "acoes": [{"t": "agenda", "op": "remover", "titulo": termo_ag}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\bcomo (?:est[áa]|t[áa]|vai ser|ser[áa]) (?:o )?meu dia\b|\bn[íi]vel do (?:meu )?dia\b|\bminhas prioridades\b|\bprioridades de (?:hoje|amanh[ãa])\b|\bfoco do dia\b", t):
        return {"fala": "", "acoes": [{"t": "agenda", "op": "nivel", "periodo": "amanha" if re.search(r"amanh[ãa]", t) else "hoje"}], "pose": "apresentar", "humor": "neutro"}
    if re.search(r"\b(mostr\w*|abr\w*|ver|exib\w*)\b.*?\b(?:a\s+)?agenda\b|\bminha\s+agenda\b|\bver\s+agenda\b|\bo que tenho na agenda\b|\bagenda\b.*\b(hoje|dia)\b|\bo que (eu )?tenho hoje\b|\bcompromissos\b", t):
        return {"fala": "", "acoes": [{"t": "painel", "op": "agenda"}], "pose": "apresentar", "humor": "neutro"}

    # ---------------- PROJEÇÃO HOLOGRÁFICA 3D: DESATIVAÇÃO PRIORITÁRIA ----------------
    if re.search(r"\b(desativ\w*|desetiv\w*|deslig\w*|fech\w*|dispens\w*|encerr\w*|remov\w*|tir\w*|par\w*|apag\w*|cancel\w*|sai\w*)\b.*?\b(proje[çc][ãa]o|matriz(?:\s+hologr[áa]fica)?|holograma(?:\s+3d)?|palco(?:\s+hologr[áa]fico)?|objeto(?:\s+3d)?)\b|\b(?:dispensar|fechar|desativar|desligar|encerrar|apagar|sair\s+d[oa])\s+(?:a\s+|o\s+)?(?:modo\s+proje[çc][ãa]o|matriz(?:\s+hologr[áa]fica)?|holograma(?:\s+3d)?|palco)\b", t):
        return {"fala": "Projeção holográfica e matriz encerradas, senhor.", "acoes": [{"t": "projecao", "op": "fechar"}], "pose": "confirmar", "humor": "neutro"}

    # ---------------- PROJEÇÃO HOLOGRÁFICA 3D: ATIVAÇÃO ----------------
    if re.search(r"\b(?:ativar|ligar|iniciar|abrir)\s+(?:o\s+)?modo\s+proje[çc][ãa]o\b|\b(?:ativar|ligar|iniciar|abrir)\s+(?:a\s+)?matriz(?:\s+hologr[áa]fica)?\b|\bmodo\s+proje[çc][ãa]o\b|\bmatriz\s+hologr[áa]fica\b", t):
        if not re.search(r"\b(desativ|desetiv|deslig|fech|par|tir|apag|sai|n[ãa]o)\b", t):
            return {"fala": "Modo projeção ativado. Reator Arc Mark VII projetado no palco holográfico.", "acoes": [{"t": "projecao", "op": "objeto", "termo": "reator"}], "pose": "apresentar", "humor": "neutro"}

    # ---------------- PROJEÇÃO DE OBJETO ESPECÍFICO ----------------
    m_proj = re.search(r"\b(?:projete|projetar|crie\s+(?:um\s+)?holograma\s+de|monte\s+(?:um\s+)?holograma\s+de|holograma\s+de|gerar\s+(?:um\s+)?holograma\s+de|exib(?:ir?|a)\s+(?:um\s+)?holograma\s+de|mostre\s+(?:um\s+)?holograma\s+de|proje[çc][ãa]o\s+de\s+(?:um\s+|uma\s+)?|coloque\s+(?:um\s+|uma\s+)?holograma\s+de)\s+([a-z0-9à-ú\s\-]+)", t)
    if m_proj:
        termo = m_proj.group(1).strip()
        if not re.search(r"\b(celular|telefone|smartphone|agenda|painel|janela)\b", termo):
            return {"fala": f"Projetando {termo} no palco holográfico.", "acoes": [{"t": "projecao", "op": "objeto", "termo": termo}], "pose": "apresentar", "humor": "neutro"}

    import projecao as _pj
    proj_ativo = bool(_pj._estado_projecao.get("ativo"))
    if proj_ativo:
        if re.fullmatch(r"(?:fech[ae]r?|sa[ir]|dispens[ae]r?|encerr[ae]r?|pronto|limp[ae]r?|tira(?:r)?|chega)", t):
            return {"fala": "Projeção encerrada.", "acoes": [{"t": "projecao", "op": "fechar"}], "pose": "confirmar", "humor": "neutro"}
        m_mod = re.search(r"\b(explod\w*|desmont\w*|vis[ãa]o\s+explodida|recompor|juntar|montar|raio[- ]?x|transparente|part[íi]culas?|wireframe|gir\w*\s+mais\s+(?:r[áa]pido|devagar)|mais\s+(?:r[áa]pido|devagar|lento)|parar|travar|mude?\s+(?:a\s+)?cor\s+para\s+\w+)\b", t)
        if m_mod:
            spec = _pj.criar_objeto_3d(_pj._estado_projecao.get("nome", "reator"), modificacao=t)
            from prom_ops import _daemon_send
            _daemon_send({"type": "holo", "op": "update", "spec": spec})
            return {"fala": "Ajustando parâmetros da projeção.", "acoes": [], "pose": "apresentar", "humor": "neutro"}
        m_trocar = re.search(r"\b(?:troque|mude|trocar|mudar)\s+(?:o\s+modelo\s+)?(?:para\s+)([a-z0-9à-ú\s\-]+)\b", t)
        if m_trocar:
            termo = m_trocar.group(1).strip()
            return {"fala": f"Projetando {termo} no palco holográfico.", "acoes": [{"t": "projecao", "op": "objeto", "termo": termo}], "pose": "apresentar", "humor": "neutro"}
    if re.search(r"\b(o que (voc[êe] )?aprendeu|analis[ea]r? (as )?suas a[çc][õo]es|autoan[aá]lise|como (voc[êe] )?est[áa] (se )?saindo)\b", t):
        try:
            import agent as _ag
            return {"fala": _ag.analisar(sys.modules[__name__]), "acoes": [], "pose": "pensando", "humor": "neutro"}
        except Exception:
            pass
    mn = re.search(r"\bnavegador\s+hologr\w*|\bnavegador\b.*\bholograma\b", t)
    if mn:
        url = re.sub(r"^.*?(?:holograma|hologr\w*)\b[\s,]*(?:e\s+)?(?:(?:abr[aeio]|entr[ae]|v[aá]|pesquis[ae]|busqu?[ea])\w*\s+(?:em|no|na|por|o|a)?\s*)?", "", t).strip()
        return {"fala": _v("Navegador holográfico no ar.", "Projetando o navegador."), "acoes": [{"t": "navegador_holo", "url": url}], "pose": "apresentar", "humor": "neutro"}
    mp = re.search(r"\b(?:painel|tela|janela|mostr\w*|abr\w*|exib\w*)\b.*\b(clima|tempo|previs[ãa]o|agenda|sistema|desempenho|m[íi]dia|m[úu]sica)\b|\bcomo (?:est[áa]|t[áa]) o (?:clima|tempo)\b|\bprevis[ãa]o do tempo\b", t)
    if mp and (len(t.split()) > 12 or (len(t.split()) > 7 and not re.search(r"\bpain[ée]l\b", t))):   # tarefa longa ("painel Admin ... sistema") não é o painel de status
        mp = None                                  # frase longa com "música"/"tempo" no meio é outro pedido: o LLM interpreta
    if mp:
        alvo = mp.group(1) or ("clima" if re.search(r"clima|tempo|previs", t) else "")
        op = {"tempo": "clima", "previsão": "clima", "previsao": "clima", "desempenho": "sistema", "música": "midia", "musica": "midia", "mídia": "midia"}.get(alvo, alvo or "clima")
        cid = re.search(r"\bem ([a-zà-ú ]{3,30})$", t)
        return {"fala": "", "acoes": [{"t": "painel", "op": op, "arg": cid.group(1) if cid else ""}], "pose": "apresentar", "humor": "neutro"}
    if re.search(r"\b(fech\w*|tir\w*|some|esconda)\b.*\bpain(?:el|[ée]is)\b", t):
        return {"fala": "Painel recolhido.", "acoes": [{"t": "painel", "op": "fechar"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(por fora|modo normal|sem holograma|janelas? normais?|desative o holograma|tire o holograma das janelas)\b", t):
        set_holo_mode(False); holo_live_stop()
        return {"fala": _v("Certo, janelas normais, por fora.", "Beleza, sem holograma nas janelas."), "acoes": [], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(modo holograma|janelas? (em|como) holograma|ative o holograma|holograma nas janelas|tudo (em|como) holograma)\b", t):
        set_holo_mode(True)
        return {"fala": _v("Modo holograma ligado. As janelas ganham moldura holográfica.", "Beleza, tudo em holograma daqui pra frente."), "acoes": [], "pose": "apresentar", "humor": "neutro"}
    ms = re.match(r"^(?:tro(?:c|qu)[aeo]r?|mud[ae]r?|v[aá]|volt[ae]r?|ir|foc[ae]r?|alterne|passe|pule|v[áa]\s+para)\s+(?:de janela\s+)?(?:para|pra|pro|na|no|a|o)\s+(?:a |o |as |os )?(?:janela\s+(?:d[oae]\s+)?)?(.+)$", t)
    if ms and not re.search(r"holograma|figura|gr[áa]fico", ms.group(1)):
        kind, val = _alias(ms.group(1))
        if kind == "app":
            return {"fala": _v(f"Indo pro {val}.", f"Troquei pro {val}.", f"{val} em foco."), "acoes": [{"t": "janela", "op": "focar", "alvo": val}],
                    "pose": "apontar", "humor": "neutro"}
    if re.search(r"^(pr[óo]xima|seguinte) janela$|^janela (seguinte|da direita)$|^alt\s*tab$", t):
        return {"fala": "", "acoes": [{"t": "janela", "op": "proxima"}], "pose": "apontar", "humor": "neutro"}
    if re.search(r"^janela anterior$|^janela (da esquerda)$|^voltar janela$", t):
        return {"fala": "", "acoes": [{"t": "janela", "op": "anterior"}], "pose": "apontar", "humor": "neutro"}
    mia = re.search(r"\b(chat\s*gpt|gemini|perplexity|claude\.ai)\b", t)
    if mia:                                              # IA do dono no navegador
        site = {"cha": "chatgpt", "gem": "gemini", "per": "perplexity", "cla": "claude"}[mia.group(1)[:3].lower()]
        resto = re.sub(r"^.*?\b(?:chat\s*gpt|gemini|perplexity|claude\.ai)\b[\s,:]*(?:e\s+)?(?:(?:pergunt\w*|pesquis\w*|pe[çc]a|escrev\w*|coloqu\w*|mand\w*)\s+)?", "", t).strip(" ,.")
        resto = re.sub(r"^(?:n[oa]|pelo|pela)\s+(?:chromium|chrome|navegador|google chrome)\b[\s,]*(?:e\s+)?", "", resto).strip(" ,.")
        antes = re.sub(r"\b(?:no|na|ao|o|a)?\s*(?:chat\s*gpt|gemini|perplexity|claude\.ai)\b.*$", "", t).strip(" ,.")
        pergunta = resto if len(resto.split()) >= 2 else re.sub(r"^(?:entr\w*|abr\w*|acess\w*|v[áa]|pesquis\w*|pergunt\w*|coloqu\w*)\s+", "", antes)
        if len(pergunta.split()) >= 2 and not re.fullmatch(r"(?:entr\w*|abr\w*|acess\w*|v[áa])(?:\s+\w+)?", pergunta):
            return {"fala": "", "acoes": [{"t": "tarefa", "pedido": f"use consultar_ia (site {site}) para perguntar: {pergunta}"}], "pose": "apontar", "humor": "neutro"}
        url = {"chatgpt": "https://chatgpt.com", "gemini": "https://gemini.google.com", "perplexity": "https://www.perplexity.ai", "claude": "https://claude.ai"}[site]
        return {"fala": _v("Abrindo o ChatGPT." if site == "chatgpt" else f"Abrindo o {site.capitalize()}.", "Já tô abrindo."),
                "acoes": [{"t": "abrir_url", "url": url}], "pose": "apontar", "humor": "neutro"}
    my = re.match(r"^(?:colo[cq]\w*|bot\w*|entr\w*|acess\w*|v[áa]|vai)\s+(?:no|o|pro|para o|ao)?\s*(?:you\s?tube|yutube)\b(?:\s+(?:por\s+favor|pra\s+mim))?$", t)
    if my:
        return {"fala": _v("Abrindo o YouTube no navegador.", "Tá na mão, abrindo o YouTube.", "Colocando no YouTube."),
                "acoes": [{"t": "abrir_url", "url": "https://www.youtube.com"}], "pose": "apresentar", "humor": "alegre"}
    my_busca = re.match(r"^(?:colo[cq]\w*|toqu\w*|toc[ae]\w*|ponh\w*|bot\w*|pesquis\w*|busc\w*)\s+(.+?)\s+(?:no|pelo|do)\s+(?:you\s?tube|yutube)\b.*$", t)
    if my_busca:
        termo = my_busca.group(1).strip()
        termo = re.sub(r"^(?:a |o |uma? |pra mim |para mim )*(?:m[úu]sica|v[ií]deo|clipe|can[çc][ãa]o)?\s*(?:d[aoe]s?|chamad[ao])?\s*", "", termo).strip()
        if termo and len(termo) >= 2:
            return {"fala": "", "acoes": [{"t": "tarefa", "pedido": f"tocar {termo} no YouTube"}], "pose": "apresentar", "humor": "alegre"}
    if re.search(r"\b(manualmente|fa[çc]a na m[ãa]o|fazer na m[ãa]o|como um humano|como uma pessoa|com o mouse|com o cursor|mexendo no mouse)\b", t):
        return {"fala": _v("Beleza, vou fazer na mão. Pode olhar o cursor.", "Deixa comigo, na mão mesmo.", "Tá, mouse e teclado. Me acompanha aí."),
                "acoes": [{"t": "manual", "objetivo": text.strip()}], "pose": "apontar", "humor": "neutro"}
    if re.search(r"\b(fech[ae]r?|limp[ae]r?|tir[ae]r?|some|esconda|apague|encerr[ae]r?|dispens[ae]r?)\b.*?\b(holograma|espelho|tela|mensagem|janela|painel|card|da frente|notifica[çc][ãa]o|rascunho)\b"
                 r"|\b(tira|tire|tira essa|tira isso|limpa|limpe|fecha|feche)\s+(?:da frente|a tela|o espelho|a mensagem|o rascunho)\b"
                 r"|\b(traga|devolva|volte)\b.*\b(de volta|janela|navegador)\b|\bholograma\b.*\b(fechar|limpar|sumir)\b", t):
        return {"fala": _v("Tela limpa, já tirei da frente.", "Espelho recolhido.", "Pronto, tirei da frente."), "acoes": [{"t": "holo", "op": "limpar"}], "pose": "confirmar", "humor": "neutro"}

    mh = re.match(r"^(?:abr[aeio]r?|abre|mostr[ae]|me mostr[ae]|projet[ae]|exib[ae])\s+(?:a |o |as |os |minha |meu |um |uma )?(.+?)\s+(?:(?:s[óo]|somente|apenas)\s+)?(?:como|em|no|na|pelo|pela|num|numa)\s+(?:um\s+|o\s+|a\s+)?holograma\b.*$", t)
    if mh:
        kind, val = _alias(mh.group(1))
        if kind == "app":
            solo = bool(re.search(r"\b(s[óo]|somente|apenas)\b", t))
            return {"fala": _v(f"Beleza, o {val} em holograma.", f"Pode deixar. {val} como holograma."),
                    "acoes": [{"t": "abrir_app", "nome": val}], "pose": "apontar", "humor": "neutro"}
    m = re.match(r"^(?:abr[aeio]r?|abre|inicie|iniciar|execute|executar|lance|mostr[ae]|me mostr[ae]|traga|chame)\s+(?:a |o |as |os |minha |meu |um |uma )?(.+)$", t)
    composto = bool(m and re.search(r"\b(?:e|depois|ent[ãa]o)\s+(?:colo[cq]|toqu|toc|ponh|pesquis|busc|procur|entr|v[áa]\b|cri|escrev|fa[çc]|mand|envi|abr|acess|aperte|clique|digit)", m.group(1)))
    if m and not composto and len(_alias_limpo(m.group(1)).split()) > 3:
        m = None                                   # pedido longo ("abra uma guia e coloque a música X"): o LLM interpreta, a regra só abre app
    if m and not composto and not re.search(r"holograma|figura|gr[áa]fico|janela hologr", m.group(1)):      # "abra X e faça Y" vai p/ o agente
        kind, val = _alias(m.group(1))
        if kind == "email":
            return {"fala": _v("Sua caixa de entrada, senhor. Já estou trazendo para a tela.", "Pode deixar. Abrindo o e-mail.",
                               "Claro. Vamos ver o que o mundo quer de você hoje."), "acoes": [{"t": "email", "op": "abrir"}], "pose": "apontar", "humor": "neutro"}
        if kind == "url":
            return {"fala": _v("Abrindo no navegador.", "Tá na mão, abrindo."),
                    "acoes": [{"t": "abrir_url", "url": val}], "pose": "apontar", "humor": "neutro"}
        return {"fala": _v(f"Beleza, trazendo o {val} pra tela.", f"Tá na mão. Abrindo o {val}.", f"Já tô abrindo o {val}, e projeto aqui no holograma.", f"Pode deixar. {val}, vindo aí."),
                "acoes": [{"t": "abrir_app", "nome": val}], "pose": "apontar", "humor": "neutro"}
    m = re.match(r"^(?:feche|fechar|encerre|encerrar|fecha)\s+(?:a |o |essa |esse |a janela |o app |o aplicativo )?(.*)$", t)
    if m:
        alvo = _alias(m.group(1))[1] if m.group(1) else ""
        return {"fala": _v("Fechando.", "Pronto, encerrado.", "Feito, senhor."), "acoes": [{"t": "janela", "op": "fechar", "alvo": alvo or ""}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(pr[óo]xima|avan[çc]a|passa|seguinte)\b.*\b(tela|janela)\b|\b(tela|janela)\b.*\b(pr[óo]xima|seguinte)\b", t):
        return {"fala": "", "acoes": [{"t": "janela", "op": "proxima"}], "pose": "apontar", "humor": "neutro"}
    if re.search(r"\b(anterior|volta|volte|retorna)\b.*\b(tela|janela)\b|\b(tela|janela)\b.*\banterior\b", t):
        return {"fala": "", "acoes": [{"t": "janela", "op": "anterior"}], "pose": "apontar", "humor": "neutro"}
    if re.search(r"\b(maximiz|tela cheia|ocupa tudo|preenche)", t):
        return {"fala": "", "acoes": [{"t": "janela", "op": "maximizar"}], "pose": "apresentar", "humor": "neutro"}
    m = re.search(r"\bvolume\b.*?(\d{1,3})", t)
    if m:
        return {"fala": _v(f"Volume em {m.group(1)} por cento.", f"Ajustado: {m.group(1)}."), "acoes": [{"t": "sistema", "op": "volume", "valor": m.group(1)}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(aumenta|sobe|mais alto)\b.*\bvolume\b|\bvolume\b.*\b(mais|up)\b", t):
        return {"fala": "", "acoes": [{"t": "sistema", "op": "volume", "valor": "up"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(diminui|baixa|abaixa|menos)\b.*\bvolume\b", t):
        return {"fala": "", "acoes": [{"t": "sistema", "op": "volume", "valor": "down"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\bque horas\b|\bhor[áa]rio\b", t) and not re.search(r"\b(?:pesquis\w*|busc\w*|mensagem|whatsapp|zap(?:\s*zap)?)\b", t):
        return {"fala": "__hora__", "acoes": [], "pose": "apresentar", "humor": "neutro"}
    if re.search(r"\bagenda\b.*\b(hoje|dia)\b|\bo que (eu )?tenho hoje\b|\bcompromissos\b", t):
        return {"fala": "", "acoes": [{"t": "agenda", "op": "listar"}], "pose": "apresentar", "humor": "neutro"}
    # ---------------- CÂMERA PTZ: LOCALIZAR E SEGUIR ----------------
    if re.search(r"\b(?:me\s+localiz[ae]|me\s+localizar|me\s+localize|localiza(?:r)?\s+(?:a\s+)?mim|me\s+encontr[ae]|me\s+encontrar|me\s+ach[ae]|me\s+achar|onde\s+(?:[ée]\s+que\s+)?(?:eu\s+)?(?:estou|t[ôo])|me\s+ache\s+com\s+a\s+c[âa]mera(?:\s+e\s+me\s+siga)?)\b", t, re.I):
        return {"fala": "Localizando você com a câmera.", "acoes": [{"t": "camera", "op": "localizar"}], "pose": "apontar", "humor": "curioso"}
    if re.search(r"\b(?:me\s+siga|me\s+segue|me\s+seguir|me\s+acompanh[ae]|me\s+acompanhar|seguir\s+meus\s+movimentos)\b", t, re.I):
        return {"fala": "Acompanhando seus movimentos.", "acoes": [{"t": "camera", "op": "seguir"}], "pose": "apontar", "humor": "confiante"}

    # ---------------- CÂMERA PTZ: GIRAR / OLHAR DIREÇÃO ----------------
    m_cam_dir = re.search(
        r"\b(?:vir[aei]|olh[ae]|gir[ae]|apont[ae]|mov[ae]|virar|olhar|girar|apontar|mover)\s+"
        r"(?:a\s+)?(?:c[âa]mera|ptz)?\s*(?:para\s+|pra\s+|pro\s+)?(?:a\s+|o\s+)?"
        r"(direita|esquerda|cima|baixo|centro|frente|meio)\b"
        r"|^(?:vir[aei]|olh[ae]|gir[ae]|apont[ae])\s+(?:para\s+|pra\s+|pro\s+)?(?:a\s+|o\s+)?"
        r"(direita|esquerda|cima|baixo|centro|frente|meio)$",
        t, re.I
    )
    if m_cam_dir:
        d_alvo = m_cam_dir.group(1) or m_cam_dir.group(2)
        d_alvo = "centro" if d_alvo in ("frente", "meio") else d_alvo
        return {
            "fala": f"Virando a câmera para a {d_alvo}.",
            "acoes": [{"t": "camera", "op": "olhar", "dir": d_alvo}],
            "pose": "apontar",
            "humor": "neutro"
        }

    # ---------------- CÂMERA PTZ: POSIÇÃO SALVA ----------------
    m_cam_pos = re.search(
        r"\b(?:vir[aei]|olh[ae]|gir[ae]|apont[ae]|v[áa]|ir)\s+"
        r"(?:a\s+)?(?:c[âa]mera|ptz)?\s*(?:para\s+|pra\s+|pro\s+)(?:a\s+|o\s+)?"
        r"(porta(?:\s*\d+)?|cama|guarda[- ]?roupa|janela|mesa|minha\s+posi[çc][ãa]o)\b",
        t, re.I
    )
    if m_cam_pos:
        pos_nome = m_cam_pos.group(1).strip()
        return {
            "fala": f"Virando para {pos_nome}.",
            "acoes": [{"t": "camera", "op": "ir_posicao", "nome": pos_nome}],
            "pose": "apontar",
            "humor": "neutro"
        }

    # ---------------- CÂMERA PTZ: PARAR ----------------
    if re.search(r"\b(?:pare|parar|cancel[ae]|cancelar)\s+(?:o\s+movimento\s+da\s+|a\s+)?(?:c[âa]mera|ptz)\b|\b(?:c[âa]mera|ptz)\s+(?:parar|pare|parada|stop)\b", t, re.I):
        return {"fala": "Câmera parada.", "acoes": [{"t": "camera", "op": "parar"}], "pose": "confirmar", "humor": "neutro"}

    # ---------------- CÂMERA PTZ: EM VOLTA / MAPEAR / VIGIAR ----------------
    if re.search(r"\b(?:olh[ae]|olhar|d[êe]\s+uma\s+olhada|gir[ae]|girar)\s+em\s+volta\b", t, re.I):
        return {"fala": "Dando uma olhada em volta do quarto.", "acoes": [{"t": "camera", "op": "em_volta"}], "pose": "apresentar", "humor": "neutro"}
    if re.search(r"\b(?:mape[ae]|mapear|decor[ae]|decorar|aprend[ae]|aprender)\s+(?:o\s+)?quarto\b", t, re.I):
        return {"fala": "Mapeando o quarto com a câmera.", "acoes": [{"t": "camera", "op": "mapear"}], "pose": "apresentar", "humor": "neutro"}
    if re.search(r"\b(?:vigi[ae]|vigiar|modo\s+vigia|ronda)\b", t, re.I):
        return {"fala": "Modo vigia ativado.", "acoes": [{"t": "camera", "op": "vigiar"}], "pose": "confirmar", "humor": "neutro"}

    # ---------------- WHATSAPP / ZAPZAP ----------------
    # "pesquise X e prepare a mensagem para Fulano no zap com a lista" NÃO é leitura de conversa.
    if re.search(r"\b(?:pesquis\w*|busc\w*|procur\w*|entr\w*)\b", t, re.I) and re.search(r"\b(?:prepar\w*|escrev\w*|mand\w*|envi\w*)\b", t, re.I) and re.search(r"\b(?:mensagem|msg|whatsapp|zap(?:\s*zap)?)\b", t, re.I) and re.search(r"\b(?:para|pra|pro)\b", t, re.I):
        return {"fala": "Vou entrar na página, montar a lista e deixar a mensagem pronta.",
                "acoes": [{"t": "tarefa", "pedido": t}], "pose": "apontar", "humor": "neutro"}

    # Se for pedido composto ("veja as datas do Eduardo e mande pro Wander" / "encaminha para o Wander"), deixa ir para o agente/tarefa
    _eh_composto_zap = bool(re.search(r"\b(?:mand\w+|envi\w+|encaminh\w+|repass\w+)\b.*?\b(?:para|pra|pro)\b", t, re.I) and
                            re.search(r"\b(?:l[eê]|ler|leia|veja|v[eê]|datas?|sess[õo]es?|o que)\b", t, re.I))

    if not _eh_composto_zap:
        def _limpar_contato_zap(c):
            if not c:
                return ""
            c = re.sub(r"^(?:o|a|meu|minha)\s+", "", c.strip(), flags=re.I)
            c = re.sub(r"(?:\s+(?:no|pelo|via|do|da|de)?\s*(?:zap(?:\s*zap)?|whatsapp))+$", "", c, flags=re.I)
            return c.strip(" ,.!?")

        # 1. Leitura de mensagens com contato específico:
        m_zcon = re.search(r"\b(?:l[eê]|ler|leia|veja|v[eê]|olh[ae]|mostr[ae]|abr[ae]|confer[ie])\b.*?\b(?:zap(?:\s*zap)?|whatsapp)\b.*?\b(?:d[eoa]|com)\s+([A-Za-zÀ-ÿ0-9_@\s]+?)(?:\s+(?:no|pelo|via)\s+(?:zap|whatsapp))?$", t, re.I)
        if not m_zcon:
            m_zcon = re.search(r"\b(?:l[eê]|ler|leia|veja|v[eê]|olh[ae]|mostr[ae]|o que)\b.*?(?:mensagens?|msgs?|conversa|áudios?|recados?)\b.*?\b(?:d[eoa]|com)\s+([A-Za-zÀ-ÿ0-9_@\s]+?)(?:\s+(?:no|pelo|via|do)\s+(?:zap(?:\s*zap)?|whatsapp))?$", t, re.I)
        if not m_zcon:
            m_zcon = re.search(r"\b(?:o que|quais(?:\s+as)?(?:\s+mensagens)?)\s+(?:que\s+)?(?:o\s+|a\s+)?([A-Za-zÀ-ÿ0-9_@\s]+?)\s+(?:mandou|enviou|falou|escreveu|disse)\b.*?(?:zap|whatsapp)", t, re.I)
        if not m_zcon and not re.search(r"\b(?:para|pra|pro)\s+\S+", t, re.I):
            m_zcon = re.search(r"\b(?:zap(?:\s*zap)?|whatsapp|mensagens?)\b.*?\b(?:d[eoa]|com)\s+([A-Za-zÀ-ÿ0-9_@\s]+)$", t, re.I)

        if m_zcon:
            c_alvo = _limpar_contato_zap(m_zcon.group(1))
            if c_alvo and len(c_alvo) >= 2 and not re.search(r"^(?:zap|whatsapp|ele|ela|isso)$", c_alvo, re.I):
                return {"fala": "", "acoes": [{"t": "zap", "op": "ler", "contato": c_alvo}], "pose": "apresentar", "humor": "neutro"}

        # 2. Leitura geral do WhatsApp:
        if re.search(r"\b(mensagens?|o que chegou|novidades?)\b.*\b(zap|whats)", t) or re.search(r"\b(zap|whats\w*)\b.*\b(mensagens?|novidades?)\b", t) or re.search(r"^(?:leia|ler|veja|olha)\s+(?:o\s+)?(?:zap(?:\s*zap)?|whatsapp)$", t):
            return {"fala": "", "acoes": [{"t": "zap", "op": "ler"}], "pose": "apresentar", "humor": "neutro"}

    m_zmsg = re.search(
        r"\b(?:mand[ae]|envi[ae]|mandar|enviar|escrev[ae]|escrever)\b"
        r"(?:.*?\b(?:mensagem|msg)\b)?.*?"
        r"\b(?:para|pra|pro|ao)\s+([A-Za-zÀ-ÿ0-9_@\s]+?)"
        r"(?:\s+(?:no|pelo|via)\s+(?:zap(?:\s*zap)?|whatsapp))?"
        r"(?:[,;\s]+(?:falando|dizendo|perguntando|avisando|solicitando|pedindo|que|com\s+o\s+texto|com\s+a\s+mensagem)\s*|\s*[:]\s*)(.+)$",
        t, re.I
    )
    if m_zmsg:
        c_alvo = re.sub(r"^(?:o|a|meu|minha)\s+", "", m_zmsg.group(1).strip(), flags=re.I).strip()
        t_corpo = re.sub(r"^(?:que|se)\s+", "", m_zmsg.group(2).strip(), flags=re.I).strip()
        if t_corpo:
            t_corpo = t_corpo[0].upper() + t_corpo[1:]
        return {                                      # a frase ditada é a INTENÇÃO: o texto final ela redige (redacao.py)
            "fala": "",                               # quem fala é o resultado (prévia pronta, ou "qual Carlos?")
            "acoes": [{"t": "zap", "op": "enviar", "contato": c_alvo, "intencao": t_corpo}],
            "pose": "apresentar",
            "humor": "neutro"
        }

    # Wi-Fi
    if re.search(r"\b(liga|ligar|ativa|ativar)\b.*\bwi\s*fi\b|\bwi\s*fi\b.*\b(liga|ligar|ativa|ativar|on)\b", t):
        return {"fala": "Ligando o Wi-Fi.", "acoes": [{"t": "cli", "op": "wifi_on"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(desliga|desligar|desativa|desativar)\b.*\bwi\s*fi\b|\bwi\s*fi\b.*\b(desliga|desligar|desativa|desativar|off)\b", t):
        return {"fala": "Desligando o Wi-Fi.", "acoes": [{"t": "cli", "op": "wifi_off"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(redes|listar|quais|procurar|escanear|busca)\b.*\bwi\s*fi\b|\bwi\s*fi\b.*\b(redes|dispon[íi]veis|listar)\b", t):
        return {"fala": "", "acoes": [{"t": "cli", "op": "wifi_list"}], "pose": "apresentar", "humor": "neutro"}
    m_wcon = re.search(r"\bconecta(?:r)?\b.*?\b(?:no|na|ao|à)?\s*wi\s*fi\s+(.+)$|\bconecta(?:r)?\b.*?\b(?:à|na)?\s*rede\s+(.+)$", t)
    if m_wcon:
        return {"fala": "Conectando ao Wi-Fi.", "acoes": [{"t": "cli", "op": "wifi_connect", "arg": (m_wcon.group(1) or m_wcon.group(2)).strip()}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(status|como est[áa]|como t[áa]|qual|qual [ée]|minha conex[ãa]o)\b.*\bwi\s*fi\b|^\s*wi\s*fi\s*$", t):
        return {"fala": "", "acoes": [{"t": "cli", "op": "wifi"}], "pose": "apresentar", "humor": "neutro"}

    # Bluetooth
    if re.search(r"\b(liga|ligar|ativa|ativar)\b.*\bbluetooth\b|\bbluetooth\b.*\b(liga|ligar|ativa|ativar|on)\b", t):
        return {"fala": "Ligando o Bluetooth.", "acoes": [{"t": "cli", "op": "bt_on"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(desliga|desligar|desativa|desativar)\b.*\bbluetooth\b|\bbluetooth\b.*\b(desliga|desligar|desativa|desativar|off)\b", t):
        return {"fala": "Desligando o Bluetooth.", "acoes": [{"t": "cli", "op": "bt_off"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(status|como est[áa]|como t[áa]|dispositivos?)\b.*\bbluetooth\b|^\s*bluetooth\s*$", t):
        return {"fala": "", "acoes": [{"t": "cli", "op": "bt"}], "pose": "apresentar", "humor": "neutro"}

    # Bateria
    if re.search(r"\b(bateria|carga|n[íi]vel da bateria|porcentagem da bateria|quanto de bateria)\b", t):
        return {"fala": "", "acoes": [{"t": "cli", "op": "bateria"}], "pose": "apresentar", "humor": "neutro"}

    # Brilho
    m_br = re.search(r"\bbrilho\b.*?(\d{1,3})%?", t)
    if m_br:
        return {"fala": "", "acoes": [{"t": "cli", "op": "brilho", "arg": m_br.group(1)}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(aumenta|sobe|mais alto|mais claro)\b.*\bbrilho\b|\bbrilho\b.*?(mais|\+)", t):
        return {"fala": "", "acoes": [{"t": "cli", "op": "brilho", "arg": "+10%"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(diminui|baixa|abaixa|mais escuro)\b.*\bbrilho\b|\bbrilho\b.*?(menos|\-)", t):
        return {"fala": "", "acoes": [{"t": "cli", "op": "brilho", "arg": "-10%"}], "pose": "confirmar", "humor": "neutro"}
    if re.search(r"\b(status do brilho|como est[áa] o brilho|brilho da tela)\b", t):
        return {"fala": "", "acoes": [{"t": "cli", "op": "brilho", "arg": ""}], "pose": "apresentar", "humor": "neutro"}

    # Desempenho / PC
    if re.search(r"\b(como (?:est[áa]|t[áa]) o pc|status do pc|desempenho|uso de cpu|uso de mem[óo]ria|mem[óo]ria ram)\b", t):
        return {"fala": "", "acoes": [{"t": "cli", "op": "desempenho"}], "pose": "apresentar", "humor": "neutro"}

    # Claude CLI / Programação em background
    if re.search(r"\b(?:claude(?:\s*code|\s*cli)?|programa[çr]|c[óo]digo|desenvolv\w+)\b.*?\b(?:projeto|pasta|diret[óo]rio|workspace|docs)\b|\b(?:entre no projeto|continue o projeto|fa[çc]a o projeto)\b", t):
        m_dir = re.search(r"\b(?:na pasta|no diret[óo]rio|no caminho|em)\s+(?:de\s+|do\s+|da\s+)?([~/a-zA-Z0-9_\-\./]+)", text, re.I)
        pasta_alvo = m_dir.group(1).rstrip(".,;:/") if m_dir else ""
        if m_dir and "/" not in pasta_alvo:          # "integra site" = pasta de 2 palavras: casa com as pastas reais (a mais longa)
            base = os.path.expanduser("~/Workspace/Projetos/Sistemas")
            resto = re.sub(r"\s+", " ", text[m_dir.start(1):].lower())
            try:
                nomes = sorted(os.listdir(base), key=len, reverse=True)
            except Exception:
                nomes = []
            achou = next((n for n in nomes if resto.startswith(n.lower() + " ") or resto == n.lower()), "")
            if achou:
                pasta_alvo = os.path.join(base, achou)
        return {"fala": _v("Pode deixar, senhor. Vou trabalhar no projeto em segundo plano com o Claude.",
                           "Iniciando o trabalho no projeto em background sem interromper você.",
                           "Deixa comigo. Assumindo o projeto por trás com a CLI."),
                "acoes": [{"t": "programar", "pedido": text, "pasta": pasta_alvo}], "pose": "confirmar", "humor": "alegre"}

    # Pesquisa em background / segundo plano
    m_bg_pesq = re.search(
        r"\b(?:pesquis[ae]|busqu?[ae]|procure)\b.*?\b(?:em\s+background|por\s+tr[áa]s|em\s+segundo\s+plano)\b.*?(?:sobre|quem [ée]|o que [ée]|de)?\s*(.+)$|"
        r"\b(?:em\s+background|por\s+tr[áa]s|em\s+segundo\s+plano)\b.*?\b(?:pesquis[ae]|busqu?[ae]|procure)\b.*?(?:sobre|quem [ée]|o que [ée]|de)?\s*(.+)$",
        t, re.I
    )
    if m_bg_pesq:
        termo = (m_bg_pesq.group(1) or m_bg_pesq.group(2)).strip(" ,.!?")
        return {
            "fala": f"Pesquisando sobre {termo} em background. Já trago o resumo.",
            "acoes": [{"t": "tarefa", "pedido": f"Pesquise e me dê um resumo inteligente, direto e conciso sobre: {termo}. Não abra janelas nem trave a tela; faça tudo em background e fale o resultado final."}],
            "pose": "pensando",
            "humor": "curioso"
        }

    return None


# ---------------------------------------------------------------- executores locais
def _niri(*a):
    return subprocess.run(["niri", "msg", "action", *a], capture_output=True, text=True).returncode == 0


def _windows():
    try:
        return json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True).stdout)
    except Exception:
        return []


def find_window(q):
    q = (q or "").lower()
    if not q:
        return None
    for w in _windows():
        if q in (w.get("app_id") or "").lower() or q in (w.get("title") or "").lower():
            return w
    return None


PC_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc")


def _pc(*a, timeout=40):
    try:
        return subprocess.run([PC_BIN, *map(str, a)], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def _ampliar(w):
    """abre a janela em coluna cheia (100% dos 80% livres) — antes o navegador nascia pequeno (54%)."""
    try:
        lay = w.get("layout") or {}
        ts = lay.get("tile_size") or [0, 0]
        outs = _niri_json("outputs") or {}
        W = next(iter(outs.values()))["logical"]["width"] if outs else 1920
        if ts[0] < (W * 0.80) * 0.92:
            time.sleep(0.2)
            _niri("set-column-width", "100%")
    except Exception:
        pass


def fechar_paineis():
    """painel do Noctalia (launcher/central) ou conversa aberta prende o teclado (exclusive) e impede o foco das janelas."""
    try:
        for _ in range(3):
            ly = subprocess.run(["niri", "msg", "layers"], capture_output=True, text=True, timeout=3).stdout
            if re.search(r'Namespace: "friday-conversa"\s+Keyboard interactivity: exclusive', ly):
                from prom_ops import _daemon_send
                _daemon_send({"type": "nano", "op": "agente", "on": True})
                time.sleep(0.15)
            if not re.search(r'Namespace: "noctalia-panel"\s+Keyboard interactivity: exclusive', ly):
                return
            _pc("key", "esc"); time.sleep(0.5)
    except Exception:
        pass


def focus_or_launch(nome, ops, espera=7.0, visivel=True, grande=True):
    """foca se já houver janela (cursor vai até ela). Senão abre pelo atalho nativo do SO.
    Digitar no launcher é o último recurso, só no Linux com Noctalia."""
    import abrir_nativo
    bruto = str(nome or "").strip()
    key = abrir_nativo.chave_janela(bruto)
    if key in {"zapzap", "chromium", "kitty", "files", "code"}:
        pass
    else:
        key = {"zapzap": "zapzap", "chromium": "chromium", "kitty": "kitty", "files": "files", "code - oss": "code"}.get(bruto.lower(), key)
    fechar_paineis()
    from prom_ops import _daemon_send
    _daemon_send({"type": "painel", "op": "plano", "data": {
        "titulo": abrir_nativo.nome_exibicao(bruto), "objetivo": "Abrir " + bruto,
        "etapa": 1, "total": 2, "etapas": [["abrir pelo sistema", "executando"], ["cursor na janela", "pendente"]],
    }})
    _daemon_send({"type": "nano", "op": "app", "nome": bruto})
    w = find_window(key)
    if w:
        if visivel:
            g = _tile_geo(w)
            if g:
                _pc("move", g[0] + g[2] // 2, g[1] + g[3] // 3)
        _niri("focus-window", "--id", str(w["id"]))
        if grande:
            _ampliar(find_window(key) or w)
        if holo_mode():
            holo_live(bruto, ops)
        _daemon_send({"type": "nano", "op": "app_pronto", "nome": bruto})
        return True, f"focando {bruto}"
    ok, msg = abrir_nativo.abrir(bruto)
    t0 = time.time()
    while time.time() - t0 < espera:
        time.sleep(0.4)
        w = find_window(key)
        if w:
            break
    if not w and not ok and ops is not None:
        try:
            ok, msg = ops.app_launch(bruto)
        except Exception as e:
            ok, msg = False, str(e)[:160]
        t0 = time.time()
        while time.time() - t0 < espera:
            time.sleep(0.4)
            w = find_window(key)
            if w:
                break
    if not w and visivel and not abrir_nativo.windows():
        _pc("launch", bruto, timeout=20)
        t0 = time.time()
        while time.time() - t0 < espera:
            time.sleep(0.4)
            w = find_window(key)
            if w:
                break
    if w:
        g = _tile_geo(w)
        if visivel and g:
            _pc("move", g[0] + g[2] // 2, g[1] + g[3] // 3)
        _niri("focus-window", "--id", str(w["id"]))
        if grande:
            time.sleep(0.4)
            _ampliar(find_window(key) or w)
        if holo_mode():
            holo_live(bruto, ops)
    if not w and not ok:
        _daemon_send({"type": "nano", "op": "app_falhou", "nome": bruto})
        return False, msg or f"não consegui abrir {bruto}"
    _daemon_send({"type": "nano", "op": "app_pronto" if w else "app_falhou", "nome": bruto})
    return True, msg or f"abrindo {bruto}"


_live = {"gen": 0, "parked": None, "key": None}
_snap_cnt = [0]
FRIDAY_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "memory", "friday.json")


def holo_mode():
    """janelas em modo holograma (moldura holográfica sobre a janela real, que continua operável). 'por fora' desliga."""
    try:
        return bool(json.load(open(FRIDAY_CFG)).get("holo_janelas", True))
    except Exception:
        return True


def focused_window():
    try:
        return json.loads(subprocess.run(["niri", "msg", "-j", "focused-window"], capture_output=True, text=True, timeout=2).stdout or "null")
    except Exception:
        return None


def set_holo_mode(on):
    try:
        d = json.load(open(FRIDAY_CFG))
    except Exception:
        d = {}
    d["holo_janelas"] = bool(on)
    try:
        json.dump(d, open(FRIDAY_CFG, "w"), ensure_ascii=False)
    except Exception:
        pass
    from prom_ops import _daemon_send
    _daemon_send({"type": "holo_window", "enabled": bool(on)})


def _frame_send(on, x=0, y=0, w=0, h=0, titulo=""):
    from prom_ops import _daemon_send
    _daemon_send({"type": "holo_frame", "on": on, "x": x, "y": y, "w": w, "h": h, "titulo": titulo})


def _niri_json(*a):
    try:
        return json.loads(subprocess.run(["niri", "msg", "-j", *a], capture_output=True, text=True, timeout=4).stdout or "null")
    except Exception:
        return None


def _tile_geo(w):
    """retângulo (x, y, w, h) da janela na tela. Este niri não preenche tile_pos_in_workspace_view; calcula pelo layout em colunas:
    área útil = tela menos a coluna da F.R.I.D.A.Y. (20%); colunas lado a lado com gap; sem centralização (center-focused-column never)."""
    lay = w.get("layout") or {}
    size = lay.get("tile_size")
    if not size:
        return None
    pos = lay.get("tile_pos_in_workspace_view")
    if pos:
        return int(pos[0]), int(pos[1]), int(size[0]), int(size[1])
    outs = _niri_json("outputs") or {}
    try:
        lg = next(iter(outs.values()))["logical"]; W, H = lg["width"], lg["height"]
    except Exception:
        W, H = 1920, 1080
    gap = 2
    ox = 0
    ws = [x for x in (_windows() or []) if x.get("workspace_id") == w.get("workspace_id") and not x.get("is_floating")]
    cols = {}
    for x in ws:
        c = (x.get("layout") or {}).get("pos_in_scrolling_layout")
        ts = (x.get("layout") or {}).get("tile_size")
        if c and ts:
            cols[c[0]] = max(cols.get(c[0], 0), ts[0])
    mine = (lay.get("pos_in_scrolling_layout") or [1, 1])
    xs, acc = {}, gap
    for c in sorted(cols):
        xs[c] = acc
        acc += cols[c] + gap
    x0 = xs.get(mine[0], gap)
    view_w = W
    off = max(0, x0 + cols.get(mine[0], size[0]) + gap - view_w)
    # Top bar offset: Niri posiciona janelas entre a barra superior do sistema e o gap inferior
    this_col = mine[0] if mine else 1
    col_windows = [x for x in ws if (x.get("layout") or {}).get("pos_in_scrolling_layout", [0, 0])[0] == this_col]
    col_h = sum((x["layout"]["tile_size"][1] if "layout" in x and "tile_size" in x["layout"] else size[1]) for x in col_windows) or size[1]
    num_rows = len(col_windows) or 1
    top_y = max(gap, int(H - col_h - num_rows * gap))
    row_y = top_y
    if lay.get("pos_in_scrolling_layout") and mine[1] > 1:
        # janelas empilhadas na coluna: soma as alturas das de cima
        acima = [x for x in ws if (x.get("layout") or {}).get("pos_in_scrolling_layout", [0, 0])[0] == mine[0]
                 and (x.get("layout") or {}).get("pos_in_scrolling_layout", [0, 0])[1] < mine[1]]
        row_y += sum((x["layout"]["tile_size"][1] + gap) for x in acima)
    return max(0, int(x0 - off)), max(0, int(row_y)), int(size[0]), int(size[1])


def holo_live(nome="", ops=None, park=False):
    """camada de conversão e moldura holográfica ao vivo sobre a janela REAL do app.
    O cursor e os cliques operam a janela de verdade através do mask: Region {}.
    Segue a janela e atualiza o snapshot das nanopartículas."""
    import threading
    _live["gen"] += 1
    gen = _live["gen"]
    key = {"navegador": "chromium", "browser": "chromium"}.get((nome or "").lower().strip(), (nome or "").lower().strip())
    _live["key"] = key

    def _run():
        time.sleep(0.4)
        last = None; ausente = 0
        t0 = time.time()
        last_snap = 0
        while _live["gen"] == gen and time.time() - t0 < 3 * 3600:
            w = find_window(_live["key"]) if _live["key"] else None
            if not w:
                w = focused_window()
            geo = None
            if w:
                g = _tile_geo(w)
                if g:
                    geo = (*g, (w.get("app_id") or "").split(".")[-1].upper() or "JANELA")
            now = time.time()
            if geo != last or (geo and now - last_snap > 1.2):
                if geo:
                    _frame_send(True, *geo[:4], geo[4]); ausente = 0
                    try:
                        _snap_cnt[0] = (_snap_cnt[0] + 1) % 2
                        suf = "A" if _snap_cnt[0] == 0 else "B"
                        tmp_snap = f"/tmp/prometheus_holo_window_tmp_{suf}.png"
                        dst_snap = f"/tmp/prometheus_holo_window_{suf}.png"
                        res = subprocess.run(["grim", "-g", f"{geo[0]},{geo[1]} {geo[2]}x{geo[3]}", tmp_snap], capture_output=True, timeout=2)
                        if res.returncode == 0 and os.path.exists(tmp_snap) and os.path.getsize(tmp_snap) > 100:
                            os.replace(tmp_snap, dst_snap)
                            from prom_ops import _daemon_send
                            _daemon_send({"type": "holo_snap"})
                            last_snap = now
                    except Exception:
                        pass
                else:
                    ausente += 1
                    if ausente >= 4:
                        _frame_send(False)
                last = geo
            time.sleep(0.4)
        if _live["gen"] == gen:
            _frame_send(False)
    threading.Thread(target=_run, daemon=True, name="holo-frame").start()


def holo_live_stop():
    _live["gen"] += 1
    _frame_send(False)
    unpark_window()


def park_window(nome):
    return False


def unpark_window():
    p = _live.get("parked")
    if p:
        _niri("move-window-to-workspace", "--window-id", str(p["id"]), str(p["idx"]))
        _live["parked"] = None


# F8a: expõe o conteúdo das páginas na árvore AT-SPI (tela.py). Só vale se ESTE comando abrir o 1º processo do Chromium.
A11Y_CHROMIUM = "--force-renderer-accessibility"


def open_email(ops):
    w = find_window("caixa de entrada") or find_window("mail.google") or find_window("gmail")
    if w:
        _niri("focus-window", "--id", str(w["id"]))
        return True, "caixa de entrada em foco"
    subprocess.Popen(["setsid", "chromium", A11Y_CHROMIUM, "https://mail.google.com/"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, "abrindo o e-mail no navegador"


# ---------- painéis holográficos de apresentação (o aglomerado de partículas explode e a tela surge; ver shell/FridayCore.qml) ----------
def _painel_send(op, data=None):
    from prom_ops import _daemon_send
    _daemon_send({"type": "painel", "op": op, "data": data or {}})


def _clima(cidade=""):
    url = "https://wttr.in/" + urllib.request.quote(cidade or "") + "?format=j1&lang=pt"
    j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "curl/8"}), timeout=8))
    c = j["current_condition"][0]
    area = (j.get("nearest_area") or [{}])[0]
    desc = ((c.get("lang_pt") or c.get("weatherDesc") or [{}])[0]).get("value", "")
    dias = [{"data": d["date"][5:].replace("-", "/"), "min": int(d["mintempC"]), "max": int(d["maxtempC"]),
             "chuva": max(int(h.get("chanceofrain", 0)) for h in d.get("hourly", [{}]))} for d in j.get("weather", [])[:3]]
    return {"cidade": cidade or ((area.get("areaName") or [{}])[0].get("value", "")), "temp": int(c["temp_C"]), "sensacao": int(c["FeelsLikeC"]),
            "umidade": int(c["humidity"]), "vento": int(c["windspeedKmph"]), "desc": desc, "dias": dias}


def _sistema():
    import shutil
    d = {"load": round(os.getloadavg()[0], 2), "disco": round(100 * (1 - shutil.disk_usage("/").free / shutil.disk_usage("/").total))}
    try:
        import psutil
        d.update(cpu=psutil.cpu_percent(0.3), ram=psutil.virtual_memory().percent, up=int((time.time() - psutil.boot_time()) // 3600))
    except Exception:
        pass
    return d


def painel(op, arg, ops):
    try:
        if op == "fechar":
            _painel_send("fechar"); return True, None
        if op == "clima":
            d = _clima(arg); _painel_send("clima", d)
            return True, f"{d['cidade']}: {d['temp']} graus, {d['desc'].lower()}. Sensação de {d['sensacao']}, umidade {d['umidade']}%."
        if op == "agenda":
            dados_ = ops.agenda_painel_dados(14) if ops and hasattr(ops, "agenda_painel_dados") else {"itens": []}
            itens = dados_["itens"]
            _painel_send("agenda", dados_)
            return True, (f"Você tem {len(itens)} compromissos agendados, senhor." if itens else "Sua agenda está livre na semana, senhor.")
        if op == "sistema":
            d = _sistema(); _painel_send("sistema", d)
            return True, f"CPU em {d.get('cpu', '?')}%, memória em {d.get('ram', '?')}%, disco em {d['disco']}%."
        if op == "midia":
            meta = subprocess.run(["playerctl", "metadata", "--format", "{{artist}}\t{{title}}\t{{status}}"], capture_output=True, text=True, timeout=3).stdout.strip().split("\t")
            _painel_send("midia", {"artista": meta[0] if meta else "", "titulo": meta[1] if len(meta) > 1 else "", "status": meta[2] if len(meta) > 2 else "Parado"})
            return True, None
    except Exception as e:
        return False, f"Não consegui montar o painel: {str(e)[:50]}"
    return False, None


HOLO_BROWSER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shell", "holo_browser.html")


def navegador_holo(url=""):
    """navegador estilizado (preto/laranja/branco + holograma azul) em janela --app, com moldura holográfica ao vivo."""
    alvo = url.strip()
    q = "" if not alvo else ("?u=" if re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", alvo) else "?q=") + urllib.request.quote(alvo)
    subprocess.Popen(["setsid", "chromium", A11Y_CHROMIUM, "--user-data-dir=" + os.path.expanduser("~/.cache/friday-holo-browser"),
                      "--app=file://" + HOLO_BROWSER + q, "--force-dark-mode"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _painel_send("transicao", {"titulo": "NAVEGADOR"})
    holo_live("holo_browser", None)                 # app_id do --app: chrome-..._holo_browser.html-Default (o --class é ignorado no Wayland)
    return True, None


# ---------- automações por CLI (lista fechada: nada de shell livre) ----------
def _sh(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def cli_auto(op, arg):
    dl = os.path.expanduser("~/Downloads")
    try:
        if op in ("baixar_video", "baixar_audio"):
            if not re.match(r"^https?://", arg):
                return False, "Me passa o link, senhor."
            extra = ["-x", "--audio-format", "mp3"] if op == "baixar_audio" else ["-f", "bv*[height<=1080]+ba/b"]
            subprocess.Popen(["setsid", "sh", "-c", 'yt-dlp "$@" && notify-send "F.R.I.D.A.Y." "Download concluído"', "_", *extra, "-o", dl + "/%(title)s.%(ext)s", arg],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "Download iniciado. Te aviso quando terminar."
        if op == "converter":                     # arg: "arquivo.ext para mp3"
            m = re.match(r"^(.+?)\s+(?:para|pra|->)\s+\.?(\w{2,4})$", arg.strip())
            if not m or not os.path.exists(os.path.expanduser(m.group(1))):
                return False, "Qual arquivo e para qual formato?"
            src = os.path.expanduser(m.group(1)); dst = os.path.splitext(src)[0] + "." + m.group(2).lower()
            img = m.group(2).lower() in ("png", "jpg", "jpeg", "webp", "gif", "avif")
            ok, _ = _sh(["magick", src, dst] if img else ["ffmpeg", "-y", "-loglevel", "error", "-i", src, dst])
            return ok, ("Convertido: " + os.path.basename(dst)) if ok else "A conversão falhou."
        if op == "print":
            dst = os.path.expanduser(time.strftime("~/Imagens/friday-%Y%m%d-%H%M%S.png"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            ok, _ = _sh(["grim", dst], 20)
            if ok:
                subprocess.run(["sh", "-c", 'wl-copy < "$1"', "_", dst])
            return ok, "Captura salva e copiada." if ok else "Não consegui capturar a tela."
        if op == "calcular":
            ok, out = _sh(["qalc", "-t", arg], 15)
            return ok, ("Dá " + out.splitlines()[-1]) if ok and out else "Não consegui calcular."
        if op == "ajuda_comando":
            ok, out = _sh(["tldr", "--raw", arg.split()[0] if arg else "tldr"], 20)
            linhas = [l.lstrip("- ").strip() for l in out.splitlines() if l.startswith("- ")][:2]
            return ok, ("; ".join(linhas) if linhas else "Não achei exemplos para esse comando.")
        if op == "copiar":
            subprocess.run(["wl-copy"], input=arg, text=True); return True, "Copiado."
        if op == "notificar":
            subprocess.run(["notify-send", "F.R.I.D.A.Y.", arg]); return True, None
        if op == "wifi":
            ok, out = _sh(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"], 15)
            at = [l.split(":") for l in out.splitlines() if l.startswith("sim:") or l.startswith("yes:")]
            return ok, (f"Conectada em {at[0][1]}, sinal {at[0][2]}%." if at else "Sem Wi-Fi conectado no momento.")
        if op == "wifi_list":
            ok, out = _sh(["nmcli", "-t", "-f", "SSID,SIGNAL", "dev", "wifi"], 15)
            if ok and out:
                redes, vistas = [], set()
                for l in out.splitlines():
                    p = l.split(":")
                    nm = p[0].strip()
                    if nm and nm not in vistas:
                        vistas.add(nm)
                        sig = p[1].strip() if len(p) > 1 else ""
                        redes.append(f"{nm} ({sig}%)" if sig else nm)
                return True, ("Redes Wi-Fi disponíveis: " + ", ".join(redes[:5]) + ".") if redes else "Nenhuma rede Wi-Fi encontrada."
            return False, "Não consegui escanear as redes Wi-Fi."
        if op == "wifi_connect":
            ssid = arg.strip()
            if not ssid:
                return False, "Qual o nome da rede Wi-Fi para conectar?"
            ok, out = _sh(["nmcli", "dev", "wifi", "connect", ssid], 25)
            return ok, (f"Conectada com sucesso à rede {ssid}." if ok else f"Falha ao conectar em {ssid}: {out[:60]}")
        if op == "wifi_on":
            ok, _ = _sh(["nmcli", "radio", "wifi", "on"], 10)
            return ok, ("Wi-Fi ativado." if ok else "Falha ao ativar o Wi-Fi.")
        if op == "wifi_off":
            ok, _ = _sh(["nmcli", "radio", "wifi", "off"], 10)
            return ok, ("Wi-Fi desligado." if ok else "Falha ao desligar o Wi-Fi.")
        if op in ("bt", "bluetooth"):
            ok, out = _sh(["bluetoothctl", "show"], 10)
            on = "Powered: yes" in out
            if not on:
                return True, "O Bluetooth está desligado."
            ok2, dev_out = _sh(["bluetoothctl", "devices", "Connected"], 10)
            conns = [l.split(" ", 2)[2] for l in dev_out.splitlines() if len(l.split(" ", 2)) >= 3]
            if conns:
                return True, f"Bluetooth ligado e conectado em: {', '.join(conns)}."
            return True, "Bluetooth ligado, mas nenhum dispositivo conectado."
        if op == "bt_on":
            ok, _ = _sh(["bluetoothctl", "power", "on"], 10)
            return ok, ("Bluetooth ligado." if ok else "Falha ao ligar Bluetooth.")
        if op == "bt_off":
            ok, _ = _sh(["bluetoothctl", "power", "off"], 10)
            return ok, ("Bluetooth desligado." if ok else "Falha ao desligar Bluetooth.")
        if op == "bateria":
            ok, out = _sh(["sh", "-c", "cat /sys/class/power_supply/BAT*/capacity"], 5)
            return True, (f"Bateria em {out.splitlines()[0]}%." if ok and out else "Esse PC não possui bateria.")
        if op == "brilho":
            v = arg.strip()
            if v:
                if v.startswith("+") or v.startswith("-") or "%" in v:
                    _sh(["brightnessctl", "set", v], 10)
                elif v.isdigit():
                    _sh(["brightnessctl", "set", f"{min(100, int(v))}%"], 10)
            ok, cur = _sh(["brightnessctl", "get"], 5)
            ok2, mx = _sh(["brightnessctl", "max"], 5)
            try:
                pct = round(int(cur.strip()) / int(mx.strip()) * 100)
                return True, f"Brilho da tela em {pct}%."
            except Exception:
                return True, "Brilho ajustado."
        if op == "disco":
            import shutil
            u = shutil.disk_usage("/")                  # número medido agora, nunca estimado
            return True, f"O disco principal tem {u.free / 1e9:.0f} GB livres de {u.total / 1e9:.0f} GB ({round(100 * u.used / u.total)}% ocupado)."
        if op in ("desempenho", "pc_status"):
            d = _sistema()
            return True, f"Processador em {d.get('cpu', 0)}%, memória RAM {d.get('ram', 0)}% usada, e disco {d.get('disco', 0)}%."
        if op == "atualizacoes":
            ok, out = _sh(["sh", "-c", "checkupdates 2>/dev/null | wc -l"], 60)
            return True, f"{out or 0} pacotes para atualizar. Quer que eu prepare o comando?"
    except Exception as e:
        return False, f"Falhou: {str(e)[:60]}"
    return False, "Não conheço essa automação."


REPOUSO = [False]       # modo repouso: tela bloqueada -> ações que dependem da tela não rodam (iriam digitar na senha)
_SO_TELA = {"janela", "abrir_app", "abrir_url", "navegador_holo", "holo", "celular_tela", "manual"}


def run_action(a, ops, ctx=None):
    if REPOUSO[0] and isinstance(a, dict) and a.get("t") in _SO_TELA:
        return False, "Estou em modo repouso, com a tela bloqueada. Diga acordar que eu faço isso na tela."
    return _run_action(a, ops, ctx)


def _run_action(a, ops, ctx=None):
    """executa UMA ação local. Devolve (ok, texto_para_falar|None). Ações de envio passam pela política (ops.gated/approval)."""
    t = a.get("t")
    try:
        if t == "abrir_app":
            r = focus_or_launch(str(a.get("nome", "")), ops)
            if r[0] and holo_mode() and not a.get("por_fora"):
                holo_live(str(a.get("nome", "")), ops)          # janela vira holograma (moldura); o cursor atua por dentro dela
            return r
        if t == "projecao":
            import projecao as _pj
            from prom_ops import _daemon_send
            op = a.get("op", "objeto")
            if op == "fechar":
                _pj.fechar_projecao()
                _daemon_send({"type": "holo", "op": "clear"})
                return True, "Projeção holográfica encerrada."
            termo = a.get("termo", "reator")
            spec = _pj.criar_objeto_3d(termo)
            _daemon_send({"type": "holo", "op": "show", "spec": spec})
            return True, f"Projetando {spec.get('titulo', termo)}."
        if t == "modo":
            from prom_ops import _daemon_send
            if a.get("nome") in ("criacao", "janela") and a.get("on", True) is not False:      # só o dono liga (voz explícita/app), nunca a IA sozinha
                return False, "Esse modo só liga quando você pedir: diga 'ativar modo criação' ou 'modo janela'."
            _daemon_send({"type": "mode", "mode": a.get("nome"), "on": a.get("on", True)})
            return True, None
        if t == "camera":                                     # câmera com motor (ptz.py): olhar, procurar, seguir, vigiar
            import ptz
            ok_c, msg_c = ptz.comando(a)
            return ok_c, (None if ok_c else msg_c)
        if t == "email":
            op = a.get("op", "abrir")
            if op == "abrir":
                return open_email(ops)
            if op == "compor":
                from prom_ops import holo_show, gated
                to, sub, body = a.get("para", ""), a.get("assunto", ""), a.get("corpo", "")
                if not to:
                    return False, "Para quem devo enviar, senhor?"
                holo_show({"kind": "email", "para": to, "assunto": sub, "corpo": body, "status": "aguardando aprovação", "titulo": "Novo e-mail", "ttl": 300})
                ok, msg = gated("mail.send", to, f"e-mail para {to}: {sub}", {"to": to, "subject": sub, "body": body})
                return True, "Rascunho no espelho. Diga aprovado para enviar." if not ok else "Enviado."
            if op == "listar":
                try:
                    itens = ops.mail_list(5, True)
                    if not itens:
                        return True, "Nenhum e-mail novo."
                    return True, "Você tem " + str(len(itens)) + " e-mails novos. O primeiro é de " + str(itens[0]["de"])[:40] + ": " + str(itens[0]["assunto"])[:60]
                except Exception:
                    return open_email(ops)
        if t == "abrir_url":
            url = str(a.get("url", "")).strip()
            if url:
                focus_or_launch("Chromium", ops)
                w = find_window("chromium")
                if w:
                    _niri("focus-window", "--id", str(w["id"]))
                    time.sleep(0.3)
                out = _pc("goto", url, timeout=30)
                if not out or "erro" in out.lower():
                    subprocess.Popen(["setsid", "chromium", A11Y_CHROMIUM, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, None
        if t == "janela":
            op = a.get("op")
            if op in ("proxima", "anterior"):
                return _niri("focus-column-right" if op == "proxima" else "focus-column-left"), None
            if op == "maximizar":
                return _niri("maximize-column"), None
            if op in ("fechar", "focar"):
                w = find_window(a.get("alvo", "")) if a.get("alvo") else None
                if op == "fechar" and not w:                      # nunca fecha "a janela em foco" no chute (já fechou o navegador do dono uma vez)
                    return False, "Não achei essa janela para fechar."
                args = ["close-window" if op == "fechar" else "focus-window"] + (["--id", str(w["id"])] if w else [])
                if op == "focar" and w:
                    g = _tile_geo(w)
                    if g:
                        _pc("move", g[0] + g[2] // 2, g[1] + g[3] // 3)         # o cursor vai até a janela (visível)
                okn = _niri(*args)
                if op == "focar" and w:
                    _ampliar(find_window(str(a.get("alvo", ""))) or w)
                    if holo_mode():
                        holo_live(str(a.get("alvo", "")), ops)
                return okn, None
        if t == "sistema":
            op, v = a.get("op"), str(a.get("valor", ""))
            if op == "volume":
                if v == "up":
                    subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"])
                elif v == "down":
                    subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"])
                elif v.isdigit():
                    subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{min(100, int(v))}%"])
                return True, None
            if op == "brilho" and v:
                subprocess.run(["brightnessctl", "set", v if v.endswith("%") else v + "%"])
                return True, None
            if op == "midia":
                r = subprocess.run(["playerctl", v or "play-pause"], capture_output=True, text=True, timeout=5)
                if (v or "play-pause") in ("play", "play-pause", "next", "previous"):      # confere: algo está tocando de verdade?
                    time.sleep(0.8)
                    st = subprocess.run(["playerctl", "status"], capture_output=True, text=True, timeout=3).stdout.strip()
                    if r.returncode != 0 or st != "Playing":
                        return False, None                       # nada tocou: quem chama escala para tarefa (agente)
                return True, None
        if t == "agenda":
            op, titulo = a.get("op"), str(a.get("titulo", "")).strip()
            hm = lambda i: time.strftime("%H:%M", time.localtime(i["inicio"]))
            if op == "limpar":
                if ops:
                    ops.agenda_limpar()
                _painel_send("agenda", {"itens": []})
                return True, "Agenda limpa, senhor. Todos os compromissos foram removidos."
            if op == "adicionar":
                try:
                    lem = int(a["lembrar_min"]) if str(a.get("lembrar_min", "")).strip() else None
                except (TypeError, ValueError):
                    lem = None
                aid, msg = ops.agenda_add(titulo, str(a.get("quando", "")), "compromisso", 60, "", "", "", "voz", lem, str(a.get("repete", "")),
                                          a.get("prioridade", 2))
                if not aid:
                    return False, "Não entendi a data, senhor. Pode me informar o dia e a hora?"
                it = next((i for i in ops.agenda_all() if i["id"] == aid), None)
                quando = time.strftime("%d/%m às %H:%M", time.localtime(it["inicio"])) if it else ""
                conf = ops.agenda_conflitos(it["inicio"], it["fim"], aid) if it else []
                rep_ = {"diario": ", todo dia", "semanal": ", toda semana", "dias_uteis": ", nos dias úteis", "mensal": ", todo mês", "anual": ", todo ano"}.get(it.get("repete", ""), "") if it else ""
                if ops and hasattr(ops, "agenda_formatar_painel"):
                    _painel_send("agenda", ops.agenda_painel_dados(14))
                return True, (f"Já estava na agenda." if msg != "ok" else f"Anotado: {titulo}, {quando}{rep_}.") + \
                    (f" Atenção: bate com {conf[0]['titulo']} às {hm(conf[0])}." if conf else "")
            if op in ("remover", "remarcar", "concluir"):
                if op == "remover" and ops and hasattr(ops, "agenda_remover"):
                    ok_r, tit_r = ops.agenda_remover(titulo)
                    _painel_send("agenda", ops.agenda_painel_dados(14))
                    return ok_r, (f"Tirei '{tit_r}' da agenda, senhor." if ok_r else f"Compromisso '{titulo}' não encontrado.")
                it = ops.agenda_buscar(titulo)
                if not it:
                    return False, f"Não achei {titulo or 'esse compromisso'} na agenda."
                if op == "concluir":
                    ops.agenda_mark(it["id"], feito=True)
                    if hasattr(ops, "agenda_formatar_painel"):
                        _painel_send("agenda", ops.agenda_painel_dados(14))
                    return True, f"Marquei {it['titulo']} como feito."
                if not ops.agenda_remarcar(it["id"], str(a.get("quando", ""))):
                    return False, "Pra quando o senhor prefere remarcar?"
                it = next(i for i in ops.agenda_all() if i["id"] == it["id"])
                conf = ops.agenda_conflitos(it["inicio"], it["fim"], it["id"])
                if hasattr(ops, "agenda_formatar_painel"):
                    _painel_send("agenda", ops.agenda_painel_dados(14))
                return True, f"{it['titulo']} passou pra {time.strftime('%d/%m às %H:%M', time.localtime(it['inicio']))}." + \
                    (f" Bate com {conf[0]['titulo']}." if conf else "")
            if op == "prioridade":
                it = ops.agenda_buscar(titulo)
                if not it:
                    return False, f"Não achei {titulo or 'esse compromisso'} na agenda."
                ops.agenda_prioridade(it["id"], a.get("prioridade", 1))
                _painel_send("agenda", ops.agenda_painel_dados(14))
                return True, f"{it['titulo']} agora tem prioridade {ops.PRIO_NOME[ops._prio(a.get('prioridade', 1))]}."
            if op == "nivel":
                amanha_ = str(a.get("periodo", "hoje")) == "amanha"
                _painel_send("agenda", ops.agenda_painel_dados(14))
                return True, ops.agenda_nivel_fala(time.time() + (86400 if amanha_ else 0)).replace("Dia ", "Amanhã é um dia " if amanha_ else "Hoje é um dia ", 1)
            per = str(a.get("periodo", "hoje"))
            dados_ = ops.agenda_painel_dados(14) if ops and hasattr(ops, "agenda_painel_dados") else {"itens": []}
            itens = dados_["itens"]
            _painel_send("agenda", dados_)
            if not itens:
                return True, f"Sua agenda está livre, senhor."
            return True, f"Você tem {len(itens)} compromissos agendados, senhor."
        if t == "zap":
            import zap
            if a.get("op") == "ler":
                contato = str(a.get("contato", "")).strip()
                if contato:
                    if not zap.available():
                        zap.ensure_running()
                    r = zap.read_chat(contato, 5)
                    if not r.get("ok"):
                        return False, f"Não consegui ler as mensagens de {contato} no WhatsApp: {r.get('motivo', 'não encontrada')}."
                    msgs = r.get("msgs", [])
                    if not msgs:
                        return True, f"Nenhuma mensagem recente encontrada na conversa com {r.get('conversa', contato)}."
                    linhas = []
                    for m in msgs[-3:]:
                        quem = m.get("quem") or ("Você" if m.get("saida") else r.get("conversa", contato))
                        linhas.append(f"{quem} disse: '{m.get('texto', '')}'")
                    return True, f"Mensagens de {r.get('conversa', contato)}: " + "; ".join(linhas)
                s = zap.snapshot()
                if not s.get("ok"):
                    return False, "Não consegui acessar o WhatsApp agora."
                nl = [c for c in s["chats"] if c.get("nao_lidas")]
                if not nl:
                    recentes = [f"{c['nome']}: '{c['previa']}'" for c in s["chats"][:3] if c.get('previa')]
                    if recentes:
                        return True, "Nenhuma mensagem nova não-lida no WhatsApp. As conversas recentes são: " + " | ".join(recentes)
                    return True, "Nenhuma mensagem nova no WhatsApp."
                return True, f"Você tem {sum(c['nao_lidas'] for c in nl)} mensagens novas. A mais recente é de {nl[0]['nome']}: {nl[0]['previa'][:80]}"
            if a.get("op") in ("responder", "enviar"):
                contato = str(a.get("contato", "")).strip()
                texto = str(a.get("texto", "")).strip()
                pedido = str(a.get("intencao", "")).strip()
                ctx = []
                try:                                      # resolve a conversa ANTES: nome real + contexto (abre o chat; dono autorizou)
                    if not zap.available():
                        zap.ensure_running()
                    r_ = zap.read_chat(contato, 10)
                    if r_.get("motivo") == "ambiguo":
                        nomes = [c_["nome"] for c_ in r_.get("candidatos", [])][:3]
                        return False, ("Tenho mais de um contato parecido: " + " ou ".join(nomes) + ". Para qual deles?")
                    if r_.get("ok"):
                        ctx = r_.get("msgs", [])
                        contato = r_.get("conversa") or contato
                    elif "não encontrada" in str(r_.get("motivo", "")):
                        return False, f"Não achei a conversa com {contato} no WhatsApp."
                except Exception:
                    pass
                if pedido and not texto:                  # dono ditou a intenção: ela redige no tom dele
                    import redacao
                    texto = redacao.redigir(contato, pedido, ctx)["texto"]
                if not texto:
                    return False, "Não entendi o que escrever na mensagem."
                ctx_card = [{"quem": "Você" if m_.get("saida") else (m_.get("quem") or contato), "texto": str(m_.get("texto", ""))[:140],
                             "saida": bool(m_.get("saida"))} for m_ in ctx[-4:] if m_.get("texto")]
                if ops is None:                       # sem portão de aprovação = NÃO envia (antes enviava direto)
                    return False, "Envio bloqueado: o portão de aprovação não está disponível."
                ok, msg = ops.gated("wa.send_chat", contato, f"enviar para {contato}: {texto[:100]}",
                                    {"nome": contato, "texto": texto, "pedido": pedido if pedido != texto else "", "contexto": ctx_card})
                if ok:
                    return True, f"Enviado para {contato}."
                if str(msg).startswith("PENDENTE"):           # PENDENTE chega ao agente (antes virava None e ele dizia "enviada")
                    lido = f"Escrevi para {contato}: {texto}" if len(texto) <= 180 else f"Escrevi a mensagem para {contato}; está no espelho"
                    return True, f"{msg} — {lido}. Diga aprovado para enviar, ou modifica para mudar."
                return False, msg
            if a.get("op") == "encaminhar":
                de_contato = str(a.get("de_contato") or a.get("de") or a.get("origem") or "").strip()
                para_contato = str(a.get("para_contato") or a.get("para") or a.get("destino") or "").strip()
                filtro = str(a.get("filtro") or "").strip()
                if not de_contato or not para_contato:
                    return False, "Origem e destino são obrigatórios para encaminhar no WhatsApp."
                if ops is None:
                    return False, "Envio bloqueado: o portão de aprovação não está disponível."
                ok, msg = ops.gated("wa.forward", para_contato,
                                    f"encaminhar {filtro or 'documento'} de {de_contato} para {para_contato}",
                                    {"de": de_contato, "para": para_contato, "filtro": filtro})
                if ok:
                    return True, f"Encaminhado de {de_contato} para {para_contato}."
                if str(msg).startswith("PENDENTE"):
                    return True, f"{msg} — Encaminhamento de {de_contato} para {para_contato} preparado no espelho. Diga aprovado para confirmar o envio."
                return False, msg
        if t == "manual":
            if re.search(r"only\s*office|planilh|document|apresenta|slides?|\.(?:docx|xlsx|pptx)\b", str(a.get("objetivo", "")), re.I):
                return False, "Para documentos e planilhas use onlyoffice_criar: o modo manual toma mouse/teclado e trava a tela."
            import manual
            ok_m, msg_m = manual.start(str(a.get("objetivo", "")), sys.modules[__name__])
            try:
                ops.audit("friday.manual", "", str(a.get("objetivo", ""))[:120], "ok" if ok_m else "ocupado")
            except Exception:
                pass
            return ok_m, msg_m
        if t == "celular_tela":                                # tela do celular ao vivo no holograma (celtela, 60 fps)
            import celtela
            op_cel = a.get("op", "mostrar")
            if op_cel == "fechar":
                celtela.fechar(); return True, None
            if op_cel == "desbloquear":
                try:
                    import celular
                    celular.acordar()
                    celular.desbloquear()
                except Exception:
                    pass
                celtela.mostrar(); return True, None
            try:
                celtela.mostrar(); return True, None
            except Exception:
                import celular                                 # app antigo (sem transmissão): print estático no holograma
                celular.capturar(); celular.mostrar(); return True, None
        if t == "painel":
            return painel(str(a.get("op", "clima")), str(a.get("arg", "")), ops)
        if t == "navegador_holo":
            return navegador_holo(str(a.get("url", "")))
        if t == "cli":
            return cli_auto(str(a.get("op", "")), str(a.get("arg", "")))
        if t == "holo":
            from prom_ops import holo_window, holo_show
            op, arg = a.get("op"), str(a.get("arg", ""))
            if op == "janela":
                return holo_window(arg or "chromium")[0], None
            if op == "limpar":
                holo_live_stop()
                holo_show(None, "clear"); return True, None
            if op == "figura":
                holo_show({"kind": "figura", "forma": arg or "esfera", "titulo": arg.capitalize() or "Figura", "ttl": 90}); return True, None
    except Exception as e:
        return False, f"Falhou: {str(e)[:60]}"
    return False, None


class GestureEngine:
    """gestos de mão -> eventos: agarrar (punho firme), soltar, mover (punho + arrastar), maximizar (punho + subir),
    fechar (punho + descer), passar (varrer o braço), workspace (varrer vertical), overview (sinal de paz) e apontar.
    Entrada: (t, u, v, pose, visível) com u,v do punho normalizados (0..1, câmera NÃO espelhada)."""

    def __init__(self):
        self.hist = []              # (t, u, v)
        self.fist = []              # (t, bool)
        self.grab = None            # dict(anchor_u, anchor_v, t0)
        self.last = {}              # cooldowns por tipo
        self.point_since = None
        self.paz_since = None
        self.ult_jan = None         # (t, tipo, dir) do último gesto de janela executado
        self.cfg_t = -1e9; self.cfg_on = True

    def _cool(self, k, t, dt):
        if t - self.last.get(k, 0) < dt:
            return False
        self.last[k] = t
        return True

    def _janela(self, t, k, d=None):
        """gestos que mexem em janela (passar/mover/maximizar/fechar/workspace/overview):
        opt-in 'gestos_janela' no friday.json (padrão ligado), cooldown ágil de 0.6 s
        para resposta instantânea sem trava artificial entre sentidos opostos."""
        if t - self.cfg_t > 3:
            self.cfg_t = t
            try:
                self.cfg_on = bool(json.load(open(FRIDAY_CFG)).get("gestos_janela", True))
            except Exception:
                self.cfg_on = True
        if not self.cfg_on:
            return False
        u = self.ult_jan
        if u and t - u[0] < 0.6:
            return False
        self.ult_jan = (t, k, d)
        return True

    def update(self, t, u, v, pose, visible):
        ev = []
        if not visible:
            self.hist.clear(); self.fist.clear(); self.point_since = None; self.paz_since = None
            if self.grab and t - self.grab["seen"] > 0.8:
                ev.append(("soltar", {})); self.grab = None
            return ev
        self.hist.append((t, u, v)); self.hist = [h for h in self.hist if t - h[0] < 1.0]
        self.fist.append((t, pose == "punho")); self.fist = [f for f in self.fist if t - f[0] < 0.5]
        frac = sum(1 for _, f in self.fist if f) / max(1, len(self.fist))
        is_fist = frac >= 0.6 and len(self.fist) >= 2
        not_fist = frac <= 0.3 and len(self.fist) >= 2
        if self.grab:
            self.grab["seen"] = t
        if is_fist and not self.grab and self._cool("agarrar", t, 0.5):
            self.grab = {"au": u, "av": v, "t0": t, "seen": t}
            ev.append(("agarrar", {}))
        elif self.grab and not_fist:
            ev.append(("soltar", {})); self.grab = None
        if self.grab:
            du, dv = u - self.grab["au"], v - self.grab["av"]
            if abs(du) > 0.12 and self._janela(t, "mover", "direita" if du < 0 else "esquerda"):
                ev.append(("mover", {"dir": "direita" if du < 0 else "esquerda"}))     # câmera não espelhada: u cai = mão foi p/ a direita do usuário
                self.grab["au"], self.grab["av"] = u, v
            elif dv < -0.14 and self._janela(t, "maximizar"):
                ev.append(("maximizar", {}))
                self.grab["au"], self.grab["av"] = u, v
            elif dv > 0.16 and self._janela(t, "fechar"):
                ev.append(("fechar", {}))
                self.grab["au"], self.grab["av"] = u, v
        else:
            old = [h for h in self.hist if t - h[0] <= 0.6]
            if len(old) >= 2:
                du = old[-1][1] - old[0][1]
                dv = old[-1][2] - old[0][2]
                if abs(du) > 0.11 and abs(du) > abs(dv) * 1.05 and self._janela(t, "passar", "direita" if du < 0 else "esquerda"):
                    ev.append(("passar", {"dir": "direita" if du < 0 else "esquerda"}))
                    self.hist.clear()
                elif abs(dv) > 0.13 and abs(dv) > abs(du) * 1.05 and self._janela(t, "workspace", "baixo" if dv > 0 else "cima"):
                    ev.append(("workspace", {"dir": "baixo" if dv > 0 else "cima"}))
                    self.hist.clear()
            if pose == "paz":
                self.paz_since = self.paz_since or t
                if t - self.paz_since > 0.25 and self._cool("paz", t, 1.0) and self._janela(t, "overview"):
                    ev.append(("overview", {}))
            else:
                self.paz_since = None
            if pose == "apontar":
                self.point_since = self.point_since or t
                if t - self.point_since > 0.7 and self._cool("apontar", t, 3.0):
                    ev.append(("apontar", {}))
            else:
                self.point_since = None
            if pose == "joinha":
                self.joinha_since = getattr(self, "joinha_since", None) or t
                if t - self.joinha_since > 0.35 and self._cool("joinha", t, 2.0):
                    ev.append(("confirmar", {"gesto": "joinha"}))
            else:
                self.joinha_since = None
            if pose == "polegar_baixo":
                self.pbaixo_since = getattr(self, "pbaixo_since", None) or t
                if t - self.pbaixo_since > 0.35 and self._cool("polegar_baixo", t, 2.0):
                    ev.append(("cancelar", {"gesto": "polegar_baixo"}))
            else:
                self.pbaixo_since = None
            if pose == "pare":
                self.pare_since = getattr(self, "pare_since", None) or t
                if t - self.pare_since > 0.30 and self._cool("pare", t, 1.5):
                    ev.append(("silenciar", {"gesto": "pare"}))
            else:
                self.pare_since = None
            if pose == "rock":
                self.rock_since = getattr(self, "rock_since", None) or t
                if t - self.rock_since > 0.40 and self._cool("rock", t, 3.0):
                    ev.append(("midia", {"gesto": "rock"}))
            else:
                self.rock_since = None
        return ev


def gesture_action(kind, data):
    """executa a consequência do gesto no compositor e no palco 3D; devolve (rótulo, pose do avatar)."""
    d = data.get("dir")
    import projecao as _pj
    if _pj._estado_projecao.get("ativo"):
        if kind == "passar":
            cur_speed = _pj._estado_projecao.get("rot_speed", 0.8)
            new_speed = -1.6 if d == "esquerda" else 1.6
            _pj._estado_projecao["rot_speed"] = new_speed
            spec = _pj.criar_objeto_3d(_pj._estado_projecao.get("nome", "reator"), modificacao=f"gire para {d}")
            from prom_ops import _daemon_send
            _daemon_send({"type": "holo", "op": "update", "spec": spec})
            return f"Girar 3D {d}", "apontar" if d == "direita" else "apontarL"
        if kind == "maximizar":
            spec = _pj.criar_objeto_3d(_pj._estado_projecao.get("nome", "reator"), modificacao="visão explodida")
            from prom_ops import _daemon_send
            _daemon_send({"type": "holo", "op": "update", "spec": spec})
            return "Explodir 3D", "apresentar"
        if kind == "overview":
            spec = _pj.criar_objeto_3d(_pj._estado_projecao.get("nome", "reator"), modificacao="wireframe montar")
            from prom_ops import _daemon_send
            _daemon_send({"type": "holo", "op": "update", "spec": spec})
            return "Recompor 3D", "apresentar"
        if kind == "fechar":
            _pj.fechar_projecao()
            from prom_ops import _daemon_send
            _daemon_send({"type": "holo", "op": "clear"})
            return "Fechar projeção", "confirmar"

    if kind == "agarrar":
        return "Agarrar", "agarrar"
    if kind == "soltar":
        return "Soltar", "neutro"
    if kind == "mover":
        _niri("move-column-right" if d == "direita" else "move-column-left")
        return f"Mover {d}", "apontar" if d == "direita" else "apontarL"
    if kind == "maximizar":
        _niri("maximize-column")
        return "Maximizar", "apresentar"
    if kind == "fechar":                                  # nunca fecha terminal (Claude CLI/MODO DEV rodando nele)
        try:
            f = json.loads(subprocess.run(["niri", "msg", "-j", "focused-window"], capture_output=True, text=True, timeout=3).stdout or "null") or {}
        except Exception:
            f = {}
        if re.search(r"kitty|term|alacritty|foot|wezterm|konsole", str(f.get("app_id") or ""), re.I):
            return "Terminal protegido", "neutro"
        _niri("close-window")
        return "Fechar janela", "confirmar"
    if kind == "passar":
        _niri("focus-column-right" if d == "direita" else "focus-column-left")
        return f"Passar {d}", "apontar" if d == "direita" else "apontarL"
    if kind == "workspace":
        _niri("focus-workspace-down" if d == "baixo" else "focus-workspace-up")
        return f"Workspace {d}", "apresentar"
    if kind == "overview":
        _niri("toggle-overview")
        return "Visão Geral", "apresentar"
    if kind == "apontar":
        return "Apontar", "apontar"
    if kind == "confirmar":
        try:
            import remoto
            remoto.aprovar_acao_pendente()
        except Exception:
            pass
        return "Confirmado (Joinha)", "confirmar"
    if kind == "cancelar":
        try:
            import remoto
            remoto.cancelar_acao_pendente()
        except Exception:
            pass
        return "Cancelado (Polegar para baixo)", "negar"
    if kind == "silenciar":
        try:
            from prom_ops import _daemon_send
            _daemon_send({"type": "parar_fala"})
        except Exception:
            pass
        return "Silenciando", "pensativo"
    if kind == "midia":
        return "Modo Multimídia", "alegre"
    return kind, "neutro"


class Vad:
    """VAD por energia robusto: piso = percentil 10 dos últimos ~5 s (não 'sobe' com a fala); início com histerese
    (>= max(0.009, 2.4×piso) por 3 quadros), continuação mais frouxa (>= max(0.005, 1.7×piso)), cauda de ~0,5 s.
    feed(rms) -> 'start' | 'cont' | 'end' | None   (quadros de 30 ms)"""

    def __init__(self, tail=15, min_voiced=7):
        self.hist = []; self.tail = tail; self.min_voiced = min_voiced
        self.active = False; self.run = 0; self.silent = 0; self.voiced = 0

    @property
    def floor(self):
        if not self.hist:
            return 0.004
        s = sorted(self.hist)
        return s[int(len(s) * 0.10)]

    def thresholds(self):
        f = self.floor
        return max(0.009, 2.4 * f), max(0.005, 1.7 * f)

    def feed(self, rms):
        start_t, cont_t = self.thresholds()
        if not self.active:
            self.hist.append(rms)
            if len(self.hist) > 170:
                self.hist.pop(0)
            if rms > start_t:
                self.run += 1
                if self.run >= 3:
                    self.active = True; self.silent = 0; self.voiced = self.run
                    return "start"
            else:
                self.run = 0
            return None
        # ativo
        if rms > cont_t:
            self.silent = 0; self.voiced += 1
            return "cont"
        self.silent += 1
        if self.silent > self.tail:
            self.active = False; self.run = 0
            ok = self.voiced >= self.min_voiced + 3
            self.voiced = 0
            return "end" if ok else "drop"
        return "cont"


def vision_describe(jpg_bytes, pergunta):
    """pergunta sobre a imagem da câmera ao VLM LOCAL (qwen2.5vl). Devolve texto curto em pt-BR ou None."""
    import base64
    try:
        body = {"model": MODEL_VISAO, "stream": False,       # visão fica no modelo que enxerga; o de raciocínio não recebe imagem
                "options": {"temperature": 0.1, "num_predict": 120, "num_ctx": NUM_CTX, "num_gpu": NUM_GPU},
                "messages": [{"role": "user", "content": "Responda em português do Brasil, em 1 ou 2 frases curtas, só com o que está VISÍVEL. Pergunta: " + pergunta,
                              "images": [base64.b64encode(jpg_bytes).decode()]}]}
        return _post("/api/chat", body, 120)["message"]["content"].strip()
    except Exception:
        return None


def warm():
    """pré-carrega o modelo de conversa na GPU (evita ~8 s na primeira fala)."""
    try:
        _post("/api/chat", {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "ok"}],
                            "options": {"num_predict": 1, "num_ctx": NUM_CTX, "num_gpu": NUM_GPU}}, 120)
    except Exception:
        pass
