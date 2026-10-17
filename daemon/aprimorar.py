#!/usr/bin/env python3
"""aprimorar — a F.R.I.D.A.Y. PROPÕE melhorias no próprio código; o dono revisa e aprova antes de qualquer mudança real.

  aprimorar.py propor "pedido"    copia o código para uma área isolada, o Claude CLI edita SÓ a cópia, valida (py_compile + qs -p)
                                  e gera a proposta (diff). O código real NÃO é tocado.
  aprimorar.py aplicar ID         (só após aprovação do dono, via prom_ops.gated "self.apply") snapshot + backups .vNbak + copia
  aprimorar.py descartar ID       apaga a proposta
  aprimorar.py desfazer [ID]      volta o código ao snapshot tirado antes de aplicar (padrão: a última aplicada)
  aprimorar.py listar             últimas propostas
  aprimorar.py falha "texto"      registra uma falha (a mente usa para sugerir melhorias)

Saída: JSON numa linha. Nunca reinicia o daemon nem a interface.
"""
import difflib, glob, json, os, re, shutil, subprocess, sys, tarfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "memory", "aprimorar")
FALHAS = os.path.join(ROOT, "memory", "falhas.jsonl")
MODEL = os.environ.get("PROMETHEUS_MODEL", "claude-sonnet-5-5")
CODIGO = ["daemon/*.py", "daemon/pc", "daemon/prometheus-ctl", "daemon/construtor_web/*", "shell/*.qml", "shell/*.html", "shell/*.js",
          "shell/*.frag", "tools/*.py", "run.sh", "Docs/FRIDAY.md",
          # app do CELULAR (APK sem Gradle): Java + página + manifesto; compila com app-remoto/build.sh
          "app-remoto/src/dev/integra/friday/*.java", "app-remoto/assets/*.js", "app-remoto/assets/*.html", "app-remoto/assets/*.css",
          "app-remoto/AndroidManifest.xml", "app-remoto/res/*/*.xml", "app-remoto/build.sh"]
ANDROID = os.path.expanduser("~/.local/android")
ADB = os.path.join(ANDROID, "sdk", "platform-tools", "adb")
LINKS = ["shell/assets", "models"]                       # só leitura: entram na cópia como atalho (pesados)
FERRAMENTAS = "Read,Edit,Write,Glob,Grep,Bash(python -m py_compile:*),Bash(grep:*),Bash(ls:*)"
_BAK = re.compile(r"\.v\d*\w*bak$|\.bak$")

PROMPT = """Você está PROPONDO uma melhoria na F.R.I.D.A.Y., assistente local do dono. Esta pasta é uma CÓPIA do projeto: edite à vontade aqui;
o dono vai revisar o diff e só então aplicar. Pedido: {pedido}

MAPA: daemon/prometheus.py (daemon: voz, mente proativa mind_think, roteamento friday_ask) · daemon/friday.py (SYSTEM de intenções,
run_action com as ações) · daemon/agent.py (TOOLS do agente) · daemon/plano.py (tarefas em etapas) · daemon/ftools.py (CLI determinística:
operações arriscadas vão para cá) · daemon/prom_ops.py (política: ações externas passam por gated) · shell/FridayPanels.qml
(telas/painéis: socket {{"type":"painel","op":...}}) · shell/shell.qml (interface). Leia Docs/FRIDAY.md antes.
APP DO CELULAR (app-remoto/, Java puro sem Gradle, minSdk 26): Cerebro.java (laço do cérebro local), Ferramentas.java (ferramentas do
celular), Voz.java/Ouvido.java (STT/TTS/voz do dono), Aprende.java (auto-aprendizado), Assistente.java (botão lateral), Flutuante.java
(janelas flutuantes), Acesso.java (serviço sempre ativo + ponte HTTP), Agenda.java; assets/app.js + index.html (interface). Pedidos
marcados [APP DO CELULAR] mexem SÓ em app-remoto/.
{falhas}
REGRAS: mudança MÍNIMA, no estilo do código ao redor; não crie arquivos .bak; não instale pacotes; envios (WhatsApp/e-mail/sudo) continuam
passando por prom_ops.gated; depois de editar .py rode `python -m py_compile <arquivo>`.
Ao terminar responda em pt-BR, 2-4 frases: o que mudou (arquivos) e como o dono testa."""


def out(d, code=0):
    print(json.dumps(d, ensure_ascii=False)); sys.exit(code)


def _rel(base):
    fs = set()
    for g in CODIGO:
        fs |= {os.path.relpath(f, base) for f in glob.glob(os.path.join(base, g)) if os.path.isfile(f) and not _BAK.search(f)}
    return fs


def _hist():
    try:
        return json.load(open(os.path.join(DIR, "historico.json")))
    except Exception:
        return []


def _salvar(h):
    os.makedirs(DIR, exist_ok=True)
    json.dump(h[-50:], open(os.path.join(DIR, "historico.json"), "w"), ensure_ascii=False, indent=1)


