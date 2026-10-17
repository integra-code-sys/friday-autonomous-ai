#!/usr/bin/env python3
"""prom — camada de operações do Prometheus (PC, celular, e-mail, WhatsApp, tarefas), com política de autonomia.

Uso (comando `prom`, o caminho oficial do Prometheus para agir no mundo):
  prom policy                              mostra a política de autonomia vigente
  prom task add "texto" [--quando ISO|diario@08:00|+30m] [--dir PASTA]
  prom task list|done ID|cancel ID
  prom phone status|battery|ring|notifs|ping "texto"|sms NUMERO "texto"|share ARQUIVO|url URL
  prom wa read                             conversas com notificação ativa no celular (WhatsApp/Telegram/SMS)
  prom wa reply NOTIF_ID "texto"           responde a uma notificação (precisa de aprovação, salvo regra permanente)
  prom mail list [--n 10] [--unread] | read UID | send --to X --subject Y --body Z | compose --to X --subject Y --body Z   (compose = mostra no espelho holográfico e pede aprovação)
  prom holo window|app NOME [--grande]      (projeta a janela REAL / um resumo do app no holograma da mão — NÃO abre nem foca o app)
  prom holo email|figure FORMA|chart TIPO --dados "a=1,b=2"|text|ui --json '{..}'|scene --json '{..}'|clear   [--grande] [--ttl S]   (palco holográfico do avatar)
  prom agenda add "titulo" --quando "amanhã 15h" [--tipo reuniao|consulta|tarefa|lembrete|prazo] [--dur 60] [--local X] [--com X] [--lembrar 15]
  prom agenda list [--dias 7] | today | done ID | rm ID | export
  prom projects list|info NOME|refresh        (índice dos sistemas em ~/Workspace/Projetos/Sistemas)
  prom remote add ALIAS ID [--senha-arquivo F] | list | status | connect ALIAS     (AnyDesk: servidor/PCs; depois use `pc` na janela)
  prom net | wifi status|list|saved|on|off|connect SSID | bt status|on|off|devices|scan|connect X|disconnect X|pair X
  prom zap status|launch|chats [--todas]|read NOME [--n 15]|reply NOME "texto"   (WhatsApp do ZapZap, via depurador local)
  prom pc info|apps [filtro]|browser [filtro]|hotkeys|refresh     (mapa do PC: hardware, apps, navegador, atalhos)
  prom apps find|launch NOME | prom win list|focus X|close X | prom browser open URL|bookmarks [filtro]
  prom sys vol [up|down|mute|N] | bright [N%] | media [play|pause|next|status] | power [perfil] | notify T [C] | clip [txt] | open URL
  prom skill list|find TERMO|show ID|add "nome" "passos" "gatilhos"|rm ID     (habilidades aprendidas: consulte ANTES de improvisar)
  prom approvals | approve ID | reject ID
  prom notify "texto"                      avisa o dono no celular (ping) — sempre permitido
Regra de ouro: tudo que sai para fora (e-mail, SMS, WhatsApp, push, apagar, instalar) passa por check(); o que a política
manda confirmar vira uma aprovação pendente (o Prometheus pergunta ao dono) em vez de ser executado."""
import json, os, re, subprocess, sys, time, imaplib, smtplib, email, ssl, fnmatch, uuid, threading, hashlib
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from email.message import EmailMessage
from email.header import decode_header

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MEM = os.path.join(ROOT, "memory")
POL_FILE = os.path.join(MEM, "politica.json")
AUD_FILE = os.path.join(MEM, "auditoria.jsonl")
TASK_FILE = os.path.join(MEM, "tarefas.json")
APPR_FILE = os.path.join(MEM, "aprovacoes.json")
ACC_FILE = os.path.join(MEM, "contas.json")
AGENDA_FILE = os.path.join(MEM, "agenda.json")
PROJ_FILE = os.path.join(MEM, "projetos.json")
REMOTE_FILE = os.path.join(MEM, "remotos.json")
SKILL_FILE = os.path.join(MEM, "habilidades.json")
MAP_FILE = os.path.join(MEM, "mapa_pc.json")

DEFAULT_POLICY = {
    # assistida: ações para fora pedem aprovação do dono | total: só o "proibido" é barrado (use com cuidado)
    "autonomia": "assistida",
    "auto": ["agenda.*", "projects.*", "holo.*", "wa.list", "wa.read_chat", "net.status", "wifi.status", "wifi.list", "wifi.on", "wifi.connect_known",
             "bt.status", "bt.list", "bt.scan", "bt.on", "bt.off", "bt.connect", "bt.disconnect",
             "remote.status", "remote.list", "phone.status", "phone.battery", "phone.ring", "phone.notifs", "phone.ping", "notify.me", "task.*",
             "mail.list", "mail.read", "wa.read", "approvals.*", "policy.show"],
    "confirmar": ["wifi.off", "wifi.connect_new", "bt.pair", "bt.remove", "remote.connect", "remote.input", "wa.send_chat", "mail.send", "sms.send", "wa.reply", "wa.send", "phone.share", "fs.delete", "git.push", "deploy", "install", "sudo.*", "self.*", "shell.escrever",
                  "money.*", "account.*"],
    "proibido": ["credencial.exfiltrar", "seguranca.desativar"],
    # regras permanentes: libera uma ação específica sem perguntar. Ex.:
    # {"acao": "wa.reply", "destino": "Fulano*", "ate": "2026-12-31", "obs": "responder o Fulano sobre horários"}
    "regras_permanentes": [],
    "silencio": ["23:00", "07:00"],        # janela em que o Prometheus não fala sozinho (avisos vão só pro celular/painel)
}


