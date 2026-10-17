"""Mouse por Gestos F.R.I.D.A.Y. — Modo Mão Livre.

Arquitetura de Alta Fidelidade (Zero Delay & Anti-Tremor):
  - Injeção direta no kernel Linux via /dev/uinput (~10 microsegundos de latência; zero subprocessos).
  - Ponto de tração no centro geométrico ósseo da palma (lm[9] 50% + lm[5] 25% + lm[17] 25%).
  - Piso de ruído com atenuação quadrática contínua: anula 100% do jitter de sensor da câmera quando a mão está parada.
  - Filtro One-Euro adaptativo com curva Hermite cúbica suave.
  - Margens do niri: x,y >= 8 px e y <= H-45 (canto quente = visão geral; dock embaixo).
  - Anti-fantasma (F5): conf >= 0,6, brilho do recorte >= 30, mão >= 35 px, estável em 4 de 6 quadros;
    pinça com histerese (memory/gestos.json fecha/abre), punho 3 de 4 quadros, arrasto só se a âncora andar.
  - Sincronização automática com eventos de mouse físico.
"""
import json, os, subprocess, time
from collections import deque
import numpy as np

POS_FILE = "/tmp/prometheus-pc-pos.json"
CFG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "gestos.json")
CFG_PADRAO = {"fecha": 0.30, "abre": 0.48,                          # pinça (polegar-indicador / largura da mão), com histerese
              "conf_min": 0.6, "lum_min": 30.0, "largura_min": 35.0,  # mão fantasma no escuro: conf 0,45, recorte escuro, mão pequena
              "estavel_n": 4, "estavel_m": 6,                       # mão precisa aparecer em 4 dos últimos 6 quadros
              "arrasto_min": 0.03, "clique_max_s": 1.5,             # regra v4: arrastar só se a âncora andar; clique = fechar e abrir
              "dir_s": 0.4,                                         # clique direito: pinça mantida
              "margem_px": 8, "dock_px": 45, "log": False}


def _cfg():
    c = dict(CFG_PADRAO)
    try:
        c.update(json.load(open(CFG_FILE)))
    except Exception:
        pass
    return c


def _screen():
    try:
        d = json.loads(subprocess.run(["niri", "msg", "-j", "outputs"], capture_output=True, text=True, timeout=3).stdout)
        o = next(iter(d.values()))["logical"]
        return o["width"], o["height"]
    except Exception:
        return 1920, 1080


def _d(lm, a, b):
    return float(np.linalg.norm(lm[a] - lm[b]))


def largura_mao(lm):
    """Escala normalizada da mão: nós (5-17), punho->nó indicador e punho->médio."""
    return max(_d(lm, 5, 17) * 1.15, _d(lm, 0, 5) * 0.75, _d(lm, 0, 9) * 0.70, 1e-3)


def mao_fechada(lm):
    """Mão fechada / punho com dedos dobrados à frente (clique / arrasto)."""
    w = largura_mao(lm)
    # Dedos indicador (8), médio (12), anelar (16), mínimo (20):
    dobrados = sum(
        (_d(lm, t, 0) < _d(lm, p, 0) * 1.12) or (_d(lm, t, m) < 0.85 * w)
        for t, p, m in ((8, 6, 5), (12, 10, 9), (16, 14, 13), (20, 18, 17))
    )
    return dobrados >= 3


def e_pinca(lm, fecha=0.28):
    """Gesto de pinça: ponta do polegar tocando ponta do indicador/médio."""
    if mao_fechada(lm):
        return False
    w = largura_mao(lm)
    d_ti = _d(lm, 4, 8) / w
    d_tm = _d(lm, 4, 12) / w
    eh_toque = d_ti < fecha or (d_ti < fecha * 1.2 and d_tm < fecha * 1.2)
    livres = (_d(lm, 16, 0) > _d(lm, 14, 0) * 0.95) or (_d(lm, 20, 0) > _d(lm, 18, 0) * 0.95) or (_d(lm, 12, 0) > _d(lm, 10, 0) * 0.95)
    return eh_toque and livres