def _item(h, mid, estado=None):
    return next((i for i in reversed(h) if (not mid or i["id"] == mid) and (estado is None or i["estado"] == estado)), None)


def _validar(base, mudou):
    erros = []
    for f in mudou:
        p = os.path.join(base, f)
        if f.endswith(".py") and os.path.exists(p):
            try:
                compile(open(p, "rb").read(), p, "exec")       # só checa sintaxe (não grava .pyc na cópia)
            except SyntaxError as e:
                erros.append(f"{f}:{e.lineno}: {e.msg}")
    if any(f.endswith(".java") for f in mudou):                 # app do celular: compila TODAS as fontes contra o android.jar
        jdk = (glob.glob(os.path.join(ANDROID, "jdk-17*")) or [""])[0]
        cls = os.path.join(base, ".javac-out")
        fontes = glob.glob(os.path.join(base, "app-remoto", "src", "**", "*.java"), recursive=True)
        gen = glob.glob(os.path.join(ROOT, "app-remoto", "build", "gen", "**", "*.java"), recursive=True)    # R.java do último build
        cp = os.path.join(ANDROID, "sdk", "platforms", "android-34", "android.jar") + ":" + os.path.join(ANDROID, "libs", "ort", "classes.jar")
        r = subprocess.run([os.path.join(jdk, "bin", "javac"), "-nowarn", "-source", "11", "-target", "11", "-cp", cp, "-d", cls] + fontes + gen,
                           capture_output=True, text=True)
        shutil.rmtree(cls, ignore_errors=True)
        if r.returncode != 0:
            erros.append("Java: " + " | ".join([l for l in r.stderr.splitlines() if "error:" in l][:4] or [r.stderr[-300:]]))
    if any(f.endswith(".qml") for f in mudou):
        r = subprocess.run(["timeout", "8", "qs", "-p", os.path.join(base, "shell", "shell.qml")], capture_output=True, text=True)
        log = r.stdout + r.stderr
        ruim = [l for l in log.splitlines() if re.search(r"\bERROR\b|error:|is not a type|Cannot assign|Expected token", l)]
        if r.returncode != 124 or ruim:
            erros.append("QML: " + " | ".join(ruim[:4] or [log[-300:]]))
    return erros


def _falhas_recentes(n=5):
    try:
        return [json.loads(l)["texto"] for l in open(FALHAS).read().splitlines()[-n:]]
    except Exception:
        return []


