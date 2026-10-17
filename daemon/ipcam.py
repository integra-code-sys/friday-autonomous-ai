"""Câmera IP PTZ Wi-Fi (ML-310 / Yoosee-Gwell) da Sexta-feira — protocolo MEDIDO nesta câmera (14/10/2026):

- Vídeo: RTSP sem senha em rtsp://IP:554/onvif1 (1280x720 ~15 fps) e /onvif2 (640x360). SÓ UDP (TCP interleaved
  responde lixo) -> o UFW precisa liberar UDP vindo da câmera (regra "friday-cam-rtp"). Uma sessão por vez: o firmware
  reiniciou quando abrimos sessões em sequência sem TEARDOWN.
- Motor: ONVIF na porta 5000, só /onvif/ptz_service responde, SEM autenticação, perfil "IPCProfilesToken0".
  ContinuousMove funciona mas gira só ~1 s por comando (renovar a cada 0,5 s p/ movimento contínuo); Stop/GetStatus/GetNodes/device_service fecham a conexão -> parar = ContinuousMove(0,0).
  Sem leitura de posição: quem estima pan/tilt é o ptz.py (tempo x velocidade calibrada).
- Rede: em modo AP a câmera cria "GW_AP_<id>" (10.108.119.1); o PC entra nela pelo wlan0 (conexão NM "friday-cam",
  never-default, a internet segue pelo cabo). Se ela for para o Wi-Fi de casa, a descoberta acha pelo 554/5000.
Config em memory/camera_ptz.json (0600).
"""
import base64, hashlib, json, os, re, socket, subprocess, threading, time
import concurrent.futures as cf
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONF = os.path.join(ROOT, "memory", "camera_ptz.json")
LOG = "/tmp/friday-ptz.log"
PERFIL_PADRAO = "IPCProfilesToken0"
INTERVALO_MIN = 0.15            # s entre dois POSTs: o firmware barato trava com rajada


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 2_000_000:
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ configuração
def ler_conf():
    try:
        return json.load(open(CONF))
    except Exception:
        return {}


def salvar_conf(**kw):
    c = ler_conf()
    c.update({k: v for k, v in kw.items() if v is not None})
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONF)
    return c


