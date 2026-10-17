#!/usr/bin/env python3
"""shell_seguro — terminal da F.R.I.D.A.Y. com classificação ANTES de rodar (F7).

Classes:
  LEITURA       roda na hora (ls, cat, grep, df, ps, git status, journalctl --user -n ...)
  ESCRITA_HOME  só com aprovação do dono (prom_ops "shell.escrever"); rm vira `gio trash` (desfazível)
  ROOT          sudo / pacman -S / systemctl de sistema -> fluxo "sudo.run" já existente (aprovação + senha no zenity)
  NEGADO        nunca roda (rm -rf /, mkfs, dd em disco, curl|sh, escrita fora de $HOME, desligar/reiniciar, segredos...)

Não usa `sh -c`: o comando é lido por um lexer com as regras de aspas do sh/shlex e executado como argv
(pipes, ;, &&, ||, >, >>, <, 2>&1). O que foi classificado é exatamente o que roda.
Execução: systemd-run --user --scope -p MemoryMax=512M -p RuntimeMaxSec=60 + bwrap (/ só leitura, segredos
mascarados; na escrita só $HOME e /tmp graváveis). Saída (stdout+stderr) cortada em 3 KB.

  shell_seguro.py classificar "cmd"     -> JSON {classe, motivo, exibir}
  shell_seguro.py rodar "cmd"           -> roda só se for LEITURA
  shell_seguro.py --rodar '<plano>'     -> uso interno (dentro do sandbox)
"""
import glob, json, os, re, shlex, shutil, subprocess, sys, tempfile

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
CFG = os.path.join(PROJ, "memory", "friday.json")
LIMITE = 3000                       # bytes de saída devolvidos ao agente
ORDEM = {"LEITURA": 0, "ESCRITA_HOME": 1, "ROOT": 2, "NEGADO": 3}
_h = lambda *p: os.path.join(HOME, *p)

# leitura E escrita negadas (e mascaradas no bwrap)
SENSIVEIS = [_h(".ssh"), _h(".gnupg"), _h("Workspace", "Secrets"), _h(".claude"), _h(".password-store"), _h(".local", "share", "keyrings"),
             _h(".netrc"), _h(".git-credentials"), _h(".aws"), _h(".kube"), _h(".docker"), _h(".config", "chromium"),
             _h(".config", "google-chrome"), _h(".mozilla"), _h(".config", "gh")] + \
            [os.path.join(PROJ, "memory", n) for n in ("celular.json", "remoto.json", "remotos.json", "voz_dono.json", "aprovacoes.json")] + \
            ["/etc/shadow", "/etc/gshadow", "/etc/sudoers", "/etc/sudoers.d", "/root"]
# escrita negada mesmo dentro do $HOME (código/memória da própria Friday e pontos de persistência)
PROTEGIDOS = SENSIVEIS + [HERE, os.path.join(PROJ, "memory"), _h(".bashrc"), _h(".bash_profile"), _h(".zshrc"), _h(".zprofile"),
                          _h(".profile"), _h(".config", "fish"), _h(".config", "systemd"), _h(".config", "autostart"), _h(".config", "environment.d")]
# perfis de navegador (cookies/senhas), inclusive backups do profile-sync-daemon e .env soltos
_NAV = re.compile(r"^" + re.escape(HOME) + r"/\.config/(chromium|google-chrome|opera|vivaldi|BraveSoftware|microsoft-edge)|"
                  r"^" + re.escape(HOME) + r"/\.config/[^/]*\.env$|^/run/user/\d+/psd(/|$)")
SENSIVEIS += [x for x in glob.glob(_h(".config", "*")) if _NAV.match(x)] + [f"/run/user/{os.getuid()}/psd"]
# arquivos de segredo soltos (.env, certificados/chaves): bloqueados pelo nome e mascarados no bwrap
_SEGREDO = re.compile(r"(^|/)(\.env(\.[\w.-]+)?|[^/]*\.(env|pem|pfx|p12|key))$")
_PROC = re.compile(r"^/proc/(self|thread-self|\d+)(/task/\d+)?/(environ|mem)$")         # ambiente/memória de processos


def _achar_segredos(raizes=(_h("Workspace"), _h(".config"), _h("Documentos")), fundo=6):
    out = []
    for r in raizes:
        base = r.rstrip("/").count("/")
        for d, subs, arqs in os.walk(r):
            subs[:] = [x for x in subs if x not in ("node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build")
                       and d.count("/") - base < fundo]
            out += [os.path.join(d, a) for a in arqs if _SEGREDO.search(a)]
    return out


SENSIVEIS += _achar_segredos()
# symlinks (ex.: ~/.config/chromium) valem pelo destino real também
SENSIVEIS = list(dict.fromkeys(SENSIVEIS + [os.path.realpath(p) for p in SENSIVEIS]))
PROTEGIDOS = list(dict.fromkeys(PROTEGIDOS + [os.path.realpath(p) for p in PROTEGIDOS]))
# como root: nunca escrever/apagar aqui
SISTEMA = ["/boot", "/efi", "/etc/passwd", "/etc/group", "/etc/fstab", "/etc/crypttab", "/etc/pam.d", "/proc", "/sys", "/bin", "/sbin",
           "/lib", "/lib64", "/usr/bin", "/usr/lib", "/usr/sbin"]
CRITICOS = re.compile(r"^(base|linux|linux-cachyos\S*|linux-lts|linux-zen|systemd|systemd-libs|glibc|pacman|sudo|filesystem|bash|zsh|coreutils|"
                      r"util-linux|shadow|pam|grub|limine|mkinitcpio|dracut|niri|python|cachyos-keyring|archlinux-keyring|networkmanager)$")

LEITURA = {"ls", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "fd", "locate", "df", "du", "free", "ps", "pgrep", "uptime",
           "uname", "whoami", "id", "groups", "cal", "which", "whereis", "file", "stat", "wc", "sort", "uniq", "cut", "tr", "nl",
           "column", "diff", "cmp", "md5sum", "sha1sum", "sha256sum", "b2sum", "basename", "dirname", "realpath", "readlink", "echo",
           "printf", "lsblk", "lscpu", "lsusb", "lspci", "lsmod", "lsof", "sensors", "inxi", "fastfetch", "neofetch", "tree", "ss",
           "jq", "pdfinfo", "identify", "ffprobe", "checkupdates", "tldr", "true", "false", "test", "[", "seq", "nproc", "getconf",
           "lsattr", "findmnt", "bat", "xxd", "hexdump", "od", "strings", "zcat", "zgrep", "xzcat", "bzcat",
           "numfmt", "comm", "join", "paste", "fold", "fmt", "expand", "rev", "tac", "shuf"}