def cmd_propor(args):
    pedido = " ".join(args).strip()
    if not pedido:
        out({"ok": False, "erro": "pedido vazio"}, 2)
    mid = time.strftime("%Y%m%d-%H%M%S")
    while os.path.exists(os.path.join(DIR, mid)):
        mid += "x"
    work = os.path.join(DIR, mid, "work")
    originais = _rel(ROOT)
    for f in originais:
        os.makedirs(os.path.dirname(os.path.join(work, f)), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, f), os.path.join(work, f))
    for l in LINKS:
        if os.path.exists(os.path.join(ROOT, l)):
            os.makedirs(os.path.dirname(os.path.join(work, l)), exist_ok=True)
            os.symlink(os.path.join(ROOT, l), os.path.join(work, l))
    fal = _falhas_recentes()
    prompt = PROMPT.format(pedido=pedido, falhas=("FALHAS RECENTES DELA: " + " · ".join(fal) + "\n") if fal else "")
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", MODEL, "--permission-mode", "acceptEdits",
           "--allowedTools", FERRAMENTAS, "--add-dir", work]
    try:
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=1800)
        try:
            relato = json.loads(r.stdout).get("result", "")
        except Exception:
            relato = (r.stdout or r.stderr)[-500:]
    except subprocess.TimeoutExpired:
        relato = "tempo esgotado (30 min)"
    novos = _rel(work)
    mudou = sorted(f for f in novos if f not in originais or open(os.path.join(work, f), "rb").read() != open(os.path.join(ROOT, f), "rb").read())
    diff = []
    for f in mudou:
        a = open(os.path.join(ROOT, f), errors="replace").read().splitlines(True) if f in originais else []
        b = open(os.path.join(work, f), errors="replace").read().splitlines(True)
        diff += difflib.unified_diff(a, b, "a/" + f, "b/" + f)
    open(os.path.join(DIR, mid, "proposta.diff"), "w").write("".join(diff))
    erros = _validar(work, mudou) if mudou else []
    item = {"id": mid, "pedido": pedido, "arquivos": mudou, "erros": erros, "relato": str(relato)[:1500], "t": int(time.time()),
            "linhas": sum(1 for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---")),
            "estado": "proposta" if mudou and not erros else "invalida"}
    h = _hist(); h.append(item); _salvar(h)
    out({**item, "diff": os.path.join(DIR, mid, "proposta.diff")}, 0 if item["estado"] == "proposta" else 1)


def _bak(p):
    n = 1
    while os.path.exists(f"{p}.v{n}bak"):
        n += 1
    shutil.copy2(p, f"{p}.v{n}bak")


def cmd_aplicar(args):
    h = _hist()
    it = _item(h, args[0] if args else None, "proposta")
    if not it:
        out({"ok": False, "erro": "proposta não encontrada (ou já aplicada/descartada)"}, 1)
    work = os.path.join(DIR, it["id"], "work")
    if any(os.path.exists(os.path.join(ROOT, f)) and os.path.getmtime(os.path.join(ROOT, f)) > it["t"] for f in it["arquivos"]):
        out({"ok": False, "erro": "o código real mudou depois da proposta; refaça a proposta"}, 1)
    with tarfile.open(os.path.join(DIR, it["id"], "antes.tar.gz"), "w:gz") as t:
        for f in it["arquivos"]:
            if os.path.exists(os.path.join(ROOT, f)):
                t.add(os.path.join(ROOT, f), arcname=f)
    for f in it["arquivos"]:
        dst = os.path.join(ROOT, f)
        if os.path.exists(dst):
            _bak(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(work, f), dst)
    it["estado"] = "aplicada"; it["aplicada"] = int(time.time()); _salvar(h)
    shutil.rmtree(work, ignore_errors=True)
    apk = _apk() if any(f.startswith("app-remoto/") for f in it["arquivos"]) else ""
    out({"ok": True, "id": it["id"], "arquivos": it["arquivos"], "apk": apk,
         "obs": "vale após reiniciar o daemon/interface" if not apk else apk})


def _apk():
    """melhoria no app do celular: gera o APK e instala pelo ADB Wi-Fi (o serviço de acessibilidade cai no update: religa)."""
    r = subprocess.run(["sh", os.path.join(ROOT, "app-remoto", "build.sh")], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return "APK NÃO gerado: " + (r.stdout + r.stderr)[-200:]
    dev = [l.split()[0] for l in subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout.splitlines()[1:] if l.endswith("device")]
    if not dev:
        return "APK gerado em app-remoto/dist (celular fora do ADB: instale manualmente)"
    i = subprocess.run([ADB, "-s", dev[0], "install", "-r", os.path.join(ROOT, "app-remoto", "dist", "friday-remoto.apk")], capture_output=True, text=True, timeout=180)
    for c in (["settings", "put", "secure", "enabled_accessibility_services", "dev.integra.friday/dev.integra.friday.Acesso"],
              ["settings", "put", "secure", "accessibility_enabled", "1"]):
        subprocess.run([ADB, "-s", dev[0], "shell"] + c, capture_output=True, timeout=20)
    return "APK instalado no celular" if "Success" in i.stdout else "APK gerado, mas a instalação falhou: " + (i.stdout + i.stderr)[-150:]


def cmd_descartar(args):
    h = _hist()
    it = _item(h, args[0] if args else None, "proposta")
    if not it:
        out({"ok": False, "erro": "nenhuma proposta pendente"}, 1)
    it["estado"] = "descartada"; _salvar(h)
    shutil.rmtree(os.path.join(DIR, it["id"], "work"), ignore_errors=True)
    out({"ok": True, "id": it["id"]})


def cmd_desfazer(args):
    h = _hist()
    it = _item(h, args[0] if args else None, "aplicada")
    if not it:
        out({"ok": False, "erro": "nenhuma melhoria aplicada para desfazer"}, 1)
    with tarfile.open(os.path.join(DIR, it["id"], "antes.tar.gz")) as t:
        antes = set(t.getnames())
        t.extractall(ROOT, filter="data")
    for f in it["arquivos"]:
        if f not in antes:                            # arquivo criado pela melhoria
            try:
                os.remove(os.path.join(ROOT, f))
            except OSError:
                pass
    it["estado"] = "desfeita"; _salvar(h)
    out({"ok": True, "id": it["id"], "pedido": it["pedido"], "arquivos": it["arquivos"]})


def cmd_listar(_):
    out({"ok": True, "itens": [{k: i.get(k) for k in ("id", "pedido", "estado", "arquivos", "linhas")} for i in _hist()[-10:]]})


def cmd_falha(args):
    os.makedirs(os.path.dirname(FALHAS), exist_ok=True)
    with open(FALHAS, "a") as f:
        f.write(json.dumps({"t": int(time.time()), "texto": " ".join(args)[:300]}, ensure_ascii=False) + "\n")
    out({"ok": True})


if __name__ == "__main__":
    cmds = {"propor": cmd_propor, "aplicar": cmd_aplicar, "descartar": cmd_descartar, "desfazer": cmd_desfazer, "listar": cmd_listar, "falha": cmd_falha}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__); sys.exit(2)
    cmds[sys.argv[1]](sys.argv[2:])