# ------------------------------------------------------------------ rede
def _ips_locais():
    """[(dev, ip_local, prefixo /24)] das interfaces IPv4 ativas."""
    out = []
    try:
        txt = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=2).stdout
        for ln in txt.splitlines():
            m = re.search(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/", ln)
            if m and not re.match(r"(lo|tailscale|docker|br-|veth|virbr)", m.group(1)):
                dev = m.group(1)
                ip = m.group(2)
                pref = ip.rsplit(".", 1)[0] + "."
                out.append((dev, ip, pref))
    except Exception:
        pass
    return out


def _redes_locais():
    """[(dev, prefixo /24)] das interfaces IPv4."""
    return [(dev, pref) for dev, _, pref in _ips_locais()]


def _porta(ip, p, t=0.35):
    s = socket.socket()
    s.settimeout(t)
    try:
        if s.connect_ex((ip, p)) == 0:
            return True
    except Exception:
        pass
    finally:
        s.close()
    for _, loc_ip, _ in _ips_locais():
        s = socket.socket()
        s.settimeout(t)
        try:
            s.bind((loc_ip, 0))
            if s.connect_ex((ip, p)) == 0:
                return True
        except Exception:
            pass
        finally:
            s.close()
    return False


def rtsp_status(ip, caminho="onvif1", t=2.0):
    """código da resposta ao DESCRIBE (200 = vídeo liberado; 401 = pede senha; 405 = câmera esperando o app)."""
    for bind_ip in [None] + [loc[1] for loc in _ips_locais()]:
        s = None
        try:
            s = socket.socket()
            s.settimeout(t)
            if bind_ip:
                try:
                    s.bind((bind_ip, 0))
                except Exception:
                    continue
            s.connect((ip, 554))
            s.sendall(f"DESCRIBE rtsp://{ip}:554/{caminho} RTSP/1.0\r\nCSeq: 2\r\nAccept: application/sdp\r\n\r\n".encode())
            d = s.recv(300).decode(errors="ignore")
            m = re.match(r"RTSP/1\.0 (\d+)", d)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
    return 0


def candidatos():
    """IPs onde pode estar a câmera: o salvo, o .1 de redes que não são a de casa (AP GW_AP_*), e varredura 554."""
    c = ler_conf()
    vistos, lista = set(), []

    def add(ip):
        if ip and ip not in vistos:
            vistos.add(ip); lista.append(ip)
    add(c.get("ip"))
    redes = _redes_locais()
    casa = c.get("rede_casa", "192.168.15.")
    for dev, pref in redes:
        if pref != casa:
            add(pref + "1")                                  # AP da câmera: ela é o gateway da rede dela
    if any(_porta(ip, 554) for ip in lista):
        return [ip for ip in lista if _porta(ip, 554)]
    # varre só a rede de casa: fora dela (PC levado para outro lugar) não procura câmera de terceiros; ao voltar acha sozinha
    ips = list(dict.fromkeys(pref + str(i) for _, pref in redes if pref == casa for i in range(2, 255)))
    with cf.ThreadPoolExecutor(96) as ex:
        achados = [ip for ip, ok in zip(ips, ex.map(lambda ip: _porta(ip, 554) and _porta(ip, 5000), ips)) if ok]
    return achados


# ------------------------------------------------------------------ câmera
class CameraIP:
    def __init__(self, ip, perfil=None, usuario="admin", senha=""):
        c = ler_conf()
        self.ip = ip
        self.perfil = perfil or c.get("perfil") or PERFIL_PADRAO
        self.usuario, self.senha = usuario or "admin", senha or ""
        self.ptz_url = f"http://{ip}:5000/onvif/ptz_service"
        self.rtsp = f"rtsp://{ip}:554/onvif1"
        self.rtsp_sub = f"rtsp://{ip}:554/onvif2"            # 640x360 14 fps: o movimento aparece em 0,65 s (o principal: 1,45 s)
        self.inv_pan = bool(c.get("inverter_pan", False))
        self.inv_tilt = bool(c.get("inverter_tilt", False))
        self.reenvio = float(c.get("reenvio_s", 0.5) or 0) # MEDIDO: cada ContinuousMove gira só ~1 s e para sozinho -> renovar a cada 0,5 s
        self.ok = False
        self.motor = False
        self.ultimo_erro = ""
        self._cmd = None
        self._cv = threading.Condition()
        self._ult_post = 0.0
        self._mov_ate = 0.0
        self.mov_fim = 0.0                                   # instante em que o último movimento terminou de fato
        self._thread = None                                  # a thread do motor só nasce no 1º comando (busca não vaza threads)
        self._falhas = 0
        self.hist = []                                       # [[t_liga, t_desliga|None, vx, vy]] já com a inversão: o ptz.py prevê o giro
        self.vel = (0.0, 0.0)                                # velocidade contínua em curso (modo mover)
        self.bind_ip = None
        for _, loc_ip, _ in _ips_locais():
            s = socket.socket()
            s.settimeout(0.25)
            try:
                s.bind((loc_ip, 0))
                if s.connect_ex((ip, 554)) == 0:
                    self.bind_ip = loc_ip
                    break
            except Exception:
                pass
            finally:
                s.close()

    # ---- SOAP cru (requests mandava cabeçalhos que esse gSOAP às vezes recusa)
    def _sec(self):
        if not self.senha:
            return ""
        nonce = os.urandom(16)
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        dig = base64.b64encode(hashlib.sha1(nonce + created.encode() + self.senha.encode()).digest()).decode()
        return ('<s:Header><Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
                f'<UsernameToken><Username>{self.usuario}</Username><Password Type="http://docs.oasis-open.org/wss/2004/01/'
                f'oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{dig}</Password><Nonce EncodingType="http://docs.oasis-open.org/'
                f'wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>'
                f'<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>'
                '</UsernameToken></Security></s:Header>')

    def _post(self, corpo, t=2.5):
        espera = INTERVALO_MIN - (time.time() - self._ult_post)
        if espera > 0:
            time.sleep(espera)
        env = ('<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
               f'xmlns:tt="http://www.onvif.org/ver10/schema">{self._sec()}<s:Body>{corpo}</s:Body></s:Envelope>').encode()
        req = (f"POST /onvif/ptz_service HTTP/1.1\r\nHost: {self.ip}:5000\r\nContent-Type: application/soap+xml; charset=utf-8\r\n"
               f"Content-Length: {len(env)}\r\nConnection: close\r\n\r\n").encode() + env
        self._ult_post = time.time()
        s = socket.socket()
        s.settimeout(t)
        if self.bind_ip:
            try:
                s.bind((self.bind_ip, 0))
            except Exception:
                pass
        s.connect((self.ip, 5000))
        try:
            s.sendall(req)
            d = b""
            while True:
                ch = s.recv(4096)
                if not ch:
                    break
                d += ch
        finally:
            s.close()
        txt = d.decode(errors="ignore")
        if " 200 " not in txt[:20] or "Fault" in txt:
            raise RuntimeError("PTZ: " + (re.sub(r"<[^>]+>", " ", txt)[:120].strip() or "conexão fechada sem resposta"))
        return txt

    def _vel(self, vx, vy):
        self._post(f'<ContinuousMove xmlns="http://www.onvif.org/ver20/ptz/wsdl"><ProfileToken>{self.perfil}</ProfileToken>'
                   f'<Velocity><tt:PanTilt x="{vx:.2f}" y="{vy:.2f}"/></Velocity></ContinuousMove>')

    def conectar(self):
        """vídeo (DESCRIBE 200) + motor (ContinuousMove 0,0 = parado, inofensivo)."""
        st = rtsp_status(self.ip)
        if st != 200:
            self.ok = False
            self.ultimo_erro = {405: "a câmera está no modo de configuração (abra-a uma vez no app Yoosee)",
                                401: "o vídeo pede senha", 0: "sem resposta no RTSP"}.get(st, f"RTSP respondeu {st}")
            return False
        try:
            self._vel(0, 0)
            self.motor = True
        except Exception as e:
            self.motor = False
            self.ultimo_erro = f"vídeo ok, motor sem resposta ({e})"
        self.ok = True
        return True

    # ---- motor (thread própria: quem chama nunca trava em rede)
    def pulso(self, vx, vy, dur):
        """gira com velocidade (vx, vy) em -1..1 por `dur` s e para. Um comando novo substitui o pendente."""
        if not (self.ok and self.motor):
            return False
        vx = -vx if self.inv_pan else vx
        vy = -vy if self.inv_tilt else vy
        dur = max(0.05, min(120.0, float(dur)))
        self._garantir_thread()
        with self._cv:
            self._cmd = ("pulso", max(-1.0, min(1.0, vx)), max(-1.0, min(1.0, vy)), dur)
            self._mov_ate = time.time() + dur + 0.3
            self._cv.notify()
        return True

    def _garantir_thread(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._worker, daemon=True, name="ptz-motor")
            self._thread.start()

    def mover(self, vx, vy):
        """giro CONTÍNUO até mover(0,0)/parar() (o worker renova o comando a cada 0,5 s). Para o rastreio em tempo real."""
        if not (self.ok and self.motor):
            return False
        vx = -vx if self.inv_pan else vx
        vy = -vy if self.inv_tilt else vy
        self._garantir_thread()
        with self._cv:
            self._cmd = ("mover", max(-1.0, min(1.0, vx)), max(-1.0, min(1.0, vy)))
            self._cv.notify()
        return True

    def _hist_liga(self, vx, vy):
        agora = time.time()
        if self.hist and self.hist[-1][1] is None:
            if (self.hist[-1][2], self.hist[-1][3]) == (vx, vy):
                return
            self.hist[-1][1] = agora
        self.hist.append([agora, None, vx, vy])
        if len(self.hist) > 300:
            del self.hist[:100]

    def _hist_desliga(self):
        if self.hist and self.hist[-1][1] is None:
            self.hist[-1][1] = time.time()

    def parar(self):
        self._garantir_thread()
        with self._cv:
            self._cmd = ("parar",)
            self._cv.notify()

    def movendo(self):
        return self.vel != (0.0, 0.0) or time.time() < self._mov_ate

    def _worker(self):
        prox = 0.0
        while True:
            with self._cv:
                if self._cmd is None:
                    espera = None if self.vel == (0.0, 0.0) else max(0.0, prox - time.time())
                    self._cv.wait(espera)
                cmd, self._cmd = self._cmd, None
            try:
                if cmd is None:                              # renovação do giro contínuo (cada comando gira só ~1 s)
                    if self.vel != (0.0, 0.0):
                        self._vel(*self.vel)
                        prox = time.time() + (self.reenvio or 0.5)
                    continue
                if cmd[0] == "mover":
                    _, vx, vy = cmd
                    if (vx, vy) == (0.0, 0.0) or (vx == 0 and vy == 0):
                        if self.vel != (0.0, 0.0) or (self.hist and self.hist[-1][1] is None):   # pulso interrompido também tem de parar (senão anda +1 s e o hist fica aberto)
                            self.vel = (0.0, 0.0)
                            self._parar_garantido()
                        continue
                    if (vx, vy) != self.vel:
                        self._vel(vx, vy)
                        self._hist_liga(vx, vy)
                        self.vel = (vx, vy)
                    prox = time.time() + (self.reenvio or 0.5)
                    self._mov_ate = time.time() + 1.0
                    self._falhas = 0
                    continue
                if cmd[0] == "pulso":
                    self.vel = (0.0, 0.0)
                    _, vx, vy, dur = cmd
                    fim = time.time() + dur
                    self._vel(vx, vy)
                    self._hist_liga(vx, vy)
                    prox_r = time.time() + self.reenvio if self.reenvio > 0 else None
                    interrompido = False
                    while time.time() < fim:
                        with self._cv:
                            if self._cmd is not None:
                                interrompido = True
                                break
                        if prox_r and time.time() >= prox_r:
                            self._vel(vx, vy); prox_r = time.time() + self.reenvio
                        time.sleep(0.02)
                    if interrompido and self._cmd is not None and self._cmd[0] in ("pulso", "mover"):
                        continue                         # o próximo comando já assume o motor
                self.vel = (0.0, 0.0)
                self._parar_garantido()
                self._falhas = 0
            except Exception as e:
                self.ultimo_erro = str(e)[:160]
                log("motor: " + self.ultimo_erro)
                if self.vel == (0.0, 0.0):
                    self._parar_garantido()              # ContinuousMove não para sozinho: insiste no (0,0)
                self._falhas += 1
                if self._falhas >= 6:                    # perto do fim de curso o firmware recusa uns segundos (medido): só desiste com muitas
                    self.vel = (0.0, 0.0)
                    self._parar_garantido()
                    self.motor = False                   # a busca revalida a câmera
                    log("motor marcado como sem resposta")

    def _parar_garantido(self):
        for tent in range(4):
            try:
                self._vel(0, 0)
                break
            except Exception as e:
                log(f"parar (tentativa {tent + 1}): {e}")
                time.sleep(0.3)
        self._hist_desliga()
        self.mov_fim = time.time()
        self._mov_ate = 0.0


# ------------------------------------------------------------------ singleton com descoberta
_cam = None
_lock = threading.Lock()
_ult_busca = [0.0]
_ult_erro = [""]


def status():
    if _cam is not None and _cam.ok:
        return f"câmera PTZ em {_cam.ip}: vídeo ok, motor {'ok' if _cam.motor else 'sem resposta'}"
    return "câmera PTZ indisponível" + (f": {_ult_erro[0]}" if _ult_erro[0] else "")


def obter(forcar=False, intervalo=20.0):
    """CameraIP conectada ou None. Procura de novo no máximo a cada `intervalo` s (a busca roda fora do laço de vídeo)."""
    global _cam
    with _lock:
        if _cam is not None and _cam.ok and not forcar:
            return _cam
        if not forcar and time.time() - _ult_busca[0] < intervalo:
            return None
        _ult_busca[0] = time.time()
        c = ler_conf()
        for ip in candidatos():
            cam = _cam if (_cam is not None and _cam.ip == ip) else CameraIP(ip, c.get("perfil"), c.get("usuario", "admin"), c.get("senha", ""))
            if cam.conectar():
                if _cam is not cam:
                    log(f"conectada em {ip} (motor {'ok' if cam.motor else 'NÃO'})")
                salvar_conf(ip=ip, perfil=cam.perfil, rtsp=cam.rtsp, rtsp_sub=cam.rtsp_sub)
                _cam = cam
                _ult_erro[0] = ""
                return cam
            if cam.ultimo_erro != _ult_erro[0]:
                log(f"{ip}: {cam.ultimo_erro}")
            _ult_erro[0] = cam.ultimo_erro
        if not _ult_erro[0]:
            _ult_erro[0] = "não achei a câmera na rede"
        return None


def perdeu():
    """o laço de vídeo avisa que o RTSP caiu: na próxima obter() revalida."""
    global _cam
    with _lock:
        if _cam is not None:
            _cam.ok = False


def atual():
    """câmera já conectada, sem tocar na rede (para laços de vídeo/motor)."""
    return _cam if (_cam is not None and _cam.ok) else None


_busca_on = [False]


def iniciar_busca(periodo=20.0):
    """thread que (re)encontra a câmera a cada `periodo` s enquanto ela não estiver conectada."""
    if _busca_on[0]:
        return
    _busca_on[0] = True

    def laco():
        while True:
            try:
                c = atual()
                if c is None or not c.motor:
                    obter(forcar=True)
            except Exception as e:
                log(f"busca: {e!r}")
            time.sleep(periodo)
    threading.Thread(target=laco, daemon=True, name="ptz-busca").start()