# ----------------------------------------------------------------- util
def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def audit(acao, destino="", resumo="", resultado="", quem="agente"):
    """trilha de auditoria (append-only). Nunca grava segredos: o chamador passa só um resumo."""
    os.makedirs(MEM, exist_ok=True)
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "acao": acao, "destino": destino, "resumo": resumo[:300],
           "resultado": str(resultado)[:200], "quem": quem}
    with open(AUD_FILE, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------- política
def policy():
    p = dict(DEFAULT_POLICY)
    p.update(_load(POL_FILE, {}))
    return p


def _match(patterns, acao):
    return any(fnmatch.fnmatch(acao, pat) for pat in patterns)


def check(acao, destino=""):
    """-> ("auto"|"confirmar"|"proibido", motivo)"""
    try:
        try:
            from daemon import parametros as _param
        except ImportError:
            import parametros as _param
        nivel_p = _param.nivel_autonomia(acao, destino)
        if nivel_p == "gated":
            return "confirmar", "parâmetro de segurança: ação de risco exige aprovação obrigatória do dono"
        elif nivel_p == "livre":
            return "auto", "parâmetro de segurança: ação livre autônoma"
    except Exception as _ep:
        pass
    p = policy()
    if _match(p["proibido"], acao):
        return "proibido", "ação proibida pela política"
    for r in p.get("regras_permanentes", []):
        if fnmatch.fnmatch(acao, r.get("acao", "")) and fnmatch.fnmatch((destino or "").lower(), (r.get("destino", "*") or "*").lower()):
            if not r.get("ate") or r["ate"] >= time.strftime("%Y-%m-%d"):
                return "auto", f"regra permanente: {r.get('obs', r.get('acao'))}"
    if _match(p["auto"], acao):
        return "auto", "ação livre"
    if _match(p["confirmar"], acao):
        if p.get("autonomia") == "total":
            return "auto", "autonomia total"
        return "confirmar", "ação externa: precisa de aprovação do dono"
    # desconhecida: tratada como externa por segurança
    return ("auto", "autonomia total") if p.get("autonomia") == "total" else ("confirmar", "ação não classificada")


# ----------------------------------------------------------------- aprovações
def approvals():
    return _load(APPR_FILE, {"itens": []})["itens"]


def _save_appr(items):
    _save(APPR_FILE, {"itens": items})


def request_approval(acao, destino, resumo, payload):
    items = approvals()
    aid = uuid.uuid4().hex[:6]
    items.append({"id": aid, "acao": acao, "destino": destino, "resumo": resumo, "payload": payload,
                  "estado": "pendente", "criado": time.time(), "anunciado": False})
    _save_appr(items)
    audit(acao, destino, resumo, "aguardando aprovação " + aid)
    if acao == "wa.send_chat":
        holo_show({
            "kind": "email",
            "para": f"WhatsApp · {destino}",
            "assunto": "Rascunho da Friday",
            "corpo": payload.get("texto", resumo),
            "contexto": payload.get("contexto") or [],
            "pedido": payload.get("pedido") or "",
            "status": "aguardando aprovação",
            "titulo": "WhatsApp — Nova Mensagem",
            "ttl": 300
        })
    elif acao == "mail.send":
        holo_show({
            "kind": "email",
            "para": str(destino),
            "assunto": payload.get("subject", "E-mail Pendente"),
            "corpo": payload.get("body", resumo),
            "status": "aguardando aprovação",
            "titulo": "Novo E-mail",
            "ttl": 300
        })
    return aid


def resolve(aid, aprovar=True, quem="dono"):
    items = approvals()
    it = next((i for i in items if i["id"] == aid and i["estado"] == "pendente"), None)
    if it is None:
        return False, "aprovação não encontrada ou já resolvida"
    if not aprovar:
        it["estado"] = "rejeitada"; _save_appr(items)
        audit(it["acao"], it["destino"], it["resumo"], "rejeitada", quem)
        holo_show(None, "clear")
        return True, "rejeitada"
    ok, msg = _execute(it["acao"], it["payload"])
    it["estado"] = "executada" if ok else "falhou"; it["resultado"] = msg[:200]
    _save_appr(items)
    audit(it["acao"], it["destino"], it["resumo"], f"aprovada→{'ok' if ok else 'falhou'}: {msg}", quem)
    if it["acao"] == "wa.send_chat":
        holo_show({
            "kind": "email",
            "para": f"WhatsApp · {it['destino']}",
            "assunto": "Mensagem " + ("Enviada" if ok else "Falhou"),
            "corpo": it["payload"].get("texto", ""),
            "status": "enviado" if ok else f"falhou: {msg[:40]}",
            "titulo": "WhatsApp — Mensagem",
            "ttl": 6
        })
    return ok, msg


def gated(acao, destino, resumo, payload):
    """executa se a política deixa; senão vira aprovação pendente."""
    nivel, motivo = check(acao, destino)
    if nivel == "proibido":
        audit(acao, destino, resumo, "BLOQUEADO: " + motivo)
        return False, "BLOQUEADO: " + motivo
    if nivel == "confirmar":
        aid = request_approval(acao, destino, resumo, payload)
        return False, f"PENDENTE de aprovação (id {aid}): {resumo}. O dono precisa autorizar; não tente enviar por outro meio."
    ok, msg = _execute(acao, payload)
    audit(acao, destino, resumo, ("ok: " if ok else "falhou: ") + msg)
    return ok, msg


# ----------------------------------------------------------------- celular (KDE Connect)
def _kc_device():
    out = subprocess.run(["kdeconnect-cli", "-l", "--id-name-only"], capture_output=True, text=True).stdout.strip().splitlines()
    return out[0].split()[0] if out else None


def _kc(*args):
    dev = _kc_device()
    if not dev:
        return False, "nenhum celular pareado (KDE Connect)"
    r = subprocess.run(["kdeconnect-cli", "-d", dev, *args], capture_output=True, text=True, timeout=20)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def phone_reachable():
    dev = _kc_device()
    if not dev:
        return False
    r = subprocess.run(["busctl", "--user", "get-property", "org.kde.kdeconnect", f"/modules/kdeconnect/devices/{dev}",
                        "org.kde.kdeconnect.device", "isReachable"], capture_output=True, text=True)
    return r.stdout.strip().endswith("true")


def _bus(path, iface, member, *args, sig=None):
    cmd = ["busctl", "--user", "--json=short", "call", "org.kde.kdeconnect", path, iface, member]
    if sig is not None:
        cmd += [sig, *map(str, args)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.returncode == 0, r.stdout.strip() or r.stderr.strip()


def phone_notifs():
    """notificações ativas no celular: [{id, app, titulo, texto, responder(bool)}]"""
    dev = _kc_device()
    if not dev or not phone_reachable():
        return []
    base = f"/modules/kdeconnect/devices/{dev}/notifications"
    ok, out = _bus(base, "org.kde.kdeconnect.device.notifications", "activeNotifications")
    res = []
    if not ok:
        return res
    try:
        ids = json.loads(out)["data"][0]
    except Exception:
        return res
    for nid in ids:
        path = f"{base}/{nid}"
        item = {"id": nid}
        for prop, key in (("appName", "app"), ("title", "titulo"), ("text", "texto"), ("replyId", "reply_id"), ("dismissable", "dispensavel")):
            r = subprocess.run(["busctl", "--user", "--json=short", "get-property", "org.kde.kdeconnect", path,
                                "org.kde.kdeconnect.device.notifications.notification", prop], capture_output=True, text=True)
            try:
                item[key] = json.loads(r.stdout)["data"]
            except Exception:
                item[key] = None
        item["responder"] = bool(item.get("reply_id"))
        res.append(item)
    return res


def _execute(acao, p):
    """executor central (só é chamado depois do portão de política)."""
    try:
        if acao == "notify.me" or acao == "phone.ping":
            return _kc("--ping-msg", p["texto"])
        if acao == "phone.ring":
            return _kc("--ring")
        if acao == "sms.send":
            return _kc("--send-sms", p["texto"], "--destination", p["numero"])
        if acao == "phone.share":
            return _kc("--share", p["arquivo"]) if p.get("arquivo") else _kc("--share-text", p.get("url") or p.get("texto", ""))
        if acao == "wa.reply":
            dev = _kc_device()
            if not dev:
                return False, "celular não pareado"
            ok, out = _bus(f"/modules/kdeconnect/devices/{dev}/notifications", "org.kde.kdeconnect.device.notifications",
                           "sendReply", p["reply_id"], p["texto"], sig="ss")
            return ok, out or "enviado"
        if acao == "mail.send":
            ok, msg = mail_send(p["to"], p["subject"], p["body"])
            holo_show({"kind": "email", "para": p["to"], "assunto": p["subject"], "corpo": p["body"], "titulo": "Novo e-mail",
                       "status": "enviado" if ok else "falhou ao enviar", "ttl": 25})
            return ok, msg
        if acao == "wa.send_chat":
            if os.environ.get("FRIDAY_ZAP_DRYRUN") == "1":       # teste: não envia nada, só registra
                audit("wa.send_chat.dryrun", p.get("nome", ""), str(p.get("texto", ""))[:200], "simulado")
                return True, "simulado (dry-run): " + str(p.get("nome"))
            import zap
            r = zap.send(p["nome"], p["texto"])
            return bool(r.get("ok")), ("enviado a " + str(r.get("conversa"))) if r.get("ok") else str(r.get("motivo"))
        if acao == "self.apply":
            r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "aprimorar.py"), "aplicar", p["id"]],
                               capture_output=True, text=True, timeout=120)
            try:
                d = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                d = {"ok": False, "erro": (r.stderr or r.stdout)[-300:]}
            return bool(d.get("ok")), ("aplicada: " + ", ".join(d.get("arquivos", []))) if d.get("ok") else str(d.get("erro"))
        if acao == "sudo.run":
            ft = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ftools.py")
            r = subprocess.run([sys.executable, ft, "sudo", p["comando"]], capture_output=True, text=True, timeout=960)
            try:
                d = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                d = {"ok": False, "saida": (r.stderr or r.stdout)[-300:]}
            holo_show({"kind": "email", "para": "root (sudo)", "assunto": "resultado", "corpo": "$ " + p["comando"] + "\n" + str(d.get("saida") or d.get("erro", ""))[-600:],
                       "status": "concluído" if d.get("ok") else "falhou", "titulo": "Comando sudo", "ttl": 40})
            return bool(d.get("ok")), str(d.get("saida") or d.get("erro", ""))[-300:]
        if acao == "shell.escrever":                  # F7: terminal seguro, já aprovado pelo dono (reclassifica antes de rodar)
            import shell_seguro as _ss
            d = _ss.executar(p["comando"], aprovado=True, exibir=p.get("exibir"))   # roda só o que o dono viu
            holo_show({"kind": "email", "para": "terminal", "assunto": "resultado", "corpo": "$ " + d.get("exibir", p["comando"]) + "\n" +
                       str(d.get("saida") or d.get("erro", ""))[-600:], "status": "concluído" if d.get("ok") else "falhou", "titulo": "Terminal", "ttl": 40})
            return bool(d.get("ok")), str(d.get("saida") or d.get("erro", ""))[-300:] or ("ok" if d.get("ok") else "falhou")
        if acao == "remote.connect":
            return remote_connect(p["alias"])
        if acao == "wifi.off":
            r = subprocess.run(["nmcli", "radio", "wifi", "off"], capture_output=True, text=True); return r.returncode == 0, r.stdout + r.stderr
        if acao == "wifi.connect_new":
            cmd = ["nmcli", "device", "wifi", "connect", p["ssid"]] + (["password", p["senha"]] if p.get("senha") else [])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60); return r.returncode == 0, (r.stdout + r.stderr).strip()[:200]
        return False, f"executor desconhecido: {acao}"
    except Exception as e:
        return False, f"erro: {e!r}"


# ----------------------------------------------------------------- e-mail (IMAP/SMTP; credenciais num arquivo que o dono indicar)
def _acc():
    """memory/contas.json: {"email": {"user": "...", "imap": "imap.gmail.com", "smtp": "smtp.gmail.com",
                                      "senha_arquivo": "/caminho/arquivo-com-a-senha-de-app", "nome": "Fulano"}}"""
    a = _load(ACC_FILE, {}).get("email")
    if not a:
        raise RuntimeError("e-mail não configurado: crie memory/contas.json (ver docs) com usuário e o ARQUIVO da senha de app")
    with open(os.path.expanduser(a["senha_arquivo"])) as f:
        a = dict(a); a["senha"] = f.read().strip()
    return a


def _dec(v):
    if v is None:
        return ""
    return "".join((t.decode(c or "utf-8", "replace") if isinstance(t, bytes) else t) for t, c in decode_header(v))


def mail_list(n=10, unread=False):
    a = _acc()
    M = imaplib.IMAP4_SSL(a.get("imap", "imap.gmail.com"))
    M.login(a["user"], a["senha"]); M.select("INBOX", readonly=True)
    typ, data = M.search(None, "UNSEEN" if unread else "ALL")
    ids = data[0].split()[-n:]
    out = []
    for i in reversed(ids):
        typ, d = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        m = email.message_from_bytes(d[0][1])
        out.append({"uid": i.decode(), "de": _dec(m["From"]), "assunto": _dec(m["Subject"]), "data": m["Date"]})
    M.logout()
    return out


def mail_read(uid, limite=4000):
    a = _acc()
    M = imaplib.IMAP4_SSL(a.get("imap", "imap.gmail.com"))
    M.login(a["user"], a["senha"]); M.select("INBOX", readonly=True)
    typ, d = M.fetch(str(uid).encode(), "(BODY.PEEK[])")
    m = email.message_from_bytes(d[0][1])
    body = ""
    for part in (m.walk() if m.is_multipart() else [m]):
        if part.get_content_type() == "text/plain":
            body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"); break
    M.logout()
    return {"de": _dec(m["From"]), "assunto": _dec(m["Subject"]), "corpo": body[:limite]}


def mail_send(to, subject, body):
    a = _acc()
    msg = EmailMessage()
    msg["From"] = f"{a.get('nome', '')} <{a['user']}>".strip()
    msg["To"] = to; msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(a.get("smtp", "smtp.gmail.com"), 465, context=ssl.create_default_context()) as s:
        s.login(a["user"], a["senha"]); s.send_message(msg)
    return True, f"e-mail enviado para {to}"