XARGS_OK = {"grep", "egrep", "fgrep", "wc", "head", "cat", "ls", "stat", "file", "du", "md5sum", "sha1sum", "sha256sum", "b2sum",
            "basename", "dirname", "realpath", "echo", "pdfinfo"}       # argumentos do stdin viram só caminhos (com "--")
INTERATIVOS = {"less", "more", "vi", "vim", "nvim", "nano", "emacs", "htop", "btop", "man", "watch", "ranger", "mc", "yes", "cmatrix"}
NEGADOS = {
    "desligar/reiniciar/encerrar sessão só pela ação própria e com pedido do dono": {"shutdown", "poweroff", "reboot", "halt", "init", "telinit", "kexec"},
    "disco/partição/sistema de arquivos: faça manualmente": {"wipefs", "fdisk", "sfdisk", "cfdisk", "gdisk", "sgdisk", "parted", "partprobe",
        "cryptsetup", "shred", "badblocks", "hdparm", "blkdiscard", "mkswap", "e2fsck", "fsck", "tune2fs", "resize2fs", "losetup", "swapoff"},
    "contas/senhas/privilégio: faça manualmente": {"passwd", "chpasswd", "usermod", "useradd", "userdel", "groupadd", "groupdel", "groupmod",
        "gpasswd", "chsh", "chfn", "visudo", "vipw", "vigr", "su", "doas", "pkexec", "sudoedit", "newgrp", "chage", "runuser"},
    "contorna o sandbox/roda em segundo plano": {"nohup", "setsid", "disown", "tmux", "screen", "script", "expect", "chroot", "unshare",
        "nsenter", "strace", "ltrace", "gdb", "busybox", "crontab", "at", "batch", "systemd-run", "bwrap", "flock", "firejail"},
    "pode expor segredos do ambiente": {"env", "printenv", "set", "export", "declare", "typeset", "history"},
    "acesso remoto/rede bruta: faça manualmente": {"ssh", "scp", "sftp", "nc", "ncat", "netcat", "socat", "telnet", "ftp"},
}
SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "eval", "exec", "source", ".", "command", "builtin"}
INTERP = re.compile(r"^(python[\d.]*|perl|ruby|node|nodejs|php|lua\S*|deno|bun|tclsh|Rscript|osascript)$")
POWER = {"poweroff", "reboot", "halt", "suspend", "hibernate", "hybrid-sleep", "suspend-then-hibernate", "kexec", "rescue", "emergency",
         "default", "isolate", "soft-reboot", "exit", "switch-root"}


class Recusa(Exception):
    pass


def ativo():
    """friday.json "terminal": false desliga a ferramenta (padrão ligada)."""
    try:
        return json.load(open(CFG)).get("terminal", True) is not False
    except Exception:
        return True


# ----------------------------------------------------------------- lexer (regras de aspas do sh)
_OPC = "|&;<>"


def _lexar(s):
    """-> lista de ("w", texto, tem_glob, tem_til, ini, fim) e ("op", texto, ini, fim)."""
    if len(s) > 2000:
        raise Recusa("comando longo demais")
    toks, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t":
            i += 1; continue
        if c == "\n":
            toks.append(("op", ";", i, i + 1)); i += 1; continue
        if c in "()":
            raise Recusa("subshell/parênteses não são suportados")
        if c in _OPC:
            j = i
            while j < n and s[j] in _OPC:
                j += 1
            toks.append(("op", s[i:j], i, j)); i = j; continue
        ini, w, glob_, til = i, [], False, c == "~"
        while i < n and s[i] not in " \t\n()" + _OPC:
            c = s[i]
            if c == "\\":
                if i + 1 < n:
                    w.append(s[i + 1])
                i += 2; continue
            if c == "'":
                j = s.find("'", i + 1)
                if j < 0:
                    raise Recusa("aspas simples sem fechar")
                w.append(s[i + 1:j]); i = j + 1; continue
            if c == '"':
                j, buf = i + 1, []
                while j < n and s[j] != '"':
                    if s[j] == "\\" and j + 1 < n and s[j + 1] in '"\\$`':
                        buf.append(s[j + 1]); j += 2; continue
                    if s[j] in "$`":
                        k, txt = _dolar(s, j)
                        buf.append(txt); j = k; continue
                    buf.append(s[j]); j += 1
                if j >= n:
                    raise Recusa("aspas duplas sem fechar")
                w.append("".join(buf)); i = j + 1; continue
            if c in "$`":
                i, txt = _dolar(s, i)
                w.append(txt); continue
            if c in "*?[":
                glob_ = True
            w.append(c); i += 1
        toks.append(("w", "".join(w), glob_, til, ini, i))
    return toks


def _dolar(s, i):
    """só $HOME/${HOME}/$USER são expandidos; $(...), crase e outras variáveis são recusados."""
    if s[i] == "`" or s.startswith("$(", i):
        raise Recusa("substituição de comando ($(...) ou crase) não é suportada: rode em passos")
    m = re.match(r"\$(?:\{(HOME|USER)\}|(HOME|USER)\b)", s[i:])
    if m:
        v = m.group(1) or m.group(2)
        return i + m.end(), HOME if v == "HOME" else os.environ.get("USER", os.path.basename(HOME))
    if re.match(r"\$[\w{@*#?!$-]", s[i:]):
        raise Recusa("variáveis de shell não são expandidas: use o caminho completo")
    return i + 1, "$"


def _parse(toks):
    """-> [{"op": None|";"|"&&"|"||", "pipe": [{"argv": [...], "flags": [(glob, til)], "redir": [[fd, modo, alvo]]}]}]"""
    seq, pipe, op_seq = [], [], None
    novo = lambda: {"argv": [], "flags": [], "redir": []}
    cmd, k = novo(), 0

    def fecha():
        if not cmd["argv"]:
            raise Recusa("comando vazio perto de um operador")
        pipe.append(cmd)
    while k < len(toks):
        t = toks[k]
        if t[0] == "w":
            cmd["argv"].append(t[1]); cmd["flags"].append((t[2], t[3])); k += 1; continue
        op = t[1]
        if op in ("|", "|&"):
            if op == "|&":
                cmd["redir"].append([2, "dup", 1])
            fecha(); cmd = novo()
        elif op in (";", "&&", "||"):
            fecha(); seq.append({"op": op_seq, "pipe": pipe}); pipe, cmd, op_seq = [], novo(), op
        elif op in (">", ">>", "<", ">&", "&>", "&>>"):
            fd = 0 if op == "<" else 1
            ant = toks[k - 1] if k else None
            if op in (">", ">>", "<", ">&") and ant and ant[0] == "w" and ant[5] == t[2] and ant[1].isdigit() and cmd["argv"]:
                fd = int(ant[1]); cmd["argv"].pop(); cmd["flags"].pop()
            if k + 1 >= len(toks) or toks[k + 1][0] != "w":
                raise Recusa(f"redirecionamento '{op}' sem destino")
            alvo = toks[k + 1][1]
            if op == ">&" and alvo.isdigit():
                cmd["redir"].append([fd, "dup", int(alvo)])
            elif op == "<":
                cmd["redir"].append([fd, "<", alvo])
            else:
                modo = "a" if op.endswith(">>") else "w"
                for f in ((1, 2) if op in ("&>", "&>>", ">&") else (fd,)):
                    cmd["redir"].append([f, modo, alvo])
            k += 2; continue
        elif op == "&":
            raise Recusa("segundo plano (&) não é suportado")
        else:
            raise Recusa(f"operador '{op}' não suportado")
        k += 1
    if cmd["argv"]:
        pipe.append(cmd)
    elif pipe:
        raise Recusa("comando termina num pipe")
    if pipe:
        seq.append({"op": op_seq, "pipe": pipe})
    elif op_seq in ("&&", "||"):
        raise Recusa("comando termina num operador")
    if not seq:
        raise Recusa("comando vazio")
    if sum(len(x["pipe"]) for x in seq) > 8:
        raise Recusa("comandos demais numa linha (máx. 8)")
    return seq


