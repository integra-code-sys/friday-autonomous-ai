"""Abre app e navegador do sistema. Linux: xdg-open. Windows: Start-Process.
'Navegador' não precisa ser o rótulo do pacote."""
import os
import re
import shutil
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAPA = os.path.join(ROOT, "memory", "mapa_pc.json")

_NAV = {
    "navegador", "browser", "internet", "web", "chrome", "chromium",
    "googlechrome", "firefox", "edge", "msedge", "brave", "opera",
}
_WIN = {
    "firefox": "firefox", "edge": "msedge", "msedge": "msedge", "brave": "brave",
    "notepad": "notepad", "explorer": "explorer", "arquivos": "explorer",
    "terminal": "wt", "console": "cmd", "powershell": "powershell", "calculadora": "calc",
    "calc": "calc", "cmd": "cmd", "tarefas": "taskmgr", "gerenciadordetarefas": "taskmgr",
    "bloco": "notepad", "blocodenotas": "notepad", "config": "ms-settings:",
    "configuracoes": "ms-settings:", "ajustes": "ms-settings:", "camera": "microsoft.windows.camera:",
}
_CAT_LINUX = {
    "calculadora": ["gnome-calculator", "kcalc", "galculator", "xcalc"],
    "calc": ["gnome-calculator", "kcalc", "galculator", "xcalc"],
    "terminal": ["x-terminal-emulator", "kitty", "alacritty", "gnome-terminal", "konsole", "xfce4-terminal"],
    "arquivos": ["nautilus", "dolphin", "thunar", "pcmanfm", "nemo"],
    "gerenciadordearquivos": ["nautilus", "dolphin", "thunar", "pcmanfm", "nemo"],
    "pastas": ["nautilus", "dolphin", "thunar", "pcmanfm", "nemo"],
    "bloco": ["gedit", "kate", "mousepad", "kwrite", "code"],
    "blocodenotas": ["gedit", "kate", "mousepad", "kwrite", "code"],
    "editor": ["gedit", "kate", "mousepad", "kwrite", "code"],
    "configuracoes": ["gnome-control-center", "systemsettings", "xfce4-settings-manager"],
    "ajustes": ["gnome-control-center", "systemsettings", "xfce4-settings-manager"],
    "tarefas": ["gnome-system-monitor", "ksysguard", "htop"],
    "gerenciadordetarefas": ["gnome-system-monitor", "ksysguard"],
}


def windows():
    return sys.platform == "win32" or os.name == "nt"


