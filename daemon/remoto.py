"""Controle REMOTO da F.R.I.D.A.Y. (app Android): HTTP + WebSocket SÓ no Tailscale (e localhost), sempre com token.
Escuta em 127.0.0.1 e no IP do Tailscale (não na rede local/Wi-Fi). Token em memory/remoto.json (0600, gerado na 1ª vez).
- WS  /ws         : recebe o que a interface recebe (estado, fala, boca, painéis) e manda comandos (texto, ligar, pare, ação)
- POST /api/audio : áudio do celular -> Whisper -> vira fala para ela
- POST /api/foto  : quadro da câmera do celular -> fica em /tmp/friday-remote-cam.jpg (perguntas visuais usam)
- POST /api/anexo : arquivos -> ~/Documentos/Friday/recebidos (o caminho vai junto da mensagem)
- GET  /api/tela  : print reduzido;  POST /api/acao : ação rápida (volume, mídia, painéis...)
- GET/POST /api/aprovacoes : pendentes / aprovar|cancelar|alterar;  GET /api/historico?n=40 : últimas falas
- WS  /vnc        : ponte para o wayvnc local (127.0.0.1:5900), protegida pelo mesmo token
- GET  /api/status: voz/câmera/Friday/modos/estado + últimos stats (consulta o socket local do daemon)
- POST /api/cmd   : {"type": voice|camera|friday|stop|mode|ptz, ...} validado por lista branca -> socket local do daemon
- GET  /api/cam/{nome} : quadro JPEG de uma câmera, SÓ nomes fixos (nativa|porta|ptz)
- GET  /api/painel: dados do painel (/tmp/friday-painel.json, só chaves conhecidas)
- POST /api/pedido: {"texto"} da Friday LOCAL do celular -> vira pedido para a Friday do PC (as duas cooperam quando ligadas)
- GET /api/agenda?dias=14 · POST /api/agenda/sync {mudancas, google} · POST /api/agenda/add {titulo, quando, prioridade}: agenda PC <-> celular"""
import asyncio
import json
import os
import secrets
import subprocess
import tempfile
import time

from aiohttp import web, WSMsgType

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CFG = os.path.join(ROOT, "memory", "remoto.json")
RECEBIDOS = os.path.expanduser("~/Documentos/Friday/recebidos")
FOTO = "/tmp/friday-remote-cam.jpg"
PORT = int(os.environ.get("FRIDAY_REMOTE_PORT", "8790"))
VNC = ("127.0.0.1", 5900)
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "prometheus.sock")
PAINEL = "/tmp/friday-painel.json"
CAMS = {"nativa": "/tmp/friday-cam.jpg", "porta": "/tmp/friday-cam-amb.jpg", "ptz": "/tmp/friday-cam-ptz.jpg"}   # lista branca
PAINEL_CHAVES = ("t", "clima", "agenda", "agenda_nivel", "tarefas", "recente", "memoria", "processos", "rede", "disco", "uptime")
MODOS = ("seguranca", "privacidade", "silencio", "mouse", "criacao", "janela", "sentinela")
PTZ_DIRS = ("esquerda", "direita", "cima", "baixo", "centro")
PTZ_OPS = ("olhar", "em_volta", "seguir", "vigiar", "auto", "parar", "zoom", "procurar", "onde")
_ult = {}                    # último evento de cada tipo visto no broadcast (stats, modes, voice, camera, friday, state)
_ULT_TIPOS = ("stats", "modes", "voice", "camera", "friday", "state")

clientes = set()
_ctx = {}
_wh = {"m": None}


def config():
    try:
        c = json.load(open(CFG))
    except Exception:
        c = {}
    if not c.get("token"):
        c["token"] = secrets.token_urlsafe(18)
        os.makedirs(os.path.dirname(CFG), exist_ok=True)
        json.dump(c, open(CFG, "w"), indent=1)
    os.chmod(CFG, 0o600)
    return c


def _ok(req):
    tok = req.headers.get("X-Token") or req.query.get("t") or ""
    return secrets.compare_digest(tok, config()["token"])


