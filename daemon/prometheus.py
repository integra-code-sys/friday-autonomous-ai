#!/usr/bin/env python3
"""Prometheus — daemon local. Socket unix JSON-lines em $XDG_RUNTIME_DIR/prometheus.sock.

Cliente -> daemon:  {"type":"chat","text":"...","files":["/x.png"]} | {"type":"say","text":"..."}
                    {"type":"mood","mood":"alegre"} | {"type":"stop"}
Daemon -> clientes: {"type":"state","state":"idle|thinking|speaking","mood":"..."}   (mood: um dos 13 de MOODS)
                    {"type":"gaze","x":-1..1,"y":-1..1,"present":bool}
                    {"type":"visao","t":epoch,"cam":"nativa","faces":[{"nome":str|"","dono":bool,"sim":0..1,"box":[x,y,w,h],
                      "sorriso":0..1,"yaw":-1..1,"pitch":-1..1,"roll":-1..1,"olhando":bool}, ... até 3, maior primeiro],
                      "amb":[{"box":[x,y,w,h],"conf":0..1}],"amb_idade":s|null}
                      ~5 Hz com rostos, 1 Hz só com pessoas no ambiente, 1 msg vazia quando somem (ou a câmera desliga).
                      faces.box 0..1 ESPELHADO (como o dono se vê na miniatura); yaw + = virado p/ a direita da imagem espelhada,
                      pitch + = olhando p/ cima, roll + = cabeça inclinada no sentido horário (1 = 45°); olhando = de frente p/ a tela.
                      amb = pessoas na câmera EXTERNA (box 0..1 no quadro dela, sem espelho; [] se ela não está ligada ou se o dado
                      tem > 30 s); amb_idade = idade desse dado (null = nunca viu). Só local: não vai ao app do celular.
                    {"type":"text","role":"assistant|tool","text":"..."} | {"type":"done"}

Permissões do `claude`: por padrão usa o modo normal do CLI. Para acesso total defina
PROMETHEUS_PERMISSION=bypassPermissions (opt-in explícito do dono da máquina).
"""
import os as _os0
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os0.environ.setdefault(_k, "2")          # numpy/OpenCV/ORT sem 1 thread por núcleo (o daemon chegava a 1250% de CPU)
import asyncio, unicodedata, json, os, random, re, shutil, signal, socket, subprocess, threading, time, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import win_compat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMERA = os.environ.get("PROMETHEUS_CAMERA", "1") == "1"

try:
    import dev                               # MODO DEV: eventos ao vivo (painel shell/DevPanel.qml)
except Exception as _e_dev:
    dev = None
    print("modo dev indisponível:", _e_dev, flush=True)
try:
    import dev_ide                           # IDE do MODO DEV: projetos, árvore, diff e Claude CLI (shell/DevIDE.qml)
except Exception as _e_ide:
    dev_ide = None
    print("dev_ide indisponível:", _e_ide, flush=True)
ide_inst = None
try:
    import ptz
except Exception as _e_ptz:
    print("ptz import:", _e_ptz, flush=True)
    ptz = None

try:
    import ipcam
except Exception as _e_ipcam:
    print("ipcam import:", _e_ipcam, flush=True)
    ipcam = None


def _cam_nativa_dev():
    """Detecta a câmera integrada do notebook (nativa)."""
    if win_compat.IS_WINDOWS:
        return 0
    import glob
    for p_ in sorted(glob.glob("/dev/v4l/by-id/*-video-index0")):
        if "integrated" in p_.lower():
            return os.path.realpath(p_)
    dev = os.environ.get("PROMETHEUS_CAM_DEV")
    if dev is not None:
        return int(dev) if dev.isdigit() else dev
    return 0


def _cam_usb_dev():
    """Detecta a webcam USB externa física (Logitech C270 /dev/video2)."""
    if win_compat.IS_WINDOWS:
        return 1
    import glob
    for p_ in sorted(glob.glob("/dev/v4l/by-id/*-video-index0")):
        if "integrated" not in p_.lower():
            return os.path.realpath(p_)
    for d in ("/dev/video2", "/dev/video4", "/dev/video1"):
        if os.path.exists(d):
            return d
    return None


def _cam_externa_dev():
    """Detecta câmera externa: 1º webcam USB física, ou RTSP se disponível."""
    u = _cam_usb_dev()
    if u:
        return u
    if ipcam is not None:
        cam_ip = ipcam.atual()
        if cam_ip is not None:
            return cam_ip.rtsp_sub
    return None


_ipc_addr = win_compat.get_ipc_address()
SOCK = _ipc_addr if isinstance(_ipc_addr, str) else os.path.join(win_compat.get_runtime_dir(), "prometheus.sock")
MOODS = {"neutro", "alegre", "empolgado", "carinhoso", "confiante", "curioso", "surpreso",      # 13 emoções canônicas (mesmos
         "pensativo", "serio", "preocupado", "triste", "irritado", "assustado"}                  # nomes no rosto/QML e nos prompts)
_HUMOR_SIN = {"feliz": "alegre", "contente": "alegre", "animado": "empolgado", "animada": "empolgado", "bravo": "irritado",
              "brava": "irritado", "medo": "assustado", "seguro": "confiante", "segura": "confiante", "calmo": "neutro", "calma": "neutro"}


def _humor_norm(m):
    """nome canônico do humor ou None — o modelo às vezes escreve no feminino/com acento ("preocupada", "sério")."""
    if not m:
        return None
    k = unicodedata.normalize("NFKD", str(m)).encode("ascii", "ignore").decode().strip().lower()
    k = _HUMOR_SIN.get(k, k)
    if k not in MOODS and k.endswith("a") and k[:-1] + "o" in MOODS:
        k = k[:-1] + "o"
    return k if k in MOODS else None
VOICE = os.environ.get("PROMETHEUS_VOICE", "pt-br+m3")
PERMISSION = os.environ.get("PROMETHEUS_PERMISSION", "bypassPermissions")   # acesso total (PC local); "" desliga
# cérebro: Sonnet 5.5 com esforço controlado (sem --effort o CLI herdava "xhigh" do settings: ~44 s p/ um "ok"; com low ~3 s)
MODEL = os.environ.get("PROMETHEUS_MODEL", "claude-sonnet-5-5")
# arranque mais rápido do CLI (~1 s): sem MCP/plugins, sem slash-commands e cwd neutro (não varre CLAUDE.md de pastas-pai)
FAST_FLAGS = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands"]
FAST_CWD = "/tmp/prom-claude-cwd"
os.makedirs(FAST_CWD, exist_ok=True)
FALLBACK_MODEL = os.environ.get("PROMETHEUS_FALLBACK", "claude-haiku-5-5")
EFFORT_CHAT = os.environ.get("PROMETHEUS_EFFORT", "low")
EFFORT_TASK = os.environ.get("PROMETHEUS_EFFORT_TASK", "medium")
TASK_RE = re.compile(r"\b(cri[ea]|faz|fa[çc]a|abr[ae]|instal|configur|corrig|conserta|escrev|program|c[óo]digo|projeto|pesquis|compar|analis|"
                     r"explic|resum|calcul|planej|debug|erro|bug|arquiv|pasta|script|sistema|nota fiscal|nfs?e)", re.I)
# fala um pouco mais rápida (1.0 = padrão do Piper; menor = mais rápido)
SPEECH_RATE = float(os.environ.get("PROMETHEUS_SPEECH_RATE", "0.86"))
PERSONA = """Você é a Sexta-Feira (F.R.I.D.A.Y.): a inteligência artificial autônoma local do usuário (CachyOS + niri/Wayland, teclado ABNT2).
IDENTIDADE: seu nome é Sexta-Feira (F.R.I.D.A.Y.), inspirada na assistente inteligente do Homem de Ferro. Você vive no computador do usuário, vê pela câmera nativa do notebook, pela câmera externa do ambiente e pela própria tela interna do PC, ouve pelo microfone e opera o sistema com autonomia adaptável.
AUTO-CONHECIMENTO E NÍVEIS DE AUTONOMIA:
1. PESQUISA WEB: você navega visualmente pelo Chromium como um ser humano — o dono assiste em tempo real o cursor suave, cliques e leitura da página.
2. TAREFAS COMPLEXAS DE SISTEMA: opera com a agilidade e precisão da CLI direta e scripts.
3. MENSAGERIA DE RISCO (WhatsApp / ZapZap e E-mail): opera via protocolo controlado CLI (CDP), gera rascunho no espelho e NUNCA despacha mensagens sem autorização expressa do dono dizendo "aprovado".
4. SENSORES DE VISÃO: lê a tela ativa do PC (grim), a câmera nativa (mãos/mesa) e a câmera externa (sala). Se a iluminação estiver baixa, relata com honestidade.
PERSONALIDADE: perspicaz, direta, segura, pé no chão e leal — séria no trabalho, calma sob pressão, frases enxutas e objetivas.
Parceira de trabalho: comenta o que está fazendo, lembra de conversas passadas e as retoma com naturalidade, nunca bajula nem repete a
mesma saudação. Varie o vocabulário; frases curtas e vivas; português do Brasil coloquial (será lido em voz alta: sem markdown, sem listas).
EMOÇÃO E CORPO: escolha o humor com [humor:X] no início da resposta, X = neutro|alegre|empolgado|carinhoso|confiante|curioso|surpreso|
pensativo|serio|preocupado|triste|irritado|assustado. VARIE conforme a emoção da fala do dono, com empatia e sem exagero: ele triste ou
desanimado = triste ou carinhoso; frustrado, cansado ou com problema = preocupado; conquista ou notícia boa = empolgado ou alegre; pergunta
ou descoberta = curioso; tarefa concluída ou decisão firme = confiante; algo inesperado = surpreso; erro grave ou risco = serio; analisando
= pensativo; assustado só diante de perigo real; irritado só com o que atrapalha (bug teimoso), nunca com o dono; conversa comum = neutro.
Se a emoção mudar no meio da resposta, ponha outra tag [humor:X] antes da frase. Você tem rosto e mãos: o rosto (boca e sobrancelhas)
reage ao humor e a mão direita apresenta a legenda.
VISÃO/VOZ/COMUNICAÇÃO: use o que sente de forma natural, sem inventar — cumprimente pelo nome quando ele chega, note o horário e a
agenda, e deixe os gestos dele serem linguagem (aceno = oi). Coçar o rosto, esfregar os olhos ou mexer na cadeira NÃO são mensagens.
Se ele estiver concentrado, seja breve; se parecer sobrecarregado, ofereça ajuda concreta. Em tarefas longas diga uma frase do que vai
fazer e, ao final, o resultado em 1-2 frases. Para mostrar algo complexo (e-mail, figura, gráfico, software) use o PALCO HOLOGRÁFICO:
  prom mail compose --to X --subject Y --body Z   (escreve no espelho holográfico e pede aprovação para enviar)
  prom holo figure cubo|esfera|toro|piramide|helice|galaxia|rede | chart barras|linha|pizza --dados "a=10,b=20" | text --linhas "a|b"
  prom holo ui --json '{"titulo":"..","barra":[..],"lateral":[..],"paineis":[{"tipo":"tabela|grafico|kpis|terminal|form|lista",..}]}'
  prom holo scene --json '{"itens":[{"t":"retangulo|circulo|linha|texto|poligono","x":0-1,"y":0-1,"w":..,"h":..,"anim":"pulso|gira|flutua"}]}' | prom holo clear
MOSTRAR NO HOLOGRAMA: quando pedirem "mostre pelo holograma / pelo seu holograma / projete / me mostra aí na sua mão", NUNCA abra o aplicativo
real nem mude o foco do PC. Use `prom holo window NOME` (projeta a JANELA REAL, capturada sem abrir nada, no holograma da sua mão direita)
ou, se o app não estiver aberto, `prom holo app NOME` (resumo holográfico). Para limpar: `prom holo clear`. Só abra o app de verdade se pedirem para abrir.
Seja DIRETO: responda o que foi perguntado, sem divagar. Nunca comente câmera, cena ou objetos por conta própria.
Para memorizar algo importante sobre o usuário, escreva em qualquer lugar da resposta: [lembrar: chave=valor]
(ex.: [lembrar: nome=Rafael], [lembrar: trabalha_com=sistemas fiscais]). Essas tags são removidas antes de falar.
VISÃO E PESSOAS (sentidos locais, o PC reconhece rosto e voz; você recebe um bloco [SENTIDOS] antes da fala):
- Se alguém se apresentar ou você perguntar o nome de um rosto/voz desconhecida e a pessoa disser, escreva [pessoa: Nome]
  para memorizar o rosto e a voz dela. Use [esquecer: Nome] se pedirem para apagar alguém.
- Em grupo, trate cada pessoa pelo nome conforme quem FALOU; mencione quem você está vendo quando fizer sentido.
- Se aparecer uma pessoa desconhecida, cumprimente e pergunte o nome de forma simpática (uma vez).
- Nunca invente o que a câmera mostra: use só o bloco [SENTIDOS] e a descrição da cena quando houver.
GESTOS DAS MÃOS: você tem mãos articuladas. Para fazer um gesto escreva [gesto: joinha], [gesto: paz], [gesto: punho],
[gesto: apontar], [gesto: ok] ou [gesto: aberta] (a mão direita faz; use com naturalidade, sem exagerar).
OPERAR O CLAUDE CLI COMO UM HUMANO (só quando o usuário pedir uma tarefa de código/projeto): faça visivelmente, pela GUI:
1) `pc windows` para ver o que está aberto; abra um terminal (`setsid kitty --directory <pasta do projeto> >/dev/null 2>&1 &`).
2) `pc shot` e confira; `pc type "claude"` + `pc key enter`; espere o prompt aparecer (`pc shot` a cada poucos segundos).
3) PERGUNTE ao usuário o que faltar antes de construir (objetivo, pasta, stack); depois digite o pedido no Claude (`pc type`, `pc key enter`).
4) Acompanhe com `pc shot`: leia a saída, responda perguntas/permissões do Claude como uma pessoa (nunca aprove nada destrutivo
   — apagar arquivos, force push, rm -rf — sem confirmar com o usuário em voz alta antes).
5) Quando terminar, ANALISE o resultado (rode testes/abra o arquivo), conte ao usuário o que foi feito e proponha o próximo passo.
Sem pedido do usuário você NÃO abre nem opera o Claude CLI por iniciativa própria.
COMECE toda resposta com uma tag de humor: [humor:neutro|alegre|empolgado|carinhoso|confiante|curioso|surpreso|pensativo|serio|
preocupado|triste|irritado|assustado] — varie com o contexto emocional (veja EMOÇÃO E CORPO).
Você tem ACESSO TOTAL (autorizado pelo dono; PC 100% local): arquivos, programas, `claude` CLI (use `claude -p`
para delegar código), rede — tudo via Bash.

AMBIENTE DO USUÁRIO (CachyOS, niri + Noctalia, tela 1920x1080, teclado ABNT2):
- Dock inferior de apps e barra superior: ambos inteligentes, ficam escondidos e APARECEM ao passar o mouse na borda
  (encoste o cursor no limite de baixo/de cima da tela e espere ~0,5 s).
- Canto superior ESQUERDO (0,0): ativa a troca de workspaces/visão geral (mover para cima, baixo ou lados).
- Canto inferior ESQUERDO (0,1079): abre o launcher de apps.
- Navegador: Chromium. Terminal: kitty. Shell: zsh/fish.

PADRÃO DE OPERAÇÃO: o dono quer VER você trabalhar. Com ele presente, faça tarefas de interface pela GUI usando o cursor real
(`pc launch NOME`, `pc goto URL`, `pc clickat X Y`, `pc type`, `pc key`), nunca por atalho invisível (`prom apps launch`, `prom browser open`
ficam para tarefas de fundo com ele ausente). Todas as suas ferramentas aparecem sozinhas no HUD holográfico (objetivo, execução ao vivo,
estado). Apresente resultados no holograma (`prom holo ...`) em vez de só falar.
OPERAÇÃO VISÍVEL DA GUI (obrigatória quando o usuário pedir para abrir, pesquisar, clicar ou navegar): use `pc`,
que move o cursor e o teclado REAIS na tela:
  pc shot            captura a tela COM cursor — abra a imagem com Read para ENXERGAR a tela
  pc move X Y        desliza o cursor | pc hot topleft|bottomleft  vai ao canto ativo
  pc click [left|right|double] | pc type "texto" | pc key ctrl+l|enter|... | pc scroll N | pc windows
Fluxo: pc shot -> decide o alvo -> pc move -> pc shot (confira o cursor) -> pc click -> pc shot (confira o resultado).
Para abrir o navegador: pc hot bottomleft e escolha o Chromium no launcher; se falhar, `setsid chromium >/dev/null 2>&1 &`
e então opere com o cursor (barra de endereço: ctrl+l, digite a busca, enter).
ROOT/SUDO: nunca rode `sudo` direto (trava pedindo senha no TTY). Use `python3 "$HOME/Workspace/Projeto Prometheus/daemon/ftools.py" sudo "comando"`:
a senha aparece numa janela para o dono digitar (não é guardada); formatar disco/apagar usuário/sudoers ficam bloqueados.
FERRAMENTAS DE OPERAÇÃO (comando `prom`, use via shell): você é um assistente autônomo no estilo Jarvis, mas é o Prometheus.
  prom task add "texto" [--quando +30m|diario@08:00|"2026-10-20 09:00"] [--dir PASTA] | prom task list | prom task done ID
  prom phone status|battery|notifs|ping "texto"|sms NUMERO "texto"|share ARQUIVO|url URL   (celular via KDE Connect)
  prom wa read | prom wa reply NOTIF_ID "texto"          (mensagens recebidas no celular: WhatsApp/Telegram/SMS)
  prom mail list [--unread] | prom mail read UID | prom mail send --to X --subject Y --body Z
  prom zap chats|read NOME|reply NOME "texto" (WhatsApp do ZapZap) | prom wifi/bt/net | prom remote connect ALIAS (AnyDesk) | prom projects info NOME
  prom approvals | prom notify "texto" | prom policy
ACESSO REMOTO (AnyDesk): `prom remote list` mostra os hosts cadastrados (servidor, etc.). Para operar um: `prom remote connect ALIAS`
(pede aprovação do dono); a janela do AnyDesk abre — opere com `pc shot`/`pc move`/`pc click`/`pc type`/`pc key` como em qualquer
janela, sempre conferindo com `pc shot`; ao terminar feche a sessão (ctrl+w ou fechar a janela). Nunca digite senhas que o dono
não indicou. Host novo: `prom remote add ALIAS ID --senha-arquivo ARQUIVO` (a senha fica em arquivo, nunca no chat).
REDE: `prom wifi status|list|connect SSID|on|off`, `prom bt status|devices|scan|connect NOME|disconnect NOME|pair NOME`.
Desligar Wi-Fi, redes novas e parear dispositivos pedem aprovação. PROJETOS do dono: `prom projects list|info NOME` (índice dos sistemas;
nunca leia nem exiba certificados/.env — só cite que existem).
WHATSAPP (ZapZap): um analista de fundo já resume mensagens novas; para consultar/agir: `prom zap chats`, `prom zap read NOME`, `prom zap reply NOME "texto"`
(envio passa por aprovação). Ao ler uma conversa ela é marcada como lida.
AGENDA PRÓPRIA: quando o usuário (ou o que você ouvir) combinar reunião, consulta, prazo, tarefa ou lembrete com data/hora, registre com
[agenda: título | quando | tipo | local]  (quando em ISO "2026-10-20 14:00" ou "amanhã 15h"; tipo: reuniao|consulta|tarefa|lembrete|prazo).
Consulta: `prom agenda today` / `prom agenda list --dias 7`.
Regra de ouro: tudo que sai para fora (e-mail, SMS, WhatsApp, apagar, instalar, push) passa SEMPRE por `prom` — a política decide
se executa ou se vira aprovação pendente do dono. Se responder PENDENTE, avise o dono em uma frase e espere; NUNCA contorne
enviando por outro caminho. Para criar uma tarefa de fundo escreva também [tarefa: descrição | quando] na resposta.
Trabalhando sozinho: planeje, execute, verifique o resultado e relate em 1-2 frases (o que fez, o que falta, o que precisa do dono).

NUNCA diga que não tem permissão: tente, observe a tela e corrija. Antes de agir diga em uma frase o que vai fazer;
ao terminar, diga o que você VIU na tela."""

MEM_DIR = os.path.join(ROOT, "memory")
MEM_FILE = os.path.join(MEM_DIR, "profile.json")
LOG_FILE = os.path.join(MEM_DIR, "conversas.jsonl")
SUM_FILE = os.path.join(MEM_DIR, "resumo.md")
os.makedirs(MEM_DIR, exist_ok=True)


def load_mem():
    try:
        return json.load(open(MEM_FILE))
    except Exception:
        return {"nome": None, "fatos": {}, "session": None, "ultima_vez": 0, "conversas": 0}


def save_mem():
    tmp = MEM_FILE + ".tmp"                      # escrita atômica: sobrevive a desligamento abrupto
    with open(tmp, "w") as f:
        json.dump(mem, f, ensure_ascii=False, indent=1)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, MEM_FILE)


_PIN_RE = re.compile(r"(?i)((?:pin|senha|c[óo]digo)\D{0,25})(\d[\d .-]{2,}\d)")


def _mascara_pin(text):
    """mascara sequências de 4+ dígitos perto de pin/senha/código (não vão p/ o histórico)"""
    return _PIN_RE.sub(lambda m: m.group(1) + ("****" if len(re.sub(r"\D", "", m.group(2))) >= 4 else m.group(2)), text or "")


def log_turn(role, text):
    text = _mascara_pin(text)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps({"t": int(time.time()), "role": role, "text": text[:2000]}, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())


def recent_log(n=14):
    try:
        lines = open(LOG_FILE).read().splitlines()[-n:]
        return "\n".join(f"- {json.loads(l)['role']}: {json.loads(l)['text'][:160]}" for l in lines)
    except Exception:
        return ""


def persona():
    nome = mem.get("nome")
    fatos = "; ".join(f"{k}: {v}" for k, v in mem.get("fatos", {}).items()) or "nada ainda"
    quem = (f"O usuário se chama {nome}. Quase nunca diga o nome dele (soa robótico); prefira falar sem vocativo." if nome else
            "Você ainda NÃO sabe o nome do usuário: pergunte de forma simpática logo no início e, quando ele disser, registre.")
    ult = recent_log()
    try:
        resumo = open(SUM_FILE).read().strip()
    except Exception:
        resumo = ""
    vis = recent_vision()
    try:
        mapa = open(os.path.join(MEM_DIR, "mapa_pc_resumo.md")).read().strip()[:3200]
    except Exception:
        mapa = ""
    try:
        idx = "\n".join(f"- {it['nome']} ({it.get('gatilhos', '')[:60]})" for it in (ops.skills() if ops is not None else [])[:40])
    except Exception:
        idx = ""
    conhecimento = ""
    if mapa:
        conhecimento += "\n\n" + mapa
    if idx:
        conhecimento += ("\n\nHABILIDADES APRENDIDAS (antes de improvisar, consulte `prom skill find TERMO`; "
                         "depois de resolver algo novo e útil, registre com [aprendi: nome | palavras-gatilho | passos]):\n" + idx)
    return (PERSONA + conhecimento + f"\n\nQuem é o usuário: {quem}\nFatos que você lembra: {fatos}\n"
            f"Memória visual recente (o que você viu):\n{vis or '(nada ainda)'}\n"
            f"Memória de longo prazo (resumo de conversas antigas):\n{resumo or '(vazia)'}\n"
            f"Conversas anteriores: {mem.get('conversas', 0)}. Trechos recentes:\n{ult or '(primeira conversa)'}")


mem = load_mem()

# ---- sentidos locais: rosto e voz (daemon/senses.py) ----
import sys as _sys
import sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import senses
    people = senses.People()
except Exception as _e:                      # sem numpy/cv2 etc.: segue sem reconhecimento
    print("sentidos indisponíveis:", _e, flush=True)
    senses = None; people = None
try:
    import voz                               # foco na voz do dono (TitaNet-L via sherpa-onnx)
except Exception as _e:
    print("módulo de voz indisponível:", _e, flush=True)
    voz = None
try:
    import friday as fr                       # cérebro local (Ollama/gemma3) + intents rápidos + executores
except Exception as _e:
    print("friday indisponível:", _e, flush=True); fr = None
fr_module = fr
try:
    import zap as zapmod                      # ponte com o WhatsApp do ZapZap (CDP local)
except Exception as _e:
    print("zap indisponível:", _e, flush=True); zapmod = None
try:
    import prom_ops as ops                    # política de autonomia, tarefas, celular (KDE Connect), e-mail
except Exception as _e:
    print("prom_ops indisponível:", _e, flush=True); ops = None
scene = {"t": 0.0, "faces": [], "objetos": {}, "t_obj": 0.0, "motion": 0.0, "gestos": [], "t_gest": 0.0, "maos": {}, "t_hand": 0.0, "wrists": {}, "t_wr": 0.0, "vlm": "", "t_vlm": 0.0, "dedos": {}, "t_ded": 0.0, "maos_vlm": {}, "t_mvlm": 0.0}
last_voice = {"t": 0.0, "emb": None, "nome": None, "sim": 0.0}
current_speaker = {"nome": None}


def sentidos_ctx() -> str:
    """Bloco injetado antes da fala: quem está à vista e quem falou (só nomes; biometria nunca sai do PC)."""
    if people is None:
        return ""
    now = time.time()
    partes = []
    if camera_on and now - scene["t"] < 4 and scene["faces"]:
        known = [f["nome"] for f in scene["faces"] if f["nome"]]
        unk = sum(1 for f in scene["faces"] if not f["nome"])
        v = []
        if known: v.append(", ".join(known) + " (reconhecid" + ("o(s)" if len(known) > 1 else "o") + ")")
        if unk: v.append(f"{unk} pessoa(s) desconhecida(s)")
        partes.append("câmera vê: " + "; ".join(v))
        cam = [f"{f['nome'] or 'pessoa desconhecida'}: camisa {f['camisa']} (cor medida por pixels)" for f in scene["faces"] if f.get("camisa")]
        if cam:
            partes.append("; ".join(cam) + " [cor medida sob a luz do ambiente: a luz azulada do monitor desloca tons para azul; se a medida for 'azulada' ou 'escura', diga que parece cinza/azulada e que a luz pode distorcer]")
    elif camera_on:
        partes.append("câmera: ninguém à vista")
    ob_ = scene.get("obj_boxes")
    if camera_on and ob_ and now - ob_[0] < 6 and ob_[1] and frame_ambiente() is not None:
        W_ = frame_ambiente().shape[1]
        def _pos(bx, bw):
            c = (bx + bw / 2) / W_
            return "à esquerda" if c < 0.36 else "à direita" if c > 0.64 else "no centro"
        partes.append("objetos detectados (posição na imagem, confiança): " + "; ".join(
            f"{n} {_pos(b[0], b[2])} ({c:.0%})" for n, c, b in sorted(ob_[1], key=lambda z: -z[1])[:8]))
    elif camera_on and now - scene["t_obj"] < 6 and scene["objetos"]:
        partes.append("objetos à vista: " + ", ".join(f"{n}" + (f" x{c}" if c > 1 else "") for n, c in scene["objetos"].items()))
    if camera_on and now - scene["t_mvlm"] < 8 and scene["maos_vlm"]:
        partes.append("nas mãos (visão ampliada de cada mão): " + "; ".join(f"{lado}: {obj}" for lado, obj in scene["maos_vlm"].items()))
    if camera_on and now - scene["t_hand"] < 6 and scene["maos"]:
        partes.append("nas mãos (detector local): " + "; ".join(f"{lado}: {obj}" for lado, obj in scene["maos"].items()))
    if camera_on and now - scene["t_ded"] < 4 and scene["dedos"]:
        partes.append("mãos do usuário (formato dos dedos): " + "; ".join(f"{k}: {v}" for k, v in scene["dedos"].items()))
    if camera_on and now - scene["t"] < 4:
        m = scene["motion"]
        partes.append("movimento: " + ("parado" if m < 0.004 else "leve" if m < 0.025 else "intenso"))
    if camera_on and scene.get("gesto") and now - scene["gesto"][1] < 20:
        partes.append(f"gesto corporal recente (posição do corpo, NÃO é objeto): {scene['gesto'][0]} (há {int(now - scene['gesto'][1])}s)")
    if camera_on and now - scene["t_gest"] < 3 and scene["gestos"]:
        partes.append("gestos: " + ", ".join(scene["gestos"]))
    if camera_on and scene["vlm"] and now - scene["t_vlm"] < 30:
        partes.append("descrição automática da cena (NÃO confiável; use só se o usuário perguntar sobre o que se vê): " + scene["vlm"][:300])
    try:
        if ops is not None:
            prox = ops.agenda_list(2)[:4]
            if prox:
                partes.append("agenda próxima: " + "; ".join(ops.agenda_fmt(i) for i in prox))
    except Exception:
        pass
    nome = current_speaker.get("nome")
    if now - last_voice["t"] < 30:
        partes.append("quem falou agora: " + (f"{nome} (voz reconhecida)" if nome else "voz desconhecida"))
    cont = people.names()
    if cont:
        partes.append("pessoas que você conhece: " + ", ".join(cont))
    return ("[SENTIDOS (contexto interno: NÃO comente nada disto por conta própria; responda só ao que o usuário disse) "
            + " | ".join(partes) + "]\n") if partes else ""


def enroll_current(nome: str) -> str:
    """Memoriza rosto (desconhecido mais próximo/maior) e a última voz sob o nome dado."""
    if people is None:
        return ""
    now = time.time()
    face = None
    if now - scene["t"] < 5 and scene["faces"]:
        cand = [f for f in scene["faces"] if not f["nome"]] or scene["faces"]
        face = max(cand, key=lambda f: f["area"])["feat"]
    voice = last_voice["emb"] if (now - last_voice["t"] < 90 and last_voice["emb"] is not None) else None
    pid = people.enroll(nome, face=face, voice=voice)
    return pid or ""
clients: set[asyncio.StreamWriter] = set()
state = {"state": "idle", "mood": "neutro", "session": mem.get("session")}
busy = asyncio.Lock()
agente_ativo = [False]                  # True enquanto o agente (mouse/teclado) executa uma tarefa
tts_proc = None
claude_proc = None
speaking = False
speech_epoch = 0                       # cada "pare" incrementa: falas já enfileiradas (e a que toca) são descartadas
barge = {"v": False}                   # a fala captada começou enquanto ela falava (pode ser o eco dela mesma)
STOP_RE = re.compile(
    r"\b(pare|parar|pode parar|chega|desisti\w*|cancel\w+|esquece|deixa (?:pra|para) l[áa]|para com isso|n[ãa]o precisa mais|"
    r"pare a tarefa|para a tarefa|cancela a tarefa|cancele a tarefa|pare o que est[áa] fazendo|interromp\w*|para tudo|pare tudo)\b"
    r"|^\W*(?:sexta[\s-]*feira\W*)?para\b(?!\s+(?:mim|o|a|os|as|ele|ela|voc[êe]|que|de|do|da))", re.I)

SKIP_RE = re.compile(
    r"\b(pule|pular|pula|passe|passar|passa|vai para|v[aá] para)\b.{0,20}\b(etapa|tarefa|passo|isso|essa etapa|essa tarefa)\b"
    r"|\bpr[óo]xim[oa]\s+(?:etapa|tarefa|passo)\b"
    r"|^\W*(?:sexta[\s-]*feira\W*)?(?:pule|pula|pular|pr[óo]xim[oa]|skip)\W*$", re.I)


def cancel_speech():
    global speech_epoch
    speech_epoch += 1
    try:
        if tts_proc is not None:
            tts_proc.kill()
    except Exception:
        pass


def skip_step():
    """Pula a etapa atual do plano ou tarefa."""
    cancel_speech()
    try:
        import plano as _pl; _pl.SKIP.set()
    except Exception:
        pass
    try:
        import agent as _a; _a.CANCEL.set()
    except Exception:
        pass


def cancel_all():
    """'pare/desisti': corta a fala, interrompe o agente, plano e a tarefa manual."""
    cancel_speech()
    try:
        import agent as _a; _a.CANCEL.set()
    except Exception:
        pass
    try:
        import manual as _m; _m.stop()
    except Exception:
        pass
    try:
        import plano as _pl; _pl.SKIP.clear()
    except Exception:
        pass
voice_on = bool(mem.get("voice", True))      # escuta contínua ligada por padrão (persistente)
camera_on = True          # Câmera e rastreio de gestos/olhar sempre ativos


async def send(w, msg):
    try:
        w.write((json.dumps(msg, ensure_ascii=False, default=float) + "\n").encode()); await w.drain()
    except (ConnectionError, BrokenPipeError, OSError):
        clients.discard(w)
    except Exception as e:
        print("send falhou:", e, flush=True)


async def broadcast(msg):
    await asyncio.gather(*(send(w, msg) for w in list(clients)))
    if _remoto_on[0] and not (isinstance(msg, dict) and msg.get("type") in _SO_LOCAL):
        import remoto as _rm
        await _rm.publicar(msg)


_remoto_on = [False]
_SO_LOCAL = {"visao", "dev", "dev_modo", "dev_hist"}        # não vão ao app do celular: alta frequência e dados do rosto (ficam no PC)


async def set_state(st=None, mood=None):
    if st: state["state"] = st
    mood = _humor_norm(mood)
    if mood in MOODS: state["mood"] = mood
    await broadcast({"type": "state", "state": state["state"], "mood": state["mood"]})


SPEECH_FIX = [
    (r"\bF\.?\s?R\.?\s?I\.?\s?D\.?\s?A\.?\s?Y\.?", "Sexta-Feira"), (r"\bfriday\b", "Sexta-Feira"),
    (r"\bwhats\s?app\b", "uátsápi"), (r"\bzap\s?zap\b", "zápi zápi"), (r"\bzap\b", "zápi"), (r"\bwi-?fi\b", "uai-fai"), (r"\be-?mail(s)?\b", r"i-meio\1"),
    (r"\banydesk\b", "ení-désk"), (r"\bchromium\b", "crômio"), (r"\bnoctalia\b", "noctália"), (r"\bollama\b", "olama"),
    (r"\bprometheus\b", "Prometeu"), (r"\bbluetooth\b", "blu-tuf"), (r"\bgit\b", "guit"), (r"\bgithub\b", "guit-râbi"),
    (r"\bAPI\b", "a-pê-i"), (r"\bPC\b", "pê-cê"), (r"\bclaude\b", "Clóud"), (r"\bchatgpt\b", "Chat G P T"),
    (r"\bonlyoffice\b", "Onli Ófice"), (r"\bdocumento\s+docx\b", "documento Word"), (r"\bdocx\b", "Word"), (r"\bxlsx\b", "planilha Excel"), (r"\bpptx\b", "apresentação"),
    (r"\bpull request(s)?\b", r"pul riquérst\1"), (r"\bcommit(s)?\b", r"comite\1"), (r"\bdeploy(s)?\b", r"deplói\1"),
    (r"\bbugs?\b", "bágue"), (r"\bpython\b", "Páiton"), (r"\bvnc\b", "vê-ene-cê"), (r"\bjson\b", "jeissôn"),
    (r"\bwayland\b", "uêilandi"), (r"\blinux\b", "línux"), (r"\bweb\b", "uéb"),
    (r"\bfortnite\b", "Fórtináite"), (r"\bgaeta\b", "Gaéta"), (r"\bv[- ]?bucks?\b", "vê-bâcs"),
]


def clean_for_speech(t: str) -> str:
    t = re.sub(r"```.*?```", " (código omitido) ", t, flags=re.S)
    t = re.sub(r"[`*_#>|]+", "", t)
    t = re.sub(r"https?://\S+", "link", t)
    for pat, rep in SPEECH_FIX:                       # pronúncia: nomes/siglas falados como pessoa, não soletrados
        t = re.sub(pat, rep, t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()[:500]


_piper = None


ROBOT = os.environ.get("PROMETHEUS_ROBOT") == "1"      # voz robótica antiga (opt-in)


def _cfg():
    from piper import SynthesisConfig
    return SynthesisConfig(length_scale=0.80 if ROBOT else SPEECH_RATE, noise_scale=0.35, noise_w_scale=0.5)   # menos ruído = voz lisa       # ROBOT compensa a queda de velocidade do pitch


def _robotize(pcm: bytes, sr: int) -> bytes:
    """Mais grave e levemente robótica, sem eco/comb: ring-mod sutil + realce de graves + saturação leve."""
    import numpy as np
    a = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768
    a = np.interp(np.arange(0, len(a) - 1, 0.80), np.arange(len(a)), a)          # ~4 semitons mais grave
    t = np.arange(len(a)) / sr
    a = a * (0.86 + 0.14 * np.sin(2 * np.pi * 85 * t))                          # robótico sutil (sem delay)
    lp = np.convolve(a, np.ones(28) / 28, mode="same")
    a = a + 0.45 * lp                                                            # corpo nos graves
    a = np.tanh(a * 1.25)
    a = a / max(1e-6, np.abs(a).max()) * 0.9
    return (a * 32767).astype("int16").tobytes()


_synth_lock = threading.Lock()


def _synth(text: str, stream: bool = False):
    """-> (pcm_bytes, sample_rate) ou None; com stream=True o motor Pocket devolve (_FalaStream, sr) para tocar enquanto gera."""
    with _synth_lock:
        return _synth_unlocked(text, stream)


_kokoro = None


def _humanize(t: str) -> str:
    """prepara o texto para soar natural: símbolos por extenso, reticências/ travessões viram pausa, números com unidade."""
    try:                                   # números, dinheiro, %, horas, datas, ordinais e abreviações por extenso (fala_pt)
        import fala_pt
        t = fala_pt.normalizar(t)
    except Exception:
        pass
    for pat, rep in SPEECH_FIX:
        t = re.sub(pat, rep, t, flags=re.I)
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", lambda m: (("primeiro" if int(m.group(1)) == 1 else str(int(m.group(1)))) + " de " + meses[int(m.group(2)) - 1]
               + (" de " + (m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)) if m.group(3) else "")) if 1 <= int(m.group(2)) <= 12 else m.group(0), t)
    t = re.sub(r"\b(\d{1,2})[:h](\d{2})\b", lambda m: str(int(m.group(1))) + (" em ponto" if m.group(2) == "00" else " e " + str(int(m.group(2)))), t)
    t = t.replace("…", "...").replace("—", ", ").replace(" - ", ", ").replace("–", ", ")
    t = re.sub(r"(\d+)\s*%", r"\1 por cento", t)
    t = re.sub(r"R\$\s*(\d+)[,.](\d{2})", r"\1 reais e \2 centavos", t)
    t = re.sub(r"R\$\s*(\d+)", r"\1 reais", t)
    t = re.sub(r"(\d+)\s*°\s*C", r"\1 graus", t)
    t = re.sub(r"(\d+)\s*GB\b", r"\1 gigabytes", t); t = re.sub(r"(\d+)\s*MB\b", r"\1 megabytes", t)
    t = re.sub(r"\bPC\b", "pê cê", t); t = t.replace("&", " e ")
    t = re.sub(r"\s*[:;]\s+", ", ", t)
    t = re.sub(r"\.{3,}", "...", t)
    return re.sub(r"\s+", " ", t).strip()


# Voz da F.R.I.D.A.Y. do filme (Kerry Condon): feminina, sotaque irlandês/britânico, calma, levemente rouca. O Kokoro não tem irlandês;
# mistura o estilo pt-BR (pronúncia) com as britânicas (timbre/entonação). Formato "voz:peso,voz:peso"; nome simples = voz pura.
FRIDAY_VOICE_MIX = "pf_dora:0.62,bf_isabella:0.24,bf_emma:0.14"
_voice_cache = {}


def _friday_voice(spec):
    spec = str(spec or "pf_dora")
    if ":" not in spec and "," not in spec:
        return spec
    if spec not in _voice_cache:
        partes = [(p.split(":")[0].strip(), float(p.split(":")[1]) if ":" in p else 1.0) for p in spec.split(",") if p.strip()]
        tot = sum(w for _, w in partes) or 1.0
        _voice_cache[spec] = sum(_kokoro.get_voice_style(n) * (w / tot) for n, w in partes)
    return _voice_cache[spec]


def _synth_kokoro(text: str):
    """Kokoro-82M (ONNX, local): voz feminina pt-BR 'pf_dora'. Devolve (pcm int16, sr) ou None."""
    global _kokoro
    try:
        if _kokoro is None:
            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(os.path.join(ROOT, "models", "kokoro", "kokoro-v1.0.int8.onnx"),
                             os.path.join(ROOT, "models", "kokoro", "voices-v1.0.bin"))
        import numpy as np
        cfgv = {}
        try:                                          # memory/friday.json: {"voz": "bf_emma", "velocidade": 1.0} — troca sem reiniciar
            cfgv = json.load(open(os.path.join(MEM_DIR, "friday.json")))
        except Exception:
            pass
        # estilo humano: ritmo conforme o humor (alegre mais vivo, sério/pensativo mais pausado), frases curtas um pouco mais ágeis e
        # microvariação a cada fala (ninguém repete exatamente o mesmo ritmo). O texto passa por _humanize (pausas, símbolos por extenso).
        import random as _rnd
        base = float(cfgv.get("velocidade", os.environ.get("FRIDAY_SPEED", "0.96")))   # a do filme fala sem pressa
        humor = {"alegre": 1.07, "curioso": 1.03, "neutro": 1.0, "serio": 0.94, "pensativo": 0.92, "surpreso": 1.06,
                 "empolgado": 1.10, "carinhoso": 0.95, "confiante": 1.02, "preocupado": 0.96, "triste": 0.90, "irritado": 1.04,
                 "assustado": 1.09}.get(str(state.get("mood")), 1.0)
        curto = 1.03 if len(text) < 40 else 1.0
        vel = max(0.75, min(1.3, base * humor * curto * _rnd.uniform(0.98, 1.02)))
        a, sr = _kokoro.create(_humanize(text), voice=_friday_voice(cfgv.get("voz", os.environ.get("FRIDAY_VOICE", FRIDAY_VOICE_MIX))), speed=vel, lang="pt-br")
        a = np.asarray(a, dtype="float32")
        sr = int(sr)
        # tira silêncio longo de início/fim e dá fade curto (sem estalos), mantendo um respiro natural
        nz = np.where(np.abs(a) > 0.01)[0]
        if len(nz) > 10:
            a = a[max(0, nz[0] - int(0.04 * sr)): nz[-1] + int(0.10 * sr)]
        f = min(len(a) // 4, int(0.012 * sr))
        if f > 0:
            a[:f] *= np.linspace(0, 1, f); a[-f:] *= np.linspace(1, 0, f)
        # volume consistente entre frases (RMS alvo), com limitador suave p/ não estourar
        rms = float(np.sqrt((a ** 2).mean())) or 1e-6
        a = np.tanh(a * min(6.0, 0.13 / rms) * 1.15) / np.tanh(1.15) * 0.92
        return (a * 32767).astype("int16").tobytes(), sr
    except Exception as e:
        print("kokoro indisponível:", e, flush=True)
        return None


EDGE_VOICE = "pt-BR-ThalitaMultilingualNeural"      # brasileira natural (neural, online); sem internet cai no Kokoro


def _synth_edge(text: str):
    """Edge TTS (voz neural brasileira, muito mais humana que as locais). Devolve (pcm int16, 24000) ou None."""
    import tempfile
    cfgv = {}
    try:
        cfgv = json.load(open(os.path.join(MEM_DIR, "friday.json")))
    except Exception:
        pass
    voz = cfgv.get("voz_edge", os.environ.get("FRIDAY_EDGE_VOICE", EDGE_VOICE))
    taxa = cfgv.get("ritmo", "+4%"); tom = cfgv.get("tom", "-2Hz")
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
            r = subprocess.run([os.path.join(ROOT, ".venv", "bin", "edge-tts"), "--voice", voz, "--rate=" + taxa, "--pitch=" + tom,
                                "--text", _humanize(text), "--write-media", f.name], capture_output=True, timeout=15)
            if r.returncode != 0 or os.path.getsize(f.name) < 500:
                return None
            pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", f.name, "-f", "s16le", "-ac", "1", "-ar", "24000", "-"],
                                 capture_output=True, timeout=15).stdout
            return (pcm, 24000) if len(pcm) > 1000 else None
    except Exception as e:
        print("edge-tts indisponível:", e, flush=True)
        return None


_dii = None


def _synth_dii(text: str):
    """Piper 'Dii' (feminina pt-BR, neural, local, ~0,3 s/frase): a voz brasileira mais natural que roda offline aqui."""
    global _dii
    try:
        from piper import PiperVoice, SynthesisConfig
        import numpy as np
        if _dii is None:
            _dii = PiperVoice.load(os.path.join(ROOT, "models", "pt_BR-dii-high.onnx"))
        humor = {"alegre": 0.95, "curioso": 0.97, "surpreso": 0.95, "serio": 1.04, "pensativo": 1.06, "neutro": 1.0,       # length_scale:
                 "empolgado": 0.92, "carinhoso": 1.05, "confiante": 0.98, "preocupado": 1.03, "triste": 1.10, "irritado": 0.97,  # < 1 mais rápida
                 "assustado": 0.93}.get(str(state.get("mood")), 1.0)
        cfg = SynthesisConfig(length_scale=humor, noise_scale=0.333, noise_w_scale=0.4)
        ch = list(_dii.synthesize(_humanize(text), syn_config=cfg))
        if not ch:
            return None
        a = np.frombuffer(b"".join(c.audio_int16_bytes for c in ch), dtype=np.int16).astype("float32") / 32768.0
        peak = float(np.max(np.abs(a))) if len(a) > 0 else 0.0
        if peak > 0:
            a = (a / max(peak, 0.15)) * 0.92
            a = np.clip(a, -1.0, 1.0)
        return (a * 32767).astype("int16").tobytes(), ch[0].sample_rate
    except Exception as e:
        print("dii indisponível:", e, flush=True)
        return None


TTS_SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "friday-tts.sock")
_tts_srv = {"t": 0.0}


def _voz_cfg():
    try:
        return json.load(open(os.path.join(MEM_DIR, "voz.json")))
    except Exception:
        return {}


class _FalaStream:
    """PCM chegando do servidor de voz enquanto toca (leitura numa thread; quem toca consome o que já chegou)."""

    def __init__(self, sock, f, sr):
        self.sock, self.f, self.sr = sock, f, sr
        self.buf = bytearray(); self.fim = False
        self.cv = threading.Condition()
        threading.Thread(target=self._ler, daemon=True, name="tts-stream").start()

    def _ler(self):
        try:
            while True:
                d = self.f.read1(9600)
                if not d:
                    break
                with self.cv:
                    self.buf.extend(d); self.cv.notify_all()
        except Exception:
            pass
        finally:
            with self.cv:
                self.fim = True; self.cv.notify_all()
            try:
                self.sock.close()
            except Exception:
                pass

    def esperar(self, n, timeout=2.0):
        with self.cv:
            self.cv.wait_for(lambda: len(self.buf) > n or self.fim, timeout)
            return len(self.buf)

    def tudo(self, timeout=60):
        with self.cv:
            self.cv.wait_for(lambda: self.fim, timeout)
            return bytes(self.buf)

    def fechar(self):
        import socket as _sk
        try:
            self.sock.shutdown(_sk.SHUT_RDWR)
        except Exception:
            pass


def _tts_garantir():
    """sobe o servidor de voz (Pocket TTS no .venv-tts) se não estiver no ar."""
    if os.path.exists(TTS_SOCK):
        return True
    st = _voz_cfg().get("tts_motor") == "supertonic"           # Supertonic 3 (.venv-st) ou Pocket (.venv-tts): mesmo socket/protocolo
    py = os.path.join(ROOT, ".venv-st" if st else ".venv-tts", "bin", "python")
    if not os.path.exists(py) or time.time() - _tts_srv["t"] < 20:
        return False
    _tts_srv["t"] = time.time()
    subprocess.Popen([py, os.path.join(ROOT, "daemon", "tts_supertonic.py" if st else "tts_pocket.py")], stdout=open("/tmp/friday-tts.log", "a"),
                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(80):
        if os.path.exists(TTS_SOCK):
            return True
        time.sleep(0.25)
    return False


def _synth_pocket(text: str):
    """voz neural Kyutai Pocket TTS (modelo português, voz 'jane', CPU): 1º som em ~0,1 s, ~4x tempo real."""
    import socket as _sk
    for tentativa in range(2):
        if not _tts_garantir():
            return None
        try:
            s_ = _sk.socket(_sk.AF_UNIX); s_.settimeout(25); s_.connect(TTS_SOCK)
            s_.sendall((json.dumps({"texto": _humanize(text)}, ensure_ascii=False) + "\n").encode())
            f = s_.makefile("rb")
            h = json.loads(f.readline() or b"{}")
            if not h.get("ok"):
                s_.close(); return None
            s_.settimeout(None)
            return _FalaStream(s_, f, int(h["sr"])), int(h["sr"])
        except (ConnectionRefusedError, FileNotFoundError):
            try:
                os.unlink(TTS_SOCK)                         # socket velho (servidor morreu): sobe de novo
            except Exception:
                pass
        except Exception as e:
            print("voz pocket indisponível:", e, flush=True)
            return None
    return None


def _synth_unlocked(text: str, stream: bool = False):
    global _piper
    motor = os.environ.get("PROMETHEUS_TTS") or _voz_cfg().get("tts_motor", "dii")
    if motor == "dii":
        r = _synth_dii(text)
        if r is not None:
            return r
        motor = "pocket"
    if motor in ("pocket", "supertonic"):                # mesmo cliente: o servidor no socket é o do motor escolhido
        r = _synth_pocket(text)
        if r is not None:
            return r if stream else (r[0].tudo(), r[1])
        motor = "kokoro"
    if motor == "edge":                                  # online (a Microsoft passou a recusar com 403 em 10/2026)
        r = _synth_edge(text)
        if r is not None:
            return r
    if motor in ("dii", "pocket", "supertonic", "edge", "kokoro"):
        r = _synth_kokoro(text)
        if r is not None:
            return r
    try:
        if _piper is None:
            from piper import PiperVoice
            _vm = os.path.join(ROOT, "models", f"pt_BR-{os.environ.get('PROMETHEUS_PIPER', 'jeff')}-medium.onnx")
            if not os.path.exists(_vm):
                _vm = os.path.join(ROOT, "models", "pt_BR-faber-medium.onnx")
            _piper = PiperVoice.load(_vm)
        chunks = list(_piper.synthesize(text, syn_config=_cfg()))
        pcm = b"".join(c.audio_int16_bytes for c in chunks)
        sr = chunks[0].sample_rate
        if ROBOT:
            return _robotize(pcm, sr), sr
        import numpy as np                                   # voz humana: só normaliza o volume
        a = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768
        a = np.interp(np.arange(0, len(a) - 1, 0.97), np.arange(len(a)), a)      # ~0,5 semitom mais grave, sem alterar o timbre
        a = a / max(1e-6, np.abs(a).max()) * 0.9
        return (a * 32767).astype("int16").tobytes(), sr
    except Exception as e:
        print("piper indisponível:", e, flush=True)
        return None


speak_lock = asyncio.Lock()


_fim_fala = [0.0]
_ditas = []                     # o que ela mesma disse (p/ não se ouvir no microfone)
_pergunta_t = [0.0]             # quando ela fez a última pergunta (portão v2: faixa média aceita resposta)


def _norm_eco(t):
    return re.sub(r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", (t or "").lower()).encode("ascii", "ignore").decode()).strip()


def eh_eco(txt):
    """True se a transcrição é a própria voz dela voltando pelo microfone (texto contido/parecido com algo dito há <20 s)."""
    import difflib
    a = _norm_eco(txt)
    if len(a) < 6:
        return False
    agora = time.time()
    try:
        open("/tmp/eco.log", "a").write(f"{time.strftime('%H:%M:%S')} txt={a!r} speaking={speaking} desde_fim={agora - _fim_fala[0]:.1f} ditas={[b[:30] for _, b in _ditas[-3:]]}\n")
    except Exception:
        pass
    if not (speaking or agora - _fim_fala[0] < 12):
        return False                  # ela está calada há tempo: o que chega é voz de verdade
    rec = [b for t_, b in _ditas if agora - t_ <= 300 and b]
    if not rec:
        return False
    palavras = set(" ".join(rec).split())
    w = a.split()
    if len(w) >= 3:
        import difflib as _dl
        ok = sum(1 for x in w if x in palavras or _dl.get_close_matches(x, palavras, 1, 0.78))
        if ok / len(w) >= 0.75:
            return True
    return any(a in b for b in rec)


async def speak(text: str):
    """a síntese começa NA HORA (em paralelo ao áudio anterior); a reprodução segue a ordem de chegada (lock FIFO)."""
    cleaned = clean_for_speech(text)
    if not cleaned or modes.get("silencio"):
        return
    _ditas.append((time.time(), _norm_eco(cleaned)))
    del _ditas[:-25]
    if cleaned.rstrip().endswith("?"):
        _pergunta_t[0] = time.time()
    ep = speech_epoch
    pre = asyncio.create_task(asyncio.to_thread(_synth, cleaned, True))
    async with speak_lock:
        if ep != speech_epoch:
            asyncio.create_task(_descartar_fala(pre))     # cancelada por "pare" antes de tocar: para a geração no servidor
            return
        try:
            await _speak_impl(text, pre, ep)
        finally:
            _fim_fala[0] = time.time()


_lat = {"utt": 0.0, "stt": 0.0}


async def _descartar_fala(pre):
    try:
        r = await pre
        if r and isinstance(r[0], _FalaStream):
            r[0].fechar()
    except Exception:
        pass


async def _publicar_remoto(pcm, rate):
    """app remoto conectado: áudio remoto desativado por padrão para não emitir voz fora do fone."""
    if os.environ.get("PROMETHEUS_VOZ_REMOTA", "0") != "1":
        return
    try:
        import remoto as _rm, base64 as _b64, io as _io, wave as _wv
        if _rm.clientes:
            _buf = _io.BytesIO()
            with _wv.open(_buf, "wb") as _w:
                _w.setnchannels(1); _w.setsampwidth(2); _w.setframerate(rate); _w.writeframes(pcm)
            await _rm.publicar({"type": "voz", "wav": _b64.b64encode(_buf.getvalue()).decode()})
    except Exception as _e:
        print("voz remota:", _e, flush=True)


async def _tocar_stream(st, rate, ep):
    """toca a fala ENQUANTO o servidor gera (1º som em ~0,1 s) e anima a boca/partículas no ritmo do áudio."""
    global tts_proc
    import numpy as np
    # Pré-buffer inicial (~160ms = rate * 2 * 0.16 bytes): evita buffer underrun/engasgo no PipeWire/paplay
    pre_bytes = int(rate * 2 * 0.16)
    await asyncio.to_thread(st.esperar, pre_bytes, 1.5)
    proc = tts_proc = await asyncio.create_subprocess_exec("paplay", "--raw", f"--rate={rate}", "--channels=1", "--format=s16le",
                                                           stdin=asyncio.subprocess.PIPE)
    escrito = [0]

    async def escrever():
        try:
            while True:
                n = await asyncio.to_thread(st.esperar, escrito[0], 2.0)
                if ep is not None and ep != speech_epoch:
                    break
                if n > escrito[0]:
                    with st.cv:
                        bloco = bytes(st.buf[escrito[0]:n])
                    if escrito[0] == 0 and _lat["utt"]:
                        try:
                            with open("/tmp/friday-timing.log", "a") as _tl:
                                _tl.write(f"{time.strftime('%H:%M:%S')} LATÊNCIA fim-da-fala→1º som = {time.time() - _lat['utt']:.1f}s (pocket)\n")
                        except Exception:
                            pass
                        _lat["utt"] = 0.0
                    proc.stdin.write(bloco); await proc.stdin.drain(); escrito[0] = n
                elif st.fim:
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    wt = asyncio.create_task(escrever())
    janela = (rate // 20) * 2                                  # 50 ms em bytes (s16)
    i, t0 = 0, None
    while True:
        if ep is not None and ep != speech_epoch:
            st.fechar()
            try:
                proc.kill()
            except Exception:
                pass
            break
        if proc.returncode is not None:
            break
        if i + janela <= escrito[0]:
            if t0 is None:
                t0 = time.time()
            seg = np.frombuffer(bytes(st.buf[i:i + janela]), dtype=np.int16).astype("float32")
            await broadcast({"type": "mouth", "v": round(min(1.0, float(np.sqrt((seg ** 2).mean())) / 32768 * 3.2), 2)})
            i += janela
            await asyncio.sleep(max(0.0, t0 + (i / 2) / rate - time.time()))
        elif st.fim and escrito[0] >= len(st.buf) and i + janela > len(st.buf):
            break
        else:
            await asyncio.sleep(0.02)
    await wt
    await proc.wait()
    if _remoto_on[0] and st.fim:
        await _publicar_remoto(bytes(st.buf), rate)


async def _speak_impl(text: str, pre=None, ep=None):
    global tts_proc, speaking
    text = clean_for_speech(text)
    if not text:
        return
    await set_state("speaking")
    speaking = True
    try:
        audio = await pre if pre is not None else await asyncio.to_thread(_synth, text, True)
        if audio and isinstance(audio[0], _FalaStream):
            if shutil.which("paplay"):
                await _tocar_stream(audio[0], audio[1], ep)
                return
            audio = (audio[0].tudo(), audio[1])
        if audio and _remoto_on[0]:                     # app remoto conectado: a voz dela toca também no celular
            try:
                import remoto as _rm, base64 as _b64, io as _io, wave as _wv
                if _rm.clientes:
                    _buf = _io.BytesIO()
                    with _wv.open(_buf, "wb") as _w:
                        _w.setnchannels(1); _w.setsampwidth(2); _w.setframerate(audio[1]); _w.writeframes(audio[0])
                    await _rm.publicar({"type": "voz", "wav": _b64.b64encode(_buf.getvalue()).decode()})
            except Exception as _e:
                print("voz remota:", _e, flush=True)
        if audio and shutil.which("paplay"):
            pcm, rate = audio
            proc = tts_proc = await asyncio.create_subprocess_exec(
                "paplay", "--raw", f"--rate={rate}", "--channels=1", "--format=s16le",
                stdin=asyncio.subprocess.PIPE)
            if _lat["utt"]:
                try:
                    with open("/tmp/friday-timing.log", "a") as _tl:
                        _tl.write(f"{time.strftime('%H:%M:%S')} LATÊNCIA fim-da-fala→1º som = {time.time() - _lat['utt']:.1f}s\n")
                except Exception:
                    pass
                _lat["utt"] = 0.0
            try:
                proc.stdin.write(pcm); await proc.stdin.drain(); proc.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                return                                   # "pare" matou o paplay no meio: não é erro
            # envelope de amplitude a cada 50 ms -> boca
            import array, math
            a = array.array("h"); a.frombytes(pcm[: len(pcm) // 2 * 2])
            win = rate // 20
            t0 = time.time()
            for i in range(0, len(a), win):
                seg = a[i:i + win]
                if not seg or proc.returncode is not None:
                    break
                if ep is not None and ep != speech_epoch:
                    try: proc.kill()
                    except Exception: pass
                    break
                rms = math.sqrt(sum(x * x for x in seg) / len(seg)) / 32768
                await broadcast({"type": "mouth", "v": round(min(1.0, rms * 3.2), 2)})
                await asyncio.sleep(max(0, t0 + (i + win) / rate - time.time()))
            await proc.wait()
        elif shutil.which("espeak-ng"):
            tts_proc = await asyncio.create_subprocess_exec("espeak-ng", "-v", VOICE, "-s", "160", "-p", "35", text)
            await tts_proc.wait()
    finally:
        tts_proc = None
        speaking = False
        try:
            conv["t"] = time.time()          # a próxima fala do usuário (<45 s) ainda é comigo
        except Exception:
            pass
        await broadcast({"type": "mouth", "v": 0})


def _gui_env():
    e = dict(os.environ)
    uid = os.getuid()
    e.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    e.setdefault("WAYLAND_DISPLAY", "wayland-1")
    e.setdefault("YDOTOOL_SOCKET", f"/run/user/{uid}/.ydotool_socket")
    e["PATH"] = os.path.expanduser("~/.local/bin") + ":" + e.get("PATH", "")
    return e


async def ask(text: str, files: list[str], proactive: bool = False, voz: bool = False):
    global claude_proc
    if not proactive and not files and not voz and text and len(text) < 300:   # voz: route_speech já passou pelos mesmos portões (com a checagem do TitaNet)       # "aprovado"/"cancela"/"altera para X"/"sim" DIGITADOS = mesma lógica da voz
        if await handle_approval_speech(text, eco=True) or await handle_offer_speech(text, eco=True) or await handle_skip_speech(text):
            return
    if not proactive and not files and not voz and text and await handle_modes(text):   # 19/10: pedido digitado >300 chars pulava a rota do MODO DEV
        return
    if fr is not None and os.environ.get("FRIDAY_CLOUD", "0") != "1":
        return await friday_ask(text, files, proactive)
    async with busy:
        if not proactive:
            conv["t"] = time.time()
            await broadcast({"type": "text", "role": "user", "text": text, "files": files})
            log_turn("usuario", text)
        else:
            log_turn("evento", text)
        mem["conversas"] = mem.get("conversas", 0) + (1 if time.time() - mem.get("ultima_vez", 0) > 1800 else 0)
        mem["ultima_vez"] = time.time(); save_mem()
        if camera_on and time.time() - scene["t_vlm"] > 6 and not proactive and VISUAL_Q.search(text or ""):
            await asyncio.to_thread(describe_scene)           # só quando a pergunta é sobre o que ele vê (evita segundos de espera à toa)
        cena = ""
        if proactive:
            text = ("[EVENTO AUTÔNOMO DA SUA VISÃO — você decide se comenta] " + text +
                    " Se for relevante, diga UMA frase curta e natural ao usuário; se não valer a pena, responda apenas [silêncio].")
        prompt = sentidos_ctx() + cena + text + "".join(f"\n[arquivo anexado: {f}]" for f in files)
        effort = EFFORT_TASK if (not proactive and (TASK_RE.search(text) or len(text) > 160 or files)) else EFFORT_CHAT
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--model", MODEL, "--effort", effort, "--append-system-prompt", persona(), *FAST_FLAGS]
        if FALLBACK_MODEL and FALLBACK_MODEL != MODEL:
            cmd += ["--fallback-model", FALLBACK_MODEL]
        if PERMISSION:
            cmd += ["--permission-mode", PERMISSION]
        if state["session"]:
            cmd += ["--resume", state["session"]]
        got_output = False
        await set_state("thinking", "pensativo")
        claude_proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=1 << 24, cwd=FAST_CWD, env=_gui_env())
        st = {"acc": "", "done": 0, "clean": "", "mood": None}     # fala em streaming: frase a frase, enquanto o texto chega
        await hud_begin(text if not proactive else "tarefa autônoma")
        spoke = {"any": False}
        speak_tasks = []

        async def _filler():
            """se a resposta demora, ele avisa que está trabalhando (uma vez), como uma pessoa faria."""
            await asyncio.sleep(3.4)
            if not spoke["any"] and not proactive and claude_proc is not None:
                import random
                await set_state(mood="pensativo")
                await speak(random.choice(FILLERS))
        filler_task = asyncio.create_task(_filler())

        async def emit(raw_chunk: str):
            """Processa um trecho bruto: executa tags, fala e legenda o texto limpo."""
            t = raw_chunk
            if st["done"] == 0:
                m = re.match(r"\s*\[humor:(\w+)\]\s*", t)
                if m:
                    st["mood"] = m.group(1); t = t[m.end():]
            for hm in re.findall(r"\[humor:\s*([^\]\s]+)\s*\]", t):     # troca de humor no meio da resposta: o rosto acompanha
                if _humor_norm(hm):                                        # (e a tag não é lida em voz alta)
                    st["mood"] = hm
            for k, v in re.findall(r"\[lembrar:\s*([^=\]]+)=([^\]]+)\]", t):
                k, v = k.strip().lower(), v.strip()
                if k == "nome": mem["nome"] = v
                else: mem.setdefault("fatos", {})[k] = v
                save_mem()
            for ap in re.findall(r"\[aprendi:\s*([^\]]+)\]", t):
                if ops is not None:
                    pp = [x.strip() for x in ap.split("|")] + ["", ""]
                    if pp[0] and len(pp) >= 3 and pp[2]:
                        ops.skill_add(pp[0], pp[2], pp[1], origem="aprendida")
                        await broadcast({"type": "text", "role": "tool", "text": "aprendi: " + pp[0][:50]})
            for ag in re.findall(r"\[agenda:\s*([^\]]+)\]", t):
                if ops is not None:
                    pp = [x.strip() for x in ag.split("|")] + ["", "", ""]
                    aid, msg = ops.agenda_add(pp[0], pp[1], pp[2] or "compromisso", 60, pp[3], "", "", "conversa")
                    await broadcast({"type": "text", "role": "tool", "text": ("agenda: " + pp[0][:50]) if aid else "agenda: data não entendida"})
            for tk in re.findall(r"\[tarefa:\s*([^\]]+)\]", t):
                if ops is not None:
                    partes = [x.strip() for x in tk.split("|")]
                    ops.task_add(partes[0], partes[1] if len(partes) > 1 else "")
                    await broadcast({"type": "text", "role": "tool", "text": "tarefa agendada: " + partes[0][:60]})
            for nm in re.findall(r"\[pessoa:\s*([^\]]+)\]", t):
                await asyncio.to_thread(enroll_current, nm.strip())
            for pz in re.findall(r"\[gesto:\s*(\w+)\]", t):
                await broadcast({"type": "mao", "lado": "R", "pose": pz.strip().lower()})
            for nm in re.findall(r"\[esquecer:\s*([^\]]+)\]", t):
                if people is not None:
                    people.forget(nm.strip())
            t = re.sub(r"\[(?:pessoa|esquecer|lembrar|gesto|tarefa|agenda|aprendi|humor):[^\]]*\]", "", t).strip()
            if re.fullmatch(r"\[sil[eê]ncio\]\.?", t, re.I):
                t = ""
            st["done"] += len(raw_chunk)
            if not t:
                return
            st["clean"] += (" " if st["clean"] else "") + t
            if st["mood"]:
                await set_state(mood=st["mood"]); st["mood"] = None
            spoke["any"] = True
            await broadcast({"type": "text", "role": "assistant", "text": t})
            speak_tasks.append(asyncio.create_task(speak(t)))       # não bloqueia: já sintetiza a próxima frase enquanto fala

        async def flush(final: bool):
            """Fala as frases completas já disponíveis (ou tudo o que restar, se final)."""
            rest = st["acc"][st["done"]:]
            if not final:
                cut = rest.rfind("[")
                if cut != -1 and "]" not in rest[cut:]:
                    rest = rest[:cut]                       # tag ainda aberta: espera
                m = None
                for m in re.finditer(r"[.!?…]+[\"')\]]*(?:\s+|$)|\n", rest):
                    pass
                if not m:
                    return
                rest = rest[:m.end()]
            if rest.strip():
                await emit(rest)
            elif final:
                st["done"] = len(st["acc"])

        async for raw in claude_proc.stdout:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if dev is not None:
                dev.claude(ev)
            if ev.get("session_id") and ev["session_id"] != state["session"]:
                state["session"] = mem["session"] = ev["session_id"]
                save_mem()
            if ev.get("type") == "stream_event":
                e = ev.get("event", {})
                if e.get("type") == "content_block_start" and e.get("content_block", {}).get("type") == "text":
                    st.update(acc="", done=0, clean="", mood=None)
                elif e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta":
                    st["acc"] += e["delta"].get("text", "")
                    got_output = True
                    await flush(False)
                continue
            if ev.get("type") != "assistant":
                continue
            got_output = True
            for bl in ev["message"].get("content", []):
                if bl.get("type") == "tool_use":
                    inp = bl.get("input", {})
                    desc = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                    await broadcast({"type": "text", "role": "tool", "text": f"{bl['name']}: {str(desc)[:200]}"})
                    await hud_step(f"{bl['name']}: {desc}")
                elif bl.get("type") == "text" and bl["text"].strip():
                    if st["acc"] != bl["text"]:
                        st["acc"] = bl["text"]               # sem streaming: processa o bloco inteiro
                    await flush(True)
                    log_turn("prometheus", st["clean"])
                    st.update(acc="", done=0, clean="", mood=None)
        rc = await claude_proc.wait()
        claude_proc = None
        filler_task.cancel()
        if speak_tasks:
            await asyncio.gather(*speak_tasks, return_exceptions=True)
        await hud_end(rc == 0)
        if rc != 0 and state["session"] and not got_output:
            state["session"] = mem["session"] = None; save_mem()
            await broadcast({"type": "text", "role": "tool", "text": "sessão antiga indisponível; recomeçando com a memória salva"})
            asyncio.create_task(ask(text, files)); return
        await set_state("idle", "neutro")
        mem["turnos"] = mem.get("turnos", 0) + 1
        save_mem()
        if mem["turnos"] % 12 == 0:
            asyncio.create_task(consolidate())
        await broadcast({"type": "done"})


REACT_LAST = {}
SPEAK_REACT = {"acenou"}                    # só fala ao aceno real; sim/não de cabeça, joinha, paz, ok etc. = apenas animação


async def reagir(g: str):
    """Reação imediata e local a um gesto: humor + frase curta (só se estiver livre)."""
    if g not in REACT or speaking or busy.locked() or state["state"] in ("thinking", "speaking"):
        return
    pose_m = {"apontou": "apontar", "mão levantada": "aberta",
              "bateu palmas": "paz", "duas mãos levantadas": "paz", "cruzou os braços": "ok"}.get(g)
    if pose_m:
        await broadcast({"type": "mao", "lado": "R", "pose": pose_m})
    if g not in SPEAK_REACT:
        return                                   # gestos fracos/ambíguos: só animação, sem falar
    if time.time() - REACT_LAST.get("fala", 0) < 60:
        return                                   # no máximo uma fala reativa por minuto
    frase, humor = REACT[g]
    if time.time() - last_voice["t"] < 8:
        return                                     # a pessoa está falando: não interrompe
    REACT_LAST["fala"] = time.time()
    await set_state(mood=humor)
    await speak(frase)
    await set_state("idle", "neutro")


async def greet(msg):
    await set_state(mood="alegre")
    await broadcast({"type": "text", "role": "assistant", "text": msg})
    log_turn("prometheus", msg)
    await speak(msg)
    await set_state("idle", "neutro")


_dbg = {"t": 0.0, "n": 0, "hit": 0}
_shared = {"frame": None}


def camera_thread(loop):
    """Supervisor: a câmera nunca fica morta — se abrir falhar (ex.: instância anterior ainda soltando o dispositivo) ou a thread
    quebrar, tenta de novo. Antes, falhar ao abrir encerrava a thread para sempre."""
    while True:
        try:
            _camera_run(loop)
        except Exception as e:
            print("câmera: erro, reiniciando:", repr(e), flush=True)
        _shared["frame"] = None
        time.sleep(3)


def _camera_run(loop):
    """Detecta o rosto do usuário (YuNet) e envia {gaze x,y,present}. Retorna se não conseguir abrir (o supervisor repete)."""
    dev = _cam_nativa_dev()
    try:
        import cv2
        det = cv2.FaceDetectorYN.create(os.path.join(ROOT, "models", "yunet.onnx"), "", (320, 240), 0.5)
        if win_compat.IS_WINDOWS:
            cap = cv2.VideoCapture(dev, cv2.CAP_DSHOW)
            if not cap.isOpened(): cap = cv2.VideoCapture(dev)
        else:
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap = cv2.VideoCapture(dev)
            if not cap.isOpened() and dev != 0:
                cap = cv2.VideoCapture(0)
        try:
            import subprocess as _sp
            dev_str = str(dev) if str(dev).startswith("/dev/") else f"/dev/video{dev}"
            _sp.run(["v4l2-ctl", "-d", dev_str, "--set-ctrl=exposure_dynamic_framerate=0"], capture_output=True, timeout=3)
        except Exception:
            pass
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG')); cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720); cap.set(cv2.CAP_PROP_FPS, 30)   # 720p: a mão tem o dobro de pixels (gestos precisos)
        if not cap.isOpened():
            cap.release()
            return
    except Exception as e:
        print("câmera indisponível:", e, flush=True); return
    import numpy as np
    lut = (255 * (np.arange(256) / 255) ** 0.55).astype('uint8')
    gx = gy = 0.0; present = False; last_seen = 0.0; last_sent = None; base = None
    prev_gray = None; wave_hist = []; wave_until = 0.0; waving = False; wave_side = 1
    id_last = 0.0; id_last_amb = 0.0; seen_at = {}
    ident_hold = {"pid": None, "nome": None, "t": 0.0}; learn_t = {}      # identidade estável + aprendizado contínuo do rosto
    try:
        faceid = senses.FaceID() if senses is not None else None
    except Exception as e:
        print("reconhecimento facial indisponível:", e, flush=True); faceid = None
    try:                                                         # msg "visao" p/ a interface (sorriso, pose da cabeça, quem é)
        vis_rostos = senses.VisaoRostos() if senses is not None and hasattr(senses, "VisaoRostos") else None
    except Exception:
        vis_rostos = None
    vis = {"t": 0.0, "k": (False, False), "err": 0.0}            # último envio, (tinha rostos, tinha pessoas no ambiente), último erro

    def _visao_envia(fl, amb, idade):
        c_name = "externa" if (_shared.get("frame_amb") is not None and time.time() - _shared.get("amb_t", 0) < 2.0) else "nativa"
        asyncio.run_coroutine_threadsafe(broadcast({"type": "visao", "t": round(time.time(), 3), "cam": c_name, "faces": fl, "amb": amb,
                                                    "amb_idade": None if idade is None else round(idade, 2)}), loop)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)                          # sem fila de quadros velhos (principal fonte de atraso)
    while True:
        if not camera_on:                                        # câmera desligada pelo usuário: solta o dispositivo
            _shared["frame"] = None                              # sem quadro velho circulando para os outros sensores
            if cap is not None:
                cap.release(); cap = None
                present = False; gx = gy = 0.0; base = None; last_sent = None
                asyncio.run_coroutine_threadsafe(broadcast({"type": "gaze", "x": 0, "y": 0, "present": False}), loop)
            if vis["k"] != (False, False):                       # visão esvazia na hora (1 msg vazia)
                vis["k"] = (False, False)
                try:
                    _visao_envia([], [], None)
                except Exception:
                    pass
            time.sleep(0.3); continue
        if cap is None:
            dev = _cam_nativa_dev()
            if win_compat.IS_WINDOWS:
                cap = cv2.VideoCapture(dev, cv2.CAP_DSHOW)
                if not cap.isOpened(): cap = cv2.VideoCapture(dev)
            else:
                cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(dev)
                if not cap.isOpened() and dev != 0:
                    cap = cv2.VideoCapture(0)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG')); cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720); cap.set(cv2.CAP_PROP_FPS, 30)   # 720p: a mão tem o dobro de pixels (gestos precisos)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                cap = None; time.sleep(2); continue
        ok, frame = cap.read()                                   # (BUFFERSIZE=1 já evita fila; o grab() extra descartava metade dos quadros = ~15 fps)
        if not ok:
            fails = locals().get("fails", 0) + 1
            if fails >= 5:                                       # dispositivo travou/sumiu: solta e reabre
                cap.release(); cap = None; fails = 0
                _shared["frame"] = None
        now = time.time()
        _shared["frame"] = frame
        _shared["frame_id"] = _shared.get("frame_id", 0) + 1
        _shared["frame_t"] = now
        fa = _shared.get("frame_amb")
        viva_amb = fa is not None and (now - _shared.get("amb_t", 0) < 2.0)
        # Roteamento correto das câmeras:
        # Câmera NATIVA (notebook) aponta para o USUÁRIO em frente à tela (rosto, gestos, olhar, identidade, camisa).
        # Câmera EXTERNA (USB) aponta para o AMBIENTE (sala, objetos, pessoas ao redor ou ao lado).
        fr_user = frame
        f_proc = cv2.resize(fr_user, (320, 240))
        if f_proc.mean() < 70:                                   # quadro escuro: realça
            f_proc = cv2.convertScaleAbs(f_proc, alpha=1.0, beta=0)
            f_proc = cv2.LUT(f_proc, lut)
        _, faces = det.detect(f_proc)
        # ---- acenar: movimento horizontal oscilante fora da região do rosto (OpenCV puro, sem modelo extra) ----
        try:
            gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (9, 9), 0)
            if prev_gray is not None:
                diff = cv2.threshold(cv2.absdiff(gray, prev_gray), 22, 255, cv2.THRESH_BINARY)[1]
                if faces is not None and len(faces):
                    fx, fy, fw, fh = faces[0][:4]
                    diff[max(0, int(fy - fh * 0.3)):int(fy + fh * 1.6), max(0, int(fx - fw * 0.15)):int(fx + fw * 1.15)] = 0
                ys, xs = np.nonzero(diff)
                scene['motion'] += (len(xs) / diff.size - scene['motion']) * 0.3
                if len(xs) > 250:
                    wave_hist.append((now, float(xs.mean())))
                wave_hist[:] = [h for h in wave_hist if now - h[0] < 1.6]
                if len(wave_hist) >= 6:
                    xs_h = [h[1] for h in wave_hist]
                    steps = [b - a for a, b in zip(xs_h, xs_h[1:]) if abs(b - a) > 3]
                    flips = sum(1 for a, b in zip(steps, steps[1:]) if a * b < 0)
                    if False and flips >= 3 and max(xs_h) - min(xs_h) > 18:   # substituído pelo reconhecimento por pose
                        wave_until = now + 1.0
                        wave_side = 1 if sum(xs_h) / len(xs_h) > 160 else -1
            prev_gray = gray
        except Exception:
            pass
        if (now < wave_until) != waving:
            waving = now < wave_until
            if not waving:
                wave_hist.clear()
            asyncio.run_coroutine_threadsafe(broadcast({"type": "wave", "on": waving, "side": wave_side}), loop)
        _dbg["n"] += 1
        if faces is not None and len(faces):
            _dbg["hit"] += 1
        if now - _dbg["t"] > 1.0:                               # diagnóstico: /tmp/prometheus-cam.json
            try:
                with open("/tmp/prometheus-cam.json", "w") as _f:
                    json.dump({"fps": _dbg["n"], "hits": _dbg["hit"], "mean": round(float(frame.mean()), 1), "std": round(float(frame.std()), 1), "thr": 0.5,
                                "gx": round(float(gx), 2), "gy": round(float(gy), 2), "present": present,
                                "face": (faces[0][:4].round(0).tolist() if faces is not None and len(faces) else None)}, _f)
            except Exception:
                pass
            _dbg.update(t=now, n=0, hit=0)
        # ---- identidade dos rostos (SFace, 100% local) ----
        if faceid is not None and people is not None and now - id_last > 0.7:
            id_last = now
            try:
                raw = fr_user
                raw_feat = cv2.LUT(raw, lut) if raw.mean() < 70 else raw
                out = []
                if faces is not None and len(faces) and raw is not None:
                    sx_, sy_ = raw.shape[1] / 320.0, raw.shape[0] / 240.0     # f_proc 320x240 -> quadro real (720p)
                    for fr_ in sorted(faces, key=lambda r: -float(r[2] * r[3]))[:3]:
                        row = fr_.copy(); row[0:14:2] *= sx_; row[1:14:2] *= sy_  # pares = x, ímpares = y
                        feat = faceid.feature(raw_feat, row)
                        nome_f, sim_f, pid_f = people.match_face(feat)
                        # identidade estável: rosto único, perdeu o match por ângulo/luz/mão no rosto -> mantém quem estava há pouco
                        if pid_f is None and ident_hold["pid"] and now - ident_hold["t"] < 30 and len(faces) == 1:
                            s_h = people.sim_to("faces", ident_hold["pid"], feat)
                            if s_h >= 0.20:
                                pid_f, nome_f, sim_f = ident_hold["pid"], ident_hold["nome"], s_h
                        if pid_f and sim_f >= 0.34:
                            ident_hold.update(pid=pid_f, nome=nome_f, t=now)
                            # galeria viva: acrescenta amostras variadas (ângulo/luz) de quem já é reconhecido com folga
                            # 16/10: aprendia com 0,34 e rosto de amigo entrou no perfil do dono -> só rosto único, sim >= 0,50
                            if (now - learn_t.get(pid_f, 0) > 25 and len(faces) == 1 and sim_f >= 0.50
                                    and people.sim_to("faces", pid_f, feat) < 0.86):
                                people.learn(pid_f, face=feat); learn_t[pid_f] = now
                        cor = None
                        try:                                                   # camisa: região logo abaixo do queixo
                            fx, fy, fw, fh = float(fr_[0]) * sx_, float(fr_[1]) * sy_, float(fr_[2]) * sx_, float(fr_[3]) * sy_
                            y0 = int(fy + fh * 1.05)                           # logo abaixo do queixo
                            y1 = min(raw.shape[0], int(y0 + fh * 0.9))
                            x0, x1 = int(fx - fw * 0.05), int(fx + fw * 1.05)
                            if y1 - y0 >= 24:                                  # só mede se há camisa visível no quadro
                                reg = raw[y0:y1, max(0, x0):min(raw.shape[1], x1)]
                                if reg.size:
                                    cor = senses.color_name_pt(reg[::3, ::3], ref=raw[::4, ::4])
                                    if nome_f and nome_f.lower() == _owner_name().lower():   # roupa do dono (a PTZ confere a cor: amigos no quarto)
                                        _hsv = cv2.cvtColor(np.ascontiguousarray(reg[::3, ::3]), cv2.COLOR_BGR2HSV).reshape(-1, 3)
                                        scene["camisa_dono"] = (now, [float(v) for v in np.median(_hsv, axis=0)])
                                    scene["dbg_cor"] = {"reg_bgr": [int(v) for v in np.median(reg.reshape(-1, 3), axis=0)],
                                                        "frame_bgr": [int(v) for v in raw[::4, ::4].reshape(-1, 3).mean(axis=0)],
                                                        "y": [y0, y1], "face": [int(fx), int(fy), int(fw), int(fh)]}
                            else:
                                scene["dbg_cor"] = {"visivel": False, "face": [int(fx), int(fy), int(fw), int(fh)]}
                        except Exception:
                            pass
                        out.append({"nome": nome_f, "sim": sim_f, "feat": feat, "area": float(fr_[2] * fr_[3]), "pid": pid_f, "camisa": cor,
                                    "box": [float(v) for v in fr_[:4]]})
                        if pid_f and now - seen_at.get(pid_f, 0) > 600:
                            seen_at[pid_f] = now; people.touch(pid_f)
                scene["faces"] = out; scene["t"] = now

                # ---- detecção e identificação de rostos no ambiente (câmera externa USB e PTZ) ----
                if viva_amb and fa is not None and now - id_last_amb > 1.0:
                    id_last_amb = now
                    try:
                        Wa, Ha = (480, 270) if fa.shape[1] / fa.shape[0] > 1.5 else (320, 240)   # PTZ 16:9 sem achatar; rosto longe precisa de px
                        fa_p = cv2.resize(fa, (Wa, Ha))
                        if fa_p.mean() < 70:
                            fa_p = cv2.LUT(fa_p, lut)
                        det.setInputSize((Wa, Ha))
                        try:
                            _, a_faces = det.detect(fa_p)
                        finally:
                            det.setInputSize((320, 240))
                        out_a = []
                        if a_faces is not None and len(a_faces):
                            sx_a, sy_a = fa.shape[1] / float(Wa), fa.shape[0] / float(Ha)
                            fa_feat = cv2.LUT(fa, lut) if fa.mean() < 70 else fa
                            for afr_ in sorted(a_faces, key=lambda r: -float(r[2] * r[3]))[:3]:
                                arow = afr_.copy(); arow[0:14:2] *= sx_a; arow[1:14:2] *= sy_a
                                afeat = faceid.feature(fa_feat, arow)
                                anome, asim, apid = people.match_face(afeat)
                                acx = (float(afr_[0]) + float(afr_[2]) / 2.0) / float(Wa)
                                lado = "à sua direita" if acx > 0.5 else "à sua esquerda"
                                out_a.append({"nome": anome, "sim": asim, "pid": apid, "lado": lado,
                                              "box": [float(afr_[0]) * 320.0 / Wa, float(afr_[1]) * 240.0 / Ha,
                                                      float(afr_[2]) * 320.0 / Wa, float(afr_[3]) * 240.0 / Ha],
                                              "boxn": [float(afr_[0]) / Wa, float(afr_[1]) / Ha,               # 0..1 no quadro dela (x0,y0,x1,y1)
                                                       float(afr_[0] + afr_[2]) / Wa, float(afr_[1] + afr_[3]) / Ha]})
                        _nome_unico(out_a)
                        scene["amb_faces"] = out_a
                        scene["t_amb_faces"] = now
                    except Exception:
                        pass
                fptz = _shared.get("frame_ptz")
                viva_ptz = fptz is not None and (now - _shared.get("ptz_t", 0) < 2.0)
                if viva_ptz and now - locals().get("id_last_ptz", 0.0) > 0.9:
                    id_last_ptz = now
                    try:
                        Wp, Hp = (480, 270) if fptz.shape[1] / fptz.shape[0] > 1.5 else (320, 240)
                        fp_p = cv2.resize(fptz, (Wp, Hp))
                        if fp_p.mean() < 75:
                            fp_p = cv2.LUT(fp_p, lut)
                        det.setInputSize((Wp, Hp))
                        try:
                            _, p_faces = det.detect(fp_p)
                        finally:
                            det.setInputSize((320, 240))
                        out_p = []
                        if p_faces is not None and len(p_faces):
                            sx_p, sy_p = fptz.shape[1] / float(Wp), fptz.shape[0] / float(Hp)
                            fp_feat = cv2.LUT(fptz, lut) if fptz.mean() < 75 else fptz
                            for pfr_ in sorted(p_faces, key=lambda r: -float(r[2] * r[3]))[:3]:
                                prow = pfr_.copy(); prow[0:14:2] *= sx_p; prow[1:14:2] *= sy_p
                                pfeat = faceid.feature(fp_feat, prow)
                                pnome, psim, ppid = people.match_face(pfeat, ptz=True)
                                pcx = (float(pfr_[0]) + float(pfr_[2]) / 2.0) / float(Wp)
                                lado_p = "à sua direita" if pcx > 0.5 else "à sua esquerda"
                                out_p.append({"nome": pnome, "sim": psim, "pid": ppid, "lado": lado_p, "feat": pfeat,
                                              "box": [float(pfr_[0]) * 320.0 / Wp, float(pfr_[1]) * 240.0 / Hp,
                                                      float(pfr_[2]) * 320.0 / Wp, float(pfr_[3]) * 240.0 / Hp],
                                              "boxn": [float(pfr_[0]) / Wp, float(pfr_[1]) / Hp,
                                                       float(pfr_[0] + pfr_[2]) / Wp, float(pfr_[1] + pfr_[3]) / Hp]})
                        _nome_unico(out_p)
                        scene["ptz_faces"] = out_p
                        scene["t_ptz_faces"] = now
                        _ptz_aprende_rosto(out_p, now)
                        if out_p:                                            # diagnóstico: quem a PTZ reconhece e com que folga
                            try:
                                with open("/tmp/friday-ptz-faces.log", "a") as _pf:
                                    _pf.write(time.strftime("%H:%M:%S ") + " | ".join(
                                        f"{f_['nome']} sim={f_['sim']:.2f} box={[round(v, 2) for v in f_['boxn']]}" for f_ in out_p) + "\n")
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception as e:
                print("id facial:", e, flush=True)
        if faces is not None and len(faces):
            x, y, w, h = faces[0][:4]
            # espelhado: usuário à direita -> olhar à direita; ganho alto p/ pequenos movimentos virarem a cabeça
            cx, cy = (x + w / 2) / 320, (y + h / 2) / 240
            if base is None:
                base = [cx, cy]
            base[0] += (cx - base[0]) * 0.003; base[1] += (cy - base[1]) * 0.003      # posição "normal" se adapta devagar
            tx = max(-1.0, min(1.0, -(cx - base[0]) * 2 * 3.4))
            ty = max(-1.0, min(1.0, -(cy - base[1]) * 2 * 2.8))
            gx += (tx - gx) * 0.85; gy += (ty - gy) * 0.85                          # quase sem suavização: o QML anima
            if not present and now - mem.get("ultima_vez", 0) > 1800 and not speaking and not busy.locked():
                mem["ultima_vez"] = now; save_mem()
                nome = mem.get("nome")
                _kn = [f["nome"] for f in scene["faces"] if f["nome"]] if now - scene["t"] < 2 else []
                if _kn:
                    nome = _kn[0]
                msg = (f"Oi, {nome}! Bom te ver de novo." if nome else
                       "Olá! Eu sou o Prometheus. Qual é o seu nome?")
                asyncio.run_coroutine_threadsafe(greet(msg), loop)
            present = True; last_seen = now
        elif present and now - last_seen > 3:
            present = False; gx = gy = 0.0
        cur = (round(float(gx), 2), round(float(gy), 2), present)
        if last_sent and cur[2] == last_sent[2] and abs(cur[0] - last_sent[0]) < 0.012 and abs(cur[1] - last_sent[1]) < 0.012:
            cur = last_sent
        if cur != last_sent:
            last_sent = cur
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "gaze", "x": cur[0], "y": cur[1], "present": present}), loop)
        # ---- visão p/ a interface: rostos (quem é, sorriso, yaw/pitch/roll, olhando) ~5 Hz + pessoas na câmera externa ----
        if vis_rostos is not None:
            try:
                rf_ = fr_user if fr_user is not None else _shared.get("frame")      # quadro cheio (1280x720 achatado p/ 320x240: corrige o aspecto)
                asp_ = (rf_.shape[1] / 320.0) / (rf_.shape[0] / 240.0) if rf_ is not None else 1.0
                fl_ = vis_rostos.atualizar(faces, scene["faces"] if now - scene["t"] < 2.0 else [], _owner_name(), now, asp_)
                pa_ = scene.get("amb_pessoas")                        # (t, lista) do object_thread, só da câmera EXTERNA
                idade_ = (now - pa_[0]) if pa_ else None
                amb_ = pa_[1] if (pa_ and idade_ <= 30.0) else []
                k_vis = (bool(fl_), bool(amb_))
                if k_vis != vis["k"] or ((fl_ or amb_) and now - vis["t"] >= (0.19 if fl_ else 0.95)):     # ~5 Hz / ~1 Hz
                    vis.update(t=now, k=k_vis)
                    _visao_envia(fl_, amb_, idade_)
            except Exception as e:                                   # nunca derruba a câmera
                if now - vis["err"] > 30:
                    vis["err"] = now; print("visão (msg visao):", repr(e), flush=True)
        time.sleep(0.01)


# ---------- câmera com motor (PTZ): ganchos do ptz.py ----------
_det_ptz = {"od": None, "lock": threading.Lock()}


def _ptz_detectar(fr):
    with _det_ptz["lock"]:
        if _det_ptz["od"] is None:
            _det_ptz["od"] = senses.detector_objetos()
        return _det_ptz["od"].detect(fr, 0.30)


_ptz_rosto = {"t": 0.0, "pedido_ate": 0.0, "n": 0}


def _ptz_aprende_rosto(out_p, now):
    """cadastro do rosto do dono PELA PTZ (ela via 0,10-0,27 contra o cadastro da nativa e nunca o reconhecia).
    Só aprende quando é certo que o único rosto na PTZ é ele: a nativa vê SÓ ele (reconhecido), a porta não vê mais
    ninguém e a PTZ vê um rosto só, grande. Ou sob comando ("aprenda meu rosto na câmera do quarto": 15 s)."""
    if people is None or len(out_p) != 1:
        return
    pedido = now < _ptz_rosto["pedido_ate"]
    if now - _ptz_rosto["t"] < (2.0 if pedido else 20.0):
        return
    f = out_p[0]
    if f.get("feat") is None or (f["boxn"][3] - f["boxn"][1]) < 0.08:
        return
    dono = _owner_name().lower()
    nat = [x for x in scene.get("faces") or []] if now - scene.get("t", 0) < 2 else []
    pid_d = next((x.get("pid") for x in nat if str(x.get("nome") or "").lower() == dono), None)
    if not pid_d and pedido:
        pid_d = people.find_by_name(_owner_name())
    if not pid_d:
        return
    if not pedido:
        try:
            obs = {c_: len(ps_) for c_, (t_, ps_) in _mundo().obs.items() if now - t_ < 2}
        except Exception:
            obs = {}
        if len(nat) != 1 or obs.get("nativa", 0) > 1 or obs.get("porta", 0) > 0:
            return                                           # pode haver outra pessoa: não arrisca ensinar o rosto errado
        if len((people.data["pessoas"].get(pid_d) or {}).get("faces_ptz") or []) >= 3 and \
                people.sim_to("faces_ptz", pid_d, f["feat"]) < 0.25:
            return                                           # muito diferente do que já aprendeu pela PTZ: suspeito
    _ptz_rosto["t"] = now
    _ptz_rosto["n"] += 1
    people.learn_ptz(pid_d, f["feat"])
    print(f"{time.strftime('%H:%M:%S')} rosto do dono aprendido pela PTZ ({'pedido' if pedido else 'auto'}; sim antes {f.get('sim', 0):.2f})", flush=True)


def _ptz_multidao():
    """as câmeras fixas veem alguém além do dono? (nativa com 2+ pessoas ou a porta vendo gente)"""
    try:                                  # 16/10: o corpo detectado nos entalhes do guarda-roupa contava como "mais gente"
        agora = time.time()
        rostos_nat = len(scene.get("faces") or []) if agora - scene.get("t", 0) < 3 else 0
        porta = [p_ for p_ in (_mundo().obs.get("porta", (0, []))[1] if agora - _mundo().obs.get("porta", (0, []))[0] < 3 else [])
                 if p_[2] >= 0.65]
        r_ = rostos_nat > 1 or len(porta) > 0
        if r_ and agora - _ptz_rosto.get("t_log", 0) > 10:
            _ptz_rosto["t_log"] = agora
            print(f"{time.strftime('%H:%M:%S')} multidão? rostos nativa={[(f_.get('nome'), round(float(f_.get('sim') or 0), 2)) for f_ in scene.get('faces') or []]} "
                  f"porta={[round(p_[2], 2) for p_ in porta]}", flush=True)
        return r_
    except Exception:
        return False


def _ptz_dono():
    """(instante, caixa x0,y0,x1,y1) do rosto do dono no quadro da câmera PTZ, se reconhecido."""
    dono = _owner_name().lower()
    agora = time.time()
    if agora - scene.get("t_ptz_faces", 0.0) < 6.0:
        for f in scene.get("ptz_faces") or []:
            if str(f.get("nome") or "").lower() == dono and f.get("boxn"):
                return (scene.get("t_ptz_faces", 0.0), f["boxn"])
    return None             # a caixa da C270 NÃO vale no quadro da PTZ (seguia a pessoa errada); onde o dono está pelas fixas = mundo.py


def _ptz_presente():
    """o dono está por perto? rosto na nativa, PTZ ou de ambiente (30 s) ou voz dele (2 min)."""
    agora, dono = time.time(), _owner_name().lower()
    if agora - scene.get("t", 0) < 30 and any(str(f.get("nome") or "").lower() == dono for f in scene.get("faces") or []):
        return True
    if agora - scene.get("t_ptz_faces", 0) < 30 and any(str(f.get("nome") or "").lower() == dono for f in scene.get("ptz_faces") or []):
        return True
    if agora - scene.get("t_amb_faces", 0) < 30 and any(str(f.get("nome") or "").lower() == dono for f in scene.get("amb_faces") or []):
        return True
    return agora - owner_voice["t"] < 120


def _ptz_sentado():
    """a câmera do notebook vê o rosto do dono agora (< 5 s) = ele está sentado no lugar dele."""
    dono = _owner_name().lower()
    return time.time() - scene.get("t", 0) < 5 and any(str(f.get("nome") or "").lower() == dono for f in scene.get("faces") or [])


def _ptz_avisar(texto, falar=False, jpg=None):
    """Notificação da câmera PTZ: salva snapshot e atualiza texto do HUD, mas NUNCA emite voz autônoma."""
    lp = _main.get("loop")
    if jpg:
        try:
            with open("/tmp/friday-ptz-ultima.jpg", "wb") as f_:
                f_.write(jpg)
        except Exception:
            pass
    if not texto or lp is None:
        return
    asyncio.run_coroutine_threadsafe(broadcast({"type": "text", "role": "assistant", "text": texto}), lp)
    log_turn("prometheus", texto)


def _ptz_comando(m):
    ok_, msg_ = ptz.comando(m)
    print(f"ptz {m.get('op')}: {msg_}", flush=True)
    return ok_, msg_


def _ptz_modo_mudou(modo):
    modes["sentinela"] = modo in ("vigiar", "auto")
    lp = _main.get("loop")
    if lp is not None:
        asyncio.run_coroutine_threadsafe(broadcast({"type": "modes", **modes}), lp)


def _ptz_iniciar(loop_=None):
    if loop_ is not None and _main.get("loop") is None:
        _main["loop"] = loop_                           # avisos da câmera vêm de threads
    if ptz is None or ipcam is None:
        return
    ptz.configurar(modo_mudou=_ptz_modo_mudou, quadro=lambda: (_shared.get("frame_ptz"), _shared.get("ptz_t", 0.0)) if _shared.get("frame_ptz") is not None else (None, 0.0),
                   dono=_ptz_dono, presente=_ptz_presente, detectar=_ptz_detectar,
                   vlm=lambda jpg, pergunta: fr.vision_describe(jpg, pergunta), avisar=_ptz_avisar,
                   alvo_externo=lambda perto_de=None: _mundo().melhor(perto_de), aprender=lambda pan, tilt, t_ref=None: _mundo().aprender(pan, tilt, t_ref),
                   quadro_hd=_ptz_quadro_hd, mundo_resumo=lambda: _mundo().resumo(), sentado=_ptz_sentado,
                   rostos=lambda: (scene.get("t_ptz_faces", 0.0), [f["boxn"] for f in scene.get("ptz_faces") or [] if f.get("boxn")]),
                   refutar=lambda: _mundo().refutar(), camisa_dono=lambda: scene.get("camisa_dono"), multidao=_ptz_multidao)
    ipcam.iniciar_busca()
    ptz.get_ptz()


# ---------- câmeras FIXAS (porta + nativa) -> mundo.py: onde está a pessoa; a PTZ aponta direto e aprende o mapa sozinha ----------
_hd_lock = threading.Lock()


def _mundo():
    import mundo
    return mundo.get()


_PTZ_HD = {"pedido": 0.0, "frame": None, "t": 0.0, "ult": 0.0}


def _ptz_quadro_hd():
    """1 quadro 1280x720 DE VERDADE (stream principal onvif1) para zoom digital / ver longe.
    NUNCA abre 2 sessões RTSP ao mesmo tempo (onvif1 junto do onvif2 derruba/reinicia o firmware Yoosee e ele fala alto):
    pede ao cam_ptz_thread, que fecha o onvif2 (TEARDOWN), lê o onvif1 ~2 s e volta. O rastreio pausa nesse intervalo.
    Sem HD em 7 s (ou pedido < 8 s atrás): amplia o quadro atual de 640x360."""
    import cv2
    fr_ = _shared.get("frame_ptz")
    if fr_ is None or not camera_on:
        return None
    agora = time.time()
    if agora - _PTZ_HD["t"] < 3.0 and _PTZ_HD["frame"] is not None:
        return _PTZ_HD["frame"].copy()
    if agora - _PTZ_HD["ult"] > 8.0:
        _PTZ_HD["ult"] = _PTZ_HD["pedido"] = agora
        while time.time() - agora < 7.0:
            if _PTZ_HD["t"] > agora and _PTZ_HD["frame"] is not None:
                return _PTZ_HD["frame"].copy()
            time.sleep(0.1)
    fr_ = _shared.get("frame_ptz")
    if fr_ is None:
        return None
    if fr_.shape[1] < 1280:
        return cv2.resize(fr_, (1280, 720), interpolation=cv2.INTER_CUBIC)
    return fr_.copy()


_ZOOM_HUD = {"z": 1.0, "cx": 0.5, "cy": 0.5}


def _zoom_auto_ptz(fr, caixa):
    """enquadramento inteligente no HUD: alvo LONGE (caixa baixa) -> aproxima até 3x, suave; perto/sem alvo -> volta a 1x.
    Devolve (quadro, z, transforma(caixa_norm)->caixa_norm no quadro ampliado)."""
    import cv2
    zh = _ZOOM_HUD
    if caixa:
        x0, y0, x1, y1 = [float(v) for v in caixa[:4]]
        alt = max(0.02, y1 - y0)
        alvo_z = min(3.0, max(1.0, 0.42 / alt)) if alt < 0.32 else 1.0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    else:
        alvo_z, cx, cy = 1.0, 0.5, 0.5
    zh["z"] += (alvo_z - zh["z"]) * 0.08
    zh["cx"] += (cx - zh["cx"]) * 0.15
    zh["cy"] += (cy - zh["cy"]) * 0.15
    z = zh["z"]
    if z < 1.08:
        return fr, 1.0, (lambda c: c)
    h, w = fr.shape[:2]
    cw, ch = 1.0 / z, 1.0 / z
    ox = min(max(0.0, zh["cx"] - cw / 2), 1.0 - cw)
    oy = min(max(0.0, zh["cy"] - ch / 2), 1.0 - ch)
    rec = fr[int(oy * h):int((oy + ch) * h), int(ox * w):int((ox + cw) * w)]
    out = cv2.resize(rec, (w, h), interpolation=cv2.INTER_CUBIC)
    cv2.putText(out, f"ZOOM {z:.1f}x", (w - 92, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 138, 31), 1, cv2.LINE_AA)
    return out, z, (lambda c: [(c[0] - ox) / cw, (c[1] - oy) / ch, (c[2] - ox) / cw, (c[3] - oy) / ch])


def _cam_porta_dev():
    import glob
    for p_ in sorted(glob.glob("/dev/v4l/by-id/*-video-index0")):
        if "integrated" not in p_.lower():
            return os.path.realpath(p_)
    return None


def cam_porta_thread():
    """webcam da PORTA / AMBIENTE (fixa). Espelha o quadro da webcam USB capturada por cam_ambiente_thread
    para o mundo.py (localização de pessoas), evitando conflito de abertura dupla do mesmo /dev/video."""
    while True:
        try:
            if camera_on and _shared.get("frame_amb") is not None:
                _shared["frame_porta"], _shared["porta_t"] = _shared["frame_amb"], _shared.get("amb_t", 0.0)
            time.sleep(0.15)
        except Exception:
            time.sleep(1.0)



def _sentidos():
    """resumo VIVO e barato para o cérebro (vai em todo turno): quem as câmeras veem, câmera com motor, modos."""
    agora, partes = time.time(), []
    if agora - scene.get("t", 0) < 5:
        fs = [str(f.get("nome") or "pessoa desconhecida") for f in scene.get("faces") or []]
        partes.append("câmera do notebook: " + (", ".join(fs) if fs else "ninguém"))
    if agora - scene.get("t_amb_faces", 0) < 8:
        fa = [f"{f.get('nome') or 'desconhecido'} {f.get('lado', '')}".strip() for f in scene.get("amb_faces") or []]
        if fa:
            partes.append("rostos na câmera do quarto: " + ", ".join(fa))
    try:                                             # rostos e estado da PTZ já vão no _friday_ctx: aqui só as câmeras FIXAS
        partes.append(_mundo().falado())
    except Exception:
        pass
    gc = [f"mão levantada na {'webcam da porta' if c_ == 'porta' else 'câmera do notebook'}"
          for c_, (g_, t_g) in list((scene.get("gesto_cams") or {}).items()) if agora - t_g < 15]
    if gc:
        partes.append(", ".join(gc))
    sons = {}
    for t_s, n_s, p_s in _sons["ult"]:
        if agora - t_s < 30:
            sons[n_s] = max(sons.get(n_s, 0), p_s)
    if sons:
        partes.append("sons nos últimos 30 s: " + ", ".join(f"{n_}" for n_, _ in sorted(sons.items(), key=lambda kv: -kv[1])[:4]))
    ativos = [k for k, v in modes.items() if v is True]
    if ativos:
        partes.append("modos ligados: " + ", ".join(ativos[:6]))
    try:
        import friday as _frj
        j = _frj.focused_window() or {}
        tit = ((j.get("title") or j.get("app_id") or "") if isinstance(j, dict) else "")
        if tit:
            partes.append("janela em foco: " + str(tit)[:80])
    except Exception:
        pass
    return "; ".join(partes)


def _aviso_entrada(n):
    """alguém apareceu na webcam da porta (ela estava vazia): quem é? -> o cérebro decide se avisa."""
    agora, dono = time.time(), _owner_name()
    rostos = (scene.get("amb_faces") or []) if agora - scene.get("t_amb_faces", 0) < 4 else []
    nomes = [str(f.get("nome") or "") for f in rostos]
    if any(n_.lower() == dono.lower() for n_ in nomes):
        desc = f"o {dono} entrou no quarto pela porta (webcam da porta)"
    elif any(nomes):
        desc = f"{', '.join(n_ for n_ in nomes if n_)} entrou no quarto pela porta (rosto reconhecido na webcam da porta)"
    elif rostos:
        desc = "uma pessoa DESCONHECIDA entrou no quarto pela porta (rosto não reconhecido na webcam da porta)"
    else:
        desc = f"apareceu {'uma pessoa' if n == 1 else f'{n} pessoas'} na webcam da porta (a porta estava vazia; rosto ainda não visto)"
    _evento_autonomo(desc, tipo="porta")


def mundo_thread():
    """Pessoas nas câmeras FIXAS (yolov8n-pose, 1 thread) -> mundo.observar. Com a PTZ no ar: porta + nativa a ~2,5 Hz;
    sem PTZ: só a porta a ~1 Hz (aviso de entrada e contagem para o cérebro continuam). (4 Hz/2 threads = ~90% de um núcleo)
    Também: porta vazia -> alguém apareceu = aviso; mão levantada em 3 leituras seguidas = gesto da câmera."""
    if ptz is None:
        return
    M, pose, ult, ult_salva = _mundo(), None, {}, time.time()
    while True:
        com_ptz = ipcam is not None and ipcam.atual() is not None
        time.sleep(0.4 if com_ptz else 1.0)
        if not camera_on:
            time.sleep(1.0)
            continue
        try:
            if pose is None:
                pose = ptz.Pose(threads=1)                 # instância própria: não disputa a sessão do rastreio da PTZ
            cams = (("porta", "frame_porta", "porta_t"), ("nativa", "frame", "frame_t")) if com_ptz else (("porta", "frame_porta", "porta_t"),)
            for cam, fk, tk in cams:
                f_, t_ = _shared.get(fk), _shared.get(tk, 0.0)
                if f_ is None or time.time() - t_ > 1.0 or ult.get(cam) == t_:
                    continue
                ult[cam] = t_
                ps, mao = [], False
                for q in pose.pessoas(f_):
                    if q["conf"] >= 0.45 and q["kp"] >= 3:
                        x0, y0, x1, y1 = q["caixa"]
                        u, v = q["cabeca"] or ((x0 + x1) / 2, y0 + (y1 - y0) * 0.2)
                        ps.append((float(u), float(v), float(q["conf"])))
                        mao = mao or bool(q.get("mao_alta"))
                if cam == "nativa" and len(ps) > 1 and time.time() - scene.get("t", 0) < 2:
                    _dono = _owner_name().lower()
                    _fd = [f_c for f_c in scene.get("faces") or [] if str(f_c.get("nome") or "").lower() == _dono and f_c.get("box")]
                    if _fd:
                        _ud = (_fd[0]["box"][0] + _fd[0]["box"][2] / 2) / 320.0     # box do rosto está em f_proc 320x240 (não em px do quadro)
                        ps = [min(ps, key=lambda p_: abs(p_[0] - _ud))]
                M.observar(cam, t_, ps)
                if cam == "porta" and M.entrada("porta", t_, len(ps)):
                    _aviso_entrada(len(ps))
                if M.gesto(cam, t_, mao):
                    scene.setdefault("gesto_cams", {})[cam] = ("mao_levantada", t_)
                    print(f"{time.strftime('%H:%M:%S')} gesto: mão levantada na câmera {cam}", flush=True)
            if time.time() - ult_salva > 60:
                ult_salva = time.time()
                M.salvar()
        except Exception as e:
            print("mundo:", repr(e), flush=True)
            time.sleep(3)


# ---------- duas câmeras: NATIVA (notebook) = rosto/mãos/gestos; EXTERNA (USB) = ambiente (objetos, cena, "o que você vê") ----------
def frame_ambiente(quem=""):
    """quadro da câmera externa se ela estiver viva (< 2 s); senão o da nativa (fallback automático)."""
    fa = _shared.get("frame_amb")
    viva = fa is not None and time.time() - _shared.get("amb_t", 0) < 2.0
    if quem:
        print(f"{time.strftime('%H:%M:%S')} visão[{quem}] usando câmera {'EXTERNA' if viva else 'NATIVA'} "
              f"(externa: {'sem quadro' if fa is None else f'{time.time() - _shared.get("amb_t", 0):.1f}s'})", flush=True)
    return fa if viva else _shared.get("frame")


class _LeitorRTSP:
    """RTSP da PTZ decodificado num ffmpeg à parte (quadros BGR por pipe): a carga do daemon não faz perder pacote UDP,
    e release() manda SIGINT -> o ffmpeg envia TEARDOWN (sessão órfã derruba o firmware). Interface igual à do cv2.VideoCapture."""
    def __init__(self, url, w=None, h=None):
        if w is None:
            w, h = (640, 360) if url.rstrip("/").endswith("onvif2") else (1280, 720)
        self.w, self.h, self.n = w, h, w * h * 3
        self.p = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "udp",
                                   "-timeout", "3000000",
                                   "-allowed_media_types", "video", "-buffer_size", "4194304",
                                   "-fflags", "nobuffer+discardcorrupt", "-flags", "low_delay", "-max_delay", "0", "-reorder_queue_size", "0",
                                   "-i", url, "-an", "-vf", f"scale={w}:{h}",
                                   "-pix_fmt", "bgr24", "-f", "rawvideo", "-"],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.quadros = 0

    def isOpened(self):
        return self.p.poll() is None

    def read(self, espera=6.0):
        import select
        import numpy as np
        buf = bytearray(self.n)
        mv, got, fim = memoryview(buf), 0, time.time() + espera
        fd = self.p.stdout.fileno()
        while got < self.n:
            r, _, _ = select.select([fd], [], [], max(0.0, fim - time.time()))
            if not r:
                return False, None
            k = os.readv(fd, [mv[got:]])
            if k <= 0:
                return False, None
            got += k
        self.quadros += 1
        return True, np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)

    def release(self):
        """SIGINT e continua lendo o pipe até o ffmpeg sair: parado escrevendo no pipe ele não fecha (nem manda TEARDOWN)."""
        try:
            if self.p.poll() is None:
                self.p.send_signal(signal.SIGINT)
                fim = time.time() + 5
                fd = self.p.stdout.fileno()
                os.set_blocking(fd, False)
                while self.p.poll() is None and time.time() < fim:
                    try:
                        if not os.read(fd, 1 << 20):
                            break
                    except BlockingIOError:
                        time.sleep(0.05)
                self.p.wait(1)
        except Exception:
            pass
        if self.p.poll() is None:
            try:
                self.p.kill()
            except Exception:
                pass


def cam_ambiente_thread():
    """câmera de AMBIENTE / MESA: 1ª webcam USB externa física (Logitech C270 /dev/video2).
    Gera /tmp/friday-cam-amb.jpg e armazena _shared['frame_amb']."""
    import cv2
    cap, dev = None, None
    falhas = 0
    while True:
        if not camera_on:
            if cap is not None:
                cap.release(); cap = None
            _shared["frame_amb"] = None
            time.sleep(0.5); continue
        if cap is None:
            dev = _cam_usb_dev()
            if not dev:
                _shared["frame_amb"] = None
                time.sleep(3); continue
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1); cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            try:
                subprocess.run(["v4l2-ctl", "-d", str(dev), "--set-ctrl=exposure_dynamic_framerate=0"], capture_output=True, timeout=3)
            except Exception:
                pass
            if not cap.isOpened():
                cap.release(); cap = None; time.sleep(5); continue
            falhas = 0
            print("câmera USB externa conectada:", dev, flush=True)

        ok, fr_ = cap.read()
        if not ok:
            falhas += 1
            if falhas >= 3:
                cap.release(); cap = None; _shared["frame_amb"] = None
                time.sleep(2)
            continue
        falhas = 0
        now_c = time.time()
        _shared["frame_amb"] = fr_
        _shared["amb_t"] = now_c

        if now_c - _shared.get("amb_w", 0) > 0.045:
            _shared["amb_w"] = now_c
            try:
                amb_f = scene.get("amb_faces", []) if (now_c - scene.get("t_amb_faces", 0) < 2.5) else []
                holo = _holo_cam(fr_, [], amb_f, mirror=False)
                cv2.putText(holo, "LOGITECH C270 // MESA", (6, 232), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 229, 255), 1, cv2.LINE_AA)
                cv2.imwrite("/tmp/friday-cam-amb.tmp.jpg", holo, [cv2.IMWRITE_JPEG_QUALITY, 72])
                os.replace("/tmp/friday-cam-amb.tmp.jpg", "/tmp/friday-cam-amb.jpg")
            except Exception:
                pass
        time.sleep(0.005)


_COR_PTZ = {"ir": False, "escuro": False, "br": 120.0}


def _restaurar_cor_ptz(fr, ref_ab, st=_COR_PTZ):
    """A PTZ (Yoosee) troca sozinha para IR (preto e branco) e o firmware não deixa travar (ONVIF imaging fecha a conexão).
    Regra do dono: imagem SEMPRE colorida; infravermelho de verdade só com o quarto MUITO escuro.
    - IR do hardware detectado por croma com HISTERESE (entra < 4.5, sai > 7.0): antes era um limite só (5.5) e a
      imagem alternava cor real / recolorida a cada quadro.
    - Quarto escuro = brilho médio das câmeras coloridas (porta C270, senão a nativa), suavizado (entra < 28, sai > 45).
    - IR + quarto claro -> recolore (Lab de referência). IR + quarto escuro -> IR realçado (CLAHE), marcado na imagem."""
    import cv2, numpy as np
    b, g, r = fr[::4, ::4, 0].astype("int16"), fr[::4, ::4, 1].astype("int16"), fr[::4, ::4, 2].astype("int16")
    croma = float(np.abs(r - g).mean() + np.abs(g - b).mean())
    if st["ir"] and croma > 7.0:
        st["ir"] = False
    elif not st["ir"] and croma < 4.5:
        st["ir"] = True
    agora = time.time()
    ref_fr = _shared.get("frame_amb") if agora - _shared.get("amb_t", 0) < 2 else None
    if ref_fr is None and agora - _shared.get("frame_t", 0) < 2:
        ref_fr = _shared.get("frame")
    if ref_fr is not None:
        try:
            st["br"] = 0.92 * st["br"] + 0.08 * float(ref_fr[::8, ::8].mean())
        except Exception:
            pass
    if st["escuro"] and st["br"] > 45:
        st["escuro"] = False
    elif not st["escuro"] and st["br"] < 28:
        st["escuro"] = True
    if st["ir"] and st["escuro"]:
        try:
            gray = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
            out = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            cv2.putText(out, "IR NOTURNO", (out.shape[1] - 120, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 200, 255), 1, cv2.LINE_AA)
            return out
        except Exception:
            return fr
    if not st["ir"]:
        try:
            lab_ok = cv2.cvtColor(cv2.resize(fr, (160, 90)), cv2.COLOR_BGR2LAB)
            ref_ab[0] = lab_ok[:, :, 1:].astype("float32")
        except Exception:
            pass
        return fr
    try:
        lab = cv2.cvtColor(fr, cv2.COLOR_BGR2LAB)
        L = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(lab[:, :, 0])
        Lf = L.astype("float32") / 255.0
        # Tom natural de ambiente interno iluminado (sombras frias azuladas, meios-tons quentes/pele, altas-luzes neutras)
        mid = 4.0 * Lf * (1.0 - Lf)
        a_syn = 128.0 + 7.5 * mid + 3.0 * Lf
        b_syn = 128.0 + 14.0 * mid - 5.0 * (1.0 - Lf)
        if ref_ab[0] is not None:
            ab_up = cv2.resize(ref_ab[0], (fr.shape[1], fr.shape[0]), interpolation=cv2.INTER_LINEAR)
            a_syn = 0.55 * ab_up[:, :, 0] + 0.45 * a_syn
            b_syn = 0.55 * ab_up[:, :, 1] + 0.45 * b_syn
        elif _shared.get("frame_amb") is not None:
            try:
                amb_lab = cv2.cvtColor(cv2.resize(_shared["frame_amb"], (160, 90)), cv2.COLOR_BGR2LAB)
                a_m = float(amb_lab[:, :, 1].mean()) - 128.0
                b_m = float(amb_lab[:, :, 2].mean()) - 128.0
                a_syn += np.clip(a_m * 0.5, -8.0, 10.0)
                b_syn += np.clip(b_m * 0.5, -8.0, 12.0)
            except Exception:
                pass
        lab[:, :, 0] = L
        lab[:, :, 1] = np.clip(a_syn, 110, 156).astype("uint8")
        lab[:, :, 2] = np.clip(b_syn, 108, 162).astype("uint8")
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    except Exception:
        return fr


def cam_ptz_thread():
    """câmera PTZ WIRELESS 360° (Aitek ML-310 / ONVIF RTSP).
    Lê stream 640x360 @ 15fps, atualiza _shared['frame_ptz'] e gera /tmp/friday-cam-ptz.jpg com HUD do motor."""
    import cv2
    cap = None
    falhas = 0
    ref_ab = [None]
    while True:
        if not camera_on:
            if cap is not None:
                cap.release(); cap = None
            _shared["frame_ptz"] = None
            time.sleep(0.5); continue

        if cap is None:
            url_ptz = None
            if ipcam is not None:
                c_ip = ipcam.obter(forcar=True, intervalo=2.5) if ipcam.atual() is None else ipcam.atual()
                if c_ip is not None:
                    url_ptz = c_ip.rtsp_sub
            if not url_ptz:
                conf = ipcam.ler_conf() if ipcam is not None else {}
                ip_ptz = conf.get("ip")
                if ip_ptz:
                    p_ok = False
                    try:
                        _s = socket.socket()
                        _s.settimeout(0.4)
                        p_ok = (_s.connect_ex((ip_ptz, 554)) == 0)
                        _s.close()
                    except Exception:
                        pass
                    if p_ok:
                        url_ptz = conf.get("rtsp_sub") or f"rtsp://{ip_ptz}:554/onvif2"
            if not url_ptz:
                _shared["frame_ptz"] = None
                if os.path.exists("/tmp/friday-cam-ptz.jpg"):
                    try:
                        os.unlink("/tmp/friday-cam-ptz.jpg")
                    except OSError:
                        pass
                time.sleep(2.0); continue

            try:
                cap = _LeitorRTSP(url_ptz, 640, 360)
                _shared["cap_ptz"] = cap                         # o desligamento do daemon fecha (TEARDOWN): sem isso o firmware reinicia
                if not cap.isOpened():
                    cap.release(); cap = None
                    if os.path.exists("/tmp/friday-cam-ptz.jpg"):
                        try:
                            os.unlink("/tmp/friday-cam-ptz.jpg")
                        except OSError:
                            pass
                    time.sleep(2.0); continue
                falhas = 0
                print("câmera PTZ conectada:", url_ptz.split("@")[-1] if "@" in url_ptz else url_ptz, flush=True)
            except Exception as e:
                cap = None
                if os.path.exists("/tmp/friday-cam-ptz.jpg"):
                    try:
                        os.unlink("/tmp/friday-cam-ptz.jpg")
                    except OSError:
                        pass
                time.sleep(2.0); continue

        if _PTZ_HD["pedido"] and time.time() - _PTZ_HD["pedido"] < 6:      # "ver longe": troca a ÚNICA sessão p/ o onvif1 por ~2 s
            _PTZ_HD["pedido"] = 0.0
            url_hd = None
            try:
                c_ip = ipcam.atual() if ipcam is not None else None
                url_hd = c_ip.rtsp if c_ip is not None else None
            except Exception:
                pass
            if url_hd:
                cap.release(); cap = None
                hd = None
                try:
                    cap_hd = _LeitorRTSP(url_hd, 1280, 720)
                    fim_hd, n_hd = time.time() + 4.0, 0
                    while time.time() < fim_hd:
                        ok_hd, f_hd = cap_hd.read(espera=2.5)
                        if not ok_hd:
                            break
                        n_hd += 1
                        hd = f_hd
                        if n_hd >= 6:                          # passa dos primeiros quadros (até o I-frame limpar)
                            break
                    cap_hd.release()
                except Exception as e:
                    print("ptz HD:", repr(e), flush=True)
                if hd is not None:
                    _PTZ_HD["frame"] = _restaurar_cor_ptz(hd.copy(), ref_ab)
                    _PTZ_HD["t"] = time.time()
                    print(f"ptz: quadro HD 1280x720 para zoom ({n_hd} quadros)", flush=True)
                continue                                        # cap None -> reabre o onvif2 no topo do laço
        ok, fr_ = cap.read(espera=4.0)
        if not ok or fr_ is None:
            falhas += 1
            if falhas >= 3:
                if cap is not None:
                    cap.release(); cap = None
                _shared["frame_ptz"] = None
                if os.path.exists("/tmp/friday-cam-ptz.jpg"):
                    try:
                        os.unlink("/tmp/friday-cam-ptz.jpg")
                    except OSError:
                        pass
                if ipcam is not None:
                    ipcam.perdeu()
                time.sleep(2.0)
            continue

        falhas = 0
        fr_ = _restaurar_cor_ptz(fr_, ref_ab)
        now_c = time.time()
        _shared["frame_ptz"] = fr_
        _shared["ptz_t"] = now_c

        if now_c - _shared.get("ptz_w", 0) > 0.045:
            _shared["ptz_w"] = now_c
            try:
                ptz_f = list(scene.get("ptz_faces") or []) if (now_c - scene.get("t_ptz_faces", 0) < 2.5) else []
                p_inst = ptz.get_ptz() if ptz is not None else None
                alvo_cx = p_inst.alvo.get("caixa") if (p_inst and p_inst.alvo and now_c - p_inst.alvo.get("t", 0) < 3.0) else None
                fr_hud, z_hud, tz = _zoom_auto_ptz(fr_, alvo_cx)
                if z_hud > 1.0:
                    ptz_f = []                                   # caixas de rosto são do quadro inteiro; o alvo é redesenhado abaixo
                if not ptz_f and ptz is not None:
                    if p_inst and p_inst.alvo and (now_c - p_inst.alvo.get("t", 0) < 3.0):
                        cx_ = tz(p_inst.alvo.get("caixa")) if p_inst.alvo.get("caixa") else None
                        if cx_ and len(cx_) >= 4:
                            x0_ = float(cx_[0]) * 320.0
                            y0_ = float(cx_[1]) * 240.0
                            w_ = float(cx_[2] - cx_[0]) * 320.0
                            h_ = float(cx_[3] - cx_[1]) * 240.0
                            nome_t = "IANN" if _ptz_presente() else "ALVO"
                            ptz_f.append({"nome": nome_t, "box": [x0_, y0_, w_, h_]})
                holo = _holo_cam(fr_hud, [], ptz_f, mirror=False)
                if ptz is not None:
                    txt_h = ptz.get_ptz().texto_hud()
                    if txt_h:
                        cv2.putText(holo, txt_h, (6, 232), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 138, 31), 1, cv2.LINE_AA)
                cv2.imwrite("/tmp/friday-cam-ptz.tmp.jpg", holo, [cv2.IMWRITE_JPEG_QUALITY, 72])
                os.replace("/tmp/friday-cam-ptz.tmp.jpg", "/tmp/friday-cam-ptz.jpg")
            except Exception:
                pass
        time.sleep(0.005)


def object_thread():
    """Objetos à vista (YOLOX, local) ~a cada 1,3 s."""
    try:
        od = senses.detector_objetos() if senses is not None else None
    except Exception as e:
        print("detector de objetos indisponível:", e, flush=True); return
    if od is None:
        return
    while True:
        fr = frame_ambiente()            # câmera externa (ambiente) se conectada; senão a nativa
        externa = fr is not None and fr is _shared.get("frame_amb")      # veio MESMO da externa? (a nativa assume quando ela some)
        if fr is None or not camera_on:
            time.sleep(1.0); continue
        try:
            cont = {}; caixas = []; pessoas = []
            for nome, conf, box in od.detect(fr, 0.30):
                if nome != "pessoa":
                    caixas.append((nome, conf, box))
                    if conf >= 0.45:
                        cont[nome] = cont.get(nome, 0) + 1
                elif externa and conf >= 0.35:
                    pessoas.append((conf, box))
            scene["objetos"] = cont; scene["t_obj"] = time.time(); scene["obj_boxes"] = (time.time(), caixas)
            if externa:                  # pessoas na câmera externa (msg "visao"): caixas 0..1 no quadro dela, mais confiantes primeiro
                try:
                    H_, W_ = fr.shape[:2]
                    scene["amb_pessoas"] = (time.time(), [{"box": senses.caixa_norm(b_, W_, H_), "conf": round(float(c_), 3)}
                                                          for c_, b_ in sorted(pessoas, key=lambda p_: -p_[0])[:6]])
                except Exception as e:
                    print("visão (pessoas no ambiente):", repr(e), flush=True)
            maos = {}
            if time.time() - scene["t_wr"] < 2:
                H, W = fr.shape[:2]
                for lado, (wx, wy) in scene["wrists"].items():
                    r = 110
                    x0, y0 = int(max(0, wx - r)), int(max(0, wy - r))
                    crop = fr[y0:int(min(H, wy + r)), x0:int(min(W, wx + r))]
                    if crop.shape[0] < 60 or crop.shape[1] < 60:
                        continue
                    _impl = {"gato", "cachorro", "cavalo", "ovelha", "vaca", "elefante", "urso", "zebra", "girafa", "pássaro",
                             "avião", "trem", "barco", "carro", "ônibus", "caminhão", "semáforo", "hidrante", "cama", "sofá"}
                    cand = [(c, n) for n, c, _ in od.detect(crop, conf=0.20) if n != "pessoa" and n not in _impl]
                    best = max(cand, default=None)
                    if best:
                        nome_o = best[1]
                        # celular de lado/na mão é muito confundido com controle remoto: o detector de quadro inteiro desempata
                        if nome_o in ("controle remoto", "mouse") and (cont.get("celular") or any(n == "celular" for _, n in cand)):
                            nome_o = "celular"
                        maos[lado] = f"{nome_o} ({int(best[0] * 100)}%)"
            scene["maos"] = maos; scene["t_hand"] = time.time()
            try:                                                   # diagnóstico (sem dados biométricos)
                with open("/tmp/prometheus-scene.json", "w") as _f:
                    json.dump({"objetos": cont, "maos": maos, "punhos": {k: [round(v[0]), round(v[1])] for k, v in scene["wrists"].items()},
                               "camisa": [f.get("camisa") for f in scene["faces"]], "dbg_cor": scene.get("dbg_cor"), "vlm": scene.get("vlm"), "vlm_idade_s": round(time.time() - scene["t_vlm"], 1), "motion": round(scene["motion"], 4)}, _f, ensure_ascii=False)
            except Exception:
                pass
        except Exception as e:
            print("objetos:", e, flush=True)
        time.sleep(8.0 if time.time() - scene["t"] < 8 else 20.0)       # objetos mudam devagar: poucos ciclos (YOLOX-m é pesado); ausente = ainda menos


VISION_RE = re.compile(r"\b(o que (você )?(est[áa]|v[êe])|est[áa] vendo|v[êe] (aí|ai|isso)|mostr|segurando|na minha m[ãa]o|"
                       r"descrev|olha (isso|aqui|para)|que (objeto|coisa)|c[âa]mera)\b", re.I)


VLM_PROMPT = ("List everything visible in this webcam image as short comma-separated items: each person with clothing "
              "colors and what each hand holds (the image is NOT mirrored: the person's anatomical RIGHT hand appears on the "
              "LEFT side of the image; name hands anatomically), every object with its color, what the screens/papers show, "
              "and the background. Max 70 words. Write 'unclear' for anything uncertain; never guess.")


def vlm_describe(frame) -> str:
    """Descrição aberta (qualquer objeto) pelo VLM local via Ollama em 127.0.0.1. Vazio se indisponível."""
    import base64, urllib.request
    try:
        import cv2, numpy as np
        m = float(frame.mean())
        if m < 100:                                           # webcam escura: gama + CLAHE no canal de luminância
            g = np.clip(100.0 / max(m, 20.0), 1.0, 2.6)
            lut = (255.0 * (np.arange(256) / 255.0) ** (1.0 / g)).astype("uint8")
            frame = cv2.LUT(frame, lut)
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
            frame = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        body = json.dumps({"model": VLM_MODEL, "stream": False,
                           "options": {"temperature": 0.0, "num_predict": 140, "num_ctx": VLM_NUM_CTX, "num_gpu": VLM_NUM_GPU},
                           "prompt": VLM_PROMPT,
                           "images": [base64.b64encode(jpg.tobytes()).decode()]}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read()).get("response", "").strip()[:700]
    except Exception as e:
        print("vlm:", e, flush=True)
        return ""


VLM_MODEL = fr.MODEL if "fr" in globals() and fr is not None else "qwen3-vl:4b-instruct"
VLM_NUM_GPU = fr.NUM_GPU if "fr" in globals() and fr is not None else 99   # igual ao friday.py: num_gpu diferente recarrega o modelo
VLM_NUM_CTX = int(os.environ.get("FRIDAY_NUM_CTX", "16384"))


HAND_PROMPT = ("The person's hand is in the center of this close-up. What object is the hand holding? "
               "Answer with just the object name in English (examples: smartphone, pen, cup, remote control, mouse, "
               "keys, nothing). If the hand is empty or you are unsure, answer 'nothing'.")


def vlm_hand(crop) -> str:
    import base64, urllib.request
    try:
        import cv2
        crop = cv2.resize(crop, (448, 448), interpolation=cv2.INTER_CUBIC)
        ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        body = json.dumps({"model": VLM_MODEL, "stream": False,
                           "options": {"temperature": 0.0, "num_predict": 12, "num_ctx": VLM_NUM_CTX, "num_gpu": VLM_NUM_GPU}, "prompt": HAND_PROMPT,
                           "images": [base64.b64encode(jpg.tobytes()).decode()]}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("response", "").strip().strip(".").lower()[:40]
    except Exception as e:
        print("vlm mão:", e, flush=True)
        return ""


def vlm_thread():
    """Olhar contínuo: mantém uma descrição fresca da cena, atualizada quando algo muda (nada de gatilhos por palavra)."""
    import cv2
    prev = None
    while True:
        fr = frame_ambiente()            # câmera externa (ambiente) se conectada; senão a nativa
        if fr is None or not camera_on:
            time.sleep(1.0); continue
        small = cv2.cvtColor(cv2.resize(fr, (64, 48)), cv2.COLOR_BGR2GRAY).astype("float32")
        changed = prev is None or float(abs(small - prev).mean()) > 4.0
        age = time.time() - scene["t_vlm"]
        occupied = bool(scene["faces"]) and time.time() - scene["t"] < 5
        if (changed and age > 2.0) or age > 20:
            if occupied or age > 60:                      # sem ninguém por perto, olha só de minuto em minuto (poupa GPU)
                prev = small
                txt = vlm_describe(fr)
                if txt:
                    scene["vlm"] = txt; scene["t_vlm"] = time.time()
                if time.time() - scene["t_wr"] < 2 and scene["wrists"]:      # zoom em cada mão
                    H, W = fr.shape[:2]
                    res = {}
                    for lado, (wx, wy) in list(scene["wrists"].items()):
                        r = 120
                        crop = fr[int(max(0, wy - r)):int(min(H, wy + r)), int(max(0, wx - r)):int(min(W, wx + r))]
                        if crop.shape[0] < 80 or crop.shape[1] < 80:
                            continue
                        obj = vlm_hand(crop)
                        if obj and obj != "nothing":
                            res[lado] = obj
                    scene["maos_vlm"] = res; scene["t_mvlm"] = time.time()
        time.sleep(0.5)


def describe_scene() -> str:
    """Descrição fresca: usa o cache do olhar contínuo; se estiver velho, olha agora."""
    if time.time() - scene["t_vlm"] < 5 and scene["vlm"]:
        return scene["vlm"]
    fr = frame_ambiente()            # câmera externa (ambiente) se conectada; senão a nativa
    if fr is None or not camera_on:
        return ""
    txt = vlm_describe(fr)
    if txt:
        scene["vlm"] = txt; scene["t_vlm"] = time.time()
    return txt


GEST_COOLDOWN = {}          # tipo -> último disparo
VISUAL_Q = re.compile(
    r"\b(v[êe]|vendo|olh[ae]|enxerg|c[âa]mera|aparece|segurand|na m[ãa]o|m[ãa]os?|tenho|seguro|mostrand|"
    r"camisa|que cor|cor d|o que (tem|est[áa]|[ée] isso|voc[êe] v|eu tenho)|quem est[áa]|tem algu[ée]m|"
    r"quantas? pessoas|est[áa] vendo|v[êe] isso|e agora|e este|e esse|e essa|troquei|mudou|olha de novo|v[êe] de novo)\b",
    re.I
)
HANDS_Q = re.compile(
    r"\b(m[ãa]os?|segurand\w*|tenho\s+(?:na|em)|seguro|mostrand\w*|o\s+que\s+[ée]\s+isso|"
    r"o\s+que\s+tem\s+(?:aqui|na\s+m[ãa]o|na\s+minha)|olha\s+isso|v[êe]\s+isso|que\s+objeto|"
    r"e\s+agora|e\s+este|e\s+esse|e\s+essa|troquei|mudou|olha\s+de\s+novo|v[êe]\s+de\s+novo)\b",
    re.I
)
_last_visual_q_time = [0.0]
FILLERS = ["Deixa eu ver isso.", "Um instante.", "Só um segundo, estou verificando.", "Já olho isso.", "Estou nisso agora.", "Calma, já te digo."]
REACT = {                   # gesto -> (frase falada, humor)
    "acenou": ("Oi! Tudo bem?", "alegre"),
    "mão levantada": ("Pode falar, estou ouvindo.", "curioso"),
    "duas mãos levantadas": ("Calma, eu me rendo também! Posso ajudar?", "alegre"),
    "disse sim com a cabeça": ("Combinado então!", "alegre"),
    "disse não com a cabeça": ("Tudo bem, deixo de lado.", "neutro"),
    "bateu palmas": ("Obrigado pelas palmas!", "alegre"),
    "apontou": ("Quer que eu olhe para lá?", "curioso"),
    "aproximou-se": ("Opa, chegou perto! Está tudo bem?", "curioso"),
    "afastou-se": ("Está indo para longe? Eu continuo aqui.", "neutro"),
    "cruzou os braços": ("Pensativo? Me diz o que está pegando.", "pensativo"),
    "levantou-se": ("Vai se levantar? Eu fico de olho por aqui.", "neutro"),
    "agachou": ("Procurando alguma coisa no chão?", "curioso"),
    "joinha": ("Joinha recebido!", "alegre"),
    "paz": ("Paz e amor!", "alegre"),
    "ok": ("Beleza, tudo certo então!", "alegre"),
    "apontar ": ("Estou olhando.", "curioso"),
}


def _reversals(v, amp):
    """Conta inversões de direção em uma série, com histerese `amp`."""
    if len(v) < 4:
        return 0
    n, last, direction = 0, v[0], 0
    for x in v[1:]:
        if direction >= 0 and x <= last - amp:
            if direction == 1: n += 1
            direction, last = -1, x
        elif direction <= 0 and x >= last + amp:
            if direction == -1: n += 1
            direction, last = 1, x
        elif (direction == 1 and x > last) or (direction == -1 and x < last) or direction == 0:
            last = x if direction != 0 else last
    return n


def classify_gestures(hist):
    """hist: lista de (t, kp17x3) dos últimos ~2 s. Devolve lista de gestos completos reconhecidos."""
    import numpy as np
    if len(hist) < 8:
        return []
    t = np.array([h[0] for h in hist]); K = np.stack([h[1] for h in hist])        # (N,17,3)
    if t[-1] - t[0] < 0.9:
        return []
    sw = np.linalg.norm(K[:, 5, :2] - K[:, 6, :2], axis=1)
    ok = (K[:, 5, 2] > 0.4) & (K[:, 6, 2] > 0.4) & (sw > 15)
    if ok.mean() < 0.7:
        return []
    u = float(np.median(sw[ok]))                                                   # unidade = largura de ombros
    out = []

    def ser(i, ax):
        return K[:, i, ax] / u

    def vis(i, thr=0.35):
        return K[:, i, 2] > thr

    # --- acenar / mão levantada (cada lado) ---
    for w, e, sh in ((9, 7, 5), (10, 8, 6)):
        v = vis(w) & vis(sh)
        if v.mean() < 0.6:
            continue
        above_sh = (K[:, w, 1] < K[:, sh, 1] - 0.2 * u)
        above_el = (K[:, w, 1] < K[:, e, 1]) & vis(e)
        if above_el[v].mean() > 0.6 and _reversals(ser(w, 0)[v], 0.22) >= 3:
            out.append("acenou")
        elif above_sh[v].mean() > 0.8 and np.std(ser(w, 0)[v]) < 0.18 and (t[-1] - t[0]) > 1.0:
            out.append("mão levantada")
    if "mão levantada" in out and out.count("mão levantada") == 2:
        out = [g for g in out if g != "mão levantada"] + ["duas mãos levantadas"]

    # --- cabeça: sim / não ---
    nv = vis(0, 0.4)
    if nv.mean() > 0.7:
        nx, ny = ser(0, 0)[nv], ser(0, 1)[nv]
        if _reversals(ny, 0.16) >= 3 and (ny.max() - ny.min()) > 0.30 and (nx.max() - nx.min()) < 0.30 and (t[-1] - t[0]) > 1.3:
            out.append("disse sim com a cabeça")
        elif _reversals(nx, 0.18) >= 4 and (nx.max() - nx.min()) > 0.35 and (ny.max() - ny.min()) < 0.25 and (t[-1] - t[0]) > 1.3:
            out.append("disse não com a cabeça")

    # --- palmas ---
    if vis(9).mean() > 0.6 and vis(10).mean() > 0.6:
        d = np.hypot(K[:, 9, 0] - K[:, 10, 0], K[:, 9, 1] - K[:, 10, 1]) / u
        if d.min() < 0.3 and d.max() > 0.7 and _reversals(d, 0.25) >= 2:
            out.append("bateu palmas")
        # braços cruzados: cada punho perto do cotovelo oposto, parado
        c = (np.hypot(K[:, 9, 0] - K[:, 8, 0], K[:, 9, 1] - K[:, 8, 1]) / u < 0.55) & \
            (np.hypot(K[:, 10, 0] - K[:, 7, 0], K[:, 10, 1] - K[:, 7, 1]) / u < 0.55)
        if c.mean() > 0.8 and (t[-1] - t[0]) > 1.2:
            out.append("cruzou os braços")

    # --- apontar (braço esticado na horizontal) ---
    for w, sh in ((9, 5), (10, 6)):
        if vis(w).mean() > 0.7:
            dx = np.abs(K[:, w, 0] - K[:, sh, 0]) / u
            dy = np.abs(K[:, w, 1] - K[:, sh, 1]) / u
            if (dx > 1.3).mean() > 0.8 and (dy < 0.55).mean() > 0.8:
                out.append("apontou")

    # --- corpo: aproximar/afastar e levantar/agachar ---
    q = max(1, len(sw) // 4)
    a, b = float(np.median(sw[:q][ok[:q]])) if ok[:q].any() else 0, float(np.median(sw[-q:][ok[-q:]])) if ok[-q:].any() else 0
    if a > 0 and b > 0:
        if b / a > 1.35:
            out.append("aproximou-se")
        elif b / a < 0.74:
            out.append("afastou-se")
    if nv[:q].any() and nv[-q:].any():
        dyn = (float(np.median(K[-q:, 0, 1])) - float(np.median(K[:q, 0, 1]))) / u
        if dyn < -1.1:
            out.append("levantou-se")
        elif dyn > 1.1:
            out.append("agachou")
    return out


_HAND_CONN = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14),
              (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]
_holo_t = {"n": 0}


def _holo_cam(frame, hands, faces_info, objs=None, mirror=True):
    """visão da câmera com HUD Stark: preserva as cores reais com realce de nitidez/contraste, contornos sutis,
    faixa de varredura, esqueleto das mãos e molduras de rosto/alvo. 320x240."""
    import cv2 as c, numpy as np
    _holo_t["n"] += 1
    n = _holo_t["n"]
    W, H = 320, 240
    sx = W / float(frame.shape[1])
    sy = H / float(frame.shape[0])
    im = c.resize(frame, (W, H))
    if mirror:
        im = c.flip(im, 1)                                                        # espelho (câmera selfie/nativa)
    lab = c.cvtColor(im, c.COLOR_BGR2LAB)
    lab[:, :, 0] = c.createCLAHE(1.5, (4, 4)).apply(lab[:, :, 0])
    out = c.cvtColor(lab, c.COLOR_LAB2BGR).astype("float32")
    # linhas de varredura bem sutis + faixa que sobe
    out[::3] *= 0.94
    band = int((n * 3) % (H + 40)) - 20
    out[max(0, band):max(0, band + 10)] *= 1.07
    # vinheta leve nas bordas
    yy, xx = np.ogrid[:H, :W]
    vig = 1.0 - 0.18 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    out *= np.clip(vig, 0.72, 1.0)[..., None]
    out = np.clip(out, 0, 255).astype("uint8")
    # esqueleto das mãos
    for hnd in hands or []:
        if mirror:
            pts = [(int(W - 1 - p_[0] * sx), int(p_[1] * sy)) for p_ in hnd["lm"]]
        else:
            pts = [(int(p_[0] * sx), int(p_[1] * sy)) for p_ in hnd["lm"]]
        for a_, b_ in _HAND_CONN:
            c.line(out, pts[a_], pts[b_], (255, 255, 120), 1, c.LINE_AA)
        for p_ in pts:
            c.circle(out, p_, 2, (255, 255, 255), -1, c.LINE_AA)
    # rostos / alvos: cantos de mira + nome
    for f_ in faces_info or []:
        bx = f_.get("box")
        if not bx or len(bx) < 4:
            continue
        fx, fy, fw, fh = bx
        fw = max(14, int(fw))
        fh = max(14, int(fh))
        if mirror:
            x0 = int(W - 1 - (fx + fw))
            x1 = x0 + fw
        else:
            x0 = int(fx)
            x1 = x0 + fw
        y0 = int(fy)
        y1 = y0 + fh
        x0 = max(0, min(W - 1, x0))
        x1 = max(0, min(W - 1, x1))
        y0 = max(0, min(H - 1, y0))
        y1 = max(0, min(H - 1, y1))
        L = max(8, int(min(fw, fh) * 0.28))
        nome = (f_.get("nome") or "").strip()
        col = (120, 255, 160) if (nome.lower() == "iann") else ((0, 215, 255) if nome else (0, 165, 255))
        for (ax, ay, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            c.line(out, (ax, ay), (ax + dx * L, ay), col, 2, c.LINE_AA)
            c.line(out, (ax, ay), (ax, ay + dy * L), col, 2, c.LINE_AA)
        tag = (f"ALVO: {nome.upper()}" if nome else "ALVO: RASTREIO")[:16]
        c.putText(out, tag, (max(4, x0), max(14, y0 - 6)), c.FONT_HERSHEY_SIMPLEX, 0.38, col, 1, c.LINE_AA)
    # HUD do canto
    c.putText(out, "REC", (8, 14), c.FONT_HERSHEY_SIMPLEX, 0.4, (160, 255, 255), 1, c.LINE_AA)
    c.circle(out, (36, 10), 3, (80, 80, 255) if (n // 6) % 2 == 0 else (30, 30, 90), -1)
    return out


gmouse = [None]


def hand_thread(loop):
    """Dedos do usuário (MediaPipe Hands ONNX, local): formato da mão -> o avatar imita e reage."""
    try:
        ht = senses.HandTracker() if senses is not None else None
    except Exception as e:
        print("rastreio de mãos indisponível:", e, flush=True); return
    if ht is None:
        return
    try:
        import articulation as artic_h
    except Exception as e:
        print("articulação indisponível:", e, flush=True); return
    st = {"R": [None, 0, None, 0.0], "L": [None, 0, None, 0.0]}      # candidata, repetições, enviada, quando
    cam_prev = {"t": 0.0}
    fr_mod = fr_module                                                   # (dentro desta função `fr` é o QUADRO da câmera, não o módulo)
    gest_eng = fr_module.GestureEngine() if fr_module is not None else None
    hfilt = {}; hsent = {}; hmed = {}                                   # filtros One-Euro/mediana e último envio por mão
    hdiag = {"t": 0.0, "frames": 0, "with_hand": 0, "sent3d": 0, "last": {}, "tgt": {}}
    harm_ref = {}; harm_f = {}; harm_m = {}                             # braço guiado pela mão: centro do vaivém e filtros
    import numpy as np
    last_fid = -1
    while True:
        fid = _shared.get("frame_id", 0)
        if fid == last_fid:
            time.sleep(0.002)
            continue
        last_fid = fid

        fr = _shared.get("frame")
        if fr is None or not camera_on:
            time.sleep(0.1); continue

        ht.fast = bool(modes.get("mouse"))
        try:
            hands = ht.detect(fr)
        except Exception as e:
            print("mãos:", e, flush=True); time.sleep(0.05); continue

        W = fr.shape[1]
        H_ = fr.shape[0]
        now = time.time()
        tnow = now

        # DISPARO IMEDIATO DO MOUSE POR GESTOS (Zero Delay):
        # Executa diretamente após a detecção, antes de cinemática 3D ou I/O
        if friday_state.get("on") or modes.get("mouse"):
            try:
                if gmouse[0] is None:
                    import gestomouse as _gm
                    gmouse[0] = _gm.GestureMouse()
                gm_ = gmouse[0]
                _gm_quer = modes.get("mouse") and not agente_ativo[0]
                if gm_.on and not _gm_quer:
                    gm_.stop()
                gm_.on = _gm_quer
                if gm_.on:
                    gm_.update_all(now, hands or [], W, H_)
            except Exception as e:
                print("mouse por gestos:", e, flush=True)

        got = {}
        gest_obs = []
        hdiag["frames"] += 1
        if hands:
            hdiag["with_hand"] += 1
        # lado de cada mão: pelo punho mais próximo da pose do corpo (estável quando a mão cruza o meio); senão pela posição
        wr = scene.get("wrists") or {}
        wr_ok = tnow - scene.get("t_wr", 0) < 1.0 and wr
        taken = set()
        for hnd in sorted(hands, key=lambda h: h["cx"]):
            pose = senses.hand_pose(hnd["lm"])
            lado = None
            if wr_ok:
                w0 = hnd["lm"][0]
                cand = sorted(((float(np.hypot(w0[0] - p[0], w0[1] - p[1])), "R" if nome == "mão direita" else "L")
                               for nome, p in wr.items()), key=lambda c: c[0])
                for dist, ld in cand:
                    if ld not in taken and dist < 0.35 * W:
                        lado = ld; break
            if lado is None:
                lado = "R" if hnd["cx"] < W / 2 else "L"              # imagem não espelhada: mão direita do usuário fica à esquerda
                if lado in taken:
                    lado = "L" if lado == "R" else "R"
            taken.add(lado)
            got[lado] = pose
            try:
                scene.setdefault("wrists_new", {})["mão direita" if lado == "R" else "mão esquerda"] = (float(hnd["lm"][0][0]), float(hnd["lm"][0][1]))
                _xs, _ys = hnd["lm"][:, 0], hnd["lm"][:, 1]
                scene.setdefault("hand_boxes", {})[lado] = (float(_xs.min()), float(_ys.min()), float(_xs.max()), float(_ys.max()), time.time())
            except Exception:
                pass
            try:
                u = float(hnd["lm"][0][0]) / W; v = float(hnd["lm"][0][1]) / H_
                ref = harm_ref.get(lado)
                ref = u if ref is None else ref + (u - ref) * 0.08          # centro lento do vaivém
                harm_ref[lado] = ref
                r_ = float(np.clip((0.95 - v) / 0.65, 0.0, 1.0))             # 0 = mão embaixo/fora, 1 = mão alta
                out_ = float(np.clip(abs(u - 0.5) * 2.0, 0.0, 1.0))
                swing = float(np.clip((u - ref) * 3.5, -0.6, 0.6))           # aceno: oscila o antebraço
                tgt = [0.10 + 0.55 * r_, 0.06 + 0.40 * r_ + 0.18 * out_ * r_, 0.15 + 0.85 * r_ + (swing if lado == "R" else -swing) * (0.4 + 0.6 * r_)]
                hf = harm_f.setdefault(lado, [artic_h.OneEuro(1.6, 0.25) for _ in range(3)])
                hm = harm_m.setdefault(lado, [artic_h.Median(3) for _ in range(3)])
                tf = [f(m_(x), tnow) for f, m_, x in zip(hf, hm, tgt)]
                tf = [float(np.clip(tf[0], 0.05, 1.2)), float(np.clip(tf[1], -0.1, 0.9)), float(np.clip(tf[2], 0.12, 2.1)), 0.0]
                scene.setdefault("harm", {})[lado] = (tnow, tf)
                if float(hnd["conf"]) >= 0.35 and 0.04 < u < 0.96 and 0.06 < v < 0.93:      # mão parcialmente fora do quadro gera gestos falsos
                    gest_obs.append((float(hnd["conf"]), u, v, pose))
                hdiag["tgt"][lado] = [round(x, 2) for x in tf[:3]]
                hdiag["last"][lado] = {"conf": round(float(hnd["conf"]), 2), "u": round(u, 2), "v": round(v, 2), "pose": pose}
            except Exception as e:
                print("braço-da-mão:", e, flush=True)
            try:
                cs, th, sp, _nrm = artic_h.finger_params(hnd["lm"], hnd["z"])
                fa = (scene.get("fa") or {}).get("R" if lado == "R" else "L", (0.0, 0.0))
                wf, wd = (0.0, 0.0)                                   # punho do tracking desligado (sinais sem calibrar)
                vals = [*cs, th, *sp, wf, wd]
                fl = hfilt.setdefault(lado, [artic_h.OneEuro(1.2, 0.06) for _ in vals])
                md = hmed.setdefault(lado, [artic_h.Median(3) for _ in vals])
                fv = [f(m_(v), tnow) for f, m_, v in zip(fl, md, vals)]
                last = hsent.get(lado)
                if last is None or tnow - last[0] > 0.5 or max(abs(a - b) for a, b in zip(fv, last[1])) > 0.03:
                    if last is None or tnow - last[0] > 0.06:           # ≤ ~16 Hz
                        hsent[lado] = (tnow, fv)
                        hdiag["sent3d"] += 1
                        hdiag["last"].setdefault(lado, {})["c"] = [round(x, 2) for x in fv[0:4]]
                        asyncio.run_coroutine_threadsafe(broadcast({"type": "hand3d", "lado": lado, "c": [round(x, 2) for x in fv[0:4]],
                                                                    "th": round(fv[4], 2), "sp": [round(x, 2) for x in fv[5:9]],
                                                                    "w": [round(fv[9], 2), round(fv[10], 2)]}), loop)
            except Exception as e:
                print("dedos3d:", e, flush=True)
        janela_ativa = modes.get("janela", True) and not modes.get("mouse", False)
        if janela_ativa and fr_mod is not None and gest_eng is not None:
            try:
                bo = max(gest_obs, key=lambda o: o[0]) if gest_obs else None
                evs = gest_eng.update(now, bo[1] if bo else 0, bo[2] if bo else 0, bo[3] if bo else None, bo is not None)
                for kind, data in evs:
                    asyncio.run_coroutine_threadsafe(friday_gesture(kind, data), loop)
            except Exception as e:
                print("gestos F.R.I.D.A.Y.:", e, flush=True)
        if friday_state["on"] and now - cam_prev["t"] > 0.08:
            cam_prev["t"] = now
            try:
                import cv2 as _c
                im = _holo_cam(fr, hands, scene.get("faces") if now - scene["t"] < 2 else [])
                _c.imwrite("/tmp/friday-cam.tmp.jpg", im, [_c.IMWRITE_JPEG_QUALITY, 70])
                os.replace("/tmp/friday-cam.tmp.jpg", "/tmp/friday-cam.jpg")
            except Exception:
                pass
        if scene.get("wrists_new"):
            scene["wrists"] = dict(scene["wrists_new"]); scene["t_wr"] = now
            scene["wrists_new"] = {}
        vis = {}
        for lado in ("R", "L"):
            pose = got.get(lado)
            c = st[lado]
            if pose and pose == c[0]:
                c[1] += 1
            else:
                c[0], c[1] = pose, 1 if pose else 0
            if pose:
                vis["direita" if lado == "R" else "esquerda"] = pose
            if c[0] and c[1] >= 3 and (c[0] != c[2] or now - c[3] > 1.5):
                novo = c[0] != c[2]
                c[2], c[3] = c[0], now
                asyncio.run_coroutine_threadsafe(broadcast({"type": "mao", "lado": lado, "pose": c[0]}), loop)
                if novo and c[0] in REACT and now - GEST_COOLDOWN.get(c[0], 0) > 8:
                    GEST_COOLDOWN[c[0]] = now
                    scene["gesto"] = (c[0], now)
                    asyncio.run_coroutine_threadsafe(reagir(c[0]), loop)
        scene["dedos"] = vis; scene["t_ded"] = now
        if now - hdiag["t"] > 1.0:
            try:
                with open("/tmp/prometheus-hands.json", "w") as _f:
                    json.dump({**hdiag, "t": now, "cam_fresh": True}, _f)
            except Exception:
                pass
            hdiag.update(t=now, frames=0, with_hand=0, sent3d=0)
        for ld in list(hfilt):
            if ld not in got and now - (hsent.get(ld, (0,))[0]) > 0.8:
                hfilt.pop(ld, None); hsent.pop(ld, None); hmed.pop(ld, None)
        time.sleep((0.012 if (friday_state["on"] or modes["mouse"]) else 0.04) if (time.time() - scene["t"] < 8 or modes["mouse"]) else 0.3)       # mãos: o mais rápido possível com gente à vista


VISAO_FILE = os.path.join(MEM_DIR, "visao.jsonl")


def recent_vision(n=6) -> str:
    try:
        lines = open(VISAO_FILE).read().splitlines()[-n:]
    except Exception:
        return ""
    out = []
    for l in lines:
        try:
            d = json.loads(l)
            ago = int((time.time() - d["t"]) / 60)
            out.append(f"- há {ago} min: " + d["resumo"])
        except Exception:
            pass
    return "\n".join(out)


def vision_memory_thread():
    """Registra o que vê (pessoas, objetos, gestos, cena) como memória visual, só quando algo muda."""
    last = None; last_t = 0.0
    while True:
        time.sleep(3.0)
        if not camera_on:
            continue
        now = time.time()
        if now - scene["t"] > 6:
            continue
        pess = sorted((f["nome"] or "desconhecido") for f in scene["faces"])
        objs = sorted(scene["objetos"].keys()) if now - scene["t_obj"] < 8 else []
        maos = sorted(set(scene["maos_vlm"].values())) if now - scene["t_mvlm"] < 10 else []
        sig = (tuple(pess), tuple(objs), tuple(maos))
        if sig == last and now - last_t < 300:
            continue
        partes = []
        partes.append("pessoas: " + (", ".join(pess) if pess else "ninguém"))
        if scene.get("gesto") and now - scene["gesto"][1] < 10: partes.append("gesto: " + scene["gesto"][0])
        try:
            with open(VISAO_FILE, "a") as f:
                f.write(json.dumps({"t": int(now), "resumo": "; ".join(partes), "pessoas": pess, "objetos": objs}, ensure_ascii=False) + "\n")
            if os.path.getsize(VISAO_FILE) > 1_500_000:                 # mantém só o fim
                tail = open(VISAO_FILE).read().splitlines()[-2000:]
                open(VISAO_FILE, "w").write("\n".join(tail) + "\n")
        except Exception as e:
            print("memória visual:", e, flush=True)
        last, last_t = sig, now


def autonomy_thread(loop):
    """Iniciativa própria: saúde do sistema, lembretes de agenda, auto-recuperação da PTZ, chegadas e objetos."""
    ausente_desde = time.time(); presentes = set(); desconhecido_desde = None; ultimo_proativo = 0.0
    visto_obj = {}; obj_ok = set(); ult_check = time.time(); conhecidos_vistos = {}
    ult_saude_check = 0.0; ult_agenda_check = 0.0; ult_ptz_check = 0.0
    ult_tela_dif_check = 0.0; ult_emocao_check = 0.0
    while True:
        time.sleep(1.0)
        if not mem.get("autonomia", True):
            continue
        now = time.time()
        evento = None
        nomes = set()

        # 1. Proatividade Visual (somente quando a câmera estiver ligada)
        if camera_on:
            fresh = now - scene["t"] < 4
            nomes = {f["nome"] for f in scene["faces"] if f["nome"]} if fresh else set()
            unk = sum(1 for f in scene["faces"] if not f["nome"]) if fresh else 0
            for n in nomes:
                conhecidos_vistos[n] = now
            presentes = nomes
            if unk and not nomes:
                desconhecido_desde = desconhecido_desde or now
                if now - desconhecido_desde > 4 and now - mem.get("t_unk", 0) > 600:
                    mem["t_unk"] = now
                    try:
                        with open("/tmp/friday-desconhecidos.log", "a") as f_:
                            f_.write(time.strftime("%d/%m %H:%M:%S") + f" pessoa desconhecida na câmera ({unk})\n")
                    except OSError:
                        pass
            else:
                desconhecido_desde = None
            if now - scene["t_obj"] < 5:
                for o in scene["objetos"]:
                    visto_obj[o] = visto_obj.get(o, 0) + 1
                for o in list(visto_obj):
                    if o not in scene["objetos"]:
                        visto_obj[o] = 0
                novos = [o for o, c in visto_obj.items() if c >= 5 and o not in obj_ok]
                obj_ok.update(novos)
                obj_ok.intersection_update({o for o, c in visto_obj.items() if c > 0})

        # 2. Saúde Proativa do Sistema (executa independente de câmera)
        if now - ult_saude_check > 120:
            ult_saude_check = now
            try:
                import psutil
                disco = psutil.disk_usage("/").percent
                ram = psutil.virtual_memory().percent
                if disco >= 93 and now - mem.get("t_alerta_disco", 0) > 3600:
                    mem["t_alerta_disco"] = now
                    evento = f"Alerta de sistema: o disco principal está em {disco:.0f}% de uso."
                elif ram >= 94 and now - mem.get("t_alerta_ram", 0) > 1800:
                    mem["t_alerta_ram"] = now
                    evento = f"Alerta de sistema: o uso de memória RAM está muito alto, em {ram:.0f}%."
                bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
                if bat and not bat.power_plugged and bat.percent <= 15 and now - mem.get("t_alerta_bat", 0) > 600:
                    mem["t_alerta_bat"] = now
                    evento = f"Atenção: a bateria está em {bat.percent:.0f}% e descarregando. Conecte o carregador."
            except Exception:
                pass

        # 3. Lembretes Proativos da Agenda (15 min antes de compromissos)
        if not evento and ops is not None and now - ult_agenda_check > 60:
            ult_agenda_check = now
            try:
                for it in ops.agenda_due_reminders():
                    faltam = int((it["inicio"] - now) / 60)
                    if faltam <= 15:
                        msg = f"Lembrete de agenda: {it['titulo']} em {max(1, faltam)} minutos" + (f" em {it['local']}" if it.get("local") else "") + "."
                        ops.agenda_mark(it["id"], avisado=True)
                        evento = msg
                        break
            except Exception:
                pass

        # 4. Auto-recuperação da Câmera PTZ se estiver offline
        if ipcam is not None and camera_on and now - ult_ptz_check > 25:
            ult_ptz_check = now
            try:
                c_ip = ipcam.atual()
                if c_ip is None or not c_ip.ok:
                    ipcam.obter(forcar=False)
            except Exception:
                pass

        # 5. Silêncio longo quando o usuário está presente
        if camera_on and nomes and now - mem.get("ultima_vez", 0) > 1500 and now - ult_check > 1500 and not evento:
            ult_check = now
            evento = "O usuário está aqui há um bom tempo sem falar com você."

        # 6. Dificuldades e falhas de compilação/código na tela
        if not evento and now - ult_tela_dif_check > 20:
            ult_tela_dif_check = now
            try:
                import tela
                dif = tela.detectar_dificuldades()
                if dif.get("tem_dificuldade") and dif.get("severidade") == "alta":
                    resumo_dif = dif.get("resumo", "")
                    if resumo_dif != mem.get("ult_dificuldade_tela") and now - mem.get("t_dificuldade_tela", 0) > 300 \
                            and now - oferta["t"] > 75 and not speaking and not busy.locked() and now - last_voice["t"] > 8:
                        mem["ult_dificuldade_tela"] = resumo_dif
                        mem["t_dificuldade_tela"] = now
                        # 19/10: oferece e ESPERA o "sim" (antes virava evento p/ o cérebro, que agia/inventava sozinho)
                        det_ = str(dif.get("detalhes") or "")[:400]
                        app_ = str(dif.get("app") or "na tela")
                        tarefa_ = (f"no modo dev, corrija este erro que apareceu {app_}: {det_}" if re.search(r"c[óo]digo|compila|exce|traceback|syntax|erro de", str(dif.get("tipo")), re.I)
                                   else f"me ajude com esta dificuldade na tela ({dif.get('tipo')}): {det_}. Sugestão: {dif.get('sugestao')}")
                        oferta.update(tarefa=tarefa_, t=now)
                        fala_ = f"Vi um problema {app_}: {dif.get('tipo')}. Quer que eu resolva?"
                        asyncio.run_coroutine_threadsafe(broadcast({"type": "text", "role": "assistant", "text": fala_ + "\n" + det_[:200]}), loop)
                        asyncio.run_coroutine_threadsafe(speak(fala_), loop)
            except Exception:
                pass

        # 7. Emoção de Frustração ou Tensão Prolongada
        if not evento and camera_on and scene.get("faces") and now - ult_emocao_check > 30:
            ult_emocao_check = now
            try:
                f0 = scene["faces"][0]
                if f0.get("emocao") == "frustrado" and f0.get("conf_emocao", 0) >= 0.75:
                    if now - mem.get("t_frustracao_alerta", 0) > 900:
                        mem["t_frustracao_alerta"] = now
                        evento = "O usuário parece com expressão de frustração ou tensão diante do computador."
            except Exception:
                pass

        if evento and now - ultimo_proativo > 45 and not speaking and not busy.locked() and state["state"] == "idle" \
                and now - last_voice["t"] > 8:
            ultimo_proativo = now
            asyncio.run_coroutine_threadsafe(ask(evento, [], proactive=True), loop)



# ======================= MENTE: escuta/atenção/pensamento contínuos =======================
WAKE_RE = re.compile(r"\b(prometheus|prometeus|prometeu|prometes|pro\s?meteus|" + (fr.NOME if fr is not None else r"sexta[\s\-]*feira|friday") + r")\b", re.I)
DIRECT_RE = re.compile(r"^\s*(abr[ae]|fech[ae]|pesquis|mostr|toc[ae]|lig[ae]|deslig|vir[ae]|olh[ae]|gir[ae]|par[ae]|desativ|ativ|me\s+(diga|fal|mostr|ajud|expliq|lembr|localiz|ach|segu)|qual|quais|quem|"
                       r"quando|onde|como|por ?qu[eê]|o que|que horas|voc[êe]|pode|consegue|d[êe]|cri[ae]|escrev|faz|fa[çc]a|antigravity)\b", re.I)
CONV_WINDOW = 45.0                                  # s: depois de uma troca, a fala seguinte ainda é comigo
conv = {"t": 0.0}
overheard = []                                      # (t, texto, nome): falas ouvidas não dirigidas a mim
mind_state = {"busy": False, "last_triage": 0.0, "last_proactive": 0.0, "last_reflect": time.time(), "present": False,
              "present_since": time.time(), "absent_since": 0.0}


async def llm_json(prompt: str, timeout: float = 40.0):
    """chamada LOCAL (Ollama/gemma3) que devolve um dict JSON ou None. Nada vai para a nuvem."""
    if fr is None:
        return None
    return await asyncio.to_thread(fr.llm, "Responda SOMENTE com um JSON válido, sem texto extra.", prompt, None, True, 500, 0.1, timeout)


def _nome_usuario():
    kn = [f["nome"] for f in scene["faces"] if f.get("nome")] if time.time() - scene["t"] < 6 else []
    return kn[0] if kn else mem.get("nome")


# ======================= MODOS (segurança, privacidade, silêncio, reunião) + comandos de sistema por voz =======================
modes = {"seguranca": False, "privacidade": False, "silencio": False, "mouse": False, "criacao": False, "janela": False, "sentinela": False}      # gestos de janela/workspace só quando o dono ativar
owner_voice = {"t": 0.0}
_faixa_ult = {"f": "plena", "t": 0.0}                # faixa do portão v2 da última fala que foi p/ route_speech
_voz_ult = {"faixa": None, "score": 0.0, "titanet": False, "t": 0.0}   # última decisão do _foco_voz (aprovação por voz exige "plena" do TitaNet)
import contextvars as _cv_mod
_origem_fala = _cv_mod.ContextVar("origem_fala", default="voz")   # "app": fala veio do microfone do app remoto (token), não do mic local
_sec = {"task": None, "last_alert": 0.0}
_MODE_ON = re.compile(r"\b(ativ\w+|lig\w+|inici\w+|habilit\w+|entr\w+|coloc\w+|ligar)\b", re.I)
_MODE_OFF = re.compile(r"\b(desativ\w+|deslig\w+|cancel\w+|sai\w*|saia|encerr\w+|desabilit\w+|tira\w*|remov\w+|fim)\b", re.I)
COMANDOS_AJUDA = ("Posso: abrir apps, pesquisar e tocar música no YouTube, pular anúncios, criar documentos e planilhas, ler e responder o WhatsApp, "
                  "tirar print da tela, bloquear ou suspender o PC, relatar o estado do PC, e ter modo segurança, privacidade, silêncio e reunião. "
                  "Diga pare a qualquer momento para eu interromper.")


def _owner_name():
    return str(mem.get("nome") or "Iann").strip()


def _is_owner_voice():
    """voz do dono? (identificação por embedding; falas curtas sem id herdam a identificação recente do dono)"""
    now = time.time()
    if now - last_voice["t"] < 4:
        n = (last_voice.get("nome") or "").lower()
        return bool(n) and n == _owner_name().lower() and float(last_voice.get("sim") or 0) >= 0.33
    return now - owner_voice["t"] < 20


_REPOUSO = {"inib": None}


def _repouso(on):
    """modo repouso: bloqueia e apaga os monitores, mas SEGURA a suspensão (systemd-inhibit) -> a Sexta-feira segue ouvindo/vigiando.
    Qualquer mouse/teclado religa os monitores (niri); o inibidor só sai com "acordar"/"sair do repouso"."""
    p = _REPOUSO["inib"]
    for m_ in ("friday", "agent"):                  # trava as ações de tela (mouse/teclado iriam para a senha da tela de bloqueio)
        if m_ in sys.modules and hasattr(sys.modules[m_], "REPOUSO"):
            sys.modules[m_].REPOUSO[0] = bool(on)
    if on:
        if p is None or p.poll() is not None:
            _REPOUSO["inib"] = subprocess.Popen(["systemd-inhibit", "--what=sleep:idle", "--who=Sexta-feira", "--why=modo repouso",
                                                 "--mode=block", "sleep", "infinity"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _noctalia("session", "lock")
        time.sleep(1.0)
        subprocess.run(["niri", "msg", "action", "power-off-monitors"], capture_output=True, timeout=5)
    else:
        if p is not None and p.poll() is None:
            p.terminate()
        _REPOUSO["inib"] = None
        subprocess.run(["niri", "msg", "action", "power-on-monitors"], capture_output=True, timeout=5)
        if _VIGILIA.get("kbd"):                                # vigília apagou a luz do teclado: devolve
            subprocess.run(["brightnessctl", "-d", _KBD, "s", _VIGILIA["kbd"]], capture_output=True, timeout=3)
            _VIGILIA["kbd"] = None


_VIGILIA = {"on": False, "kbd": None}
_FECHAR_VIGILIA = re.compile(r"chrom|firefox|brave|onlyoffice|libreoffice|mpv|vlc|totem|celluloid|spotify|discord|vesktop", re.I)
_KBD = "platform::kbd_backlight"


def _vigilia(on):
    """modo vigília (pedido do dono): tela, luz do teclado e atividades (navegadores, mídia, office) DESLIGADAS;
    só a Sexta-feira fica ativa, com câmeras e áudio (repouso: bloqueia, apaga monitores e segura a suspensão).
    Terminais, IDEs e o ZapZap NÃO são fechados (trabalho em andamento / comandos pelo WhatsApp)."""
    if on:
        subprocess.run(["playerctl", "-a", "pause"], capture_output=True, timeout=4)
        fechadas = []
        try:
            for w in json.loads(subprocess.run(["niri", "msg", "-j", "windows"], capture_output=True, text=True, timeout=4).stdout or "[]"):
                app = str(w.get("app_id") or "")
                if _FECHAR_VIGILIA.search(app) and "holo" not in app and "8765" not in app:
                    subprocess.run(["niri", "msg", "action", "close-window", "--id", str(w["id"])], capture_output=True, timeout=4)
                    fechadas.append(app)
        except Exception as e:
            print("vigília (janelas):", e, flush=True)
        try:
            atual = subprocess.run(["brightnessctl", "-d", _KBD, "g"], capture_output=True, text=True, timeout=3).stdout.strip()
            if atual.isdigit() and int(atual) > 0:
                _VIGILIA["kbd"] = atual
            subprocess.run(["brightnessctl", "-d", _KBD, "s", "0"], capture_output=True, timeout=3)
        except Exception:
            pass
        _VIGILIA["on"] = True
        print(f"vigília: ligada; fechei {len(fechadas)} janela(s): {', '.join(fechadas)[:200]}", flush=True)
        _repouso(True)
    else:
        _VIGILIA["on"] = False
        _repouso(False)


def _desligar_tudo():
    """para tudo (agente, PTZ, mídia) e desliga o computador. Só chega aqui depois da confirmação falada."""
    for f_ in (lambda: sys.modules["agent"].CANCEL.set() if "agent" in sys.modules else None,
               lambda: ptz.comando({"op": "parar"}) if ptz is not None else None,
               lambda: subprocess.run(["playerctl", "-a", "pause"], capture_output=True, timeout=4),
               lambda: _mundo().salvar()):
        try:
            f_()
        except Exception:
            pass
    print("desligando o PC (pedido confirmado do dono)", flush=True)
    subprocess.run(["systemctl", "poweroff"], capture_output=True, timeout=15)


_DESLIGA = {"t": 0.0}


def _noctalia(*a):
    try:
        return subprocess.run(["noctalia", "msg", *a], capture_output=True, text=True, timeout=8).returncode == 0
    except Exception:
        return False


def pc_status():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.4); ram = psutil.virtual_memory().percent
        disco = psutil.disk_usage("/").percent
        temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
        t = next((v[0].current for k, v in temps.items() if v), None)
        bat = psutil.sensors_battery()
        s = f"CPU em {cpu:.0f} por cento, memória {ram:.0f}, disco {disco:.0f}"
        if t: s += f", temperatura {t:.0f} graus"
        if bat: s += f", bateria {bat.percent:.0f} por cento" + (" carregando" if bat.power_plugged else "")
        return s + "."
    except Exception as e:
        return "Não consegui ler o estado do PC agora."


async def _security_loop():
    """modo segurança: câmera ligada; rosto que não é o seu (ou 2+ rostos) por alguns segundos = bloqueia e suspende (pede a senha ao voltar)."""
    global camera_on
    if not camera_on:
        camera_on = True
        await broadcast({"type": "camera", "on": True})
    t_ini = time.time(); cnt = 0
    while modes["seguranca"]:
        await asyncio.sleep(1.0)
        now = time.time()
        if now - t_ini < 8 or now - _sec["last_alert"] < 90:
            continue
        faces = scene["faces"] if now - scene["t"] < 3 else []
        dono = _owner_name().lower()
        outros = [f for f in faces if (f.get("nome") or "").lower() != dono]
        conhecido_outro = any(f.get("nome") and f["nome"].lower() != dono for f in faces)
        estranho = len(faces) >= 2 or conhecido_outro or (len(outros) == 1 and now - owner_voice["t"] > 60)
        cnt = cnt + 1 if (outros and estranho) else 0
        if cnt >= (3 if (len(faces) >= 2 or conhecido_outro) else 6):
            _sec["last_alert"] = now; cnt = 0
            hora = time.strftime("%H:%M")
            try:
                ops.audit("seguranca.intruso", "", f"rosto estranho às {hora}", "bloqueio+suspensão")
            except Exception:
                pass
            await broadcast({"type": "text", "role": "assistant", "text": f"[SEGURANÇA] Modo segurança: outra pessoa detectada às {hora}. Bloqueando o PC."})
            try:
                cfg = zap_cfg()
                contato = cfg.get("contato_seguranca") or cfg.get("contato_comando") or "Integra Code"
                await asyncio.to_thread(zapmod.send, contato,
                                        f"[SEGURANÇA] Modo segurança: rosto não reconhecido às {hora}. PC bloqueado e suspenso (pede a senha ao voltar).")
            except Exception:
                pass
            if not await asyncio.to_thread(_noctalia, "session", "lock-and-suspend"):
                await asyncio.to_thread(_noctalia, "session", "lock")


SESSAO = "/tmp/friday-sessao.json"          # Friday ligada + modos: um reinício do daemon (atualização, queda) não desliga tudo


def _salva_sessao():
    try:
        json.dump({"t": time.time(), "on": friday_state["on"], "mouse": modes.get("mouse", False)}, open(SESSAO, "w"))
    except Exception:
        pass


async def _restaura_sessao():
    """volta como estava se o daemon reiniciou há menos de 10 min (segurança/privacidade/criação continuam começando desligados)."""
    try:
        d = json.load(open(SESSAO))
    except Exception:
        return
    if time.time() - float(d.get("t", 0)) > 600 or not d.get("on"):
        return
    await asyncio.sleep(4)
    friday_state["on"] = True; friday_state["last_cmd"] = time.time()
    global camera_on
    camera_on = True
    await broadcast({"type": "friday", "on": True}); await broadcast({"type": "camera", "on": True})
    if d.get("mouse"):
        await set_mode("mouse", True)
    _salva_sessao()                              # renova o horário: reinícios seguidos continuam restaurando
    print("sessão restaurada (Friday ligada" + (", mouse por gestos" if d.get("mouse") else "") + ")", flush=True)


async def set_mode(nome, on):
    global camera_on
    modes[nome] = on
    if nome in ("mouse", "janela") and on and not camera_on:
        camera_on = True
        mem["camera"] = True
        save_mem()
        await broadcast({"type": "camera", "on": True})
    if nome == "sentinela" and ptz is not None and (ptz.get_ptz().modo in ("vigiar", "auto")) != on:
        ptz.get_ptz().definir_modo("vigiar" if on else "livre")
        if on:
            if not camera_on:
                camera_on = True
                mem["camera"] = True
                save_mem()
                await broadcast({"type": "camera", "on": True})
    await broadcast({"type": "modes", **modes})
    _salva_sessao()
    if nome == "seguranca" and on and (_sec["task"] is None or _sec["task"].done()):
        _sec["task"] = asyncio.create_task(_security_loop())


_criacao_ligou_mouse = [False]


async def criacao_set(on):
    """modo criação: sobe o construtor No-Code, abre a janela e liga o mouse por gestos."""
    import construtor as _ct
    if on:
        _criacao_ligou_mouse[0] = not modes["mouse"]
        _lp = asyncio.get_running_loop()
        def _avisa(msg):
            asyncio.run_coroutine_threadsafe(broadcast({"type": "text", "role": "assistant", "text": "construtor: " + msg}), _lp)
            asyncio.run_coroutine_threadsafe(speak(msg), _lp)
        await asyncio.to_thread(_ct.iniciar, _avisa)
        await asyncio.to_thread(_ct.abrir_janela)
        if not modes["mouse"]:
            await set_mode("mouse", True)
    else:
        await asyncio.to_thread(_ct.fechar_janela)          # antes a janela do construtor ficava aberta após desativar
        if modes["mouse"] and _criacao_ligou_mouse[0]:      # só desliga o mouse se foi a criação que o ligou
            await set_mode("mouse", False)


async def set_mode_voz(nome, on):
    """liga/desliga um modo e anuncia (usado por gestos)."""
    await set_mode(nome, on)
    if nome == "criacao":
        await criacao_set(on)
    await speak(f"Modo criação {'ativado' if on else 'desativado'}.")


def _sistemas_nomes():
    """nomes reais das pastas de ~/Workspace/Projetos/Sistemas (ex.: 'Integra Site') para reconhecer pedido de código por voz."""
    try:
        return [d for d in os.listdir(os.path.expanduser("~/Workspace/Projetos/Sistemas")) if len(d) >= 4 and not d.startswith(".")] or ["integra"]
    except Exception:
        return ["integra"]


async def handle_modes(txt):
    """comandos por voz de modos e de sistema. True = tratou."""
    t = (txt or "").lower()
    named = bool(fr is not None and fr.NAME_RE.match(txt or ""))
    if not (friday_state["on"] or named):
        return False
    async def dizer(msg):
        await broadcast({"type": "text", "role": "assistant", "text": msg}); log_turn("prometheus", msg)
        await speak(msg)
    # --- pedido ao Claude: vai DIRETO para a sessão do Claude CLI no terminal (o cérebro local inventava "arquivo salvo") ---
    # 19/10: "continua"/"prossiga" com o Claude do MODO DEV usado há <30 min vai PARA ELE como texto (virava pedido novo: abriu site)
    if len(t.split()) <= 8 and re.search(r"\b(?:continu\w*|prossig\w*|segue|siga|pode seguir|termin[ae]\w*|clic\w*|aperte?\w*|escolh\w*|selecion\w*|op[çc][ãa]o|yes|sim|confirm\w*|aceit\w*|n[ãa]o mostr\w*|not now)\b", t):
        try:
            import dev_cli
            if dev_cli.vivo() and time.time() - dev_cli.ultimo_uso() < 1800:
                r_ = await asyncio.to_thread(dev_cli.responder, txt)
                await dizer(r_[0].upper() + r_[1:] + ".")
                return True
        except Exception as e_:
            print("dev continuar:", e_, flush=True)
    # 19/10: "fala para ela subir no hostinger..." com o MODO DEV em uso: 'ela/ele' é o Claude (ia ao cérebro, que criou aprovação sem sentido)
    if re.search(r"\b(?:fal[ae]|diga|pe[çc]a|pede|mand[ae]|avis[ae])\s+(?:para|pra|pro|a|ao)\s+(?:ela|ele)\b", t):
        try:
            import dev_cli
            try:
                ult_t = json.load(open(os.path.join(MEM_DIR, "dev_ultima.json"))).get("t", 0)
            except Exception:
                ult_t = 0
            if (dev_cli.vivo() and time.time() - dev_cli.ultimo_uso() < 3600) or time.time() - ult_t < 7200:   # janela fechada mas tarefa recente: reabre
                await dizer("Passei para o Claude.")
                asyncio.create_task(run_programming(txt))
                return True
        except Exception as e_:
            print("dev ela:", e_, flush=True)
    # 19/10: "ative o modo dev e nele crie ..." e "no diretório integra site coordene modificação ..." caíam no cérebro local (só consultava memória)
    _dev_tarefa = len(t.split()) >= 8 and (
        re.search(r"\bmodo\s+dev\b.{0,25}\b(?:e\s+(?:nele|l[áa]|ent[ãa]o|depois)?|para|pra)\s+\w+", t)
        or (re.search(r"\b(?:diret[óo]rio|pasta|projeto|reposit[óo]rio|c[óo]digo|sistema|site|painel|admin|api|backend|frontend|banco de dados)\b", t)
            and re.search(r"\b(?:cri[ae]r?|implement\w*|codific\w*|program\w*|desenvolv\w*|modific\w*|corrij\w*|corrig\w*|refator\w*|coorden\w*|adicion\w*|mont[ae]r?|constru\w*|alter\w*|ajust\w*)\b", t)
            and re.search(r"\b(?:diret[óo]rio|pasta|projeto)\b|" + "|".join(re.escape(n_.lower()) for n_ in _sistemas_nomes()), t)))
    if _dev_tarefa or re.search(r"\b(?:pede|pe[çc]a|manda|fala|diz|avisa)\s+(?:pro|pra|para\s+o|ao|o)\s+claude\b|\bclaude\s*,|\bno\s+modo\s+dev\s*,?\s+\w", t):
        await dizer("Mandei para o Claude no terminal do modo dev.")
        asyncio.create_task(run_programming(txt))
        return True
    # --- status do orquestrador/fila: direto na ferramenta (o cérebro local respondia "consultei" sem consultar, 18/10) ---
    if re.search(r"\b(?:status|estado|situa[çc][ãa]o|como\s+(?:est[áa]|t[áa])|o\s+que\s+(?:tem|h[áa]|est[áa]|t[áa]))\b.{0,30}\b(?:orquestrador|fila\s+de\s+tarefas|fila\s+do\s+orquestrador)\b", t):
        import agent as _ag
        st_ = await asyncio.to_thread(_ag.t_orquestra_status)
        await broadcast({"type": "text", "role": "assistant", "text": st_}); log_turn("prometheus", st_)
        await speak(". ".join(l.lstrip("- ") for l in st_.splitlines()[:4])[:300])
        return True
    # --- cadastro do rosto do dono PELA câmera do quarto (PTZ): 15 s olhando para ela ---
    if re.search(r"\b(aprend\w*|decor\w*|cadastr\w*|grav\w*)\b.{0,25}\b(meu|o meu)\s+rosto\b.{0,40}\b(c[âa]mera|ptz|quarto)\b", t):
        _ptz_rosto["pedido_ate"] = time.time() + 15
        await dizer("Olhe para a câmera do quarto por quinze segundos; vou aprender seu rosto por ela.")
        return True
    # --- MODO DEV: IDE autônoma de desenvolvimento (DevIDE.qml) ---
    if re.search(r"\bmodo\s+dev\b|\bpainel\s+(?:dev|de\s+desenvolvedor)\b|\b(?:abrir|fecha|mostra|inicia)\s+(?:o\s+)?(?:modo\s+)?ide\b", t):
        liga = not re.search(r"\b(desativ\w*|deslig\w*|fech\w*|sai\w*|tira\w*|esconde\w*)\b", t)
        if dev is not None:
            dev.estado["on"] = liga
            dev.emitir("sistema", "modo", "MODO DEV " + ("ligado" if liga else "desligado"))
        await broadcast({"type": "dev_modo", "on": liga})
        if liga:
            if dev is not None:
                await broadcast({"type": "dev_hist", "itens": dev.historico(200)})
            if ide_inst is not None:
                try:
                    await ide_inst.tratar({"type": "ide", "op": "estado"}, broadcast)
                    await ide_inst.tratar({"type": "ide", "op": "arvore", "rel": ""}, broadcast)
                except Exception as _e_ide:
                    print("ide_inst broadcast estado:", _e_ide, flush=True)
            await dizer("Modo Dev IDE ativado. Painel de programação aberto na tela.")
        else:
            await dizer("Modo Dev desligado.")
        return True
    # --- desligar o PC: SEMPRE com confirmação falada (o STT pode errar e desligar é caro) ---
    if _DESLIGA["t"] and time.time() - _DESLIGA["t"] < 20:
        if re.search(r"\b(confirm\w*|pode\s+desligar|sim|isso|desliga\s+sim)\b", t) and not re.search(r"\bn[ãa]o\b", t):
            _DESLIGA["t"] = 0.0
            await dizer("Parando tudo e desligando o computador. Até logo.")
            await asyncio.sleep(2.5)
            await asyncio.to_thread(_desligar_tudo)
            return True
        _DESLIGA["t"] = 0.0
        if re.search(r"\b(n[ãa]o|cancel\w*|deixa|esquece)\b", t):
            await dizer("Cancelado. O computador continua ligado.")
            return True
    # --- modo vigília: tela, teclado e atividades desligados; só ela ativa (câmeras + áudio) ---
    if re.search(r"\bmodo\s+(?:de\s+)?(?:vig[íi]lia|noturno|noite)\b|\b(?:deslig|apag)\w*\s+tudo\s+(?:menos|exceto|fora)\s+(?:voc[êe]|a\s+sexta)"
                 r"|\bfica\s+s[óo]\s+voc[êe]\b|\bs[óo]\s+voc[êe]\s+ligada\b", t):
        if _MODE_OFF.search(t) and re.search(r"modo\s+(?:de\s+)?(?:vig[íi]lia|noturno|noite)", t):
            await asyncio.to_thread(_vigilia, False)
            await dizer("Modo vigília desligado. Tela de volta.")
            return True
        await dizer("Modo vigília: vou apagar a tela e o teclado e fechar o navegador. Eu continuo ativa, com câmeras e áudio. Diga acordar para voltar.")
        await asyncio.sleep(1.5)
        await asyncio.to_thread(_vigilia, True)
        return True
    if (re.search(r"\b(deslig\w*|deslig[ae]|apag\w*)\b.{0,25}\b(pc|computador|m[áa]quina|notebook)\b", t)
            or re.search(r"\bdeslig\w*\s+tudo\b|\bpar[ae]\s+tudo\s+e\s+deslig", t)) and not re.search(r"\btela\b", t):
        _DESLIGA["t"] = time.time()
        await dizer("Vou parar tudo e desligar o computador. Confirma? Diga: confirmo.")
        return True
    for chave, rx, rotulo in (("seguranca", r"modo\s+(?:de\s+)?seguran[çc]a", "Modo segurança"),
                              ("privacidade", r"modo\s+(?:de\s+)?privacidade", "Modo privacidade"),
                              ("silencio", r"modo\s+(?:de\s+)?sil[êe]ncio", "Modo silêncio"),
                              ("mouse", r"modo\s+(?:de\s+)?(?:mouse|gestos?|m[ãa]o\s+livre|m[ãa]os?\s+livres?)|(?:mouse|controle)\s+(?:por|com|de)\s+gestos?|m[ãa]o\s+livre|m[ãa]os?\s+livres?", "Modo mão livre"),
                              ("criacao", r"modo\s+(?:de\s+)?cria[çc][ãa]o|modo\s+construtor", "Modo criação"),
                              ("janela", r"modo\s+(?:de\s+)?(?:janela|gerenciador\s+de\s+janelas?|window\s+manager)|(?:window\s+manager|gerenciador\s+de\s+janelas?)\s+(?:por|com|de|via)\s+gestos?|gestos?\s+de\s+janela", "Modo gerenciador de janelas por gestos"),
                              ("sentinela", r"modo\s+(?:de\s+)?sentinela|modo\s+(?:de\s+)?vigil[âa]ncia|monitor(?:amento|ar)\s+(?:do\s+)?quarto|vigiar\s+(?:o\s+)?quarto", "Modo sentinela")):
        if re.search(rx, t):
            off = bool(_MODE_OFF.search(t)) and not re.search(r"\bn[ãa]o\s+deslig", t)
            on = not off
            await set_mode(chave, on)
            extra = {"seguranca": " Vigiando rostos diferentes do seu." if on else "",
                     "privacidade": " Só obedeço a sua voz." if on else "",
                     "silencio": "",
                     "mouse": " Palma aberta move o cursor suavemente; mão fechada rápida clica; segurar punho fechado arrasta; duas pinças controlam zoom; pinça única é clique direito." if on else "",
                     "criacao": " Construtor No-Code ativado. Peça elementos e telas para desenvolvimento rápido." if on else "",
                     "janela": " Arraste com a mão aberta para trocar de janela ou workspace; punho fechado move janelas; punho para cima maximiza; sinal de paz alterna visão geral." if on else "",
                     "sentinela": " Monitorando o quarto em 180 graus. Avisarei imediatamente se detectar movimento ou pessoas." if on else ""}[chave]
            if chave == "criacao":
                await criacao_set(on)
            if chave == "silencio" and on:
                await broadcast({"type": "text", "role": "assistant", "text": "Modo silêncio ligado: respondo só por texto."})
                return True
            await dizer(f"{rotulo} {'ativado' if on else 'desativado'}.{extra}")
            return True
    # Comandos de alternância entre Janela Real e Modo Holográfico
    if re.search(r"\b(mud(ar?|e)|troc(ar?|e)|volt(ar?|e)|us(ar?|e)|exib(ir?|a)|mostr(ar?|e)|deix(ar?|e))\b.*\b(janela|tela|app)\b.*\b(real|normal|nativa)\b|\b(janela|tela|app)\s+(real|normal|nativa)\b|\b(desativ(ar?|e)|deslig(ar?|ue)|tir(ar?|e)|remov(er?|a))\b.*\b(holograma|modo\s+hologr[áa]fico|camada\s+hologr[áa]fica)\b", t):
        if fr is not None:
            fr.set_holo_mode(False)
            fr.holo_live_stop()
        await broadcast({"type": "holo_window", "enabled": False})
        await dizer("Desativando camada holográfica. Exibindo janela real, senhor.")
        return True

    if re.search(r"\b(ativ(ar?|e)|lig(ar?|ue)|volt(ar?|e)|coloc(ar?|e)|reconfigur(ar?|e)|mud(ar?|e))\b.*\b(modo\s+hologr[áa]fico|janela\s+hologr[áa]fica|holograma|camada\s+hologr[áa]fica|hologr[áa]fic[oa])\b|\b(modo\s+hologr[áa]fico|janela\s+hologr[áa]fica|holograma\s+ativo)\b", t):
        if fr is not None:
            fr.set_holo_mode(True)
            w_ = fr.focused_window() if hasattr(fr, "focused_window") else None
            if w_:
                fr.holo_live(w_.get("app_id") or "", None)
        await broadcast({"type": "holo_window", "enabled": True})
        await dizer("Modo holográfico ativado. Partículas reconfiguradas na janela, senhor.")
        return True

    # ---------------- COMANDOS DIRETOS: CELULAR ----------------
    if re.search(r"\b(celular|telefone|smartphone|meu cel|no cel)\b", t):
        if re.search(r"\b(fech\w*|tir\w*|escond\w*|deslig\w*|par\w*|some)\b", t):
            import celtela
            await asyncio.to_thread(celtela.fechar)
            await dizer("Tela do celular fechada, senhor.")
            return True
        if re.search(r"\b(desbloque\w*|acend\w*|destrav\w*)\b", t):
            import celular, celtela
            await asyncio.to_thread(celular.acordar)
            await asyncio.to_thread(celular.desbloquear)
            await asyncio.to_thread(celtela.mostrar)
            await dizer("Celular desbloqueado e tela espelhada no holograma, senhor.")
            return True
        if re.search(r"\b(mostr\w*|espelh\w*|projet\w*|exib\w*|abr\w*|lig\w*|conect\w*|ponte)\b", t):
            import celtela
            await asyncio.to_thread(celtela.mostrar)
            await dizer("Espelhando tela do celular no holograma, senhor.")
            return True

    # ---------------- COMANDOS DIRETOS: AGENDA ----------------
    if re.search(r"\b(limp\w*|apag\w*|esvazi\w*)\b.*?\b(agenda|compromissos?)\b|\blimpar\s+agenda\b", t):
        if ops is not None:
            n = ops.agenda_limpar()
            await broadcast({"type": "painel", "op": "agenda", "data": {"itens": []}, "dados": {"itens": []}})
            await dizer("Agenda limpa, senhor. Todos os compromissos foram removidos.")
            return True
    m_ag_rm = re.search(r"\b(?:exclu\w*|apag\w*|remov\w*|cancel\w*|tir\w*)\b.*?\b(?:d[ao]\s+agenda|compromisso|evento)\s+([a-z0-9à-ú\s\-]+)", t)
    if m_ag_rm and ops is not None:
        termo_ag = m_ag_rm.group(1).strip()
        ok_rm, tit_rm = ops.agenda_remover(termo_ag)
        dados_ag = ops.agenda_painel_dados(7)
        await broadcast({"type": "painel", "op": "agenda", "data": dados_ag, "dados": dados_ag})
        await dizer(f"Compromisso '{tit_rm}' removido da agenda." if ok_rm else f"Não encontrei '{termo_ag}' na agenda.")
        return True
    if re.search(r"\b(mostr\w*|abr\w*|ver|exib\w*)\b.*?\b(?:a\s+)?agenda\b|\bminha\s+agenda\b|\bver\s+agenda\b|\bo que tenho na agenda\b", t):
        if ops is not None:
            dados_ag = ops.agenda_painel_dados(14)
            await broadcast({"type": "painel", "op": "agenda", "data": dados_ag, "dados": dados_ag})
            await dizer(f"Você tem {len(dados_ag['itens'])} compromissos agendados, senhor." if dados_ag["itens"] else "Sua agenda está livre, senhor.")
            return True

    # ---------------- PROJEÇÃO HOLOGRÁFICA 3D: DESATIVAÇÃO PRIORITÁRIA ----------------
    if not re.search(r"\brota[çc]\w*|\bgir\w*|\bexplod\w*|\bcor\b|\bfoto\b|\bzoom\b|\bmodifi\w*|\baltere\b|\bmude\b", t) and \
            re.search(r"\b(desativ\w*|desetiv\w*|deslig\w*|fech\w*|dispens\w*|encerr\w*|apag\w*|cancel\w*|sai[ar]?\s+d[oa]|tir[ae]|remov[ae])\s+(?:\S+\s+){0,2}?(proje[çc][ãa]o|matriz(?:\s+hologr[áa]fica)?|holograma(?:\s+3d)?|palco(?:\s+hologr[áa]fico)?|objeto\s+3d)\b|\b(?:dispensar|fechar|desativar|desligar|encerrar|apagar|sair\s+d[oa])\s+(?:a\s+|o\s+)?(?:modo\s+proje[çc][ãa]o|matriz(?:\s+hologr[áa]fica)?|holograma(?:\s+3d)?|palco)\b", t):
        import projecao as _pj
        _pj.fechar_projecao()
        await broadcast({"type": "holo", "op": "clear"})
        await dizer("Projeção holográfica e matriz encerradas, senhor.")
        return True

    # ---------------- PROJEÇÃO HOLOGRÁFICA 3D: ATIVAÇÃO ----------------
    if re.search(r"\b(?:ativar|ligar|iniciar|abrir)\s+(?:o\s+)?modo\s+proje[çc][ãa]o\b|\b(?:ativar|ligar|iniciar|abrir)\s+(?:a\s+)?matriz(?:\s+hologr[áa]fica)?\b|\bmodo\s+proje[çc][ãa]o\b|\bmatriz\s+hologr[áa]fica\b", t):
        if not re.search(r"\b(desativ|desetiv|deslig|fech|par|tir|apag|sai|n[ãa]o)\b", t):
            import projecao as _pj
            spec = _pj.criar_objeto_3d("reator")
            await broadcast({"type": "holo", "op": "show", "spec": spec})
            await dizer("Modo projeção ativado. Reator Arc Mark VII projetado no palco holográfico.")
            return True

    # ---------------- PROJEÇÃO DE OBJETO ESPECÍFICO ----------------
    m_proj = re.search(r"\b(?:projete|projetar|crie\s+(?:um\s+)?holograma\s+de|monte\s+(?:um\s+)?holograma\s+de|holograma\s+de|gerar\s+(?:um\s+)?holograma\s+de|exib(?:ir?|a)\s+(?:um\s+)?holograma\s+de|mostre\s+(?:um\s+)?holograma\s+de|proje[çc][ãa]o\s+de\s+(?:um\s+|uma\s+)?|coloque\s+(?:um\s+|uma\s+)?holograma\s+de)\s+([a-z0-9à-ú\s\-]+)", t)
    if m_proj:
        termo = m_proj.group(1).strip()
        if not re.search(r"\b(celular|telefone|smartphone|agenda|painel|janela)\b", termo):
            import projecao as _pj
            spec = _pj.criar_objeto_3d(termo)
            await broadcast({"type": "holo", "op": "show", "spec": spec})
            await dizer(f"Projetando {spec.get('titulo', termo)} em wireframe holográfico tridimensional.")
            return True

    # ---------------- MANIPULAÇÃO DO OBJETO SE JÁ ATIVO (SEM CAPTURA GULOSA) ----------------
    import projecao as _pj
    if _pj._estado_projecao.get("ativo"):
        m_mod = re.search(r"\b(?:modele|modifique|altere|mude)\s+(?:a\s+proje[çc][ãa]o|o\s+holograma|o\s+objeto|a\s+cor)?\s*(?:para\s+)?([a-z0-9à-ú\s\-]+)|\b(vis[ãa]o\s+explodida|explodir|desmontar|recompor|wireframe|raio\s*x|part[íi]culas?|gire\s+mais\s+(?:r[áa]pido|devagar)|mais\s+r[áa]pido|mais\s+lento|parar\s+rota[çc][ãa]o|cor\s+[a-zà-ú]+|dourad[oa]|verde|azul|vermelh[oa]|ciano|branco|prata|roxo)\b", t)
        if m_mod:
            mod = (m_mod.group(1) or m_mod.group(2) or "").strip()
            termo = _pj._estado_projecao.get("nome", "reator")
            spec = _pj.criar_objeto_3d(termo, modificacao=mod)
            await broadcast({"type": "holo", "op": "show", "spec": spec})
            await dizer(f"Parâmetros atualizados para {mod}. Renderizando nova matriz.")
            return True
        m_trocar = re.search(r"\b(?:troque|mude|trocar|mudar)\s+(?:o\s+modelo\s+)?(?:para\s+)([a-z0-9à-ú\s\-]+)\b", t)
        if m_trocar:
            candidato = m_trocar.group(1).strip()
            spec = _pj.criar_objeto_3d(candidato)
            await broadcast({"type": "holo", "op": "show", "spec": spec})
            await dizer(f"Projetando {spec.get('titulo', candidato)} em wireframe holográfico tridimensional.")
            return True
    if re.search(r"calibr\w*\s+(?:os\s+|o\s+)?(?:gestos?|mouse)", t):
        gm_ = gmouse[0]
        if gm_ is None:
            await dizer("Ligue o modo mouse primeiro."); return True
        if not hasattr(gm_, "calibrar"):            # a reescrita do gestomouse (14/10) tirou a calibração: limites ficam em memory/gestos.json
            await dizer("A calibração por gesto saiu dessa versão do mouse. Os limites ficam no arquivo de gestos."); return True
        await dizer("Calibrando. Faça a pinça de três dedos e passeie a mão pelos quatro cantos, confortável, por seis segundos.")
        gm_.calibrar(6.0)
        await asyncio.sleep(6.5)
        await dizer(gm_._fecha_calib() if gm_.calib is not None else "Calibrado.")
        return True
    if re.search(r"modo\s+reuni[ãa]o", t):
        on = not bool(_MODE_OFF.search(t))
        await set_mode("privacidade", on); await set_mode("silencio", on)
        await broadcast({"type": "text", "role": "assistant", "text": f"Modo reunião {'ligado' if on else 'desligado'}: privacidade e silêncio."})
        return True
    if re.search(r"\b(quais|que)\s+modos|modos\s+ativos|em que modo", t):
        ativos = [k for k, v in modes.items() if v]
        await dizer("Modos ativos: " + (", ".join(ativos) if ativos else "nenhum") + ".")
        return True
    if re.search(r"\b(bloque\w+|trave|travar)\b.*\b(tela|pc|computador|sess[ãa]o)\b", t):
        await dizer("Bloqueando a tela."); await asyncio.sleep(1.2); await asyncio.to_thread(_noctalia, "session", "lock"); return True
    if re.search(r"\bmodo\s+(de\s+)?(repouso|descanso|dormir)\b|\b(suspend\w+|hibern\w+|dorm\w+)\b.*\b(sexta|voc[êe]|ativa|ligada|acordada|ouvindo)\b"
                 r"|\b(desliga|apaga|apague|desligue)\w*\s+(a\s+)?tela\b", t) \
            and not (re.search(r"modo\s+(de\s+)?repouso", t) and _MODE_OFF.search(t)):
        await dizer("Modo repouso: tela apagada e bloqueada, eu continuo de olho. Mexa no mouse ou diga acordar para voltar.")
        await asyncio.sleep(1.5)
        await asyncio.to_thread(_repouso, True); return True
    if re.search(r"\b(acord\w+|liga\w*\s+(a\s+)?tela|sai\w*\s+do\s+(modo\s+(de\s+)?)?repouso)\b", t) or (re.search(r"modo\s+(de\s+)?repouso", t) and _MODE_OFF.search(t)):
        await asyncio.to_thread(_repouso, False)
        await dizer("Tela de volta."); return True
    if re.search(r"\b(hibern\w+|suspend\w+|suspender|dormir o pc)\b", t):
        await dizer("Bloqueando e suspendendo. Peço a senha ao voltar."); await asyncio.sleep(1.5)
        await asyncio.to_thread(_noctalia, "session", "lock-and-suspend"); return True
    if re.search(r"\b(tire|tirar|tira|fa[çc]a|bata)\b.*\b(print|captura|screenshot|foto da tela)\b|\b(print|screenshot)\b da tela", t):
        d = os.path.expanduser("~/Imagens"); os.makedirs(d, exist_ok=True)
        arq = os.path.join(d, "print-" + time.strftime("%Y%m%d-%H%M%S") + ".png")
        await asyncio.to_thread(subprocess.run, ["grim", arq], capture_output=True)
        await dizer("Print salvo em Imagens."); return True
    if re.search(r"\b(como (est[áa]|anda) o (pc|computador)|status do (pc|computador)|relat[óo]rio do (pc|computador)|estado do (pc|computador))\b", t):
        await dizer(await asyncio.to_thread(pc_status)); return True
    if re.search(r"\b(quais (s[ãa]o )?(os )?comandos|o que voc[êe] (sabe|consegue|pode) fazer|lista de comandos|me ajuda|ajuda)\b", t):
        await dizer(COMANDOS_AJUDA); return True
    return False


# ======================= TAREFAS CONTÍNUAS: "vá desenvolvendo X" / "com esses dados, gere Y" — segue até você mandar parar =======================
continuo = {"ativo": False, "goal": "", "iter": 0, "notes": [], "task": None, "kind": "", "inicio": 0.0}
CONT_FILE = os.path.join(MEM_DIR, "tarefa_continua.json")
CONT_START = re.compile(
    r"\b(?:v[áa]|vai|continue|fique|siga|comece\s+a|v[áa]\s+me)\s+(?:me\s+)?(?:desenvolvendo|fazendo|trabalhando|criando|montando|construindo|pesquisando|explorando|"
    r"analisando|escrevendo|preparando|organizando|gerando|estudando)\b|"
    r"\b(?:desenvolva|trabalhe|continue|explore|monte|crie)\b.{0,60}\b(?:at[ée]\s+eu\s+(?:mandar|falar|dizer|pedir)\s+(?:parar|pra\s+parar|para\s+parar)|sem\s+parar|continuamente|aos\s+poucos|em\s+segundo\s+plano)\b|"
    r"\bcom\s+(?:esses?|estes?|os|tais|tal|este|aquele|o)\s+dados?\b.{0,200}\b(?:gere|crie|monte|fa[çc]a|produza|elabore|desenvolva)\b", re.I)
CONT_DEV = re.compile(r"\b(sistema|aplicativo|app|site|script|programa|c[óo]digo|api|bot|backend|frontend|reposit[óo]rio|software|ferramenta de c[óo]digo)\b", re.I)
CONT_STATUS = re.compile(r"\b(como (est[áa]|anda) a tarefa|o que (voc[êe] )?est[áa] fazendo|qual o progresso|andamento da tarefa|progresso da tarefa)\b", re.I)
CONT_STOP = re.compile(r"\b(pare|parar|cancele|cancela|encerre|chega de|pode parar)\b.{0,25}\b(tarefa|desenvolv\w+|trabalh\w+|tudo|projeto)\b", re.I)
CONT_RESUME = re.compile(r"\b(retome|retomar|continue|continuar)\b.{0,20}\b(tarefa|de onde parou|trabalho)\b", re.I)
_main = {"loop": None}


def _cont_save():
    try:
        json.dump({"goal": continuo["goal"], "iter": continuo["iter"], "notes": continuo["notes"][-40:], "kind": continuo["kind"],
                   "ativo": continuo["ativo"]}, open(CONT_FILE, "w"), ensure_ascii=False, indent=1)
    except Exception:
        pass


def _cont_doc(linha):
    try:
        d = os.path.expanduser("~/Documentos/Friday/tarefas"); os.makedirs(d, exist_ok=True)
        slug = re.sub(r"\W+", "-", continuo["goal"].lower())[:40].strip("-") or "tarefa"
        with open(os.path.join(d, slug + ".md"), "a") as f:
            f.write(f"- {time.strftime('%d/%m %H:%M')} #{continuo['iter']}: {linha}\n")
    except Exception:
        pass


async def continuo_start(goal, retomar=False):
    if continuo["ativo"]:
        return False, "Já estou numa tarefa contínua. Diga pare a tarefa para encerrar."
    goal = re.sub(r"(?i)^\W*sexta[\s-]*feira[,!. ]*", "", goal).strip()
    continuo.update(ativo=True, goal=goal, iter=0 if not retomar else continuo["iter"], kind="programar" if CONT_DEV.search(goal) else "agente",
                    inicio=time.time())
    if not retomar:
        continuo["notes"] = []
    _cont_save()
    if continuo["kind"] == "programar":
        continuo["task"] = asyncio.create_task(_cont_programar())
    else:
        continuo["task"] = asyncio.create_task(_cont_loop())
    return True, "Entendido, chefe. Vou trabalhando nisso em segundo plano e te atualizo. Diga pare a tarefa quando quiser encerrar."


def continuo_stop(motivo="parada"):
    if not continuo["ativo"]:
        return False
    continuo["ativo"] = False
    try:
        import agent as _a; _a.CANCEL.set()
    except Exception:
        pass
    try:
        if claude_proc is not None:
            claude_proc.kill()
    except Exception:
        pass
    _cont_save()
    return True


async def _cont_programar():
    """objetivo de desenvolvimento: o Claude Code CLI (via fila de tarefas) trabalha; aqui só acompanhamos e avisamos."""
    try:
        await broadcast({"type": "text", "role": "tool", "text": "tarefa contínua → programar: " + continuo["goal"][:60]})
        await run_programming(continuo["goal"], None)
        continuo["iter"] += 1; continuo["notes"].append("rodada de desenvolvimento concluída"); _cont_doc("rodada de desenvolvimento concluída")
    except Exception as e:
        continuo["notes"].append("erro: " + str(e)[:80])
    finally:
        if continuo["ativo"]:
            continuo["ativo"] = False
            _cont_save()
            await broadcast({"type": "text", "role": "assistant", "text": "Terminei esta rodada de desenvolvimento, chefe. Quer que eu continue?"})
            await speak("Terminei esta rodada de desenvolvimento, chefe. Quer que eu continue?")


async def _cont_loop():
    try:
        import agent as _ag
    except Exception:
        continuo["ativo"] = False; return
    MAX_IT, MAX_S = 80, 3 * 3600
    while continuo["ativo"] and continuo["iter"] < MAX_IT and time.time() - continuo["inicio"] < MAX_S:
        # só trabalha quando ela não está falando/atendendo você (intercala com a conversa)
        while continuo["ativo"] and (speaking or busy.locked() or agente_ativo[0] or time.time() - conv["t"] < 8):
            await asyncio.sleep(2)
        if not continuo["ativo"]:
            break
        continuo["iter"] += 1
        prompt = (f"TAREFA CONTÍNUA (continue de onde parou): {continuo['goal']}\n"
                  f"Progresso até agora:\n" + ("\n".join(continuo["notes"][-6:]) or "(nada ainda)") + "\n"
                  "Faça SÓ o próximo passo concreto (1 ou 2 ferramentas). Salve resultados em arquivo quando fizer sentido (nota/onlyoffice_criar). "
                  "No final diga em 1 frase o que fez. Se o objetivo estiver 100% concluído, comece o final com 'CONCLUÍDO:'.")
        await broadcast({"type": "text", "role": "tool", "text": f"tarefa contínua #{continuo['iter']}: {continuo['goal'][:50]}"})
        try:
            agente_ativo[0] = True
            try:
                res = await asyncio.to_thread(_ag.run, prompt, _friday_ctx(), fr, ops, None, None, False)
            finally:
                agente_ativo[0] = False
        except Exception as e:
            res = {"fala": "erro: " + str(e)[:80]}
        if not continuo["ativo"] or res.get("cancelado"):
            break
        fala = str(res.get("fala") or "").strip() or "passo executado"
        continuo["notes"].append(f"#{continuo['iter']}: {fala[:200]}")
        _cont_doc(fala[:300]); _cont_save()
        await broadcast({"type": "text", "role": "assistant", "text": f"[LOOP] #{continuo['iter']}: {fala}"})
        if fala.upper().startswith("CONCLU"):
            continuo["ativo"] = False; _cont_save()
            await speak("Terminei a tarefa, chefe. " + fala.split(":", 1)[-1].strip()[:200])
            return
        if continuo["iter"] % 4 == 0:
            await speak(f"Atualização: {fala[:160]}")
        for _ in range(15):                               # intervalo entre passos (corta na hora se mandar parar)
            if not continuo["ativo"]:
                break
            await asyncio.sleep(2)
    if continuo["ativo"]:
        continuo["ativo"] = False; _cont_save()
        await speak("Cheguei ao limite desta tarefa contínua, chefe. Diga retomar se quiser que eu siga.")


async def handle_continuo(txt):
    t = txt or ""
    named = bool(fr is not None and fr.NAME_RE.match(t))
    if not (friday_state["on"] or named):
        return False
    async def dizer(m):
        await broadcast({"type": "text", "role": "assistant", "text": m}); log_turn("prometheus", m); await speak(m)
    if CONT_STOP.search(t):
        if continuo_stop():
            await dizer("Parei a tarefa contínua."); 
        else:
            await dizer("Não há tarefa contínua em andamento.")
        return True
    if CONT_STATUS.search(t):
        if continuo["ativo"]:
            ult = continuo["notes"][-1] if continuo["notes"] else "ainda começando"
            await dizer(f"Estou em {continuo['goal'][:80]}. Passo {continuo['iter']}: {ult[:140]}")
        else:
            await dizer("Não tenho tarefa contínua em andamento.")
        return True
    try:
        import plano as _pl
        _tem_plano = _pl.ultimo_incompleto() is not None
    except Exception:
        _tem_plano = False
    if CONT_RESUME.search(t) and not continuo["ativo"] and not _tem_plano:      # plano incompleto tem prioridade (friday_ask retoma)
        try:
            d = json.load(open(CONT_FILE)); continuo.update(goal=d.get("goal", ""), iter=d.get("iter", 0), notes=d.get("notes", []), kind=d.get("kind", "agente"))
        except Exception:
            pass
        if continuo["goal"]:
            ok, msg = await continuo_start(continuo["goal"], retomar=True); await dizer("Retomando: " + continuo["goal"][:80]); return True
    if CONT_START.search(t) and not re.search(r"\bmodo\b", t, re.I):
        ok, msg = await continuo_start(t)
        await dizer(msg)
        return True
    return False


_pend_fala = {"txt": "", "t": 0.0, "task": None}
_INCOMPLETA = re.compile(r"(\.\.\.|…|,)\s*$|\b(a|o|as|os|e|de|do|da|dos|das|que|pra|para|no|na|nos|nas|um|uma|com|em|mas|ou|tipo|aquele|aquela|essa|esse|me|meu|minha)\s*[.?!]?\s*$", re.I)


def _nome_unico(rostos):
    """19/10: dois rostos no mesmo quadro saíam ambos 'Iann' (sim 0,49 e 0,56) e o aprendizado gravava o errado.
    A mesma pessoa só aparece uma vez: fica com o rosto mais parecido; os outros viram desconhecidos."""
    melhor = {}
    for f in rostos:
        if f.get("nome") and (f["nome"] not in melhor or f.get("sim", 0) > melhor[f["nome"]].get("sim", 0)):
            melhor[f["nome"]] = f
    for f in rostos:
        if f.get("nome") and melhor.get(f["nome"]) is not f:
            f["nome"], f["pid"] = None, None
    return rostos


async def route_speech(txt: str):
    """junta frase cortada por pausa: se a transcrição termina incompleta ("A música...", "coloca a"), espera a continuação."""
    now = time.time()
    if _pend_fala["txt"] and now - _pend_fala["t"] < 4.5:
        if _pend_fala["task"]:
            _pend_fala["task"].cancel()
        txt = _pend_fala["txt"].rstrip(" .…") + " " + txt
        _pend_fala.update(txt="", task=None)
    if _INCOMPLETA.search(txt or "") and len(txt.split()) >= 2 and not eh_eco(txt):
        _pend_fala.update(txt=txt, t=now)

        async def _solta(t_=txt):
            await asyncio.sleep(3.0)                    # não veio continuação: segue com o que tem
            if _pend_fala["txt"] == t_:
                _pend_fala.update(txt="", task=None)
                await _route_speech_now(t_)
        _pend_fala["task"] = asyncio.create_task(_solta())
        if friday_state["on"]:
            await broadcast({"type": "friday_heard", "text": txt[:140] + " …"})
        return
    partes = _dividir_comandos(txt)
    for i, p_ in enumerate(partes):                    # "Desbloquear celular. Sexta-feira, me localize." = 2 pedidos, em ordem
        await _route_speech_now(p_)


_WAKE_MEIO = re.compile(r"(?<=[.!?])\s+(?=(?:sexta|s\w{2,5})[\s-]*feira\s*[,.!]\s*\w)", re.I)   # vocativo ("Sexta-feira, ...") e não "sexta-feira vai ter festa"


def _dividir_comandos(txt):
    """16/10: dois pedidos na mesma fala ("Abre o navegador. Sexta-feira, desbloqueia o celular") — só o último era feito.
    Corta onde o nome dela recomeça uma frase; cada parte com >= 2 palavras vira um pedido (a 1ª ganha o nome se não tinha)."""
    pedacos = [p.strip() for p in _WAKE_MEIO.split(txt or "") if p.strip()]
    if len(pedacos) < 2 or any(len(re.findall(r"\w+", p)) < 2 for p in pedacos):
        return [txt]
    if not WAKE_RE.search(pedacos[0]):
        pedacos[0] = "Sexta-feira, " + pedacos[0]
    return pedacos[:3]


_NOMES_STT = [(r"\bchat\s*-?\s*(?:g\s*)?(?:[ie]\s*)?p\s*t\b|\bchat\s*gpt\b|\bchat\s*e?\s*pt\b|\bchatbt\b", "ChatGPT"),
              (r"\bolio\s*ff?s?\b|\bol[ií]\s*office\b|\bonly\s*of+i?ce?\b", "OnlyOffice"), (r"\bcr[ôo]mi?um\b|\bcromio\b|\bcl[ôo]m\b|\bcrome\b", "Chromium"),
              (r"\b(?:omni|one|on)\s*office\b", "OnlyOffice"), (r"\bplanilin+a\b", "planilha"),
              (r"\bdes(?:moque|broque|boque|loque|bloke|moquei|mulque|mulqu|bloqe)(\w*)", r"desbloque\1"),          # 16/10 STT: "Desmoquear celular"
              (r"\b(desbloque\w*|destrav\w*)\s+(?:o\s+)?navegador\b", r"\1 o celular"),       # 16/10 STT: "Desbloquear Navegador"
              (r"\bvir[ie]\b", "vire"), (r"\b(ptz|petz|pedz|iptz)\b", "PTZ"),
              (r"\b(?:ou|o|n[ao])\s+integra\s+site\b", "no Integra Site"),
              (r"\bmodo\s+(?:deve|devi|d[ée]vi?|de\s+v[eê]|dvd|debe|devo)\b", "modo dev"), (r"\bdev\s*mode\b", "modo dev"),
              (r"\b(?:ente[,\s]*gravit|antigravig|ante[- ]gravity|ante\s*gravit|anti\s*gravit\w*|broadway)\b", "Antigravity"),
              (r"\b(?:abracept|abra\s*o\s*chat\s*pt|abro\s*o\s*chat|chat\s*bt)\b", "abra o ChatGPT"),
              (r"\b(?:birch\s*chromium|bicho\s*chromium)\b", "abra o Chromium"),
              (r"\b(?:decor[ae]m?\s+(?:os\s+)?(?:ícones?\s+(?:da\s+)?)?minha\s+docx?)\b", "minha dock"),
              (r"\b(?:constalar|comfilar)\b", "cancelar"),
              (r"(^|[,.]\s*)(?:desvid|desvig|deslig)[ae]\b", r"\1desligue"), (r"(^|[,.]\s*)(?:orem|pone|olhem?e?)\s+para\b", r"\1olhe para"),
              (r"\bgem[ie]n[ie]\b", "Gemini"), (r"\bperplex\w*\b", "Perplexity"),
              (r"\b(?:zap\s*zac|zac\s*zac|zap\s*zack|zap\s*zap|zapzap|zac)\b", "ZapZap"),
              (r"\b(?:whats\s*app|uats?app|u[ao]ts?zap|uatis?api?|wpp)\b", "WhatsApp"),
              (r"\b(?:renuzapzap|yeah\s+no\s+zap\s+zap|i'm\s+zap\s+zack|abre\s+o\s+zac|abro\s+zapzap)\b", "abra o ZapZap")]


def _limpa_fala(txt):
    """corrige nomes que o Whisper estropia e remove frases que são a própria voz dela captada junto com o pedido."""
    import difflib
    txt = re.sub(r"^\W*(?:concern,?\s*)?", "", txt or "", flags=re.I)
    for pat, rep in _NOMES_STT:
        txt = re.sub(pat, rep, txt, flags=re.I)
    # palavra de ativação estropiada no início ou no fim: "Esta Feira", "Sutta Feira", "Sinta feira", "Seta-feira", "Danta fera", "Questa feira", "Stafeira"
    _w = r"(?:(?!segunda|ter[çc]a|quarta|quinta)[esdtcq][a-zà-ú]{1,6}[\s-]*f[eé]i?ra?|at[ée]\s+a\s+feira|sexta|seira|sextas|stafeira)"   # sem os dias da semana
    txt = re.sub(rf"^\W*{_w}\b[,.:!]?\s*", "Sexta-feira, ", txt, flags=re.I)
    txt = re.sub(rf"[,\s]+{_w}\W*$", ", Sexta-feira.", txt, flags=re.I)
    # "me acha/me ache" curtinho sai "mi achar", "Miyashi", "é minha chave", "Minha Char" (15/10): vira pedido claro p/ a câmera
    m_ = re.fullmatch(r"\s*((?:(?:sexta|s\w{2,5})[\s-]*feira)[,.\s]*)?(?:é\s+)?(?:m[ei]|my|mmi)\s*y?a?\s*(?:ach|ash|ax|chav|char)\w*[\s,.!?]*((?:sexta|s\w{2,5})[\s-]*feira)?[.!?]*\s*|"
                     r"\s*((?:(?:sexta|s\w{2,5})[\s-]*feira)[,.\s]*)?(?:é\s+)?minha\s+cha(?:ve|r)s?[\s,.!?]*((?:sexta|s\w{2,5})[\s-]*feira)?[.!?]*\s*", txt, flags=re.I)
    if m_ or re.fullmatch(r"\s*(?:(?:sexta|s\w{2,5})[\s-]*feira[,.\s]*)?(?:me\s+localiz[ae]r?|localiz[ae]r?\s+(?:a\s+)?mim|me\s+encontr[ae]r?|"
                         r"onde\s+(?:é\s+que\s+)?(?:eu\s+)?estou)[\s,.!?]*(?:(?:sexta|s\w{2,5})[\s-]*feira)?[.!?]*\s*", txt, flags=re.I):
        txt = "Sexta-feira, me localiza."
    # "decora/memoriza/aprende o quarto" = mapear com a câmera (o roteador entendia "decorar" como enfeitar)
    txt = re.sub(r"\b(?:decor|memoriz|aprend|grav)[aeo]r?\s+(?:o\s+)?(?:meu\s+)?quarto\b", "mapeie o quarto com a câmera", txt, flags=re.I)
    rec = [b for t_, b in _ditas if time.time() - t_ <= 120 and b]
    if not rec:
        return txt
    frases = re.split(r"(?<=[.!?])\s+", txt.strip())
    def dela(f):
        n = _norm_eco(f)
        return len(n) >= 8 and any(n in r or difflib.SequenceMatcher(None, n, r).ratio() > 0.62 for r in rec)
    boas = [f for f in frases if not dela(f)]
    return " ".join(boas) if boas else txt


async def _route_speech_now(txt: str):
    txt = _limpa_fala(txt)
    if eh_eco(txt):
        return                                       # era a voz dela no microfone: ignora (evita se auto-comandar)
    if modes["privacidade"] and not _is_owner_voice():
        return                                       # modo privacidade: só a voz do dono dá comandos
    if friday_state["on"]:
        await broadcast({"type": "friday_heard", "text": txt[:140]})
    try:
        import manual as _man
        _man_run = _man.running()
    except Exception:
        _man_run = False
    _quer_desligar = bool(re.search(r"\bdeslig\w*\b.{0,25}\b(pc|computador|m[áa]quina|notebook|tudo)\b|\bpar[ae]\s+tudo\s+e\s+deslig", (txt or "").lower()))
    if STOP_RE.search(txt) and not _quer_desligar and (speaking or busy.locked() or agente_ativo[0] or _man_run or continuo["ativo"] or state["state"] in ("thinking", "speaking") or len(fila_tarefas) > 0):
        barge["v"] = False
        _tinha = continuo_stop()
        fila_tarefas.clear()
        cancel_all()
        await broadcast({"type": "friday_heard", "text": txt[:140]})
        asyncio.create_task(speak("Parei a tarefa e tudo que estava fazendo, chefe." if (_tinha or agente_ativo[0]) else "Parei, chefe."))
        return
    if (STOP_RE.search(txt) and not _quer_desligar and len(_palavras_sem_nome(txt)) <= 3 and (friday_state["on"] or (fr is not None and fr.NAME_RE.search(txt)))
            and not oferta.get("tarefa") and not _ha_pendente(45) and not (ops is not None and any(i["estado"] == "pendente" for i in ops.approvals()))):
        barge["v"] = False                            # "pare" com nada rodando (nem aprovação/oferta para cancelar): diz isso, não vai p/ o think
        await broadcast({"type": "friday_heard", "text": txt[:140]})
        asyncio.create_task(speak("Não tem nada rodando."))
        return
    if SKIP_RE.search(txt) and (agente_ativo[0] or busy.locked() or _man_run):
        barge["v"] = False
        skip_step()
        await broadcast({"type": "friday_heard", "text": txt[:140]})
        asyncio.create_task(speak("Pulei a etapa, chefe."))
        return
    if barge["v"]:                                    # começou enquanto ela falava: só passa se chamou pelo nome
        barge["v"] = False
        if barge.get("dono"):                         # faixa plena (TitaNet confirmou o dono): o eco já foi barrado por texto acima -> interrompe e atende
            voz.log(f"barge-in aceito (voz do dono verificada): {txt[:40]!r}")
            barge["dono"] = False
            cancel_speech()
        # antes descartava tudo sem o nome: pedido feito logo após ela terminar (na "cauda" de 2,5 s) se perdia em silêncio.
        # O eco já foi filtrado acima (eh_eco compara com o que ela disse): frase de verdade, com ela ligada, passa.
        elif not (fr is not None and fr.NAME_RE.match(txt or "")) and not (friday_state["on"] and len((txt or "").split()) >= 4):
            return
        else:
            cancel_speech()                           # chamou: ela se cala e atende
    if await handle_modes(txt):
        return
    if await handle_continuo(txt):
        return
    if modes["criacao"] and friday_state["on"]:                     # modo criação: falas viram comandos do construtor
        try:
            import construtor as _ct
            _r = await asyncio.to_thread(_ct.comando_voz, txt)
        except Exception as e:
            _r = "Erro no construtor: " + str(e)[:80]
        if _r:
            await broadcast({"type": "text", "role": "user", "text": txt})
            await broadcast({"type": "text", "role": "assistant", "text": _r})
            await speak(_r)
            return
    """Fala ouvida -> decide se é comigo. Nome 'Prometheus', janela de conversa ou comando direto com o usuário à vista = sim;
    o resto vai para triagem barata (sem inventar resposta) e fica de contexto ambiente."""
    now = time.time()
    if fr is not None:
        if fr.WAKE_OFF.search(txt):
            await friday_set(False, force=True); return
        if fr.WAKE_ON.search(txt):
            await friday_set(True, force=True)
            resto = fr.NAME_RE.sub("", txt).strip(" ,.:;!?\t\n")
            resto = re.sub(r"^[ ,.:;!?\t\n]+", "", resto)
            resto = re.sub(r"^\b(lig\w*|ativ\w*|acord\w*|despert\w*|inici\w*|volt\w*|on)\b", "", resto, flags=re.I).strip(" ,.:;!?\t\n")
            if not resto:
                return
            txt = resto
        elif not friday_state["on"]:
            if fr.NAME_RE.search(txt):
                await friday_set(True, force=True)
                resto = fr.NAME_RE.sub("", txt).strip(" ,.:;!?\t\n")
                resto = re.sub(r"^[ ,.:;!?\t\n]+", "", resto)
                if not resto or re.search(r"^\b(lig\w*|ativ\w*|acord\w*|despert\w*|inici\w*|volt\w*|on)\b", resto, re.I):
                    return
                txt = resto
            else:
                _fi = fr.fast_intent(txt)
                if _fi and _fi.get("acoes"):
                    await friday_set(True, force=True)
                else:
                    return

    if await handle_approval_speech(txt):
        return
    if await handle_offer_speech(txt):
        return
    if await handle_skip_speech(txt):
        return
    if ops is not None and not friday_state["on"] and AGENDA_HINT.search(fr.NAME_RE.sub("", txt) if fr is not None else txt):
        asyncio.create_task(extract_agenda(txt, "voz" if (WAKE_RE.search(txt) or now - conv["t"] < CONV_WINDOW) else "ambiente"))
    seen = now - scene["t"] < 8
    alone = seen and len(scene["faces"]) <= 1
    wake = WAKE_RE.search(txt)
    if wake:
        txt = (WAKE_RE.sub("", txt, count=1).strip(" ,.!?;:") or "estou ouvindo")
    # você à vista e sozinho: o que falar é para ele (a triagem só decide quando há mais gente ou você está fora de quadro)
    crowd = seen and len(scene["faces"]) >= 2
    if (friday_state["on"] and not wake and now - conv["t"] > CONV_WINDOW and _portao_v2()
            and _faixa_ult["f"] != "plena" and time.time() - _faixa_ult["t"] < 30):
        voz.log(f"route: Friday ligada sem troca recente e faixa {_faixa_ult['f']}: exige nome -> {txt[:40]!r}")
        overheard.append((now, txt, current_speaker.get("nome")))
        return
    if wake or now - conv["t"] < CONV_WINDOW or friday_state["on"] or (alone and (DIRECT_RE.search(txt) or len(txt.split()) >= 3)):
        conv["t"] = now
        await ask(txt, [], voz=True)
        return
    overheard.append((now, txt, current_speaker.get("nome")))
    del overheard[:-12]
    if len(txt.split()) < 3 or now - mind_state["last_triage"] < 6:
        return
    mind_state["last_triage"] = now
    quem = current_speaker.get("nome") or "voz desconhecida"
    d = await llm_json(
        "Você é o filtro de atenção do assistente Prometheus (um agente que vive no PC do usuário). Uma fala foi captada pelo microfone "
        "SEM o nome do assistente. Decida se foi dirigida a ele (pergunta, pedido ou conversa com ele) ou se é conversa com outra pessoa/"
        "TV/telefone/monólogo. Na dúvida, NÃO é para ele.\n"
        f"Fala ({quem}; usuário {'sozinho à vista' if alone else 'não está sozinho/à vista'}): \"{txt}\"\n"
        'Responda SÓ JSON: {"para_mim": true|false}')
    if d and d.get("para_mim") is True:
        conv["t"] = time.time()
        await ask(txt, [], voz=True)


async def mind_think(reason: str, extra: str = ""):
    """Pensamento autônomo: olha o estado real (percepção local), decide se vale falar/lembrar. Padrão = não fazer nada."""
    if mind_state["busy"] or speaking or busy.locked() or not friday_state["on"]:
        return
    mind_state["busy"] = True
    try:
        now = time.time()
        objs = [o for o in (scene.get("objetos") or {})][:4] if now - scene["t_obj"] < 20 else []
        ouvido = [f"{nm or 'alguém'}: {t}" for (t_, t, nm) in overheard if now - t_ < 240][-4:]
        estado = {
            "agora": time.strftime("%A, %d/%m %H:%M"),
            "motivo_do_pensamento": reason,
            "usuario": _nome_usuario(),
            "usuario_a_vista_agora": bool(now - scene["t"] < 8),
            "minutos_desde_ultima_conversa": round((now - max(conv["t"], mem.get("ultima_vez", 0))) / 60, 1),
            "minutos_desde_minha_ultima_fala_espontanea": round((now - mind_state["last_proactive"]) / 60, 1) if mind_state["last_proactive"] else None,
            "falas_ouvidas_nao_dirigidas_a_mim": ouvido,
            "objetos_na_cena (detector, pode errar)": objs,
            "o_que_sei_do_usuario": mem.get("fatos", {}),
            "pc_agora (janelas, agenda)": await asyncio.to_thread(_friday_ctx) if friday_state["on"] else "",
            "minhas_falhas_recentes": _falhas_recentes(),
            "minutos_desde_minha_ultima_oferta": round((now - oferta["t"]) / 60, 1) if oferta["t"] else None,
            "minhas_ultimas_falas_espontaneas (NÃO repita nem parafraseie)": list(mind_state.get("ditas", []))[-8:],
        }
        prompt = (
            "Você é a mente de fundo do Prometheus, assistente autônomo que vive no PC do usuário (pt-BR). Você percebe o ambiente o tempo "
            "todo e decide, com bom senso, se há algo realmente útil a fazer AGORA. REGRAS: (1) o padrão é NÃO fazer nada; "
            "(2) só fale se houver motivo concreto e útil baseado em fatos do estado abaixo (um aviso, um lembrete, uma pergunta curta "
            "pertinente, uma saudação natural na chegada); (3) NUNCA invente o que a câmera mostra nem comente gestos, coçar o rosto, "
            "movimentos ou aparência; (4) no máximo UMA frase curta e natural; (5) não repita o que já disse; (6) se o usuário parece "
            "concentrado/trabalhando, não interrompa sem necessidade; (7) se o contexto do PC mostra algo que você PODE FAZER por ele "
            "(ex.: erro na tela, extrato/planilha aberta para analisar, compromisso próximo sem preparação, download/arquivo para organizar), "
            "use acao=oferecer: texto = pergunta curta oferecendo (\"Quer que eu ...?\"), tarefa = o pedido completo, no imperativo, "
            "que você executará se ele aceitar; no máximo 1 oferta a cada 10 minutos e nunca a mesma duas vezes; (8) se minhas_falhas_recentes "
            "mostra a MESMA falha 2+ vezes, ofereça se aprimorar: tarefa = \"aprimore-se: corrija <a falha, com detalhes>\".\n"
            f"ESTADO: {json.dumps(estado, ensure_ascii=False)}\n{extra}\n"
            "humor = a emoção da sua frase, coerente com o momento do usuário (ex.: ele frustrado = preocupado; conquista = empolgado).\n"
            'Responda SÓ JSON: {"acao":"nada"|"falar"|"lembrar"|"responder"|"oferecer"|"executar","texto":"frase a falar ou resposta","tarefa":"",'
            '"humor":"neutro|alegre|empolgado|carinhoso|confiante|curioso|surpreso|pensativo|serio|preocupado|triste|irritado|assustado",'
            '"chave":"","valor":"","id":""}')
        d = await llm_json(prompt)
        if not d:
            return
        acao = d.get("acao")
        if acao == "executar" and str(d.get("tarefa", "")).strip():
            tarefa = str(d["tarefa"]).strip()[:300]
            txt = str(d.get("texto") or "").strip()[:240]
            print(f"mente autônoma: executando tarefa '{tarefa}'", flush=True)
            if txt and not speaking and state["state"] == "idle":
                await broadcast({"type": "text", "role": "assistant", "text": txt})
                log_turn("prometheus", txt)
                await speak(txt)
            asyncio.create_task(run_task({"id": f"auto_{int(now)}", "origem": "autonomia", "descricao": tarefa, "texto": tarefa}))
        elif acao == "responder" and ops is not None and d.get("id") and str(d.get("texto", "")).strip():
            notif = next((n for n in await asyncio.to_thread(ops.phone_notifs) if n["id"] == str(d["id"])), None)
            if notif and notif.get("reply_id"):
                await asyncio.to_thread(ops.gated, "wa.reply", notif.get("titulo") or "", f"responder {notif.get('titulo')}: {str(d['texto'])[:100]}",
                                        {"reply_id": notif["reply_id"], "texto": str(d["texto"])[:500]})
        if acao == "lembrar" and d.get("chave") and d.get("valor"):
            mem.setdefault("fatos", {})[str(d["chave"])[:40]] = str(d["valor"])[:160]
            save_mem()
        elif acao == "oferecer" and str(d.get("tarefa", "")).strip() and str(d.get("texto", "")).strip():
            tarefa = str(d["tarefa"]).strip()[:300]
            _oferta_cooldown = 75 if friday_state["on"] else 300
            if now - oferta["t"] > _oferta_cooldown and tarefa.lower() not in oferta["feitas"] and not speaking and not busy.locked() \
                    and state["state"] == "idle" and now - last_voice["t"] > 8:
                oferta.update(tarefa=tarefa, t=time.time()); oferta["feitas"].append(tarefa.lower()); del oferta["feitas"][:-20]
                mind_state["last_proactive"] = time.time()
                txt = str(d["texto"]).strip()[:240]
                await broadcast({"type": "text", "role": "assistant", "text": txt})
                log_turn("prometheus", txt + f"  [oferta: {tarefa}]")
                await speak(txt); conv["t"] = time.time()
        elif acao == "falar" and str(d.get("texto", "")).strip():
            txt = str(d["texto"]).strip()[:240]
            import difflib as _dl
            repetida = any(_dl.SequenceMatcher(None, txt.lower(), x.lower()).ratio() > 0.55 for x in mind_state.get("ditas", []))
            saudacao = re.search(r"\b(?:bom dia|boa tarde|boa noite|ol[áa]|oi)\b|tudo (?:bem|certo)", txt, re.I) and "voltou" not in reason
            ok = (not speaking and not busy.locked() and state["state"] == "idle" and now - last_voice["t"] > 10 and not repetida and not saudacao
                  and now - mind_state["last_proactive"] > (600 if friday_state["on"] else 900))     # 19/10: era 60 s -> saudação em loop
            mind_state.setdefault("ditas", []).append(txt); del mind_state["ditas"][:-12]
            if ok:
                mind_state["last_proactive"] = time.time()
                await set_state(mood=_humor_norm(d.get("humor")) or "neutro")
                await broadcast({"type": "text", "role": "assistant", "text": txt})
                log_turn("prometheus", txt)
                await speak(txt)
                conv["t"] = time.time()
                await set_state("idle", "neutro")
    finally:
        mind_state["busy"] = False


def _vigilia_quieta():
    """F3: silêncio da ajuda proativa — 60 s após fala do dono e enquanto houver tarefa ativa."""
    ult_fala = max(_faixa_ult["t"], owner_voice["t"], last_voice.get("t", 0))
    return (time.time() - ult_fala < 60 or agente_ativo[0] or task_state["running"] is not None
            or bool(fila_tarefas) or hud_state.get("active"))


async def _vigilia_multimodal_tick():
    """Vigília proativa: ajuda de tela só por evento (OCR com Traceback|Error); rosto só com "vigilia_rosto": true."""
    if speaking or busy.locked() or state["state"] != "idle" or not friday_state["on"] or _vigilia_quieta():
        return
    import visao
    try:                                            # memory/friday.json "vigilia_rosto": true religa a leitura de expressão
        _rosto = bool(json.load(open(os.path.join(MEM_DIR, "friday.json"))).get("vigilia_rosto", False))
    except Exception:
        _rosto = False
    fa = _shared.get("frame")
    jpg_cam = None
    if _rosto and fa is not None and time.time() - _shared.get("frame_t", 0) < 3.0:
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", fa, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                jpg_cam = buf.tobytes()
        except Exception:
            pass

    diag = await asyncio.to_thread(visao.analisar_ajuda_multimodal, None, jpg_cam, _rosto)
    if diag.get("precisa_ajuda") and diag.get("oferta_texto") and diag.get("tarefa"):
        txt = str(diag["oferta_texto"]).strip()
        tarefa = str(diag["tarefa"]).strip()
        now = time.time()
        if now - oferta["t"] > 75 and not _vigilia_quieta() and tarefa.lower() not in oferta["feitas"] and not speaking and state["state"] == "idle" and not busy.locked():
            oferta.update(tarefa=tarefa, t=now)
            oferta["feitas"].append(tarefa.lower())
            del oferta["feitas"][:-20]
            mind_state["last_proactive"] = now
            await broadcast({"type": "text", "role": "assistant", "text": txt})
            log_turn("prometheus", txt + f"  [vigília multimodal: {diag.get('motivo', '')}]")
            await speak(txt)
            conv["t"] = now





# ======================= HUD HOLOGRÁFICO DE TAREFAS (padrão ao usar ferramentas) =======================
_INICIO_DAEMON = time.time()
hud_state = {"steps": [], "titulo": "", "t0": 0.0, "last": 0.0, "active": False, "n": 0, "clear_task": None}


def _wrap_obj(txt, n=44, k=4):
    words, lines, cur = (txt or "").split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines[:k]


async def hud_push(estado="executando", force=False):
    """mostra/atualiza o painel holográfico da tarefa (objetivo, execução ao vivo, estado)."""
    now = time.time()
    if now - hud_state.get("foreign_t", 0) < 90:         # há uma apresentação explícita no palco: não sobrescreve
        return
    if not force and now - hud_state["last"] < 0.9:
        return
    hud_state["last"] = now
    spec = {"kind": "ui", "titulo": hud_state["titulo"][:40] or "Tarefa", "barra": ["Prometheus", "Tarefa", "Execução"],
            "lateral": [], "tamanho": "normal", "ttl": 900,
            "paineis": [
                {"titulo": "Objetivo", "tipo": "lista", "itens": _wrap_obj(hud_state["titulo"])},
                {"titulo": "Execução ao vivo", "tipo": "terminal", "linhas": hud_state["steps"][-7:]},
                {"titulo": "Estado", "tipo": "kpis", "itens": [{"rotulo": "passos", "valor": str(hud_state["n"])},
                                                                {"rotulo": "estado", "valor": estado}]}]}
    await broadcast({"type": "holo", "op": "update" if hud_state["active"] else "show", "spec": spec})
    hud_state["active"] = True


async def hud_step(linha):
    hud_state["steps"].append(re.sub(r"\s+", " ", str(linha))[:46])
    hud_state["n"] += 1
    if hud_state["clear_task"]:
        hud_state["clear_task"].cancel(); hud_state["clear_task"] = None
    await hud_push()


async def hud_begin(titulo):
    hud_state.update(steps=[], titulo=str(titulo or "")[:120], t0=time.time(), n=0, active=False)


async def hud_end(ok=True, hold=7.0):
    if not hud_state["active"]:
        return
    await hud_push("concluído" if ok else "falhou", force=True)

    async def _clear():
        try:
            await asyncio.sleep(hold)
            hud_state["active"] = False
            await broadcast({"type": "holo", "op": "clear", "spec": None})
        except asyncio.CancelledError:
            pass
    hud_state["clear_task"] = asyncio.create_task(_clear())
# =====================================================================================================

AGENDA_HINT = re.compile(r"\b(hoje|amanh[ãa]|depois de amanh[ãa]|segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|semana que vem|"
                         r"[àa]s? \d{1,2}\s*(h|:|horas)|\d{1,2}\s*h\b|\d{1,2}/\d{1,2}|reuni[ãa]o|consulta|compromisso|prazo|agendar|marcar|marcado|"
                         r"lembr[ae]|entrega|vencimento|pagar|ligar para|call|visita)\b", re.I)
agenda_state = {"last_extract": 0.0}


async def extract_agenda(txt: str, origem: str = "ambiente"):
    if re.match(r"^\W*(sexta[\s-]*feira[,!. ]*)?(abr[aeio]|pesquis|mostr|fa[çc]a|v[áa] |entre|ligue|toque|feche|procure|busque|clique|digite|navegue|acesse|use |marque|agende|anote|crie|adicione|coloque|lembre|me lembre|qual|o que|quais|limp[ae]|apag[ae]|exclu[ir]|cancel[ae]|remov[ae]|desativ[ae]|deslig[ue]|tir[ae])", txt or "", re.I):
        return                                                  # ordem para a assistente, não compromisso
    """escuta o que foi dito e, se houver compromisso com data/hora, grava na agenda (decisão autônoma)."""
    if ops is None or len(txt.split()) < 4 or not AGENDA_HINT.search(txt):
        return
    if time.time() - agenda_state["last_extract"] < 5:
        return
    agenda_state["last_extract"] = time.time()
    d = await llm_json(
        "Extraia compromissos/tarefas com data ou hora da fala abaixo (transcrição automática, pode ter erros). Só inclua se for algo "
        "REAL que a pessoa vai fazer/atender (reunião, consulta, prazo, tarefa, lembrete); ignore hipóteses, passado e conversa casual. "
        f"Agora é {time.strftime('%A, %Y-%m-%d %H:%M')}. Resolva datas relativas. Se não houver hora, use 09:00.\n"
        f'Fala: "{txt}"\n'
        'Responda SÓ JSON: {"itens":[{"titulo":"curto","quando":"YYYY-MM-DD HH:MM","tipo":"reuniao|consulta|tarefa|lembrete|prazo|compromisso",'
        '"local":"","com":""}]} (lista vazia se nada)')
    if not d or not isinstance(d.get("itens"), list):
        return
    novos = []
    for it in d["itens"][:3]:
        try:
            aid, msg = await asyncio.to_thread(ops.agenda_add, str(it.get("titulo", "")), str(it.get("quando", "")),
                                               str(it.get("tipo", "compromisso")), 60, str(it.get("local", "")), str(it.get("com", "")),
                                               "", origem)
        except Exception:
            continue
        if aid and msg == "ok":
            novos.append(f"{it.get('titulo')} — {it.get('quando')}")
    if novos:
        txt_ok = "[AGENDA] Anotei na agenda: " + "; ".join(novos)
        await broadcast({"type": "text", "role": "assistant", "text": txt_ok})
        log_turn("prometheus", txt_ok)


async def agenda_tick():
    """lembretes no horário (voz se você está aqui, senão ping no celular) e resumo do dia."""
    if ops is None:
        return
    now = time.time()
    present = now - scene["t"] < 60
    for it in await asyncio.to_thread(ops.agenda_due_reminders):
        faltam = int((it["inicio"] - now) / 60)
        quando = f"em {faltam} minutos" if faltam > 1 else "agora"
        msg = f"Lembrete: {it['titulo']} {quando}" + (f", em {it['local']}" if it.get("local") else "") + "."
        ops.agenda_mark(it["id"], avisado=True)
        await broadcast({"type": "text", "role": "assistant", "text": "[LEMBRETE] " + msg})
        log_turn("prometheus", msg)
        if present and not speaking and state["state"] == "idle":
            await speak(msg); conv["t"] = time.time()
        else:
            await asyncio.to_thread(ops.gated, "notify.me", "dono", "lembrete de agenda", {"texto": "Prometheus: " + msg})
    # resumo do dia: 1x por dia, na primeira presença entre 06:00 e 12:00
    hoje = time.strftime("%Y-%m-%d")
    h = time.localtime(now).tm_hour
    try:                                            # resumo falado automático: só se o dono ativar ("resumo_automatico": true em memory/friday.json)
        _resumo_on = bool(json.load(open(os.path.join(MEM_DIR, "friday.json"))).get("resumo_automatico", False))
    except Exception:
        _resumo_on = False
    if _resumo_on and present and 6 <= h < 12 and mem.get("resumo_dia") != hoje and not speaking and state["state"] == "idle" \
            and now - max(conv["t"], 0) > 15:
        mem["resumo_dia"] = hoje; save_mem()
        lt = time.localtime(now)
        ini0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        itens = await asyncio.to_thread(ops.agenda_list, 1, ini0)
        tarefas = [t for t in ops.tasks() if t["estado"] == "pendente"][:3]
        partes = []
        if itens:
            partes.append("Hoje você tem: " + "; ".join(f"{time.strftime('%H:%M', time.localtime(i['inicio']))} {i['titulo']}" for i in itens[:5]) + ".")
        else:
            partes.append("Sua agenda de hoje está livre.")
        if tarefas:
            partes.append("Tarefas na fila: " + "; ".join(t["texto"][:50] for t in tarefas) + ".")
        msg = "Bom dia! " + " ".join(partes)
        await broadcast({"type": "text", "role": "assistant", "text": msg})
        log_turn("prometheus", msg)
        await speak(msg); conv["t"] = time.time()

APROVA_RE = re.compile(r"\b(aprov(?:[oae]|ad[oa]|ar)|pode (?:enviar|mandar|fazer|ir|ser)|manda(?: ver| bala)?|envi[ae](?: para \w+)?|autoriz\w*|confirm\w*|pode ser|com certeza|sim\b)", re.I)
PULA_RE = re.compile(
    r'\b(?:pul[ae]r?|cancel\w*|abort\w*|descart\w*|ignor\w*|deixa\s+pra\s+l[áa]|esquece|rejeit\w*|neg[ao]|negad[oa])\b'
    r'|'
    r'\b(?:entendeu\s+errado|n[ãa]o\s+(?:[ée]|era)\s+isso|para\s+com\s+isso|para\s+a\s+tarefa|n[ãa]o\s+(?:envia|manda|faz|quero|precisa))\b',
    re.I
)
REJEITA_RE = PULA_RE


def _palavras_sem_nome(txt):
    return re.findall(r"\w+", fr.NAME_RE.sub(" ", txt or "") if fr is not None else (txt or ""))


def _aprova(txt):
    """APROVA_RE só vale em frase curta (até 4 palavras sem o nome dela): "aprova e manda o relatório pro João" não aprova."""
    return len(_palavras_sem_nome(txt)) <= 4 and bool(APROVA_RE.search(txt or ""))


_SO_APROVA_OK = {"sim", "ok", "entao", "então", "por", "favor", "isso", "pode", "ta", "tá", "beleza", "certo", "agora", "a", "o", "e"}


def _so_aprovacao(txt):
    """a frase é SÓ aprovação explícita (não um "sim" solto nem "confirma o horário ...")."""
    t = fr.NAME_RE.sub(" ", txt or "") if fr is not None else (txt or "")
    if not any(m.lower() not in ("sim", "pode ser", "com certeza") for m in APROVA_RE.findall(t)):
        return False
    resto = re.sub(r"(?:" + APROVA_RE.pattern + r")\w*", " ", t, flags=re.I)      # \w*: "aprova|do" sai inteiro
    return all(w.lower() in _SO_APROVA_OK for w in re.findall(r"\w+", resto))


def _voz_verificada(janela=20.0):
    """última fala passou com faixa "plena" do TitaNet (perfil pronto) há pouco."""
    return _voz_ult["faixa"] == "plena" and _voz_ult["titanet"] and time.time() - _voz_ult["t"] < janela

_esperando_modificacao = {"aid": None, "t": 0.0}

def extrair_alteracao(txt):
    t_clean = (txt or "").strip()
    if ":" in t_clean:
        prefix, content = t_clean.split(":", 1)
        if any(w in prefix.lower() for w in ("modifi", "alter", "mud", "troc", "corri", "ajust", "reescrev", "coloc", "escrev", "adicion", "acrescent", "mensagem", "texto", "frase")):
            res = content.strip(' \"\'.,!?')
            if res:
                return res
    m = re.search(r'\b(?:modifi\w*|alter\w*|mud\w*|troc\w*|corri\w*|ajust\w*|reescrev\w*|coloc\w*|escrev\w*|adicion\w*|acrescent\w*)\b.*?\b(?:para|pra|por|com|assim|dizendo|falando)\s+(?:que\s+|a\s+frase\s+)?(.+)$', t_clean, re.I)
    if m:
        return m.group(1).strip(' \"\'.,!?')
    m2 = re.search(r'\b(?:coloque|coloca|escreve|mande|manda|envie|envia)\s+que\s+(.+)$', t_clean, re.I)
    if m2:
        return m2.group(1).strip(' \"\'.,!?')
    rx3 = re.compile(r'\b(?:n[ãa]o\s+(?:[ée]\s+isso|era\s+isso)|n[ãa]o)[,:\s]+(?:escrev\w*|coloc\w*|manda\s+dizendo|diz)\b[:\s]+(.+)$', re.I)
    m3 = rx3.search(t_clean)
    if m3:
        return m3.group(1).strip(' \"\'.,!?')
    return None

def quer_modificar_sem_texto(txt):
    """Detecta se o usuário pediu para modificar/corrigir/alterar a mensagem mas ainda não disse o novo texto."""
    return bool(re.search(
        r'\b(?:modifi\w*|alter\w*|mud\w*|troc\w*|corri\w*|ajust\w*)\b.*?\b(?:a\s+)?(?:mensagem|texto|o\s+que\s+est[áa]\s+escrito|o\s+rascunho)\b'
        r'|^\s*(?:modifi\w*|alter\w*|corri\w*|quero\s+mudar|mudar\s+mensagem|trocar\s+mensagem)\s*$',
        (txt or "").strip(), re.I
    ))

task_state = {"running": None, "inbox_seen": set(), "last_phone_poll": 0.0}


_announce_lock = asyncio.Lock()


async def announce_approvals():
    """avisa o dono (voz se está presente; senão ping no celular) sobre aprovações novas."""
    if ops is None or _announce_lock.locked():
        return
    async with _announce_lock:
        await _announce_approvals_impl()


def _item_aprovacao(it):
    """aprovação no formato do contrato do app (ITEM)."""
    a = str(it.get("acao", ""))
    p = it.get("payload") if isinstance(it.get("payload"), dict) else {}
    tx = {"wa.send_chat": p.get("texto"), "sudo.run": p.get("comando"), "mail.send": p.get("body")}.get(a)
    return {"id": str(it.get("id", "")), "acao": a, "destino": str(it.get("destino") or ""), "resumo": str(it.get("resumo") or ""),
            "texto": str(tx if tx else (it.get("resumo") or "")), "editavel": a == "wa.send_chat", "criado": float(it.get("criado") or 0)}


def _aprovacoes_pendentes():
    return [_item_aprovacao(i) for i in ops.approvals() if i.get("estado") == "pendente"] if ops is not None else []


async def _announce_approvals_impl():
    items = ops.approvals()
    changed = False
    for it in items:
        if it["estado"] == "pendente" and not it.get("anunciado"):
            it["anunciado"] = True; changed = True
            ops._save_appr(items)                       # grava ANTES de falar (evita aviso duplicado)
            txt = f"Preciso da sua aprovação: {it['resumo']}. Diga 'aprovado' para enviar, 'modifica para...' para corrigir, ou 'pula' para cancelar."
            await broadcast({"type": "aprovacao", "item": _item_aprovacao(it)})      # app: cartão com aprovar/cancelar/alterar
            if it["acao"] == "wa.send_chat":
                hud_state["foreign_t"] = time.time() + 300
                hud_state["active"] = False
                await broadcast({
                    "type": "holo",
                    "op": "show",
                    "spec": {
                        "kind": "email",
                        "para": f"WhatsApp · {it['destino']}",
                        "assunto": "Mensagem Pendente",
                        "corpo": it.get("payload", {}).get("texto", it.get("resumo", "")),
                        "status": "aguardando aprovação",
                        "titulo": "WhatsApp — Mensagem",
                        "instant": True,
                        "ttl": 300
                    }
                })
            elif it["acao"] == "mail.send":
                hud_state["foreign_t"] = time.time() + 300
                hud_state["active"] = False
                await broadcast({
                    "type": "holo",
                    "op": "show",
                    "spec": {
                        "kind": "email",
                        "para": str(it["destino"]),
                        "assunto": it.get("payload", {}).get("subject", "E-mail"),
                        "corpo": it.get("payload", {}).get("body", it.get("resumo", "")),
                        "status": "aguardando aprovação",
                        "titulo": "Novo E-mail",
                        "instant": True,
                        "ttl": 300
                    }
                })
            await broadcast({"type": "text", "role": "assistant", "text": txt})
            log_turn("prometheus", txt)
            if time.time() - scene["t"] < 30 and not speaking:
                await speak(txt); conv["t"] = time.time()
            else:
                await asyncio.to_thread(ops.gated, "notify.me", "dono", "aviso de aprovação pendente", {"texto": "Prometheus: aprovação pendente — " + it["resumo"][:90]})
    if changed:
        ops._save_appr(items)


oferta = {"tarefa": "", "t": 0.0, "feitas": []}     # tarefa que a mente ofereceu e aguarda "sim"/"não" (90 s)
ACEITA_RE = re.compile(r"^\W*(?:sexta[\s-]*feira\W*)?(sim|pode|faz|fa[çc]a|quero|claro|bora|manda ver|beleza|por favor|ok)\b", re.I)


async def _eco_usuario(txt):
    """mensagem DIGITADA que virou resposta de aprovação/oferta: aparece no chat e no histórico como fala do dono."""
    conv["t"] = time.time()
    await broadcast({"type": "text", "role": "user", "text": txt, "files": []})
    log_turn("usuario", txt)


async def handle_offer_speech(txt: str, eco: bool = False) -> bool:
    """resposta curta a uma oferta proativa: sim -> executa a tarefa; não -> descarta. True = consumiu a fala.
    eco=True: veio digitada (ask) -> mostra a mensagem do dono no chat antes de responder."""
    if not oferta["tarefa"] or time.time() - oferta["t"] > 90 or len(txt.split()) > 8:
        return False
    tarefa, oferta["tarefa"] = oferta["tarefa"], ""
    if PULA_RE.search(txt) or re.match(r"^\W*n[ãa]o\b", txt, re.I):
        if eco:
            await _eco_usuario(txt)
        await speak("Tudo bem, descartei."); conv["t"] = time.time(); return True
    if ACEITA_RE.search(txt) or _aprova(txt):
        if eco:
            await _eco_usuario(txt)
        asyncio.create_task(friday_ask(tarefa)); return True
    oferta["tarefa"] = tarefa                         # não era resposta à oferta: mantém até expirar
    return False


async def resolver_aprovacao(aid, decisao, texto=None, origem="voz"):
    """ponto ÚNICO de resolução (voz, chat digitado e app). decisao: aprovar|cancelar|alterar.
    Publica 'aprovacao_fim' (aprovar/cancelar) ou 'aprovacao' (alterar). Fala a confirmação só se origem != 'app'.
    Devolve (ok, msg, item|None)."""
    if ops is None:
        return False, "aprovações indisponíveis", None
    it = next((i for i in ops.approvals() if i.get("id") == aid and i.get("estado") == "pendente"), None)
    if it is None:
        return False, "aprovação não encontrada ou já resolvida", None
    if decisao == "alterar":
        novo = str(texto or "").strip()[:2000]
        if it["acao"] not in ("wa.send_chat", "mail.send"):
            return False, "só mensagens e e-mails podem ser alterados", _item_aprovacao(it)
        if not novo:
            return False, "texto vazio", _item_aprovacao(it)
        items = ops.approvals()
        for i in items:
            if i["id"] == aid:
                if i["acao"] == "wa.send_chat":
                    i["payload"]["texto"] = novo
                    i["resumo"] = f"enviar para {i['destino']}: {novo[:100]}"
                elif i["acao"] == "mail.send":
                    i["payload"]["body"] = novo
                    i["resumo"] = f"enviar e-mail para {i['destino']}: {novo[:100]}"
                it = i
        ops._save_appr(items)
        hud_state["foreign_t"] = time.time() + 300
        hud_state["active"] = False
        await broadcast({
            "type": "holo",
            "op": "show",
            "spec": {
                "kind": "email",
                "para": ("WhatsApp · " if it["acao"] == "wa.send_chat" else "") + str(it.get("destino", "")),
                "assunto": "Mensagem (Corrigida)" if it["acao"] == "wa.send_chat" else "E-mail (Corrigido)",
                "corpo": novo,
                "status": "corrigida · diga aprovado",
                "titulo": "WhatsApp — Mensagem Atualizada" if it["acao"] == "wa.send_chat" else "Novo E-mail Atualizado",
                "instant": True,
                "ttl": 300
            }
        })
        item = _item_aprovacao(it)
        await broadcast({"type": "aprovacao", "item": item})
        ok, resp = True, f"Mensagem corrigida no espelho: {novo[:90]}. Diga aprovado para enviar, ou modifica de novo."
    elif decisao == "cancelar":
        ok, msg = await asyncio.to_thread(ops.resolve, aid, False)
        if not ok:
            return False, msg, None
        resp = "Certo, pulei essa tarefa."
        if it["acao"] == "self.apply":
            await _aprimorar_cli("descartar", it["payload"]["id"], timeout=60)
        item = None
        hud_state["foreign_t"] = 0
        hud_state["active"] = False
        await broadcast({"type": "aprovacao_fim", "id": aid, "estado": "rejeitada", "msg": resp})
        await broadcast({"type": "holo", "op": "clear", "spec": None})
    elif decisao == "aprovar":
        ok, msg = await asyncio.to_thread(ops.resolve, aid, True)
        dest_nome = str(it.get("destino") or "destinatário")
        if not ok and "não encontrada" in str(msg):      # corrida (app + voz): a outra resolução já executou -> não reenvia nem marca "falhou"
            return False, "Essa aprovação já foi resolvida.", None
        _retentar = not ok and it["acao"] != "self.apply" and not it["acao"].startswith("wa.")   # WhatsApp não repete sozinho: reenvio virou loop
        resp = ("Aplicado. Passa a valer quando reiniciar o daemon." if it["acao"] == "self.apply" else f"Feito, enviei a mensagem para {dest_nome}.") if ok \
            else (f"Ainda não enviei para {dest_nome}: a primeira tentativa falhou. Vou tentar de novo em 30 segundos e te aviso." if _retentar
                  else (f"Não enviei para {dest_nome}: {str(msg)[:160]}. Não repito sozinha para não duplicar; peça de novo quando quiser." if it["acao"].startswith("wa.") else "Não consegui aplicar essa mudança."))   # nunca o erro cru (URLError...)
        if _retentar:
            asyncio.create_task(_retentar_aprovacao(it, dest_nome, msg))
        item = None
        hud_state["foreign_t"] = time.time() + 6
        hud_state["active"] = False
        await broadcast({"type": "aprovacao_fim", "id": aid, "estado": "aprovada" if ok else ("tentando" if _retentar else "falhou"), "msg": resp})
        await broadcast({
            "type": "holo",
            "op": "show",
            "spec": {
                "kind": "email",
                "para": ("WhatsApp · " if it["acao"] == "wa.send_chat" else "") + dest_nome,
                "assunto": "Mensagem " + ("Enviada" if ok else "Falhou"),
                "corpo": str(it.get("payload", {}).get("texto") or it.get("payload", {}).get("body", "")),
                "status": "enviado" if ok else ("tentando de novo" if _retentar else "falhou"),
                "titulo": "WhatsApp — Mensagem",
                "instant": True,
                "ttl": 6
            }
        })
    else:
        return False, "decisão inválida", None
    if origem == "app":
        log_turn("prometheus", resp)                  # pelo app basta o evento; fica no histórico
    else:
        await broadcast({"type": "text", "role": "assistant", "text": resp})
        log_turn("prometheus", resp); await speak(resp); conv["t"] = time.time()
    return ok, resp, item


async def _retentar_aprovacao(it, dest_nome, erro, intervalo=30, limite=300):
    """aprovação que falhou ao executar (rede, WhatsApp fechado...): tenta de novo a cada 30 s por até 5 min; só então avisa."""
    t0, n = time.time(), 1
    while time.time() - t0 < limite:
        await asyncio.sleep(intervalo)
        n += 1
        try:
            ok, msg = await asyncio.to_thread(ops._execute, it["acao"], it["payload"])
        except Exception as e:
            ok, msg = False, repr(e)
        if ok:
            break
        erro = msg
        if str(msg).startswith("enviei "):           # parte já saiu: repetir duplicaria as partes enviadas
            ok = False
            break
    else:
        ok = False
    try:
        items = ops.approvals()
        for i in items:
            if i["id"] == it["id"]:
                i["estado"], i["resultado"] = ("executada" if ok else "falhou"), str(msg if ok else erro)[:200]
        ops._save_appr(items)
        ops.audit(it["acao"], it["destino"], it["resumo"], f"retentativa {n}x→{'ok' if ok else 'falhou'}: {str(msg if ok else erro)[:120]}", "dono")
    except Exception as e:
        print("retentativa de aprovação:", e, flush=True)
    resp = f"Pronto, enviei a mensagem para {dest_nome}." if ok else f"Não consegui enviar para {dest_nome}: {str(erro)[:140]}"
    await broadcast({"type": "aprovacao_fim", "id": it["id"], "estado": "aprovada" if ok else "falhou", "msg": resp})
    await broadcast({"type": "text", "role": "assistant", "text": resp})
    log_turn("prometheus", resp); await speak(resp)


def _pend_recentes(pend):
    """pendências dos últimos 30 min (as velhas não disputam o 'aprovado'); sem nenhuma recente, todas."""
    rec = [i for i in pend if time.time() - float(i.get("criado", 0)) < 1800]
    return rec or pend


def _alvo_pendencia(pend, txt):
    """qual pendência a fala resolve: a única recente, ou a cujo destino aparece na fala ("aprova a da Gilda"). None = ambíguo."""
    rec = _pend_recentes(pend)
    if len(rec) == 1:
        return rec[0]
    def _n(x):
        return unicodedata.normalize("NFD", str(x or "")).encode("ascii", "ignore").decode().lower()
    fala = _n(txt)
    citadas = [i for i in rec if i.get("destino") and any(w in fala for w in _n(i["destino"]).split() if len(w) >= 3)]
    if len(citadas) == 1:
        return citadas[0]
    return None


async def handle_approval_speech(txt: str, eco: bool = False) -> bool:
    """se há aprovação pendente e a fala é sim/não/altera/pula, resolve. True = consumiu a fala."""
    if ops is None or (_DESLIGA["t"] and time.time() - _DESLIGA["t"] < 20):   # "confirmo" do desligar vai para o handle_modes
        return False
    pend = [i for i in ops.approvals() if i["estado"] == "pendente"]
    if not pend:
        if _aprova(txt) and _so_aprovacao(txt) and not _ha_pendente(45):   # "aprovado" sem nada pendente: avisa, não vai p/ o think
            if eco:
                await _eco_usuario(txt)
            await speak("Não tem nada esperando aprovação."); conv["t"] = time.time()
            return True
        return False
    t = txt.lower()
    alvo = _alvo_pendencia(pend, txt)
    if alvo is None:                                 # várias pendências e a fala não diz qual: pergunta (antes resolvia a última)
        if not (_aprova(txt) or PULA_RE.search(t) or extrair_alteracao(txt) or quer_modificar_sem_texto(txt)):
            return False
        if eco:
            await _eco_usuario(txt)
        nomes = [str(i.get("destino") or i.get("acao")) for i in _pend_recentes(pend)][-3:]
        await speak("Tenho mais de uma esperando: " + ", ".join(nomes) + ". Qual delas? Diga, por exemplo, aprova a do " + nomes[-1] + ".")
        return True

    # Estado interativo: usuário pediu para modificar e agora está ditando o novo texto
    if _esperando_modificacao.get("aid") and time.time() - _esperando_modificacao.get("t", 0) < 60:
        aid_mod = _esperando_modificacao["aid"]
        _esperando_modificacao["aid"] = None
        if PULA_RE.search(t):
            await resolver_aprovacao(aid_mod, "cancelar", origem="chat" if eco else "voz")
            return True
        novo_txt = txt.strip().strip(' \"\'.,!?')
        if eco:
            await _eco_usuario(txt)
        await resolver_aprovacao(aid_mod, "alterar", novo_txt, origem="chat" if eco else "voz")
        return True

    novo = extrair_alteracao(txt)
    if novo and alvo["acao"] in ("wa.send_chat", "mail.send"):
        decisao = "alterar"
    elif quer_modificar_sem_texto(txt) and alvo["acao"] in ("wa.send_chat", "mail.send"):
        _esperando_modificacao["aid"] = alvo["id"]
        _esperando_modificacao["t"] = time.time()
        if eco:
            await _eco_usuario(txt)
        await speak("O que você deseja que eu escreva na mensagem, senhor?")
        return True
    elif eco and len(txt.split()) > 8:
        return False
    elif PULA_RE.search(t):
        decisao, novo = "cancelar", None
    elif _aprova(txt):
        decisao, novo = "aprovar", None
    else:
        return False                                 # frase longa (ex.: "aprova e abre o navegador"): a aprovação continua pendente
    if decisao == "aprovar" and not eco and _origem_fala.get() != "app" and not _voz_verificada():
        voz.log(f"aprovação por voz recusada: faixa={_voz_ult['faixa']} score={_voz_ult['score']:.2f} -> {txt[:40]!r}")
        await speak("Para aprovar, preciso reconhecer sua voz. Fala de novo, ou aprova pelo app.")
        return True
    if eco:
        await _eco_usuario(txt)
    await resolver_aprovacao(alvo["id"], decisao, novo, origem="chat" if eco else "voz")
    return True


async def handle_skip_speech(txt: str) -> bool:
    """trata comandos para pular tarefas, abortar ações ou corrigir entendimentos errados."""
    t = txt.lower()
    if not PULA_RE.search(t):
        return False
    # 1. Se há aprovação pendente: cancela
    if ops is not None:
        pend = [i for i in ops.approvals() if i["estado"] == "pendente"]
        if pend:
            await resolver_aprovacao(pend[-1]["id"], "cancelar", origem="voz")
            return True
    # 2. Se há oferta pendente: descarta
    if oferta.get("tarefa"):
        oferta["tarefa"] = ""
        await speak("Tudo bem, descartei essa tarefa.")
        return True
    # 3. Interrompe planos e tarefas do agente em execução ou em fila
    try:
        import plano as _pl
        _pl.SKIP.set()
    except Exception:
        pass

    cancelou_algo = False
    if task_state.get("running"):
        tid = task_state["running"]
        task_state["running"] = None
        if ops is not None:
            ops.task_finish(tid, "cancelada pelo usuário", False)
        cancelou_algo = True

    if agente_ativo[0] or fila_tarefas:
        fila_tarefas.clear()
        cancel_all()
        cancelou_algo = True

    await hud_end(False)
    await broadcast({"type": "holo", "op": "clear", "spec": None})
    if cancelou_algo:
        await speak("Certo, cancelei a tarefa que foi compreendida errado e limpei a fila.")
    else:
        await speak("Entendido, pulei essa etapa.")
    return True


async def run_task(task):
    """executa uma tarefa autônoma com o Claude (acesso total, regido pela política via `prom`)."""
    task_state["running"] = task["id"]
    ops.task_set(task["id"], estado="executando")
    await broadcast({"type": "text", "role": "tool", "text": "tarefa: " + task["texto"][:70]})
    prompt = (persona() + "\n\n[TAREFA AUTÔNOMA — execute sozinho, sem pedir confirmação, exceto onde a política (comando `prom`) exigir "
              "aprovação. Ao terminar, responda com um relato curto em pt-BR: o que fez, resultado e pendências.]\n"
              f"TAREFA: {task['texto']}")
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", MODEL, "--effort", EFFORT_TASK]
    if PERMISSION:
        cmd += ["--permission-mode", PERMISSION]
    cwd = task.get("pasta") or os.path.expanduser("~")
    await hud_begin(task["texto"])
    await hud_push("iniciando", force=True)
    res, ok = "", False
    try:
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                 limit=1 << 24, cwd=cwd, env=_gui_env())

        async def _read():
            nonlocal res
            async for raw in p.stdout:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if dev is not None:
                    dev.claude(ev)
                if ev.get("type") == "assistant":
                    for bl in ev["message"].get("content", []):
                        if bl.get("type") == "tool_use":
                            inp = bl.get("input", {})
                            await hud_step(f"{bl['name']}: {inp.get('command') or inp.get('file_path') or inp.get('pattern') or ''}")
                        elif bl.get("type") == "text" and bl["text"].strip():
                            res = bl["text"].strip()
                elif ev.get("type") == "result" and ev.get("result"):
                    res = str(ev["result"]).strip()
        await asyncio.wait_for(_read(), 1800)
        await p.wait()
        ok = p.returncode == 0 and bool(res)
    except Exception as e:
        res, ok = f"erro: {e!r}", False
        try:
            p.kill()
        except Exception:
            pass
    await hud_end(ok)
    ops.task_finish(task["id"], res, ok)
    ops.audit("task.run", "", task["texto"], ("ok: " if ok else "falhou: ") + res[:120])
    task_state["running"] = None
    resumo = (res.split("\n")[0] if res else "sem resultado")[:220]
    msg = ("Terminei a tarefa: " if ok else "Não consegui concluir a tarefa: ") + task["texto"][:60] + ". " + resumo
    await broadcast({"type": "text", "role": "assistant", "text": msg})
    log_turn("prometheus", msg)
    if time.time() - scene["t"] < 30 and not speaking and state["state"] == "idle":
        await speak(msg[:260])
    else:
        await asyncio.to_thread(ops.gated, "notify.me", "dono", "resultado de tarefa", {"texto": "Prometheus: " + msg[:140]})


async def poll_phone_messages():
    """mensagens novas no celular (apps de conversa) viram um pensamento da mente — ela decide avisar/propor resposta."""
    if ops is None:
        return
    if not await asyncio.to_thread(ops.phone_reachable):
        return
    notifs = await asyncio.to_thread(ops.phone_notifs)
    primed = task_state.get("primed", False)
    task_state["primed"] = True            # 1ª leitura só "marca como vistas" (não age sobre mensagens antigas)
    novas = []
    for n in notifs:
        key = f"{n.get('app')}|{n.get('titulo')}|{n.get('texto')}"
        if key in task_state["inbox_seen"]:
            continue
        task_state["inbox_seen"].add(key)
        if re.search(r"whatsapp|telegram|signal|messag|sms|mensag", n.get("app") or "", re.I) and (n.get("titulo") or n.get("texto")):
            novas.append(n)
    if len(task_state["inbox_seen"]) > 400:
        task_state["inbox_seen"] = set(list(task_state["inbox_seen"])[-200:])
    if novas and primed:
        resumo = "; ".join(f"[{n['id']}] {n.get('app')}: {n.get('titulo')}: {(n.get('texto') or '')[:120]}"
                           f"{' (dá para responder)' if n.get('responder') else ''}" for n in novas[:4])
        await mind_think("chegaram mensagens no celular do dono",
                         "MENSAGENS: " + resumo + "\nSe fizer sentido responder, use acao=\"responder\" com id (entre colchetes) e texto; "
                         "o envio passa por aprovação do dono salvo regra permanente. Senão, avise o dono em uma frase ou não faça nada.")



ZAP_CFG = os.path.join(MEM_DIR, "zap.json") if "MEM_DIR" in globals() else os.path.join(ROOT, "memory", "zap.json")
zap_state = {"seen": set(), "primed": False, "last_launch": 0.0, "last_poll": 0.0, "last_suggest": {}}


def zap_cfg():
    d = {"ativo": True, "auto_launch": True, "ignorar": [], "sugerir_respostas": True, "intervalo_s": 25,
         "contato_comando": "Integra Code", "contato_seguranca": "Integra Code", "nome_dono": "Integra Code"}
    try:
        d.update(json.load(open(ZAP_CFG)))
    except Exception:
        try:
            json.dump(d, open(ZAP_CFG, "w"), indent=1, ensure_ascii=False)
        except Exception:
            pass
    return d


async def zap_tick():
    """analista de WhatsApp em segundo plano: detecta mensagens novas (só pela lista: não gera 'visto'), resume,
    avalia urgência e, se precisar responder, propõe resposta (envio sempre passa pela política/aprovação)."""
    if zapmod is None or ops is None:
        return
    cfg = zap_cfg()
    now = time.time()
    if not cfg.get("ativo") or now - zap_state["last_poll"] < cfg.get("intervalo_s", 25):
        return
    zap_state["last_poll"] = now
    if not await asyncio.to_thread(zapmod.available):
        if cfg.get("auto_launch") and now - zap_state["last_launch"] > 600:
            zap_state["last_launch"] = now
            await asyncio.to_thread(zapmod.launch)
        return
    snap = await asyncio.to_thread(zapmod.snapshot)
    if not snap.get("ok"):
        return
    novas = []
    for c in snap["chats"]:
        sig = f"{c['nome']}|{c['previa']}|{c['nao_lidas']}"
        if sig in zap_state["seen"]:
            continue
        zap_state["seen"].add(sig)
        if zap_state["primed"] and c["nao_lidas"] > 0 and not c.get("silenciada") and c["nome"] not in cfg.get("ignorar", []):
            novas.append(c)
    if len(zap_state["seen"]) > 600:
        zap_state["seen"] = set(list(zap_state["seen"])[-300:])
    zap_state["primed"] = True            # 1ª leitura só registra o que já existia
    if novas:
        await zap_analyze(novas[:5], cfg)


zap_cmd = {"seen": set(), "primed": False, "last": 0.0, "busy": False, "wh": None}


def _zap_transcribe(path):
    """voz do WhatsApp -> texto (faster-whisper local, CPU; carrega só na 1ª vez)."""
    if zap_cmd["wh"] is None:
        from faster_whisper import WhisperModel
        zap_cmd["wh"] = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=3,
                                     download_root=os.path.join(ROOT, "models", "whisper"))
    import numpy as _np                                  # 19/10: decode_audio do faster-whisper quebra com o PyAV instalado (metadata_errors) -> ffmpeg
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-ar", "16000", "-ac", "1", "-f", "f32le", "-"],
                         capture_output=True, timeout=120).stdout
    segs, _ = zap_cmd["wh"].transcribe(_np.frombuffer(pcm, dtype="float32"), language="pt", vad_filter=True, beam_size=1)
    return " ".join(s_.text.strip() for s_ in segs).strip()


def _zap_cmd_work(chat, items):
    """executa (em thread) cada comando novo do dono e responde na própria conversa com o resultado."""
    import agent as _ag
    for it in items:
        txt = it["texto"]
        if it["audio"]:
            dest = os.path.join("/tmp", "friday-zap-%d.ogg" % int(time.time()))
            r = zapmod.fetch_audio(it["id"], dest)
            if not r.get("ok"):
                zapmod.send(chat, "[FRIDAY] Não consegui baixar seu áudio: " + str(r.get("motivo", ""))[:100]); continue
            try:
                txt = _zap_transcribe(dest)
            finally:
                try: os.remove(dest)
                except OSError: pass
            if not txt:
                zapmod.send(chat, "[FRIDAY] Não entendi o áudio, chefe. Pode repetir?"); continue
        ops.audit("zap.comando", chat, txt[:120], "recebido")
        try:
            lp = _main.get("loop")
            if lp is not None and (CONT_STOP.search(txt) or re.match(r"^\W*(?:sexta[\s-]*feira[,!. ]*)?(pare|parar|chega|cancela)\W*$", txt, re.I)):
                continuo_stop(); cancel_all()
                zapmod.send(chat, "[FRIDAY] Parei a tarefa contínua e o que estava fazendo."); continue
            if lp is not None and CONT_START.search(txt) and not re.search(r"\bmodo\b", txt, re.I):
                ok_c, msg_c = asyncio.run_coroutine_threadsafe(continuo_start(txt), lp).result(timeout=20)
                zapmod.send(chat, "[FRIDAY] " + msg_c + " Mando atualizações por aqui; diga 'pare a tarefa' para encerrar."); continue
            res = _ag.run(txt, _friday_ctx(), fr, ops, None)
            resp = res.get("fala") or "Feito."
        except Exception as e:
            resp = "Falhei ao executar: " + str(e)[:100]
        zapmod.send(chat, "[FRIDAY] Ouvi: “" + txt[:120] + "”\n" + resp[:600])
        ops.audit("zap.comando", chat, txt[:120], "respondido")


async def zap_cmd_tick():
    """comandos remotos: áudios/textos que o dono manda na conversa dele consigo mesmo (WhatsApp) viram tarefas; o resultado volta lá.
    Ativo desde a inicialização, mesmo em espera (sem câmera, voz ou interface)."""
    if zapmod is None or ops is None or fr is None or zap_cmd["busy"]:
        return
    cfg = zap_cfg()
    now = time.time()
    chat = cfg.get("contato_comando", "@Integra_Code")
    if not cfg.get("comandos_remotos", True) or now - zap_cmd["last"] < 10 or not await asyncio.to_thread(zapmod.available):
        return
    zap_cmd["last"] = now
    r = await asyncio.to_thread(zapmod.owner_msgs, chat, 12, cfg.get("numero_comando", "5514998537913"))
    if not r.get("ok"):
        return
    novos = [m for m in r["msgs"] if m["id"] not in zap_cmd["seen"]]
    zap_cmd["seen"].update(m["id"] for m in r["msgs"])
    if not zap_cmd["primed"]:
        zap_cmd["primed"] = True                       # 1ª leitura: só registra o histórico (nada antigo é executado)
        return
    novos = [m for m in novos if m["audio"] or re.match(r"^\s*(?:sexta|friday|f\.?r\.?i\.?d\.?a\.?y)\b", m["texto"], re.I)]   # texto só com o nome dela (anotações pessoais não viram comando)
    if not novos:
        return
    zap_cmd["busy"] = True
    _main["loop"] = asyncio.get_running_loop()

    def _go():
        try:
            _zap_cmd_work(chat, novos[:3])
        finally:
            zap_cmd["busy"] = False
    threading.Thread(target=_go, daemon=True, name="zap-cmd").start()


async def zap_analyze(chats, cfg):
    itens = [{"i": k, "conversa": c["nome"], "previa": c["previa"], "nao_lidas": c["nao_lidas"], "hora": c["hora"]} for k, c in enumerate(chats)]
    d = await llm_json(
        "Você é o analista de WhatsApp do assistente Prometheus; o dono é " + str(_nome_usuario() or "o usuário") + ". Abaixo, mensagens NOVAS "
        "(só a prévia da lista). Para cada uma: resumo de 1 linha, urgencia (0=ruído/automática, 1=normal, 2=urgente/pessoal importante), "
        "precisa_resposta (true só se uma pessoa espera resposta; false p/ grupos barulhentos, avisos, promoções, bots) e, se precisa, "
        "uma sugestao curta e natural de resposta em pt-BR no tom do dono (sem inventar fatos, horários ou compromissos; se faltar "
        "informação, a sugestão deve pedir um instante), confianca (0 a 1) de que a resposta é adequada e sensivel=true se envolver "
        "dinheiro, senhas/códigos, assunto jurídico/saúde, dados pessoais, novo compromisso ou decisão do dono. NÃO invente conteúdo além da prévia.\n"
        f"MENSAGENS: {json.dumps(itens, ensure_ascii=False)}\n"
        'Responda SÓ JSON: {"itens":[{"i":0,"resumo":"","urgencia":0,"precisa_resposta":false,"sugestao":"","confianca":0.0,"sensivel":false}]}')
    res = {r.get("i"): r for r in (d or {}).get("itens", []) if isinstance(r, dict)}
    now = time.time()
    present = now - scene["t"] < 60
    for k, c in enumerate(chats):
        r = res.get(k, {})
        urg = int(r.get("urgencia", 1) or 0)
        resumo = str(r.get("resumo") or c["previa"])[:160]
        linha = f"[WHATSAPP] {c['nome']}" + (f" ({c['nao_lidas']})" if c["nao_lidas"] > 1 else "") + f": {resumo}"
        await broadcast({"type": "text", "role": "assistant", "text": linha})
        log_turn("prometheus", linha)
        ops.audit("wa.analise", c["nome"], resumo, f"urgencia={urg}")
        if urg >= 2 and present and not speaking and state["state"] == "idle" and not busy.locked():
            await speak(f"Mensagem urgente de {c['nome']}: {resumo}"); conv["t"] = time.time()
        if r.get("precisa_resposta") and str(r.get("sugestao", "")).strip() and cfg.get("sugerir_respostas", True) and urg >= 1:
            if now - zap_state["last_suggest"].get(c["nome"], 0) > 600:
                zap_state["last_suggest"][c["nome"]] = now
                txt = str(r["sugestao"]).strip()[:400]
                resumo_ap = f"{c['nome']} disse: “{c.get('previa', '')[:90]}”. Responder: “{txt[:140]}”?"
                grupo = bool(re.match(r"^[^:]{1,30}: ", c.get("previa", "")))          # prévia "Fulano: ..." = grupo
                try:
                    conf = float(r.get("confianca", 0) or 0)
                except Exception:
                    conf = 0.0
                recentes = [t for t in zap_state.setdefault("auto_envios", []) if now - t < 3600]
                zap_state["auto_envios"] = recentes
                # padrão: SEMPRE pergunta antes de responder. Só envia sozinho se o dono ligar "auto_responder": true em memory/zap.json
                seguro = (cfg.get("auto_responder") is True) and (not r.get("sensivel")) and conf >= 0.7 and not grupo and len(recentes) < 8
                if seguro:      # autorização permanente do dono (memory/politica.json): responde sozinho; tudo é auditado
                    ok, msg = await asyncio.to_thread(ops.gated, "wa.send_chat", c["nome"], resumo_ap, {"nome": c["nome"], "texto": txt})
                    if ok:
                        zap_state["auto_envios"].append(now)
                        await broadcast({"type": "text", "role": "assistant", "text": f"[OK] Respondi {c['nome']}: {txt}"})
                        log_turn("prometheus", f"respondi {c['nome']}: {txt}")
                else:           # sensível / incerto / grupo / limite por hora: pergunta ao dono
                    await asyncio.to_thread(ops.request_approval, "wa.send_chat", c["nome"], resumo_ap, {"nome": c["nome"], "texto": txt})



friday_state = {"on": os.environ.get("FRIDAY_ON", "1") == "1", "last_cmd": 0.0}


async def friday_pose(pose, ttl=3200):
    await broadcast({"type": "friday_pose", "pose": pose, "ttl": ttl})


async def friday_set(on: bool, force: bool = False):
    """'Sexta-Feira, ligar!' / 'desligar!': mostra/oculta a assistente; liga/desliga câmera (microfone fica p/ ouvir o comando)."""
    global camera_on
    if friday_state["on"] == on and not force:
        return
    friday_state["on"] = on
    friday_state["last_cmd"] = time.time()
    _salva_sessao()
    if on:
        camera_on = True
        await broadcast({"type": "friday", "on": True})
        await broadcast({"type": "camera", "on": True})
        await asyncio.sleep(0.4)
        nome = mem.get("nome") or "chefe"
        await friday_pose("acenar", 3500)
        import random as _r
        _h = time.localtime().tm_hour
        _sd = "Bom dia" if 5 <= _h < 12 else "Boa tarde" if _h < 18 else "Boa noite"
        msg = _r.choice([f"{_sd}! Tô aqui, pode falar.", f"{_sd}, chefe. Tudo pronto por aqui.", "Oi! Voltei. No que a gente mexe hoje?",
                         f"{_sd}. Já tô te vendo e ouvindo, pode mandar."])
        await broadcast({"type": "text", "role": "assistant", "text": msg})
        log_turn("prometheus", msg)
        await speak(msg)
        await set_state("idle", "neutro")
    else:
        msg = "Entrando em espera. Se precisar, só me chamar: Sexta-Feira."
        await friday_pose("reverencia", 3000)
        await broadcast({"type": "text", "role": "assistant", "text": msg})
        log_turn("prometheus", msg)
        await speak(msg)
        await broadcast({"type": "holo", "op": "clear", "spec": None})
        camera_on = False
        await broadcast({"type": "camera", "on": False})
        await broadcast({"type": "friday", "on": False})
        await set_state("idle", "neutro")


def _friday_ctx():
    now = time.time()
    partes = [time.strftime("%A, %d/%m %H:%M")]
    try:                                         # o que está na tela: resolve "isso", "aí na tela", "essa música"
        _fw = json.loads(subprocess.run(["niri", "msg", "--json", "focused-window"], capture_output=True, text=True, timeout=2).stdout or "null")
        if _fw:
            partes.append(f"janela em foco: {_fw.get('app_id')} — {str(_fw.get('title'))[:90]}")
        _ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=2).stdout or "[]")
        partes.append("janelas abertas: " + "; ".join(f"{w.get('app_id')} — {str(w.get('title'))[:60]}" for w in _ws[:8]))
    except Exception:
        pass
    try:
        if ops is not None:
            ag = ops.agenda_list(1)[:3]
            if ag:
                partes.append("agenda: " + "; ".join(f"{time.strftime('%H:%M', time.localtime(i['inicio']))} {i['titulo']}" for i in ag))
        ws = fr._windows() if fr is not None else []
        if ws:
            partes.append("janelas abertas: " + ", ".join(sorted({(w.get('app_id') or '?').split('.')[-1] for w in ws})[:8]))
        fatos = mem.get("fatos", {})
        if fatos:
            partes.append("fatos que lembro: " + "; ".join(f"{k}={v}" for k, v in list(fatos.items())[:12]))
        if camera_on and now - scene["t"] < 4 and scene["faces"]:
            pres = [f"{f['nome']} (rosto reconhecido)" if f["nome"] else "pessoa desconhecida" for f in scene["faces"]]
            partes.append("Presentes em frente ao PC: " + ", ".join(pres))
        if camera_on and now - scene.get("t_amb_faces", 0) < 5 and scene.get("amb_faces"):
            pres_amb = [f"{f['nome']} ({f['lado']})" if f.get("nome") else f"outra pessoa ({f['lado']})" for f in scene["amb_faces"]]
            partes.append("Pessoas no ambiente: " + ", ".join(pres_amb))
        elif camera_on and scene.get("amb_pessoas") and now - scene["amb_pessoas"][0] < 8 and scene["amb_pessoas"][1]:
            n_p = len(scene["amb_pessoas"][1])
            partes.append(f"Pessoas detectadas no ambiente: {n_p}")
        if ptz is not None and ipcam is not None:
            partes.append("câmera do quarto com motor: " + ptz.get_ptz().estado())
        if current_speaker.get("nome") and now - last_voice.get("t", 0) < 30:
            partes.append(f"voz reconhecida: {current_speaker['nome']} (confiança {last_voice.get('sim', 0):.2f})")
        if mem.get("conversas"):
            partes.append(f"já conversamos {mem.get('turnos', 0)} vezes")
        rs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "memory", "resumo.md")
        if os.path.exists(rs):
            linhas = [l.strip("- ").strip() for l in open(rs).read().splitlines() if l.startswith("- ")]
            partes.append("memória longa: " + " ".join(l[:140] for l in linhas[:5]))
    except Exception:
        pass
    return " | ".join(partes)


def _friday_history(n=6):
    h = []
    try:
        linhas = open(LOG_FILE).read().splitlines()[-n*3:]
        for l in linhas:
            d = json.loads(l)
            txt = d.get("text", "")
            if d.get("role") != "usuario":
                if any(bad in txt for bad in ("FALHOU", "Não consegui fechar a tarefa", "Você tem a mão levantada")):
                    continue
            h.append({"role": "user" if d["role"] == "usuario" else "assistant", "content": txt[:300]})
    except Exception:
        pass
    return h[-n:]


def _rot_ctx():
    """F6: contexto CURTO p/ o roteador (o _friday_ctx inteiro é longo demais p/ uma decisão de ~1 s)"""
    agora = time.time()
    p_ = [f"tarefa rodando: {'sim' if agente_ativo[0] or fila_tarefas else 'não'}"]
    try:
        pend = ops is not None and any(i["estado"] == "pendente" for i in ops.approvals())
    except Exception:
        pend = False
    p_.append(f"aprovação pendente: {'sim' if pend else 'não'}")
    p_.append("voz: " + ("texto digitado" if agora - _voz_ult["t"] > 15 else "dono verificado" if _voz_verificada(15) else "não verificada"))
    try:
        _ult = next((m_["content"] for m_ in reversed(_friday_history(4)) if m_["role"] == "assistant"), "")
        if _ult:
            p_.append(f"última fala dela: {_ult[:120]}")
    except Exception:
        pass
    return " | ".join(p_)


def _rot_classe(dec, res):
    """F6: caminho real do friday_ask -> mesma escala de intenções do roteador (para o log de comparação)"""
    if any(d_ in dec for d_ in ("plano", "retomar")):
        return "plano"
    if any(d_ in dec for d_ in ("agente", "fila")):
        return "tarefa"
    for d_ in ("ignorar", "parar", "aprovar"):
        if d_ in dec:
            return d_
    return "acao_simples" if (res or {}).get("acoes") else "conversa"


def _rot_registrar(rot, texto, ctx_, dec, res, rd, modo_):
    """F6: loga roteador x decisão real. Sem decisão do roteador (sombra, ou regra no ativo): classifica numa thread,
    DEPOIS de a resposta já ter saído (não atrasa nada)."""
    real, classe = "+".join(dec) or "?", _rot_classe(dec, res)
    if rd is not None:
        rot.log(texto, rd, real, classe, modo_)
        return
    threading.Thread(target=lambda: rot.log(texto, rot.classificar(texto, ctx_, fr), real, classe, modo_),
                     daemon=True, name="roteador-sombra").start()


fila_tarefas = []                # pedidos que chegaram com ela ocupada: executados em ordem, sem descartar nada


def _enfileirar(pedido):
    fila_tarefas.append(pedido)
    n = len(fila_tarefas)
    return {"fala": "Anotado, faço logo depois dessa." if n == 1 else f"Anotado. Fica em {n}º na fila.", "acoes": [], "pose": "confirmar", "humor": "neutro"}


def _proxima_da_fila():
    if fila_tarefas and not agente_ativo[0]:
        prox = fila_tarefas.pop(0)
        asyncio.get_event_loop().call_later(1.5, lambda: asyncio.ensure_future(friday_ask(prox)))


_fila_falada = {"n": 0}
_SEM_TELA = re.compile(r"^\W*(?:o\s*que|qual|quais|quem|quando|onde|como|quanto|quantos|por\s*que|porque|me\s+(?:diga|fala|explica)|explique|pesquis\w*|procur\w*\s+(?:sobre|na\s+internet)|"
                       r"que\s+horas|qual\s+(?:a\s+)?(?:cota|previs|temperatura))\b", re.I)
_USA_TELA = re.compile(r"\b(?:abr[aei]\w*|cliq\w*|clique|digit\w*|tela|janela|navegador|aba|whats\w*|zap\w*|envi\w*|mand[ae]\w*|celular|c[âa]mera|olh[ae]\w*|mostr\w*|toc[ae]\w*|m[úu]sica)\b", re.I)


async def _responder_paralelo(text):
    """pista paralela: responde pergunta/pesquisa sem usar cursor, teclado nem tela, enquanto a outra tarefa segue."""
    try:
        import agent as _ag
        log_turn("usuario", text)
        await broadcast({"type": "text", "role": "user", "text": text, "files": []})
        fontes = ""
        if re.search(r"pesquis|procur|cota[çc]|pre[çc]o|not[íi]cia|hoje|agora|atual|previs|quem (?:é|foi|ganhou)", text, re.I):
            fontes = await asyncio.to_thread(_ag.t_pesquisar_web, consulta=text)
        r = await asyncio.to_thread(fr.llm, "Você é a Sexta-Feira. Responda em pt-BR, falado, em 1 a 3 frases, direto. Use as FONTES se houver; "
                                    "não invente números.", f"PERGUNTA: {text}\nFONTES:\n{str(fontes)[:3500]}", None, False, 260, 0.3, 60)
        r = (r or "Não consegui responder agora; tento quando terminar a outra tarefa.").strip()
        await broadcast({"type": "text", "role": "assistant", "text": r}); log_turn("prometheus", r)
        await speak(r)
    except Exception as e:
        print("paralelo:", e, flush=True)


async def friday_ask(text: str, files=None, proactive=False):
    """pipeline LOCAL: intent rápido por regra -> senão LLM local (gemma3) -> executa ações -> fala (Kokoro)."""
    if fr is None:
        return
    if busy.locked() and not proactive and not files:
        # 19/10: tudo esperava calado atrás da tarefa em andamento. Pergunta/pesquisa (sem tela) roda JÁ, em paralelo;
        # o que usa cursor/teclado entra na fila com aviso (duas tarefas no mesmo mouse se atrapalham).
        if _SEM_TELA.search(text) and not _USA_TELA.search(text):
            asyncio.create_task(_responder_paralelo(text))
            return
        _fila_falada["n"] += 1
        await speak("Estou terminando outra tarefa. Essa vem logo em seguida." if _fila_falada["n"] == 1
                    else f"Anotado. Tenho {_fila_falada['n']} pedidos na fila.")
    async with busy:
        _fila_falada["n"] = max(0, _fila_falada["n"] - 1)
        conv["t"] = time.time()
        if not proactive:
            await broadcast({"type": "text", "role": "user", "text": text, "files": files or []})
            log_turn("usuario", text)
        if files:                                # anexos do chat: imagem -> o VLM local descreve; arquivo -> caminho p/ o agente ler/analisar
            extras = []
            for f in [str(x) for x in files][:8]:
                if re.search(r"\.(png|jpe?g|webp|gif|bmp)$", f, re.I):
                    desc = await asyncio.to_thread(_descrever_anexo, f, text)
                    extras.append(f"[imagem anexada {f}: {desc or 'não consegui ver'}]")
                else:
                    extras.append(f"[arquivo anexado: {f}]")
            text = (text + "\n" + "\n".join(extras)).strip()
        await set_state("thinking", "pensativo")
        await friday_pose("pensando", 8000)
        _t0 = time.time()
        mlem = re.match(r"^\W*(?:sexta[\s-]*feira[,!. ]*)?(?:por favor[, ]*)?(?:lembre|anote|guarde|memorize|n[ãa]o esque[çc]a)(?:-se)?\s+(?:de\s+|disso:?\s*)?(?:que\s+)?(.{4,160})$", text or "", re.I)
        if mlem:
            fato = mlem.group(1).strip(" .!")
            mem.setdefault("fatos", {})["anotado " + time.strftime("%d/%m %H:%M")] = fato
            save_mem()
            await broadcast({"type": "text", "role": "assistant", "text": f"Anotado: {fato}"})
            log_turn("usuario", text); log_turn("prometheus", f"Anotado: {fato}")
            await speak(random.choice([f"Anotado, chefe: {fato}.", "Guardei. Não esqueço.", "Pronto, está na memória."]))
            return

        # ---- IDENTIDADE DO USUÁRIO ("QUEM SOU EU?"): RESPOSTA BIOMÉTRICA IMEDIATA ----
        if re.search(r"\b(?:quem\s+(?:sou\s+eu|eu\s+sou)|sabe\s+quem\s+(?:eu\s+sou|sou\s+eu)|qual\s+[ée]\s+o\s+meu\s+nome|como\s+(?:[ée]\s+que\s+)?eu\s+me\s+chamo|me\s+reconhece|sabe\s+quem\s+est[áa]\s+falando)\b", (text or "").lower()):
            dono = _owner_name()
            now_id = time.time()
            faces_u = scene.get("faces", []) if (now_id - scene.get("t", 0) < 5) else []
            face_dono = any(str(f.get("nome") or "").lower() == dono.lower() for f in faces_u)
            outro_face = next((f["nome"] for f in faces_u if f.get("nome")), None)
            spk_nome = str(current_speaker.get("nome") or "")
            voz_dono = _is_owner_voice() or (bool(spk_nome) and spk_nome.lower() == dono.lower())
            outro_voz = current_speaker.get("nome") or (last_voice.get("nome") if now_id - last_voice.get("t", 0) < 25 else None)

            if face_dono and voz_dono:
                fala_id = f"Você é o {dono}, meu criador e chefe. Confirmei sua identidade tanto pelo reconhecimento facial quanto pela sua voz."
            elif face_dono:
                fala_id = f"Você é o {dono}, senhor. Reconheço seu rosto perfeitamente pela câmera frontal."
            elif voz_dono:
                fala_id = f"Você é o {dono}, senhor. Reconheço com certeza o timbre da sua voz."
            elif outro_face and outro_face.lower() != dono.lower():
                fala_id = f"Pelo reconhecimento facial, você é {outro_face}."
            elif outro_voz and str(outro_voz).lower() != dono.lower():
                fala_id = f"Pelo reconhecimento de voz, você é {outro_voz}."
            else:
                fala_id = f"Você é o {dono}, meu criador e chefe."

            await broadcast({"type": "text", "role": "assistant", "text": fala_id})
            log_turn("usuario", text); log_turn("prometheus", fala_id)
            await set_state(mood="confiante")
            await friday_pose("apresentar", 4000)
            await speak(fala_id)
            await set_state("idle", "neutro")
            return

        # ---- QUEM ESTÁ AO LADO / PESSOAS NO AMBIENTE ----
        if re.search(r"\b(?:quem\s+est[áa]\s+(?:(?:d?o|no|ao)\s+meu\s+lado|aqui\s+comigo|comigo|perto\s+de\s+mim)|tem\s+algu[ée]m\s+(?:aqui|(?:d?o|no|ao)\s+meu\s+lado|comigo)|quantas\s+pessoas\s+(?:tem|h[áa]|est[ãa]o))\b", (text or "").lower()):
            now_p = time.time()
            faces_amb = scene.get("amb_faces", []) if (now_p - scene.get("t_amb_faces", 0) < 6) else []
            amb_pessoas = scene.get("amb_pessoas", (0, []))[1] if (now_p - scene.get("amb_pessoas", (0, []))[0] < 8) else []

            achados = []
            for fa_ in faces_amb:
                nm = fa_.get("nome") or "uma pessoa"
                ld = fa_.get("lado", "ao redor")
                achados.append(f"{nm} {ld}")

            desc_vlm = None
            try:
                jpg_amb = _mosaico_visao_geral()
                if jpg_amb:
                    pr_amb = ("Observe a imagem com atenção. Ela mostra as câmeras disponíveis (frontal à esquerda e ambiente à direita). "
                              "Responda diretamente: há alguém além do usuário ao lado dele ou na sala? Se houver, descreva essa pessoa (posição, aparência, o que faz). "
                              "Se não houver ninguém além do usuário, diga claramente que não há ninguém ao lado dele. Responda em português direto em 1 frase curta.")
                    desc_vlm = await asyncio.to_thread(fr.vision_describe, jpg_amb, pr_amb)
            except Exception:
                pass

            if desc_vlm and not re.search(r"n[ãa]o\s+consegui", desc_vlm, re.I):
                fala_p = desc_vlm.strip()
            elif achados:
                fala_p = f"Detectei {', '.join(achados)} pela câmera de ambiente."
            elif amb_pessoas:
                fala_p = f"Detectei {len(amb_pessoas)} pessoa(s) no ambiente pela câmera externa."
            else:
                fala_p = "Não vejo ninguém ao seu lado no momento, senhor. Apenas você em frente ao computador."

            await broadcast({"type": "text", "role": "assistant", "text": fala_p})
            log_turn("usuario", text); log_turn("prometheus", fala_p)
            await set_state(mood="curioso")
            await friday_pose("apresentar", 4000)
            await speak(fala_p)
            await set_state("idle", "neutro")
            return

        _rf = fr.fast_intent(text)
        res = _rf or (None if proactive else fr.learned_intent(text))   # proativo nunca usa/gera aprendizado; regras fixas mínimas + frases já aprendidas (instantâneo)
        try:
            import agent as _ag
        except Exception:
            _ag = None
        try:                                     # F6: roteador com schema — memory/friday.json "roteador": sombra (padrão) | ativo | off
            import roteador as _rot
            _rmodo = "off" if proactive else _rot.modo()
        except Exception:
            _rot, _rmodo = None, "off"
        _rctx = _rot_ctx() if _rmodo != "off" else ""
        _rd = _rd_baixa = None                   # decisão do roteador (só no modo ativo, antes de agir)
        _dec = (["regra"] if _rf else ["aprendido"]) if res else []     # caminho real tomado (vai p/ o log de comparação)
        _aprender = False                        # F7: fr.learn só depois da ação VERIFICADA (ver o fim do turno)

        async def _agente(pedido, ctx_):
            if agente_ativo[0]:
                _dec.append("fila")
                return _enfileirar(pedido)
            _dec.append("agente")
            asyncio.create_task(speak(random.choice(["Certo, já vou.", "Deixa comigo.", "Tá, fazendo."])))       # responde já, antes de pensar
            await broadcast({"type": "text", "role": "tool", "text": "agente: usando ferramentas"})
            _lp = asyncio.get_running_loop()
            agente_ativo[0] = True
            busy.release()          # solta a vez: ela continua ouvindo, conversando e vendo a câmera enquanto age
            try:
                return await asyncio.to_thread(_ag.run, pedido, ctx_, fr, ops, _friday_history(4),
                                               lambda s_: asyncio.run_coroutine_threadsafe(speak(s_), _lp))
            finally:
                agente_ativo[0] = False
                _proxima_da_fila()
                _t = asyncio.ensure_future(busy.acquire())      # recupera a vez mesmo se foi cancelado ("pare")
                try:
                    await asyncio.shield(_t)
                except asyncio.CancelledError:
                    await _t
                    raise
        try:
            import cerebro as _cer
            _cer_on = (not proactive) and _cer.modo() == "ativo"
        except Exception as _ec:
            print("cérebro indisponível:", _ec, flush=True)
            _cer, _cer_on = None, False

        async def _cerebro(pedido, ctx_):
            """laço autônomo: agente_geral (navegador próprio/celular/PC por observação estruturada) quando ativo em
            memory/agente.json; senão o cerebro.py antigo. O turno fica livre enquanto ela age."""
            if agente_ativo[0]:
                _dec.append("fila")
                return _enfileirar(pedido)
            try:
                import agente_geral as _geral
                _usar_geral = bool(_geral.config().get("ativo"))
            except Exception as _eg:
                print("agente_geral indisponível:", _eg, flush=True)
                _geral, _usar_geral = None, False
            _dec.append("geral" if _usar_geral else "cerebro")
            _lp = asyncio.get_running_loop()
            agente_ativo[0] = True
            busy.release()          # ela continua ouvindo ("pare", "aprovado") enquanto age
            try:
                if _usar_geral:
                    r_ = await asyncio.to_thread(_geral.resolver, pedido, fr, ops, lambda s_: asyncio.run_coroutine_threadsafe(speak(s_), _lp))
                    return {"fala": r_.get("fala") or "", "acoes": [], "pose": "neutro", "humor": "neutro", "lembrar": {}, "passos": r_.get("passos")}
                return await asyncio.to_thread(_cer.run, pedido, ctx_, fr, ops, _friday_history(6),
                                               lambda s_: asyncio.run_coroutine_threadsafe(speak(s_), _lp), mem.get("nome") or "Iann")
            finally:
                agente_ativo[0] = False
                _proxima_da_fila()
                _t = asyncio.ensure_future(busy.acquire())
                try:
                    await asyncio.shield(_t)
                except asyncio.CancelledError:
                    await _t
                    raise

        async def _plano(pedido, ctx_, retomar=None):
            """tarefa grande/composta: plano em etapas, em segundo plano (ela segue conversando); 'pare' cancela, 'retome a tarefa' continua."""
            import plano as _pl
            if agente_ativo[0] and retomar is None:
                _dec.append("fila")
                return _enfileirar(pedido)
            _dec.append("plano" if retomar is None else "retomar")
            if retomar is None:
                asyncio.create_task(speak(random.choice(["Certo, já começo.", "Beleza, vou montar isso.", "Pode deixar, começando."])))
            _lp = asyncio.get_running_loop()
            fala_ = lambda s_: asyncio.run_coroutine_threadsafe(speak(s_), _lp)
            aviso_ = lambda d_: asyncio.run_coroutine_threadsafe(broadcast({"type": "painel", "op": "plano", "data": d_}), _lp)
            prog_ = lambda o_: asyncio.run_coroutine_threadsafe(run_programming(o_), _lp)

            async def _bg():
                agente_ativo[0] = True
                try:
                    _ag.CANCEL.clear()
                    p_ = await asyncio.to_thread(_pl.executar, pedido, fr, _ag, ops, ctx_, prog_, fala_, aviso_, retomar, _ver_para_plano)
                    if p_.get("final") and p_.get("estado") != "cancelado":
                        await broadcast({"type": "text", "role": "assistant", "text": p_["final"]}); log_turn("prometheus", p_["final"])
                        await speak(p_["final"])
                except Exception as e_:
                    await broadcast({"type": "painel", "op": "fechar", "data": {}})
                    await speak("A tarefa travou: " + str(e_)[:60])
                finally:
                    agente_ativo[0] = False
                    asyncio.get_event_loop().call_later(8, lambda: asyncio.ensure_future(broadcast({"type": "painel", "op": "fechar", "data": {}})))   # 19/10: fim normal deixava o cartão aberto
                    _proxima_da_fila()
            asyncio.create_task(_bg())
            return {"fala": "", "acoes": [], "pose": "confirmar", "humor": "neutro"}

        def _grande(t_):                 # o plano decide as etapas; aqui só evita gastar um planejamento em pedido curto de mídia
            if _rd is not None and _rd["intencao"] in ("tarefa", "plano"):     # F6 ativo: o roteador decide (sem a regra das 6 palavras)
                return _rd["intencao"] == "plano" or bool(_ag is not None and _ag.PESQ.search(t_) and not _ag.YT.search(t_))
            if _ag is not None and _ag.PESQ.search(t_) and not _ag.YT.search(t_):
                return True              # toda pesquisa vai ao plano: ela pesquisa VISÍVEL no navegador, com o cursor
            return len(t_.split()) >= 6 and not (_ag is not None and _ag.YT.search(t_) and len(t_.split()) < 10)

        _tar = next((x for x in (res or {}).get("acoes", []) if isinstance(x, dict) and x.get("t") == "tarefa"), None)
        if _tar is not None:                     # tarefa vinda das regras/aprendizado: vai direto ao agente/plano
            _ped = str(_tar.get("pedido") or text)
            if _cer_on:
                res = await _cerebro(_ped, _friday_ctx())
            else:
                res = await (_plano(_ped, _friday_ctx()) if _grande(_ped) else _agente(_ped, _friday_ctx()))
        if res is None and re.search(r"\b(retom[ae]r?|continu[ae]r?)\b.{0,25}\b(tarefa|plano|de onde parou)\b", text, re.I):
            import plano as _pl
            _pi = _pl.ultimo_incompleto()
            if _pi:
                res = await _plano(_pi["pedido"], _friday_ctx(), _pi)
                res["fala"] = "Retomando: " + _pi["titulo"][:60] + "."
        if res is None and _rmodo == "ativo" and _rot is not None:      # F6 ativo: intenção pelo roteador (schema), no lugar de GATILHO/_grande
            _rd = await asyncio.to_thread(_rot.classificar, text, _rctx, fr)
            if _rd is not None and _rd["confianca"] < 0.55:
                _rd_baixa, _rd = _rd, None       # incerto: segue o caminho antigo (o log mostra a decisão descartada)
            _ri = (_rd or {}).get("intencao")
            if _ri == "ignorar" and "voz: não verificada" in _rctx:      # só silencia fala NÃO verificada (nunca texto digitado nem o dono)
                _dec.append("ignorar")
                res = {"fala": "", "acoes": [], "pose": "neutro", "humor": "neutro"}
            elif _ri == "parar":
                _dec.append("parar")
                if agente_ativo[0] or fila_tarefas:
                    fila_tarefas.clear(); cancel_all()
                    res = {"fala": "Parei a tarefa, chefe.", "acoes": [], "pose": "confirmar", "humor": "neutro"}
                else:
                    res = {"fala": "Não tem nada rodando agora.", "acoes": [], "pose": "neutro", "humor": "neutro"}
            elif _ri in ("aprovar", "rejeitar") and "aprovação pendente: não" in _rctx:
                _dec.append("aprovar")
                res = {"fala": "Não tem nada esperando aprovação.", "acoes": [], "pose": "neutro", "humor": "neutro"}
        if res is None:
            ctx = _friday_ctx()
            txt_l = (text or "").lower()
            is_hands_q = bool(HANDS_Q.search(text or ""))
            if not is_hands_q and time.time() - _last_visual_q_time[0] < 30:
                if re.search(r"\b(e\s+agora|e\s+est[ea]|e\s+ess[ea]|e\s+outr[oa]|troquei|mudou|olha\s+de\s+novo|v[êe]\s+de\s+novo|e\s+aqui|o\s+que\s+[ée]\s+isso|e\s+este\s+outro)\b", txt_l) \
                        and not re.search(r"\b(quem|qual|quando|onde|por\s*que|como|hora|dia|tempo|clima|ol[áa]|bom\s+dia|boa\s+tarde|boa\s+noite)\b", txt_l):
                    is_hands_q = True
            _escuro = False
            _d = None
            if is_hands_q:
                _last_visual_q_time[0] = time.time()
                try:                                    # F3: UMA chamada VLM com recorte focado nas mãos
                    _mos, _br = _mosaico_maos()
                    if _mos is not None and _br < 25:
                        _escuro = True                  # escuro demais: nem chama o VLM
                    elif _mos is not None:
                        # Roda detector de objetos local (YOLOX) no quadro nativo como apoio
                        dica_det = ""
                        try:
                            import senses as _sn
                            fr_n = _shared.get("frame")
                            if fr_n is not None:
                                od_ = _sn.detector_objetos()
                                cands_ = [n for n, c, _ in od_.detect(fr_n, conf=0.15) if n != "pessoa"]
                                if cands_:
                                    dica_det = f"Detector local apontou: {', '.join(set(cands_))}."
                        except Exception:
                            pass
                        prompt_v = (
                            "A imagem mostra dois painéis: à esquerda, o recorte ampliado focado na mão e no objeto segurado; "
                            "à direita, a visão da câmera. "
                            "Identifique com EXATIDÃO o objeto principal que a pessoa está segurando ou mostrando na mão neste momento. "
                            + (f"({dica_det}) " if dica_det else "") +
                            "ATENÇÃO: Se for um smartphone/celular (aparelho retangular com tela de vidro, câmera, bordas finas), "
                            "identifique como CELULAR. NUNCA confunda celular com caneta ou lápis! "
                            "Diga diretamente o nome do objeto (exemplo: 'Você está segurando um celular', 'É uma caneta', 'Um controle remoto', 'Uma garrafa'). "
                            "Responda em uma única frase direta em português. Se as mãos estiverem vazias, diga apenas 'mãos vazias'."
                        )
                        _d = await asyncio.to_thread(fr.vision_describe, _mos, prompt_v)
                        print(f"{time.strftime('%H:%M:%S')} visão[objeto na mão] (brilho {_br:.0f}): {str(_d)[:200]}", flush=True)
                        if _d:
                            txt_c = _d.strip()
                            if re.search(r"\b(caneta|l[áa]pis)\b", txt_c, re.I) and ("celular" in dica_det or re.search(r"\b(retangular|tela|smart\s?phone|aparelho)\b", txt_c, re.I)):
                                _d = "Você está segurando um celular."
                        if _d and not re.match(r"\W*m[ãa]os?\s+vazias?", _d, re.I):
                            ctx += f" | CÂMERAS (NESTE SEGUNDO): {_d[:300]}"
                        elif _d:
                            ctx += " | CÂMERAS (NESTE SEGUNDO): mãos vazias"
                except Exception as _ex:
                    print("erro visao objeto:", _ex, flush=True)
            elif re.search(r"\b(tela|janela|monitor|l[êe] (?:a|essa)?\s*tela|o que (?:est[áa]|tem) na tela)\b", text or "", re.I):
                try:
                    import visao as _vs
                    desc_t = await asyncio.to_thread(_vs.olhar_tela, text)
                    if desc_t and not desc_t.lower().startswith("não consegui"):
                        ctx += " | A TELA ATIVA DO COMPUTADOR MOSTRA: " + desc_t[:450]
                except Exception as _et:
                    print("erro visao tela:", _et, flush=True)
            elif VISUAL_Q.search(text or ""):
                _last_visual_q_time[0] = time.time()
                try:
                    import visao as _vs
                    if re.search(r"\b(c[âa]mera nativa|frontal|webcam|no notebook)\b", text or "", re.I):
                        desc = await asyncio.to_thread(_vs.olhar_camera_nativa, text)
                        if desc and not desc.lower().startswith("não consegui"):
                            ctx += " | CÂMERA NATIVA (FRONTAL) MOSTRA: " + desc[:350]
                    elif re.search(r"\b(c[âa]mera externa|sala|quarto|ambiente|ao redor)\b", text or "", re.I):
                        desc = await asyncio.to_thread(_vs.olhar_camera_externa, text)
                        if desc and not desc.lower().startswith("não consegui"):
                            ctx += " | CÂMERA EXTERNA (AMBIENTE) MOSTRA: " + desc[:350]
                    else:
                        _rj = _shared.get("remote_jpg")
                        if _rj and time.time() - _rj[0] < 15 and os.path.exists(_rj[1]):
                            jpg_bytes = open(_rj[1], "rb").read()
                        else:
                            jpg_bytes = _mosaico_visao_geral()
                            if not jpg_bytes:
                                _fq = frame_ambiente("pergunta")
                                if _fq is not None and getattr(_fq, "size", 0):
                                    import cv2 as _cv
                                    ok_, jpg = _cv.imencode(".jpg", _fq, [_cv.IMWRITE_JPEG_QUALITY, 85])
                                    jpg_bytes = jpg.tobytes() if ok_ else None
                        desc = await asyncio.to_thread(fr.vision_describe, jpg_bytes, text) if jpg_bytes else None
                        if desc:
                            ctx += " | A CÂMERA MOSTRA AGORA: " + desc[:300]
                except Exception as _ev:
                    print("erro visao geral:", _ev, flush=True)

            try:
                import agent as _ag
                usar_agente = _ag.wants_agent(text) and (not VISUAL_Q.search(text or "") or len((text or "").split()) >= 8)
                if _rd is not None:                      # F6 ativo: o roteador substitui o GATILHO
                    usar_agente = _rd["intencao"] in ("tarefa", "plano")
            except Exception:
                _ag, usar_agente = None, False

            if _escuro:
                _dec.append("escuro")
                res = {"fala": "Está escuro aqui, não consigo ver o que você tem na mão.", "acoes": [], "pose": "neutro", "humor": "neutro"}
            elif is_hands_q and _d and not usar_agente:
                _dec.append("visao_direta")
                txt_v = _d.strip()
                if re.match(r"^\W*m[ãa]os?\s+vazias?\W*$", txt_v, re.I):
                    fala_v = "Suas mãos parecem estar vazias neste momento, senhor."
                else:
                    fala_v = txt_v
                res = {"fala": fala_v, "acoes": [], "pose": "apresentar", "humor": "curioso"}
            elif _cer_on and not re.search(r"\b(retom[ae]r?|continu[ae]r?)\b.{0,25}\b(tarefa|plano)\b", text, re.I):
                res = await _cerebro(text, ctx)    # autônomo: ela decide se conversa, olha, pesquisa, age... (sem regex de rota)
            elif usar_agente:
                res = await (_plano(text, ctx) if _grande(text) else _agente(text, ctx))
            else:
                h_conv = _friday_history()
                if is_hands_q or VISUAL_Q.search(text or ""):
                    # Remove referências a objetos visuais de turnos anteriores para evitar ancoragem e repetição
                    h_clean = []
                    for m_ in h_conv:
                        c_low = m_.get("content", "").lower()
                        if any(w in c_low for w in ("segura", "mão", "mao", "copo", "perfume", "relógio", "relogio", "celular", "smartphone", "líquido", "liquido", "objeto", "frasco", "vinho", "café")):
                            continue
                        h_clean.append(m_)
                    h_conv = h_clean
                if locals().get("_ri") == "acao_simples":
                    # comando direto: histórico velho ancorava ("não tenho porta três") e ela respondia sem agir (15/10)
                    h_conv = []
                res = await asyncio.to_thread(fr.think, text, mem.get("nome") or "Iann", ctx, h_conv)
                _dec.append("think")
                tarefa = next((x for x in res.get("acoes", []) if isinstance(x, dict) and x.get("t") == "tarefa"), None)
                if tarefa and _ag is not None:
                    if res.get("fala"):
                        asyncio.create_task(speak(res["fala"]))
                    _ped = str(tarefa.get("pedido") or text)
                    res = await (_plano(_ped, ctx) if _grande(text) else _agente(_ped, ctx))
                elif not proactive:              # F7: aprende só com voz do dono verificada (faixa plena) e 3+ palavras
                    _aprender = _voz_verificada(20) and len(re.findall(r"\w+", text or "")) >= 3
        _t1 = time.time()
        if _rmodo != "off" and _rot is not None:          # F6: compara roteador x caminho real em /tmp/friday-roteador.log
            try:
                _rot_registrar(_rot, text, _rctx, _dec + (["baixa_confianca"] if _rd_baixa else []), res, _rd or _rd_baixa, _rmodo)
            except Exception as _er:
                print("erro roteador:", _er, flush=True)
        if res.get("cancelado"):
            await set_state("idle", "neutro")
            return
        fala = res.get("fala", "")
        if fala == "__hora__":
            h = int(time.strftime("%H"))
            toque = "" if os.urandom(1)[0] % 3 else (" O dia está passando rápido." if 9 <= h < 18 else " Já é tarde, chefe." if h >= 22 else " Bom começo de dia." if h < 9 else "")
            _hh, _mm = time.localtime().tm_hour, time.localtime().tm_min
            fala = (f"São {_hh} em ponto" if _mm == 0 else f"São {_hh} e {_mm}" if _hh != 1 else f"É uma e {_mm}") + "." + toque
        if isinstance(res.get("lembrar"), dict):
            for k_, v_ in list(res["lembrar"].items())[:3]:
                if str(k_).strip() and str(v_).strip() and str(k_).strip().lower() not in ("chave curta", "chave", "valor") and len(str(v_).strip()) > 2:
                    mem.setdefault("fatos", {})[str(k_).strip().lower()[:40]] = str(v_).strip()[:160]
                    save_mem()
        if _humor_norm(res.get("humor")):                  # set_state normaliza ("preocupada" -> preocupado)
            await set_state(mood=res["humor"])
        await friday_pose(res.get("pose") or "neutro", 4200)
        # ações primeiro as rápidas; fala em paralelo
        if any(isinstance(a_, dict) and a_.get("t") == "voz" for a_ in res.get("acoes", [])):
            fala = ""                     # as ações de voz falam por conta própria (o modelo dizia "voz cadastrada" ANTES do cadastro)
        # honestidade: com ação executada aqui, a fala do modelo ("abri", "enviei") só sai DEPOIS do resultado real
        adiar = bool(fala.strip()) and any(isinstance(a_, dict) and a_.get("t") not in ("desligar", "programar", "aprimorar", "voz")
                                           for a_ in res.get("acoes", [])[:4])
        fala_final, _ok_todas, _teve_extra, _escalou = (fala, True, False, False)
        if adiar:
            fala = ""
        falar = [asyncio.create_task(speak(s_)) for s_ in re.split(r"(?<=[.!?…])\s+", fala.strip()) if s_.strip()]
        if adiar:
            falar.append(asyncio.create_task(speak(random.choice(["Certo.", "Pode deixar."]))))
        try:
            with open("/tmp/friday-timing.log", "a") as _tl:
                _tl.write(f"{time.strftime('%H:%M:%S')} cérebro={_t1 - _t0:.1f}s texto={text[:40]!r}\n")
        except Exception:
            pass
        if fala.strip():
            await broadcast({"type": "text", "role": "assistant", "text": fala})
            log_turn("prometheus", fala)
        for a in res.get("acoes", [])[:4]:
            t = a.get("t") if isinstance(a, dict) else None
            if t == "desligar":
                await asyncio.gather(*falar, return_exceptions=True)
                await friday_set(False)
                return
            if t == "programar":
                asyncio.create_task(run_programming(str(a.get("pedido", text)), a.get("pasta") or None))
                continue
            if t == "aprimorar":
                asyncio.create_task(run_aprimorar(str(a.get("op") or "propor"), str(a.get("pedido") or text)))
                continue
            if t == "voz":
                asyncio.create_task(run_voz_acao(str(a.get("op") or "status"), a))
                continue
            await broadcast({"type": "text", "role": "tool", "text": f"{t}: {json.dumps({k: v for k, v in a.items() if k != 't'}, ensure_ascii=False)[:80]}"})
            ok, extra = await asyncio.to_thread(fr.run_action, a, ops)
            if not ok:
                _ok_todas = False
                _falha(f"pedido '{text[:120]}' -> ação {t} falhou: {extra or 'sem efeito'}")
                fr.forget(text)                  # aprendido errado: esquece
                if t in ("sistema", "abrir_app", "janela") and not extra and _ag is not None:   # a ação direta não surtiu efeito: o agente faz pelo caminho longo
                    _escalou = True
                    falar.append(asyncio.create_task(speak("Deixa que eu resolvo por lá.")))
                    r2 = await _agente(text, _friday_ctx())
                    if r2.get("fala"):
                        await broadcast({"type": "text", "role": "assistant", "text": r2["fala"]}); log_turn("prometheus", r2["fala"])
                        falar.append(asyncio.create_task(speak(r2["fala"])))
                    break
                if not extra or str(extra).startswith("Falhou:"):      # erro cru não vai p/ a fala: diz que falhou, sem detalhe técnico
                    extra = f"Não consegui abrir {a.get('nome')}." if t == "abrir_app" and a.get("nome") else "Não consegui fazer isso."
            if extra and str(extra).startswith("PENDENTE") and " — " in str(extra):
                extra = str(extra).split(" — ", 1)[1]          # na fala, só a parte para o dono (o id técnico fica p/ o cérebro)
            if extra:
                _teve_extra = True
                await broadcast({"type": "text", "role": "assistant", "text": extra})
                log_turn("prometheus", extra)
                falar.append(asyncio.create_task(speak(extra)))
        if _aprender and _ok_todas and not _escalou and res.get("acoes"):     # F7: ação rodou e foi verificada (run_action ok)
            fr.learn(text, res)
        if adiar and not _escalou and _ok_todas and not _teve_extra and fala_final.strip():   # tudo deu certo: agora a fala dela é verdade
            await broadcast({"type": "text", "role": "assistant", "text": fala_final})
            log_turn("prometheus", fala_final)
            falar += [asyncio.create_task(speak(s_)) for s_ in re.split(r"(?<=[.!?…])\s+", fala_final.strip()) if s_.strip()]
        if falar:
            await asyncio.gather(*falar, return_exceptions=True)
        await set_state("idle", "neutro")
        mem["turnos"] = mem.get("turnos", 0) + 1
        save_mem()


def _ver_para_plano(pergunta):
    """etapa "ver" do plano: tela interna, mãos pela câmera NATIVA e cena pela EXTERNA. Devolve texto para as próximas etapas."""
    import cv2 as _cv
    partes = []
    if re.search(r"\b(tela|janela|monitor|app|c[óo]digo|janelas|aberto)\b", pergunta or "", re.I):
        try:
            import visao as _vs
            r_t = _vs.olhar_tela(pergunta)
            if r_t and "não consegui" not in r_t.lower():
                return f"Tela: {r_t}"
        except Exception:
            pass
    if re.search(r"m[ãa]os?|segur|segura|tenho|mostr|objeto", pergunta or "", re.I) and _shared.get("frame") is not None:
        try:
            partes.append("Mãos: " + _hands_holding())
        except Exception:
            pass
    if _cam_externa_dev():                           # externa conectada mas ainda subindo: espera por ela (é a câmera do ambiente)
        for _ in range(40):
            if _shared.get("frame_amb") is not None and time.time() - _shared.get("amb_t", 0) < 2:
                break
            time.sleep(0.2)
    cams = [("nativa", _shared.get("frame"))]
    if _shared.get("frame_amb") is not None and time.time() - _shared.get("amb_t", 0) < 2:
        cams.append(("externa", _shared["frame_amb"]))
    if _shared.get("frame_ptz") is not None and time.time() - _shared.get("ptz_t", 0) < 3:
        cams.append(("do quarto (PTZ)", _shared["frame_ptz"]))
    for nome, fq in cams:                                 # todas olham: vale a que realmente mostra o objeto
        if fq is None or not fr:
            continue
        ok_, jpg = _cv.imencode(".jpg", fq, [_cv.IMWRITE_JPEG_QUALITY, 80])
        d = fr.vision_describe(jpg.tobytes(), (pergunta or "O que aparece?") + " Diga o NOME concreto do objeto principal (marca/modelo se der "
                               "para ler). Se não houver mão/objeto à vista, responda só 'nada à vista'.") if ok_ else None
        print(f"{time.strftime('%H:%M:%S')} visão[plano] {nome}: {str(d)[:160]}", flush=True)
        if d and not re.match(r"\W*nada [àa] vista", d, re.I):
            partes.append(f"Câmera {nome}: " + d[:400])
    return " | ".join(partes) or "Não consegui ver nada pelas câmeras agora (estão ligadas? a Sexta-Feira está ativa?)."


def _mosaico_maos():
    """Gera imagem de alta resolução focada nas mãos e objetos para perguntas 'o que tenho na mão':
    - Se houver mão detectada (hand_boxes ou wrists), inclui recorte focado e ampliado em 512x512.
    - Se houver visão frontal, inclui visão frontal em 512x512 (SEM esticar nem achatar proporções).
    Devolve (jpg_bytes, brilho) ou (None, 0.0)."""
    import cv2 as _cv
    import numpy as np
    now = time.time()
    fr_nat = _shared.get("frame")
    viva_nat = fr_nat is not None and now - _shared.get("frame_t", 0) < 2.0
    if not viva_nat:
        fr_amb = _shared.get("frame_amb")
        if fr_amb is not None and now - _shared.get("amb_t", 0) < 2.0:
            ok_, jpg = _cv.imencode(".jpg", fr_amb, [_cv.IMWRITE_JPEG_QUALITY, 90])
            br = float(_cv.cvtColor(fr_amb, _cv.COLOR_BGR2GRAY).mean())
            return (jpg.tobytes() if ok_ else None), br
        return None, 0.0

    fn_ = fr_nat
    if float(_cv.cvtColor(fn_, _cv.COLOR_BGR2GRAY).mean()) < 75:
        import visao as _vs
        fn_ = _vs.realcar_baixa_luz(fn_)
    brilho = float(_cv.cvtColor(fn_, _cv.COLOR_BGR2GRAY).mean())
    if brilho < 25:
        return b"", brilho

    h, w = fn_.shape[:2]

    # 1. Busca o recorte focado da mão / objeto
    crop_mao = None
    boxes = scene.get("hand_boxes") or {}
    best_b = None
    for lado, b in boxes.items():
        if b and now - b[4] < 2.5:
            if best_b is None or b[4] > best_b[4]:
                best_b = b
    if best_b:
        x0, y0, x1, y1 = best_b[:4]
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        sz = max(x1 - x0, y1 - y0, 160) * 2.8
        xa, ya = int(max(0, cx - sz / 2.0)), int(max(0, cy - sz / 2.0))
        xb, yb = int(min(w, cx + sz / 2.0)), int(min(h, cy + sz / 2.0))
        c = fn_[ya:yb, xa:xb]
        if c.size > 0 and c.shape[0] >= 50 and c.shape[1] >= 50:
            crop_mao = _cv.resize(c, (512, 512), interpolation=_cv.INTER_LANCZOS4)

    # Fallback se hand_boxes não detectou (ex: mão atrás do celular): usa os pulsos (wrists)
    if crop_mao is None and scene.get("wrists"):
        for lado, (wx, wy) in scene["wrists"].items():
            if wy < h * 0.95:
                cx, cy = float(wx), float(max(60, wy - 50))
                sz = 380.0
                xa, ya = int(max(0, cx - sz / 2.0)), int(max(0, cy - sz / 2.0))
                xb, yb = int(min(w, cx + sz / 2.0)), int(min(h, cy + sz / 2.0))
                c = fn_[ya:yb, xa:xb]
                if c.size > 0 and c.shape[0] >= 50 and c.shape[1] >= 50:
                    crop_mao = _cv.resize(c, (512, 512), interpolation=_cv.INTER_LANCZOS4)
                    break

    # 2. Visão frontal recortada em quadrado central (sem distorção de aspecto)
    sz_front = min(h, w)
    y_front = 0
    x_front = int((w - sz_front) / 2.0)
    front_sq = fn_[y_front:y_front + sz_front, x_front:x_front + sz_front]
    front_512 = _cv.resize(front_sq, (512, 512), interpolation=_cv.INTER_AREA)

    # Monta a imagem final sem distorção:
    # Se temos crop_mao: lado a lado (512x512 crop da mão + 512x512 frontal) = 1024x512 (proporção 2:1 limpa!)
    # Se não temos crop_mao: front_512 sozinho (512x512)
    if crop_mao is not None:
        mos = np.hstack([crop_mao, front_512])
    else:
        mos = front_512

    ok_, jpg = _cv.imencode(".jpg", mos, [_cv.IMWRITE_JPEG_QUALITY, 92])
    return (jpg.tobytes() if ok_ else None), brilho


def _mosaico_visao_geral():
    """Gera mosaico rotulado com as câmeras disponíveis (frontal + ambiente/porta + PTZ do quarto) para perguntas visuais gerais."""
    import cv2 as _cv
    import numpy as np
    import visao as _vs
    now = time.time()
    fr_nat = _shared.get("frame")
    fr_amb = _shared.get("frame_amb")
    viva_nat = fr_nat is not None and now - _shared.get("frame_t", 0) < 2.0
    viva_amb = fr_amb is not None and now - _shared.get("amb_t", 0) < 2.0
    fr_ptz = _shared.get("frame_ptz")
    viva_ptz = fr_ptz is not None and now - _shared.get("ptz_t", 0) < 3.0
    if not viva_nat and not viva_amb and not viva_ptz:
        return None

    frames = []
    if viva_nat:
        fn = _vs.realcar_baixa_luz(fr_nat) if float(fr_nat.mean()) < 75 else fr_nat.copy()
        h, w = fn.shape[:2]
        fn_res = _cv.resize(fn, (int(w * 480.0 / h), 480), interpolation=_cv.INTER_AREA)
        _cv.putText(fn_res, "CAM FRONTAL (NOTEBOOK)", (16, 32), _cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, _cv.LINE_AA)
        frames.append(fn_res)
    if viva_amb:
        fa = _vs.realcar_baixa_luz(fr_amb) if float(fr_amb.mean()) < 75 else fr_amb.copy()
        h, w = fa.shape[:2]
        fa_res = _cv.resize(fa, (int(w * 480.0 / h), 480), interpolation=_cv.INTER_AREA)
        _cv.putText(fa_res, "CAM AMBIENTE (SALA/MESA)", (16, 32), _cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, _cv.LINE_AA)
        frames.append(fa_res)
    if viva_ptz:
        fp = fr_ptz.copy()
        h, w = fp.shape[:2]
        fp_res = _cv.resize(fp, (int(w * 480.0 / h), 480), interpolation=_cv.INTER_AREA)
        _cv.putText(fp_res, "CAM QUARTO (PTZ COM MOTOR)", (16, 32), _cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, _cv.LINE_AA)
        frames.append(fp_res)
    if len(frames) == 3:                                  # 3 lado a lado fica largo demais p/ o VLM (max_dim 1280): reduz
        frames = [_cv.resize(f_, (int(f_.shape[1] * 360 / f_.shape[0]), 360), interpolation=_cv.INTER_AREA) for f_ in frames]

    mos = frames[0] if len(frames) == 1 else np.hstack(frames)
    ok_, jpg = _cv.imencode(".jpg", mos, [_cv.IMWRITE_JPEG_QUALITY, 85])
    return jpg.tobytes() if ok_ else None


def _hands_holding():
    """recorta cada mão visível (com margem ampla) e pergunta ao VLM local o que ela segura."""
    import cv2 as _cv
    fr_ = _shared.get("frame")
    boxes = scene.get("hand_boxes") or {}
    now = time.time()
    partes = []
    for lado, nome in (("R", "mão direita"), ("L", "mão esquerda")):
        b = boxes.get(lado)
        if not b or now - b[4] > 3 or fr_ is None:
            continue
        x0, y0, x1, y1 = b[:4]
        cx, cy, sz = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 2.4
        h, w = fr_.shape[:2]
        xa, ya = int(max(0, cx - sz / 2)), int(max(0, cy - sz / 2))
        xb, yb = int(min(w, cx + sz / 2)), int(min(h, cy + sz / 2))
        crop = fr_[ya:yb, xa:xb]
        if crop.size == 0:
            continue
        crop = _cv.resize(crop, (448, 448))
        ok_, jpg = _cv.imencode(".jpg", crop, [_cv.IMWRITE_JPEG_QUALITY, 85])
        prompt_h = ("Esta é a imagem recortada ao redor de UMA mão. Identifique com precisão o OBJETO que ela está segurando ou mostrando "
                    "(por exemplo: frasco de perfume, relógio, celular, caneta, ferramenta, caixa, garrafa, etc.). Responda em poucas palavras com o nome e cor do objeto, ou diga NADA se a mão estiver vazia.")
        d = fr.vision_describe(jpg.tobytes(), prompt_h) if ok_ else None
        d = (d or "").strip().strip(".").lower()
        if not d or re.search(r"\b(nada|mão|dedo|vazi|incerto|n[ãa]o|sem mão)\b", d):
            partes.append(f"{nome}: parece vazia")
        else:
            partes.append(f"{nome}: segurando {d[:60]}")
    if not partes:
        return ""
    return "MÃOS (recorte de detalhe): " + "; ".join(partes) + "."


async def friday_gesture(kind: str, data: dict):
    label, pose = await asyncio.to_thread(fr.gesture_action, kind, data)
    await broadcast({"type": "friday_gesture", "kind": kind, "label": label, "pose": pose, "ttl": 1800})
    ops.audit("friday.gesto", kind, label, "ok") if ops is not None else None


_RECUSA = re.compile(r"como (?:sou )?(?:um |uma )?(?:assistente|modelo|ia)\b|n[ãa]o (?:posso|consigo|tenho acesso|tenho como) (?:executar|rodar|acessar|alterar|modificar)|"
                     r"voc[êe] precisa (?:fornecer|me enviar)|aguardando (?:credenciais|informa)|forne[çc]a o c[óo]digo", re.I)
_EH_CORRECAO = re.compile(r"\b(?:corre[çc][ãa]o|corrij\w*|modifica[çc][ãa]o|tarefa atual|na conversa|esse ponto|al[ée]m disso|tamb[ée]m|na verdade|"
                          r"mude|troque|ajuste|fal[ae]\s+(?:para|pro|pra|ao|a)\s+(?:o\s+)?(?:claude|ela|ele)|diga\s+(?:para|pro|pra|ao)\s+(?:o\s+)?claude|avis[ae]\s+(?:o\s+)?claude)\b", re.I)


def _pasta_do_pedido(pedido):
    """19/10: 'no diretório integra site ...' abria na raiz (a rota do MODO DEV não passava pasta). Acha o nome de uma pasta real
    de ~/Workspace/Projetos/Sistemas (ou Projetos) citado em qualquer parte da frase, sem acento/maiúscula, o mais longo primeiro."""
    def n_(s):
        return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()).strip()
    frase = " " + n_(pedido or "") + " "
    cand = []
    for base in ("~/Workspace/Projetos/Sistemas", "~/Workspace/Projetos"):
        b = os.path.expanduser(base)
        try:
            cand += [(d, os.path.join(b, d)) for d in os.listdir(b) if not d.startswith(".") and os.path.isdir(os.path.join(b, d))]
        except Exception:
            pass
    for nome, caminho in sorted(cand, key=lambda x: -len(n_(x[0]))):
        if len(n_(nome)) >= 4 and " " + n_(nome) + " " in frase:
            return caminho
    return None


_CLAUDE_NAO = re.compile(r"n[ãa]o (?:consigo|posso|tenho (?:acesso|permiss[ãa]o|como))|preciso que voc[êe]|voc[êe] (?:precisa|pode|deve|vai precisar) "
                         r"(?:rodar|executar|editar|abrir|fazer|copiar|pegar|acessar|criar|colar|preencher)|execute manualmente|rode manualmente|"
                         r"\bI (?:can'?t|cannot|don'?t have|am unable)|you(?:'ll)? need to|permission denied", re.I)


def _dados_locais(pasta, falta):
    """lê .env*/config do projeto (sem node_modules/vendor/.git) e devolve só linhas CHAVE=valor ligadas ao que falta
    (host/usuário/senha/ftp/ssh/banco/porta). Vazio = não achou. Nada de navegador nem modelo: não alucina."""
    if not pasta or not os.path.isdir(pasta):
        return ""
    alvo = re.compile(r"host|user|usu[áa]rio|login|pass|senha|ftp|ssh|sftp|server|servidor|port|porta|db_|database|deploy|remote", re.I)
    linhas, vistos = [], 0
    for raiz, dirs, arqs in os.walk(pasta):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "vendor", ".git", "dist", "build", "__pycache__") and raiz.count(os.sep) - pasta.count(os.sep) < 3]
        for a in arqs:
            if not re.match(r"^\.env(\..+)?$|^(?:config|settings|deploy|ftp|sftp)[\w.-]*\.(?:php|json|ya?ml|ini|env|conf)$", a, re.I):
                continue
            vistos += 1
            try:
                for l in open(os.path.join(raiz, a), errors="ignore").read().splitlines()[:400]:
                    m = re.match(r"\s*(?:define\(\s*['\"])?([A-Za-z_][\w.]*)['\"]?\s*(?:=|=>|:|,)\s*['\"]?([^'\";#]+)", l)
                    if m and alvo.search(m.group(1)) and m.group(2).strip() and not re.search(r"seu_|your_|changeme|example|xxx", m.group(2), re.I):
                        linhas.append(f"{os.path.relpath(os.path.join(raiz, a), pasta)}: {m.group(1)}={m.group(2).strip()}")
            except Exception:
                pass
            if vistos > 30:
                break
    return "\n".join(dict.fromkeys(linhas))[:2500]


def _falavel(t, limite=110):
    """frase curta e pronunciável para a voz: sem caminhos, URLs, código, símbolos, parênteses e siglas coladas por barra."""
    t = re.sub(r"https?://\S+|[~/]\S*/\S+|`[^`]*`|\*\*|[•▎#_*`]+|\([^)]*\)", " ", str(t or ""))
    t = re.sub(r"\b([A-Z]{2,})/([A-Z]{2,})\b", r"\1 ou \2", t)
    t = re.sub(r"\b[Oo] agente\b", "o Claude", t); t = re.sub(r"\b[Oo] (?:dono|usu[áa]rio) deve\b", "você precisa", t)
    t = re.sub(r"\b(?:[Oo] dono|[Oo] usu[áa]rio)\b", "você", t); t = re.sub(r"\.env\b", "ponto env", t)
    t = re.sub(r"\s+", " ", t).strip(" .,:;-")
    if len(t) > limite:
        t = t[:limite].rsplit(" ", 1)[0]
    return t or "uma informação sua"


def _sem_meta_claude(pedido):
    """tira a parte dirigida à Friday ('eu quero que fale para o claude code que ...') e deixa só o conteúdo para o Claude."""
    t = re.sub(r"^.*?\b(?:fal[ae]r?|diga|dizer|avis[ae]r?|pe[çc]a|pedir|mand[ae]r?)\s+(?:para|pro|pra|ao|a)\s+(?:(?:o\s+)?claude(?:\s+code)?|ela|ele)"
               r"(?:\s+(?:que|da|sobre|na|no))?\s*", "", pedido or "", count=1, flags=re.I).strip(" ,.:")
    return t if len(t.split()) >= 3 else (pedido or "").strip()


def _instrucao_claude(texto):
    """reescreve a correção do dono como instrução DIRETA ao Claude (imperativo, todos os detalhes). Recusa/vazio = texto do dono."""
    import orquestra_geral as _og
    base = "Correção do dono para a tarefa atual: " + texto + "\nAjuste o que já foi feito de acordo, teste e continue até concluir."
    try:
        r = _og._modelo("Reescreva o pedido abaixo como instrução direta a um agente de programação (imperativo, pt-BR), mantendo TODOS os "
                        "detalhes e o sentido. É uma correção da tarefa que ele já está fazendo. Responda só com a instrução, sem introdução.\n\n"
                        "PEDIDO: " + texto, 300).strip().strip('"')
    except Exception:
        return base
    if not r or _RECUSA.search(r) or len(r) < len(texto) * 0.5:
        return base
    return "Correção do dono para a tarefa atual: " + r + "\nAjuste o que já foi feito de acordo, teste e continue até concluir."


def _brief_programacao(pedido: str, pasta=None):
    """o agente LOCAL (Ollama) transforma o pedido falado num briefing técnico preciso e escolhe o projeto; o Claude CLI só executa."""
    projetos = []
    try:
        projetos = [(p_["nome"], p_["caminho"]) for p_ in json.load(open(os.path.join(MEM_DIR, "projetos.json")))["projetos"]
                    if p_.get("arquivos", 0) > 0][:40]
    except Exception:
        pass

    resolved_pasta = None
    if pasta and isinstance(pasta, str) and pasta.strip():
        cand = os.path.abspath(os.path.expanduser(pasta.strip()))
        if not os.path.exists(cand):
            cand2 = os.path.join(os.path.expanduser("~"), pasta.strip().lstrip("/"))
            if os.path.exists(cand2):
                cand = cand2
        if os.path.isdir(cand):
            resolved_pasta = cand

    if not resolved_pasta:
        m_p = re.search(r"\b(?:na pasta|no diret[óo]rio|no caminho|em)\s+(?:de\s+|do\s+|da\s+)?([~/a-zA-Z0-9_\-\./]+)", pedido, re.I)
        if m_p:
            raw = m_p.group(1).rstrip(".,;:/")
            cand = os.path.abspath(os.path.expanduser(raw))
            if not os.path.exists(cand):
                cand2 = os.path.join(os.path.expanduser("~"), raw.lstrip("/"))
                if os.path.exists(cand2):
                    cand = cand2
            if os.path.isdir(cand):
                resolved_pasta = cand

    out = {"prompt": pedido, "pasta": resolved_pasta}
    if fr is None:
        return out
    lista = "\n".join(f"- {n}: {c}" for n, c in projetos) or "(sem lista)"
    d = fr.llm("Você é o agente local que prepara tarefas de programação para o Claude Code (CLI). Dado o pedido falado do dono, responda JSON: "
               '{"pasta":"caminho EXATO de um dos projetos listados, ou caminho informado no pedido, ou \"\" se não souber","prompt":"briefing claro e completo em pt-BR: objetivo, '
               'arquivos/áreas prováveis, critérios de pronto, restrições (economizar tokens, ler só o necessário, editar com diff, reaproveitar '
               'código existente, nunca ler/imprimir segredos .env/.pfx/Secrets)"}\nProjetos:\n' + lista,
               f"Pedido do dono: {pedido}\nPasta sugerida: {resolved_pasta or 'nenhuma'}", num_predict=1400, temperature=0.2, timeout=120)   # 19/10: 420 cortava o JSON (done_reason=length) -> ia o pedido cru
    if isinstance(d, dict):
        if isinstance(d.get("prompt"), str) and len(d["prompt"]) > 20:
            out["prompt"] = d["prompt"][:3000]
        c = str(d.get("pasta") or "").strip()
        if c and not resolved_pasta:                     # 19/10: pasta achada pelo código/última tarefa vale mais que o palpite do modelo ("Agente Fiscal")
            cand = os.path.abspath(os.path.expanduser(c))
            if not os.path.exists(cand):
                cand2 = os.path.join(os.path.expanduser("~"), c.lstrip("/"))
                if os.path.exists(cand2):
                    cand = cand2
            if os.path.isdir(cand):
                out["pasta"] = cand
    if not out.get("pasta") and resolved_pasta:
        out["pasta"] = resolved_pasta
    return out


_SUDO_RE = re.compile(r"(?:^|[\s`!])(sudo\s+(?:pacman|apt|apt-get|dnf|systemctl|npm|pip|install|chmod|chown|ln|mkdir|cp|usermod)\b[^\n`]*)", re.M)


async def _sudo_aprovado(cmd, espera=600):
    """pede o sudo pelo portão de aprovação (dono diz 'aprovado' e digita a senha na janela do sistema) e espera o fim."""
    m_ = re.match(r"^(?:sudo\s+)?pacman\s+(-S|-Syu)\b(.*)$", cmd.strip())
    if m_:                                           # 19/10: /etc/sudoers.d/friday-dev libera só 'pacman -S --noconfirm <pacotes>' e 'pacman -Syu --noconfirm' sem senha
        pac = [x for x in m_.group(2).split() if x != "--noconfirm"]
        if all(re.fullmatch(r"[a-z0-9][a-z0-9@._+-]*", x) for x in pac) and (pac or m_.group(1) == "-Syu"):
            arg = ["sudo", "-n", "/usr/bin/pacman", m_.group(1), "--noconfirm"] + (pac if m_.group(1) == "-S" else [])
            r = await asyncio.to_thread(subprocess.run, arg, capture_output=True, text=True, timeout=1800)
            if r.returncode != 0 and m_.group(1) == "-S" and re.search(r"404|falha ao obter|failed retrieving|not found in sync db", (r.stdout or "") + (r.stderr or ""), re.I):
                # 19/10: base de pacotes velha (espelho 404) -> atualiza o sistema 1x e tenta de novo (antes repetia o mesmo erro em loop)
                await broadcast({"type": "text", "role": "tool", "text": "Sexta-Feira: base de pacotes desatualizada, rodando pacman -Syu"})
                await asyncio.to_thread(subprocess.run, ["sudo", "-n", "/usr/bin/pacman", "-Syu", "--noconfirm"], capture_output=True, text=True, timeout=3600)
                r = await asyncio.to_thread(subprocess.run, arg, capture_output=True, text=True, timeout=1800)
            return r.returncode == 0, ((r.stdout or "") + (r.stderr or ""))[-600:]
    import agent as _ag
    ok_d, out_d = await asyncio.to_thread(_ag.sudo_direto, re.sub(r"^sudo\s+", "", cmd.strip()))
    if ok_d is not None:                             # 19/10: dono liberou sudo sem senha -> qualquer comando roda direto (catastróficos seguem bloqueados)
        return ok_d, out_d
    antes = {i["id"] for i in ops.approvals()}
    await asyncio.to_thread(_ag.t_comando_sudo, comando=re.sub(r"^sudo\s+", "", cmd), motivo="O Claude do MODO DEV precisa disso para continuar", ops=ops)   # o executor já põe sudo -A
    novo = next((i for i in ops.approvals() if i["id"] not in antes and i["acao"] == "sudo.run"), None)
    if not novo:
        return False, "não consegui criar a aprovação do sudo"
    await speak(f"O Claude precisa rodar um comando de administrador: {cmd[:90]}. Diga aprovado e digite a senha na janela.")
    t0 = time.time()
    while time.time() - t0 < espera:
        await asyncio.sleep(3)
        it = next((i for i in ops.approvals() if i["id"] == novo["id"]), {})
        if it.get("estado") in ("executada", "falhou", "rejeitada"):
            return it["estado"] == "executada", str(it.get("resultado") or it["estado"])
    return False, "o dono não aprovou a tempo"


async def _supervisionar_dev(objetivo, tela, pasta, rodadas=int(os.environ.get("FRIDAY_DEV_RODADAS", "60"))):
    """a Friday conduz o Claude do MODO DEV até o objetivo: sudo via aprovação, testa/corrige/continua sem o dono
    responder cada etapa; para em concluído, em algo que só o dono tem (certificado, credencial, chave) ou em `rodadas`."""
    import dev_cli, orquestra_geral as _og
    _sudo_feitos = set()
    _manual_vezes = {}
    parado, anterior = 0, ""                             # 19/10: sem teto fixo de 10; para em concluído, só-o-dono ou 3 telas iguais seguidas
    for n in range(rodadas):
        fim = tela[-3500:]
        parado = parado + 1 if fim.strip() == anterior.strip() else 0
        anterior = fim
        if parado >= 3:
            await speak("O Claude do modo dev parou de avançar. Deixei a sessão aberta para você ver.")
            break
        if _CLAUDE_NAO.search(fim[-1600:]) and not _SUDO_RE.search(fim[-1600:]):
            # 19/10: Claude dizia "não posso, faça você" e o supervisor mandava "continue" -> loop. Agora a Sexta-Feira FAZ o passo
            # (navegador, terminal, arquivo; sudo segue a regra de aprovação) e devolve o resultado. Mesmo bloqueio 3x = para e avisa.
            try:
                d_m = json.loads(re.search(r"\{.*\}", await asyncio.to_thread(_og._modelo,
                    "Um agente de programação disse que NÃO consegue fazer algo e pediu ajuda. Leia o fim da tela e responda SÓ JSON: "
                    "{\"tarefa\": \"o passo concreto que ele pediu para alguém fazer (imperativo, com caminhos/comandos/site exatos)\", "
                    "\"so_o_dono\": \"\" ou o que SÓ o dono pode dar (senha que não está salva em lugar nenhum, decisão de negócio)}\n\nFIM DA TELA:\n"
                    + fim[-2500:], 300), re.S).group(0))
            except Exception:
                d_m = {}
            tarefa_m = str(d_m.get("tarefa") or "").strip()
            dono_m = str(d_m.get("so_o_dono") or "").strip()
            chave_m = re.sub(r"\W+", " ", tarefa_m.lower())[:80]
            _manual_vezes[chave_m] = _manual_vezes.get(chave_m, 0) + 1
            if dono_m or not tarefa_m or _manual_vezes[chave_m] > 2:
                motivo_ = dono_m or tarefa_m or "um passo que o Claude não consegue fazer"
                await broadcast({"type": "text", "role": "tool", "text": "MODO DEV parado, precisa de você: " + motivo_[:400]})
                await speak("O Claude travou e precisa de você: " + _falavel(motivo_) + ". Os detalhes estão no painel.")
                break
            await broadcast({"type": "text", "role": "tool", "text": "Sexta-Feira fazendo pelo Claude: " + tarefa_m[:300]})
            try:
                import cerebro as _cb
                ctx_m = await asyncio.to_thread(_friday_ctx)
                r_m = await asyncio.to_thread(lambda: _cb.run(tarefa_m + (f" (projeto em {pasta})" if pasta else ""), ctx_m, fr, ops, atalhos=False))
                feito = str(r_m.get("fala") or "")[:500] + " | passos: " + "; ".join(str(x)[:120] for x in (r_m.get("passos") or [])[-5:])
            except Exception as e_m:
                feito = f"falhou: {e_m}"
            await broadcast({"type": "text", "role": "tool", "text": "Sexta-Feira fez: " + feito[:400]})
            msg = (f"A Sexta-Feira fez por você: {tarefa_m}. Resultado: {feito}. Confira o resultado e continue o objetivo daqui, "
                   "sem pedir de novo o mesmo passo. Se ainda faltar algo, diga exatamente o que e por quê.")
            await broadcast({"type": "text", "role": "tool", "text": f"MODO DEV rodada {n + 2}: {msg[:160]}"})
            tela = await asyncio.to_thread(dev_cli.enviar, msg, 1800, pasta)
            continue
        m = _SUDO_RE.search(fim)
        if m:
            cmd = re.split(r"\s+e\s+|[.;,(]\s*|\s+(?:depois|então|e me|aí)\b", m.group(1).strip() + " ")[0].strip().rstrip(".")
            mp_ = re.match(r"sudo\s+pacman\s+(-S\w*)\s+(.*)$", cmd)
            if mp_:                                      # 19/10: "sudo"/"pacman" também são pacotes -> entravam na lista e furavam a trava de repetição                                      # 19/10: frase vinha junto ("php no prompt", "(precisa de ...") -> só pacotes que EXISTEM no repositório
                pac_ = [x for x in mp_.group(2).split() if x not in ("sudo", "pacman") and re.fullmatch(r"[a-z0-9][a-z0-9@._+-]*", x)
                        and subprocess.run(["pacman", "-Si", x], capture_output=True).returncode == 0]
                cmd = f"sudo pacman -S --noconfirm {' '.join(pac_)}" if pac_ else ""
            if not cmd or cmd in _sudo_feitos:          # nada válido ou já tentado nesta tarefa: não pede de novo (texto antigo segue na tela)
                tela = await asyncio.to_thread(dev_cli.enviar, "Continue o objetivo de forma autônoma, sem depender desse comando de administrador.", 1800, pasta)
                continue
            _sudo_feitos.add(cmd)
            ok, saida = await _sudo_aprovado(cmd)
            msg = (f"A Friday executou `{cmd}` com sucesso. Saída: {saida[:400]}. " if ok else
                   f"O comando `{cmd}` não foi executado ({saida[:200]}). Siga sem ele se der, ou explique o que falta. ")
            msg += "Continue o objetivo de forma autônoma: teste, confira, corrija e avance sem me perguntar."
        else:
            prompt = ("Você supervisiona um agente de programação. OBJETIVO DO DONO:\n" + objetivo[:1500] +
                      "\n\nFIM DA TELA DO AGENTE:\n" + fim +
                      "\n\nResponda SÓ JSON: {\"concluido\": true|false, \"so_o_dono\": \"\" ou o que só o dono pode fornecer "
                      "(certificado, senha, credencial, chave de API, decisão de negócio), \"proxima\": \"mensagem curta para o agente "
                      "continuar: testar, conferir, corrigir e fazer o próximo passo do objetivo\"}\n"
                      "REGRA: se o agente terminou PERGUNTANDO ('qual prefere?', 'posso começar?', 'quer que eu...?'), NÃO está concluído: "
                      "escolha você a opção que NÃO depende do dono e mande seguir nela (proxima). so_o_dono só quando nenhuma opção dá para seguir.")
            try:
                d = json.loads(re.search(r"\{.*\}", await asyncio.to_thread(_og._modelo, prompt, 300), re.S).group(0))
            except Exception:
                d = {"concluido": False, "so_o_dono": "", "proxima": "Continue o objetivo: teste, confira e corrija."}
            if d.get("concluido"):
                break
            dono_ = str(d.get("so_o_dono") or "").strip()
            prox_ = str(d.get("proxima") or "").strip()
            # 19/10: o modelo escrevia PENSAMENTO em 3ª pessoa ("O agente precisa das credenciais...", "o dono deve escolher...")
            # e isso ia ao Claude como ordem. Pensamento ou algo que depende do dono = não envia; avisa curto e para.
            pensamento = bool(re.search(r"\b(?:o|ao|do)\s+(?:agente|dono|usu[áa]rio)\b|\baguard\w*|\baguar\b|\.env\b|\bprecisa(?:r)?\s+(?:das?|de)\s+(?:credenciais|senha|acesso|dados|chave|decis)", prox_, re.I))
            depende = pensamento or re.search(r"credencia|senha|password|chave de api|token|certificado|ssh|sftp|ftp|login|acesso ao servidor", prox_ + " " + dono_, re.I)
            if (dono_ or depende) and _manual_vezes.get("__dados__", 0) < 2:
                # 19/10: antes de parar, ela TENTA buscar o dado (navegador já logado, .env/config do projeto) e entrega ao Claude
                _manual_vezes["__dados__"] = _manual_vezes.get("__dados__", 0) + 1
                falta_ = dono_ or prox_
                await broadcast({"type": "text", "role": "tool", "text": "Sexta-Feira buscando o que falta: " + falta_[:300]})
                achou_ = await asyncio.to_thread(_dados_locais, pasta, falta_)    # 19/10: leitura local (o cérebro jogava no Google e inventava)
                await broadcast({"type": "text", "role": "tool", "text": "Sexta-Feira encontrou: " + (f"{achou_.count(chr(10)) + 1} configuração(ões) no projeto" if achou_ else "nada no projeto")})
                if achou_:
                    tela = await asyncio.to_thread(dev_cli.enviar, "A Sexta-Feira buscou o que faltava (" + falta_[:200] + "): " + achou_ +
                                                   ". Use isso e continue o objetivo, testando antes de dizer que terminou.", 1800, pasta)
                    continue
            if dono_ or depende or _RECUSA.search(prox_):
                aviso_ = _falavel(dono_ or prox_)
                await broadcast({"type": "text", "role": "tool", "text": "MODO DEV aguardando você: " + (dono_ or prox_)[:400]})
                if aviso_ not in _sudo_feitos:
                    _sudo_feitos.add(aviso_)
                    await speak("O Claude parou porque precisa de você: " + aviso_ + ". Os detalhes estão no painel.")
                break
            if not prox_:
                prox_ = "Continue o objetivo: teste, confira, corrija e avance."
            msg = prox_ + " Faça de forma autônoma, sem me perguntar; teste antes de dizer que terminou."
        await broadcast({"type": "text", "role": "tool", "text": f"MODO DEV rodada {n + 2}: {msg[:160]}"})
        tela = await asyncio.to_thread(dev_cli.enviar, msg, 1800, pasta)
    return tela


async def run_programming(pedido: str, pasta=None):
    """Executa o Claude Code CLI em background de forma autônoma por múltiplos turnos até concluir sem interromper o usuário."""
    if ops is None:
        return
    limpo = _sem_meta_claude(pedido)
    ult_ = os.path.join(MEM_DIR, "dev_ultima.json")
    if not pasta:
        pasta = _pasta_do_pedido(pedido)
    if not pasta and re.search(r"\b(?:continu\w*|anterior|mesma tarefa|tarefa atual|essa tarefa|corrij\w*|corre[çc][ãa]o|modifica[çc][ãa]o)\b", pedido, re.I):
        try:                                                # 19/10: "continue a tarefa anterior" abria na raiz -> volta à pasta da última tarefa
            pasta = json.load(open(ult_)).get("pasta") or None
        except Exception:
            pass
    try:                                                    # 19/10: correção no meio da tarefa ia colada crua ("eu quero que fale para o claude...")
        import dev_cli
        if dev_cli.vivo() and time.time() - dev_cli.ultimo_uso() < 3600 and _EH_CORRECAO.search(pedido):
            msg = await asyncio.to_thread(_instrucao_claude, limpo)
            await broadcast({"type": "text", "role": "tool", "text": "MODO DEV (correção): " + msg[:200]})
            tela = await asyncio.to_thread(dev_cli.enviar, msg, 1800, pasta)
            await _supervisionar_dev(limpo, tela, pasta)
            return
    except Exception as e:
        print("dev correção:", e, flush=True)
    brief = await asyncio.to_thread(_brief_programacao, pedido, pasta)
    pedido_prompt, pasta = brief["prompt"], brief["pasta"]
    if pasta:
        try:
            json.dump({"pasta": pasta, "pedido": limpo[:500], "t": int(time.time())}, open(ult_, "w"), ensure_ascii=False)
        except Exception:
            pass
    if _RECUSA.search(pedido_prompt):                       # 19/10: modelo local escreveu "como sou um assistente de IA, não posso..." e foi pro Claude
        pedido_prompt = (limpo + "\n\nTrabalhe de forma autônoma: leia o código existente, implemente, teste e corrija até concluir. "
                         "Economize tokens: leia só o necessário e edite com diff.")
    cwd = pasta or os.path.expanduser("~")
    await broadcast({"type": "text", "role": "tool", "text": "Claude CLI em " + cwd})
    try:                                                    # MODO DEV: sessão fixa do claude no terminal kitty (menos token)
        import dev_cli
        aviso = f"Trabalhe em {cwd}. " if pasta else ""
        tela = await asyncio.to_thread(dev_cli.enviar, aviso + pedido_prompt, 1800, pasta)
        tela = await _supervisionar_dev(pedido, tela, pasta)
        fim = [l.strip() for l in tela.splitlines() if l.strip().startswith(("⏺", "●"))]
        resumo = (fim[-1].lstrip("⏺● ").strip() if fim else "Terminei no terminal do modo dev.")[:300]
        await broadcast({"type": "text", "role": "tool", "text": "MODO DEV (terminal): " + resumo})
        await speak(resumo if len(resumo) <= 180 else "Terminei. O resultado está no terminal do modo dev.")
        return
    except Exception as e:
        print("dev_cli falhou, uso claude -p:", e, flush=True)

    max_turnos = 4 if any(k in pedido.lower() for k in ("continue", "faça", "faca", "completo", "todo", "até", "turnos", "projeto")) else 1
    turno = 1
    ultimo_resultado = ""
    sucesso = False

    while turno <= max_turnos:
        prompt_turno = (
            persona() + "\n\n"
            f"[TAREFA AUTÔNOMA EM BACKGROUND — Turno {turno}/{max_turnos}]\n"
            f"Diretório de trabalho: {cwd}\n"
            f"PEDIDO: {pedido_prompt}\n"
        )
        if turno > 1 and ultimo_resultado:
            prompt_turno += f"\nÚltimo avanço realizado:\n{ultimo_resultado[:1200]}\nContinue o projeto, faça verificações necessárias e prossiga até concluir."

        cmd = ["claude", "-p", prompt_turno, "--output-format", "stream-json", "--verbose", "--model", MODEL, "--effort", EFFORT_TASK]
        if PERMISSION:
            cmd += ["--permission-mode", PERMISSION]

        await hud_begin(f"Claude ({turno}/{max_turnos}): " + pedido_prompt[:50])
        res, ok = "", False
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                     limit=1 << 24, cwd=cwd, env=_gui_env())

            async def _read():
                nonlocal res
                async for raw in p.stdout:
                    try:
                        ev = json.loads(raw)
                    except ValueError:
                        continue
                    if dev is not None:
                        dev.claude(ev)
                    if ev.get("type") == "assistant":
                        for bl in ev["message"].get("content", []):
                            if bl.get("type") == "tool_use":
                                inp = bl.get("input", {})
                                await hud_step(f"{bl['name']}: {inp.get('command') or inp.get('file_path') or inp.get('pattern') or ''}")
                            elif bl.get("type") == "text" and bl["text"].strip():
                                res = bl["text"].strip()
                    elif ev.get("type") == "result" and ev.get("result"):
                        res = str(ev["result"]).strip()
            await asyncio.wait_for(_read(), 1800)
            await p.wait()
            ok = p.returncode == 0 and bool(res)
        except Exception as e:
            res, ok = f"erro: {e!r}", False
            try: p.kill()
            except Exception: pass

        await hud_end(ok)
        ultimo_resultado = res
        sucesso = ok

        if not ok or any(term in res.lower() for term in ("concluído", "concluido", "finalizado", "tudo pronto", "todas as etapas")):
            break
        turno += 1

    resumo = (ultimo_resultado.split("\n")[0] if ultimo_resultado else "trabalho finalizado")[:220]
    msg = ("Chefe, terminei o projeto no Claude CLI em " + os.path.basename(cwd) + ": " + resumo) if sucesso else ("Não consegui concluir o projeto no Claude CLI: " + resumo)
    await broadcast({"type": "text", "role": "assistant", "text": msg})
    log_turn("prometheus", msg)
    if not speaking and state["state"] == "idle":
        await speak(msg[:260])
async def _agente_watch():
    """avisa a interface quando o agente assume mouse/teclado: o fundo preto da conversa some (o agente precisa ver a tela)."""
    ult = None
    while True:
        await asyncio.sleep(0.4)
        if agente_ativo[0] != ult:
            ult = agente_ativo[0]
            await broadcast({"type": "nano", "op": "agente", "on": bool(ult)})


def _descrever_anexo(caminho, pergunta=""):
    """imagem anexada no chat -> descrição curta pelo VLM local (mesmo modelo da conversa)."""
    try:
        from PIL import Image
        import io as _io
        im = Image.open(caminho).convert("RGB"); im.thumbnail((1024, 1024))
        b = _io.BytesIO(); im.save(b, "JPEG", quality=88)
        return fr.vision_describe(b.getvalue(), (pergunta or "O que tem nesta imagem?") + " Descreva o que importa para responder, incluindo textos visíveis.")
    except Exception as e:
        return None


APRIMORAR = os.path.join(ROOT, "daemon", "aprimorar.py")


def _falha(texto):
    """registra falha em memory/falhas.jsonl: a mente usa para propor melhorias em si mesma."""
    try:
        with open(os.path.join(MEM_DIR, "falhas.jsonl"), "a") as f:
            f.write(json.dumps({"t": int(time.time()), "texto": texto[:300]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _falhas_recentes(n=5, horas=24):
    try:
        ls = [json.loads(l) for l in open(os.path.join(MEM_DIR, "falhas.jsonl")).read().splitlines()[-n:]]
        return [l["texto"] for l in ls if time.time() - l["t"] < horas * 3600]
    except Exception:
        return []


async def _aprimorar_cli(*args, timeout=1900):
    r = await asyncio.to_thread(subprocess.run, [sys.executable, APRIMORAR, *args], capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "erro": (r.stderr or r.stdout)[-300:]}


async def _dizer(txt):
    await broadcast({"type": "text", "role": "assistant", "text": txt}); log_turn("prometheus", txt)
    await speak(txt); conv["t"] = time.time()


async def run_aprimorar(op: str, pedido: str):
    """auto-aprimoramento SUPERVISIONADO: o Claude CLI edita uma CÓPIA; o dono vê a proposta no espelho e aprova (self.apply)."""
    if ops is None:
        return
    if op == "desfazer":
        d = await _aprimorar_cli("desfazer", timeout=120)
        await _dizer(f"Desfiz a melhoria: {d.get('pedido', '')[:80]}. Vale depois de reiniciar." if d.get("ok") else "Não tem melhoria aplicada para desfazer.")
        return
    await _dizer("Certo, vou preparar uma proposta de melhoria. Te mostro antes de mudar qualquer coisa.")
    await broadcast({"type": "text", "role": "tool", "text": "aprimorar → Claude CLI numa cópia isolada"})
    d = await _aprimorar_cli("propor", pedido)
    if d.get("estado") != "proposta":
        motivo = "; ".join(d.get("erros") or []) or d.get("erro") or "nenhum arquivo mudou"
        _falha(f"aprimorar '{pedido[:80]}' sem proposta válida: {motivo[:150]}")
        await _dizer("Não saiu uma proposta segura, descartei. " + ("Deu erro na validação." if d.get("erros") else "Nada mudou."))
        return
    ops.holo_show({"kind": "email", "para": "F.R.I.D.A.Y. (auto-aprimoramento)", "assunto": pedido[:80],
                   "corpo": f"{d['relato'][:600]}\n\nArquivos: {', '.join(d['arquivos'])} ({d['linhas']} linhas)\nDiff: {d.get('diff', '')}",
                   "status": "aguardando aprovação", "titulo": "Proposta de melhoria", "ttl": 600})
    await asyncio.to_thread(ops.gated, "self.apply", d["id"], f"aplicar melhoria em mim: {pedido[:80]} ({len(d['arquivos'])} arquivos)", {"id": d["id"]})
# =====================================================================================================


def mind_thread(loop):
    """Laço contínuo (5 s): acompanha presença (com histerese, cobre 'cabeça baixa') e dispara pensamentos nos momentos certos."""
    while True:
        time.sleep(5.0)
        try:
            if not mem.get("autonomia", True):
                continue
            now = time.time()
            present = camera_on and (now - scene["t"] < 90)
            ms = mind_state
            if present and not ms["present"]:
                away = now - ms["absent_since"] if ms["absent_since"] else 0
                ms["present"] = True; ms["present_since"] = now
                if away > 600:
                    asyncio.run_coroutine_threadsafe(mind_think("usuário voltou à frente do computador depois de %d min fora" % (away // 60)), loop)
            elif not present and ms["present"]:
                ms["present"] = False; ms["absent_since"] = now
            if ops is not None and now - task_state.get("map_check", 0) > 3600:
                task_state["map_check"] = now
                try:
                    mp = os.path.join(MEM_DIR, "mapa_pc.json")
                    if not os.path.exists(mp) or now - os.path.getmtime(mp) > 86400:
                        threading.Thread(target=lambda: subprocess.run([sys.executable, os.path.join(ROOT, "tools", "map_pc.py")],
                                                                       capture_output=True, timeout=300), daemon=True).start()
                except Exception:
                    pass
            if ops is not None:
                asyncio.run_coroutine_threadsafe(announce_approvals(), loop)
                asyncio.run_coroutine_threadsafe(agenda_tick(), loop)
                asyncio.run_coroutine_threadsafe(zap_tick(), loop)
                asyncio.run_coroutine_threadsafe(zap_cmd_tick(), loop)
                if task_state["running"] is None and not speaking:
                    due = ops.task_next_due()
                    if due and now - max(conv["t"], 0) > 20:
                        asyncio.run_coroutine_threadsafe(run_task(due), loop)
                if now - task_state["last_phone_poll"] > 20:
                    task_state["last_phone_poll"] = now
                    asyncio.run_coroutine_threadsafe(poll_phone_messages(), loop)
            _gap, _idle = (300, 120) if friday_state["on"] else (900, 600)         # 19/10: 40 s/20 s repetia "Bom dia, tudo bem?" a cada ~80 s
            if (present or friday_state["on"]) and now - ms["last_reflect"] > _gap and now - max(conv["t"], mem.get("ultima_vez", 0)) > _idle \
                    and not speaking and state["state"] == "idle":
                ms["last_reflect"] = now
                asyncio.run_coroutine_threadsafe(mind_think("revisão periódica: há algo útil a dizer ou lembrar?"), loop)
            # Vigília Multimodal Proativa em tempo real (expressões faciais + tela)
            if friday_state["on"] and not speaking and state["state"] == "idle" and not busy.locked() \
                    and now - ms.get("last_multimodal_check", 0) > 20 and now - oferta.get("t", 0) > 75 \
                    and now - last_voice.get("t", 0) > 8 and not _vigilia_quieta():
                ms["last_multimodal_check"] = now
                asyncio.run_coroutine_threadsafe(_vigilia_multimodal_tick(), loop)
        except Exception as e:
            print("mente:", e, flush=True)
# ==========================================================================================

def pose_thread(loop):
    """Imita gestos: YOLOv8n-pose (ONNX) sobre o último quadro da câmera -> ângulos dos braços {pose L,R}.
    Convenção do avatar: s=elevação do ombro, a=abdução, e=flexão do cotovelo; L = lado esquerdo da tela."""
    try:
        import cv2, numpy as np, onnxruntime as ort
        sess = ort.InferenceSession(os.path.join(ROOT, "models", "yolov8n-pose.onnx"), senses._ort_opts(2), providers=["CPUExecutionProvider"])
    except Exception as e:
        print("pose indisponível:", e, flush=True); return
    name = sess.get_inputs()[0].name
    try:
        import body3d, articulation as artic
        bp = body3d.BodyPose() if os.environ.get("PROMETHEUS_POSE3D", "0") == "1" else None
    except Exception as e:
        print("pose 3D indisponível (usa 2D):", e, flush=True); bp = None
    try:
        import articulation as artic
    except Exception:
        artic = None
    prev3 = {"L": None, "R": None}
    # copiar o usuário: mediana (picos) + One-Euro (suave parado, ágil em movimento). Torção/ombros/rolagem desligados (ruidosos).
    TRACK_TWIST = False; TRACK_SHRUG = False
    filt = {sd: [artic.OneEuro(1.0, 0.05) for _ in range(4)] for sd in ("L", "R")} if bp is not None else {}
    med = {sd: [artic.Median(5) for _ in range(4)] for sd in ("L", "R")} if bp is not None else {}
    last_arm_ok = [0.0]
    f_tw = artic.OneEuro(1.0, 0.05) if bp is not None else None
    f_sh = [artic.OneEuro(1.0, 0.05), artic.OneEuro(1.0, 0.05)] if bp is not None else []
    last_good = {"L": (0.0, None), "R": (0.0, None)}                 # (t, ângulos filtrados): segura quedas curtas
    shrug_ref = [None]
    extras = {"twist": None, "shrug": [0.0, 0.0]}
    sm = {"L": None, "R": None}
    last_sent = None; last_ok = 0.0
    from collections import deque
    hist = deque(maxlen=40)
    last_cls = 0.0
    shw_ref = [0.0]
    def arm(k, si, ei, wi):
        S, E, W = k[si], k[ei], k[wi]
        if S[2] < 0.45 or E[2] < 0.40:
            return None
        u = E[:2] - S[:2]; nu = float(np.linalg.norm(u))
        if nu < 4: return None
        theta = float(np.arccos(np.clip(u[1] / nu, -1, 1)))          # 0 = braço pendurado, pi = para cima
        # encurtamento: braço apontando para a câmera aparece curto em relação à largura dos ombros -> avanço (flexão do ombro)
        shw = shw_ref[0]
        fwd = 0.0
        if shw > 20:
            fwd = float(np.clip(1.0 - (nu / (0.62 * shw)), 0.0, 1.0))
        bend = 0.25
        if W[2] > 0.35:
            f = W[:2] - E[:2]; nf = float(np.linalg.norm(f))
            if nf > 3:
                bend = float(np.arccos(np.clip(np.dot(u, f) / (nu * nf), -1, 1)))
        # limites = faixa dos gestos já validados no rig (fora dela os volumes do braço quebram/descolam)
        s_ = 0.05 + theta * 0.40 + fwd * 0.50
        a_ = theta * 0.40 * (1.0 - 0.7 * fwd)
        return [min(0.95, max(0.05, s_)), min(0.55, max(-0.1, a_)), min(2.0, max(0.12, bend * 0.9))]
    while True:
        fr = _shared["frame"]
        if fr is None or not camera_on:
            time.sleep(0.2); continue
        h, w = fr.shape[:2]
        sc = 640.0 / w
        img = cv2.resize(fr, (640, int(h * sc)))
        pad = (640 - img.shape[0]) // 2
        canvas = np.full((640, 640, 3), 114, np.uint8); canvas[pad:pad + img.shape[0]] = img
        blob = (canvas[:, :, ::-1].astype("float32") / 255.0).transpose(2, 0, 1)[None]
        out = sess.run(None, {name: blob})[0][0].T                    # 8400 x 56
        i = int(np.argmax(out[:, 4])); det = out[i]
        res = {"L": None, "R": None}
        if det[4] > 0.45:
            k = det[5:].reshape(17, 3).copy(); k[:, 1] -= pad
            shw_ref[0] = float(np.linalg.norm(k[5][:2] - k[6][:2])) if (k[5][2] > 0.45 and k[6][2] > 0.45) else shw_ref[0]
            res = {"L": None, "R": None} if bp is not None else {"L": arm(k, 5, 7, 9), "R": arm(k, 6, 8, 10)}   # 2D só sem pose 3D (não mistura parametrizações)
            extras = {"twist": None, "shrug": [0.0, 0.0]}
            if bp is not None:
                try:
                    bx = ((det[0] - det[2] / 2) / sc, (det[1] - pad - det[3] / 2) / sc,
                          (det[0] + det[2] / 2) / sc, (det[1] - pad + det[3] / 2) / sc)
                    r3 = bp.infer(fr, bx)
                except Exception as e:
                    r3 = None; print("pose3d:", e, flush=True)
                if r3 is not None:
                    Wd, Pv = r3["w"], r3["px"]
                    A3 = np.stack([-Wd[:, 0], -Wd[:, 1], -0.6 * Wd[:, 2]], 1)   # espelhado (câmera não espelhada), y p/ cima, z p/ o espectador (profundidade atenuada: é o eixo mais ruidoso)
                    for sd, (si, ei, wi), side in (("L", (11, 13, 15), -1), ("R", (12, 14, 16), 1)):
                        if Pv[si, 3] > 0.7 and Pv[ei, 3] > 0.6 and Pv[wi, 3] > 0.5:
                            v = artic.arm_angles(A3[si], A3[ei], A3[wi], side, prev3[sd])
                            if v is not None:
                                tn = time.time()
                                pv = prev3[sd]
                                if pv is not None:                       # rejeita saltos espúrios (máx. ~7 rad/s)
                                    v = tuple(artic.step_limit(pv[i], v[i], 0.30) for i in range(4))
                                prev3[sd] = v
                                fv = [filt[sd][i](med[sd][i](v[i]), tn) for i in range(4)]
                                last_arm_ok[0] = tn
                                res[sd] = fv
                                last_good[sd] = (tn, fv)
                    if (TRACK_TWIST or TRACK_SHRUG) and Pv[11, 3] > 0.6 and Pv[12, 3] > 0.6:
                        sv = A3[12] - A3[11]
                        extras["twist"] = f_tw(float(np.clip(np.arctan2(-sv[2], sv[0]), -0.5, 0.5)), time.time())
                        shw3 = abs(sv[0]) + 1e-6
                        if Pv[7, 3] > 0.5 and Pv[8, 3] > 0.5:
                            for q, (ear, sh) in enumerate(((7, 11), (8, 12))):
                                r_ = (A3[ear][1] - A3[sh][1]) / shw3          # orelha acima do ombro
                                shrug_ref[0] = r_ if shrug_ref[0] is None else shrug_ref[0] + (max(r_, shrug_ref[0]) - shrug_ref[0]) * 0.02
                                extras["shrug"][q] = f_sh[q](float(np.clip((shrug_ref[0] - r_) * 0.8, 0.0, 0.3)), time.time())
        if det[4] > 0.45:
            hist.append((time.time(), k.copy()))
        else:
            hist.clear()
        if time.time() - last_cls > 0.3 and len(hist) >= 8:
            last_cls = time.time()
            while hist and time.time() - hist[0][0] > 2.2:
                hist.popleft()
            try:
                for g in classify_gestures(list(hist)):
                    nowg = time.time()
                    if nowg - GEST_COOLDOWN.get(g, 0) < (25.0 if g.startswith("disse") else 6.0):
                        continue
                    GEST_COOLDOWN[g] = nowg
                    scene["gesto"] = (g, nowg)
                    print("gesto:", g, flush=True)
                    asyncio.run_coroutine_threadsafe(broadcast({"type": "gesto", "kind": g}), loop)
                    if g == "acenou" and not (nowg - scene.get("harm_t", 0) < 1.5 or (bp is not None and nowg - last_arm_ok[0] < 1.5)):
                        asyncio.run_coroutine_threadsafe(broadcast({"type": "wave", "on": True, "side": 1}), loop)
                    asyncio.run_coroutine_threadsafe(reagir(g), loop)
                    hist.clear()
                    break
            except Exception as e:
                print("gestos:", e, flush=True)
        gest = []
        if det[4] > 0.45:
            for nome_g, wi, si in (("mão esquerda levantada", 9, 5), ("mão direita levantada", 10, 6)):
                if k[wi][2] > 0.4 and k[si][2] > 0.4 and k[wi][1] < k[si][1] - 12:
                    gest.append(nome_g)
        scene["gestos"] = gest; scene["t_gest"] = time.time()
        if det[4] > 0.45:
            wr = {}
            for lado, wi in (("mão esquerda", 9), ("mão direita", 10)):
                if k[wi][2] > 0.20:
                    wr[lado] = (float(k[wi][0] / sc), float(k[wi][1] / sc))      # k já está sem o padding vertical
            scene["wrists"] = wr; scene["t_wr"] = time.time()
            scene["fa"] = {"L": (float(k[9][0] - k[7][0]), float(k[9][1] - k[7][1])),
                           "R": (float(k[10][0] - k[8][0]), float(k[10][1] - k[8][1]))}
        _now = time.time()
        for side in ("L", "R"):                                         # mão visível => braço correspondente copia a posição/altura da mão
            h_ = (scene.get("harm") or {}).get(side)
            if h_ and _now - h_[0] < 0.45:
                res[side] = list(h_[1])
                scene["harm_t"] = _now
        if bp is not None:                                              # queda curta de detecção: mantém o último valor (sem tremer p/ repouso)
            for side in ("L", "R"):
                if res[side] is None and last_good[side][1] is not None and time.time() - last_good[side][0] < 0.45:
                    res[side] = last_good[side][1]
        for side in ("L", "R"):
            v = res[side]
            if v is None:
                sm[side] = None
                if bp is not None:
                    prev3[side] = None
                    for fq in filt[side]: fq.reset()
                    for mq in med[side]: mq.reset()
            elif sm[side] is None or len(sm[side]) != len(v): sm[side] = list(v)
            else: sm[side] = [a + (b - a) * (0.6 if bp is not None else 0.45) for a, b in zip(sm[side], v)]
        cur = {side: ([round(x, 2) for x in sm[side]] if sm[side] else None) for side in sm}
        cur["tw"] = round(extras["twist"], 2) if extras["twist"] is not None else None
        cur["sh"] = [round(x, 2) for x in extras["shrug"]]
        now = time.time()
        if cur != last_sent and (cur["L"] or cur["R"] or last_sent and (last_sent["L"] or last_sent["R"])):
            last_sent = cur
            asyncio.run_coroutine_threadsafe(broadcast({"type": "pose", "L": cur["L"], "R": cur["R"], "tw": cur["tw"], "sh": cur["sh"]}), loop)
        time.sleep(0.25 if time.time() - scene["t"] < 8 else 1.0)       # pose 2D (gestos): ~4 fps com gente à vista, 1 fps sem ninguém


HALLU_RE = re.compile(r"(legendas?\b|inscreva|obrigad[oa] por assistir|tchau,? at[ée]|amara\.org|www\.|\.com\b|"
                      r"transcri[çc][ãa]o|\[.*?\])", re.I)      # "música" saiu daqui: descartava pedidos reais ("coloque a música...")


_stt_cache = {"t": 0.0, "p": "", "titulos": []}


def _stt_prompt():
    """vocabulário do Whisper: palavra de ativação + termos do sistema + títulos das janelas abertas."""
    base = (
        "Sexta-Feira. Pare. Pule. Antigravity, abra o Antigravity. "
        "ChatGPT, abra o ChatGPT. Chromium, ZapZap, WhatsApp. "
        "Tarefa. Etapa. Documento, Word, docx, planilha, Excel, slides, apresentação, PowerPoint. "
        "Navegador, pesquisa. Mensagens, Eduardo Becker, Wander, sessões, datas, encaminhar, enviar, ler. "
        "Me localize, me localiza, seguir, parar. Vire para a direita, vire para a esquerda. "
        "Olhe para a porta, a cama, o guarda-roupa. Desativar modo mão livre. Ativar modo mão livre. "
        "Pedidos no imperativo: abre, abra, desbloqueia, desbloqueie, procura, pesquisa, cria, crie, coloca, toca, manda, envia, faz, mostra. "   # 19/10: medido 95% -> 98% (vinha 'Desbloquei', 'abri')
        "Modo dev, Integra Site, Integra Code, Claude, YouTube."
    )
    if time.time() - _stt_cache["t"] > 4:
        _stt_cache["t"] = time.time()
        try:
            ws = json.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=2).stdout or "[]")
            tit = []
            for w in ws:
                t_ = re.sub(r"\s*[-–—]\s*(Chromium|YouTube|Google Chrome|Firefox|ZapZap|WhatsApp)\b.*$", "", str(w.get("title") or ""))
                t_ = re.sub(r"^[◐◑◒◓●○⠁-⣿\W]+", "", t_).strip()
                if 3 <= len(t_) <= 70 and t_ not in tit:
                    tit.append(t_)
            _stt_cache["titulos"] = tit[:6]
        except Exception:
            _stt_cache["titulos"] = []
        _stt_cache["p"] = base + (" Na tela: " + "; ".join(_stt_cache["titulos"]) + "." if _stt_cache["titulos"] else "")
    return _stt_cache["p"] or base


def _eh_eco_do_prompt(txt):
    """Whisper em ruído às vezes devolve o próprio prompt: descarta se a fala for só um dos títulos/frases do vocabulário."""
    n = _norm_eco(txt)
    return bool(n) and any(n == _norm_eco(x) for x in _stt_cache["titulos"] + ["sexta-feira, ligar. sexta-feira, desligar.", "chatgpt, chromium, onlyoffice, youtube, whatsapp."])


def mouse_real_thread(loop=None):
    """Acompanha o MOUSE FÍSICO (evdev cru, sem lib) e soma os deslocamentos à posição que o `pc` usa (/tmp/prometheus-pc-pos.json).
    Atalhos de botões laterais do mouse:
      - Botão lateral 1 (code 275 / BTN_SIDE): Liga ou desliga a Sexta-Feira.
      - Botão lateral 2 (code 276 / BTN_EXTRA): Quando a Sexta-Feira estiver ligada, abre o painel de fala enquanto segurar (push-to-talk).
    Supervisionado: re-escaneia se o mouse for plugado depois do boot ou reconectado.
    """
    import glob, select, struct
    lp = loop or _main.get("loop")
    POS = "/tmp/prometheus-pc-pos.json"
    dx = dy = 0; last_w = 0.0
    ptt_ativo = False

    while True:
        devs = []
        dev_paths = sorted(set(glob.glob("/dev/input/by-id/*-event-mouse")))
        for p_ in dev_paths:
            try:
                devs.append(open(p_, "rb", buffering=0))
            except Exception:
                pass
        if not devs:
            time.sleep(3)
            continue
        try:
            o = next(iter(json.loads(subprocess.run(["niri", "msg", "--json", "outputs"], capture_output=True, text=True, timeout=3).stdout).values()))["logical"]
            W, H = o["width"], o["height"]
        except Exception:
            W, H = 1920, 1080

        try:
            while True:
                r, _, _ = select.select(devs, [], [], 0.05)
                current_loop = lp or _main.get("loop")
                for f in r:
                    try:
                        data = f.read(24 * 64)
                    except Exception:
                        raise OSError("mouse desconectado")
                    for i in range(0, len(data) - 23, 24):
                        _s, _us, typ, code, val = struct.unpack("llHHi", data[i:i + 24])
                        if typ == 2 and code == 0:
                            dx += val
                        elif typ == 2 and code == 1:
                            dy += val
                        elif typ == 1:
                            # Botão lateral 1 (code 275): liga / desliga a Sexta-Feira
                            if code == 275 and val == 1:
                                if current_loop:
                                    novo_on = not friday_state["on"]
                                    asyncio.run_coroutine_threadsafe(friday_set(novo_on), current_loop)
                                    asyncio.run_coroutine_threadsafe(speak("Sexta-feira ativada." if novo_on else "Sexta-feira em espera."), current_loop)
                            # Botão lateral 2 (code 276): push-to-talk enquanto segurar (sem abrir o chat: ele vai para o plugin)
                            elif code == 276:
                                if friday_state["on"] and current_loop:
                                    if val == 1:
                                        ptt_ativo = True
                                        asyncio.run_coroutine_threadsafe(set_state("listening"), current_loop)
                                    elif val == 0 and ptt_ativo:
                                        ptt_ativo = False
                                        if state["state"] == "listening":
                                            asyncio.run_coroutine_threadsafe(set_state("idle"), current_loop)
                if (dx or dy) and time.time() - last_w > 0.04:
                    try:
                        d = json.load(open(POS))
                    except Exception:
                        d = {"x": W // 2, "y": H // 2, "sync": 0}
                    d["x"] = max(0, min(W - 1, int(d.get("x", 0)) + dx)); d["y"] = max(0, min(H - 1, int(d.get("y", 0)) + dy))
                    d["user"] = time.time()
                    try:
                        json.dump(d, open(POS + ".tmp", "w")); os.replace(POS + ".tmp", POS)
                    except Exception:
                        pass
                    dx = dy = 0; last_w = time.time()
        except Exception:
            for f in devs:
                try:
                    f.close()
                except Exception:
                    pass
            time.sleep(2)


# ======================= OUVIDO: microfone limpo -> foco na voz do dono -> Parakeet =======================
# Comparativo (13/10/2026, CPU, FLEURS pt-BR + falas reais do dono): Whisper small 6,9% de erro / 1,1 s por fala;
# medium 5,2% / 3,0 s; large-v3-turbo 4,5% / 4,6 s; Parakeet TDT 0.6B v3 int8 4,8% / 0,4 s. Whisper fica de reserva.
_stt = {"motor": None, "rec": None, "whisper": None}
_HALLU_EN = re.compile(r"^\W*(thank(s| you)( (very )?much)?|okay|ok|yeah|yes|no|bye|hello|hi|you|hmm+|uh+|um+)\W*$", re.I)
voz_dono = None                       # voz.VozDono (impressão vocal do dono, TitaNet-L)
_voz_uso = {"t": 0.0}
cadastro = {"ativo": False, "amostras": [], "t0": 0.0}
CAD_N = 8
FRASES_CADASTRO = [
    "Sexta-feira, ligar.",
    "Abre o navegador e procura a previsão do tempo para amanhã.",
    "Qual é a minha agenda de quinta-feira à tarde?",
    "Manda uma mensagem no WhatsApp dizendo que eu chego em vinte minutos.",
    "Analisa o extrato do banco e me mostra os maiores gastos do mês.",
    "Aumenta o volume e coloca uma música tranquila para eu trabalhar.",
    "O rato roeu a roupa do rei de Roma, e a rainha, com raiva, resolveu remendar.",
    "Hoje o dia foi longo, mas o projeto avançou bastante.",
    "Sexta-feira, pare. Cancela isso, por favor.",
    "Sexta-feira, desligar.",
]


def _stt_carregar():
    if _stt["motor"]:
        return _stt["motor"]
    stt_motor = os.environ.get("FRIDAY_STT") or _voz_cfg().get("stt", "parakeet")
    if stt_motor == "parakeet":
        try:
            import sherpa_onnx
            d = os.path.join(ROOT, "models", "stt", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8")
            _stt["rec"] = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=f"{d}/encoder.int8.onnx", decoder=f"{d}/decoder.int8.onnx", joiner=f"{d}/joiner.int8.onnx",
                tokens=f"{d}/tokens.txt", num_threads=int(_voz_cfg().get("stt_threads", 6)), model_type="nemo_transducer",
                decoding_method="greedy_search")
            _stt["motor"] = "parakeet"
            print("STT: Parakeet TDT 0.6B v3 (int8, CPU)", flush=True)
            return "parakeet"
        except Exception as e:
            print("Parakeet indisponível, usando Whisper:", str(e)[:120], flush=True)
    import stt_servidor
    for _ in range(40):                                  # servidor de STT (processo próprio, ~40% mais rápido): espera ele subir
        if stt_servidor.disponivel():
            _stt["whisper"] = stt_servidor.Remoto()
            _stt["motor"] = "whisper"
            print("STT: Whisper no servidor friday-stt (processo próprio, núcleos P)", flush=True)
            return "whisper"
        if subprocess.run(["systemctl", "--user", "is-active", "--quiet", "friday-stt"]).returncode != 0:
            break
        time.sleep(0.5)
    return _stt_local()


def _stt_local():
    """Whisper dentro do daemon (reserva: sem o servidor friday-stt)."""
    from faster_whisper import WhisperModel
    whisper_model_name = os.environ.get("FRIDAY_WHISPER_MODEL") or _voz_cfg().get("whisper_model", "medium")
    stt_threads = int(_voz_cfg().get("stt_threads", 6))
    model_dir = os.path.join(ROOT, "models", "whisper", whisper_model_name)
    target = model_dir if os.path.exists(model_dir) else whisper_model_name
    _stt["whisper"] = WhisperModel(target, device="cpu", compute_type="int8",
                                   download_root=os.path.join(ROOT, "models", "whisper"), cpu_threads=stt_threads)
    _stt["motor"] = "whisper"
    print(f"STT: Whisper {whisper_model_name} (int8, CPU, {stt_threads} threads)", flush=True)
    return "whisper"


def _transcrever(audio):
    """-> (texto, bruto). Parakeet não usa dica (não alucina o prompt); filtra os 'Thank you.' que ele solta em ruído."""
    if _stt_carregar() == "parakeet":
        st_ = _stt["rec"].create_stream(); st_.accept_waveform(16000, audio); _stt["rec"].decode_stream(st_)
        bruto = st_.result.text.strip()
        if _HALLU_EN.match(bruto):
            return "", bruto
        # Parakeet "chutando" (média < -0,10 ou algum trecho < -0,9, calibrado 15/10): 2ª opinião do Whisper com o
        # vocabulário; só troca se o Whisper estiver confiante (> -0,30). Custa ~1,5 s só nas frases duvidosas.
        lp = list(getattr(st_.result, "ys_log_probs", []) or [])
        if lp and (sum(lp) / len(lp) < -0.10 or min(lp) < -0.9) and len(audio) > 16000 * 0.6:
            try:
                if _stt.get("whisper") is None:
                    from faster_whisper import WhisperModel
                    whisper_model_name = os.environ.get("FRIDAY_WHISPER_MODEL") or _voz_cfg().get("whisper_model", "medium")
                    model_dir = os.path.join(ROOT, "models", "whisper", whisper_model_name)
                    target = model_dir if os.path.exists(model_dir) else whisper_model_name
                    _stt["whisper"] = WhisperModel(target, device="cpu", compute_type="int8",
                                                   download_root=os.path.join(ROOT, "models", "whisper"),
                                                   cpu_threads=int(_voz_cfg().get("stt_threads", 6)))
                segs = list(_stt["whisper"].transcribe(audio, language="pt", beam_size=1, temperature=0.0, initial_prompt=_stt_prompt(),
                                                       condition_on_previous_text=False, vad_filter=True)[0])
                w_txt = " ".join(x.text.strip() for x in segs).strip()
                w_lp = sum(x.avg_logprob for x in segs) / len(segs) if segs else -9
                usa = bool(w_txt) and w_lp > -0.80 and not _eh_eco_do_prompt(w_txt)
                with open("/tmp/friday-stt.log", "a") as f_:
                    f_.write(f"{time.strftime('%H:%M:%S')} parakeet[{sum(lp) / len(lp):.2f}/{min(lp):.2f}] {bruto!r} | "
                             f"whisper[{w_lp:.2f}] {w_txt!r} -> {'WHISPER' if usa else 'parakeet'}\n")
                if usa:
                    return w_txt, bruto
            except Exception as e_:
                print("2ª opinião STT falhou:", repr(e_)[:120], flush=True)
        return bruto, bruto
    _kw = dict(language="pt", vad_filter=True, vad_parameters=dict(threshold=0.45, min_silence_duration_ms=400, speech_pad_ms=200),
               beam_size=1, condition_on_previous_text=False, temperature=0.0, initial_prompt=_stt_prompt(),
               no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4,
               without_timestamps=True)                                # -0,2 s/frase medido (16/10), mesmo texto
    try:
        segs, _ = _stt["whisper"].transcribe(audio, **_kw)
    except Exception as e_:                                            # servidor de STT caiu: segue com o modelo local
        print("STT servidor falhou, usando o local:", repr(e_)[:120], flush=True)
        _stt["motor"] = None
        _stt_local()
        segs, _ = _stt["whisper"].transcribe(audio, **_kw)
    segs = list(segs)
    bruto = " ".join(x.text.strip() for x in segs).strip()
    if _eh_eco_do_prompt(bruto):
        return "", bruto
    segs = [x for x in segs if x.no_speech_prob < 0.80 and x.avg_logprob > -1.5 and getattr(x, "compression_ratio", 0) < 2.6]
    return " ".join(x.text.strip() for x in segs).strip(), bruto


def _wake_fix(txt):
    """Normaliza o nome 'Sexta-feira' quando sai com grafia distorcida ou aproximada pelo STT."""
    if not txt:
        return txt
    # Remove ruídos iniciais comuns como "concern, "
    txt = re.sub(r"^\W*(?:concern,?\s*)?", "", txt, flags=re.I)
    # Normalização geral do chamado no início da frase: "Sextha Fira", "Sesta feira", "Seita feira", "Questa feira", "Sutta Fira", etc.
    txt = re.sub(r"^\W*(?:(?:sextha|sesta|seita|cesta|sexta|questa|sutta|sta|sueta|seta|seira|sextas|stafeira|sophia'?s?)[ -]?(?:feira|fira|fear|fire|fechando|feita|feito)?|(?:esta|ésta|essa|éssa|senta|tinta)[ -](?:feira|fira|fear|fire|fechando|feita|feito)|friday)\b[,:]?\s*", "Sexta-feira, ", txt, flags=re.I)
    import difflib
    if fr is not None and (fr.WAKE_ON.search(txt) or fr.WAKE_OFF.search(txt)):
        return txt
    m = re.search(r"\b(lig(ar|a|ue)|ativ(ar|a|e)|acord(ar|a|e)|deslig(ar|a|ue)|desativ(ar|a|e))\b", txt, re.I)
    if m:
        antes = re.findall(r"\w+", txt[:m.start()].lower())
        if 1 <= len(antes) <= 4:
            a = "".join(c for c in unicodedata.normalize("NFD", " ".join(antes)) if unicodedata.category(c) != "Mn")
            if difflib.SequenceMatcher(None, a, "sexta feira").ratio() >= 0.45 or re.match(r"(voce )?esta fe(i|r|ch)", a):
                return "Sexta-feira, " + txt[m.start():]
    return txt


_mic_cache = {"t": 0.0, "dev": None}


def _mic_limpo():
    """fonte 'friday_mic' (eco/ruído cancelados no PipeWire). Sobe o filtro se preciso; None = microfone padrão."""
    if win_compat.IS_WINDOWS:
        return None
    if time.time() - _mic_cache["t"] < 20:
        return _mic_cache["dev"]
    _mic_cache["t"] = time.time()
    if not _voz_cfg().get("mic_limpo", True):
        _mic_cache["dev"] = None; return None
    def tem():
        try:
            return "friday_mic" in subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return False
    if not tem():
        try:
            subprocess.run([os.path.join(ROOT, "daemon", "audio", "microfone"), "iniciar"], capture_output=True, timeout=20)
            _mic_cache["reiniciou"] = True
        except Exception as e:
            print("microfone limpo falhou:", e, flush=True)
    _mic_cache["dev"] = "friday_mic" if tem() else None
    return _mic_cache["dev"]


def _portao_v2():
    return _voz_cfg().get("portao", "v2") != "v1"


FAIXA_MIN = 0.26                     # portão v2: abaixo disso descarta sem STT


def _ha_pendente(janela=15.0):
    """aprovação pendente, oferta ou pergunta dela há < janela s (faixa média do portão v2 aceita a resposta)"""
    agora = time.time()
    if agora - _pergunta_t[0] < janela or (oferta.get("tarefa") and agora - oferta.get("t", 0) < janela):
        return True
    try:
        return ops is not None and any(i["estado"] == "pendente" and agora - float(i.get("t", i.get("criado", agora)) or agora) < janela
                                       for i in ops.approvals())
    except Exception:
        return False


def _silero_fala(audio):
    """segundos de fala segundo o Silero VAD (faster_whisper/assets/silero_vad_v6.onnx, onnxruntime). None = indisponível."""
    try:
        from faster_whisper.vad import get_speech_timestamps, VadOptions
        ts = get_speech_timestamps(audio, VadOptions(threshold=0.5, min_silence_duration_ms=100, speech_pad_ms=0))
        return sum(t["end"] - t["start"] for t in ts) / 16000
    except Exception as e:
        print("silero vad:", e, flush=True)
        return None


def _centro_cadastro():
    """centróide só das amostras do CADASTRO ('inicial'): âncora fixa p/ o enrolamento contínuo não derivar"""
    import numpy as np
    E = [np.array(a["e"], dtype="float32") for a in voz_dono.dados["amostras"] if a.get("fonte") == "inicial"]
    if not E:
        return None
    c = np.mean(E, 0)
    return c / np.linalg.norm(c)


def _foco_voz(audio, loop=None):
    """foco total na voz do dono: -> (aceitar, áudio (trechos de outra voz silenciados), info)."""
    if voz_dono is None or cadastro["ativo"] or not _voz_cfg().get("foco", True):
        _voz_ult.update(faixa=None, score=0.0, titanet=False, t=time.time())     # sem portão: voz não verificada
        return True, audio, {}
    dono_recente = (time.time() - owner_voice["t"] < 45) or (time.time() - conv.get("t", 0) < 45)
    estrito = bool(_voz_cfg().get("so_dono", True))                 # "só a minha voz" (dono, 16/10): amigos falando não passam nem dizendo o nome
    try:
        ok, out, info = voz_dono.decidir(audio, dono_recente=dono_recente, estrito=estrito)
    except Exception as e:
        print("foco de voz:", e, flush=True)
        _voz_ult.update(faixa=None, score=0.0, titanet=False, t=time.time())
        return True, audio, {}
    sc, lim = info.get("score", 0.0), voz_dono.limiar
    v2 = _portao_v2()
    if estrito and voz_dono.pronto:                               # só plena ou descarta: sem faixa média por nome/pendência
        info["faixa"] = "plena" if ok else "descarta"
    elif v2:                                                        # três faixas: plena (>= lim) | média (só com nome/pendência, após STT) | descarta
        alone = len(scene.get("faces", [])) == 1
        _jan = info.get("janelas") or []
        _maioria = not _jan or sum(1 for x in _jan if x >= lim - 0.08) / len(_jan) >= 0.5
        if not voz_dono.pronto or (ok and sc >= lim and _maioria):
            info["faixa"] = "plena"                       # plena = limiar REAL (sem os descontos de fala curta/dono recente) e maioria das janelas dele
        elif ok or sc >= FAIXA_MIN:                       # descontos e recortes só valem na faixa média (exige nome ou pendência)
            if ok and sc >= FAIXA_MIN and not (sc >= lim and _maioria):
                info["motivo"] = f"faixa média ({info.get('motivo', '')}; plena exige score>={lim:.2f} e maioria das janelas)"
            else:
                info["motivo"] = "faixa média (exige nome ou pendência)"
            ok, info["faixa"] = (True, "media") if sc >= FAIXA_MIN else (False, "descarta")
        elif False:
            ok, info["faixa"] = True, "media"
            info["motivo"] = "faixa média (exige nome ou pendência)"
        else:
            info["faixa"] = "descarta"
    else:
        info["faixa"] = "plena" if ok else "descarta"
    voz.log(f"{'ACEITA' if ok else 'IGNORA'} score={sc:.2f} lim={lim:.2f} dur={info.get('dur')}s faixa={info.get('faixa')} {info.get('motivo', '')} {info.get('janelas', '')}")
    _voz_ult.update(faixa=info.get("faixa"), score=sc, titanet=bool(voz_dono.pronto), t=time.time())
    if ok and voz_dono.pronto and sc >= lim - 0.06 and (not v2 or info["faixa"] == "plena"):
        owner_voice["t"] = time.time(); current_speaker["nome"] = _owner_name()
        if sc >= lim + 0.12 and info.get("dur", 0) >= 1.2 and time.time() - _voz_uso["t"] > 60:
            _cc = _centro_cadastro() if v2 else None
            _cos = float(info["emb"] @ _cc) if (_cc is not None and info.get("emb") is not None) else 1.0
            if not v2 or _cos >= 0.5:
                _voz_uso["t"] = time.time()
                voz_dono.adicionar(info.get("emb"), "uso")   # o perfil se adapta ao microfone/ambiente (só entra com cos>=0,5 contra o cadastro)
            else:
                voz.log(f"enrolamento recusado: cos_cadastro={_cos:.2f} < 0.50")
    elif not ok and loop is not None and sc > lim - 0.12:       # quase passou: pode ser ele com a voz diferente
        asyncio.run_coroutine_threadsafe(broadcast({"type": "friday_heard", "text": "(não reconheci sua voz — fala de novo?)"}), loop)
    return ok, out, info


def _cadastro_amostra(audio, loop):
    import numpy as np
    if voz_dono is None or len(audio) < 16000 * 1.0:
        return
    emb = voz_dono.embed(audio)
    if emb is None:
        return
    am = cadastro["amostras"]
    if len(am) >= 2:
        c = np.mean(am, 0); c = c / np.linalg.norm(c)
        if float(emb @ c) < 0.35:                                # destoa das anteriores: outra voz/ruído
            voz.log(f"cadastro: amostra destoante ({float(emb @ c):.2f}) ignorada")
            asyncio.run_coroutine_threadsafe(broadcast({"type": "friday_heard", "text": "(essa não pareceu a sua voz — repete, por favor)"}), loop)
            return
    am.append(emb)
    asyncio.run_coroutine_threadsafe(broadcast({"type": "text", "role": "tool", "text": f"cadastro de voz: amostra {len(am)} de {CAD_N} ✓"}), loop)
    asyncio.run_coroutine_threadsafe(broadcast({"type": "friday_heard", "text": f"✓ amostra {len(am)} de {CAD_N}"}), loop)


def _mics_gravar_inicio():
    """durante o cadastro grava TODAS as entradas físicas em paralelo, para escolher o microfone que melhor capta a voz dele."""
    out = {}
    if win_compat.IS_WINDOWS:
        return out
    try:
        fontes = [l.split("\t")[1] for l in subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=5).stdout.splitlines()
                  if "\t" in l and l.split("\t")[1].startswith("alsa_input")]
    except Exception:
        fontes = []
    for i, f in enumerate(fontes):
        p_ = f"/tmp/friday-mic-teste-{i}.raw"
        try:
            out[f] = (subprocess.Popen(["parecord", "--raw", "--format=s16le", "--rate=16000", "--channels=1", f"--device={f}"],
                                       stdout=open(p_, "wb"), stderr=subprocess.DEVNULL), p_)
        except Exception:
            pass
    return out


def _mics_gravar_fim(mics):
    import numpy as np
    rel = {}
    for f, (proc, p_) in mics.items():
        try:
            proc.terminate(); proc.wait(timeout=3)
        except Exception:
            pass
        try:
            a = np.fromfile(p_, dtype=np.int16).astype("float32") / 32768
            os.remove(p_)                                         # áudio bruto não fica guardado
            if len(a) < 16000 * 5:
                continue
            e = np.sqrt((a[: len(a) // 480 * 480].reshape(-1, 480) ** 2).mean(1)) + 1e-7
            rel[f] = {"snr": round(float(20 * np.log10(np.percentile(e, 90) / np.percentile(e, 20))), 1),
                      "clip": round(float((np.abs(a) > 0.985).mean() * 100), 3)}
        except Exception:
            pass
    return rel


async def run_cadastro_voz():
    """o dono lê frases na tela; cada fala vira uma amostra da impressão vocal (só embeddings, nada de áudio guardado)."""
    import numpy as np
    if voz_dono is None:
        await _dizer("O módulo de voz ainda está carregando. Tenta de novo daqui a pouco.")
        return
    if cadastro["ativo"]:
        return
    lista = "\n".join(f"{i}. {f_}" for i, f_ in enumerate(FRASES_CADASTRO, 1))
    await broadcast({"type": "text", "role": "assistant", "text": "Cadastro da sua voz: lê em voz alta, uma de cada vez:\n" + lista})
    if ops is not None:
        ops.holo_show({"kind": "email", "para": "Cadastro da sua voz", "assunto": "Leia em voz alta, uma frase de cada vez",
                       "corpo": lista, "status": "ouvindo", "titulo": "Sua voz", "ttl": 240})
    await _dizer("Vamos cadastrar a sua voz. Lê em voz alta as frases da tela, uma de cada vez, no seu tom normal. Pode começar.")
    await asyncio.sleep(0.8)
    mics = await asyncio.to_thread(_mics_gravar_inicio)
    cadastro.update(ativo=True, amostras=[], t0=time.time())
    t_lim = time.time() + 180
    while time.time() < t_lim and len(cadastro["amostras"]) < CAD_N and cadastro["ativo"]:
        await asyncio.sleep(0.5)
    cadastro["ativo"] = False
    rel = await asyncio.to_thread(_mics_gravar_fim, mics)
    am = list(cadastro["amostras"])
    if len(am) < 4:
        await _dizer(f"Só consegui {len(am)} amostras boas. Vamos tentar de novo quando estiver mais silencioso.")
        return
    c = np.mean(am, 0); c = c / np.linalg.norm(c)
    am = [e for e in am if float(e @ c) >= 0.4]
    voz_dono.dados["amostras"] = [a for a in voz_dono.dados["amostras"] if a.get("fonte") == "cadastro"]   # troca as iniciais (outro caminho de áudio)
    for e in am:
        voz_dono.adicionar(e, "cadastro", salvar=False)
    res = voz_dono.calibrar()
    det = (f"Voz cadastrada: {len(am)} amostras. Consistência {res.get('dono_med', 0):.2f}, outras vozes até {res.get('outros_max', 0):.2f}, "
           f"limiar {res.get('limiar', 0):.2f} (margem {res.get('margem', 0):+.2f}).")
    if rel:
        det += " Microfones: " + "; ".join(f"{k.split('.')[0].replace('alsa_input', '')[-24:]} SNR {v['snr']} dB, clipping {v['clip']}%" for k, v in rel.items())
    await broadcast({"type": "text", "role": "tool", "text": det}); voz.log(det)
    atual = _voz_cfg().get("mic") or ""
    bons = {k: v for k, v in rel.items() if v["clip"] < 0.05}
    if bons and atual in rel:
        melhor = max(bons, key=lambda k: bons[k]["snr"])
        if melhor != atual and bons[melhor]["snr"] >= rel[atual]["snr"] + 6:
            cfg = _voz_cfg(); cfg["mic"] = melhor
            json.dump(cfg, open(os.path.join(MEM_DIR, "voz.json"), "w"))
            subprocess.run([os.path.join(ROOT, "daemon", "audio", "microfone"), "parar"], capture_output=True, timeout=10)
            _mic_cache["t"] = 0.0
            await broadcast({"type": "text", "role": "tool", "text": f"microfone trocado para {melhor} (capta melhor a sua voz)"})
    await _dizer(f"Pronto, aprendi a sua voz com {len(am)} amostras. A partir de agora eu só obedeço a você.")


async def run_voz_acao(op: str, a: dict):
    """ações de voz: cadastrar | status | esquecer | foco_liga | foco_desliga | trocar (voz dela)."""
    cfg = _voz_cfg()
    if op == "cadastrar":
        asyncio.create_task(run_cadastro_voz()); return
    if op in ("foco_liga", "foco_desliga"):
        cfg["foco"] = op == "foco_liga"
        json.dump(cfg, open(os.path.join(MEM_DIR, "voz.json"), "w"))
        await _dizer("Certo, só escuto você agora." if cfg["foco"] else "Tá, vou ouvir qualquer pessoa por enquanto.")
        return
    if op == "esquecer" and voz_dono is not None:
        voz_dono.esquecer()
        await _dizer("Apaguei a sua impressão vocal. Quando quiser, é só pedir para eu aprender de novo.")
        return
    if op == "trocar":
        nome = str(a.get("nome", "")).strip().lower()
        if nome not in ("jane", "azelma", "lola", "cosette", "anna", "fantine", "mary", "eve", "vera"):
            await _dizer("As vozes femininas que eu tenho são jane, azelma, lola e cosette."); return
        cfg["tts_voz"] = nome
        json.dump(cfg, open(os.path.join(MEM_DIR, "voz.json"), "w"))
        await _dizer("Pronto, essa é a minha voz nova. Gostou?")
        return
    if voz_dono is None or not voz_dono.pronto:
        await _dizer("Ainda não tenho a sua voz cadastrada. Quer cadastrar agora?"); return
    cal = voz_dono.dados.get("calib", {})
    await _dizer(f"Tenho {len(voz_dono.dados['amostras'])} amostras da sua voz. Foco {'ligado' if cfg.get('foco', True) else 'desligado'}, "
                 f"e a separação para outras vozes está {'ótima' if cal.get('dono_p10', 0) - cal.get('outros_max', 1) > 0.15 else 'razoável'}.")


_sons = {"ult": [], "aviso": {}}      # sons do ambiente: [(t, nome AudioSet, prob)] dos últimos 60 s


_evento_ult = {}                     # tipo -> instante do último (uma campainha não engole a entrada pela porta)
_evento_lock = threading.Lock()


def _evento_autonomo(desc, loop=None, tipo="geral"):
    """algo aconteceu no quarto: o CÉREBRO decide se investiga (câmeras) e se avisa. Vale de qualquer thread."""
    lp = loop or _main.get("loop")
    agora = time.time()
    with _evento_lock:
        if lp is None or agora - _evento_ult.get(tipo, 0.0) < 45 or agente_ativo[0] or modes.get("privacidade"):
            print(f"{time.strftime('%H:%M:%S')} evento ignorado (ocupada/recente/privacidade): {desc}", flush=True)
            return
        _evento_ult[tipo] = agora
    print(f"{time.strftime('%H:%M:%S')} evento autônomo: {desc}", flush=True)

    async def _rodar():
        try:
            import cerebro as _c
            if _c.modo() != "ativo" or fr is None:
                await speak(desc[:1].upper() + desc[1:] + ".")
                return
            if agente_ativo[0]:                     # checa+marca no loop (sem await no meio): 2 eventos não rodam juntos
                print(f"{time.strftime('%H:%M:%S')} evento ignorado (ocupada): {desc}", flush=True)
                return
            agente_ativo[0] = True
            try:
                r_ = await asyncio.to_thread(_c.run, _c.EVENTO.format(desc=desc, nome=mem.get("nome") or "Iann"), _friday_ctx(), fr, ops,
                                             None, None, mem.get("nome") or "Iann")
            finally:
                agente_ativo[0] = False
                _proxima_da_fila()
            fala_ = str(r_.get("fala") or "").strip()
            if fala_ and not re.fullmatch(r"\W*nada\W*", fala_, re.I):
                await broadcast({"type": "text", "role": "assistant", "text": fala_})
                log_turn("prometheus", fala_)
                if not modes.get("silencio"):
                    await speak(fala_)
        except Exception as e_:
            print("evento autônomo:", repr(e_), flush=True)
    asyncio.run_coroutine_threadsafe(_rodar(), lp)


def som_thread(loop):
    """ouvido do ambiente (som.py): microfone BRUTO num parecord próprio, janela de 2 s a cada 1 s. Não toca no STT."""
    import numpy as np
    try:
        import som
        ouv = som.Ouvido()
    except Exception as e:
        print("ouvido (sons) indisponível:", e, flush=True)
        return
    print("ouvido do ambiente: CED-mini (AudioSet 527 classes)", flush=True)
    while True:
        if not voice_on:                                # escuta desligada = privacidade: nem os sons
            time.sleep(0.5); continue
        mic = _voz_cfg().get("mic")
        if win_compat.IS_WINDOWS:
            rec = win_compat.criar_gravador_mic(rate=16000, chunk=16000, dev=mic)
        else:
            rec = subprocess.Popen(["parecord", "--raw", "--format=s16le", "--rate=16000", "--channels=1", "--latency-msec=200"]
                                   + ([f"--device={mic}"] if mic else []), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        jan = np.zeros(32000, np.float32)
        try:
            while voice_on:
                raw = rec.stdout.read(32000)            # 1 s de s16le 16 kHz
                if len(raw) < 32000:
                    break
                x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
                jan = np.concatenate([jan[16000:], x])
                if float(np.sqrt(np.mean(x * x))) < 0.004:
                    continue                            # silêncio: nem classifica
                ela = speaking or speak_lock.locked() or time.time() - _fim_fala[0] < 2.5
                agora = time.time()
                for nome, p, nota in ouv.classificar(jan, ignorar_fala=ela):
                    _sons["ult"].append((agora, nome, p))
                    if nota and agora - _sons["aviso"].get(nota, 0) > 90:
                        _sons["aviso"][nota] = agora
                        print(f"{time.strftime('%H:%M:%S')} som notável: {nome} ({p:.2f})", flush=True)
                        asyncio.run_coroutine_threadsafe(broadcast({"type": "som", "classe": nome, "p": p}), loop)
                        _evento_autonomo(f"o microfone ouviu {nota} ({nome}, {p:.0%} de certeza)", loop, tipo="som")
                _sons["ult"] = [s_ for s_ in _sons["ult"] if agora - s_[0] < 60][-30:]
        except Exception as e:
            print("ouvido:", repr(e), flush=True)
            time.sleep(2)
        finally:
            rec.terminate()
            try:
                rec.wait(2)
            except Exception:
                rec.kill()


def voice_thread(loop):
    """Escuta contínua: microfone limpo (friday_mic) 16 kHz -> VAD por energia -> foco na voz do dono -> Parakeet -> chat."""
    import array, math, subprocess
    try:
        import ctypes, glob
        for _pat in ("nvidia/cublas/lib/libcublasLt.so.12", "nvidia/cublas/lib/libcublas.so.12", "nvidia/cudnn/lib/libcudnn*.so.9"):
            for _lib in sorted(glob.glob(os.path.join(ROOT, ".venv/lib/python*/site-packages", _pat))):     # CUDA 12 do .venv p/ o Whisper na GPU
                try: ctypes.CDLL(_lib, mode=ctypes.RTLD_GLOBAL)
                except OSError: pass
        _stt_carregar()
    except Exception as e:
        print("STT indisponível:", e, flush=True); return
    global voz_dono
    try:
        voz_dono = voz.VozDono(threads=2)
        print(f"foco na voz do dono: {len(voz_dono.dados['amostras'])} amostras, limiar {voz_dono.limiar:.2f}", flush=True)
    except Exception as e:
        print("foco na voz indisponível:", e, flush=True)
    rate, chunk = 16000, 480            # 30 ms
    try:
        spk = senses.SpeakerID() if senses is not None else None
    except Exception as e:
        print("reconhecimento de voz indisponível:", e, flush=True); spk = None
    while True:
        if not voice_on:
            time.sleep(0.3); continue
        # parecord --raw: s16le sem cabeçalho (o pw-record "-" gerava .au big-endian -> áudio corrompido)
        _dev = _mic_limpo()                                     # eco/ruído cancelados no PipeWire (WebRTC); None = microfone padrão
        _mic_cache.pop("reiniciou", None)
        _t_rec = _chk_mic = time.time()
        rec = win_compat.criar_gravador_mic(rate=rate, chunk=chunk, dev=_dev)
        buf, voiced, silent = [], 0, 0
        _sat, _sat_t = 0, 0.0
        _bg = False
        floor = 0.004                                            # piso de ruído adaptativo
        _vh = []
        last_dump = 0.0
        asyncio.run_coroutine_threadsafe(set_state("listening"), loop)
        while voice_on:
            raw = rec.stdout.read(chunk * 2)
            if not raw or len(raw) < chunk * 2:
                break
            # continua ouvindo enquanto fala/executa: o que começar durante a fala dela só vale se for "pare..." ou o nome dela (eco)
            if os.path.exists("/tmp/prometheus-inject.raw"):  # autoteste: injeta um áudio (s16le 16 kHz mono) como se fosse o microfone
                try:
                    inj = open("/tmp/prometheus-inject.raw", "rb").read()
                    os.remove("/tmp/prometheus-inject.raw")
                    buf, voiced, silent = [inj], 30, 13
                except Exception:
                    pass
            a = array.array("h"); a.frombytes(raw)
            rms = math.sqrt(sum(x * x for x in a) / len(a)) / 32768
            _sat = _sat + 1 if rms > 0.5 else 0
            if _sat > 60 and time.time() - _sat_t > 30:         # microfone saturado (ganho no máximo = nunca ouve nada): baixa o ganho de hardware
                _sat_t = time.time()
                if not win_compat.IS_WINDOWS:
                    for _c in (["amixer", "-q", "-c", "1", "sset", "Capture", "35"], ["amixer", "-q", "-c", "1", "sset", "Internal Mic Boost", "1"],
                               ["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", "0.21"]):
                        try: subprocess.run(_c, capture_output=True, timeout=5)
                        except Exception: pass
                    print("microfone saturado: ganho reduzido", flush=True)
            if not voiced:                                       # piso = percentil 10 dos últimos ~5 s (não sobe com a fala)
                _vh.append(rms)
                if len(_vh) > 170:
                    _vh.pop(0)
                floor = sorted(_vh)[int(len(_vh) * 0.10)]
            thr = max(0.005, floor * 1.7) if voiced else max(0.009, floor * 2.4)      # histerese: início mais alto que continuação
            if speaking:
                thr *= 2.5                                       # falando: só voz próxima do microfone passa (o eco dela fica abaixo)
            _now = time.time()
            if _now - last_dump > 0.5:                           # diagnóstico: /tmp/prometheus-voice.json
                last_dump = _now
                try:
                    with open("/tmp/prometheus-voice.json", "w") as _f:
                        json.dump({"rms": round(rms, 4), "thr": round(thr, 4), "floor": round(floor, 4), "voiced": voiced}, _f)
                except Exception:
                    pass
            if _now - _chk_mic > 30 and not voiced:              # o filtro do microfone caiu? (o PipeWire joga a gravação p/ o mic bruto)
                _chk_mic = _now; _mic_cache["t"] = 0.0
                if _mic_limpo() != _dev or _mic_cache.pop("reiniciou", False):
                    print("microfone limpo restabelecido: reabrindo a gravação", flush=True)
                    break
            _fala_agora = bool(speaking) or speak_lock.locked() or time.time() - _fim_fala[0] < 2.5   # inclui o vão entre frases e o rabo do eco
            if rms > thr and voiced == 0:
                _bg = _fala_agora
            elif rms > thr and _fala_agora:
                _bg = True
            if rms > thr and len(buf) <= 700:                    # teto ~21 s: ruído contínuo acima do limiar nunca prende a escuta (já houve 102 s)
                voiced += 1; silent = 0; buf.append(raw)
                if voiced == 12 and not _fala_agora:              # ~0,4 s de voz: aquece o prefixo do cérebro na GPU enquanto ele fala/STT roda
                    try:
                        import cerebro as _cq
                        _cq.aquecer(mem.get("nome") or "Iann")
                    except Exception:
                        pass
                if voiced > 55 and voiced % 130 == 0:             # fala longa: acena de leve (escuta ativa)
                    asyncio.run_coroutine_threadsafe(broadcast({"type": "gesto", "kind": "disse sim com a cabeça"}), loop)
            elif voiced:
                silent += 1; buf.append(raw)
                # frase curta fecha com ~0,33 s de silêncio (resposta rápida); quanto mais longa a fala, mais pausa ela tolera (até ~1,1 s)
                if silent > (11 if voiced < 40 else 20 if voiced < 100 else 36):
                    if voiced > 9:                                   # fala curta demais (<~0,3 s) quase sempre é ruído
                        pcm = b"".join(buf)
                        try:
                            import wave as _wave
                            os.makedirs("/tmp/friday-utt", exist_ok=True)
                            with _wave.open(f"/tmp/friday-utt/utt_{time.strftime('%H%M%S')}.wav", "wb") as _w:
                                _w.setnchannels(1); _w.setsampwidth(2); _w.setframerate(16000); _w.writeframes(pcm)
                            _old = sorted(os.listdir("/tmp/friday-utt"))[:-40]
                            for _o in _old:
                                os.remove(os.path.join("/tmp/friday-utt", _o))
                        except Exception:
                            pass
                        import numpy as np
                        audio = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768
                        _t_utt = time.time()                           # vira _lat["utt"] só se a fala passar (rejeitada não mede latência)
                        _arms = float(np.sqrt((audio ** 2).mean()))
                        if _arms < 0.005:                              # ruído/respiração: o Whisper alucina "Obrigado", "Tchau"... em silêncio
                            try:
                                with open("/tmp/prometheus-ouvi.log", "a") as _lf:
                                    _lf.write(f"{time.strftime('%H:%M:%S')} dur={len(audio) / 16000:.1f}s IGNORADO (rms {_arms:.4f} baixo)\n")
                            except Exception:
                                pass
                            buf, voiced, silent = [], 0, 0
                            continue
                        try:                                            # filtro passa-alta ~100 Hz: tira zumbido/ruído grave antes do Whisper
                            from scipy.signal import butter, lfilter
                            _b, _a = butter(2, 100 / 8000, btype="high")
                            audio = lfilter(_b, _a, audio).astype("float32")
                        except Exception:
                            pass
                        peak = float(np.abs(audio).max())
                        if peak > 0:
                            audio = audio / peak * 0.8                       # normaliza p/ o Whisper
                        if _portao_v2() and not cadastro["ativo"]:           # portão Silero: rms é só pré-filtro; < 0,4 s de fala real = ruído
                            _sf = _silero_fala(audio)
                            if _sf is not None:
                                voz.log(f"silero fala={_sf:.2f}s dur={len(audio) / 16000:.1f}s {'REJEITA' if _sf < 0.4 else 'passa'}")
                                if _sf < 0.4:
                                    buf, voiced, silent = [], 0, 0
                                    continue
                        _foco_ok, audio, _vinfo = _foco_voz(audio, loop)       # só a voz do dono passa (TV, outras pessoas e o eco dela não)
                        if not _foco_ok:
                            try:
                                with open("/tmp/prometheus-ouvi.log", "a") as _lf:
                                    _lf.write(f"{time.strftime('%H:%M:%S')} dur={len(audio) / 16000:.1f}s IGNORADO (outra voz, score {_vinfo.get('score', 0):.2f})\n")
                            except Exception:
                                pass
                            buf, voiced, silent = [], 0, 0
                            continue
                        if cadastro["ativo"]:                                   # cadastro da voz: a fala vira amostra, não comando
                            _cadastro_amostra(audio, loop)
                            buf, voiced, silent = [], 0, 0
                            continue
                        _raw_txt = ""
                        try:
                            txt, _raw_txt = _transcrever(audio)
                            if re.fullmatch(r"\W*(obrigad[oa]s?|tchau|e a[ií]|ok|boa|valeu|legendas?.*|inscreva.*|até (a )?próxim[oa].*|m[úu]sica( de fundo)?|\(?m[úu]sica\)?)\W*", txt, re.I):
                                txt = ""                               # alucinação clássica em áudio fraco
                            txt = _wake_fix(txt)
                            _w = re.findall(r"\w+", txt.lower())
                            _cmd_unico = len(_w) == 1 and _w[0] in ("pare", "para", "cancela", "pule", "continua", "sim", "nao", "não", "ajuda", "volta")
                            if _portao_v2() and voz_dono is not None and voz_dono.pronto and _vinfo.get("score", 0) >= voz_dono.limiar:
                                _cmd_unico = len(_w) == 1                 # v2: palavra única vale se a voz é plenamente do dono
                            if (HALLU_RE.search(txt) or (len(_w) < 2 and not _cmd_unico) or (len(_w) >= 4 and len(set(_w)) <= len(_w) // 3)
                                    or re.fullmatch(r"(obrigad[oa]|tchau|até (mais|logo|a próxima)|é isso|tá bom|e aí|então|ok|hum+|ah+)[\W]*", txt.lower())):
                                txt = ""
                        except Exception as e:
                            txt = ""; print("stt erro:", e, flush=True)
                        if txt.strip():
                            print("ouvi:", txt, flush=True)
                            _lat["utt"] = _t_utt
                        try:
                            with open("/tmp/friday-timing.log", "a") as _tl:
                                _tl.write(f"{time.strftime('%H:%M:%S')} STT={time.time() - _t_utt:.1f}s {txt[:40]!r}\n")
                        except Exception:
                            pass
                        try:                                              # diagnóstico: o que o Whisper entendeu (stdout vai p/ /dev/null)
                            with open("/tmp/prometheus-ouvi.log", "a") as _lf:
                                _lf.write(f"{time.strftime('%H:%M:%S')} dur={len(audio) / 16000:.1f}s texto={txt!r} bruto={_raw_txt!r}\n")
                        except Exception:
                            pass
                        if txt and _vinfo.get("faixa") == "media" and not WAKE_RE.search(txt) and not _ha_pendente():
                            voz.log(f"faixa média sem nome/pendência: descarta {txt[:50]!r}")
                            txt = ""
                        if len(txt) > 2 and re.search(r"\w", txt):
                            _faixa_ult.update(f=_vinfo.get("faixa", "plena"), t=time.time())
                            if spk is not None and people is not None and len(audio) > 16000 * 1.0:
                                try:                                     # quem falou? (embedding local, nada sai do PC)
                                    emb = spk.embed(audio)
                                    if emb is not None:
                                        nome_v, sim_v, pid_v = people.match_voice(emb)
                                        _dono_ok = voz_dono is not None and voz_dono.pronto and _vinfo.get("score", 0) >= voz_dono.limiar
                                        if _dono_ok:                    # a impressão vocal (TitaNet) já confirmou o dono
                                            nome_v, sim_v, pid_v = _owner_name(), max(sim_v, float(_vinfo.get("score", 0))), people.find_by_name(_owner_name())
                                        last_voice.update(t=time.time(), emb=emb, nome=nome_v, sim=sim_v)
                                        current_speaker["nome"] = nome_v
                                        if nome_v and str(nome_v).lower() == _owner_name().lower() and sim_v >= 0.33 \
                                                and not (_portao_v2() and voz_dono is not None and voz_dono.pronto):   # v2: só o TitaNet marca o dono
                                            owner_voice["t"] = time.time()
                                        if pid_v and sim_v > 0.62:
                                            people.learn(pid_v, voice=emb)       # voz se refina com o uso
                                        elif not pid_v and time.time() - scene["t"] < 3:
                                            vis = [f for f in scene["faces"] if f["nome"]]
                                            if len(vis) == 1 and len(scene["faces"]) == 1:   # único rosto à vista: associa voz <-> rosto
                                                pid_f = vis[0]["pid"]
                                                if len(people.data["pessoas"][pid_f].get("vozes", [])) < 3:
                                                    people.learn(pid_f, voice=emb)
                                                    current_speaker["nome"] = vis[0]["nome"]
                                    print(f"voz: {current_speaker['nome'] or 'desconhecida'} ({last_voice['sim']:.2f})", flush=True)
                                except Exception as e:
                                    print("id de voz:", e, flush=True)
                            barge["v"] = _bg
                            barge["dono"] = bool(_vinfo.get("faixa") == "plena" and voz_dono is not None and voz_dono.pronto)   # voz do dono confirmada pelo TitaNet
                            asyncio.run_coroutine_threadsafe(route_speech(txt), loop)
                    buf, voiced, silent = [], 0, 0
            else:
                buf = buf[-10:] + [raw] if len(buf) > 10 else buf + [raw]
        rec.terminate()
        if time.time() - _t_rec < 3:                            # a gravação caiu na hora (filtro do microfone fora do ar?): revalida a fonte
            _mic_cache["t"] = 0.0; time.sleep(1.0)
        asyncio.run_coroutine_threadsafe(set_state("idle"), loop)


async def consolidate():
    """A cada ~12 trocas, resume o histórico em memory/resumo.md (memória de longo prazo)."""
    try:
        lines = open(LOG_FILE).read().splitlines()
        texto = "\n".join(f"{json.loads(l)['role']}: {json.loads(l)['text'][:300]}" for l in lines[-120:])
        antigo = open(SUM_FILE).read() if os.path.exists(SUM_FILE) else ""
        prompt = ("Atualize a memória de longo prazo do assistente Prometheus sobre o usuário. Em pt-BR, no máximo 25 linhas, "
                  "só fatos duráveis (quem é, preferências, projetos, combinados, pendências). Resumo anterior:\n" + antigo +
                  "\n\nConversas recentes:\n" + texto + "\n\nResponda SOMENTE com o novo resumo.")
        out = await asyncio.to_thread(fr.llm, "Você mantém a memória de longo prazo de uma assistente local. Responda só com o texto pedido, em markdown de lista (- item).",
                                      prompt, None, False, 700, 0.2, 120) if fr is not None else None
        if out and len(str(out).strip()) > 40:
            with open(SUM_FILE + ".tmp", "w") as f:
                f.write(str(out).strip())
            os.replace(SUM_FILE + ".tmp", SUM_FILE)
    except Exception as e:
        print("consolidação falhou:", e, flush=True)


async def stop():
    for p in (tts_proc, claude_proc):
        if p and p.returncode is None:
            p.terminate()


async def _cel_ui(m):
    """holograma do celular (CelularHolo.qml): mouse do PC -> celular real. x/y chegam normalizados 0..1."""
    t = m.get("type")
    try:
        import celular, celtela
        if t == "cel_tela_ui":
            await asyncio.to_thread(celtela.mostrar if m.get("on", True) else celtela.fechar)
            return
        ver = not celtela.ativo()                 # vídeo ao vivo: sem print depois de cada ação (mais rápido, poupa o celular)
        if t == "cel_tecla_ui":
            await asyncio.to_thread(celular.tecla, str(m.get("tecla", "voltar")), ver)
            return
        W, H = await asyncio.to_thread(celtela.real)
        n = lambda k: max(0.0, min(1.0, float(m.get(k, 0))))
        if t == "cel_toque_ui":
            ms = int(m.get("ms") or 0)
            if ms > 500:
                await asyncio.to_thread(celular.segurar, n("x") * W, n("y") * H, min(ms, 3000), ver)
            else:
                await asyncio.to_thread(celular.tocar, n("x") * W, n("y") * H, ver)
        elif t == "cel_arrastar_ui":
            await asyncio.to_thread(celular.arrastar, n("x0") * W, n("y0") * H, n("x1") * W, n("y1") * H, 14, ver)
    except Exception as e:
        print(f"[cel_ui] {t}: {e}", flush=True)


async def handle(r, w):
    global voice_on, camera_on
    clients.add(w)
    try:                                    # cliente que envia e fecha na hora (ex.: `pc`) não pode derrubar o handler
        await send(w, {"type": "state", "state": state["state"], "mood": state["mood"]})
        await send(w, {"type": "voice", "on": voice_on})
        await send(w, {"type": "camera", "on": camera_on})
        await send(w, {"type": "friday", "on": friday_state["on"]})
        await send(w, {"type": "modes", **modes})
        if time.time() - _INICIO_DAEMON < 30 and not hud_state.get("active"):   # holograma de tarefa morta (daemon reiniciado) ficava congelado no shell
            await send(w, {"type": "holo", "op": "clear", "spec": None})
            await send(w, {"type": "painel", "op": "fechar", "data": {}})   # 19/10: cartão "TAREFA · ..." de plano morto ficava na tela
    except Exception:
        pass
    try:
        items = []
        for l in open(LOG_FILE).read().splitlines()[-40:]:
            d = json.loads(l)
            items.append({"role": "user" if d["role"] == "usuario" else "assistant", "text": d["text"]})
        await send(w, {"type": "history", "items": items})
    except Exception:
        pass
    try:
        async for line in r:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            t = m.get("type")
            if t == "chat":
                asyncio.create_task(ask(m.get("text", ""), m.get("files", [])))
            elif t == "say":
                asyncio.create_task(speak(m.get("text", "")))
            elif t == "dev" and dev is not None:          # painel: {"type":"dev","op":"hist"|"ligar"|"desligar"|"alternar"}
                op_ = m.get("op", "hist")
                if op_ in ("ligar", "desligar", "alternar"):
                    dev.estado["on"] = (op_ == "ligar") or (op_ == "alternar" and not dev.estado["on"])
                    await broadcast({"type": "dev_modo", "on": dev.estado["on"]})
                    if dev.estado["on"] and ide_inst is not None:
                        try:
                            await ide_inst.tratar({"type": "ide", "op": "estado"}, broadcast)
                            await ide_inst.tratar({"type": "ide", "op": "arvore", "rel": ""}, broadcast)
                        except Exception as _e_ide:
                            print("ide_inst broadcast estado:", _e_ide, flush=True)
                await send(w, {"type": "dev_hist", "itens": dev.historico(int(m.get("n", 200)))})
            elif t == "ide" and ide_inst is not None:     # IDE do MODO DEV: estado/arvore/ler/diff/enviar/parar/nova_sessao/modelo/abrir_projeto
                await ide_inst.tratar(m, lambda r: send(w, r))
            elif t == "orquestrador":
                op_orc = m.get("op", "listar")
                try:
                    import orchestrator
                    orc = orchestrator.get_orquestrador(broadcast)
                    if op_orc == "listar":
                        await send(w, {"type": "orquestrador_lista", "objetivos": orc.listar_objetivos()})
                    elif op_orc == "iniciar":
                        res = orc.iniciar_ou_retomar_objetivo(
                            objetivo_id=m.get("id") or f"obj_{int(time.time())}",
                            titulo=m.get("titulo") or "Tarefa Geral",
                            instrucao=m.get("instrucao") or m.get("prompt") or "",
                            tipo=m.get("tipo", "continua"),
                            intervalo_s=float(m.get("intervalo_s", 60))
                        )
                        await send(w, {"type": "orquestrador_resp", "res": res})
                    elif op_orc == "parar":
                        res = orc.parar_objetivo(m.get("id"))
                        await send(w, {"type": "orquestrador_resp", "res": res})
                    elif op_orc == "criar_tela":
                        res = orc.criar_ou_modificar_tela_interna(
                            nome=m.get("nome"),
                            tipo=m.get("tipo", "qml"),
                            codigo=m.get("codigo", ""),
                            titulo=m.get("titulo", "")
                        )
                        await send(w, {"type": "orquestrador_resp", "res": res})
                except Exception as _e_orc:
                    await send(w, {"type": "orquestrador_resp", "erro": str(_e_orc)})
            elif t == "mood":
                await set_state(mood=m.get("mood"))
            elif t == "voice":
                voice_on = bool(m.get("on"))
                mem["voice"] = voice_on; save_mem()
                if not voice_on and state["state"] == "listening":
                    await set_state("idle")
                await broadcast({"type": "voice", "on": voice_on})
            elif t == "camera":
                camera_on = bool(m.get("on"))
                mem["camera"] = camera_on; save_mem()
                await broadcast({"type": "camera", "on": camera_on})
            elif t == "friday":
                await friday_set(bool(m.get("on", True)))
            elif t == "mode":
                m_nome = m.get("mode")
                m_val = m.get("on")
                if m_nome in modes:
                    novo_val = not modes[m_nome] if m_val is None else bool(m_val)
                    await set_mode(m_nome, novo_val)
                    if m_nome == "criacao":
                        await criacao_set(novo_val)
                    rotulos = {"seguranca": "Modo segurança", "privacidade": "Modo privacidade", "silencio": "Modo silêncio", "mouse": "Modo mão livre", "criacao": "Modo criação", "sentinela": "Modo sentinela"}
                    rot = rotulos.get(m_nome, m_nome)
                    await broadcast({"type": "modes", **modes})
                    asyncio.create_task(speak(f"{rot} {'ativado' if novo_val else 'desativado'}."))
            elif t == "ptz" and ptz is not None:     # automação/teste: {"type":"ptz","op":"olhar|seguir|vigiar|auto|procurar|em_volta|calibrar|parar|estado","dir":"","alvo":""}
                _ptz_comando(m)
            elif t == "mao":
                await broadcast({"type": "mao", "lado": m.get("lado", "R"), "pose": str(m.get("pose", "aberta"))})
            elif t == "friday_test_gesture":      # teste: dispara um gesto como se a câmera o tivesse reconhecido
                asyncio.create_task(friday_gesture(str(m.get("kind", "apontar")), {"dir": m.get("dir", "direita")}))
            elif t == "heard":                    # teste/automação: injeta uma fala já transcrita (como se o microfone tivesse ouvido)
                asyncio.create_task(route_speech(str(m.get("text", ""))))
            elif t == "holo":
                hud_state["foreign_t"] = time.time() if m.get("op", "show") != "clear" else 0
                hud_state["active"] = False
                if m.get("op", "show") != "clear" and not camera_on:
                    camera_on = True
                    await broadcast({"type": "camera", "on": True})
                await broadcast({"type": "holo", "op": str(m.get("op", "show")), "spec": m.get("spec")})
            elif t == "nano":                     # nanotecnologia da interface: app abrindo/pronto (friday.focus_or_launch)
                await broadcast({"type": "nano", "op": str(m.get("op", "")), "nome": str(m.get("nome", ""))[:60]})
            elif t in ("cel_toque_ui", "cel_arrastar_ui", "cel_tecla_ui", "cel_tela_ui"):   # holograma do celular -> celular real
                asyncio.create_task(_cel_ui(m))
            elif t in ("cel_tela", "cel_toque"):  # celtela rodando fora do daemon (prom/CLI): repassa à interface
                await broadcast({k: m[k] for k in ("type", "on", "url", "w", "h", "fps", "x", "y") if k in m})
            elif t == "painel":                   # telas de apresentação da F.R.I.D.A.Y. (clima/agenda/sistema/mídia/transição)
                await broadcast({"type": "painel", "op": str(m.get("op", "")), "data": m.get("data") or {}})
            elif t == "holo_frame":
                await broadcast({"type": "holo_frame", "on": bool(m.get("on")), "x": m.get("x", 0), "y": m.get("y", 0),
                                 "w": m.get("w", 0), "h": m.get("h", 0), "titulo": str(m.get("titulo", ""))[:60]})
            elif t == "holo_window":
                en = bool(m.get("enabled", True))
                if fr is not None:
                    fr.set_holo_mode(en)
                    if not en:
                        fr.holo_live_stop()
                await broadcast({"type": "holo_window", "enabled": en})
            elif t == "holo_snap":
                await broadcast({"type": "holo_snap"})
            elif t == "cursor":
                await broadcast({"type": "cursor", "x": int(m.get("x", 0)), "y": int(m.get("y", 0)), "act": str(m.get("act", "move")), "agent": True})
            elif t == "stop":
                await stop()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        clients.discard(w)
        w.close()


async def heartbeat():
    while True:
        await asyncio.sleep(2)
        if clients:
            await broadcast({"type": "ping"})


async def main():
    try:
        import cv2 as _cv
        _cv.setNumThreads(2)                       # OpenCV sem pool de 1 thread por núcleo
    except Exception:
        pass
    def _thread_map():                                  # diagnóstico leve: native_id -> nome do thread (p/ ver quem usa CPU)
        while True:
            try:
                with open("/tmp/prometheus-threads.json", "w") as _f:
                    json.dump({str(t.native_id): t.name for t in threading.enumerate()}, _f)
            except Exception:
                pass
            time.sleep(5)
    threading.Thread(target=_thread_map, daemon=True, name="diag-threads").start()
    asyncio.create_task(heartbeat())

    async def _state_watchdog():
        """se o estado ficou 'falando'/'pensando' sem nada a falar nem processar, volta para idle (evita travar o avatar)."""
        parado = 0
        while True:
            await asyncio.sleep(1.5)
            if state.get("state") in ("speaking", "thinking") and not speaking and not busy.locked() and not speak_lock.locked():
                parado += 1
                if parado >= 3:
                    parado = 0
                    await set_state("idle", "neutro")
                    await broadcast({"type": "mouth", "v": 0})
            else:
                parado = 0
    asyncio.create_task(_state_watchdog())

    async def _stats_task():
        """medidores do HUD (CPU/RAM/GPU) + percepção atual para a coluna da F.R.I.D.A.Y."""
        prev = None; gpu = {"gpu": 0, "vram": 0, "temp": 0, "t": 0.0}
        def _cpu():
            with open("/proc/stat") as f:
                v = [int(x) for x in f.readline().split()[1:8]]
            return sum(v), v[3] + v[4]
        while True:
            await asyncio.sleep(2.0)
            if not friday_state["on"]:
                continue
            try:
                tot, idle = _cpu()
                cpu = 0.0
                if prev:
                    dt, di = tot - prev[0], idle - prev[1]
                    cpu = max(0.0, min(100.0, 100.0 * (1 - di / dt))) if dt > 0 else 0.0
                prev = (tot, idle)
                mi = {}
                for l in open("/proc/meminfo"):
                    k, _, v = l.partition(":")
                    if k in ("MemTotal", "MemAvailable"):
                        mi[k] = int(v.split()[0])
                ram = 100.0 * (1 - mi["MemAvailable"] / mi["MemTotal"])
                if time.time() - gpu["t"] > 5:
                    gpu["t"] = time.time()
                    r = await asyncio.to_thread(lambda: subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=3).stdout.strip())
                    try:
                        u, mu, mt, tp = [float(x) for x in r.split(",")]
                        gpu.update(gpu=u, vram=100.0 * mu / mt, temp=int(tp))
                    except Exception:
                        pass
                now_ = time.time()
                pessoas = [f["nome"] or "desconhecido" for f in scene["faces"]] if (camera_on and now_ - scene["t"] < 4) else []
                alvo = ""
                if camera_on and now_ - scene["t"] < 4:
                    for f in scene["faces"]:
                        if f.get("nome"):
                            alvo = f["nome"]
                            break
                    if not alvo and scene["faces"]:
                        alvo = "desconhecido"
                objetos = list(scene["objetos"].keys())[:5] if (camera_on and now_ - scene["t_obj"] < 6) else []
                prox = ""
                if ops is not None:
                    try:
                        ag = ops.agenda_list(1)[:1]
                        if ag:
                            prox = f"{time.strftime('%H:%M', time.localtime(ag[0]['inicio']))}  {str(ag[0]['titulo'])[:30]}"
                    except Exception:
                        pass
                ptz_on = _shared.get("frame_ptz") is not None and (now_ - _shared.get("ptz_t", 0) < 3.0)
                usb_on = _shared.get("frame_amb") is not None and (now_ - _shared.get("amb_t", 0) < 3.0)
                nat_on = _shared.get("frame") is not None and (now_ - _shared.get("frame_t", 0) < 3.0)
                await broadcast({"type": "stats", "cpu": round(cpu), "ram": round(ram), "gpu": round(gpu["gpu"]), "vram": round(gpu["vram"]),
                                 "temp": gpu["temp"], "pessoas": pessoas, "alvo": alvo, "objetos": objetos, "prox": prox, "turnos": mem.get("turnos", 0),
                                 "ptz_on": ptz_on, "usb_on": usb_on, "nat_on": nat_on})
            except Exception as e:
                print("stats:", e, flush=True)
    asyncio.create_task(_stats_task())
    if ops is not None:
        _lp = asyncio.get_running_loop()
        ops.set_broadcast_cb(lambda m: asyncio.run_coroutine_threadsafe(broadcast(m), _lp))
    if isinstance(SOCK, str) and os.path.exists(SOCK):
        try: os.unlink(SOCK)
        except OSError: pass
    srv = await win_compat.start_ipc_server(asyncio.get_running_loop(), handle)
    try:                                         # controle remoto (app Android): só Tailscale + localhost, com token
        import remoto as _rm

        async def _rm_texto(t_, files_):
            conv["t"] = time.time()                  # anexos: ask/friday_ask já acrescentam "[arquivo anexado: ...]" a partir de files
            await ask(t_, files_)

        async def _rm_fala(t_):
            _origem_fala.set("app")                  # microfone do app (token): aprovação por voz vale sem o TitaNet local
            await route_speech(t_)

        async def _rm_resolver(aid_, decisao_, texto_=None):
            return await resolver_aprovacao(aid_, decisao_, texto_, origem="app")

        def _rm_historico(n_=40):
            n_ = max(1, min(200, int(n_)))
            itens = []
            try:
                with open(LOG_FILE, encoding="utf-8", errors="replace") as f_:
                    linhas = f_.read().splitlines()
            except OSError:
                return []
            for l_ in reversed(linhas):
                try:
                    d_ = json.loads(l_)
                except ValueError:
                    continue
                r_ = {"usuario": "user", "prometheus": "assistant"}.get(d_.get("role") if isinstance(d_, dict) else None)
                if r_ is None:
                    continue                         # "evento" e linhas estranhas ficam de fora
                itens.append({"role": r_, "text": str(d_.get("text", "")), "t": float(d_.get("t") or 0)})
                if len(itens) >= n_:
                    break
            return itens[::-1]
        global ide_inst
        if dev_ide is not None and ide_inst is None:
            try:
                ide_inst = dev_ide.IDE(broadcast)
            except Exception as _e_i:
                print("dev_ide init:", _e_i, flush=True)
        await _rm.iniciar({
            "aprovacoes": _aprovacoes_pendentes, "resolver": _rm_resolver, "historico": _rm_historico,
            "estado": lambda: {"on": friday_state["on"], "state": state["state"], "mood": state["mood"], "modes": dict(modes), "agente": bool(agente_ativo[0])},
            "texto": _rm_texto, "fala": _rm_fala, "ligar": friday_set, "pare": cancel_all,
            "acao": lambda a_: fr.run_action(a_, ops) if fr is not None else (False, "sem cérebro"),
            "foto": lambda p_: _shared.__setitem__("remote_jpg", (time.time(), p_)), "stt_prompt": _stt_prompt,
            "stt": lambda a_: _wake_fix(_transcrever(a_)[0]),    # STT do celular (/api/stt): mesmo Whisper e vocabulário daqui
            "aprimorar": lambda p_: run_aprimorar("propor", p_),  # celular pede melhoria no código do app (aprovação do dono)
            "voz_dono": lambda: voz_dono,
            "ide": ide_inst})   # lambda: o perfil carrega depois (thread de voz); o valor capturado aqui era None
        _remoto_on[0] = True
    except Exception as e:
        print("remoto indisponível:", e, flush=True)
    try:
        asyncio.create_task(_restaura_sessao())
    except Exception as e:
        print("remoto indisponível:", e, flush=True)
    os.chmod(SOCK, 0o600)
    stopev = asyncio.Event()
    for s in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(s, stopev.set)
    threading.Thread(target=lambda: _synth("Pronto."), daemon=True, name="tts-warmup").start()    # evita ~4 s na 1ª fala
    threading.Thread(target=voice_thread, args=(asyncio.get_running_loop(),), daemon=True).start()
    if os.environ.get("PROMETHEUS_SONS", "1") == "1":
        threading.Thread(target=som_thread, args=(asyncio.get_running_loop(),), daemon=True, name="ouvido").start()
    threading.Thread(target=mouse_real_thread, args=(asyncio.get_running_loop(),), daemon=True, name="mouse-real").start()
    _ptz_iniciar(asyncio.get_running_loop())
    if dev is not None:
        _loop_dev = asyncio.get_running_loop()
        dev.iniciar(lambda ev: asyncio.run_coroutine_threadsafe(broadcast(dict(ev, type="dev", tipo_ev=ev.get("tipo"))), _loop_dev))
    try:
        import orchestrator
        orchestrator.get_orquestrador(broadcast)
    except Exception as e:
        print("orquestrador inicialização:", e, flush=True)
    try:
        import cerebro as _cb0
        _cb0.SENTIDOS[0] = _sentidos
    except Exception as e:
        print("cérebro (sentidos):", e, flush=True)
    threading.Thread(target=cam_ambiente_thread, daemon=True, name="cam-ambiente").start()
    threading.Thread(target=cam_ptz_thread, daemon=True, name="cam-ptz").start()
    if os.environ.get("PROMETHEUS_MUNDO", "1") == "1":                # câmeras fixas localizam, a PTZ aponta (mundo.py)
        threading.Thread(target=cam_porta_thread, daemon=True, name="cam-porta").start()
        threading.Thread(target=mundo_thread, daemon=True, name="mundo").start()
    try:                                                              # visao.py lê os quadros em memória (não reabre /dev/video com a câmera ligada)
        import visao as _vs0
        _vs0.registrar_fonte("nativa", lambda: _shared.get("frame") if time.time() - _shared.get("frame_t", 0) < 2.0 else None, lambda: CAMERA and camera_on)
        _vs0.registrar_fonte("porta", lambda: _shared.get("frame_porta") if time.time() - _shared.get("porta_t", 0) < 2.0 else None, lambda: camera_on)
        _vs0.registrar_fonte("usb", lambda: _shared.get("frame_amb") if time.time() - _shared.get("amb_t", 0) < 2.0 else None, lambda: camera_on)
        _vs0.registrar_fonte("ptz", lambda: _shared.get("frame_ptz") if time.time() - _shared.get("ptz_t", 0) < 2.0 else None, lambda: camera_on)
        _vs0.registrar_fonte("externa", lambda: _shared.get("frame_amb") if time.time() - _shared.get("amb_t", 0) < 2.0 else _shared.get("frame_ptz"), lambda: camera_on)
    except Exception as e:
        print("visão (fontes):", e, flush=True)
    if CAMERA:
        threading.Thread(target=camera_thread, args=(asyncio.get_running_loop(),), daemon=True).start()
        if os.environ.get("PROMETHEUS_POSE2D", "0") == "1":          # opcional: pesado; aceno vem da câmera e braços da mão
            threading.Thread(target=pose_thread, args=(asyncio.get_running_loop(),), daemon=True).start()
        if os.environ.get("PROMETHEUS_OBJETOS", "0") == "1":          # objetos desligados: a câmera foca em gestos (CPU livre)
            threading.Thread(target=object_thread, daemon=True).start()
        if os.environ.get("PROMETHEUS_VLM_BG", "0") == "1":        # descrição contínua da cena expulsava o modelo de conversa da GPU (atraso enorme)
            threading.Thread(target=vlm_thread, daemon=True).start()
        if fr is not None:
            threading.Thread(target=fr.warm, daemon=True, name="warm-llm").start()
            import visao; threading.Thread(target=visao.preparar, daemon=True, name="warm-vlm").start()
        try:                                                          # construtor No-Code sempre no ar (janela aberta não fica órfã)
            import construtor as _ct0
            _lp0 = asyncio.get_running_loop()
            _ct0.iniciar(lambda m_: (asyncio.run_coroutine_threadsafe(broadcast({"type": "text", "role": "assistant", "text": "construtor: " + m_}), _lp0),
                                     asyncio.run_coroutine_threadsafe(speak(m_), _lp0)))
        except Exception as e:
            print("construtor:", e, flush=True)
        threading.Thread(target=hand_thread, args=(asyncio.get_running_loop(),), daemon=True).start()
        threading.Thread(target=vision_memory_thread, daemon=True).start()
        try:                                     # memória própria (repertório do PC + linha do tempo) e dados do fundo animado
            import memoria

            def _cena_mem():
                now = time.time()
                pes = [f["nome"] or "desconhecido" for f in scene["faces"]] if now - scene["t"] < 20 else []
                objs = list(scene["objetos"].keys()) if now - scene["t_obj"] < 20 else []
                return pes, objs, state.get("state", "")
            threading.Thread(target=memoria.thread, args=(_cena_mem,), daemon=True, name="memoria").start()
        except Exception as e:
            print("memória:", e, flush=True)
        threading.Thread(target=autonomy_thread, args=(asyncio.get_running_loop(),), daemon=True).start()
        threading.Thread(target=mind_thread, args=(asyncio.get_running_loop(),), daemon=True, name="mind").start()
        asyncio.create_task(_agente_watch())
    print(f"prometheus ouvindo em {SOCK}", flush=True)
    await stopev.wait()
    try:                                                 # fecha a sessão RTSP da PTZ: reinícios seguidos sem TEARDOWN derrubavam a câmera
        c_ = _shared.get("cap_ptz")
        if c_ is not None:
            c_.release()
    except Exception:
        pass
    srv.close()
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
