"""IDE do MODO DEV: painel de controle do Claude CLI para programar (projeto, árvore, arquivo, diff, chat ao vivo).

Protocolo (socket unix, JSON por linha; o prometheus.py roteia {"type":"ide", "op":...} para IDE.tratar):
  estado | abrir_projeto(caminho) | arvore(rel) | ler(rel) | diff(rel) | enviar(texto) | parar | nova_sessao | modelo(modelo)
Respostas só a quem pediu: ide_estado, ide_arvore, ide_arquivo, ide_diff.
Eventos a todos: {"type":"ide_ev","id","hora","kind",...} kinds: usuario texto pensamento ferramenta resultado terminal
  edicao inicio fim erro.
Segurança: caminhos sempre relativos ao projeto; recusa '..' para fora, Secrets/, .env*, *.pem, *.key. Todo texto
emitido passa por mascarar() (dev.mascarar quando disponível).
"""
import asyncio, difflib, json, os, re, signal, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # .../Projeto Prometheus
SISTEMAS = os.path.expanduser("~/Workspace/Projetos/Sistemas")
ESTADO_PATH = os.path.join(ROOT, "memory", "dev_ide.json")
MODELO_PADRAO = "sonnet"

MAX_LER = 300 * 1024
MAX_ITENS = 1500
PROF = 3
IGN_NOMES = {".git", "node_modules", "dist", "build", "__pycache__", "Secrets"}
IGN_EXT = (".zip", ".tar.gz", ".tgz", ".7z", ".rar", ".so", ".o", ".a", ".pyc", ".pyo", ".exe", ".dll", ".apk",
           ".appimage", ".bin", ".iso", ".deb", ".gguf", ".onnx", ".pt", ".pth", ".safetensors", ".class", ".jar")

# ---------- mascaramento ----------
try:
    import dev as _dev
    _mascarar_full = _dev.mascarar
except Exception:
    _dev = None
    _SEG = [
        (re.compile(r"(?i)\b(senha|password|passwd|token|api[_-]?key|secret|bearer|pin|authorization)\b(\s*[:=]\s*|\s+)(\S+)"), r"\1\2•••"),
        (re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,}|hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9\-]{10,})"), "•••"),
        (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "•••"),
        (re.compile(r"(?i)[^\s'\"]*/Secrets/[^\s'\"]*"), "[Secrets]"),
    ]

    def _mascarar_full(v):
        if isinstance(v, str):
            for rx, rep in _SEG:
                v = rx.sub(rep, v)
        return v

# Para código (arquivo/diff) não aplica a regra de "blob longo" (estragaria identificadores longos).
_SEG_LEVE = [
    (re.compile(r"(?i)\b(senha|password|passwd|api[_-]?key|secret|bearer|authorization)\b(\s*[:=]\s*)(['\"]?)([^\s'\"]{4,})"), r"\1\2\3•••"),
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,}|hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9\-]{10,})"), "•••"),
    (re.compile(r"(?i)[^\s'\"]*/Secrets/[^\s'\"]*"), "[Secrets]"),
]


def mascarar(s):
    return _mascarar_full(s) if isinstance(s, str) else s


def mascarar_codigo(s):
    if not isinstance(s, str):
        return s
    for rx, rep in _SEG_LEVE:
        s = rx.sub(rep, s)
    return s


def _corta(s, n):
    s = s if isinstance(s, str) else str(s)
    return s if len(s) <= n else s[:n] + f"\n… (+{len(s) - n} caracteres)"


# ---------- caminhos ----------
def _proibido(rel):
    partes = [p for p in rel.replace("\\", "/").split("/") if p]
    for p in partes:
        pl = p.lower()
        if pl == "secrets" or pl == ".env" or pl.startswith(".env."):
            return True
    base = partes[-1].lower() if partes else ""
    return base.endswith(".pem") or base.endswith(".key")


def _ignorar(nome):
    nl = nome.lower()
    if nome in IGN_NOMES or nl.startswith(".venv") or nl.endswith("bak"):
        return True
    if nl == ".env" or nl.startswith(".env.") or nl.endswith(".pem") or nl.endswith(".key"):
        return True
    return nl.endswith(IGN_EXT)