@web.middleware
async def _auth(req, handler):
    if req.method == "OPTIONS":
        r = web.Response()
    elif req.path == "/api/ping":
        r = await handler(req)
    elif not _ok(req):
        r = web.json_response({"erro": "token inválido"}, status=401)
    else:
        try:
            rem = req.remote
            if rem and rem not in ("127.0.0.1", "::1"):
                import sync_mesh
                sync_mesh.salvar_peer_configurado(rem, alias=f"peer-{rem}")
        except Exception:
            pass
        r = await handler(req)
    if not isinstance(r, web.WebSocketResponse):
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Headers"] = "X-Token, Content-Type"
        r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        r.headers["Access-Control-Allow-Private-Network"] = "true"      # WebView/Chrome: página https -> IP privado (Tailscale) exige isto
    return r


async def publicar(msg):
    """chamado pelo broadcast do daemon: repassa ao app (cliente lento não trava ninguém)."""
    if isinstance(msg, dict) and msg.get("type") in _ULT_TIPOS:
        _ult[msg["type"]] = msg
    if not clientes:
        return
    raw = json.dumps(msg, ensure_ascii=False)
    for ws in list(clientes):
        try:
            await asyncio.wait_for(ws.send_str(raw), 1.0)
        except Exception:
            clientes.discard(ws)


def _transcrever(caminho):
    # Cancelamento de Ruído ativo via FFT denoiser + corte de ruído de alta/baixa frequência
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", caminho,
                          "-af", "highpass=f=85,lowpass=f=4000,afftdn=nr=18:nf=-25:tn=1",
                          "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, timeout=60).stdout
    if len(pcm) < 8000:
        return ""
    import numpy as np
    a = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768

    # Supressão Estrita de Vozes de Terceiros (Speaker Verification TitaNet — só a voz do dono)
    vd = _ctx.get("voz_dono")
    vd = vd() if callable(vd) else vd
    if vd is not None and getattr(vd, "pronto", False):
        aceitar, a_filtrado, info = vd.decidir(a, estrito=True)
        if not aceitar:
            sc = info.get("score") or 0.0
            print(f"[remoto] áudio ignorado: não é a voz do dono (score={sc}, motivo={info.get('motivo')})", flush=True)
            return f"__RECUSADA__:{sc:.2f}"
        a = a_filtrado

    if _wh["m"] is None:
        from faster_whisper import WhisperModel
        _wh["m"] = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4, download_root=os.path.join(ROOT, "models", "whisper"))
    segs, _ = _wh["m"].transcribe(a, language="pt", vad_filter=True, beam_size=1, condition_on_previous_text=False,
                                  initial_prompt=_ctx.get("stt_prompt", lambda: "")())
    return " ".join(s.text.strip() for s in segs).strip()


async def ping(req):
    return web.json_response({"ok": True, "nome": "F.R.I.D.A.Y.", "auth": _ok(req)})


async def estado(req):
    return web.json_response(_ctx["estado"]())


async def ws_handler(req):
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 << 20)
    await ws.prepare(req)
    clientes.add(ws)
    await ws.send_str(json.dumps({"type": "hello", **_ctx["estado"](), **(await _estado_daemon())}, ensure_ascii=False))
    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                d = json.loads(m.data)
            except Exception:
                continue
            t = d.get("type")
            if t == "texto" and str(d.get("text", "")).strip():
                asyncio.create_task(_ctx["texto"](str(d["text"])[:4000], [str(x) for x in (d.get("files") or [])][:10]))
            elif t == "ligar":
                asyncio.create_task(_ctx["ligar"](bool(d.get("on", True))))
            elif t == "pare":
                _ctx["pare"]()
            elif t == "acao" and isinstance(d.get("acao"), dict):
                asyncio.create_task(_acao_bg(d["acao"]))
            elif t == "ide" and _ctx.get("ide") is not None:
                asyncio.create_task(_ctx["ide"].tratar(d, lambda r: ws.send_str(json.dumps(r, ensure_ascii=False))))
            elif t == "dev":
                try:
                    import dev as _dev
                    await ws.send_str(json.dumps({"type": "dev_hist", "itens": _dev.historico(int(d.get("n", 200)))}, ensure_ascii=False))
                except Exception:
                    pass
            elif t == "cmd" and isinstance(d.get("cmd"), dict):
                c, erro = _validar_cmd(d["cmd"])
                if c is not None:
                    asyncio.create_task(_sock_enviar(c))
                else:
                    await ws.send_str(json.dumps({"type": "acao_res", "ok": False, "msg": erro}, ensure_ascii=False))
    finally:
        clientes.discard(ws)
    return ws