# ----------------------------------------------------------------- tarefas autônomas
def tasks():
    return _load(TASK_FILE, {"itens": []})["itens"]


def _save_tasks(items):
    _save(TASK_FILE, {"itens": items})


def _parse_when(q):
    """'' (agora) | +30m | +2h | ISO 'YYYY-MM-DD HH:MM' | diario@08:00 -> (próxima execução epoch, recorrente|None)"""
    now = time.time()
    if not q:
        return now, None
    m = re.fullmatch(r"\+(\d+)([mhd])", q.strip())
    if m:
        return now + int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)], None
    m = re.fullmatch(r"diario@(\d{1,2}):(\d{2})", q.strip())
    if m:
        t = time.localtime(now)
        nxt = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, int(m.group(1)), int(m.group(2)), 0, 0, 0, -1))
        if nxt <= now:
            nxt += 86400
        return nxt, q.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(q.strip(), fmt)), None
        except ValueError:
            pass
    return now, None


def task_add(texto, quando="", pasta=None):
    items = tasks()
    t, rec = _parse_when(quando)
    tid = uuid.uuid4().hex[:6]
    items.append({"id": tid, "texto": texto, "quando": t, "recorrente": rec, "pasta": pasta, "estado": "pendente",
                  "criada": time.time(), "resultado": ""})
    _save_tasks(items)
    audit("task.add", "", texto, tid)
    return tid


def task_set(tid, **kw):
    items = tasks()
    for it in items:
        if it["id"] == tid:
            it.update(kw)
    _save_tasks(items)


def task_next_due(now=None):
    now = now or time.time()
    due = [i for i in tasks() if i["estado"] == "pendente" and i["quando"] <= now]
    return sorted(due, key=lambda i: i["quando"])[0] if due else None


def task_finish(tid, resultado, ok=True):
    items = tasks()
    for it in items:
        if it["id"] == tid:
            if it.get("recorrente") and ok:                      # recorrente: reagenda
                it["quando"], _ = _parse_when(it["recorrente"]); it["estado"] = "pendente"
            else:
                it["estado"] = "feita" if ok else "falhou"
            it["resultado"] = resultado[:600]; it["ultima"] = time.time()
    _save_tasks(items)



# ----------------------------------------------------------------- agenda própria
TIPOS = ("reuniao", "compromisso", "tarefa", "lembrete", "prazo", "aniversario", "consulta")
_DIAS = {"segunda": 0, "terça": 1, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sábado": 5, "sabado": 5, "domingo": 6}


def parse_quando(q, ref=None):
    """aceita ISO 'YYYY-MM-DD HH:MM' ou PT-BR: 'hoje 15h', 'amanhã 9:30', 'sexta 14h', '20/10 8h', '+2h', 'daqui a 30 min'. -> epoch|None"""
    if q is None:
        return None
    if isinstance(q, (int, float)):
        return float(q)
    q = str(q).strip().lower()
    now = ref or time.time()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            t = time.strptime(q, fmt)
            return time.mktime(t) if "H" in fmt else time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 9, 0, 0, 0, 0, -1))
        except ValueError:
            pass
    q = re.sub(r"\bmeia hora\b", "30 min", q)
    m = re.fullmatch(r"\+(\d+)\s*([mhd])", q) or re.search(r"daqui a (\d+)\s*(min|h|hora|horas|dia|dias)", q)
    if m:
        u = m.group(2)[0]
        return now + int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[u]
    lt = time.localtime(now)
    base = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    day = None
    if re.search(r"pr[óo]xima semana|semana que vem", q):
        day = base + ((7 - lt.tm_wday) % 7 or 7) * 86400              # segunda que vem
    elif "depois de amanh" in q:
        day = base + 2 * 86400
    elif "amanh" in q:
        day = base + 86400
    elif "hoje" in q:
        day = base
    else:
        for nome, wd in _DIAS.items():
            if nome in q:
                delta = (wd - lt.tm_wday) % 7 or 7
                day = base + delta * 86400
                break
        md = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", q)
        dn = re.search(r"\bdia (\d{1,2})\b", q)
        if dn and not md and day is None:                               # "dia 20": este mês, ou o próximo se já passou
            y, mo = lt.tm_year, lt.tm_mon
            if int(dn.group(1)) < lt.tm_mday:
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
            try:
                day = time.mktime((y, mo, int(dn.group(1)), 0, 0, 0, 0, 0, -1))
            except Exception:
                return None
        if md and day is None:
            y = int(md.group(3)) if md.group(3) else lt.tm_year
            y = y + 2000 if y < 100 else y
            try:
                day = time.mktime((y, int(md.group(2)), int(md.group(1)), 0, 0, 0, 0, 0, -1))
            except Exception:
                return None
    hm = (re.search(r"\b(\d{1,2})\s*(?:h|:|horas?\b)\s*(\d{2})?", q) or re.search(r"\b(?:[àa]s?|ao?)\s+(\d{1,2})(?:\s*e\s*(\d{1,2}))?\b(?!/)", q)
          or re.search(r"\b(\d{1,2})(?:\s*e\s*(\d{1,2}))?\s+da (?:manh|tarde|noite)", q))
    h, mi = (int(hm.group(1)), int(hm.group(2) or 0)) if hm else (9, 0)
    if hm and re.search(r"\be meia\b", q):
        mi = 30
    if hm and h < 12 and re.search(r"da tarde|da noite", q):
        h += 12
    if re.search(r"meio[- ]dia", q):
        h, mi, hm = 12, 30 if "meia" in q.split("dia", 1)[-1] else 0, True
    elif re.search(r"meia[- ]noite", q):
        h, mi, hm = 0, 0, True
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    if day is None:
        if not hm:
            return None
        day = base
        if day + h * 3600 + mi * 60 < now:           # só "15h" e já passou hoje -> amanhã
            day += 86400
    return day + h * 3600 + mi * 60


def agenda_all():
    return _load(AGENDA_FILE, {"itens": []})["itens"]


def _save_agenda(items):
    """grava e carimba "mod" em todo item que mudou (a sincronização com o celular decide por ele quem é mais novo)."""
    antes = {i.get("id"): json.dumps({k: v for k, v in i.items() if k != "mod"}, sort_keys=True, ensure_ascii=False) for i in agenda_all()}
    agora = time.time()
    for i in items:
        if antes.get(i.get("id")) != json.dumps({k: v for k, v in i.items() if k != "mod"}, sort_keys=True, ensure_ascii=False):
            i["mod"] = agora
    _save(AGENDA_FILE, {"itens": items})
    try:
        import sync_mesh
        sync_mesh.notificar_mudanca("agenda")
    except Exception:
        pass


def agenda_add(titulo, quando, tipo="compromisso", dur=60, local="", participantes="", notas="", origem="manual", lembrar=None, repete="", prioridade=2):
    ini = parse_quando(quando)
    if ini is None:
        return None, "não entendi a data/hora"
    titulo = titulo.strip()[:120]
    tipo = tipo if tipo in TIPOS else "compromisso"
    items = agenda_all()
    for it in items:                                  # evita duplicata (mesmo título e horário ±30 min)
        if it.get("removido"):
            continue
        import difflib, unicodedata
        norm = lambda x: "".join(c for c in unicodedata.normalize("NFD", x.lower()) if unicodedata.category(c) != "Mn")
        mesmo = difflib.SequenceMatcher(None, norm(it["titulo"]), norm(titulo)).ratio() >= 0.7
        if (mesmo and abs(it["inicio"] - ini) < 3600) or (it["titulo"].lower() == titulo.lower() and abs(it["inicio"] - ini) < 1800):
            return it["id"], "já estava na agenda"
    if lembrar is None:
        lembrar = 15 if tipo in ("reuniao", "consulta", "compromisso") else 0
    aid = uuid.uuid4().hex[:6]
    items.append({"id": aid, "titulo": titulo, "tipo": tipo, "inicio": ini, "fim": ini + int(dur) * 60, "local": local[:80],
                  "participantes": participantes[:120], "notas": notas[:300], "origem": origem, "criado": time.time(),
                  "lembrar_min": int(lembrar), "avisado": False, "feito": False, "prioridade": _prio(prioridade), "fonte": "pc",
                  **({"repete": repete} if repete in REPETE else {})})
    _save_agenda(items)
    audit("agenda.add", tipo, f"{titulo} @ {time.strftime('%Y-%m-%d %H:%M', time.localtime(ini))}", origem)
    return aid, "ok"


REPETE = {"diario": 1, "semanal": 7, "dias_uteis": 1, "mensal": 0, "anual": 0}


def _proxima(i, now):
    """avança um item recorrente até a próxima ocorrência futura."""
    rep, ini = i.get("repete"), i["inicio"]
    while ini + (i["fim"] - i["inicio"]) < now:
        lt = time.localtime(ini)
        if rep in ("mensal", "anual"):
            y, mo = (lt.tm_year + 1, lt.tm_mon) if rep == "anual" else (lt.tm_year + (lt.tm_mon == 12), lt.tm_mon % 12 + 1)
            ini = time.mktime((y, mo, lt.tm_mday, lt.tm_hour, lt.tm_min, 0, 0, 0, -1))
        else:
            ini = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + REPETE[rep], lt.tm_hour, lt.tm_min, 0, 0, 0, -1))
            while rep == "dias_uteis" and time.localtime(ini).tm_wday >= 5:
                ini = time.mktime((*time.localtime(ini)[:2], time.localtime(ini).tm_mday + 1, lt.tm_hour, lt.tm_min, 0, 0, 0, -1))
    return ini


def _rolar_recorrentes():
    items, mudou, now = agenda_all(), False, time.time()
    for i in items:
        if i.get("repete") in REPETE and not i.get("removido") and i["inicio"] + (i["fim"] - i["inicio"]) < now:
            dur = i["fim"] - i["inicio"]
            i["inicio"] = _proxima(i, now); i["fim"] = i["inicio"] + dur; i["avisado"] = False; i["feito"] = False; mudou = True
    if mudou:
        _save_agenda(items)


