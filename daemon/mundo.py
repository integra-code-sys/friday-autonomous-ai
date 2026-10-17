"""MUNDO: câmeras FIXAS (porta = webcam USB, nativa = notebook) dizem ONDE está a pessoa; a PTZ aponta direto para lá.

Sem calibração manual nem geometria fixa: a correspondência "ponto na câmera fixa -> pan/tilt da PTZ" é APRENDIDA sozinha.
Toda vez que a PTZ está centrada numa pessoa (seguir) e uma câmera fixa vê exatamente UMA pessoa, grava o par
(u, v da cabeça na fixa) -> (pan_s, tilt_s da PTZ). Para estimar, interpola pelos pares mais próximos (IDW).
Par novo perto de um antigo substitui o antigo (se o notebook/webcam mudar de lugar, o mapa se refaz com o uso).
"""
import json
import math
import os
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQ = os.path.join(ROOT, "memory", "mundo_pares.json")
MAX_PARES = 400            # por câmera
RAIO_MESMO = 0.035         # par novo a menos disso (fração da tela) de um antigo = substitui
RAIO_MAX = 0.22            # sem par a menos disso = "não sei" (fora da área já vista)
VALIDADE = 1.0             # s: observação mais velha que isso não vale


class Mundo:
    def __init__(self):
        self._lock = threading.Lock()
        self.pares = {}                    # cam -> [[u, v, pan, tilt, t], ...]
        self.obs = {}                      # cam -> (t, [(u, v, conf), ...])
        self._ult_aprendeu = 0.0
        self._sujo = False
        self._discorda = {}                # cam -> amostras que contradizem o mapa (só valem se repetirem)
        self._entrada = {}                 # cam -> estado do detector de entrada (porta vazia -> alguém apareceu)
        self._gesto = {}                   # cam -> estado do detector de mão levantada
        try:
            with open(ARQ) as f:
                self.pares = {k: [list(p) for p in v] for k, v in json.load(f).items()}
        except Exception:
            pass

    # ---------------------------------------------------------------- entrada das câmeras fixas
    def observar(self, cam, t, pessoas):
        """pessoas: [(u, v, conf)] normalizados 0..1 (ponto da cabeça)."""
        with self._lock:
            self.obs[cam] = (t, [(float(u), float(v), float(c)) for u, v, c in pessoas])

    def entrada(self, cam, t, n, vazio_min=20.0, seguidas=2):
        """True UMA vez quando a câmera ficou vazia por >= vazio_min s e depois vê n>=1 em `seguidas` leituras seguidas
        (um quadro só com falso positivo não dispara). Chamada a cada leitura da câmera (porta)."""
        with self._lock:
            st = self._entrada.setdefault(cam, {"vazio_desde": t, "seq": 0, "armado": False})   # ao ligar não avisa quem já está lá
            if n <= 0:
                if st["seq"] > 0 or st["vazio_desde"] is None:
                    st["vazio_desde"] = t
                st["seq"] = 0
                if t - st["vazio_desde"] >= vazio_min:
                    st["armado"] = True
                return False
            st["seq"] += 1
            if st["seq"] >= seguidas and st["armado"]:
                st["armado"] = False
                return True
            return False

    def gesto(self, cam, t, mao_alta, seguidas=3):
        """mão levantada em `seguidas` leituras seguidas -> True uma vez (re-arma quando a mão desce)."""
        with self._lock:
            st = self._gesto.setdefault(cam, {"seq": 0, "armado": True})
            if not mao_alta:
                st["seq"], st["armado"] = 0, True
                return False
            st["seq"] += 1
            if st["seq"] >= seguidas and st["armado"]:
                st["armado"] = False
                return True
            return False

    def _frescas(self, agora=None):
        agora = agora or time.time()
        return {c: ps for c, (t, ps) in self.obs.items() if agora - t < VALIDADE}

    # ---------------------------------------------------------------- aprendizado (chamado pela PTZ centrada no alvo)
    def aprender(self, pan, tilt, t_ref=None):
        agora = time.time()
        if agora - self._ult_aprendeu < 0.5:
            return 0
        n = 0
        with self._lock:
            for cam, ps in self._frescas(agora).items():
                if len(ps) != 1:           # 0 ou várias pessoas: ambíguo, não aprende
                    continue
                if t_ref is not None and abs(self.obs[cam][0] - t_ref) > 0.45:
                    continue               # fixa e PTZ de instantes diferentes
                u, v = float(ps[0][0]), float(ps[0][1])
                pan, tilt = float(pan), float(tilt)
                r = self._idw(cam, u, v)
                if r and r[2] >= 0.5 and abs(r[0] - pan) > 3.0:
                    # contradiz o mapa (outra pessoa? estimativa derivada?): só aceita após 3 discordâncias coerentes
                    d = self._discorda.setdefault(cam, [])
                    d.append((u, v, pan))
                    d[:] = [x for x in d[-6:] if math.hypot(x[0] - u, x[1] - v) < 0.08 and abs(x[2] - pan) < 3.0]
                    if len(d) < 3:
                        continue
                    d.clear()
                    # confirmado: os pares VELHOS da vizinhança que dizem outro pan estão errados (câmera/estimativa mudou) — saem,
                    # senão o IDW mistura os dois e a estimativa salta (9 <-> 32 com o dono parado = PTZ girando sem parar)
                    self.pares[cam] = [p for p in self.pares.get(cam, [])
                                       if math.hypot(p[0] - u, p[1] - v) > RAIO_MAX / 2 or abs(p[2] - pan) <= 3.0]
                lst = [p for p in self.pares.get(cam, []) if math.hypot(p[0] - u, p[1] - v) > RAIO_MESMO]
                lst.append([round(u, 4), round(v, 4), round(pan, 2), round(tilt, 2), round(agora)])
                self.pares[cam] = lst[-MAX_PARES:]
                n += 1
            if n:
                self._ult_aprendeu = agora
                self._sujo = True
        if n and agora - getattr(self, "_ult_grava", 0) > 30:
            self.salvar()
        return n

    def refutar(self):
        """a PTZ foi aonde o mapa mandou e não havia ninguém lá: os pares perto do que as fixas veem AGORA estão errados
        (câmera mudou de lugar, par aprendido com alvo falso) e saem. Sem isso o mapa velho mandava para o mesmo lugar errado
        para sempre (16/10: PTZ foi para a mesa e o mapa antigo apontava para o espelho)."""
        n = 0
        with self._lock:
            for cam, ps in self._frescas().items():
                for u, v, _c in ps:
                    antes = self.pares.get(cam, [])
                    self.pares[cam] = [p for p in antes if math.hypot(p[0] - u, p[1] - v) > RAIO_MAX / 2]
                    n += len(antes) - len(self.pares[cam])
            if n:
                self._sujo = True
        if n:
            self.salvar()
        return n

    def salvar(self):
        with self._lock:
            if not self._sujo:
                return
            dados = json.dumps(self.pares, default=float)
            self._sujo = False
        self._ult_grava = time.time()
        try:
            tmp = ARQ + ".tmp"
            with open(tmp, "w") as f:
                f.write(dados)
            os.replace(tmp, ARQ)
        except Exception:
            pass

    # ---------------------------------------------------------------- estimativa
    def _idw(self, cam, u, v, k=5):
        ps = self.pares.get(cam) or []
        if len(ps) < 3:
            return None
        ds = sorted((math.hypot(p[0] - u, p[1] - v), p) for p in ps)[:k]
        if ds[0][0] > RAIO_MAX:
            return None
        if ds[0][0] < 1e-4:
            return ds[0][1][2], ds[0][1][3], 1.0
        w = [1.0 / (d * d) for d, _ in ds]
        sw = sum(w)
        pan = sum(wi * p[2] for wi, (_, p) in zip(w, ds)) / sw
        tilt = sum(wi * p[3] for wi, (_, p) in zip(w, ds)) / sw
        conf = max(0.0, 1.0 - ds[0][0] / RAIO_MAX) * min(1.0, len(ps) / 6.0)
        return pan, tilt, conf

    def estimar(self):
        """[{pan, tilt, conf, cams}] — pessoas vistas AGORA pelas câmeras fixas, já no espaço da PTZ (fundidas)."""
        with self._lock:
            cands = []
            for cam, ps in self._frescas().items():
                for u, v, c in ps:
                    r = self._idw(cam, u, v)
                    if r:
                        cands.append({"pan": r[0], "tilt": r[1], "conf": r[2] * c, "cams": [cam]})
        # funde a mesma pessoa vista pelas duas câmeras (pan a menos de 4 s de motor)
        fundidos = []
        for c in sorted(cands, key=lambda x: -x["conf"]):
            for f in fundidos:
                if abs(f["pan"] - c["pan"]) < 4.0 and not set(c["cams"]) & set(f["cams"]):
                    wt = f["conf"] + c["conf"] or 1.0
                    f["pan"] = (f["pan"] * f["conf"] + c["pan"] * c["conf"]) / wt
                    f["tilt"] = (f["tilt"] * f["conf"] + c["tilt"] * c["conf"]) / wt
                    f["conf"] = min(1.0, f["conf"] + c["conf"] * 0.5)
                    f["cams"] = f["cams"] + c["cams"]
                    break
            else:
                fundidos.append(dict(c))
        return fundidos

    def melhor(self, perto_de=None):
        """estimativa mais confiável (ou a mais próxima de um pan, p/ continuar o mesmo alvo)."""
        es = [e for e in self.estimar() if e["conf"] >= 0.2]
        if not es:
            return None
        if perto_de is not None:
            return min(es, key=lambda e: abs(e["pan"] - perto_de) - e["conf"])
        return max(es, key=lambda e: e["conf"])

    def falado(self):
        """o que as câmeras FIXAS veem, em linguagem de gente (vai para o cérebro)."""
        nomes = {"porta": "webcam da porta", "nativa": "câmera do notebook"}
        with self._lock:
            vistas = self._frescas()
        n = lambda k: "ninguém" if k == 0 else "1 pessoa" if k == 1 else f"{k} pessoas"
        partes = [f"{nomes.get(c, c)}: {n(len(ps))}" for c, ps in sorted(vistas.items())]
        if any(self.pares.get(c) for c in vistas) and self.estimar():
            partes.append("a câmera do quarto já sabe apontar para elas")
        return ", ".join(partes)

    def resumo(self):
        with self._lock:
            n = {c: len(v) for c, v in self.pares.items()}
            vistas = {c: len(ps) for c, ps in self._frescas().items()}
        es = self.estimar()
        txt = "pares aprendidos: " + (", ".join(f"{c} {k}" for c, k in n.items()) or "nenhum")
        txt += "; pessoas nas fixas: " + (", ".join(f"{c} {k}" for c, k in vistas.items()) or "nenhuma câmera fixa ativa")
        if es:
            txt += "; estimativas p/ PTZ: " + ", ".join(f"pan {e['pan']:.1f} tilt {e['tilt']:.1f} ({e['conf']:.0%}, {'+'.join(e['cams'])})" for e in es)
        return txt


_M = None


def get():
    global _M
    if _M is None:
        _M = Mundo()
    return _M