async def _acao_bg(a):
    ok, msg = await asyncio.to_thread(_ctx["acao"], a)
    await publicar({"type": "acao_res", "ok": ok, "msg": msg or ""})


async def audio(req):
    dados = await req.read()
    if len(dados) < 2000:
        return web.json_response({"texto": ""})
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(dados)
    try:
        txt = await asyncio.to_thread(_transcrever, f.name)
    finally:
        os.unlink(f.name)
    if isinstance(txt, str) and txt.startswith("__RECUSADA__:"):
        sc = txt.split(":", 1)[1]
        return web.json_response({"texto": "", "recusada": True, "score": sc, "msg": f"Voz não reconhecida como dono ({sc})"})
    if txt:
        await publicar({"type": "remote_heard", "text": txt})
        asyncio.create_task(_ctx["fala"](txt))
    return web.json_response({"texto": txt})


async def foto(req):
    dados = await req.read()
    if len(dados) > 1000:
        open(FOTO + ".tmp", "wb").write(dados)
        os.replace(FOTO + ".tmp", FOTO)
        _ctx["foto"](FOTO)
    return web.json_response({"ok": True})


async def anexo(req):
    os.makedirs(RECEBIDOS, exist_ok=True)
    salvos = []
    rd = await req.multipart()
    async for parte in rd:
        if not parte.filename:
            continue
        nome = os.path.basename(parte.filename)[:120] or "arquivo"
        dest = os.path.join(RECEBIDOS, time.strftime("%H%M%S-") + nome)
        with open(dest, "wb") as f:
            while True:
                ch = await parte.read_chunk(1 << 16)
                if not ch:
                    break
                f.write(ch)
        salvos.append(dest)
    return web.json_response({"arquivos": salvos})


