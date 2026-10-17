"""Cinemática do avatar a partir do tracking: ângulos do braço (3D), dedos, punho e tronco.
Convenção do rig (shell/scene3d.frag): swing sw (elevação à frente), abdução ab, flexão do cotovelo fl, rolagem axial ro.
Coords do avatar: x = direita da tela, y = cima, z = para o espectador. side = -1 (braço E, esquerda da tela) | +1 (D)."""
import numpy as np

AXIS_R = np.array([1.48, -2.11, -0.10]); AXIS_R /= np.linalg.norm(AXIS_R)
F0_R = np.array([0.4725, -0.4438, 0.7614])   # antebraço em repouso: cotovelo -> punho (HUMANOID.obj, mão direita)


def _rx(v, a):
    c, s = np.cos(a), np.sin(a)
    return np.stack([v[..., 0], c * v[..., 1] - s * v[..., 2], s * v[..., 1] + c * v[..., 2]], -1)


def _rz(v, a):
    c, s = np.cos(a), np.sin(a)
    return np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1], v[..., 2]], -1)


def _rot_axis(v, ax, ang):
    c, s = np.cos(ang)[..., None], np.sin(ang)[..., None]
    return v * c + np.cross(ax, v) * s + ax * (v @ ax)[..., None] * (1 - c)


def _axis(side):
    return AXIS_R * np.array([side, 1.0, 1.0])


def _fwd(v, sw, ab, side):
    """direção no frame do úmero (sem rolagem) -> mundo (igual a armUpperFwdN)."""
    return _rx(_rz(v, ab * side), -sw)


_SW, _AB = np.meshgrid(np.arange(-0.2, 1.65, 0.05), np.arange(-0.9, 1.3, 0.05), indexing="ij")
_FL, _RO = np.meshgrid(np.arange(-1.0, 2.5, 0.05), np.arange(-1.7, 1.7, 0.1), indexing="ij")


def arm_angles(S, E, Wr, side, prev=None, use_roll=False):
    """S,E,Wr: ombro, cotovelo, punho (3D, coords do avatar). Retorna (sw, ab, fl, ro)."""
    du = E - S; nu = np.linalg.norm(du)
    df = Wr - E; nf = np.linalg.norm(df)
    if nu < 1e-6 or nf < 1e-6:
        return None
    du /= nu; df /= nf
    r = _axis(side)
    pred = _fwd(np.broadcast_to(r, _SW.shape + (3,)), _SW, _AB, side)
    err = 1.0 - pred @ du
    if prev is not None:                                   # regulariza p/ continuidade
        err = err + 0.02 * ((_SW - prev[0]) ** 2 + (_AB - prev[1]) ** 2)
    i = np.unravel_index(np.argmin(err), err.shape)
    sw, ab = float(_SW[i]), float(_AB[i])
    f0 = np.array([F0_R[0] * side, F0_R[1], F0_R[2]])
    if not use_roll:                                       # rolagem do antebraço sai muito ruidosa (aceno vira "giro"): fixa em 0
        fls = _FL[:, 0]
        dirs0 = _fwd(_rx(np.broadcast_to(f0, fls.shape + (3,)), -fls), sw, ab, side)
        e0 = 1.0 - dirs0 @ df
        if prev is not None:
            e0 = e0 + 0.02 * (fls - prev[2]) ** 2
        return sw, ab, float(fls[int(np.argmin(e0))]), 0.0
    dirs = _rx(np.broadcast_to(f0, _FL.shape + (3,)), -_FL)
    dirs = _rot_axis(dirs, r, _RO * side)
    predf = _fwd(dirs, sw, ab, side)
    errf = 1.0 - predf @ df
    if prev is not None:
        errf = errf + 0.02 * (_FL - prev[2]) ** 2 + 0.06 * (_RO - prev[3]) ** 2
    j = np.unravel_index(np.argmin(errf), errf.shape)
    fl, ro = float(_FL[j]), float(_RO[j])
    bend = float(np.arccos(np.clip(np.dot(du, df), -1.0, 1.0)))     # ângulo braço x antebraço no mundo
    conf = float(np.clip((bend - 0.25) / 0.5, 0.0, 1.0))           # 0 = esticado (rolagem indefinida), 1 = dobrado
    ro_prev = prev[3] if prev is not None else 0.0
    ro = ro_prev + (ro - ro_prev) * conf                            # com braço esticado, mantém a rolagem anterior
    ro = float(np.clip(ro, -1.3, 1.3))
    return sw, ab, fl, ro