def agenda_buscar(texto, dias=60):
    """item futuro cujo título mais se parece com 'texto' (para remover/remarcar por voz)."""
    import difflib, unicodedata
    norm = lambda x: "".join(c for c in unicodedata.normalize("NFD", x.lower()) if unicodedata.category(c) != "Mn")
    alvo = norm(texto)
    melhor, nota = None, 0.0
    for i in agenda_list(dias, desde=time.time() - 86400):
        t = norm(i["titulo"])
        r = 1.0 if alvo and (alvo in t or t in alvo) else difflib.SequenceMatcher(None, alvo, t).ratio()
        if r > nota:
            melhor, nota = i, r
    return melhor if nota >= 0.55 else None


def agenda_conflitos(ini, fim, ignorar=None):
    return [i for i in agenda_list(2, desde=ini - 86400) if i["id"] != ignorar and i["inicio"] < fim and ini < i["fim"]]


def agenda_remarcar(aid, quando):
    ini = parse_quando(quando)
    if ini is None:
        return False
    items = agenda_all()
    for i in items:
        if i["id"] == aid:
            dur = i["fim"] - i["inicio"]; i.update(inicio=ini, fim=ini + dur, avisado=False)
    _save_agenda(items)
    audit("agenda.move", aid, time.strftime("%Y-%m-%d %H:%M", time.localtime(ini)), "voz")
    return True


def agenda_list(dias=7, desde=None, incluir_feitos=False):
    _rolar_recorrentes()
    desde = desde if desde is not None else time.time() - 3600
    ate = desde + dias * 86400 + 3600
    return sorted((i for i in agenda_all() if not i.get("removido") and (incluir_feitos or not i.get("feito"))
                   and desde <= i["inicio"] <= ate), key=lambda i: i["inicio"])


def agenda_due_reminders(now=None):
    """itens cujo lembrete venceu e ainda não foi avisado."""
    now = now or time.time()
    out = []
    for i in agenda_all():
        if i.get("removido") or i.get("feito") or i.get("avisado"):
            continue
        t0 = i["inicio"] - i.get("lembrar_min", 0) * 60
        if t0 <= now <= i["inicio"] + 600:
            out.append(i)
    return out


def agenda_mark(aid, **kw):
    items = agenda_all()
    for i in items:
        if i["id"] == aid:
            i.update(kw)
    _save_agenda(items)


def agenda_fmt(i):
    t = time.strftime("%a %d/%m %H:%M", time.localtime(i["inicio"]))
    extra = " · " + i["local"] if i.get("local") else ""
    return f"[{i['id']}] {t} — {i['titulo']} ({i['tipo']}{extra})"


