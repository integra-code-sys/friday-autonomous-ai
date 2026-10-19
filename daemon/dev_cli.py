"""MODO DEV = Claude CLI REAL num terminal kitty (sessão fixa, roda em segundo plano).

A Friday digita os pedidos na MESMA sessão interativa do `claude` (reaproveita contexto e cache de prompt => bem menos
token que um `claude -p` novo por pedido) e lê a tela do terminal para saber quando terminou.
  python3 dev_cli.py iniciar | enviar "texto" | ler | mostrar | estado
"""
import os, re, subprocess, sys, time

SOCK = f"/run/user/{os.getuid()}/friday-dev-kitty.sock"
TITULO = "Friday DEV — Claude CLI"
PASTA = os.path.expanduser(os.environ.get("FRIDAY_DEV_PASTA", "~/Workspace"))
MODELO = os.environ.get("FRIDAY_DEV_MODELO", "sonnet")                 # padrão do dono: Sonnet (economia)


def _k(*a, timeout=8):
    return subprocess.run(["kitty", "@", "--to", "unix:" + SOCK, *a], capture_output=True, text=True, timeout=timeout)


def vivo():
    return os.path.exists(SOCK) and _k("ls").returncode == 0


PASTA_ATUAL = f"/run/user/{os.getuid()}/friday-dev-pasta"