async def tela(req):
    esc = req.query.get("s", "0.5")
    esc = esc if esc in ("0.25", "0.35", "0.5", "0.75", "1") else "0.5"
    img = await asyncio.to_thread(lambda: subprocess.run(["grim", "-s", esc, "-t", "jpeg", "-q", "60", "-"], capture_output=True, timeout=10).stdout)
    return web.Response(body=img, content_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def acao(req):
    ok, msg = await asyncio.to_thread(_ctx["acao"], await req.json())
    return web.json_response({"ok": ok, "msg": msg or ""})


async def aprovacoes_get(req):
    itens = await asyncio.to_thread(_ctx["aprovacoes"])
    return web.json_response({"itens": itens})


async def aprovacoes_post(req):
    try:
        d = await req.json()
    except Exception:
        return web.json_response({"ok": False, "msg": "JSON inválido", "item": None}, status=400)
    if not isinstance(d, dict):
        return web.json_response({"ok": False, "msg": "JSON inválido", "item": None}, status=400)
    aid, dec, txt = d.get("id"), d.get("decisao"), d.get("texto")
    if not isinstance(aid, str) or not aid.strip() or len(aid) > 64:
        return web.json_response({"ok": False, "msg": "id inválido", "item": None}, status=400)
    if dec not in ("aprovar", "cancelar", "alterar"):
        return web.json_response({"ok": False, "msg": "decisão inválida (aprovar|cancelar|alterar)", "item": None}, status=400)
    if dec == "alterar":
        if not isinstance(txt, str) or not txt.strip():
            return web.json_response({"ok": False, "msg": "texto obrigatório para alterar", "item": None}, status=400)
        if len(txt) > 2000:
            return web.json_response({"ok": False, "msg": "texto acima de 2000 caracteres", "item": None}, status=400)
    pend = await asyncio.to_thread(_ctx["aprovacoes"])
    it = next((i for i in pend if i.get("id") == aid), None)
    if it is None:
        return web.json_response({"ok": False, "msg": "aprovação não encontrada ou já resolvida", "item": None}, status=404)
    if dec == "alterar" and not it.get("editavel"):
        return web.json_response({"ok": False, "msg": "só mensagens de WhatsApp podem ser alteradas", "item": it}, status=400)
    ok, msg, item = await _ctx["resolver"](aid, dec, txt.strip() if dec == "alterar" else None)
    return web.json_response({"ok": bool(ok), "msg": str(msg or ""), "item": item})


async def historico(req):
    try:
        n = int(req.query.get("n", "40"))
    except ValueError:
        n = 40
    n = max(1, min(200, n))
    return web.json_response({"itens": await asyncio.to_thread(_ctx["historico"], n)})


# ---------- controle pelo socket local do daemon (mesmo protocolo do prometheus-ctl) ----------
def _validar_cmd(d):
    """Lista branca: devolve (mensagem_limpa, None) ou (None, erro). Nada do cliente passa adiante sem ser reconstruído aqui."""
    if not isinstance(d, dict):
        return None, "comando inválido"
    t = d.get("type")
    if t in ("voice", "camera", "friday"):
        return {"type": t, "on": bool(d.get("on", True))}, None
    if t == "stop":
        return {"type": "stop"}, None
    if t == "mode":
        if d.get("mode") not in MODOS:
            return None, "modo desconhecido"
        on = d.get("on")
        return {"type": "mode", "mode": d["mode"], "on": None if on is None else bool(on)}, None
    if t == "ptz":
        op = d.get("op")
        if op not in PTZ_OPS:
            return None, "operação de câmera não permitida"
        m = {"type": "ptz", "op": op}
        if op == "olhar":
            if d.get("dir") not in PTZ_DIRS:
                return None, "direção inválida"
            m["dir"] = d["dir"]
        elif op == "zoom":
            try:
                m["fator"] = max(1.0, min(4.0, float(d.get("fator", 2.0))))
            except (TypeError, ValueError):
                return None, "fator inválido"
        elif op == "procurar":
            alvo = str(d.get("alvo") or "").strip()[:60]
            if not alvo:
                return None, "falta o alvo"
            m["alvo"] = alvo
        elif op == "onde":
            m["falar"] = False
        return m, None
    return None, "comando desconhecido"


async def _sock_enviar(msg):
    """Uma linha JSON no socket do daemon (o handler lê a linha mesmo com o cliente fechando logo depois)."""
    try:
        r, w = await asyncio.wait_for(asyncio.open_unix_connection(SOCK), 2)
    except Exception as e:
        return False, f"daemon inacessível: {e}"
    try:
        w.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        await w.drain()
        await asyncio.sleep(0.05)
    except Exception as e:
        return False, str(e)
    finally:
        try:
            w.close()
        except Exception:
            pass
    return True, "ok"


async def _estado_daemon():
    """Ao conectar, o daemon manda state/voice/camera/friday/modes (+ history): lê só isso e fecha."""
    out = {}
    try:
        r, w = await asyncio.wait_for(asyncio.open_unix_connection(SOCK, limit=4 << 20), 1.5)
    except Exception:
        return {"voice": (_ult.get("voice") or {}).get("on"), "camera": (_ult.get("camera") or {}).get("on")} if _ult else {}
    try:
        fim = time.time() + 1.5
        while time.time() < fim and "modes" not in out:
            ln = await asyncio.wait_for(r.readline(), max(0.05, fim - time.time()))
            if not ln:
                break
            try:
                m = json.loads(ln)
            except ValueError:
                continue
            tp = m.get("type")
            if tp in ("voice", "camera", "friday"):
                out[tp] = bool(m.get("on"))
            elif tp == "state":
                out["state"], out["mood"] = m.get("state"), m.get("mood")
            elif tp == "modes":
                out["modes"] = {k: bool(m.get(k)) for k in MODOS if k in m}
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass
    if "friday" in out:
        out["on"] = out["friday"]
    return out


async def status(req):
    d = await _estado_daemon()
    st = _ult.get("stats")
    if st:
        d["stats"] = st
    return web.json_response(d)


async def cmd(req):
    try:
        d = await req.json()
    except Exception:
        return web.json_response({"ok": False, "msg": "JSON inválido"}, status=400)
    m, erro = _validar_cmd(d)
    if m is None:
        return web.json_response({"ok": False, "msg": erro}, status=400)
    ok, msg = await _sock_enviar(m)
    return web.json_response({"ok": ok, "msg": msg}, status=200 if ok else 503)


async def pedido(req):
    """a Friday do CELULAR (cérebro local) delega ao PC o que é do computador. Mesmo caminho do texto digitado no app."""
    try:
        d = await req.json()
    except Exception:
        return web.json_response({"ok": False, "erro": "JSON inválido"}, status=400)
    t = str(d.get("texto") or "").strip()[:2000]
    if not t:
        return web.json_response({"ok": False, "erro": "pedido vazio"}, status=400)
    asyncio.create_task(_ctx["texto"]("[pedido da Friday do celular] " + t, []))
    return web.json_response({"ok": True})


_stt_trava = asyncio.Lock()


async def stt(req):
    """POST PCM16 16 kHz mono do celular (já filtrado: só a voz do dono) -> Whisper do PC (mesmo modelo/vocabulário do
    microfone daqui). Só transcreve: NÃO vira pedido para a Friday do PC."""
    dados = await req.read()
    if len(dados) < 16000 * 2 * 0.3:
        return web.json_response({"texto": "", "erro": "áudio curto"})
    if not _ctx.get("stt"):
        return web.json_response({"texto": "", "erro": "STT indisponível"}, status=503)
    import numpy as np
    a = np.frombuffer(dados[: len(dados) // 2 * 2], dtype="<i2").astype("float32") / 32768
    pico = float(np.abs(a).max()) if len(a) else 0.0
    if pico > 0:
        a = a / pico * 0.8
    vd = _ctx.get("voz_dono")
    vd = vd() if callable(vd) else vd
    if vd is not None and getattr(vd, "pronto", False):
        aceitar, a_filt, info = await asyncio.to_thread(vd.decidir, a, False, True)
        if not aceitar and info.get("score", 0.0) < vd.limiar - 0.04:
            print(f"[remoto/stt] voz recusada pelo TitaNet: score={info.get('score')} limiar={vd.limiar}", flush=True)
            return web.json_response({"texto": "", "erro": "outra voz", "score": info.get("score", 0.0)})
        a = a_filt
    t0 = time.time()
    async with _stt_trava:
        try:
            txt = await asyncio.to_thread(_ctx["stt"], a)
        except Exception as e:
            return web.json_response({"texto": "", "erro": repr(e)[:120]}, status=500)
    return web.json_response({"texto": txt or "", "ms": int((time.time() - t0) * 1000)})


async def aprimorar(req):
    """POST {"pedido", "falhas":[...], "voz":"resumo"} do celular -> proposta de melhoria no código do APP (Claude numa cópia);
    o dono aprova no PC/app (self.apply) e o aprimorar.py compila e instala o APK pelo ADB."""
    try:
        d = await req.json()
    except Exception:
        return web.json_response({"ok": False, "erro": "JSON inválido"}, status=400)
    if not _ctx.get("aprimorar"):
        return web.json_response({"ok": False, "erro": "aprimoramento indisponível"}, status=503)
    pedido = str(d.get("pedido") or "corrigir as falhas recentes do app do celular").strip()[:400]
    fal = [str(x)[:200] for x in (d.get("falhas") or [])][:8]
    texto = ("[APP DO CELULAR] " + pedido + (". Falhas registradas no celular: " + " · ".join(fal) if fal else "")
             + (". Voz no celular: " + str(d.get("voz"))[:300] if d.get("voz") else ""))
    asyncio.create_task(_ctx["aprimorar"](texto))
    return web.json_response({"ok": True})


async def agenda_get(req):
    """agenda do PC p/ o celular: janela [-1 dia, +dias] com feitos + nível de cada dia."""
    import prom_ops as ops
    try:
        dias = max(1, min(31, int(req.query.get("dias", "14"))))
    except ValueError:
        dias = 14
    return web.json_response(await asyncio.to_thread(ops.agenda_janela, dias), headers={"Cache-Control": "no-store"})


async def agenda_sync(req):
    """POST {"mudancas":[itens editados/criados no celular], "google":[eventos do Google do celular] | null, "dias":14}"""
    import prom_ops as ops
    try:
        d = await req.json()
    except Exception:
        return web.json_response({"ok": False, "erro": "JSON inválido"}, status=400)
    mud = d.get("mudancas") if isinstance(d.get("mudancas"), list) else []
    goo = d.get("google") if isinstance(d.get("google"), list) else None
    try:
        dias = max(1, min(31, int(d.get("dias", 14))))
    except (TypeError, ValueError):
        dias = 14
    r = await asyncio.to_thread(ops.agenda_sync, mud[:500], goo[:1000] if goo is not None else None, dias)
    if mud and _ctx.get("agenda_mudou"):
        try:
            asyncio.create_task(_ctx["agenda_mudou"]())
        except Exception:
            pass
    return web.json_response(r)


async def agenda_add(req):
    """POST {"titulo","quando" (texto livre: 'amanhã 15h'),"prioridade","dur"} -> o PC interpreta a data (parse_quando)."""
    import prom_ops as ops
    try:
        d = await req.json()
    except Exception:
        return web.json_response({"ok": False, "erro": "JSON inválido"}, status=400)
    tit, q = str(d.get("titulo") or "").strip(), str(d.get("quando") or "").strip()
    if not tit or not q:
        return web.json_response({"ok": False, "erro": "título e quando são obrigatórios"}, status=400)
    try:
        dur = max(5, min(24 * 60, int(d.get("dur", 60))))
    except (TypeError, ValueError):
        dur = 60
    aid, msg = await asyncio.to_thread(ops.agenda_add, tit, q, "compromisso", dur, str(d.get("local") or ""), "", "", "celular", None, "",
                                       d.get("prioridade", 2))
    if not aid:
        return web.json_response({"ok": False, "erro": msg})
    it = next((i for i in ops.agenda_all() if i["id"] == aid), None)
    return web.json_response({"ok": True, "msg": msg, "item": it})


async def cam(req):
    caminho = CAMS.get(req.match_info.get("nome", ""))
    if caminho is None:
        return web.json_response({"erro": "câmera desconhecida"}, status=404)
    try:
        dados = await asyncio.to_thread(lambda: open(caminho, "rb").read())
        idade = max(0.0, time.time() - os.path.getmtime(caminho))
    except OSError:
        return web.json_response({"erro": "sem imagem"}, status=404)
    return web.Response(body=dados, content_type="image/jpeg",
                        headers={"Cache-Control": "no-store", "X-Idade": f"{idade:.1f}", "Access-Control-Expose-Headers": "X-Idade"})


async def painel(req):
    try:
        d = await asyncio.to_thread(lambda: json.load(open(PAINEL)))
    except Exception:
        return web.json_response({"erro": "painel indisponível"}, status=503)
    if not isinstance(d, dict):
        return web.json_response({"erro": "painel inválido"}, status=503)
    return web.json_response({k: d[k] for k in PAINEL_CHAVES if k in d}, headers={"Cache-Control": "no-store"})


_vnc_proc = {"p": None}


async def _vnc_pronto():
    async def tenta():
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(*VNC), 1)
            w.close()
            return True
        except Exception:
            return False
    if await tenta():
        return True
    if not subprocess.run(["sh", "-c", "command -v wayvnc"], capture_output=True).stdout:
        return False
    _vnc_proc["p"] = subprocess.Popen(["wayvnc", "--max-fps=" + os.environ.get("FRIDAY_VNC_FPS", "60"), VNC[0], str(VNC[1])], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        await asyncio.sleep(0.2)
        if await tenta():
            return True
    return False


async def vnc(req):
    if not await _vnc_pronto():
        return web.json_response({"erro": "wayvnc indisponível (sudo pacman -S wayvnc)"}, status=503)
    ws = web.WebSocketResponse(protocols=("binary",), max_msg_size=16 << 20)
    await ws.prepare(req)
    try:
        r, w = await asyncio.open_connection(*VNC)
    except Exception:
        await ws.close()
        return ws

    async def tcp_para_ws():
        try:
            while True:
                b = await r.read(65536)
                if not b:
                    break
                await ws.send_bytes(b)
        except Exception:
            pass
        await ws.close()

    t = asyncio.create_task(tcp_para_ws())
    try:
        async for m in ws:
            if m.type in (WSMsgType.BINARY, WSMsgType.TEXT):
                w.write(m.data if m.type == WSMsgType.BINARY else m.data.encode())
                await w.drain()
    finally:
        t.cancel()
        w.close()
    return ws


def _ips():
    return ["0.0.0.0"]


async def dev_get(req):
    """Histórico e estado do MODO DEV do PC (eventos de voz, cérebro, Claude CLI, câmeras e tempos)."""
    try:
        import dev as _dev
        n = max(10, min(400, int(req.query.get("n", "150"))))
        return web.json_response({"ok": True, "on": bool(_dev.estado.get("on")), "itens": _dev.historico(n)},
                                 headers={"Cache-Control": "no-store"})
    except Exception as e:
        return web.json_response({"ok": False, "erro": str(e)[:120], "itens": []}, status=503)


async def ide_post(req):
    """Operações do IDE do MODO DEV (estado, arvore, ler, diff, enviar, parar, nova_sessao, modelo, abrir_projeto)."""
    ide = _ctx.get("ide")
    if ide is None:
        return web.json_response({"ok": False, "erro": "IDE indisponível"}, status=503)
    try:
        d = await req.json()
    except Exception:
        return web.json_response({"ok": False, "erro": "JSON inválido"}, status=400)
    respostas = []
    async def _resp(r):
        respostas.append(r)
    await ide.tratar(d, _resp)
    return web.json_response({"ok": True, "respostas": respostas, "estado": ide.estado_dict()},
                             headers={"Cache-Control": "no-store"})


def criar_app(ctx):
    _ctx.update(ctx)
    config()
    import sync_mesh
    app = web.Application(middlewares=[_auth], client_max_size=200 << 20)
    app.add_routes([web.get("/api/ping", ping), web.get("/api/estado", estado), web.get("/ws", ws_handler),
                    web.post("/api/audio", audio), web.post("/api/foto", foto), web.post("/api/anexo", anexo),
                    web.get("/api/tela", tela), web.post("/api/acao", acao), web.get("/vnc", vnc),
                    web.get("/api/aprovacoes", aprovacoes_get), web.post("/api/aprovacoes", aprovacoes_post),
                    web.get("/api/historico", historico), web.get("/api/status", status), web.post("/api/cmd", cmd), web.post("/api/pedido", pedido),
                    web.get("/api/cam/{nome}", cam), web.get("/api/painel", painel),
                    web.get("/api/agenda", agenda_get), web.post("/api/agenda/sync", agenda_sync), web.post("/api/agenda/add", agenda_add), web.post("/api/stt", stt),
                    web.post("/api/aprimorar", aprimorar),
                    web.get("/api/dev", dev_get), web.post("/api/ide", ide_post),
                    web.get("/api/mesh/info", sync_mesh.handle_mesh_info),
                    web.get("/api/mesh/peers", sync_mesh.handle_mesh_peers),
                    web.post("/api/mesh/sync", sync_mesh.handle_mesh_sync)])
    return app


async def iniciar(ctx):
    """ctx: estado(), texto(txt, files), fala(txt), ligar(on), pare(), acao(dict)->(ok,msg), foto(path), stt_prompt(),
    aprovacoes()->[ITEM], resolver(id, decisao, texto) async->(ok,msg,item), historico(n)->[{role,text,t}]."""
    app = criar_app(ctx)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    for ip in _ips():
        try:
            await web.TCPSite(runner, ip, PORT).start()
            print(f"remoto: http://{ip}:{PORT}", flush=True)
        except OSError as e:
            print("remoto: não abriu em", ip, e, flush=True)
    try:
        import sync_mesh
        sync_mesh.iniciar_mesh()
    except Exception as e:
        print("[MESH] Erro ao iniciar sincronizador:", e, flush=True)