# ----------------------------------------------------------------- caminhos
def _abs(p, cwd):
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(p)))


def _dentro(p, base):
    return p == base or p.startswith(base.rstrip("/") + "/")


def _sensivel(p):
    return bool(_NAV.match(p) or _SEGREDO.search(p) or _PROC.match(p)) or any(_dentro(p, s) for s in SENSIVEIS)


def _escrita(p, root):
    """None se pode escrever em p; senão o motivo do NEGADO."""
    if p in ("/dev/null", "/dev/stdout", "/dev/stderr"):
        return None
    if any(_dentro(p, s) for s in PROTEGIDOS):
        return f"área protegida: {p}"
    if p == "/" or (_dentro(p, "/dev") and not root):
        return f"escrita em {p}"
    if root:
        return f"área do sistema: {p}" if any(_dentro(p, s) for s in SISTEMA) or _dentro(p, "/dev") else None
    if not (_dentro(p, HOME) or _dentro(p, "/tmp")):
        return f"escrita fora de $HOME: {p}"
    return None


def _pos(argv, com_valor=()):
    """argumentos posicionais (pula opções e o valor das opções em com_valor)."""
    out, pula, fim = [], False, False
    for a in argv[1:]:
        if pula:
            pula = False; continue
        if not fim and a == "--":
            fim = True; continue
        if not fim and a.startswith("-") and a != "-":
            if a in com_valor:
                pula = True
            continue
        out.append(a)
    return out


def _tem(argv, *ops):
    """opção presente (curta agrupada como -rf também conta)."""
    for a in argv[1:]:
        if a == "--":
            break
        for o in ops:
            if a == o or (o.startswith("--") and a.startswith(o + "=")):
                return True
            if len(o) == 2 and o[0] == "-" and o[1] != "-" and re.match(r"^-[A-Za-z0-9]+$", a) and o[1] in a[1:]:
                return True
    return False


def _val(argv, *ops):
    """valor de uma opção (-o X, -oX, --out=X, --out X)."""
    for i, a in enumerate(argv[1:], 1):
        for o in ops:
            if a == o and i + 1 < len(argv):
                return argv[i + 1]
            if o.startswith("--") and a.startswith(o + "="):
                return a.split("=", 1)[1]
            if len(o) == 2 and a.startswith(o) and len(a) > 2 and not a.startswith("--"):
                return a[2:]
    return None