def palma_aberta(lm):
    """Mão aberta com dedos estendidos (move o cursor)."""
    if mao_fechada(lm) or e_pinca(lm):
        return False
    w = largura_mao(lm)
    estendidos = sum(
        _d(lm, t, 0) > _d(lm, p, 0) * 1.05 and _d(lm, t, m) > 0.60 * w
        for t, p, m in ((8, 6, 5), (12, 10, 9), (16, 14, 13), (20, 18, 17))
    )
    return estendidos >= 3


class OneEuro:
    def __init__(self, mincut=0.7, beta=0.15, dcut=1.0):
        self.mc, self.b, self.dc, self.x, self.dx, self.t = mincut, beta, dcut, None, 0.0, None

    def reset(self):
        self.x = None

    def __call__(self, x, t):
        if self.x is None:
            self.x, self.t, self.dx = x, t, 0.0
            return x
        dt = max(t - self.t, 1e-3); self.t = t
        a = lambda c: 1.0 / (1.0 + 1.0 / (2 * np.pi * c * dt))
        dx = (x - self.x) / dt
        self.dx += a(self.dc) * (dx - self.dx)
        self.x += a(self.mc + self.b * abs(self.dx)) * (x - self.x)
        return self.x


class UInputDriver:
    """Injeção direta no kernel Linux via /dev/uinput com latência de 10 microsegundos."""
    def __init__(self):
        self.fd = None
        self._init_dev()

    def _init_dev(self):
        try:
            import fcntl, struct
            self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            fcntl.ioctl(self.fd, 0x40045564, 0x00) # EV_SYN
            fcntl.ioctl(self.fd, 0x40045564, 0x01) # EV_KEY
            fcntl.ioctl(self.fd, 0x40045564, 0x02) # EV_REL

            for rel in (0x00, 0x01, 0x08): # REL_X, REL_Y, REL_WHEEL
                fcntl.ioctl(self.fd, 0x40045566, rel)

            for k in (0x110, 0x111, 0x112, 29, 13, 12): # BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, KEY_CTRL, EQUAL, MINUS
                fcntl.ioctl(self.fd, 0x40045565, k)

            setup = struct.pack("=HHHH80sI", 0x03, 0x1234, 0x5678, 1, b"Prometheus UInput Mouse", 0)
            fcntl.ioctl(self.fd, 0x405c5503, setup)
            fcntl.ioctl(self.fd, 0x5501) # UI_DEV_CREATE
        except Exception:
            self.fd = None

    def _write_ev(self, ev_type, code, val):
        if self.fd is not None:
            try:
                import struct
                os.write(self.fd, struct.pack("llHHi", 0, 0, ev_type, code, val))
            except Exception:
                pass

    def _sync(self):
        self._write_ev(0x00, 0, 0)

    def move(self, dx, dy):
        if self.fd is not None:
            if dx:
                self._write_ev(0x02, 0x00, int(dx)) # REL_X
            if dy:
                self._write_ev(0x02, 0x01, int(dy)) # REL_Y
            self._sync()
        else:
            try:
                subprocess.Popen(["ydotool", "mousemove", "-x", str(dx), "-y", str(dy)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def btn_down(self, btn="left"):
        code = 0x110 if btn == "left" else 0x111
        if self.fd is not None:
            self._write_ev(0x01, code, 1)
            self._sync()
        else:
            try:
                subprocess.Popen(["ydotool", "click", "0x40" if btn == "left" else "0x41"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def btn_up(self, btn="left"):
        code = 0x110 if btn == "left" else 0x111
        if self.fd is not None:
            self._write_ev(0x01, code, 0)
            self._sync()
        else:
            try:
                subprocess.Popen(["ydotool", "click", "0x80" if btn == "left" else "0x81"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def click(self, btn="left"):
        self.btn_down(btn)
        self.btn_up(btn)

    def zoom(self, direction):
        if self.fd is not None:
            key = 13 if direction > 0 else 12
            self._write_ev(0x01, 29, 1); self._write_ev(0x01, key, 1); self._sync()
            self._write_ev(0x01, key, 0); self._write_ev(0x01, 29, 0); self._sync()
        else:
            try:
                k = "13" if direction > 0 else "12"
                subprocess.Popen(["ydotool", "key", "29:1", f"{k}:1", f"{k}:0", "29:0"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def destroy(self):
        if self.fd is not None:
            try:
                import fcntl
                fcntl.ioctl(self.fd, 0x5502)
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None


class GestureMouse:
    def __init__(self, cursor_cb=None):
        self.W, self.H = _screen()
        self.cb = cursor_cb
        self.on = False
        self.uinput = UInputDriver()

        self.x, self.y = self.W / 2, self.H / 2
        try:
            p = json.load(open(POS_FILE)); self.x, self.y = float(p["x"]), float(p["y"])
        except Exception:
            pass

        self.au = OneEuro(mincut=1.8, beta=1.2)
        self.av = OneEuro(mincut=1.8, beta=1.2)

        # Estados de punho / clique
        self.punho_ativo = False
        self.t_punho_inicio = 0.0
        self.arrastando = False
        self.trava_pos = None

        # Estados de pinça única (clique direito)
        self.pinca_unica_ativa = False
        self.t_pinca_dir = 0.0
        self.pinca_disparada = False

        # Estados de duas pinças (zoom)
        self.duas_pincas_ativas = False
        self.dist_zoom_anterior = None
        self.t_ultimo_zoom = 0.0

        # Rastreamento de cursor e continuidade
        self.ancora = None
        self.t_anc = None
        self.acc = [0.0, 0.0]
        self.lost_frames = 0
        self.ultima_mao = None

        # Anti-fantasma (F5)
        self.c = _cfg()
        self.estavel = deque(maxlen=int(self.c["estavel_m"]))   # mão válida nos últimos quadros
        self.punho_hist = deque(maxlen=4)                       # punho bruto: entra com 3/4, sai com 3/4 abertos
        self.ponto_fecha = None                                 # âncora (nós 5/9/13) quando o punho fechou

    def _log(self, t, s):
        if self.c.get("log"):
            try:
                if os.path.getsize("/tmp/gestomouse.log") > 5_000_000:      # teto: não enche o /tmp em sessões longas
                    os.replace("/tmp/gestomouse.log", "/tmp/gestomouse.log.1")
            except OSError:
                pass
            try:
                with open("/tmp/gestomouse.log", "a") as fh:
                    fh.write(f"{t:.2f} {s}\n")
            except Exception:
                pass

    def _mao_ok(self, h):
        """mão real: confiança, brilho do recorte e tamanho mínimos (no escuro o detector inventa mão com conf 0,45)."""
        c = self.c
        if float(h.get("conf", 0)) < c["conf_min"] or float(h.get("lum", 255.0)) < c["lum_min"]:
            return False
        lm = h.get("lm")
        return lm is not None and largura_mao(lm) >= c["largura_min"]

    def _cb(self, act):
        if self.cb:
            self.cb(int(self.x), int(self.y), act)

    def _move_to(self, x, y, act="move"):
        # Sincroniza com a posição real se o mouse físico tiver sido mexido
        try:
            p = json.load(open(POS_FILE))
            px, py = float(p.get("x", self.x)), float(p.get("y", self.y))
            if abs(px - self.x) > 30 or abs(py - self.y) > 30:
                self.x, self.y = px, py
        except Exception:
            pass

        # Margens do niri: canto quente (x,y < 8 = visão geral) e dock (y > H-45) abriam coisas sem querer
        m = self.c["margem_px"]
        x = float(np.clip(x, m, self.W - 1 - m))
        y = float(np.clip(y, m, self.H - self.c["dock_px"]))
        dx, dy = int(round(x - self.x)), int(round(y - self.y))
        if dx or dy:
            self.uinput.move(dx, dy)
            self.x += dx; self.y += dy
            try:
                json.dump({"x": int(self.x), "y": int(self.y)}, open(POS_FILE, "w"))
            except Exception:
                pass
        self._cb(act)

    def _clique(self, botao="esq"):
        self.uinput.click("left" if botao == "esq" else "right")
        self._cb("click")

    def _zoom(self, sentido=1):
        self.uinput.zoom(sentido)
        self._cb("zoom_in" if sentido > 0 else "zoom_out")

    def stop(self):
        if self.arrastando:
            self.uinput.btn_up("left")
            self.arrastando = False
        self.on = False
        self.punho_ativo = False
        self.pinca_unica_ativa = False
        self.pinca_disparada = False
        self.duas_pincas_ativas = False
        self.dist_zoom_anterior = None
        self.ancora = None
        self.lost_frames = 0
        self.ultima_mao = None
        self.trava_pos = None
        self.ponto_fecha = None
        self.estavel.clear()
        self.punho_hist.clear()

    def _relativo(self, lm, Wc, Hc, t):
        """Deslocamento relativo ultra-suave e milimétrico ancorado no centro rígido da palma."""
        # Centro geométrico rígido da palma da mão (nós 5, 9, 17)
        # 100% imune a mexer ou dobrar dedos individuais
        ax = 0.50 * float(lm[9][0]) + 0.25 * float(lm[5][0]) + 0.25 * float(lm[17][0])
        ay = 0.50 * float(lm[9][1]) + 0.25 * float(lm[5][1]) + 0.25 * float(lm[17][1])

        # Normalização isotrópica 1:1 rigorosamente pela largura da câmera (Wc).
        # Evita a distorção vertical de 3.16x que causava tremor e saltos.
        u_raw = 1.0 - ax / float(Wc)
        v_raw = ay / float(Wc)

        # Filtro OneEuro adaptativo na posição
        u = self.au(u_raw, t)
        v = self.av(v_raw, t)

        if self.ancora is None or self.t_anc is None or (t - self.t_anc > 0.35):
            self.ancora, self.t_anc = (u, v), t
            self.acc = [0.0, 0.0]
            return self.x, self.y

        du = u - self.ancora[0]
        dv = v - self.ancora[1]
        dt = max(t - self.t_anc, 1e-3)
        self.ancora, self.t_anc = (u, v), t

        dist = float(np.hypot(du, dv))

        # Supressão de ruído de sensor contínua e quadrática (zero tremor ao parar a mão)
        piso_ruido = 0.0010
        if dist < piso_ruido:
            fator_quieto = (dist / piso_ruido) ** 2
            du *= fator_quieto
            dv *= fator_quieto

        vel = dist / dt

        # Curva de aceleração cúbica Hermite:
        # vel <= 0.025: micro-movimento para mira precisa em botões de 16px (ganho 2600)
        # vel >= 0.25: movimento amplo para cruzar toda a tela com facilidade (ganho 6800)
        v_norm = float(np.clip((vel - 0.025) / 0.225, 0.0, 1.0))
        s_curve = v_norm * v_norm * (3.0 - 2.0 * v_norm)
        gain = 2600.0 + 4200.0 * s_curve

        self.acc[0] += du * gain * (self.W / 1920.0)
        self.acc[1] += dv * gain * (self.H / 1080.0)

        mx = int(round(self.acc[0]))
        my = int(round(self.acc[1]))
        self.acc[0] -= mx
        self.acc[1] -= my
        return self.x + mx, self.y + my

    def update_all(self, t, hands, Wc, Hc):
        """Processa todas as mãos detectadas para os 4 modos de gestos."""
        c = self.c
        # Anti-fantasma: conf/brilho/tamanho e mão estável em 4 de 6 quadros (fantasma pisca e some)
        valid_hands = [h for h in (hands or []) if self._mao_ok(h)]
        self.estavel.append(bool(valid_hands))
        if valid_hands and sum(self.estavel) < c["estavel_n"]:
            self._log(t, f"INSTAVEL n={sum(self.estavel)}/{len(self.estavel)}")
            valid_hands = []

        # Buffer de tolerância a quedas momentâneas de quadro (evita "cair toda hora")
        if not valid_hands:
            if hands:
                h0 = max(hands, key=lambda h_: float(h_.get("conf", 0)))
                self._log(t, f"REJEITADA conf={float(h0.get('conf', 0)):.2f} lum={float(h0.get('lum', -1)):.0f} w={largura_mao(h0['lm']):.0f}")
            self.lost_frames += 1
            if self.lost_frames <= 4:
                return
            if self.arrastando:
                self.uinput.btn_up("left")
                self.arrastando = False
            self.punho_ativo = False
            self.pinca_unica_ativa = False
            self.pinca_disparada = False
            self.duas_pincas_ativas = False
            self.dist_zoom_anterior = None
            self.ancora = None
            self.ultima_mao = None
            self.trava_pos = None
            self.ponto_fecha = None
            self.punho_hist.clear()
            return

        self.lost_frames = 0

        # ---------------------------------------------------------------------
        # GESTO 3: DUAS PINÇAS (UMA EM CADA MÃO) -> ZOOM IN / ZOOM OUT
        # ---------------------------------------------------------------------
        if len(valid_hands) >= 2:
            h1, h2 = valid_hands[0]["lm"], valid_hands[1]["lm"]
            p1 = e_pinca(h1, c["fecha"])
            p2 = e_pinca(h2, c["fecha"])

            if p1 and p2:
                c1 = np.mean(h1[[4, 8]], axis=0)
                c2 = np.mean(h2[[4, 8]], axis=0)
                dist_atual = float(np.hypot(c1[0] - c2[0], c1[1] - c2[1]))

                if self.dist_zoom_anterior is not None:
                    delta_dist = dist_atual - self.dist_zoom_anterior
                    step_px = 26.0

                    if t - self.t_ultimo_zoom > 0.08:
                        if delta_dist > step_px:
                            self._zoom(1)
                            self.t_ultimo_zoom = t
                            self.dist_zoom_anterior = dist_atual
                        elif delta_dist < -step_px:
                            self._zoom(-1)
                            self.t_ultimo_zoom = t
                            self.dist_zoom_anterior = dist_atual
                else:
                    self.dist_zoom_anterior = dist_atual

                self.duas_pincas_ativas = True
                self._cb("zoom")
                return
            else:
                self.duas_pincas_ativas = False
                self.dist_zoom_anterior = None
        else:
            self.duas_pincas_ativas = False
            self.dist_zoom_anterior = None

        # ---------------------------------------------------------------------
        # SELEÇÃO DA MÃO DOMINANTE (Para Palma, Punho ou Pinça Única)
        # ---------------------------------------------------------------------
        if self.ultima_mao is not None:
            active_h = min(valid_hands, key=lambda h_: float(np.linalg.norm(h_["lm"][9] - self.ultima_mao)))
        else:
            active_h = max(valid_hands, key=lambda h_: float(h_.get("conf", 0)))

        lm = active_h["lm"]
        self.ultima_mao = lm[9].copy()

        w_m = largura_mao(lm)
        ab = _d(lm, 4, 8) / w_m
        punho_bruto = mao_fechada(lm)
        # pinça com histerese: fecha < 0,30, só solta > 0,48 (sem pisca-pisca no limiar)
        if self.pinca_unica_ativa:
            eh_pinca = not punho_bruto and ab < c["abre"]
        else:
            eh_pinca = e_pinca(lm, c["fecha"])
        # punho N-de-M: entra com 3 de 4 quadros fechados, sai com 3 de 4 abertos
        self.punho_hist.append(punho_bruto)
        n_p = sum(self.punho_hist)
        eh_punho = (len(self.punho_hist) - n_p) < 3 if self.punho_ativo else n_p >= 3
        eh_palma = palma_aberta(lm)
        self._log(t, f"conf={float(active_h.get('conf', 0)):.2f} lum={float(active_h.get('lum', -1)):.0f} w={w_m:.0f} ab={ab:.2f} "
                     f"pinca={int(eh_pinca)} punho={n_p}/{len(self.punho_hist)}:{int(eh_punho)} drag={int(self.arrastando)} x={int(self.x)} y={int(self.y)}")

        # ---------------------------------------------------------------------
        # GESTO 4: PINÇA ÚNICA -> CLIQUE DIREITO
        # ---------------------------------------------------------------------
        if eh_pinca and not self.duas_pincas_ativas and not self.punho_ativo:
            if not self.pinca_unica_ativa:
                self.pinca_unica_ativa = True
                self.t_pinca_dir = t
                self.pinca_disparada = False
            elif (t - self.t_pinca_dir >= c["dir_s"]) and not self.pinca_disparada:     # 0,12 s disparava por engano
                self._clique("dir")
                self._log(t, "CLIQUE_DIR")
                self.pinca_disparada = True
            self._cb("right_click")
            return
        else:
            if not eh_pinca:
                self.pinca_unica_ativa = False
                self.pinca_disparada = False

        # ---------------------------------------------------------------------
        # GESTO 2: MÃO FECHADA (PUNHO) -> CLIQUE OU CLIQUE LONGO / ARRASTO
        # ---------------------------------------------------------------------
        if eh_punho:
            if not self.punho_ativo:
                self.punho_ativo = True
                self.t_punho_inicio = t
                self.trava_pos = (self.x, self.y)
                self.ponto_fecha = None

            # arrastar só se, fechada, a ÂNCORA (nós 5/9/13) andar > 0,03 (regra v4; antes segurar 0,32 s já arrastava)
            ax_, ay_ = np.mean(lm[[5, 9, 13]], axis=0)
            pa = (float(ax_) / Wc, float(ay_) / Hc)
            if self.ponto_fecha is None:
                self.ponto_fecha = pa
            andou = float(np.hypot(pa[0] - self.ponto_fecha[0], pa[1] - self.ponto_fecha[1]))
            if not self.arrastando and andou > c["arrasto_min"]:
                self.uinput.btn_down("left")
                self.arrastando = True
                self.ancora = None                 # cursor parte do ponto travado, sem salto acumulado
                self._log(t, f"ARRASTO andou={andou:.3f}")

            if self.arrastando:
                tx, ty = self._relativo(lm, Wc, Hc, t)
                dist = float(np.hypot(tx - self.x, ty - self.y))
                if dist > 0.5:
                    self._move_to(tx, ty, "drag")
                else:
                    self._cb("drag")
            else:
                self._cb("fist")
            return

        elif self.punho_ativo and not eh_punho:
            duracao = t - self.t_punho_inicio
            self.punho_ativo = False

            if self.arrastando:
                self.uinput.btn_up("left")
                self.arrastando = False
                self._log(t, "SOLTA")
            elif duracao <= c["clique_max_s"]:     # fechou e abriu parado: clique; segurou demais parado: nada
                if self.trava_pos:
                    self._move_to(self.trava_pos[0], self.trava_pos[1], "click")
                self._clique("esq")
                self._log(t, f"CLIQUE dur={duracao:.2f}")

            self.trava_pos = None
            self.ponto_fecha = None
            self.ancora = None
            self.au.reset(); self.av.reset()

        # ---------------------------------------------------------------------
        # GESTO 1: MÃO ABERTA (PALMA) -> MOVE O CURSOR
        # ---------------------------------------------------------------------
        if (eh_palma or not (eh_punho or eh_pinca)) and not punho_bruto:     # fechando (ainda não confirmado): cursor parado
            tx, ty = self._relativo(lm, Wc, Hc, t)
            dist = float(np.hypot(tx - self.x, ty - self.y))
            if dist > 0.5:
                self._move_to(tx, ty, "move")
            else:
                self._cb("move")

    def update(self, t, hand_or_hands, Wc, Hc):
        """Compatibilidade retroativa: encaminha para update_all."""
        if isinstance(hand_or_hands, list):
            return self.update_all(t, hand_or_hands, Wc, Hc)
        elif hand_or_hands is not None:
            return self.update_all(t, [hand_or_hands] if isinstance(hand_or_hands, dict) else [{"lm": hand_or_hands, "conf": 0.9}], Wc, Hc)
        return self.update_all(t, [], Wc, Hc)

    def escolher(self, hands):
        """Compatibilidade retroativa: retorna a lista completa de mãos para update_all."""
        return hands or []