def agenda_ics():
    def d(t): return time.strftime("%Y%m%dT%H%M%S", time.localtime(t))
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Prometheus//Agenda//PT"]
    for i in agenda_list(3650, desde=0):
        L += ["BEGIN:VEVENT", f"UID:{i['id']}@prometheus", f"DTSTART:{d(i['inicio'])}", f"DTEND:{d(i['fim'])}",
              "SUMMARY:" + i["titulo"].replace("\n", " "), "LOCATION:" + i.get("local", ""), "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\n".join(L)


def agenda_limpar():
    """remove todos os itens ativos da agenda."""
    items = agenda_all()
    count = 0
    for i in items:
        if not i.get("removido"):
            i["removido"] = True
            count += 1
    _save_agenda(items)
    try:
        open(os.path.join(MEM, "agenda.ics"), "w").write(agenda_ics())
    except Exception:
        pass
    audit("agenda.clear", "todos", f"{count} itens removidos", "ok")
    return count


def agenda_remover(termo_ou_id):
    """remove um item da agenda por ID ou por busca aproximada no título."""
    if not termo_ou_id:
        return False, "Nenhum compromisso especificado."
    termo = str(termo_ou_id).strip()
    items = agenda_all()
    for i in items:
        if not i.get("removido") and i["id"].lower() == termo.lower():
            i["removido"] = True
            _save_agenda(items)
            try:
                open(os.path.join(MEM, "agenda.ics"), "w").write(agenda_ics())
            except Exception:
                pass
            audit("agenda.remove", i["id"], i["titulo"], "ok")
            return True, i["titulo"]
    it = agenda_buscar(termo)
    if it:
        for i in items:
            if i["id"] == it["id"]:
                i["removido"] = True
                _save_agenda(items)
                try:
                    open(os.path.join(MEM, "agenda.ics"), "w").write(agenda_ics())
                except Exception:
                    pass
                audit("agenda.remove", i["id"], i["titulo"], "ok")
                return True, i["titulo"]
    return False, f"Compromisso '{termo}' não encontrado."


def agenda_formatar_painel(dias=14):
    """prepara lista rica e estruturada de compromissos para a tela holográfica TelasHolo.qml."""
    now = time.time()
    itens = agenda_list(dias, desde=now - 1800)
    hoje_lt = time.localtime(now)
    hoje_dia = (hoje_lt.tm_year, hoje_lt.tm_mon, hoje_lt.tm_mday)
    amanha_ts = now + 86400
    am_lt = time.localtime(amanha_ts)
    amanha_dia = (am_lt.tm_year, am_lt.tm_mon, am_lt.tm_mday)
    dias_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

    cores_tipo = {
        "reuniao": "#3fd4ff",      # Ciano
        "compromisso": "#ff8a1f",  # Laranja Stark
        "tarefa": "#ffd27f",       # Dourado
        "lembrete": "#4ade80",     # Esmeralda
        "consulta": "#c084fc",     # Púrpura
        "prazo": "#f87171"         # Coral
    }

    out = []
    for idx, it in enumerate(itens[:12]):
        lt = time.localtime(it["inicio"])
        it_dia = (lt.tm_year, lt.tm_mon, lt.tm_mday)
        hora_str = time.strftime("%H:%M", lt)
        if it_dia == hoje_dia:
            dia_str = "HOJE"
            quando_fmt = f"Hoje às {hora_str}"
        elif it_dia == amanha_dia:
            dia_str = "AMANHÃ"
            quando_fmt = f"Amanhã às {hora_str}"
        else:
            w_str = dias_semana[lt.tm_wday]
            dia_str = f"{w_str} {lt.tm_mday:02d}/{lt.tm_mon:02d}"
            quando_fmt = f"{w_str}, {lt.tm_mday:02d}/{lt.tm_mon:02d} às {hora_str}"

        tipo = str(it.get("tipo", "compromisso")).lower()
        out.append({
            "id": it["id"],
            "titulo": it["titulo"],
            "dia": dia_str,
            "hora": hora_str,
            "quando": quando_fmt,
            "tipo": tipo.upper(),
            "local": str(it.get("local") or ""),
            "cor": cores_tipo.get(tipo, "#8fe9ff"),
            "proximo": idx == 0,
            "prioridade": it.get("prioridade", 2),
            "fonte": it.get("fonte", "pc"),
            "feito": bool(it.get("feito"))
        })
    return out



# ----------------------------------------------------------------- prioridades, nível do dia e sincronização com o celular
PRIO_NOME = {1: "alta", 2: "normal", 3: "baixa"}
_PRIO_PESO = {1: 3.0, 2: 2.0, 3: 1.0}
_AG_LOCK = threading.RLock()


def _prio(p):
    """aceita 1/2/3 ou 'alta|urgente|importante' / 'normal|media' / 'baixa' -> 1..3"""
    t = str(p).strip().lower()
    if t in ("1", "alta", "urgente", "importante", "maxima", "máxima"):
        return 1
    if t in ("3", "baixa", "minima", "mínima", "opcional"):
        return 3
    return 2


def agenda_prioridade(aid, p):
    items = agenda_all()
    for i in items:
        if i["id"] == aid:
            i["prioridade"] = _prio(p)
    _save_agenda(items)
    audit("agenda.prio", aid, PRIO_NOME[_prio(p)], "voz")


def _dia(ts):
    lt = time.localtime(ts)
    ini = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return ini, ini + 86400


def agenda_nivel(ts=None):
    """carga do dia: pontos = soma(peso da prioridade x horas, mínimo 0,5 h) -> leve | moderado | intenso | crítico.
    Também: foco (3 mais importantes ainda abertos), concluídos, conflitos e minutos livres entre 8h e 22h."""
    ini, fim = _dia(ts or time.time())
    _rolar_recorrentes()
    dia = sorted((i for i in agenda_all() if not i.get("removido") and ini <= i["inicio"] < fim), key=lambda i: i["inicio"])
    abertos = [i for i in dia if not i.get("feito")]
    pts = sum(_PRIO_PESO[i.get("prioridade", 2)] * max(0.5, (i["fim"] - i["inicio"]) / 3600) for i in abertos if not i.get("dia_todo"))
    pts += sum(_PRIO_PESO[i.get("prioridade", 2)] for i in abertos if i.get("dia_todo"))
    nivel = "livre" if not dia else "leve" if pts < 4 else "moderado" if pts < 9 else "intenso" if pts < 15 else "crítico"
    conflitos = sum(1 for a_, b_ in zip(dia, dia[1:]) if not a_.get("dia_todo") and not b_.get("dia_todo") and b_["inicio"] < a_["fim"])
    j0, j1 = max(ini + 8 * 3600, time.time() if ini <= time.time() < fim else ini), ini + 22 * 3600
    ocupado, cur = 0.0, j0
    for i in dia:
        if i.get("dia_todo") or i.get("feito"):
            continue
        a_, b_ = max(i["inicio"], cur), min(i["fim"], j1)
        if b_ > a_:
            ocupado += b_ - a_; cur = b_
    livre = max(0, int((max(0, j1 - j0) - ocupado) / 60))
    foco = sorted(abertos, key=lambda i: (i.get("prioridade", 2), i["inicio"]))[:3]
    return {"dia": time.strftime("%Y-%m-%d", time.localtime(ini)), "pontos": round(pts, 1), "nivel": nivel, "total": len(dia),
            "feitos": len(dia) - len(abertos), "conflitos": conflitos, "livre_min": livre,
            "foco": [{"id": i["id"], "titulo": i["titulo"], "prioridade": i.get("prioridade", 2),
                      "hora": "" if i.get("dia_todo") else time.strftime("%H:%M", time.localtime(i["inicio"]))} for i in foco]}


def agenda_nivel_fala(ts=None):
    n = agenda_nivel(ts)
    if not n["total"]:
        return "Seu dia está livre, chefe."
    partes = [f"Dia {n['nivel']}: {n['total']} compromisso{'s' if n['total'] > 1 else ''}"]
    if n["feitos"]:
        partes.append(f"{n['feitos']} já feito{'s' if n['feitos'] > 1 else ''}")
    if n["conflitos"]:
        partes.append(f"{n['conflitos']} conflito{'s' if n['conflitos'] > 1 else ''} de horário")
    f = [x for x in n["foco"] if x["prioridade"] == 1] or n["foco"][:1]
    fala = ", ".join(partes) + "."
    if f:
        fala += " Prioridade: " + " e ".join(x["titulo"] + (f" às {x['hora']}" if x["hora"] else "") for x in f[:2]) + "."
    h, m = divmod(n["livre_min"], 60)
    return fala + (f" Você tem {h}h{m:02d} livres." if n["livre_min"] >= 30 else "")


_SYNC_CAMPOS = ("titulo", "tipo", "inicio", "fim", "local", "notas", "prioridade", "feito", "removido", "lembrar_min", "dia_todo", "repete")


def agenda_sync(mudancas=None, google=None, dias=14):
    """sincroniza com o CELULAR. mudancas = itens editados/criados lá (vence o "mod" mais novo; mirrors do Google só aceitam
    prioridade/feito); google = eventos da agenda Google do celular nessa janela -> espelho "fonte: google" (some daqui se sumir de lá).
    Devolve a janela [-1 dia, +dias] inteira (com feitos) + o nível de cada dia."""
    with _AG_LOCK:
        items = agenda_all()
        por_id = {i["id"]: i for i in items}
        for m in mudancas or []:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            atual = por_id.get(m["id"])
            if atual is None:
                if m.get("removido") or not m.get("titulo") or not isinstance(m.get("inicio"), (int, float)):
                    continue
                novo = {"id": str(m["id"])[:16], "titulo": str(m["titulo"])[:120], "tipo": m.get("tipo") if m.get("tipo") in TIPOS else "compromisso",
                        "inicio": float(m["inicio"]), "fim": float(m.get("fim") or m["inicio"] + 3600), "local": str(m.get("local", ""))[:80],
                        "participantes": "", "notas": str(m.get("notas", ""))[:300], "origem": "celular", "fonte": "pc", "criado": time.time(),
                        "lembrar_min": int(m.get("lembrar_min", 15)), "avisado": False, "feito": bool(m.get("feito")),
                        "prioridade": _prio(m.get("prioridade", 2)), "dia_todo": bool(m.get("dia_todo"))}
                items.append(novo); por_id[novo["id"]] = novo
                audit("agenda.add", novo["tipo"], novo["titulo"], "celular")
                continue
            if float(m.get("mod", 0)) <= float(atual.get("mod", 0)):
                continue                                          # o PC tem versão mais nova
            campos = ("prioridade", "feito") if atual.get("fonte") == "google" else _SYNC_CAMPOS
            for k in campos:
                if k in m:
                    atual[k] = _prio(m[k]) if k == "prioridade" else m[k]
            if "inicio" in m and atual.get("fonte") != "google":
                atual["avisado"] = False
        if google is not None:                                   # espelho da agenda Google do celular
            vistos = set()
            for g in google:
                if not isinstance(g, dict) or not g.get("ext_id") or not isinstance(g.get("inicio"), (int, float)):
                    continue
                gid = "g" + hashlib.sha1(str(g["ext_id"]).encode()).hexdigest()[:9]
                vistos.add(gid)
                it = por_id.get(gid)
                dados = {"titulo": str(g.get("titulo") or "(sem título)")[:120], "inicio": float(g["inicio"]), "fim": float(g.get("fim") or g["inicio"] + 3600),
                         "local": str(g.get("local") or "")[:80], "dia_todo": bool(g.get("dia_todo")), "removido": False}
                if it is None:
                    it = {"id": gid, "tipo": "compromisso", "participantes": "", "notas": "", "origem": "google", "fonte": "google",
                          "criado": time.time(), "lembrar_min": 10, "avisado": False, "feito": False, "prioridade": 2, **dados}
                    items.append(it); por_id[gid] = it
                else:
                    if it["inicio"] != dados["inicio"]:
                        it["avisado"] = False
                    it.update(dados)
            j0, j1 = time.time() - 86400, time.time() + dias * 86400
            for i in items:
                if i.get("fonte") == "google" and i["id"] not in vistos and j0 <= i["inicio"] <= j1 and not i.get("removido"):
                    i["removido"] = True
        _save_agenda(items)
        return agenda_janela(dias)


def agenda_janela(dias=14):
    desde = _dia(time.time())[0] - 86400
    itens = agenda_list(dias + 1, desde=desde, incluir_feitos=True)
    hoje = _dia(time.time())[0]
    return {"itens": itens, "agora": time.time(),
            "niveis": {n["dia"]: n["nivel"] for n in (agenda_nivel(hoje + k * 86400 + 3600) for k in range(min(dias, 7)))}}


def agenda_painel_dados(dias=14):
    """dados da tela da agenda no PC: itens + nível/foco de hoje."""
    return {"itens": agenda_formatar_painel(dias), "nivel": agenda_nivel()}


# ----------------------------------------------------------------- projetos (índice gerado por tools/scan_projetos.py)
def projects():
    return _load(PROJ_FILE, {"projetos": []}).get("projetos", [])


def project_find(q):
    q = q.lower().strip()
    ps = projects()
    for p in ps:
        if p["nome"].lower() == q:
            return p
    hit = [p for p in ps if q in p["nome"].lower()]
    return hit[0] if len(hit) == 1 else (hit[0] if hit else None)


# ----------------------------------------------------------------- acesso remoto (AnyDesk)
def remotes():
    return _load(REMOTE_FILE, {"hosts": {}})["hosts"]


def _anydesk_cmd():
    import shutil
    if shutil.which("anydesk"):
        return ["anydesk"]
    if shutil.which("flatpak") and subprocess.run(["flatpak", "info", "com.anydesk.Anydesk"], capture_output=True).returncode == 0:
        return ["flatpak", "run", "com.anydesk.Anydesk"]
    return None


def remote_connect(alias):
    hosts = remotes()
    h = hosts.get(alias)
    if not h:
        return False, f"host '{alias}' não cadastrado (prom remote add {alias} ID --senha-arquivo ARQ)"
    cmd = _anydesk_cmd()
    if not cmd:
        return False, "AnyDesk não instalado"
    senha = None
    if h.get("senha_arquivo"):
        try:
            senha = open(os.path.expanduser(h["senha_arquivo"])).read().strip()
        except Exception as e:
            return False, f"não consegui ler o arquivo da senha: {e}"
    args = cmd + [h["id"]] + (["--with-password"] if senha else [])
    p = subprocess.Popen(args, stdin=subprocess.PIPE if senha else subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    if senha:                                     # a senha vai só pelo stdin do AnyDesk (nunca em argv/log)
        try:
            p.stdin.write(senha + "\n"); p.stdin.flush(); p.stdin.close()
        except Exception:
            pass
    return True, f"conectando a {alias} ({h['id']}); a janela do AnyDesk abre em instantes — opere com `pc shot`/`pc click`"


def net_status():
    out = subprocess.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], capture_output=True, text=True).stdout
    return out.strip()



# ----------------------------------------------------------------- rede: Wi-Fi e Bluetooth
def _run(cmd, timeout=40):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _bt(*args, timeout=20):
    return _run(["bluetoothctl", *args], timeout)


def _bt_devices(paired_only=False):
    ok, out = _bt("devices", "Paired") if paired_only else _bt("devices")
    res = []
    for l in out.splitlines():
        m = re.match(r"Device\s+([0-9A-F:]{17})\s+(.*)", l.strip(), re.I)
        if m:
            res.append((m.group(1), m.group(2)))
    return res


def _bt_find(q):
    q = q.strip().lower()
    for mac, nome in _bt_devices():
        if q == mac.lower() or q in nome.lower():
            return mac, nome
    return None, None