# ----------------------------------------------------------------- classificação de um comando
def _cmd(argv, cwd, root):
    """-> (classe, motivo, argv_final, escritas[list de caminhos absolutos])"""
    nome = argv[0]
    if "/" in nome:
        b = os.path.basename(nome)
        if os.path.dirname(_abs(nome, cwd)) in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
            nome = b
        else:
            p = _abs(nome, cwd)
            if _sensivel(p):
                return "NEGADO", f"caminho sensível: {p}", argv, []
            return "ESCRITA_HOME", "script/programa local: pede aprovação", argv, [cwd]
    pos = _pos(argv)
    L = lambda m="leitura": ("LEITURA", m, argv, [])
    E = lambda m, esc: ("ESCRITA_HOME", m, argv, esc)
    R = lambda m: ("ROOT", m, argv, [])
    N = lambda m: ("NEGADO", m, argv, [])

    for motivo, nomes in NEGADOS.items():
        if nome in nomes:
            return N(motivo)
    if re.match(r"^mkfs(\.\w+)?$|^mke2fs$|^mkfs\.", nome):
        return N("formatar disco: faça manualmente")
    if nome in INTERATIVOS:
        return N("comando interativo/contínuo não roda aqui (use cat/head/grep)")
    if nome in SHELLS:
        return N("shell dentro do comando contorna a checagem: mande o comando direto")
    if INTERP.match(nome):
        if _tem(argv, "-c", "-e", "-E", "-r", "--eval", "-m") or not pos or pos[0] == "-":
            return N("código inline/stdin no interpretador não roda aqui: salve num arquivo e peça aprovação")
        p = _abs(pos[0], cwd)
        return ("NEGADO", f"caminho sensível: {p}", argv, []) if _sensivel(p) else E("roda script local: pede aprovação", [cwd])
    if nome in ("timeout", "nice", "ionice", "time", "stdbuf", "nocache"):
        resto = argv[1:]
        while resto and resto[0].startswith("-"):
            o = resto.pop(0)
            if o in ("-n", "-c", "-k", "-s", "--signal", "--kill-after", "-o", "-e", "-i") and resto:
                resto.pop(0)
        if nome == "timeout" and resto:
            resto.pop(0)                                    # duração
        if not resto:
            return N(f"{nome} sem comando")
        c, m, a2, esc = _cmd(resto, cwd, root)
        return c, m, argv[:len(argv) - len(resto)] + a2, esc
    if nome == "sudo":
        return N("sudo no meio do comando: use só no início")

    if nome in ("sleep", "xdg-open"):
        return E(f"{nome}: pede aprovação", [])
    if nome == "cd":
        return L("cd")
    if nome in LEITURA:
        if nome in ("tail",) and _tem(argv, "-f", "-F", "--follow"):
            return N("tail -f não termina: use tail -n")
        if nome == "rg" and (_tem(argv, "--pre", "--pre-glob") or any(a.startswith(("--pre", "--hostname-bin")) for a in argv)):
            return N("rg --pre/--hostname-bin executa programa")
        if nome == "bat" and any(a.startswith("--pager") for a in argv):
            return N("bat --pager executa programa")
        if nome == "fd" and (_tem(argv, "-x", "-X", "--exec", "--exec-batch")):
            return N("fd --exec executa comando: liste e peça a ação separada")
        if nome == "sort" and any(a.startswith("--compress-prog") for a in argv):
            return N("sort --compress-program executa programa")
        if nome == "ps" and any(not a.startswith("-") and "e" in a for a in argv[1:]):
            return N("ps e mostra o ambiente (segredos) dos processos")
        if nome in ("fastfetch", "neofetch") and (_tem(argv, "-c", "--config", "--load-config", "--source") or
                                                  any(re.search(r"command|script", a) for a in argv[1:])):
            return E(f"{nome} com config/comando próprio: pede aprovação", [cwd])
        if nome == "sort" and _val(argv, "-o", "--output"):
            return E("sort -o grava arquivo", [_abs(_val(argv, "-o", "--output"), cwd)])
        if nome == "uniq" and len(pos) >= 2:
            return E("uniq ENTRADA SAÍDA grava arquivo", [_abs(pos[1], cwd)])
        return L()
    if nome == "date":
        return R("acertar a data") if _tem(argv, "-s", "--set") else L()
    if nome == "hostname":
        return R("trocar hostname") if pos else L()
    if nome == "top":
        return L() if _tem(argv, "-b") else N("top interativo: use top -b -n 1 | head")
    if nome == "nvidia-smi":
        return R("altera a GPU") if _tem(argv, "-pm", "-pl", "-r", "-ac", "-rac", "-lgc", "-rgc", "-e", "-c", "--persistence-mode",
                                         "--power-limit", "--gpu-reset", "-am", "-caa") else L()
    if nome == "pdftotext":
        if len(pos) >= 2 and pos[1] == "-":
            return L()
        saida = pos[1] if len(pos) >= 2 else (re.sub(r"\.pdf$", "", pos[0], flags=re.I) + ".txt" if pos else "")
        return E("pdftotext grava .txt (use 'pdftotext ARQ -' para só ler)", [_abs(saida, cwd)] if saida else [cwd])
    if nome == "sed":
        if _tem(argv, "-i", "--in-place"):
            return E("sed -i altera arquivo", [_abs(p, cwd) for p in pos[1:]] or [cwd])
        if _tem(argv, "-f", "--file") or any(a.startswith("--file=") or re.match(r"^-[a-zA-Z]+e.", a) for a in argv[1:]):
            return E("sed com script em arquivo: pede aprovação", [cwd])
        scrs = [argv[i + 1] for i, a in enumerate(argv[:-1]) if i and a in ("-e", "--expression")] + \
               [a.split("=", 1)[1] if a.startswith("--") else a[2:] for a in argv[1:] if a.startswith("--expression=") or (a.startswith("-e") and len(a) > 2)]
        scrs = scrs or [pos[0] if pos else ""]
        ok = all(re.match(r"^\s*(\d+(,(\d+|\$))?|\$|/[^/]*/(,/[^/]*/)?)?\s*[pdq]\s*$|^\s*(\d+(,(\d+|\$))?\s*)?s(.)(?:(?!\8).|\\.)*\8(?:(?!\8).|\\.)*\8[gIi0-9p]*\s*$", scr) for scr in scrs)
        return L() if ok else E("script de sed fora do padrão de leitura: pede aprovação", [cwd])
    if nome in ("awk", "gawk", "mawk"):
        scr = " ".join(argv[1:])
        return L() if pos and not re.search(r"system|getline|[>|]|close|fflush|ENVIRON|@", scr) and not _tem(argv, "-f", "-l", "-i", "-E") \
            and not any(a.startswith(("--load", "--include", "--exec", "--file", "--source")) for a in argv) else \
            E("awk com saída/sistema: pede aprovação", [cwd])
    if nome == "xargs":
        resto, i = argv[1:], 0
        while i < len(resto) and resto[i].startswith("-"):
            i += 2 if resto[i] in ("-n", "-I", "-P", "-d", "-L", "-s", "-E", "-a") else 1
        inner = resto[i:] or ["echo"]
        if inner[0] not in XARGS_OK or _tem(argv[:len(argv) - len(inner)], "-I", "-i", "--replace"):
            return N("xargs só com grep/wc/head/cat/ls/stat/sha256sum... (os argumentos vêm do stdin): rode o comando direto")
        c, m, a2, esc = _cmd(inner, cwd, root)
        if c != "LEITURA":
            return N("xargs com comando que altera algo: liste os arquivos e rode o comando direto")
        return c, m, argv[:len(argv) - len(inner)] + a2 + ([] if a2[0] == "echo" or "--" in a2 else ["--"]), esc
    if nome == "find":
        esc, i, a2 = [], 1, list(argv)
        inicio = [a for a in argv[1:] if not a.startswith(("-", "(", ")", "!"))][:1] or ["."]
        while i < len(argv):
            a = argv[i]
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                j = i + 1
                while j < len(argv) and argv[j] not in (";", "+"):
                    j += 1
                inner = [x for x in argv[i + 1:j] if x != "{}"] or ["true"]
                c, m, _a, _e = _cmd(inner, cwd, root)
                if c != "LEITURA":
                    return N("find -exec com comando que altera algo: use find para listar e peça a ação separada")
                i = j + 1; continue
            if a == "-delete":
                esc += [_abs(p, cwd) for p in inicio]
            if a in ("-fprint", "-fprint0", "-fprintf", "-fls") and i + 1 < len(argv):
                esc.append(_abs(argv[i + 1], cwd))
            i += 1
        return E("find com -delete/-fprint altera arquivos", esc) if esc else ("LEITURA", "leitura", a2, [])
    if nome in ("curl", "wget"):
        if (nome == "curl" and _tem(argv, "-K", "--config", "--json")) or (nome == "wget" and _tem(argv, "-e", "--execute", "--config")):
            return N(f"{nome} com config/--json: faça manualmente")
        if any(re.search(r"(file|scp|sftp|telnet|dict|gopher|ldap|smb|tftp)s?:/", a, re.I) for a in argv[1:]):     # inclui {file,http}:// do curl
            return N("curl/wget só para http(s): para arquivo local use cat")
        if _tem(argv, "-d", "--data", "--data-binary", "--data-raw", "--data-urlencode", "-F", "--form", "-T", "--upload-file",
                "--post-data", "--post-file", "--body-data", "--body-file") or (_val(argv, "-X", "--request", "--method") or "GET").upper() != "GET":
            return N("envio de dados para a rede: faça manualmente")
        if nome == "curl":
            out = _val(argv, "-o", "--output")
            if out and out != "-":
                return E("curl -o grava arquivo", [_abs(out, cwd)])
            if _tem(argv, "-O", "--remote-name", "--remote-name-all"):
                return E("curl -O grava arquivo", [cwd])
            return L("leitura da web")
        out = _val(argv, "-O", "--output-document")
        if out == "-" or any(re.match(r"^-[a-zA-Z]*O-$", a) for a in argv[1:]):
            return L("leitura da web")
        d = _val(argv, "-P", "--directory-prefix")
        return E("wget grava arquivo", [_abs(out or d or ".", cwd)])
    if nome in ("systemctl", "loginctl", "hostnamectl", "timedatectl", "localectl", "busctl", "journalctl") and _tem(argv, "-H", "--host"):
        return N("acesso remoto (-H/--host): faça manualmente")
    if nome == "systemctl":
        user = _tem(argv, "--user")
        verbo = next(iter(_pos(argv, ("-t", "--type", "-p", "--property", "--state", "-n", "--lines", "-o", "--output", "-H", "--host", "-M"))), "list-units")
        if verbo in POWER:
            return N("desligar/reiniciar/suspender só a pedido do dono, pela ação própria")
        if verbo == "edit":
            return N("systemctl edit é interativo")
        if verbo in ("status", "list-units", "list-unit-files", "list-timers", "list-sockets", "list-dependencies", "list-jobs",
                     "is-active", "is-enabled", "is-failed", "show", "cat", "help", "list-machines"):
            return L()
        return E(f"systemctl --user {verbo}: pede aprovação", []) if user else R(f"systemctl {verbo} (sistema)")
    if nome == "journalctl":
        if _tem(argv, "-f", "--follow"):
            return N("journalctl -f não termina: use -n 50")
        if _tem(argv, "--vacuum-size", "--vacuum-time", "--vacuum-files", "--rotate", "--flush", "--sync", "--relinquish-var", "--setup-keys"):
            return R("manutenção do journal")
        return L()
    if nome == "git":
        if _tem(argv, "-c") or any(a.startswith("--exec-path") or a.startswith("--config-env") for a in argv):
            return N("git -c pode executar programas")
        base = _abs(_val(argv, "-C") or ".", cwd)
        p2 = _pos(argv, ("-C",))
        sub, resto = (p2[0], argv[argv.index(p2[0]) + 1:]) if p2 else ("status", [])
        r2 = ["git"] + resto
        if any(a.startswith(("--open-files-in-pager", "--ext-diff")) for a in resto) or (sub == "grep" and _tem(r2, "-O")):
            return N("git com pager/diff externo executa programa")
        if sub in ("status", "log", "diff", "show", "rev-parse", "ls-files", "blame", "describe", "shortlog", "reflog", "grep",
                   "ls-tree", "cat-file", "rev-list", "whatchanged", "count-objects", "help", "version"):
            return E("git com --output grava arquivo", [base]) if any(a.startswith("--output") for a in resto) else L()
        if sub in ("branch", "tag") and not _pos(r2) and not _tem(r2, "-d", "-D", "-m", "-M", "-c", "-C", "-f", "--delete", "--force"):
            return L()
        if sub == "remote" and not _pos(r2):
            return L()
        if sub == "config" and _tem(r2, "--get", "--get-all", "--list", "-l", "--get-regexp"):
            return L()
        if (sub == "reset" and _tem(r2, "--hard")) or sub == "clean" or (sub == "push" and _tem(r2, "-f", "--force", "--force-with-lease", "--mirror", "--delete")) \
                or (sub in ("checkout", "restore") and ("." in resto or _tem(r2, "-f", "--force"))):
            return N(f"git {sub} destrutivo (perde trabalho): faça manualmente")
        return E(f"git {sub}: pede aprovação", [base])
    if nome == "pacman":
        op = next((a for a in argv[1:] if re.match(r"^-[A-Z]", a)), None) or next((a for a in argv[1:] if a in (
            "--query", "--sync", "--remove", "--upgrade", "--database", "--files", "--deptest", "--version")), "")
        if op.startswith("-Q") or op.startswith("-T") or op in ("--query", "--deptest", "--version", "-V"):
            return L()
        if op.startswith("-S") and re.search(r"[sigl]", op[2:]) and not re.search(r"[yuc]", op[2:]) and not _tem(argv, "-y", "-u", "-c"):
            return L()
        if op.startswith("-F") and "y" not in op:
            return L()
        if op.startswith("-R") or op == "--remove":
            if any(CRITICOS.match(p) for p in pos):
                return N("remover pacote essencial do sistema: faça manualmente")
        return R("pacman instala/remove/atualiza")
    if nome in ("yay", "paru"):
        op = next((a for a in argv[1:] if a.startswith("-")), "")
        if op.startswith("-Q") or (op.startswith("-S") and re.search(r"[si]", op[2:]) and "y" not in op and "u" not in op) or op.startswith("-Ps"):
            return L()
        return N("AUR precisa de terminal interativo: faça manualmente")
    if nome == "flatpak":
        return L() if pos[:1] and pos[0] in ("list", "info", "search", "remotes", "history", "ps") else E(f"flatpak {pos[:1]}", [])
    if nome == "ip":
        if "exec" in pos or "netns" in pos:
            return N("ip netns exec")
        return R("altera a rede") if set(pos) & {"add", "del", "delete", "set", "flush", "change", "replace", "append", "prepend", "up", "down"} else L()
    if nome == "nmcli":
        if _tem(argv, "-s", "--show-secrets") or "--show-secrets" in argv or "show-password" in pos:
            return N("nmcli com segredos")
        if "monitor" in pos:
            return N("nmcli monitor não termina")
        if set(pos) & {"up", "down", "delete", "modify", "add", "connect", "disconnect", "edit", "reload", "load", "import", "export",
                       "clone", "on", "off", "set", "hotspot", "reapply", "password"}:
            return E("nmcli altera a rede: pede aprovação", [])
        return L()
    if nome == "niri":
        if pos[:1] != ["msg"]:
            return N("niri fora de 'niri msg'")
        if "quit" in pos or "power-off-monitors" in pos:
            return N("encerrar a sessão/desligar monitores só a pedido do dono")
        return L() if pos[1:2] and pos[1] in ("windows", "workspaces", "outputs", "focused-window", "focused-output", "layers",
                                              "keyboard-layouts", "version", "overview-state") and len(pos) == 2 else \
            E(f"niri msg {' '.join(pos[1:2])}: pede aprovação", [])
    if nome == "loginctl":
        return L() if pos[:1] and re.match(r"^(list-|show-|session-status|user-status|seat-status)", pos[0]) or not pos else \
            N("loginctl altera sessão: só a pedido do dono")
    if nome in ("hostnamectl", "timedatectl", "localectl"):
        return R(f"{nome} altera o sistema") if pos[:1] and re.match(r"^set-|^ntp|^add-|^remove-", pos[0]) else L()
    if nome == "pactl":
        return L() if pos[:1] and re.match(r"^(list|info|stat|get-)", pos[0]) else E("pactl altera áudio", [])
    if nome == "wpctl":
        return L() if pos[:1] and pos[0] in ("status", "inspect", "get-volume") else E("wpctl altera áudio", [])
    if nome == "playerctl":
        return L() if not pos or pos[0] in ("status", "metadata", "position", "-l", "--list-all") else E("playerctl controla a mídia", [])
    if nome == "gio":
        sub = pos[0] if pos else ""
        if sub in ("info", "list", "tree", "help", "version") or (sub == "mime" and len(pos) <= 2):
            return L()
        if sub == "trash" and _tem(argv, "--empty"):
            return N("esvaziar a lixeira é irreversível: faça manualmente")
        return E(f"gio {sub}", [_abs(p, cwd) for p in pos[1:]] or [cwd])
    if nome in ("kill", "pkill", "killall"):
        if any(p in ("-1", "1") for p in argv[1:]) or _tem(argv, "-u", "--user") or (nome != "kill" and not pos):
            return N("matar todos os processos/de usuário")
        return E(f"{nome}: pede aprovação (pode derrubar a Friday)", [])
    if nome == "dd":
        of = next((a[3:] for a in argv[1:] if a.startswith("of=")), None)
        if of and _dentro(_abs(of, cwd), "/dev") and _abs(of, cwd) != "/dev/null":
            return N("dd em disco: faça manualmente")
        return E("dd grava arquivo", [_abs(of, cwd)] if of else [])
    if nome == "rm":
        if "--no-preserve-root" in argv:
            return N("rm --no-preserve-root")
        if not pos:
            return N("rm sem caminho")
        alvos = [_abs(p, cwd) for p in pos]
        for p in alvos:
            if p == "/" or _dentro(HOME, p) or (os.path.dirname(p) == HOME and os.path.isdir(p)):
                return N(f"apagar {p} inteiro: faça manualmente")
        if root:
            for p in alvos:
                if _tem(argv, "-r", "-R", "--recursive") and not (_dentro(p, HOME) or _dentro(p, "/tmp") or _dentro(p, "/var/cache")):
                    return N(f"rm -r fora de $HOME como root: {p}")
            return ("ROOT", "rm como root", argv, alvos)
        if all(_dentro(p, "/tmp") for p in alvos):
            return ("ESCRITA_HOME", "rm em /tmp (sem lixeira)", argv, alvos)    # gio não tem lixeira em tmpfs
        a2 = ["gio", "trash"] + (["-f"] if _tem(argv, "-f", "--force") else []) + ["--"] + pos
        return ("ESCRITA_HOME", "rm vira gio trash (vai para a lixeira)", a2, alvos)
    if nome in ("chmod", "chown", "chgrp"):
        rec = _tem(argv, "-R", "--recursive")
        alvos = [_abs(p, cwd) for p in pos[1:]]
        if nome != "chmod" and rec:
            return N(f"{nome} -R: faça manualmente")
        if nome == "chmod" and (any(a.startswith("--reference") for a in argv) or pos and re.search(r"[ugoa]*[+=][rwxXt]*s|^0*[2-7][0-7]{3}$", pos[0])):
            return N("setuid/setgid")
        if rec and any(not _dentro(p, HOME) or p == HOME for p in alvos):
            return N(f"{nome} -R fora de uma pasta do $HOME")
        return E(f"{nome} altera permissões", alvos)
    # ---- escrita comum (destino conferido)
    if nome == "cp":
        t = _val(argv, "-t", "--target-directory")
        dest = t or (pos[-1] if len(pos) >= 2 else None)
        if not dest:
            return N("cp sem destino")
        return E("cp grava cópia", [_abs(dest, cwd)])
    if nome in ("mv", "ln", "mkdir", "touch", "rmdir", "truncate", "tee", "install", "mktemp", "rename"):
        alvos = _pos(argv, ("-s", "--size", "-m", "--mode", "-t", "--target-directory", "--suffix", "-S")) if nome != "ln" else pos[-1:]
        if nome == "mv" and _val(argv, "-t", "--target-directory"):
            alvos.append(_val(argv, "-t", "--target-directory"))
        if nome == "install" and re.search(r"s|^0*[2-7][0-7]{3}$", _val(argv, "-m", "--mode") or ""):
            return N("install com setuid/setgid")
        if nome == "ln" and len(pos) == 1:
            alvos = [os.path.basename(pos[0])]
        if nome == "tee" and not alvos:
            return L()
        if nome == "mktemp":
            return L()
        return E(f"{nome} altera arquivos", [_abs(p, cwd) for p in alvos] or [cwd])
    if nome in ("tar", "bsdtar"):
        if any(a.startswith(("--to-command", "--use-compress", "--checkpoint-action", "--info-script", "--new-volume-script", "--rsh-command",
                             "--rmt-command", "--index-file")) for a in argv) or _tem(argv, "-I", "-F") or ":" in (_val(argv, "-f", "--file") or ""):
            return N("tar com opção que executa programa/arquivo remoto: faça manualmente")
        modo = (argv[1] if len(argv) > 1 else "").lstrip("-")
        if "t" in modo or _tem(argv, "-t", "--list"):
            return L()
        if "c" in modo or _tem(argv, "-c", "--create"):
            f = _val(argv, "-f", "--file") or (pos[0] if not argv[1].startswith("-") and pos else None)
            return E("tar cria arquivo", [_abs(f or ".", cwd)])
        return E("tar extrai arquivos", [_abs(_val(argv, "-C", "--directory") or ".", cwd)])
    if nome == "unzip":
        return L() if _tem(argv, "-l", "-t", "-Z") else E("unzip extrai", [_abs(_val(argv, "-d") or ".", cwd)])
    if nome in ("zip", "7z", "gzip", "gunzip", "xz", "unxz", "bzip2", "bunzip2", "zstd", "unzstd"):
        if nome in ("gzip", "gunzip", "xz", "unxz", "bzip2", "bunzip2", "zstd", "unzstd") and (_tem(argv, "-c", "--stdout", "-l", "--list", "-t", "--test")):
            return L()
        if nome == "7z" and pos[:1] in (["l"], ["t"]):
            return L()
        return E(f"{nome} grava arquivos", [_abs(p, cwd) for p in pos] or [cwd])
    if nome in ("rsync",):
        if any(re.match(r"^[\w.@-]+:", p) for p in pos):
            return N("rsync remoto: faça manualmente")
        return E("rsync grava cópia", [_abs(pos[-1], cwd)] if pos else [cwd])
    if nome in ("ffmpeg", "magick", "convert", "yt-dlp", "pip", "pip3", "uv", "npm", "pnpm", "npx", "make", "cargo", "go", "notify-send",
                "wl-copy", "wl-paste", "grim", "slurp", "qalc", "mount", "umount"):
        if nome in ("mount", "umount"):
            return R(f"{nome} precisa de root")
        if nome in ("pip", "pip3") and pos[:1] and pos[0] in ("list", "show", "freeze", "check"):
            return L()
        if nome in ("npm", "pnpm") and pos[:1] and pos[0] in ("ls", "list", "view", "outdated"):
            return L()
        if nome == "qalc":
            return L()
        return E(f"{nome}: pede aprovação", [cwd])
    if nome in ("btrfs", "modprobe", "rmmod", "insmod", "sysctl", "grub-mkconfig", "mkinitcpio", "efibootmgr", "ufw", "iptables", "nft", "tlp"):
        if nome == "sysctl" and not _tem(argv, "-w", "--write", "-p", "--load", "--system") and not any("=" in p for p in pos):
            return L()
        return R(f"{nome} precisa de root")
    return E(f"comando não classificado ({nome}): pede aprovação", [cwd])