def _eh_binario(dados):
    if b"\x00" in dados[:8192]:
        return True
    try:
        dados[:8192].decode("utf-8")
    except UnicodeDecodeError as e:
        return e.start < len(dados[:8192]) - 4          # corte no meio de um caractere multibyte no fim é ok
    return False


def _ler_texto(caminho):
    try:
        with open(caminho, "rb") as f:
            d = f.read()
    except FileNotFoundError:
        return ""
    except OSError:
        return None
    if _eh_binario(d):
        return None
    return d.decode("utf-8", "replace")


def _udiff(antes, depois, rel):
    a = antes.splitlines(keepends=True)
    b = depois.splitlines(keepends=True)
    linhas = difflib.unified_diff(a, b, fromfile="a/" + rel, tofile="b/" + rel, n=3)
    return "".join(l if l.endswith("\n") else l + "\n\\ No newline at end of file\n" for l in linhas)


class IDE:
    def __init__(self, publicar, estado_path=ESTADO_PATH, projeto_padrao=ROOT, cmd_claude="claude", sistemas=SISTEMAS):
        self.publicar = publicar
        self.estado_path = estado_path
        self.projeto_padrao = projeto_padrao
        self.cmd_claude = cmd_claude
        self.sistemas = sistemas
        self.sessoes = {}
        self.modelo = MODELO_PADRAO
        self.custo_total = 0.0
        self.projeto = projeto_padrao
        self._carregar()
        self.proc = None
        self.tarefa = None
        self._seq = 0
        self._antes = {}            # (projeto, rel) -> conteúdo antes da 1ª edição nesta sessão
        self.alterados = {}         # projeto -> set(rel)
        self._pend = {}             # tool_id -> {"nome", "input"}

    # ----- persistência -----
    def _carregar(self):
        try:
            with open(self.estado_path, encoding="utf-8") as f:
                d = json.load(f)
            self.sessoes = {k: v for k, v in (d.get("sessoes") or {}).items() if isinstance(v, str)}
            self.modelo = d.get("modelo") or MODELO_PADRAO
            self.custo_total = float(d.get("custo_total") or 0.0)
            p = d.get("projeto")
            if p and os.path.isdir(p):
                self.projeto = p
        except (OSError, ValueError, TypeError):
            pass

    def _salvar(self):
        d = {"projeto": self.projeto, "sessoes": self.sessoes, "modelo": self.modelo, "custo_total": round(self.custo_total, 6)}
        try:
            os.makedirs(os.path.dirname(self.estado_path), exist_ok=True)
            tmp = self.estado_path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.estado_path)
        except OSError as e:
            print("dev_ide: falha ao salvar estado:", e, flush=True)

    # ----- projetos / estado -----
    def projetos(self):
        lst = []
        vistos = set()
        def _add(nome, cam):
            rc = os.path.realpath(cam)
            if rc not in vistos and os.path.isdir(rc):
                vistos.add(rc)
                lst.append({"nome": nome, "caminho": cam})
        if os.path.isdir(self.projeto_padrao):
            _add(os.path.basename(self.projeto_padrao), self.projeto_padrao)
        for base_dir in (self.sistemas, os.path.expanduser("~/Workspace")):
            try:
                for e in sorted(os.scandir(base_dir), key=lambda e: e.name.lower()):
                    if e.is_dir() and not e.name.startswith(".") and not _ignorar(e.name):
                        _add(e.name, e.path)
            except OSError:
                pass
        try:
            pjson = os.path.join(ROOT, "memory", "projetos.json")
            if os.path.exists(pjson):
                for p in json.load(open(pjson, encoding="utf-8")).get("projetos", [])[:35]:
                    if p.get("caminho") and p.get("nome"):
                        _add(str(p["nome"]), str(p["caminho"]))
        except Exception:
            pass
        return lst

    @property
    def rodando(self):
        return self.proc is not None and self.proc.returncode is None

    def _alt(self, projeto=None):
        return self.alterados.setdefault(projeto or self.projeto, set())

    def estado_dict(self):
        return {"type": "ide_estado", "projeto": self.projeto, "projetos": self.projetos(),
                "sessao": self.sessoes.get(self.projeto, ""), "rodando": self.rodando, "modelo": self.modelo,
                "custo_total": round(self.custo_total, 4), "alterados": sorted(self._alt())}

    def _resolver(self, rel, projeto=None):
        """rel -> (caminho absoluto real, rel normalizado). ValueError se fora do projeto ou proibido."""
        base = os.path.realpath(projeto or self.projeto)
        rel = (rel or "").strip()
        alvo = os.path.realpath(os.path.join(base, rel)) if not os.path.isabs(rel) else os.path.realpath(rel)
        if alvo != base and not alvo.startswith(base + os.sep):
            raise ValueError("caminho fora do projeto")
        reln = "" if alvo == base else os.path.relpath(alvo, base)
        if _proibido(reln):
            raise ValueError("caminho protegido")
        return alvo, reln

    def _rel_de(self, file_path, projeto):
        if not file_path:
            return None
        base = os.path.realpath(projeto)
        alvo = os.path.realpath(file_path if os.path.isabs(file_path) else os.path.join(base, file_path))
        if alvo == base or not alvo.startswith(base + os.sep):
            return None
        return os.path.relpath(alvo, base)

    # ----- árvore / ler / diff -----
    def arvore(self, rel=""):
        try:
            raiz, reln = self._resolver(rel)
        except ValueError as e:
            return {"type": "ide_arvore", "rel": rel, "itens": [], "erro": str(e)}
        alt = self._alt()
        alt_dirs = set()
        for a in alt:
            p = os.path.dirname(a)
            while p:
                alt_dirs.add(p); p = os.path.dirname(p)
        itens = []

        def anda(d, drel, nivel):
            if nivel >= PROF or len(itens) >= MAX_ITENS:
                return
            try:
                ents = [e for e in os.scandir(d) if not _ignorar(e.name)]
            except OSError:
                return
            ents.sort(key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
            for e in ents:
                if len(itens) >= MAX_ITENS:
                    return
                r = os.path.join(drel, e.name) if drel else e.name
                eh_dir = e.is_dir(follow_symlinks=False)
                itens.append({"nome": e.name, "rel": r, "dir": eh_dir, "nivel": nivel,
                              "alterado": (r in alt_dirs) if eh_dir else (r in alt)})
                if eh_dir:
                    anda(e.path, r, nivel + 1)

        if os.path.isdir(raiz):
            anda(raiz, reln, 0)
        return {"type": "ide_arvore", "rel": reln, "itens": itens, "truncado": len(itens) >= MAX_ITENS}

    def ler(self, rel):
        try:
            alvo, reln = self._resolver(rel)
        except ValueError as e:
            return {"type": "ide_arquivo", "rel": rel, "texto": "", "linhas": 0, "truncado": False, "erro": str(e)}
        if not os.path.isfile(alvo):
            return {"type": "ide_arquivo", "rel": reln, "texto": "", "linhas": 0, "truncado": False, "erro": "não é arquivo"}
        try:
            tam = os.path.getsize(alvo)
            with open(alvo, "rb") as f:
                d = f.read(MAX_LER)
        except OSError as e:
            return {"type": "ide_arquivo", "rel": reln, "texto": "", "linhas": 0, "truncado": False, "erro": str(e)}
        if _eh_binario(d):
            return {"type": "ide_arquivo", "rel": reln, "texto": "(arquivo binário)", "linhas": 0, "truncado": False}
        txt = mascarar_codigo(d.decode("utf-8", "replace"))
        return {"type": "ide_arquivo", "rel": reln, "texto": txt, "linhas": txt.count("\n") + (0 if txt.endswith("\n") or not txt else 1),
                "truncado": tam > MAX_LER}

    async def _git(self, *args):
        try:
            p = await asyncio.create_subprocess_exec("git", *args, cwd=self.projeto, stdin=asyncio.subprocess.DEVNULL,
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(p.communicate(), 10)
            return p.returncode, out.decode("utf-8", "replace")
        except (OSError, asyncio.TimeoutError):
            return -1, ""

    async def diff(self, rel):
        try:
            alvo, reln = self._resolver(rel)
        except ValueError as e:
            return {"type": "ide_diff", "rel": rel, "diff": "", "erro": str(e)}
        txt = ""
        rc, _ = await self._git("rev-parse", "--is-inside-work-tree")
        if rc == 0:
            rc, txt = await self._git("diff", "--no-color", "--no-ext-diff", "HEAD", "--", reln)
            if rc != 0:
                rc, txt = await self._git("diff", "--no-color", "--no-ext-diff", "--", reln)
        if not txt.strip():
            antes = self._antes.get((self.projeto, reln))
            if antes is not None:
                atual = _ler_texto(alvo)
                txt = _udiff(antes, atual or "", reln) if atual is not None else ""
        return {"type": "ide_diff", "rel": reln, "diff": _corta(mascarar_codigo(txt), 200000)}

    # ----- eventos -----
    async def _ev(self, kind, **campos):
        self._seq += 1
        ev = {"type": "ide_ev", "id": self._seq, "hora": time.strftime("%H:%M:%S"), "kind": kind}
        for k, v in campos.items():
            if k in ("texto", "resumo", "args", "comando", "saida", "nome"):
                v = mascarar(v)
            elif k == "diff":
                v = mascarar_codigo(v)
            ev[k] = v
        if _dev is not None:
            try:
                resumo_txt = str(ev.get("texto") or ev.get("resumo") or ev.get("comando") or ev.get("arquivo") or kind)[:600]
                _dev.emitir("claude", kind, resumo_txt, **{k: v for k, v in ev.items() if k in ("diff", "args", "custo", "dur_s", "turnos")})
            except Exception:
                pass
        try:
            await self.publicar(ev)
        except Exception as e:
            print("dev_ide: publicar falhou:", e, flush=True)
        return ev

    # ----- roteamento -----
    async def tratar(self, msg, responder):
        op = msg.get("op", "estado")
        try:
            if op == "estado":
                await responder(self.estado_dict())
            elif op == "abrir_projeto":
                cam = os.path.realpath(os.path.expanduser(str(msg.get("caminho", ""))))
                validos = {os.path.realpath(p["caminho"]) for p in self.projetos()}
                if self.rodando:
                    await self._ev("erro", texto="já estou trabalhando; diga parar antes de trocar de projeto")
                elif cam not in validos:
                    await self._ev("erro", texto=f"projeto não permitido: {os.path.basename(cam)}")
                else:
                    self.projeto = cam
                    self._salvar()
                await responder(self.estado_dict())
                await responder(self.arvore(""))
            elif op == "arvore":
                await responder(self.arvore(str(msg.get("rel") or "")))
            elif op == "ler":
                await responder(self.ler(str(msg.get("rel") or "")))
            elif op == "diff":
                await responder(await self.diff(str(msg.get("rel") or "")))
            elif op == "enviar":
                texto = str(msg.get("texto") or "").strip()
                if not texto:
                    return
                if self.rodando or (self.tarefa and not self.tarefa.done()):
                    await self._ev("erro", texto="já estou trabalhando; diga parar")
                    return
                self.tarefa = asyncio.create_task(self._executar(texto))
            elif op == "parar":
                asyncio.create_task(self.parar())
            elif op == "nova_sessao":
                if self.rodando:
                    await self._ev("erro", texto="já estou trabalhando; diga parar")
                else:
                    self.sessoes.pop(self.projeto, None)
                    self._limpar_sessao(self.projeto)
                    self._salvar()
                await responder(self.estado_dict())
            elif op == "modelo":
                m = str(msg.get("modelo") or "").strip()
                if re.fullmatch(r"[A-Za-z0-9._\-\[\]]{2,60}", m):
                    self.modelo = m
                    self._salvar()
                else:
                    await self._ev("erro", texto="modelo inválido")
                await responder(self.estado_dict())
            else:
                await self._ev("erro", texto=f"op desconhecida: {op}")
        except Exception as e:
            await self._ev("erro", texto=f"falha em {op}: {e}")

    def _limpar_sessao(self, projeto):
        for k in [k for k in self._antes if k[0] == projeto]:
            del self._antes[k]
        self.alterados.pop(projeto, None)

    async def parar(self):
        p = self.proc
        if p is None or p.returncode is not None:
            return
        try:
            p.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(p.wait(), 3)
            except asyncio.TimeoutError:
                p.terminate()
                try:
                    await asyncio.wait_for(p.wait(), 3)
                except asyncio.TimeoutError:
                    p.kill()
        except ProcessLookupError:
            pass
        await self._ev("erro", texto="interrompido pelo dono")

    # ----- execução do Claude -----
    async def _executar(self, texto):
        projeto = self.projeto
        sessao = self.sessoes.get(projeto)
        cmd = [self.cmd_claude, "-p", texto, "--output-format", "stream-json", "--verbose", "--model", self.modelo,
               "--permission-mode", "bypassPermissions"]
        if sessao:
            cmd += ["--resume", sessao]
        await self._ev("usuario", texto=texto)
        ctx = {"projeto": projeto, "teve_fim": False}
        self._pend = {}
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE"))}
        try:
            self.proc = await asyncio.create_subprocess_exec(*cmd, cwd=projeto, stdin=asyncio.subprocess.DEVNULL,
                                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                             limit=64 * 1024 * 1024, env=clean_env)
        except FileNotFoundError:
            await self._ev("erro", texto="Claude CLI não encontrado no PATH")
            return
        except OSError as e:
            await self._ev("erro", texto=f"não consegui iniciar o Claude: {e}")
            return
        err_buf = []

        async def le_err():
            while True:
                l = await self.proc.stderr.readline()
                if not l:
                    break
                err_buf.append(l.decode("utf-8", "replace"))
                del err_buf[:-40]

        t_err = asyncio.create_task(le_err())
        try:
            while True:
                try:
                    linha = await self.proc.stdout.readline()
                except ValueError:
                    continue                          # linha absurda (> limit): ignora
                if not linha:
                    break
                await self.processar_linha(linha, ctx)
            await self.proc.wait()
            await t_err
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._ev("erro", texto=f"falha lendo o Claude: {e}")
        rc = self.proc.returncode
        if rc not in (0, None) and not ctx["teve_fim"] and rc not in (-signal.SIGINT, -signal.SIGTERM, -signal.SIGKILL):
            await self._ev("erro", texto=_corta("".join(err_buf).strip() or f"Claude saiu com código {rc}", 3000))
        self.proc = None

    async def processar_linha(self, linha, ctx):
        if isinstance(linha, bytes):
            linha = linha.decode("utf-8", "replace")
        linha = linha.strip()
        if not linha:
            return
        try:
            ev = json.loads(linha)
        except ValueError:
            return
        if isinstance(ev, dict):
            await self.processar_evento(ev, ctx)

    async def processar_evento(self, ev, ctx):
        projeto = ctx["projeto"]
        sid = ev.get("session_id")
        if isinstance(sid, str) and sid and self.sessoes.get(projeto) != sid:
            self.sessoes[projeto] = sid
            self._salvar()
        tp = ev.get("type")
        if tp == "system" and ev.get("subtype") == "init":
            await self._ev("inicio", sessao=sid or "", modelo=ev.get("model") or self.modelo)
        elif tp == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                ct = c.get("type")
                if ct == "text" and c.get("text", "").strip():
                    await self._ev("texto", texto=_corta(c["text"], 20000))
                elif ct == "thinking" and (c.get("thinking") or "").strip():
                    await self._ev("pensamento", texto=_corta(c["thinking"], 8000))
                elif ct == "tool_use":
                    await self._tool_use(c, projeto)
        elif tp == "user":
            conteudo = (ev.get("message") or {}).get("content")
            if isinstance(conteudo, list):
                for c in conteudo:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        await self._tool_result(c)
        elif tp == "result":
            ctx["teve_fim"] = True
            custo = float(ev.get("total_cost_usd") or ev.get("cost_usd") or 0.0)
            self.custo_total += custo
            self._salvar()
            await self._ev("fim", texto=_corta(str(ev.get("result") or ""), 20000), custo=round(custo, 6),
                           dur_s=round((ev.get("duration_ms") or 0) / 1000, 1), turnos=ev.get("num_turns") or 0)
            if ev.get("is_error") or (ev.get("subtype") or "success") != "success":
                await self._ev("erro", texto=f"execução terminou com erro ({ev.get('subtype') or 'erro'})")

    def _resumo(self, nome, inp, projeto):
        if not isinstance(inp, dict):
            return ""
        if nome == "Bash":
            return _corta(inp.get("command", ""), 160)
        fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
        if fp:
            return self._rel_de(fp, projeto) or fp
        for k in ("pattern", "url", "query", "description", "prompt", "skill"):
            if inp.get(k):
                return _corta(str(inp[k]), 160)
        for v in inp.values():
            if isinstance(v, str) and v:
                return _corta(v, 160)
        return ""

    async def _tool_use(self, c, projeto):
        nome = c.get("name") or "?"
        inp = c.get("input") or {}
        tid = c.get("id") or ""
        self._pend[tid] = {"nome": nome, "input": inp}
        try:
            args = json.dumps(inp, ensure_ascii=False)
        except (TypeError, ValueError):
            args = str(inp)
        await self._ev("ferramenta", nome=nome, resumo=self._resumo(nome, inp, projeto), args=_corta(args, 400), tool_id=tid)
        if nome in ("Edit", "MultiEdit", "Write") and isinstance(inp, dict):
            rel = self._rel_de(inp.get("file_path"), projeto)
            if not rel or _proibido(rel):
                return
            alvo = os.path.join(projeto, rel)
            chave = (projeto, rel)
            atual = _ler_texto(alvo)
            if chave not in self._antes and atual is not None:
                self._antes[chave] = atual                  # cópia "antes" da 1ª edição desta sessão
            if nome == "Write":
                d = _udiff(atual or "", str(inp.get("content") or ""), rel)
            elif nome == "Edit":
                d = _udiff(str(inp.get("old_string") or ""), str(inp.get("new_string") or ""), rel)
            else:
                d = "".join(_udiff(str(e.get("old_string") or ""), str(e.get("new_string") or ""), rel)
                            for e in inp.get("edits") or [] if isinstance(e, dict))
            self._alt(projeto).add(rel)
            await self._ev("edicao", arquivo=rel, diff=_corta(d, 40000))

    async def _tool_result(self, c):
        tid = c.get("tool_use_id") or ""
        cont = c.get("content")
        if isinstance(cont, list):
            texto = "\n".join(str(x.get("text", "")) for x in cont if isinstance(x, dict) and x.get("type") == "text")
        else:
            texto = str(cont or "")
        erro = bool(c.get("is_error"))
        pend = self._pend.pop(tid, None)
        if pend and pend["nome"] == "Bash":
            cmd = (pend["input"] or {}).get("command", "") if isinstance(pend["input"], dict) else ""
            await self._ev("terminal", comando=_corta(cmd, 2000), saida=_corta(texto, 12000), erro=erro, tool_id=tid)
        else:
            await self._ev("resultado", tool_id=tid, texto=_corta(texto, 6000), erro=erro)


# ======================= autoteste OFFLINE =======================
if __name__ == "__main__":
    import shutil, stat, sys, tempfile

    falhas = []

    def ok(cond, msg):
        print(("  OK  " if cond else "  FALHA ") + msg)
        if not cond:
            falhas.append(msg)

    async def main():
        tmp = tempfile.mkdtemp(prefix="dev_ide_teste_")
        try:
            proj = os.path.join(tmp, "proj")
            os.makedirs(os.path.join(proj, "src", "sub", "fundo", "maisfundo"))
            os.makedirs(os.path.join(proj, "node_modules", "x"))
            os.makedirs(os.path.join(proj, "Secrets"))
            os.makedirs(os.path.join(proj, ".git"))
            with open(os.path.join(proj, "src", "app.py"), "w") as f:
                f.write("def soma(a, b):\n    return a + b\n")
            with open(os.path.join(proj, "src", "sub", "fundo", "maisfundo", "z.txt"), "w") as f:
                f.write("z\n")
            with open(os.path.join(proj, "README.md"), "w") as f:
                f.write("# teste\napi_key = 'abcd1234efgh'\n")
            with open(os.path.join(proj, ".env"), "w") as f:
                f.write("TOKEN=x\n")
            with open(os.path.join(proj, "Secrets", "s.txt"), "w") as f:
                f.write("segredo\n")
            with open(os.path.join(proj, "app.py.v1bak"), "w") as f:
                f.write("velho\n")
            with open(os.path.join(proj, "img.bin.dat"), "wb") as f:
                f.write(b"\x00\x01\x02binario")
            os.rmdir(os.path.join(proj, ".git"))                       # sem git: diff usa a cópia "antes"

            eventos = []

            async def publicar(m):
                eventos.append(m)

            respostas = []

            async def responder(m):
                respostas.append(m)

            est = os.path.join(tmp, "dev_ide.json")
            ide = IDE(publicar, estado_path=est, projeto_padrao=proj, sistemas=os.path.join(tmp, "nao_existe"))

            print("== árvore")
            arv = ide.arvore("")
            for it in arv["itens"]:
                print("   " + "  " * it["nivel"] + it["nome"] + ("/" if it["dir"] else ""))
            nomes = [it["rel"] for it in arv["itens"]]
            ok("src" in nomes and "README.md" in nomes, "árvore lista src e README.md")
            ok(not any(n.startswith(("node_modules", "Secrets")) or n in (".env", "app.py.v1bak") for n in nomes),
               "árvore ignora node_modules, Secrets, .env, *bak")
            ok(nomes.index("src") < nomes.index("README.md"), "diretórios antes de arquivos")
            ok(not any("maisfundo" in n for n in nomes), "profundidade máx 3")

            print("== ler")
            r = ide.ler("src/app.py")
            ok(r["texto"].startswith("def soma") and r["linhas"] == 2 and not r["truncado"], "ler src/app.py")
            r = ide.ler("README.md")
            ok("abcd1234efgh" not in r["texto"], "ler mascara api_key: " + r["texto"].splitlines()[1])
            ok(ide.ler("img.bin.dat")["texto"] == "(arquivo binário)", "binário detectado")
            ok("erro" in ide.ler("../../etc/passwd"), "recusa .. fora do projeto")
            ok("erro" in ide.ler("Secrets/s.txt"), "recusa Secrets/")
            ok("erro" in ide.ler(".env"), "recusa .env")
            ok("erro" in ide.ler("/etc/passwd"), "recusa caminho absoluto fora")

            print("== parser stream-json (eventos falsos)")
            ctx = {"projeto": proj, "teve_fim": False}
            app = os.path.join(proj, "src", "app.py")
            falsos = [
                {"type": "system", "subtype": "init", "session_id": "11111111-2222-3333-4444-555555555555", "model": "claude-sonnet"},
                {"type": "assistant", "session_id": "11111111-2222-3333-4444-555555555555", "message": {"content": [
                    {"type": "thinking", "thinking": "Vou rodar os testes e corrigir a soma."},
                    {"type": "tool_use", "id": "toolu_A", "name": "Bash", "input": {"command": "pytest -q", "description": "testes"}},
                    {"type": "tool_use", "id": "toolu_B", "name": "Edit", "input": {"file_path": app, "old_string": "return a + b", "new_string": "return int(a) + int(b)"}},
                    {"type": "text", "text": "Corrigi a soma. password: hunter22"}]}},
                {"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "toolu_A", "content": "1 passed in 0.01s", "is_error": False},
                    {"type": "tool_result", "tool_use_id": "toolu_B", "content": [{"type": "text", "text": "The file has been updated."}]}]}},
                {"type": "result", "subtype": "success", "is_error": False, "result": "Pronto.", "total_cost_usd": 0.0123,
                 "duration_ms": 4567, "num_turns": 3, "session_id": "11111111-2222-3333-4444-555555555555"},
            ]
            for e in falsos:
                await ide.processar_linha(json.dumps(e).encode() + b"\n", ctx)
            # simula a edição aplicada pelo Claude
            with open(app, "w") as f:
                f.write("def soma(a, b):\n    return int(a) + int(b)\n")
            for e in eventos:
                print("   " + json.dumps(e, ensure_ascii=False))
            kinds = [e["kind"] for e in eventos]
            ok(kinds == ["inicio", "pensamento", "ferramenta", "ferramenta", "edicao", "texto", "terminal", "resultado", "fim"],
               "sequência de kinds: " + ",".join(kinds))
            ok(sum(1 for e in eventos if e.get("tool_id") == "toolu_A" and e["kind"] == "resultado") == 0, "Bash não duplica como resultado")
            term = next(e for e in eventos if e["kind"] == "terminal")
            ok(term["comando"] == "pytest -q" and "1 passed" in term["saida"], "terminal junta comando+saída")
            ed = next(e for e in eventos if e["kind"] == "edicao")
            ok(ed["arquivo"] == "src/app.py" and "+return int(a) + int(b)" in ed["diff"], "edicao com unified diff")
            ok("hunter22" not in next(e for e in eventos if e["kind"] == "texto")["texto"], "texto mascarado")
            ok(ide.sessoes.get(proj) == "11111111-2222-3333-4444-555555555555", "session_id guardado")
            ok(abs(ide.custo_total - 0.0123) < 1e-9, "custo_total acumulado")
            ok(ide.estado_dict()["alterados"] == ["src/app.py"], "alterados marcado")
            ok(any(it["rel"] == "src" and it["alterado"] for it in ide.arvore("")["itens"]), "árvore marca dir alterado")
            ok(stat.S_IMODE(os.stat(est).st_mode) == 0o600, "estado salvo com 0600")
            ok([e["id"] for e in eventos] == list(range(1, len(eventos) + 1)), "ids sequenciais")

            print("== diff (sem git -> cópia antes)")
            d = await ide.diff("src/app.py")
            print("   " + d["diff"].replace("\n", "\n   "))
            ok("-    return a + b" in d["diff"] and "+    return int(a) + int(b)" in d["diff"], "diff contra cópia antes")
            ok((await ide.diff("README.md"))["diff"] == "", "diff vazio sem edição")

            print("== tratar() com Claude falso (script local, sem chamar o claude de verdade)")
            fake = os.path.join(tmp, "claude_falso")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\n"
                        "echo '{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"sess-falsa-2\",\"model\":\"m\"}'\n"
                        "echo \"{\\\"type\\\":\\\"assistant\\\",\\\"message\\\":{\\\"content\\\":[{\\\"type\\\":\\\"text\\\",\\\"text\\\":\\\"args: $*\\\"}]}}\"\n"
                        "echo '{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"ok\",\"total_cost_usd\":0.001,\"duration_ms\":10,\"num_turns\":1}'\n")
            os.chmod(fake, 0o700)
            ide.cmd_claude = fake
            eventos.clear()
            await ide.tratar({"type": "ide", "op": "modelo", "modelo": "haiku"}, responder)
            await ide.tratar({"type": "ide", "op": "enviar", "texto": "oi"}, responder)
            await ide.tratar({"type": "ide", "op": "enviar", "texto": "de novo"}, responder)   # deve recusar (rodando)
            await ide.tarefa
            for e in eventos:
                print("   " + json.dumps(e, ensure_ascii=False))
            ks = [e["kind"] for e in eventos]
            ok("erro" in ks and any("já estou trabalhando" in e.get("texto", "") for e in eventos), "segunda execução recusada")
            txt = next(e for e in eventos if e["kind"] == "texto")["texto"]
            ok("--resume 11111111-2222-3333-4444-555555555555" in txt and "--model haiku" in txt and "bypassPermissions" in txt,
               "comando com --resume, --model e permission-mode")
            ok(ide.sessoes[proj] == "sess-falsa-2" and ks[-1] == "fim", "sessão atualizada e fim recebido")
            respostas.clear()
            await ide.tratar({"type": "ide", "op": "nova_sessao"}, responder)
            ok(respostas[-1]["sessao"] == "" and respostas[-1]["alterados"] == [], "nova_sessao esquece sessão e alterados")
            respostas.clear()
            await ide.tratar({"type": "ide", "op": "estado"}, responder)
            ok(respostas[-1]["type"] == "ide_estado" and respostas[-1]["modelo"] == "haiku", "estado responde")
            await ide.tratar({"type": "ide", "op": "abrir_projeto", "caminho": "/etc"}, responder)
            ok(ide.projeto == proj and eventos[-1]["kind"] == "erro", "abrir_projeto recusa caminho fora da lista")
            with open(est) as f:
                print("   estado persistido:", f.read().replace("\n", ""))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    asyncio.run(main())
    print("\nRESULTADO:", "PASSOU" if not falhas else f"{len(falhas)} FALHA(S)")
    sys.exit(1 if falhas else 0)