def net_cli(g, s, rest):
    def gate(acao, destino, resumo, payload=None):
        nivel, motivo = check(acao, destino)
        if nivel == "proibido":
            audit(acao, destino, resumo, "BLOQUEADO"); print("BLOQUEADO: " + motivo); return False
        if nivel == "confirmar":
            aid = request_approval(acao, destino, resumo, payload or {})
            print(f"PENDENTE de aprovação (id {aid}): {resumo}"); return False
        return True

    if g == "net":
        print(net_status()); return 0
    if g == "wifi":
        if s in ("status", ""):
            ok, out = _run(["nmcli", "-t", "-f", "WIFI", "general"])
            ok2, act = _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi"])
            ativo = [l for l in act.splitlines() if l.startswith("yes") or l.startswith("sim")]
            ok3, ip = _run(["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show"])
            print(json.dumps({"radio": out, "conectado": ativo[:1], "ip": [l for l in ip.splitlines() if "IP4" in l][:2]}, ensure_ascii=False, indent=1)); return 0
        if s == "list":
            ok, out = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"], 40)
            seen, rows = set(), []
            for l in out.splitlines():
                f = l.split(":")
                if len(f) >= 4 and f[1] and f[1] not in seen:
                    seen.add(f[1]); rows.append(f"{'*' if f[0] == '*' else ' '} {f[1]}  {f[2]}%  {f[3] or 'aberta'}")
            print("\n".join(rows[:20]) or "(nenhuma rede)"); return 0
        if s == "saved":
            ok, out = _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
            print("\n".join(l.split(":")[0] for l in out.splitlines() if "wireless" in l or "wifi" in l)); return 0
        if s == "on":
            ok, out = _run(["nmcli", "radio", "wifi", "on"]); audit("wifi.on", "", "ligar Wi-Fi", out); print("Wi-Fi ligado" if ok else out); return 0
        if s == "off":
            if gate("wifi.off", "", "desligar o Wi-Fi (o Prometheus pode perder a conexão)"):
                ok, out = _run(["nmcli", "radio", "wifi", "off"]); audit("wifi.off", "", "desligar Wi-Fi", out); print("Wi-Fi desligado")
            return 0
        if s == "connect" and rest:
            ssid = rest[0]
            ok, saved = _run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
            if ssid in saved.splitlines():
                ok, out = _run(["nmcli", "connection", "up", ssid], 60); audit("wifi.connect_known", ssid, "conectar a rede salva", out[:80]); print(out); return 0 if ok else 1
            senha = ""
            if "--senha-arquivo" in rest:
                try:
                    senha = open(os.path.expanduser(rest[rest.index("--senha-arquivo") + 1])).read().strip()
                except Exception as e:
                    print("ERRO lendo arquivo da senha:", e); return 1
            if gate("wifi.connect_new", ssid, f"conectar à rede nova '{ssid}'", {"ssid": ssid, "senha": senha}):
                ok, out = _execute("wifi.connect_new", {"ssid": ssid, "senha": senha}); print(out); return 0 if ok else 1
            return 0
    if g == "bt":
        if s in ("status", ""):
            ok, out = _bt("show")
            keep = [l.strip() for l in out.splitlines() if re.search(r"Name|Powered|Discoverable|Pairable", l)]
            conn = [n for mac, n in _bt_devices() if "Connected: yes" in _bt("info", mac)[1]]
            print(json.dumps({"controlador": keep, "conectados": conn}, ensure_ascii=False, indent=1)); return 0
        if s == "on":
            _run(["rfkill", "unblock", "bluetooth"]); ok, out = _bt("power", "on"); audit("bt.on", "", "ligar Bluetooth", out[:60]); print(out); return 0
        if s == "off":
            ok, out = _bt("power", "off"); audit("bt.off", "", "desligar Bluetooth", out[:60]); print(out); return 0
        if s in ("devices", "list"):
            pair = {m for m, _ in _bt_devices(True)}
            for mac, nome in _bt_devices():
                print(f"{'pareado ' if mac in pair else 'visto   '} {mac}  {nome}")
            return 0
        if s == "scan":
            secs = rest[0] if rest else "8"
            _bt("--timeout", secs, "scan", "on", timeout=int(secs) + 10)
            for mac, nome in _bt_devices():
                print(f"{mac}  {nome}")
            return 0
        if s in ("connect", "disconnect") and rest:
            mac, nome = _bt_find(rest[0])
            if not mac:
                print("dispositivo não encontrado (use `prom bt scan`)"); return 1
            ok, out = _bt(s, mac, timeout=30); audit("bt." + s, nome, f"{s} {nome}", out[:80]); print(out); return 0 if ok else 1
        if s == "pair" and rest:
            mac, nome = _bt_find(rest[0])
            if not mac:
                print("dispositivo não encontrado (use `prom bt scan`)"); return 1
            if gate("bt.pair", nome, f"parear com '{nome}' ({mac})", {"mac": mac}):
                ok, out = _bt("pair", mac, timeout=40); print(out)
            return 0
    print("uso: prom net | wifi status|list|saved|on|off|connect SSID [--senha-arquivo F] | bt status|on|off|devices|scan|connect X|disconnect X|pair X")
    return 1



# ----------------------------------------------------------------- habilidades (playbooks aprendidos)
def skills():
    return _load(SKILL_FILE, {"itens": []})["itens"]


def _save_skills(items):
    _save(SKILL_FILE, {"itens": items})


def skill_add(nome, passos, gatilhos="", origem="aprendida", nota=""):
    items = skills()
    nome = nome.strip()[:60]
    for it in items:
        if it["nome"].lower() == nome.lower():
            it.update(passos=passos.strip(), gatilhos=gatilhos or it.get("gatilhos", ""), nota=nota or it.get("nota", ""), atualizada=time.time())
            _save_skills(items); return it["id"], "atualizada"
    sid = uuid.uuid4().hex[:6]
    items.append({"id": sid, "nome": nome, "gatilhos": gatilhos[:160], "passos": passos.strip()[:2500], "origem": origem, "nota": nota[:200],
                  "criada": time.time(), "atualizada": time.time(), "usos": 0})
    _save_skills(items)
    audit("skill.add", nome, gatilhos, origem)
    return sid, "criada"


def skill_find(q):
    toks = [t for t in re.split(r"\W+", q.lower()) if len(t) > 2]
    scored = []
    for it in skills():
        hay = (it["nome"] + " " + it.get("gatilhos", "") + " " + it["passos"]).lower()
        sc = sum(hay.count(t) * (3 if t in it["nome"].lower() or t in it.get("gatilhos", "").lower() else 1) for t in toks)
        if sc:
            scored.append((sc, it))
    return [it for _, it in sorted(scored, key=lambda x: -x[0])][:5]


def skill_bump(sid):
    items = skills()
    for it in items:
        if it["id"] == sid:
            it["usos"] = it.get("usos", 0) + 1
    _save_skills(items)


# ----------------------------------------------------------------- apps / janelas / sistema / navegador
def _desktop_apps():
    return _load(MAP_FILE, {}).get("apps", {})


def app_find(q):
    q = q.lower().strip()
    apps = _desktop_apps()
    exact = [(i, a) for i, a in apps.items() if a["nome"].lower() == q or i.lower() == q]
    part = [(i, a) for i, a in apps.items() if q in a["nome"].lower() or q in i.lower() or q in a["exec"].lower()]
    return (exact or part)[:8]


def app_launch(q):
    hit = app_find(q)
    if not hit:
        return False, f"app '{q}' não encontrado no mapa (rode `prom pc refresh`)"
    did, a = hit[0]
    if subprocess.run(["which", "gtk-launch"], capture_output=True).returncode == 0:
        subprocess.Popen(["gtk-launch", did], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        subprocess.Popen(a["exec"], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True, f"abrindo {a['nome']} ({did})"


def windows():
    out = subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except Exception:
        return []


def pc_cli(s, rest):
    d = _load(MAP_FILE, {})
    if s in ("refresh", "map"):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "map_pc.py")], capture_output=True, text=True, timeout=240)
        print(r.stdout.strip() or r.stderr.strip()[-200:]); return 0
    if not d:
        print("mapa ainda não gerado: prom pc refresh"); return 1
    if s in ("info", ""):
        print(open(os.path.join(MEM, "mapa_pc_resumo.md")).read()); return 0
    if s == "apps":
        q = rest[0].lower() if rest else ""
        for i, a in sorted(d["apps"].items(), key=lambda kv: kv[1]["nome"].lower()):
            if not q or q in a["nome"].lower() or q in a["cat"].lower():
                print(f"{a['nome']:32s} {i:34s} {a['exec'][:60]}")
        return 0
    if s == "browser":
        n = d.get("navegador", {})
        q = rest[0].lower() if rest else ""
        print(f"padrão: {n.get('padrao')} | instalados: {', '.join(n.get('instalados', []))} | perfis: {[p['nome'] for p in n.get('perfis', [])]}")
        for b in n.get("favoritos", []):
            if not q or q in b["titulo"].lower() or q in b["url"].lower():
                print(f"- {b['titulo']}  {b['url']}")
        return 0
    if s == "hotkeys":
        print("\n".join(d["sessao"]["atalhos"])); return 0
    return 1