def classificar(comando, root=False):
    """-> {"classe", "motivo", "comando", "exibir", "plano", "sem_sudo", "escritas"}. root=True: chamado pelo sudo.run."""
    c = str(comando or "").strip()
    res = {"classe": "NEGADO", "motivo": "", "comando": c, "exibir": c, "plano": None, "sem_sudo": c, "escritas": []}
    if not c:
        res["motivo"] = "comando vazio"; return res
    try:
        seq = _parse(_lexar(c))
        # sudo no início de um comando: tira e classifica o resto como root
        tem_sudo = False
        for it in seq:
            for cm in it["pipe"]:
                if cm["argv"][0] == "sudo":
                    a = cm["argv"][1:]
                    while a and a[0] in ("--", "-A", "-n", "-E"):
                        if a[0] == "-E":
                            raise Recusa("sudo -E (passa o ambiente) não é permitido")
                        a.pop(0)
                    if not a or a[0].startswith("-") or a[0] in ("su", "-s", "-i") or a[0] in SHELLS:
                        raise Recusa("sudo com shell/opção: mande só o comando")
                    cm["flags"] = cm["flags"][len(cm["argv"]) - len(a):]
                    cm["argv"] = a; tem_sudo = True
        root = root or tem_sudo
        pior, motivos, cwd, escritas = "LEITURA", [], HOME, []
        for it in seq:
            pipe = it["pipe"]
            for i, cm in enumerate(pipe):
                # expansão de ~ e glob (feita aqui, então o que roda é o que foi conferido)
                argv = []
                for w, (gl, til) in zip(cm["argv"], cm["flags"]):
                    if til and (w == "~" or w.startswith("~/")):
                        w = HOME + w[1:]
                    if gl:
                        m = sorted(glob.glob(w, root_dir=cwd)) if not os.path.isabs(w) else sorted(glob.glob(w))
                        argv += ["./" + x if x.startswith("-") else x for x in m] if m else [w]
                    else:
                        argv.append(w)
                if argv and INTERP.match(argv[0]) or (argv and argv[0] in SHELLS):
                    if i > 0:
                        raise Recusa("pipe para interpretador (ex.: curl | sh) é proibido")
                if argv[0] == "cd":
                    if len(pipe) > 1:
                        raise Recusa("cd dentro de pipe")
                    d = _abs(argv[1] if len(argv) > 1 else HOME, cwd)
                    if not os.path.isdir(d) or _sensivel(d):
                        raise Recusa(f"cd para {d} não permitido")
                    cwd = d
                    cm["argv"] = ["cd", d]; continue
                # nenhum argumento pode apontar para lugar sensível (leitura de segredo)
                for a in argv[1:] + [r[2] for r in cm["redir"] if r[1] != "dup"]:
                    for v in ([a] + ([a.split("=", 1)[1]] if a.startswith("-") and "=" in a else []) +
                              ([a[2:]] if a.startswith("-") and not a.startswith("--") and len(a) > 2 else [])):
                        if v and not v.startswith("-") and _sensivel(_abs(v, cwd)):
                            raise Recusa(f"caminho sensível: {_abs(v, cwd)}")
                classe, motivo, argv, esc = _cmd(argv, cwd, root)
                for r in cm["redir"]:
                    if r[1] in ("w", "a"):
                        p = _abs(r[2], cwd)
                        r[2] = p
                        if p not in ("/dev/null", "/dev/stdout", "/dev/stderr"):
                            esc = esc + [p]
                            if ORDEM[classe] < 1:
                                classe, motivo = "ESCRITA_HOME", "'>' grava arquivo"
                    elif r[1] == "<":
                        r[2] = _abs(r[2], cwd)
                for p in esc:
                    m = _escrita(p, root)
                    if m:
                        classe, motivo = "NEGADO", m
                if classe == "NEGADO":
                    raise Recusa(motivo)
                cm["argv"] = argv
                escritas += esc
                motivos.append(f"{argv[0]}: {motivo}")
                if ORDEM[classe] > ORDEM[pior]:
                    pior = classe
        if root:
            pior = "ROOT"
        for it in seq:
            for cm in it["pipe"]:
                cm.pop("flags", None)
        res.update(classe=pior, motivo="; ".join(dict.fromkeys(motivos))[:300], plano={"cwd": HOME, "seq": seq}, escritas=escritas,
                   exibir=_exibir(seq), sem_sudo=re.sub(r"(^|[|;&]\s*)sudo\s+(?:(?:-A|-n|--)\s+)*", r"\1", c))
    except Recusa as e:
        res["motivo"] = str(e)
    except Exception as e:
        res["motivo"] = f"não entendi o comando: {e}"
    return res


