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


def iniciar():
    """abre (uma vez) o kitty com o claude interativo. Se já existe, não duplica."""
    if vivo():
        return "sessão DEV já aberta"
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    subprocess.Popen(["kitty", "-o", "allow_remote_control=socket-only", "--listen-on", "unix:" + SOCK,
                      "--title", TITULO, "--directory", PASTA, "claude", "--model", MODELO, "--permission-mode", "acceptEdits"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                     env={k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE"))})
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


def enviar(texto, esperar=0):
    """digita o pedido na sessão (abre se preciso). esperar>0: aguarda até terminar e devolve o fim da tela."""
    iniciar()
    texto = " ".join(str(texto).split())                                # uma linha só: Enter no meio enviaria pela metade
    _k("send-text", "--", texto)
    time.sleep(0.4)
    _k("send-key", "enter")
    if not esperar:
        return "pedido enviado ao Claude CLI (MODO DEV)"
    t0 = time.time()
    time.sleep(3)
    while time.time() - t0 < esperar and ocupado():
        time.sleep(2)
    return ler(40)


def mostrar():
    """traz o terminal DEV para a tela (o dono quer ver)."""
    iniciar()
    _k("focus-window")
    return "terminal DEV em foco"


def estado():
    if not vivo():
        return "fechado"
    return "trabalhando" if ocupado() else "livre"


if __name__ == "__main__":
    c, a = (sys.argv[1:2] or ["estado"])[0], " ".join(sys.argv[2:])
    print(enviar(a, 600) if c == "enviar" else {"iniciar": iniciar, "ler": ler, "mostrar": mostrar, "estado": estado}[c]())