def sys_cli(s, rest):
    def run(*c):
        r = subprocess.run(list(c), capture_output=True, text=True, timeout=15); return (r.stdout + r.stderr).strip()
    if s == "vol":
        if rest and rest[0] in ("up", "down", "mute", "unmute"):
            arg = {"up": ["5%+"], "down": ["5%-"]}.get(rest[0])
            if arg:
                run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", *arg)
            else:
                run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if rest[0] == "mute" else "0")
        elif rest and rest[0].isdigit():
            run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{int(rest[0])}%")
        print(run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")); return 0
    if s == "bright":
        if rest and (rest[0].isdigit() or rest[0][:-1].isdigit()):
            run("brightnessctl", "set", rest[0] if rest[0].endswith("%") else rest[0] + "%")
        print(run("brightnessctl", "-m")); return 0
    if s == "media":
        a = rest[0] if rest else "status"
        if a in ("play", "pause", "play-pause", "next", "previous", "stop"):
            print(run("playerctl", a) or "ok")
        else:
            print(run("playerctl", "metadata", "--format", "{{artist}} — {{title}} [{{status}}]"))
        return 0
    if s == "power":
        if rest:
            print(run("powerprofilesctl", "set", rest[0]) or "ok")
        print(run("powerprofilesctl", "get")); return 0
    if s == "notify" and rest:
        print(run("notify-send", "-a", "Prometheus", rest[0], rest[1] if len(rest) > 1 else "") or "ok"); return 0
    if s == "clip":
        if rest:
            subprocess.run(["wl-copy", rest[0]]); print("copiado")
        else:
            print(run("wl-paste")[:1000])
        return 0
    if s == "open" and rest:
        subprocess.Popen(["xdg-open", rest[0]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True); print("ok"); return 0
    print("uso: prom sys vol [up|down|mute|N] | bright [N%] | media [play|pause|next|previous|status] | power [perfil] | notify T [C] | clip [texto] | open URL/ARQ"); return 1



# ----------------------------------------------------------------- holograma (palco do avatar)
_broadcast_cb = None

def set_broadcast_cb(cb):
    global _broadcast_cb
    _broadcast_cb = cb

def _daemon_send(msg):
    if _broadcast_cb is not None:
        try:
            _broadcast_cb(msg)
            return True
        except Exception:
            pass
    import socket
    sp = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "prometheus.sock")
    try:
        c = socket.socket(socket.AF_UNIX)
        c.settimeout(0.6)
        c.connect(sp)
        c.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        c.close()
        return True
    except Exception:
        return False


def holo_show(spec, op="show"):
    return _daemon_send({"type": "holo", "op": op, "spec": spec})


def _opt(rest, name, default=None):
    return rest[rest.index(name) + 1] if name in rest and rest.index(name) + 1 < len(rest) else default


def _find_window(q):
    q = q.lower().strip()
    ws = windows()
    for w in ws:
        if q == str(w.get("id")) or q == (w.get("app_id") or "").lower():
            return w
    for w in ws:
        if q in (w.get("app_id") or "").lower() or q in (w.get("title") or "").lower():
            return w
    return None


def holo_window(q, tamanho="mao"):
    """projeta a JANELA REAL (captura do niri, sem abrir/focar nada) no holograma — ex.: 'mostre meu Chromium'."""
    w = _find_window(q)
    if not w:
        return False, f"nenhuma janela aberta casa com '{q}'"
    prev = subprocess.run(["wl-paste", "--no-newline", "--type", "text"], capture_output=True).stdout
    r = subprocess.run(["niri", "msg", "action", "screenshot-window", "--id", str(w["id"]), "--write-to-disk", "false",
                        "--show-pointer", "false"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, "captura falhou: " + r.stderr.strip()[:120]
    time.sleep(0.5)
    img = subprocess.run(["wl-paste", "--type", "image/png"], capture_output=True).stdout
    try:
        if prev:
            subprocess.run(["wl-copy"], input=prev)               # devolve o texto que estava na área de transferência
    except Exception:
        pass
    if not img.startswith(b"\x89PNG"):
        return False, "não obtive a imagem da janela"
    path = f"/tmp/prometheus-holo-{int(time.time())}.png"
    with open(path, "wb") as f:
        f.write(img)
    import struct
    wpx, hpx = struct.unpack(">II", img[16:24])
    for old in sorted(glob_files("/tmp/prometheus-holo-*.png"))[:-3]:
        try:
            os.remove(old)
        except OSError:
            pass
    spec = {"kind": "imagem", "src": "file://" + path, "aspecto": wpx / max(1, hpx), "tamanho": tamanho,
            "titulo": f"{(w.get('app_id') or '').split('.')[-1].capitalize()} — {(w.get('title') or '')[:48]}",
            "legenda": f"{wpx}×{hpx} · janela real projetada", "ttl": 120}
    ok = holo_show(spec)
    audit("holo.window", w.get("app_id") or "", spec["titulo"], "ok" if ok else "daemon offline")
    return ok, f"projetando {spec['titulo']}" if ok else "daemon não respondeu"


def glob_files(pat):
    import glob
    return glob.glob(pat)


def holo_app_summary(nome):
    """sem janela aberta: monta um painel holográfico com o que o mapa sabe do app (ex.: navegador)."""
    d = _load(MAP_FILE, {})
    nome_l = nome.lower()
    paineis, titulo = [], nome.capitalize()
    if "chrom" in nome_l or "naveg" in nome_l or "browser" in nome_l:
        n = d.get("navegador", {})
        titulo = "Chromium"
        jan = [w.get("title", "")[:40] for w in windows() if "chrom" in (w.get("app_id") or "").lower()]
        paineis = [{"titulo": "Janelas/abas abertas", "tipo": "lista", "itens": jan or ["(nenhuma janela aberta)"]},
                   {"titulo": "Favoritos", "tipo": "lista", "itens": [b["titulo"][:40] for b in n.get("favoritos", [])[:8]]},
                   {"titulo": "Perfil", "tipo": "kpis", "itens": [{"rotulo": "perfis", "valor": str(len(n.get("perfis", [])))},
                                                                {"rotulo": "favoritos", "valor": str(n.get("favoritos_total", 0))},
                                                                {"rotulo": "extensões", "valor": str(len(n.get("extensoes", [])))}]}]
    else:
        hit = app_find(nome)
        if hit:
            did, a = hit[0]
            titulo = a["nome"]
            paineis = [{"titulo": "Aplicativo", "tipo": "lista", "itens": [f"id: {did}", f"comando: {a['exec'][:40]}", f"origem: {a['origem']}", f"categorias: {a['cat'][:40]}"]}]
    return {"kind": "ui", "titulo": titulo, "barra": ["Arquivo", "Ver", "Ajuda"], "lateral": [], "paineis": paineis or [{"titulo": "Sem dados", "tipo": "lista", "itens": ["app não encontrado no mapa"]}],
            "tamanho": "mao", "ttl": 120}


def holo_cli(s, rest):
    base = {}
    if "--grande" in rest:
        base["tamanho"] = "grande"
    if _opt(rest, "--ttl"):
        base["ttl"] = int(_opt(rest, "--ttl"))
    if s == "clear":
        holo_show(None, "clear"); print("ok"); return 0
    if s in ("window", "app") and rest:
        ok, msg = holo_window(rest[0], "grande" if "--grande" in rest else "mao")
        if not ok and s == "app":
            sp = holo_app_summary(rest[0])
            if "--grande" in rest:
                sp["tamanho"] = "grande"
            holo_show(sp); audit("holo.app", rest[0], "resumo holográfico (sem janela)", msg); print("sem janela aberta; exibindo resumo holográfico"); return 0
        print(msg); return 0 if ok else 1
    spec = None
    if s == "email":
        spec = {"kind": "email", "para": _opt(rest, "--to", ""), "cc": _opt(rest, "--cc", ""), "assunto": _opt(rest, "--subject", ""),
                "corpo": _opt(rest, "--body", ""), "status": _opt(rest, "--status", "rascunho"), "titulo": "Novo e-mail"}
    elif s == "figure" and rest:
        spec = {"kind": "figura", "forma": rest[0], "titulo": _opt(rest, "--titulo", rest[0].capitalize()), "legenda": _opt(rest, "--legenda", "")}
    elif s == "chart" and rest:
        dados = []
        for kv in (_opt(rest, "--dados", "") or "").split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    dados.append({"rotulo": k.strip(), "valor": float(v)})
                except ValueError:
                    pass
        spec = {"kind": "grafico", "tipo": rest[0], "titulo": _opt(rest, "--titulo", "Gráfico"), "dados": dados}
    elif s == "text":
        spec = {"kind": "texto", "titulo": _opt(rest, "--titulo", ""), "linhas": [x for x in (_opt(rest, "--linhas", "") or "").split("|") if x]}
    elif s in ("ui", "scene"):
        raw = _opt(rest, "--json")
        if not raw and _opt(rest, "--file"):
            raw = open(os.path.expanduser(_opt(rest, "--file"))).read()
        try:
            spec = json.loads(raw)
        except Exception as e:
            print("JSON inválido:", e); return 1
        spec.setdefault("kind", "ui" if s == "ui" else "cena")
    if spec is None:
        print('uso: prom holo email --to X --subject Y --body Z | figure cubo|esfera|toro|piramide|helice|galaxia|rede [--titulo T] | '
              'chart barras|linha|pizza --dados "a=10,b=20" [--titulo T] | text --titulo T --linhas "a|b" | ui|scene --json \'{...}\'|--file F | clear   [--grande] [--ttl S]')
        return 1
    spec.update(base)
    ok = holo_show(spec)
    audit("holo.show", spec.get("kind", ""), str(spec.get("titulo", ""))[:80], "ok" if ok else "daemon offline")
    print("exibindo no palco" if ok else "ERRO: daemon não respondeu"); return 0 if ok else 1


# ----------------------------------------------------------------- CLI
def _p(x):
    print(json.dumps(x, ensure_ascii=False, indent=1) if not isinstance(x, str) else x)


def main(a):
    if not a:
        print(__doc__); return 0
    g, s = a[0], (a[1] if len(a) > 1 else "")
    rest = a[2:]
    if g == "policy":
        _p(policy()); return 0
    if g == "approvals":
        _p([i for i in approvals() if i["estado"] == "pendente"]); return 0
    if g in ("approve", "reject"):
        ok, msg = resolve(s, g == "approve"); print(("OK: " if ok else "ERRO: ") + msg); return 0 if ok else 1
    if g == "notify":
        ok, msg = gated("notify.me", "dono", f"aviso ao dono: {s}", {"texto": s}); print(msg); return 0 if ok else 1
    if g == "holo":
        return holo_cli(s, rest)
    if g == "mail" and s == "compose":
        to, sub, body = _opt(rest, "--to"), _opt(rest, "--subject", ""), _opt(rest, "--body", "")
        if not to:
            print("ERRO: faltou --to"); return 1
        holo_show({"kind": "email", "para": to, "cc": _opt(rest, "--cc", ""), "assunto": sub, "corpo": body,
                   "status": "aguardando aprovação", "titulo": "Novo e-mail", "ttl": 300})
        ok, msg = gated("mail.send", to, f"e-mail para {to}: {sub}", {"to": to, "subject": sub, "body": body})
        print(msg); return 0 if ok else 1
    if g == "skill":
        if s in ("list", ""):
            for it in skills():
                print(f"[{it['id']}] {it['nome']}  (usos {it.get('usos', 0)}) — gatilhos: {it.get('gatilhos', '')[:80]}")
            return 0
        if s == "find" and rest:
            for it in skill_find(" ".join(rest)):
                print(f"## {it['nome']}  [{it['id']}]\n{it['passos']}\n"); skill_bump(it["id"])
            return 0
        if s == "show" and rest:
            it = next((i for i in skills() if i["id"] == rest[0] or i["nome"].lower() == " ".join(rest).lower()), None)
            print(it["passos"] if it else "não encontrada"); return 0
        if s == "add" and len(rest) >= 2:
            sid, msg = skill_add(rest[0], rest[1], rest[2] if len(rest) > 2 else ""); print(f"habilidade {msg}: {sid}"); return 0
        if s == "rm" and rest:
            _save_skills([i for i in skills() if i["id"] != rest[0]]); print("ok"); return 0
    if g == "pc":
        return pc_cli(s, rest)
    if g == "apps":
        if s == "launch" and rest:
            ok, msg = app_launch(" ".join(rest)); audit("apps.launch", " ".join(rest), msg); print(msg); return 0 if ok else 1
        if s == "find" and rest:
            for did, a in app_find(" ".join(rest)):
                print(f"{a['nome']} | {did} | {a['exec']}")
            return 0
        return pc_cli("apps", rest)
    if g == "win":
        ws = windows()
        if s in ("list", ""):
            for w in ws:
                print(f"{w.get('id')}  {w.get('app_id')}  — {w.get('title', '')[:60]}{'  [foco]' if w.get('is_focused') else ''}")
            return 0
        if s in ("focus", "close") and rest:
            q = " ".join(rest).lower()
            w = next((w for w in ws if q == str(w.get("id")) or q in (w.get("app_id") or "").lower() or q in (w.get("title") or "").lower()), None)
            if not w:
                print("janela não encontrada"); return 1
            act = "focus-window" if s == "focus" else "close-window"
            r = subprocess.run(["niri", "msg", "action", act, "--id", str(w["id"])], capture_output=True, text=True)
            print("ok" if r.returncode == 0 else r.stderr.strip()); return r.returncode
    if g == "sys":
        return sys_cli(s, rest)
    if g == "browser":
        if s == "open" and rest:
            subprocess.Popen(["setsid", "chromium", "--force-renderer-accessibility", rest[0]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); audit("browser.open", rest[0], "abrir URL"); print("abrindo"); return 0
        return pc_cli("browser", rest)
    if g == "projects":
        ps = projects()
        if s in ("list", ""):
            for p in ps:
                if p["nome"].startswith("."):
                    continue
                gi = p.get("git")
                print(f"- {p['nome']}: {', '.join(p['stack'][:4]) or '—'} | {p['arquivos']} arqs | {p['tamanho_mb']} MB | "
                      f"{(gi['branch'] + ', ' + str(gi['alteracoes_pendentes']) + ' alt.') if gi else 'sem git'}")
            return 0
        if s == "info" and rest:
            p = project_find(rest[0])
            if not p:
                print("projeto não encontrado"); return 1
            _p(p); return 0
        if s == "refresh":
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "scan_projetos.py")], capture_output=True, text=True)
            print(r.stdout.strip() or r.stderr.strip()[-200:]); return 0
    if g == "remote":
        if s == "add" and len(rest) >= 2:
            hosts = remotes()
            hosts[rest[0]] = {"id": rest[1].replace(" ", ""), "senha_arquivo": rest[rest.index("--senha-arquivo") + 1] if "--senha-arquivo" in rest else ""}
            _save(REMOTE_FILE, {"hosts": hosts}); audit("remote.add", rest[0], "host cadastrado"); print("ok"); return 0
        if s in ("list", ""):
            _p({k: {"id": v["id"], "senha": "arquivo" if v.get("senha_arquivo") else "sem"} for k, v in remotes().items()}); return 0
        if s == "status":
            _p({"anydesk": " ".join(_anydesk_cmd() or []) or "não instalado", "hosts": list(remotes())}); return 0
        if s == "connect" and rest:
            if rest[0] not in remotes():
                print(f"ERRO: host '{rest[0]}' não cadastrado. Cadastrados: {', '.join(remotes()) or 'nenhum'}"); return 1
            nivel, motivo = check("remote.connect", rest[0])
            if nivel == "confirmar":
                aid = request_approval("remote.connect", rest[0], f"conectar via AnyDesk a {rest[0]}", {"alias": rest[0]})
                print(f"PENDENTE de aprovação (id {aid}): conectar via AnyDesk a {rest[0]}"); return 1
            ok, msg = remote_connect(rest[0]); audit("remote.connect", rest[0], "conexão AnyDesk", msg); print(msg); return 0 if ok else 1
    if g in ("net", "wifi", "bt"):
        return net_cli(g, s, rest)
    if g == "zap":
        import zap
        if s in ("status", ""):
            _p({"depurador": zap.available(), "config": _load(os.path.join(MEM, "zap.json"), {})}); return 0
        if s == "launch":
            print(zap.launch()); return 0
        if s == "chats":
            r = zap.snapshot()
            if not r.get("ok"):
                print("ERRO:", r.get("motivo")); return 1
            cs = [c for c in r["chats"] if (c["nao_lidas"] or "--todas" in rest)]
            for c in cs[:30]:
                print(f"{'●' + str(c['nao_lidas']) if c['nao_lidas'] else ' '}  {c['nome']} ({c['hora']}): {c['previa'][:120]}")
            if not cs:
                print("(sem mensagens não lidas)")
            return 0
        if s == "read" and rest:
            nivel, motivo = check("wa.read_chat", rest[0])
            if nivel != "auto":
                print("PENDENTE/BLOQUEADO:", motivo); return 1
            r = zap.read_chat(rest[0], int(rest[rest.index("--n") + 1]) if "--n" in rest else 15)
            audit("wa.read_chat", rest[0], "leitura de conversa", "ok" if r.get("ok") else str(r.get("motivo")))
            if not r.get("ok"):
                print("ERRO:", r.get("motivo")); return 1
            for m in r["msgs"]:
                print(f"{'eu' if m['saida'] else m['quem'] or '?'} [{m['quando']}]: {m['texto']}")
            return 0
        if s == "reply" and len(rest) >= 2:
            ok, msg = gated("wa.send_chat", rest[0], f"responder {rest[0]}: {rest[1][:100]}", {"nome": rest[0], "texto": rest[1]})
            print(msg); return 0 if ok else 1
    if g == "agenda":
        def opt(n, d=None):
            return rest[rest.index(n) + 1] if n in rest and rest.index(n) + 1 < len(rest) else d
        if s == "add":
            titulo = rest[0] if rest and not rest[0].startswith("--") else ""
            aid, msg = agenda_add(titulo, opt("--quando", ""), opt("--tipo", "compromisso"), int(opt("--dur", 60)),
                                  opt("--local", ""), opt("--com", ""), opt("--notas", ""), "manual", opt("--lembrar"))
            print((f"agendado {aid}" if aid else "ERRO") + ": " + msg); return 0 if aid else 1
        if s in ("list", "today", "hoje", ""):
            dias = 1 if s in ("today", "hoje") else int(opt("--dias", 7))
            lt = time.localtime(); ini0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
            itens = agenda_list(dias, desde=ini0 if s in ("today", "hoje") else None)
            print("\n".join(agenda_fmt(i) for i in itens) if itens else "(agenda vazia)"); return 0
        if s in ("done", "rm") and rest:
            agenda_mark(rest[0], **({"feito": True} if s == "done" else {"removido": True})); print("ok"); return 0
        if s == "export":
            ics = agenda_ics(); path = os.path.join(MEM, "agenda.ics"); open(path, "w").write(ics); print(path); return 0
    if g == "task":
        if s == "add":
            texto = rest[0] if rest else ""
            quando = rest[rest.index("--quando") + 1] if "--quando" in rest else ""
            pasta = rest[rest.index("--dir") + 1] if "--dir" in rest else None
            print("tarefa criada:", task_add(texto, quando, pasta)); return 0
        if s == "list":
            _p([{k: v for k, v in i.items() if k in ("id", "texto", "estado", "quando", "recorrente", "resultado")} for i in tasks()]); return 0
        if s in ("done", "cancel") and rest:
            task_set(rest[0], estado="feita" if s == "done" else "cancelada"); print("ok"); return 0
    if g == "phone":
        if s == "status":
            _p({"pareado": bool(_kc_device()), "alcancavel": phone_reachable()}); return 0
        if s == "notifs":
            _p(phone_notifs()); return 0
        if s == "battery":
            dev = _kc_device()
            r = subprocess.run(["busctl", "--user", "get-property", "org.kde.kdeconnect", f"/modules/kdeconnect/devices/{dev}/battery",
                                "org.kde.kdeconnect.device.battery", "charge", "isCharging"], capture_output=True, text=True)
            print(r.stdout.strip() or r.stderr.strip()); return 0
        if s in ("ring", "ping"):
            ok, msg = gated("phone." + s, "dono", f"celular: {s}", {"texto": rest[0] if rest else ""}); print(msg); return 0 if ok else 1
        if s == "sms" and len(rest) >= 2:
            ok, msg = gated("sms.send", rest[0], f"SMS para {rest[0]}: {rest[1][:80]}", {"numero": rest[0], "texto": rest[1]}); print(msg); return 0 if ok else 1
        if s in ("share", "url") and rest:
            ok, msg = gated("phone.share", "dono", f"enviar ao celular: {rest[0]}", {"arquivo": rest[0]} if s == "share" else {"url": rest[0]}); print(msg); return 0 if ok else 1
    if g == "wa":
        if s == "read":
            n = [x for x in phone_notifs() if re.search(r"whatsapp|telegram|messag|sms|signal", (x.get("app") or ""), re.I)]
            _p(n); return 0
        if s == "reply" and len(rest) >= 2:
            n = next((x for x in phone_notifs() if x["id"] == rest[0]), None)
            if not n or not n.get("reply_id"):
                print("ERRO: notificação não encontrada ou sem resposta rápida"); return 1
            ok, msg = gated("wa.reply", n.get("titulo") or "", f"responder {n.get('titulo')}: {rest[1][:100]}",
                            {"reply_id": n["reply_id"], "texto": rest[1]}); print(msg); return 0 if ok else 1
    if g == "mail":
        try:
            if s == "list":
                n = int(rest[rest.index("--n") + 1]) if "--n" in rest else 10
                _p(mail_list(n, "--unread" in rest)); return 0
            if s == "read" and rest:
                _p(mail_read(rest[0])); return 0
            if s == "send":
                kv = {rest[i]: rest[i + 1] for i in range(0, len(rest) - 1, 2)}
                to, sub, body = kv.get("--to"), kv.get("--subject", ""), kv.get("--body", "")
                if not to:
                    print("ERRO: faltou --to"); return 1
                ok, msg = gated("mail.send", to, f"e-mail para {to}: {sub}", {"to": to, "subject": sub, "body": body})
                print(msg); return 0 if ok else 1
        except RuntimeError as e:
            print("ERRO:", e); return 1
        except Exception as e:
            print("ERRO de e-mail:", repr(e)); return 1
    print(__doc__); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
