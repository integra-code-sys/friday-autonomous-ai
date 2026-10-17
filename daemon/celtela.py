"""Tela do CELULAR ao vivo no holograma (60 fps): o app F.R.I.D.A.Y. 2.3+ transmite H.264 (MediaProjection) na porta 8792;
aqui um relay recebe, empacota em MPEG-TS (ffmpeg -c copy, sem recodificar) e serve em tcp://127.0.0.1:8793 para o
CelularHolo.qml (MediaPlayer). O relay só puxa o vídeo do celular enquanto a interface está conectada (economia de bateria):
cada conexão da interface abre uma conexão nova com o celular, que manda SPS/PPS + quadro-chave (o vídeo começa limpo).
Toques do holograma chegam normalizados (0..1) e viram pixels reais do celular (real())."""
import json
import os
import socket
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PORTA_LOCAL = 8793
URL = f"tcp://127.0.0.1:{PORTA_LOCAL}"
AUTO_FECHAR = 180          # s sem mostrar(): fecha o holograma e para o stream
FFMPEG = ["ffmpeg", "-loglevel", "error", "-fflags", "+genpts+nobuffer", "-flags", "low_delay", "-use_wallclock_as_timestamps", "1",
          "-probesize", "32768", "-analyzeduration", "0", "-f", "h264", "-i", "-", "-c", "copy", "-f", "mpegts",
          "-muxdelay", "0", "-muxpreload", "0", "-flush_packets", "1", "pipe:1"]

_lock = threading.RLock()          # estado (info/relay)
_ini = threading.Lock()            # um (re)início por vez
_st = {"info": None, "relay": None, "visto": 0.0, "ja": False, "falhou_ate": 0.0, "erro": "", "vigia": None, "reabriu": 0.0}
_ultimo = {}                       # último pedido de iniciar (fps/largura/kbps): o relay reabre a transmissão igual


def _cel():
    import celular
    return celular


def _token():
    return json.load(open(os.path.join(HERE, "..", "memory", "remoto.json")))["token"]


def _pub(msg):
    try:
        from prom_ops import _daemon_send
        _daemon_send(msg)
    except Exception:
        pass


def real():
    """(largura, altura) reais do celular em pixels (as mesmas coordenadas de tocar/arrastar)."""
    c = _cel()
    try:
        if not (c._pv.get("w") and c._pv.get("h")):
            c.ponte_ok(cache=0)
    except Exception:
        pass
    return (c._pv.get("w") or 1272), (c._pv.get("h") or 2772)