def _exibir(seq):
    """texto do que vai rodar (com o rm já trocado por gio trash)."""
    out = []
    for it in seq:
        if it["op"]:
            out.append(it["op"])
        cmds = []
        for cm in it["pipe"]:
            t = shlex.join(cm["argv"])
            for fd, modo, alvo in cm["redir"]:
                if modo == "dup":
                    t += f" {fd}>&{alvo}"; continue
                simb = "<" if modo == "<" else ">>" if modo == "a" else ">"
                t += f" {'' if fd == (0 if modo == '<' else 1) else fd}{simb} {shlex.quote(alvo)}"
            cmds.append(t)
        out.append(" | ".join(cmds))
    return " ".join(out)


# ----------------------------------------------------------------- execução
def _cortar(s, lim=LIMITE):
    b = s.encode("utf-8", "replace")
    if len(b) <= lim:
        return s
    return b[:lim - 800].decode("utf-8", "ignore") + f"\n…(cortado: {len(b)} bytes)…\n" + b[-700:].decode("utf-8", "ignore")


def _rodar_plano(plano):
    """roda o plano (dentro do sandbox). -> {"codigo", "saida"}"""
    cwd, rc, saidas = plano.get("cwd") or HOME, 0, []
    for it in plano["seq"]:
        if (it["op"] == "&&" and rc != 0) or (it["op"] == "||" and rc == 0):
            continue
        pipe = it["pipe"]
        if pipe[0]["argv"][0] == "cd":
            cwd, rc = pipe[0]["argv"][1], 0; continue
        err = tempfile.TemporaryFile()
        procs, abertos, ant = [], [], None
        try:
            for i, cm in enumerate(pipe):
                stdin, stdout, stderr = (ant if ant is not None else subprocess.DEVNULL), subprocess.PIPE, err
                for fd, modo, alvo in cm["redir"]:
                    if modo == "dup":
                        if fd == 2 and alvo == 1:
                            stderr = subprocess.STDOUT
                        continue
                    f = next((x for x in abertos if x.name == alvo and x.mode != "rb"), None) if modo != "<" else None
                    if f is None:
                        f = open(alvo, "rb" if modo == "<" else modo + "b"); abertos.append(f)
                    if fd == 0:
                        stdin = f
                    elif fd == 1:
                        stdout = f
                    elif fd == 2:
                        stderr = f
                if stderr == subprocess.STDOUT and stdout is not subprocess.PIPE:
                    stderr = stdout
                try:
                    p = subprocess.Popen(cm["argv"], cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr, env=_env())
                except FileNotFoundError:
                    err.write(f"{cm['argv'][0]}: comando não encontrado\n".encode())
                    p = subprocess.Popen(["false"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
                if ant is not None:
                    ant.close()
                ant = p.stdout
                procs.append(p)
            buf = b""
            if ant is not None:
                while True:
                    ch = ant.read(65536)
                    if not ch:
                        break
                    if len(buf) < 262144:
                        buf += ch
                ant.close()
            for p in procs:
                p.wait()
            rc = procs[-1].returncode
            err.seek(0)
            saidas.append((buf + err.read(65536)).decode("utf-8", "replace"))
        finally:
            for f in abertos:
                f.close()
            err.close()
    return {"codigo": rc, "saida": _cortar("".join(saidas).strip())}


def _bwrap(escrita):
    """/ só leitura, segredos mascarados; na escrita: $HOME e /tmp graváveis, mas a pasta da Friday continua só leitura."""
    if not shutil.which("bwrap"):
        return []
    a = ["bwrap", "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev", "--die-with-parent", "--new-session",
         "--tmpfs", "/var/tmp", "--setenv", "TMPDIR", "/var/tmp"]
    if escrita:
        a += ["--bind", HOME, HOME, "--bind", "/tmp", "/tmp"]
        a += sum((["--ro-bind", p, p] for p in PROTEGIDOS if p not in SENSIVEIS and os.path.exists(p) and not os.path.islink(p)), [])
    for p in SENSIVEIS:
        if not (_dentro(p, HOME) or _dentro(p, f"/run/user/{os.getuid()}")) or os.path.islink(p):
            continue                                        # /etc/shadow, /root: o usuário já não lê; symlink: o destino real está na lista
        if os.path.isdir(p):
            a += ["--tmpfs", p]
        elif os.path.exists(p):
            a += ["--ro-bind", "/dev/null", p]
    return a + ["--"]


def _py():
    return "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable


def _env():
    e = {k: v for k, v in os.environ.items() if k in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_MESSAGES", "TERM", "XDG_RUNTIME_DIR",
                                                    "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "NIRI_SOCKET", "DISPLAY", "TZ")}
    e["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin:" + os.environ.get("PATH", "")
    return e


def _limites(mem, seg):
    if os.path.exists(f"/run/user/{os.getuid()}/bus") and shutil.which("systemd-run"):
        return ["systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={mem}", "-p", f"RuntimeMaxSec={seg}", "--"]
    return ["timeout", "-k", "5", str(seg)]


def executar(comando, aprovado=False, exibir=None):
    """LEITURA roda; ESCRITA_HOME só com aprovado=True (depois do portão de aprovação). -> dict
    exibir: o texto que o dono aprovou; se o glob/cd agora der outro comando, não roda."""
    c = classificar(comando)
    base = {k: c[k] for k in ("classe", "motivo", "exibir")}
    if exibir is not None and exibir != c["exibir"]:
        return dict(base, ok=False, erro="o comando mudou desde a aprovação (arquivos diferentes): peça de novo")
    if not shutil.which("bwrap"):
        return dict(base, ok=False, erro="bwrap não instalado: sem sandbox o terminal não roda")
    if c["classe"] == "NEGADO":
        return dict(base, ok=False, erro="NEGADO: " + c["motivo"])
    if c["classe"] == "ROOT":
        return dict(base, ok=False, erro="precisa de root: vai pelo sudo.run")
    if c["classe"] == "ESCRITA_HOME" and not aprovado:
        return dict(base, ok=False, pendente=True, erro="precisa de aprovação do dono")
    cmd = _limites("512M", 60) + _bwrap(c["classe"] == "ESCRITA_HOME") + [_py(), "-I", os.path.abspath(__file__), "--rodar", json.dumps(c["plano"])]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=75, cwd=HOME, env=_env())
    except subprocess.TimeoutExpired:
        return dict(base, ok=False, erro="tempo esgotado (60 s)")
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        msg = "tempo esgotado (60 s)" if r.returncode in (143, 124, -15) else (r.stderr or r.stdout or f"código {r.returncode}")[-300:]
        return dict(base, ok=False, erro=msg)
    return dict(base, ok=d["codigo"] == 0, codigo=d["codigo"], saida=d["saida"])


def rodar_root(comando, segundos=900):
    """chamado pelo ftools sudo (já aprovado): classifica como root e roda o plano via sudo -A + timeout dentro de um scope."""
    c = classificar(comando, root=True)
    if c["classe"] == "NEGADO":
        return {"ok": False, "erro": "comando bloqueado por segurança: " + c["motivo"] + ("" if "manualmente" in c["motivo"] else " (faça manualmente)"),
                "classe": "NEGADO"}
    cmd = _limites("2G", segundos + 30) + ["sudo", "-A", "--", "timeout", "-k", "10", str(segundos), _py(), "-I", os.path.abspath(__file__),
                                         "--rodar", json.dumps(c["plano"])]
    return {"ok": None, "cmd": cmd, "exibir": c["exibir"]}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--rodar":
        try:
            print(json.dumps(_rodar_plano(json.loads(sys.argv[2])), ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"codigo": 127, "saida": f"erro ao rodar: {e}"}, ensure_ascii=False))
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "classificar":
        d = classificar(" ".join(sys.argv[2:]))
        print(json.dumps({k: d[k] for k in ("classe", "motivo", "exibir")}, ensure_ascii=False)); sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "rodar":
        print(json.dumps(executar(" ".join(sys.argv[2:])), ensure_ascii=False)); sys.exit(0)
    print(__doc__); sys.exit(2)