def norm(s):
    t = unicodedata.normalize("NFKD", str(s or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t)


def limpar_nome_app(s):
    t = unicodedata.normalize("NFKD", str(s or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c)).strip()
    t = re.sub(r"^(?:abrir|abra|abre|inicie|iniciar|inicia|execute|executar|roda|rodar|lan[cç]ar|lan[cç]e|acessar|acesse|ver|mostrar|mostre)\s+", "", t)
    t = re.sub(r"^(?:o|a|os|as|um|uma|uns|umas|meu|minha|meus|minhas|o\s+meu|a\s+minha)\s+", "", t)
    t = re.sub(r"^(?:aplicativo|aplica[cç][aã]o|app|programa|ferramenta)\s+(?:de|do|da|dos|das)?\s*", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def eh_navegador(nome):
    nl = limpar_nome_app(nome)
    nn = norm(nome)
    for c in (nl, nn):
        if c in _NAV or any(nav in c for nav in ("navegador", "browser", "chrome", "firefox", "edge", "brave", "opera")):
            return True
    return False


def _bin_linux():
    for b in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave", "firefox"):
        p = shutil.which(b)
        if p:
            return p
    return ""


def chave_janela(nome):
    n = limpar_nome_app(nome) or norm(nome)
    if n == "firefox":
        return "firefox"
    if n in {"edge", "msedge"}:
        return "msedge"
    if n == "brave":
        return "brave"
    if eh_navegador(nome):
        b = os.path.basename(_bin_linux())
        if "firefox" in b:
            return "firefox"
        if "brave" in b:
            return "brave"
        return "chrom"
    return (nome or "").strip().lower()


def nome_exibicao(nome):
    n = limpar_nome_app(nome) or norm(nome)
    if n == "firefox":
        return "Firefox"
    if n in {"edge", "msedge"}:
        return "Edge"
    if eh_navegador(nome):
        return "Navegador"
    return (nome or "").strip()


def _popen(argv):
    if not argv:
        return False, "sem comando"
    try:
        cmd = list(argv)
        if not windows() and shutil.which("setsid") and cmd[0] != "xdg-open":
            cmd = ["setsid", *cmd]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True, " ".join(cmd[:5])
    except Exception as e:
        return False, str(e)[:180]


def _win_start(alvo):
    alvo = str(alvo or "").strip()
    if not alvo:
        return False, "alvo vazio"
    lit = alvo.replace("'", "''")
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"Start-Process -FilePath '{lit}'"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        return True, f"Start-Process {alvo}"
    except Exception as e:
        try:
            os.startfile(alvo)  # type: ignore[attr-defined]
            return True, f"startfile {alvo}"
        except Exception:
            return False, str(e)[:180]


def abrir_url(url):
    u = str(url or "").strip()
    if not u:
        return False, "url vazia"
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        u = "https://" + u
    if windows():
        return _win_start(u)
    if shutil.which("xdg-open"):
        ok, msg = _popen(["xdg-open", u])
        if ok:
            return True, "xdg-open " + u
    exe = _bin_linux()
    if exe:
        argv = [exe, "--new-tab", u] if "firefox" not in os.path.basename(exe) else [exe, "--new-tab", u]
        ok, msg = _popen(argv)
        if ok:
            return True, "navegador " + u
        return False, msg
    return False, "não achei navegador (xdg-open, chromium ou firefox)"


def _desktops():
    dirs = [
        os.path.expanduser("~/.local/share/applications"),
        "/usr/share/applications",
        "/usr/local/share/applications",
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    ]
    out = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            nomes = os.listdir(d)
        except OSError:
            continue
        for fn in nomes:
            if not fn.endswith(".desktop"):
                continue
            nome, exe = "", ""
            try:
                with open(os.path.join(d, fn), encoding="utf-8", errors="replace") as f:
                    for linha in f:
                        if linha.startswith("Name=") and not nome:
                            nome = linha[5:].strip()
                        elif linha.startswith("Exec=") and not exe:
                            exe = linha[5:].strip()
            except OSError:
                continue
            if nome:
                out.append((fn[:-8], nome, exe))
    return out


def abrir_app(nome):
    bruto = str(nome or "").strip()
    nl = limpar_nome_app(bruto)
    n = norm(bruto)
    chave = nl or n
    if not chave:
        return False, "nome vazio"
    especifico = chave in {"firefox", "brave", "edge", "msedge"}
    if eh_navegador(bruto) and not especifico:
        if windows():
            return _win_start("https://www.google.com/")
        return abrir_url("https://www.google.com/")
    if windows():
        cmd_win = _WIN.get(chave) or _WIN.get(n) or _WIN.get(bruto.lower()) or bruto
        return _win_start(cmd_win)
    if especifico:
        exe = shutil.which(chave if chave != "msedge" else "microsoft-edge") or shutil.which("firefox" if chave == "firefox" else chave)
        if exe:
            return _popen([exe])

    # Categoria Linux conhecida
    if chave in _CAT_LINUX:
        for candidato in _CAT_LINUX[chave]:
            w = shutil.which(candidato)
            if w:
                return _popen([w])

    melhor, nota = None, 0
    for did, titulo, exe in _desktops():
        nn, nd = norm(titulo), norm(did)
        nl_t = limpar_nome_app(titulo)
        v = 100 if (nn == chave or nd == chave or nl_t == chave) else \
            80 if (nn.startswith(chave) or nd.startswith(chave) or nl_t.startswith(chave)) else \
            60 if (chave in nn or chave in nd or chave in nl_t) else 0
        if v > nota:
            nota, melhor = v, (did, titulo, exe)
    if not melhor:
        try:
            import json
            apps = json.load(open(MAPA, encoding="utf-8")).get("apps") or {}
            for did, a in apps.items():
                if isinstance(a, dict) and (chave in norm(a.get("nome", "")) or chave in norm(did)):
                    melhor = (did, a.get("nome") or did, a.get("exec") or "")
                    break
        except Exception:
            pass
    if melhor:
        did, titulo, exe = melhor
        if shutil.which("gtk-launch"):
            ok, msg = _popen(["gtk-launch", did])
            if ok:
                return True, f"abrindo {titulo}"
        if exe:
            cmd = exe.split("%", 1)[0].strip().split()
            if cmd:
                ok, msg = _popen(cmd)
                if ok:
                    return True, f"abrindo {titulo}"
    w = shutil.which(chave) or shutil.which(bruto)
    if w:
        return _popen([w])
    return False, f"app '{bruto}' não está instalado ou não tem atalho"


def abrir(nome):
    return abrir_app(nome)


def abrir_urls(urls):
    falhou = ""
    ok_algum = False
    for u in urls or []:
        ok, msg = abrir_url(u)
        ok_algum = ok_algum or ok
        if not ok:
            falhou = msg
    return (True, "ok") if ok_algum else (False, falhou or "nada para abrir")