# ------------------------------------------------------------------ relay celular -> ffmpeg -> interface
class _Sessao(threading.Thread):
    """uma conexão da interface: puxa o H.264 do celular e devolve MPEG-TS para ela."""

    def __init__(self, relay, cli):
        super().__init__(daemon=True)
        self.relay, self.cli, self.fim = relay, cli, threading.Event()
        self.cel = self.ff = None

    def fechar(self):
        self.fim.set()
        for s in (self.cel, self.cli):
            try:
                s.close()
            except Exception:
                pass
        if self.ff is not None:
            try:
                self.ff.kill()
                self.ff.wait(timeout=2)
            except Exception:
                pass

    def _conectar(self):
        """conecta no celular (backoff 1-3 s); se a transmissão caiu lá (notificação/60 s sem cliente), pede de novo."""
        atraso, falhas = 1.0, 0
        while not self.fim.is_set():
            try:
                s = socket.create_connection((self.relay.host, self.relay.porta), timeout=4)
                s.sendall((self.relay.tok + "\n").encode())
                s.settimeout(6)
                return s
            except OSError:
                falhas += 1
                if falhas >= 3:
                    self.relay.reabrir()
                    falhas = 0
                self.fim.wait(atraso)
                atraso = min(3.0, atraso + 1.0)
        return None

    def _saida(self):
        fd = self.ff.stdout.fileno()
        try:
            while not self.fim.is_set():
                b = os.read(fd, 65536)
                if not b:
                    break
                self.cli.sendall(b)
        except Exception:
            pass
        self.fechar()                          # interface saiu (ou ffmpeg morreu): ela reconecta e começa de novo

    def run(self):
        try:
            self.cli.settimeout(3)             # interface travada não segura o celular
            self.cel = self._conectar()
            if self.cel is None:
                return
            self.ff = subprocess.Popen(FFMPEG, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            threading.Thread(target=self._saida, daemon=True).start()
            while not self.fim.is_set():
                b = self.cel.recv(65536)
                if not b:
                    break                      # celular fechou: a interface reconecta e a próxima sessão reabre
                self.ff.stdin.write(b)
        except Exception:
            pass
        finally:
            self.fechar()


class _Relay(threading.Thread):
    """escuta 127.0.0.1:8793; atende uma interface por vez (a nova substitui a antiga)."""

    def __init__(self, host, porta, tok):
        super().__init__(daemon=True)
        self.host, self.porta, self.tok = host, int(porta), tok
        self.parar = threading.Event()
        self.sessao = None
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", PORTA_LOCAL))       # erro aqui (porta ocupada) sobe para iniciar()
        self.srv.listen(4)
        self.srv.settimeout(0.5)

    def reabrir(self):
        if time.time() - _st["reabriu"] < 15:
            return
        _st["reabriu"] = time.time()
        try:
            r = _cel().ponte("/transmitir", timeout=25, **_ultimo)
            if r.get("ok"):
                self.porta = int(r.get("porta") or self.porta)
        except Exception:
            pass

    def run(self):
        while not self.parar.is_set():
            try:
                cli, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            cli.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if self.sessao is not None:
                self.sessao.fechar()
            self.sessao = _Sessao(self, cli)
            self.sessao.start()
        self.encerrar()

    def encerrar(self):
        self.parar.set()
        if self.sessao is not None:
            self.sessao.fechar()
        try:
            self.srv.close()
        except Exception:
            pass


# ------------------------------------------------------------------ API
def ativo():
    r = _st["relay"]
    return _st["info"] is not None and r is not None and r.is_alive()


def iniciar(fps=60, largura=720, kbps=6000):
    """pede a transmissão ao celular (aceita sozinho o diálogo de captura) e garante o relay. Idempotente."""
    with _lock:
        if ativo():
            return dict(_st["info"])
        _ultimo.update(fps=int(fps), w=int(largura), kbps=int(kbps))
        r = _cel().ponte("/transmitir", timeout=25, **_ultimo)
        if not isinstance(r, dict) or not r.get("ok"):
            return {"ok": False, "erro": (r or {}).get("erro", "celular não iniciou a transmissão") if isinstance(r, dict) else "resposta inválida"}
        host = _cel().config()["host"]
        rel = _Relay(host, int(r.get("porta") or 8792), _token())
        rel.start()
        rw, rh = real()
        real_h = int(r.get("h") or round(largura * rh / max(1, rw)))
        _st["info"] = {"ok": True, "url": URL, "w": int(r.get("w") or largura), "h": real_h, "fps": int(r.get("fps") or fps)}
        _st["ja"] = True
        return dict(_st["info"])


def parar():
    with _lock:
        rel, _st["relay"], _st["info"] = _st["relay"], None, None
        if rel is not None:
            rel.encerrar()
    try:
        _cel().ponte("/parar_transmissao", timeout=6)
    except Exception:
        pass
    return {"ok": True}


def _publica(x=None, y=None):
    i = _st["info"]
    if not i:
        return
    _pub({"type": "cel_tela", "on": True, "url": i["url"], "w": i["w"], "h": i["h"], "fps": i["fps"]})
    if x is not None and y is not None:
        W, H = real()
        _pub({"type": "cel_toque", "x": max(0.0, min(1.0, float(x) / W)), "y": max(0.0, min(1.0, float(y) / H))})


def _vigiar():
    """fecha sozinho se ninguém chamar mostrar() por AUTO_FECHAR s."""
    while _st["info"] is not None:
        time.sleep(5)
        if _st["info"] is not None and time.time() - _st["visto"] > AUTO_FECHAR:
            fechar()
    _st["vigia"] = None


def _religa(x, y):
    try:
        r = iniciar(**{"fps": _ultimo.get("fps", 60), "largura": _ultimo.get("w", 720), "kbps": _ultimo.get("kbps", 6000)})
        if r.get("ok"):
            _publica(x, y)
            _garante_vigia()
        else:
            _st["falhou_ate"], _st["erro"] = time.time() + 60, r.get("erro", "")
    except Exception as e:
        _st["falhou_ate"], _st["erro"] = time.time() + 60, str(e)[:120]
    finally:
        _ini.release()


def _garante_vigia():
    if _st["vigia"] is None or not _st["vigia"].is_alive():
        _st["vigia"] = threading.Thread(target=_vigiar, daemon=True)
        _st["vigia"].start()


def mostrar(x=None, y=None):
    """tela do celular ao vivo no holograma (+ anel em x,y: pixels reais). 1ª vez síncrona (erro -> quem chamou usa o print);
    depois religa em segundo plano, sem travar quem chamou."""
    _st["visto"] = time.time()
    if not ativo():
        if time.time() < _st["falhou_ate"]:
            raise RuntimeError("transmissão do celular indisponível: " + _st["erro"])
        if _st["ja"]:
            if _ini.acquire(blocking=False):
                threading.Thread(target=_religa, args=(x, y), daemon=True).start()
            return {"ok": True, "iniciando": True}
        with _ini:
            if not ativo():
                try:
                    r = iniciar()
                except Exception as e:
                    _st["falhou_ate"], _st["erro"] = time.time() + 60, str(e)[:120]
                    raise
                if not r.get("ok"):
                    _st["falhou_ate"], _st["erro"] = time.time() + 60, r.get("erro", "")
                    raise RuntimeError("transmissão do celular: " + r.get("erro", ""))
    _garante_vigia()
    _publica(x, y)
    return dict(_st["info"] or {})


def fechar():
    _pub({"type": "cel_tela", "on": False})
    _pub({"type": "holo", "op": "clear"})             # some também a imagem parada antiga do holograma (modo sem stream)
    return parar()