def iniciar(pasta=None):
    """abre (uma vez) o kitty com o claude interativo NA PASTA do pedido. Se já existe na mesma pasta, não duplica;
    em outra pasta e livre, fecha e reabre no lugar certo (o dono via '~/Workspace' e achava que era a pasta errada)."""
    if pasta is None and vivo():
        return "sessão DEV já aberta"                                 # mostrar()/ler() sem pasta: nunca troca a sessão de lugar
    pasta = os.path.expanduser(pasta) if pasta and os.path.isdir(os.path.expanduser(pasta)) else PASTA
    if vivo():
        try:
            atual = open(PASTA_ATUAL).read().strip()
        except Exception:
            atual = PASTA
        if atual == pasta or ocupado():
            return "sessão DEV já aberta"
        _k("close-window", "--match", "title:Friday DEV")
        time.sleep(1.5)
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    subprocess.Popen(["kitty", "-o", "allow_remote_control=socket-only", "--listen-on", "unix:" + SOCK,
                      "--title", TITULO, "--directory", pasta, "claude", "--model", MODELO, "--permission-mode", "auto"],   # auto: não para em pergunta de permissão (tarefas autônomas do dono)
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                     env={k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE"))})
    open(PASTA_ATUAL, "w").write(pasta)
    for _ in range(40):
        time.sleep(0.5)
        if vivo():
            time.sleep(5)                                               # o claude desenha a interface
            return "sessão DEV aberta"
    raise RuntimeError("o terminal do MODO DEV não abriu")


def ler(linhas=60):
    r = _k("get-text", "--extent", "screen")
    return "\n".join((r.stdout or "").rstrip().splitlines()[-linhas:])


def ocupado(txt=None):
    t = txt if txt is not None else ler(15)
    if "esc to interrupt" in t.lower():
        return True
    return bool(re.search(r"^\s*\S\s+\w[\w ]*…", t, re.M))             # linha do spinner: "· Doodling…", "✻ Thinking…"


def enviar(texto, esperar=0, pasta=None):
    """digita o pedido na sessão (abre se preciso, na pasta do pedido). esperar>0: aguarda até terminar e devolve o fim da tela."""
    iniciar(pasta)
    texto = " ".join(str(texto).split())                                # uma linha só: Enter no meio enviaria pela metade
    _k("send-text", "--", texto)
    time.sleep(0.4)
    _k("send-key", "enter")
    _painel("pedido", texto[:600])
    try:
        os.utime(PASTA_ATUAL)                                        # uso recente: "continua" do dono vai para esta sessão
    except Exception:
        pass
    if os.environ.get("FRIDAY_DEV_MOSTRAR") == "1":                   # 19/10: padrão = segundo plano; progresso vai ao painel DEV
        mostrar()
    if not esperar:
        return "pedido enviado ao Claude CLI (MODO DEV)"
    t0 = time.time()
    time.sleep(3)
    avisou = 0.0
    ultimo = ""
    while time.time() - t0 < esperar:
        tela = ler(25)
        if "Teach auto mode" not in tela and menu_aberto(tela):
            if AUTOACEITE:                                            # 19/10 (dono autorizou): aceita sozinho a 1ª opção ("Yes") e segue
                _k("send-text", "--", "1"); time.sleep(0.3); _k("send-key", "enter")
                _painel("aceite", "menu do Claude respondido sozinho: opção 1"); time.sleep(1.5); continue
            if time.time() - avisou > 60:
                mostrar(); avisou = time.time()
        elif "Teach auto mode" in tela:                               # 19/10: dica do Claude CLI (não é permissão) travava o fim -> Esc = "Not now"
            _k("send-key", "escape"); _painel("aceite", "dica 'Teach auto mode' dispensada"); time.sleep(1); continue
        elif not ocupado(tela):
            break
        linha = next((l.strip() for l in reversed(tela.splitlines()) if l.strip().startswith(("⏺", "●", "✻"))), "")
        if linha and linha != ultimo:
            _painel("progresso", linha[:300]); ultimo = linha
        time.sleep(2)
    fim = ler(40)
    _painel("fim", fim[-1500:])
    return fim


def _painel(tipo, texto):
    try:
        import dev
        dev.emitir("modo_dev", tipo, texto)
    except Exception:
        pass


AUTOACEITE = os.environ.get("FRIDAY_DEV_AUTOACEITE", "1") != "0"


def menu_aberto(tela=None):
    """o Claude espera escolha num menu (❯ 1. ... / Enter to confirm / Do you want to ...)?"""
    t = tela if tela is not None else ler(20)
    return bool(re.search(r"Enter to confirm|Do you want to|❯\s*1\.", t))


def responder(fala):
    """resposta do dono à sessão DEV ('clique no yes', 'opção 2', 'continua'): menu aberto = escolhe pelo número; senão manda continuar."""
    f = (fala or "").lower()
    if menu_aberto():
        n = ("3" if re.search(r"\b(?:3|tr[êe]s|terceir\w*|n[ãa]o mostr\w*|don'?t show)\b", f) else
             "2" if re.search(r"\b(?:2|dois|segund\w*|n[ãa]o|no|not now|agora n[ãa]o|depois)\b", f) else "1")
        _k("send-text", "--", n); time.sleep(0.3); _k("send-key", "enter")
        _painel("aceite", f"opção {n} escolhida pelo dono ({fala[:60]})")
        return f"escolhi a opção {n} no Claude"
    enviar("Continue a tarefa de onde parou, de forma autônoma: teste, confira e corrija até concluir.")
    return "mandei o Claude continuar"


def ultimo_uso():
    try:
        return os.path.getmtime(PASTA_ATUAL)
    except Exception:
        return 0


def mostrar():
    """traz o terminal DEV para a tela (o dono quer ver)."""
    iniciar()
    try:                                                              # kitty focus-window não troca a área de trabalho do niri
        import json as _j
        ws = _j.loads(subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, timeout=5).stdout)
        w = next(x for x in ws if "Friday DEV" in (x.get("title") or ""))
        wss = _j.loads(subprocess.run(["niri", "msg", "--json", "workspaces"], capture_output=True, text=True, timeout=5).stdout)
        idx = next((x["idx"] for x in wss if x["id"] == w.get("workspace_id")), None)
        if idx is not None:
            subprocess.run(["niri", "msg", "action", "focus-workspace", str(idx)], timeout=5)
        subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(w["id"])], timeout=5)
    except Exception:
        _k("focus-window")
    return "terminal DEV em foco"


def estado():
    if not vivo():
        return "fechado"
    return "trabalhando" if ocupado() else "livre"


if __name__ == "__main__":
    c, a = (sys.argv[1:2] or ["estado"])[0], " ".join(sys.argv[2:])
    print(enviar(a, 600) if c == "enviar" else {"iniciar": iniciar, "ler": ler, "mostrar": mostrar, "estado": estado}[c]())