def _ang(a, b, c):
    u = a - b; v = c - b
    return float(np.arccos(np.clip(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9), -1, 1)))


NEUTRAL_SPREAD = (0.10, 0.0, -0.08, -0.20)
FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))


def finger_params(lm, z):
    """lm (21,2) px, z (21,) -> curls[4], thumb, spreads[4], palm_normal(3). Curl 0 = esticado, 1 = fechado.
    Abertura (leque) = ângulo entre indicador e mindinho (sem sinal => independe de mão/palma/costas)."""
    P = np.concatenate([lm, z[:, None]], 1).astype("float64")
    curls = []
    for (m, p, d, t) in FINGERS:
        pip = np.pi - _ang(P[m], P[p], P[d])
        dip = np.pi - _ang(P[p], P[d], P[t])
        mcp = np.pi - _ang(P[0], P[m], P[p])
        raw_c = 0.5 * pip / 1.7 + 0.2 * dip / 1.2 + 0.3 * mcp / 1.3
        curls.append(float(np.clip((raw_c - 0.04) / 0.82, 0, 1)))      # calibrado: punho fechado ~0,9 bruto -> 1,0
    a = P[6] - P[5]; b = P[18] - P[17]
    fan = float(np.arccos(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9), -1, 1)))
    f = float(np.clip((fan - 0.35) / 0.55, -0.4, 1.2))
    open_k = 1.0 - float(np.mean(curls))                         # dedos fechados não abrem em leque
    spreads = [f * 0.45 * open_k, f * 0.15 * open_k, -f * 0.20 * open_k, -f * 0.55 * open_k]
    tcurl = float(np.clip((np.pi - _ang(P[2], P[3], P[4])) / 1.0, 0, 1))
    nrm = np.cross(P[5] - P[0], P[17] - P[0])
    nrm = nrm / (np.linalg.norm(nrm) + 1e-9)
    return curls, tcurl, spreads, nrm


def wrist_params(lm, z, forearm_xy, side_img):
    """(flexão, desvio) do punho, limitados. Desvio = ângulo mão x antebraço no plano da imagem;
    flexão = inclinação em profundidade da mão. Ganhos moderados (sinais a calibrar com a câmera real)."""
    hand = lm[9] - lm[0]
    fa = np.asarray(forearm_xy, dtype="float64")
    nh, nf = np.linalg.norm(hand), np.linalg.norm(fa)
    if nf < 1e-6 or nh < 1e-6:
        return 0.0, 0.0
    ang = np.arctan2(fa[0] * hand[1] - fa[1] * hand[0], float(np.dot(fa, hand)))
    dev = float(np.clip(ang * 0.8, -0.5, 0.5))
    flex = float(np.clip(np.arcsin(np.clip((z[9] - z[0]) / nh, -1, 1)) * 0.8, -0.6, 0.6))
    return flex, dev


class OneEuro:
    """Filtro One-Euro: suaviza forte parado (sem tremor) e quase não atrasa em movimento rápido."""
    def __init__(self, mincutoff=1.5, beta=0.08, dcutoff=1.0):
        self.mc, self.beta, self.dc = mincutoff, beta, dcutoff
        self.x = None; self.dx = 0.0; self.t = None

    @staticmethod
    def _a(cut, dt):
        tau = 1.0 / (2 * np.pi * cut)
        return 1.0 / (1.0 + tau / max(dt, 1e-3))

    def __call__(self, x, t):
        if self.x is None or self.t is None or t - self.t > 1.0:
            self.x, self.dx, self.t = float(x), 0.0, t
            return float(x)
        dt = t - self.t; self.t = t
        d = (x - self.x) / max(dt, 1e-3)
        self.dx += self._a(self.dc, dt) * (d - self.dx)
        cut = self.mc + self.beta * abs(self.dx)
        self.x += self._a(cut, dt) * (x - self.x)
        return float(self.x)

    def reset(self):
        self.x = None


def step_limit(prev, new, max_step):
    """limita a variação por quadro (rejeita saltos espúrios do estimador)."""
    return prev + float(np.clip(new - prev, -max_step, max_step))


class Median:
    """mediana móvel (janela n): remove picos isolados do estimador (típico em movimentos rápidos, como acenar)."""
    def __init__(self, n=5):
        self.n = n; self.buf = []

    def __call__(self, x):
        self.buf.append(float(x))
        if len(self.buf) > self.n:
            self.buf.pop(0)
        return float(np.median(self.buf))

    def reset(self):
        self.buf = []
