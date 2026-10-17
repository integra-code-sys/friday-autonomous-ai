"""Controle da câmera com motor (PTZ) da Sexta-feira: olhar, varrer, procurar, LOCALIZAR e SEGUIR o dono em tempo real, vigiar.

Fatos medidos nesta câmera (Yoosee ML-310, 14/10/2026) que definem o desenho:
- velocidade FIXA (o firmware ignora o valor de 0,15 a 8): pan ~0,16 da largura/s, tilt ~0,17 da altura/s;
- não move pan e tilt juntos (diagonal = só pan) -> os eixos se alternam;
- cada ContinuousMove gira ~1 s e para sozinho -> o ipcam renova a cada 0,5 s (mover());
- vídeo do fluxo 640x360: o movimento aparece ~0,65 s depois do comando (o 1280x720 leva 1,45 s).
A posição não é lida da câmera: é ESTIMADA em "segundos de motor" (pan 0..pan_total_s, tilt 0..tilt_total_s) pelo
histórico de comandos do ipcam. Rastreio: yolov8n-pose em todo quadro + controle por velocidade com PREDITOR do atraso
(desconta o quanto a câmera já girou desde o quadro analisado) -> não passa do ponto nem fica oscilando.

O daemon liga os ganchos com configurar(...): quadro(), dono(), presente(), detectar(frame), vlm(jpg, pergunta),
avisar(texto, falar, jpg), modo_mudou(modo). Modos: "livre" | "seguir" | "vigiar" | "auto".
"""
import math
import re
import os
import threading
import time

import cv2
import numpy as np

import ipcam

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PASTA_VIGIA = os.path.expanduser("~/Imagens/Friday/vigia")
LAT_VIDEO = 0.45        # s entre a cena acontecer e o quadro chegar (fluxo 640x360)
LAT_MOTOR = 0.20        # s entre o comando e o motor andar / parar
LATENCIA = LAT_VIDEO + LAT_MOTOR + 0.15    # espera "segura" para o vídeo mostrar a posição nova
_PADRAO = {"pan_v": 0.1695, "tilt_v": 0.17, "pan_total_s": 64.5, "tilt_total_s": 34.0,
           "tilt_horizonte": 2.0, "tilt_min_busca": 4.5}   # abaixo de tilt_min_busca a PTZ (na mesa, 16/10) só vê as próprias antenas          # s de tilt baixo (altura da mesa/usuário) p/ manter iluminação e evitar modo IR P&B

log = ipcam.log
ALVO_Y = 0.38      # altura da CABEÇA no quadro ao seguir (terço superior = corpo visível; 0.48 cortava o corpo)


def _conf():
    c = dict(_PADRAO)
    c.update({k: v for k, v in ipcam.ler_conf().items() if v is not None})
    return c


class Ganchos:
    quadro = staticmethod(lambda: (None, 0.0))          # (frame BGR da câmera PTZ, instante em que chegou)
    dono = staticmethod(lambda: None)                   # (instante, caixa x0,y0,x1,y1 normalizada) do rosto do dono, se reconhecido
    presente = staticmethod(lambda: False)              # o dono está por perto (PC, voz, câmeras)?
    detectar = staticmethod(lambda fr: [])              # [(nome_pt, conf, (x, y, w, h) px)] — YOLOX (objetos)
    vlm = staticmethod(lambda jpg, pergunta: None)      # texto do modelo de visão
    avisar = staticmethod(lambda texto, falar=False, jpg=None: None)
    modo_mudou = staticmethod(lambda modo: None)
    alvo_externo = staticmethod(lambda perto_de=None: None)   # câmeras FIXAS: {pan, tilt, conf, cams} de quem elas veem (mundo.py)
    aprender = staticmethod(lambda pan, tilt, t_ref=None: 0)            # PTZ centrada numa pessoa: ensina o mapa fixas -> pan/tilt
    quadro_hd = staticmethod(lambda: None)                  # 1 quadro 1280x720 (stream principal) p/ zoom digital
    mundo_resumo = staticmethod(lambda: "câmeras fixas indisponíveis")
    sentado = staticmethod(lambda: False)                   # câmera do notebook vê o dono sentado agora (rosto reconhecido)
    rostos = staticmethod(lambda: (0.0, []))                # (instante, [caixas x0,y0,x1,y1 normalizadas]) de QUALQUER rosto no quadro da PTZ
    refutar = staticmethod(lambda: 0)                       # fui aonde as fixas mandaram e não havia ninguém: apaga os pares que erraram
    camisa_dono = staticmethod(lambda: None)
    multidao = staticmethod(lambda: False)                  # as câmeras fixas veem mais alguém além do dono?                # (instante, [H, S, V] mediana OpenCV) da roupa do dono vista pela nativa


G = Ganchos()


def configurar(**kw):
    for k, v in kw.items():
        setattr(Ganchos, k, staticmethod(v))


# ------------------------------------------------------------------ pessoas: yolov8n-pose (25 ms por quadro na CPU)
def mao_alta(k, conf=0.4):
    """keypoints COCO 17x3 (x, y, conf; y cresce para baixo): algum pulso (9/10) acima do nariz (0) ou, sem nariz, dos ombros (5/6)."""
    ref = [k[0][1]] if k[0][2] >= conf else [k[i][1] for i in (5, 6) if k[i][2] >= conf]
    if not ref:
        return False
    topo = min(ref)
    return any(k[i][2] >= conf and k[i][1] < topo for i in (9, 10))


class Pose:
    def __init__(self, threads=2):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")     # sem busy-wait entre quadros (igual ao senses.py)
        self.s = ort.InferenceSession(os.path.join(ROOT, "models", "yolov8n-pose.onnx"), so, providers=["CPUExecutionProvider"])
        self.nome = self.s.get_inputs()[0].name

    def pessoas(self, fr, conf=0.40):
        """[{caixa: (x0,y0,x1,y1) 0..1, cabeca: (x,y) 0..1 ou None, conf}] mais confiantes primeiro."""
        h, w = fr.shape[:2]
        sc = 640.0 / max(w, h)
        img = cv2.resize(fr, (int(w * sc), int(h * sc)))
        py, px = (640 - img.shape[0]) // 2, (640 - img.shape[1]) // 2
        tela = np.full((640, 640, 3), 114, np.uint8)
        tela[py:py + img.shape[0], px:px + img.shape[1]] = img
        blob = (tela[:, :, ::-1].astype("float32") / 255.0).transpose(2, 0, 1)[None]
        out = self.s.run(None, {self.nome: blob})[0][0].T                       # 8400 x 56
        m = out[:, 4] > conf
        if not m.any():
            return []
        d = out[m]
        caixas = [[float(c[0] - c[2] / 2), float(c[1] - c[3] / 2), float(c[2]), float(c[3])] for c in d]
        keep = cv2.dnn.NMSBoxes(caixas, d[:, 4].tolist(), conf, 0.5)
        res = []
        for i in np.array(keep).ravel():
            cx, cy, bw, bh = d[i][:4]
            k = d[i][5:].reshape(17, 3)
            x0, y0 = (cx - bw / 2 - px) / sc / w, (cy - bh / 2 - py) / sc / h
            x1, y1 = (cx + bw / 2 - px) / sc / w, (cy + bh / 2 - py) / sc / h
            cab = [p for p in (k[0], k[1], k[2], k[3], k[4]) if p[2] > 0.5]       # nariz, olhos, orelhas
            cabeca = None
            if cab:
                cabeca = (float(np.mean([(p[0] - px) / sc / w for p in cab])), float(np.mean([(p[1] - py) / sc / h for p in cab])))
            elif k[5][2] > 0.5 and k[6][2] > 0.5:                               # ombros: cabeça um pouco acima
                cabeca = (float(((k[5][0] + k[6][0]) / 2 - px) / sc / w), float(((k[5][1] + k[6][1]) / 2 - py) / sc / h) - 0.08)
            res.append({"caixa": (max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)), "cabeca": cabeca, "conf": float(d[i][4]),
                        "kp": int((k[:, 2] > 0.5).sum()), "mao_alta": mao_alta(k)})          # pontos do corpo confiáveis: casaco/cadeira dá 0, gente visível dá 5+
        return sorted(res, key=lambda r: -r["conf"])


class PTZ:
    def __init__(self):
        c = _conf()
        self.pan = float(c.get("pan_est", c["pan_total_s"] / 2))
        self.tilt = min(4.0, float(c.get("tilt_est", c["tilt_horizonte"])))
        self.calibrada = bool(c.get("calibrada", False))
        self.modo = "livre"
        self.modo_salvo = c.get("modo", "auto")           # autônoma por padrão: segue o dono presente, vigia quando ele sai
        self.ocupada = None
        self._lock = threading.RLock()
        self._parar_tarefa = threading.Event()
        self._pose = None
        self._pose_lock = threading.Lock()
        self._ult_salvo = 0.0
        self._hist_i = 0                     # até onde o histórico do motor já entrou na estimativa
        self._ancorado = time.time()
        self._tilt_ancorado = 0.0            # 16/10: ao subir o tilt salvo pode estar errado (achava 4, estava em 10 = olhando p/ cima): 1ª busca ancora
        self.alvo = None                     # {"x","y" (ponto a centralizar), "caixa", "t" (chegada do quadro)}
        self._eixo = None                    # eixo em movimento no rastreio ("pan"/"tilt"/"busca") e sentido
        self._sinal = 0
        self._visto = 0.0
        self._lado = 0                       # último lado em que o alvo sumiu (-1 esq, +1 dir)
        self._vel = (0.0, 0.0)               # velocidade do alvo NA CENA (fração da tela/s, já sem o giro da câmera)
        self._ex_ant = None                  # (instante, ex, ey) do último erro previsto, p/ estimar a velocidade
        self.cobertura = (0, 0)
        # vigia
        self._ult_alerta = self._ult_mov_alerta = self._ult_fala = 0.0
        self._confirma, self._ult_conf_t = 0, 0.0
        self._ronda_i, self._ronda_ate, self._ronda_ref = 0, 0.0, None
        self._ausente_desde = None
        self._pessoas = (0.0, [])
        threading.Thread(target=self._laco, daemon=True, name="ptz-laco").start()
        threading.Thread(target=self._retomar, daemon=True, name="ptz-retomar").start()
        threading.Thread(target=self._relocalizar, daemon=True, name="ptz-reloc").start()

    def _retomar(self):
        """ao subir (ou quando a câmera volta), retoma o modo salvo assim que houver vídeo e motor."""
        while True:
            time.sleep(3)
            if self.modo == "livre" and not self.ocupada and self.modo_salvo != "livre" and self.disponivel() \
                    and time.time() > getattr(self, "_pausa_ate", 0.0):   # pedido manual (olhar/pare) segura o automático
                fr, t = G.quadro()
                if fr is not None and time.time() - t < 2:
                    log(f"retomando modo {self.modo_salvo}")
                    self.definir_modo(self.modo_salvo, salvar=False)

    # ------------------------------------------------------------ básico
    @property
    def cam(self):
        return ipcam.atual()

    def disponivel(self):
        c = self.cam
        return c is not None and c.ok and c.motor

    def pose(self):
        with self._pose_lock:
            if self._pose is None:
                self._pose = Pose(threads=3)        # 2 threads ~61 ms/quadro (perto dos 67 ms do vídeo)
            return self._pose

    def estado(self):
        c = _conf()
        if not self.disponivel():
            return ipcam.status()
        self._integrar()
        pp = 100 * self.pan / max(0.1, c["pan_total_s"])
        tp = 100 * self.tilt / max(0.1, c["tilt_total_s"])
        alvo = ", com você no quadro" if (self.modo in ("seguir", "auto") and time.time() - self._visto < 2) else ""
        return (f"câmera PTZ ok, modo {self.modo}{' (' + self.ocupada + ')' if self.ocupada else ''}{alvo}, "
                f"pan {pp:.0f}% tilt {tp:.0f}%{'' if self.calibrada else ', sem calibrar'}"
                f"; posições salvas: {', '.join(sorted(ipcam.ler_conf().get('posicoes') or {})) or 'nenhuma'}")

    def _integrar(self):
        """soma na estimativa de posição o que o motor girou (histórico do ipcam)."""
        cam = self.cam
        if cam is None:
            return
        c = _conf()
        agora = time.time()
        with self._lock:
            h = list(cam.hist)                                  # cópia: a thread do motor poda (del hist[:100]) durante a leitura
            ult = getattr(self, "_hist_t", 0.0)                 # t_on do último giro já somado (índice quebrava na poda e recontava ~200 giros)
            for i in range(len(h)):
                t_on, t_off, vx, vy = h[i]
                if t_on <= ult:
                    continue
                if t_off is None:
                    break
                d = max(0.0, t_off - t_on)
                if vx:
                    self.pan = min(max(self.pan + math.copysign(d, vx) * (-1 if cam.inv_pan else 1), 0.0), c["pan_total_s"])
                elif vy:
                    self.tilt = min(max(self.tilt + math.copysign(d, vy) * (-1 if cam.inv_tilt else 1), 0.0), c["tilt_total_s"])
                self._hist_t = ult = t_on
        if agora - self._ult_salvo > 10:
            self._ult_salvo = agora
            ipcam.salvar_conf(pan_est=round(self.pan, 2), tilt_est=round(self.tilt, 2))

    def _giro_desde(self, t0, eixo):
        """quanto a câmera girou (fração da tela, sinal = sentido) entre t0 e agora, pelo histórico do motor + atraso do motor."""
        cam = self.cam
        if cam is None:
            return 0.0
        c = _conf()
        v = c["pan_v"] if eixo == "pan" else c["tilt_v"]
        agora = time.time()
        tot = 0.0
        for t_on, t_off, vx, vy in cam.hist[-20:]:
            comp = vx if eixo == "pan" else vy
            if not comp:
                continue
            a = t_on + LAT_MOTOR
            b = (t_off if t_off is not None else agora) + LAT_MOTOR
            ini, fim = max(a, t0), min(b, agora)
            if fim > ini:
                inv = cam.inv_pan if eixo == "pan" else cam.inv_tilt
                tot += math.copysign(fim - ini, comp) * (-1 if inv else 1) * v
        return tot

    def _quadro_apos(self, t_min, espera=6.0):
        fim = time.time() + espera
        while time.time() < fim:
            fr, t = G.quadro()
            if fr is not None and t >= t_min:
                return fr
            time.sleep(0.03)
        return None

    def girar_s(self, dpan_s, dtilt_s, esperar=True):
        """gira dpan_s/dtilt_s segundos de motor (pan + direita, tilt + cima), um eixo de cada vez."""
        cam = self.cam
        if cam is None or not cam.motor:
            return False
        with self._lock:
            for eixo, d in (("pan", dpan_s), ("tilt", dtilt_s)):
                if abs(d) < 0.05 or self._parar_tarefa.is_set():
                    continue
                vx, vy = (math.copysign(1, d), 0) if eixo == "pan" else (0, math.copysign(1, d))
                if not cam.pulso(vx, vy, abs(d)):
                    return False
                t0 = time.time()
                while (cam.movendo() or time.time() - t0 < abs(d)) and not self._parar_tarefa.is_set():
                    time.sleep(0.03)
                if self._parar_tarefa.is_set():
                    cam.parar()
                    time.sleep(0.3)
            self._integrar()
        if esperar:
            time.sleep(LATENCIA)
        return True

    def ir(self, pan_s, tilt_s, esperar=True):
        with self._lock:
            self._integrar()
            return self.girar_s(pan_s - self.pan, tilt_s - self.tilt, esperar)

    # ------------------------------------------------------------ autolocalização pela imagem
    VISTAS = os.path.join(ROOT, "memory", "ptz_vistas")

    def _salvar_vistas(self, fotos):
        """guarda as vistas do mapeamento (pan_s -> jpg 320 px) como "memória visual" do quarto."""
        import json as _j, shutil
        tmp = self.VISTAS + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp, mode=0o700)
        idx = []
        for i, (pan_s, fr) in enumerate(sorted(fotos, key=lambda x: x[0])):
            h, w = fr.shape[:2]
            cv2.imwrite(os.path.join(tmp, f"{i:02d}.jpg"), cv2.resize(fr, (320, int(320 * h / w))), [cv2.IMWRITE_JPEG_QUALITY, 85])
            idx.append({"arq": f"{i:02d}.jpg", "pan": round(pan_s, 2)})
        with open(os.path.join(tmp, "indice.json"), "w") as f:
            _j.dump(idx, f)
        shutil.rmtree(self.VISTAS, ignore_errors=True); os.replace(tmp, self.VISTAS)
        self._vistas = None
        log(f"memória visual: {len(idx)} vistas")

    def _carregar_vistas(self):
        if getattr(self, "_vistas", None) is None:
            import json as _j
            try:
                idx = _j.load(open(os.path.join(self.VISTAS, "indice.json")))
                self._vistas = [(v["pan"], cv2.imread(os.path.join(self.VISTAS, v["arq"]))) for v in idx]
                self._vistas = [(p_, im) for p_, im in self._vistas if im is not None]
            except Exception:
                self._vistas = []
        return self._vistas

    def onde_estou(self, fr):
        """compara o quadro com a memória visual -> (pan_s, pontos) ou None. Vistas perto da estimativa primeiro;
        sem acerto, procura em todas (estimativa perdida)."""
        vs = self._carregar_vistas()
        if not vs or fr is None:
            return None
        c = _conf()
        h, w = fr.shape[:2]
        peq = cv2.resize(fr, (320, int(320 * h / w)))
        perto = sorted(vs, key=lambda v: abs(v[0] - self.pan))
        for grupo in (perto[:4], perto[4:]):
            melhor = None
            for pan_v, im in grupo:
                d = self._desloc(im, peq)
                if d and abs(d[0]) < 0.45 and (melhor is None or d[2] > melhor[1]):
                    melhor = (pan_v - d[0] / c["pan_v"], d[2])   # câmera p/ direita => conteúdo vai p/ esquerda (dx < 0)
            if melhor and melhor[1] >= 25:
                return melhor
        return None

    def _relocalizar(self):
        """sozinha, sem comando: com a câmera parada, olha o que vê e corrige onde acha que está."""
        inicio = time.time()
        while True:
            time.sleep(3)
            try:
                cam = self.cam
                # sem memória visual: monta sozinha uma vez, 2 min depois de subir, se a câmera estiver livre
                if cam is not None and not self._carregar_vistas() and not getattr(self, "_auto_mapa", False) \
                        and time.time() - inicio > 120 and not self.ocupada:
                    self._auto_mapa = True
                    log("sem memória visual do quarto: mapeando sozinha")
                    threading.Thread(target=self.mapear, daemon=True, name="ptz-automapa").start()
                    continue
                if cam is None or cam.movendo() or time.time() - cam.mov_fim < 1.5 or not self._carregar_vistas() \
                        or getattr(self, "_servo", False) or self.ocupada:              # nunca no meio de um ajuste visual / giro
                    continue
                fr, t = G.quadro()
                if fr is None or time.time() - t > 1.0 or t < cam.mov_fim + LATENCIA:
                    continue
                r = self.onde_estou(fr)
                if not r or cam.movendo():
                    continue
                self._integrar()
                tot = _conf()["pan_total_s"]
                novo = min(max(r[0], 0.0), tot)
                if abs(novo - self.pan) > 5 and r[1] < 120:
                    continue                                      # salto grande só com muita certeza (55 pontos deu salto errado)
                if abs(novo - self.pan) > 0.4:
                    log(f"me localizei pela imagem: pan {self.pan:.1f} -> {novo:.1f} ({r[1]} pontos)")
                self.pan = novo
                self._ancorado = time.time()
                self._tilt_ancorado = time.time()
            except Exception as e:
                log(f"relocalizar: {e!r}")

    def ancorar(self, lado):
        """bate no batente FÍSICO do pan (lado -1 = esquerda/0, +1 = direita/total) e zera a estimativa ali.
        A posição é só estimada e deriva (reboot da câmera, rastreio): sem isso o mapa e as posições ficam deslocados."""
        c = _conf()
        tot = c["pan_total_s"]
        self._integrar()
        falta = (tot - self.pan) if lado > 0 else self.pan
        self.girar_s(lado * (falta + 0.12 * tot), 0, esperar=False)   # passa do fim estimado: o motor para sozinho no batente
        self._integrar()
        self.pan = tot if lado > 0 else 0.0
        log(f"ancorado no batente {'direito' if lado > 0 else 'esquerdo'}")

    def ancorar_tilt(self):
        """bate no batente de BAIXO (tilt físico 0) e zera a estimativa: a altura também deriva (achava 1,5 e olhava alto)."""
        c = _conf()
        self._integrar()
        self.girar_s(0, -(self.tilt + 0.25 * c["tilt_total_s"]), esperar=False)
        self._integrar()
        self.tilt = 0.0
        self._tilt_ancorado = time.time()
        log("ancorado no batente de baixo")

    def centro(self):
        c = _conf()
        return self.ir(c["pan_total_s"] / 2, c["tilt_horizonte"])

    def olhar(self, direcao="", fracao=0.6):
        """olha para um lado: fracao = quanto da tela andar."""
        c = _conf()
        d = (direcao or "").lower()
        if d in ("centro", "frente", "meio"):
            return self.centro()
        dp = fracao / c["pan_v"]
        dt = fracao / c["tilt_v"]
        mapa = {"esquerda": (-dp, 0), "direita": (dp, 0), "cima": (0, dt), "baixo": (0, -dt)}
        if d not in mapa:
            return False
        return self.girar_s(*mapa[d], esperar=False)

    # ------------------------------------------------------------ posições com nome
    def salvar_posicao(self, nome, fixa=False):
        """fixa=True: o dono confirmou (pediu para salvar) -> o mapeamento automático não sobrescreve."""
        self._integrar()
        c = ipcam.ler_conf()
        pos = dict(c.get("posicoes") or {})
        nome = {"padrão": "minha posição", "padrao": "minha posição", "posição padrão": "minha posição"}.get(nome.strip().lower(), nome)
        pos[nome.strip().lower()] = [round(self.pan, 2), round(self.tilt, 2)]
        kw = {"posicoes": pos}
        if fixa:
            kw["posicoes_fixas"] = sorted(set(c.get("posicoes_fixas") or []) | {nome.strip().lower()})
        ipcam.salvar_conf(**kw)
        return True

    @staticmethod
    def achar_posicao(nome):
        """posição salva pelo nome exato, ou a primeira que começa/contém o nome ("porta" -> "porta 1", "armário" -> "guarda-roupa")."""
        pos = ipcam.ler_conf().get("posicoes") or {}
        n = (nome or "").strip().lower()
        for w, d in (("um", "1"), ("uma", "1"), ("dois", "2"), ("duas", "2"), ("três", "3"), ("tres", "3"), ("quatro", "4"), ("cinco", "5")):
            n = re.sub(rf"\b{w}\b", d, n)                 # "porta três" -> "porta 3" (fala/LLM escrevem por extenso)
        n = re.sub(r"^(?:a|o)\s+", "", n)
        n = {"armário": "guarda-roupa", "armario": "guarda-roupa", "guarda roupa": "guarda-roupa", "eu": "minha posição",
             "mim": "minha posição", "minha posicao": "minha posição", "onde eu fico": "minha posição", "padrão": "minha posição",
             "padrao": "minha posição", "posição padrão": "minha posição", "posicao padrao": "minha posição"}.get(n, n)
        if n in pos:
            return pos[n]
        for k in sorted(pos):
            if k.startswith(n) or n in k:
                return pos[k]
        return None

    def ir_posicao(self, nome):
        pos = self.achar_posicao(nome)
        if not pos:
            return False
        c = _conf()
        if time.time() - getattr(self, "_ancorado", 0.0) > 86400:     # evita bater no batente a cada 10 min (causava reboot/voz na câmera)
            self.ancorar(1 if pos[0] > c["pan_total_s"] / 2 else -1)
            self._ancorado = time.time()
            self.ancorar_tilt()
        fixas = ipcam.ler_conf().get("posicoes_fixas") or []
        nome_n = next((k for k, v in (ipcam.ler_conf().get("posicoes") or {}).items() if v == pos), "")
        tilt = min(4.0, pos[1]) if nome_n in fixas else c["tilt_horizonte"]     # limita tilt alto p/ não acionar IR P&B
        self.ir(pos[0], tilt, esperar=True)
        return self.centralizar_vendo(re.sub(r"\s*\d+$", "", nome.strip().lower()) or nome)

    def centralizar_vendo(self, alvo, tentativas=5):
        """laço fechado com o modelo de visão: olha, pergunta onde o alvo está na imagem, gira a correção, olha de novo."""
        if alvo in ("minha posição", "eu", "mim"):
            return True
        c = _conf()
        lados = []
        for i in range(tentativas):
            if self._parar_tarefa.is_set():
                return False
            self._pausa_ate = time.time() + 60                  # enquanto ajusta, o seguir não toma a câmera
            fr = self._quadro_apos(time.time() + LATENCIA)
            if fr is None:
                return False
            ok, jpg = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            txt = (G.vlm(jpg.tobytes(), f"Em que parte desta imagem está {alvo}? Responda SÓ uma opção: muito_esquerda, "
                         f"esquerda, centro, direita, muito_direita ou nao_aparece.") or "").lower() if ok else ""
            # faixas (número livre viciava em "50"); "muito" antes do simples
            x = next((v for k, v in (("muito_esq", 10), ("muito esq", 10), ("muito_dir", 90), ("muito dir", 90), ("nao_apar", -1),
                                     ("não apar", -1), ("nao apar", -1), ("esquerd", 30), ("direit", 70), ("centr", 50), ("meio", 50))
                      if k in txt), None)
            if x is None:
                return False
            log(f"vendo {alvo}: {txt[:30]!r} -> {x} (tentativa {i + 1})")
            if x < 0:
                return False                                  # não está na vista: fica na posição do mapa
            if abs(x - 50) <= 10:
                self._ancorado = time.time()
                return True
            passo = (x - 50) / 100.0 / c["pan_v"] * (0.5 ** sum(1 for d in lados if d != (x > 50)))   # trocou de lado: passo pela metade
            lados.append(x > 50)
            self._servo = True
            try:
                self.girar_s(passo, 0, esperar=False)
            finally:
                self._servo = False
        return True

    def localizar_dono(self, aviso=None):
        """vai primeiro à posição padrão do dono (a que ELE gravou); só varre o quarto se não estiver lá."""
        if self.apontar_externo():                              # as câmeras fixas já te veem: direto, sem varrer
            self.definir_modo("seguir")
            msg = "Te achei pelas câmeras fixas. Seguindo você."
            (aviso or (lambda *_: None))(msg)
            return msg
        pos = self.achar_posicao("minha posição")
        sentado = bool(G.sentado())                             # a câmera do notebook vê o dono sentado: ele está no lugar dele
        if pos and self.disponivel():
            self.ir_posicao("minha posição")
            for _ in range(8 if sentado else 4):                # ~3 s olhando ali (~6 s se a nativa confirma que está sentado)
                fr = self._quadro_apos(time.time() + LATENCIA)
                ps = [q for q in self.pose().pessoas(fr) if q["conf"] >= 0.45 and q["kp"] >= 3] if fr is not None else []
                if ps and self._pessoa_real(fr, max(ps, key=lambda q: q["conf"])):
                    self._centralizar_rapido(lambda f: (self.pose().pessoas(f) or [None])[0])
                    self.definir_modo("seguir")
                    msg = "Te achei no seu lugar de sempre. Seguindo você."
                    (aviso or (lambda *_: None))(msg)
                    return msg
                time.sleep(0.5)
            # 16/10: aqui ela dizia "apontei para lá" SEM te ver (a posição salva tinha derivado p/ a mesa) e parava.
            # A nativa te vê sentado mas a PTZ não te achou ali: a posição salva está errada -> esquece (se não for fixa) e varre.
            if sentado and "minha posição" not in (ipcam.ler_conf().get("posicoes_fixas") or []):
                pos_ = dict(ipcam.ler_conf().get("posicoes") or {})
                if pos_.pop("minha posição", None) is not None:
                    ipcam.salvar_conf(posicoes=pos_)
                    log("localizar: não te vi na 'minha posição' com a nativa te vendo sentado: apaguei a posição (reaprende ao te achar)")
        r = self.procurar("você", True)
        (aviso or (lambda *_: None))(r)
        return r

    def nome_da_posicao(self, pan_s):
        c = _conf()
        pos = ipcam.ler_conf().get("posicoes") or {}
        perto = sorted(((abs(p[0] - pan_s), n) for n, p in pos.items()))
        if perto and perto[0][0] < 0.3 / c["pan_v"]:
            return f"perto de {perto[0][1]}"
        f = pan_s / max(0.1, c["pan_total_s"])
        return "à esquerda" if f < 0.36 else ("à direita" if f > 0.64 else "no centro")

    # ------------------------------------------------------------ tarefas
    def _tarefa(self, rotulo):
        if self.ocupada:
            return False
        self.ocupada = rotulo
        self._parar_tarefa.clear()
        return True

    def _fim_tarefa(self):
        self.ocupada = None
        self._integrar()

    def _varrer_continuo(self, a_cada_quadro, foto_a_cada=None, desde_atual=False, tilt=None):
        """gira SEM parar (a velocidade é fixa: parar e esperar só perde tempo). a_cada_quadro(frame, t) -> True interrompe.
        desde_atual: parte de onde está rumo à ponta mais longe e volta varrendo o resto (procurar/localizar começa já);
        senão vai à ponta mais perto e cruza o curso todo (olhar em volta: fotos em ordem). -> fotos [(pan_s, frame)]."""
        c = _conf()
        cam = self.cam
        total = c["pan_total_s"]
        self._integrar()
        meio_t = c["tilt_horizonte"] if tilt is None else tilt
        if desde_atual:
            if abs(self.tilt - meio_t) > c["tilt_total_s"] * 0.15:
                self.ir(self.pan, meio_t, esperar=False)
            longe = 1 if self.pan < total / 2 else -1
            pernas = [(longe, (total - self.pan) if longe > 0 else self.pan), (-longe, total)]
        else:
            ir_dir = self.pan < total / 2
            self.ancorar(-1 if ir_dir else 1)                             # começa no batente REAL mais perto
            self.ir(self.pan, meio_t, esperar=True)                       # tilt no meio
            pernas = [(1 if ir_dir else -1, total)]
        fotos, ult_foto, ult_t = [], -1e9, time.time()
        andou_tot, coberto = 0.0, 0.0
        self.cobertura = (0, total)
        try:
            for sinal, dist in pernas:
                if self._parar_tarefa.is_set():
                    break
                pan0 = self.pan
                cam.mover(sinal, 0)
                t_ini = time.time()
                self._pausa_var = 0.0                       # tempo parado conferindo uma pessoa (teste freia e retoma)
                parou = False
                while time.time() - t_ini - self._pausa_var < dist + LATENCIA and not self._parar_tarefa.is_set():
                    time.sleep(0.02)
                    fr, t = G.quadro()
                    if fr is None or t <= ult_t:
                        if time.time() - ult_t > 4:
                            parou = True                            # vídeo parou
                            break
                        continue
                    ult_t = t
                    andou = min(dist, max(0.0, (t - LAT_VIDEO) - (t_ini + self._pausa_var + LAT_MOTOR)))
                    coberto = max(coberto, min(total, andou_tot + andou) if desde_atual else andou)
                    self.cobertura = (coberto, total)
                    if foto_a_cada and andou - ult_foto >= foto_a_cada:
                        ult_foto = andou
                        fotos.append((pan0 + sinal * andou, fr.copy()))
                    if a_cada_quadro and a_cada_quadro(fr, t):
                        parou = True
                        break
                cam.mover(0, 0)
                time.sleep(0.4)
                self._integrar()
                andou_tot += dist
                if parou:
                    break
        finally:
            if cam.vel != (0.0, 0.0):
                cam.mover(0, 0)
            self._integrar()
        return fotos

    def olhar_em_volta(self):
        if not self.disponivel():
            return "Não consigo mexer a câmera agora: " + ipcam.status() + "."
        if not self._tarefa("olhando em volta"):
            return "Estou ocupada com a câmera agora (" + str(self.ocupada) + ")."
        try:
            c = _conf()
            p0, t0 = self.pan, self.tilt
            fotos = self._varrer_continuo(None, foto_a_cada=0.75 / c["pan_v"])
            self.ir(p0, t0, esperar=False)
            if not fotos:
                return "Girei a câmera, mas o vídeo não chegou. Não consegui ver o quarto."
            fotos = sorted(fotos, key=lambda x: x[0])
            lado = 1280 // max(1, len(fotos))
            tiras = [cv2.resize(f, (lado, int(lado * f.shape[0] / f.shape[1]))) for _, f in fotos]
            ok, jpg = cv2.imencode(".jpg", np.hstack(tiras), [cv2.IMWRITE_JPEG_QUALITY, 85])
            txt = G.vlm(jpg.tobytes(), "São vistas do quarto lado a lado, da esquerda para a direita, tiradas girando a câmera. "
                                       "Conte como quem acabou de olhar em volta, sem falar em imagem, faixa ou foto: "
                                       "o ambiente, móveis, portas e janelas e se há alguém. Só o que está visível.") if ok else None
            return txt or "Girei a câmera pelo quarto, mas o modelo de visão não respondeu. Não vou inventar o que vi."
        finally:
            self._fim_tarefa()

    REFERENCIAS = ("porta", "guarda-roupa", "cama")

    def mapear(self):
        """decora os objetos de referência do quarto: gira o curso todo, pergunta ao VLM em cada vista onde estão
        porta(s), guarda-roupa e cama (esquerda/centro/direita da vista) e salva cada um como posição com nome.
        Portas viram "porta 1", "porta 2"... da esquerda para a direita; se eu (dono) aparecer, salva "minha posição"."""
        if not self.disponivel():
            return "Não consigo mexer a câmera agora: " + ipcam.status() + "."
        if not self._tarefa("mapeando o quarto"):
            return "Estou ocupada com a câmera agora (" + str(self.ocupada) + ")."
        try:
            c = _conf()
            p0, t0 = self.pan, self.tilt
            fotos = self._varrer_continuo(None, foto_a_cada=0.6 / c["pan_v"])
            self.ir(p0, t0, esperar=False)
            if not fotos:
                return "Girei a câmera, mas o vídeo não chegou. Não consegui mapear o quarto."
            try:
                self._salvar_vistas(fotos)
            except Exception as e:
                log(f"vistas: {e!r}")
            frac = {"esquerda": 0.2, "centro": 0.5, "meio": 0.5, "direita": 0.8}
            achados = {n: [] for n in self.REFERENCIAS}
            eu = []
            respondeu = 0
            for pan_s, fr in sorted(fotos, key=lambda x: x[0]):
                ok, jpg = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                txt = (G.vlm(jpg.tobytes(), "Nesta vista aparecem porta, guarda-roupa (armário) ou cama? Responda SÓ uma linha no formato "
                             "porta=esquerda|centro|direita|não; guarda-roupa=...; cama=... (onde fica na imagem). Não invente.") or "") if ok else ""
                respondeu += bool(txt)
                for n in self.REFERENCIAS:
                    m = re.search(re.escape(n.split("-")[0]) + r"\w*[^=;:\n]*[=:]\s*([a-zçãé]+)", txt.lower())
                    if m and m.group(1) in frac:
                        achados[n].append(pan_s + (frac[m.group(1)] - 0.5) / c["pan_v"])
                try:
                    ps = [q for q in self.pose().pessoas(fr) if q["conf"] >= 0.55 and q["kp"] >= 4]
                except Exception:
                    ps = []
                if ps:
                    x = self._ponto(ps[0])[0]
                    eu.append(pan_s + (x - 0.5) / c["pan_v"])
            if not respondeu:
                return "Girei pelo quarto, mas o modelo de visão não respondeu. Não salvei nada para não inventar."
            junta = 0.35 / c["pan_v"]                         # vistas vizinhas veem o mesmo objeto: agrupa o que está perto
            def grupos(v):
                out = []
                for x in sorted(v):
                    if out and x - out[-1][-1] < junta:
                        out[-1].append(x)
                    else:
                        out.append([x])
                return [sum(g) / len(g) for g in out]
            tot = c["pan_total_s"]
            salvo = {}
            for n, v in achados.items():
                g = grupos(v)
                if not g:
                    continue
                if n == "porta":
                    for i, x in enumerate(g[:4], 1):
                        salvo[f"porta {i}"] = x
                else:
                    salvo[n] = max(g, key=lambda gx: sum(1 for y in v if abs(y - gx) < junta))   # o grupo mais visto
            if eu:
                salvo["minha posição"] = sum(eu) / len(eu)
            if not salvo:
                return "Girei pelo quarto, mas não reconheci porta, guarda-roupa nem cama com segurança."
            cf = ipcam.ler_conf()
            pos = dict(cf.get("posicoes") or {})
            fixas = set(cf.get("posicoes_fixas") or [])
            salvo = {n: x for n, x in salvo.items() if n not in fixas}     # o que o dono confirmou vale mais que o palpite do VLM
            for n, x in salvo.items():
                pos[n] = [round(min(max(x, 0.0), tot), 2), round(c["tilt_horizonte"], 2)]
            ipcam.salvar_conf(posicoes=pos)
            log("mapa: " + ", ".join(f"{n}={pos[n][0]}" for n in salvo))
            return "Decorei: " + ", ".join(salvo) + ". É só pedir para eu olhar para qualquer um deles."
        finally:
            self._fim_tarefa()

    def procurar(self, alvo, seguir_depois=False):
        """pessoa: giro contínuo com yolov8n-pose em todo quadro (rápido). Objeto: YOLOX nas 80 classes, senão VLM."""
        import senses
        if not self.disponivel():
            return "Não consigo mexer a câmera agora: " + ipcam.status() + "."
        if not self._tarefa(f"procurando {alvo}"):
            return "Estou ocupada com a câmera agora (" + str(self.ocupada) + ")."
        alvo_n = (alvo or "").strip().lower()
        eu = alvo_n in ("eu", "mim", "me", "iann", "o iann", "dono", "você")
        pessoa = eu or alvo_n in ("alguém", "alguem", "gente", "pessoa", "uma pessoa")
        classe = None if pessoa else next((k for k in senses.classes_objetos() if k.lower() == alvo_n or alvo_n in k.lower().split("/")), None)
        achado = {}
        prox = [0.0]
        seguidos = []                                     # pessoa precisa aparecer em 3 quadros seguidos (1 quadro = falso positivo comum)

        def teste(fr, t):
            if pessoa:
                # 1º sinal de gente (até só o corpo, de perto e sem rosto): FREIA já e confere com a câmera PARADA.
                # Antes exigia 3 quadros com pose forte girando + VLM com o motor andando => passava do dono e ia até o fim.
                ps = [q for q in self.pose().pessoas(fr, conf=0.30) if q["kp"] >= 2 or (q["caixa"][3] - q["caixa"][1]) > 0.25]
                if not ps and eu:                                    # de perto o dono é só ROSTO (pose não acha corpo): rosto também freia
                    t_r, rs_ = G.rostos()
                    if time.time() - t_r < 1.2:
                        ps = [{"caixa": (max(0.0, r[0] - (r[2] - r[0])), r[1], min(1.0, r[2] + (r[2] - r[0])), min(1.0, r[3] + 2.5 * (r[3] - r[1]))),
                               "conf": 0.9, "kp": 0, "cabeca": ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)} for r in rs_ if r[3] - r[1] >= 0.06]
                if not ps or time.time() < prox[0]:
                    return False
                cam_ = self.cam
                v_ = cam_.vel if cam_ is not None else (0.0, 0.0)
                t_freio = time.time()
                if cam_ is not None:
                    cam_.mover(0, 0)
                ok_, nao_ = False, 0
                for _ in range(5 if eu else 3):                      # quadros já com a câmera parada (eu: espera o rosto, ~1 Hz)
                    fr2 = self._quadro_apos(time.time() + LATENCIA)
                    if fr2 is None:
                        continue
                    ps2 = [q for q in self.pose().pessoas(fr2, conf=0.3) if q["kp"] >= 2 or q["conf"] >= 0.5]
                    if not ps2 and eu:                               # parado: o rosto (YuNet ~1 Hz) também vale como pessoa
                        time.sleep(0.6)
                        t_r, rs_ = G.rostos()
                        if time.time() - t_r < 1.5:
                            ps2 = [{"caixa": (max(0.0, r[0] - (r[2] - r[0])), r[1], min(1.0, r[2] + (r[2] - r[0])), min(1.0, r[3] + 2.5 * (r[3] - r[1]))),
                                    "conf": 0.9, "kp": 0, "cabeca": ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)} for r in rs_ if r[3] - r[1] >= 0.06]
                    if not ps2:
                        continue
                    q2 = max(ps2, key=lambda q: q["conf"])
                    d0 = G.dono()                                    # rosto do dono dentro da caixa: é ele, sem VLM
                    if d0 and time.time() - d0[0] < 1.5:
                        dx0, dy0 = (d0[1][0] + d0[1][2]) / 2, (d0[1][1] + d0[1][3]) / 2
                        q_d = self._dono_em(ps2, 1.5)
                        if q_d is not None:
                            achado.update(frame=fr2, t=time.time(), pessoa=q_d); ok_ = True
                            break
                    if eu:                                           # 16/10: só o SEU rosto confirma (amigos no quarto viravam "achei você")
                        cor_ = self._cor_confere(fr2, q2)
                        sozinho = not G.multidao()                   # só o dono no quarto (fixas): cor não pode vetar
                        if cor_ is True or (cor_ is None and q2["kp"] >= 5 and not G.sentado()):
                            log(f"procurar: é você pela {'cor da roupa (nativa)' if cor_ else 'pose nítida'}")
                            achado.update(frame=fr2, t=time.time(), pessoa=q2); ok_ = True
                            break
                        if sozinho and self._pessoa_real(fr2, q2):   # sozinho: qualquer pessoa REAL é você (de perto o corpo sai cortado)
                            log("procurar: só você no quarto e é gente de verdade: é você")
                            achado.update(frame=fr2, t=time.time(), pessoa=q2); ok_ = True
                            break
                        if cor_ is False and not sozinho:
                            log("procurar: há mais gente e a roupa é de outra cor que a sua: não é você")
                            break
                        time.sleep(0.4)
                        continue
                    if self._pessoa_real(fr2, q2):
                        achado.update(frame=fr2, t=time.time(), pessoa=q2); ok_ = True
                        break
                    nao_ += 1                                        # só descarta com 2 "não" (1 VLM errado fazia passar do dono)
                    if nao_ >= 2:
                        break
                if ok_:
                    log("procurar: freei no 1º sinal de pessoa e confirmei parada")
                    return True
                prox[0] = time.time() + 1.2                          # falso: segue girando e ignora este trecho por ~1 s
                self._pausa_var = getattr(self, "_pausa_var", 0.0) + (time.time() - t_freio)
                if cam_ is not None and v_ != (0.0, 0.0):
                    cam_.mover(*v_)
                return False
            agora = time.time()
            if agora < prox[0]:
                return False
            if classe:
                prox[0] = agora + 0.6
                hits = [h for h in G.detectar(fr) if h[0] == classe and h[1] >= 0.35]   # YOLOE pontua mais baixo que o YOLOX
                if hits:
                    achado.update(frame=fr, t=t, caixa=max(hits, key=lambda h: h[1])[2])
                    return True
                return False
            prox[0] = agora + 0.1
            ok, jpg = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            r = (G.vlm(jpg.tobytes(), f"Existe {alvo} nesta imagem? Responda começando com SIM ou NÃO e, se sim, diga onde.") or "") if ok else ""
            if r.strip().upper().startswith("SIM"):
                achado.update(frame=fr, t=t, onde=r)
                return True
            return False
        try:
            if pessoa:
                # o dono costuma estar SENTADO (abaixo do horizonte): 1ª volta na altura da posição padrão dele, 2ª no horizonte
                # 1º as câmeras FIXAS (nativa/porta): se veem alguém, vai direto para lá em vez de varrer devagar
                if G.alvo_externo(None) and self.apontar_externo():
                    fr_ = self._quadro_apos(time.time() + LATENCIA)
                    ps_ = [q for q in self.pose().pessoas(fr_) if q["conf"] >= 0.45] if fr_ is not None else []
                    if ps_:
                        log("procurar: achei pelas câmeras fixas, sem varrer")
                        achado.update(frame=fr_, t=time.time(), pessoa=max(ps_, key=lambda q: q["conf"]))
                c_ = _conf()
                baixo = (self.achar_posicao("minha posição") or [None, None])[1]
                baixo = baixo if baixo is not None and baixo <= c_["tilt_horizonte"] else max(1.0, c_["tilt_horizonte"] - 1.5)   # -6 batia no batente (0,5): só pernas cortadas
                baixo = max(baixo, c_["tilt_min_busca"])      # tilt 2 = antenas da própria câmera viravam "pessoa" gigante
                if time.time() - getattr(self, "_tilt_ancorado", 0.0) > 120:
                    self.ancorar_tilt()
                # alturas da varredura (camera_ptz.json "tilt_busca"): a PTZ fica NA MESA, abaixo do rosto de quem está sentado
                # -> 1º olha um pouco para cima (8), depois baixo e alto. Antes só "baixo" (4,5) e horizonte: passava por cima/baixo dele.
                alturas = [float(x) for x in (c_.get("tilt_busca") or [8.0, baixo, 11.0])]
                for i_, alt_ in enumerate(alturas):
                    if achado or self._parar_tarefa.is_set():
                        break
                    seguidos.clear()
                    self.ir(self.pan, alt_, esperar=True)
                    log(f"procurando você na altura {alt_:.1f} ({i_ + 1}/{len(alturas)})")
                    self._varrer_continuo(teste, desde_atual=True, tilt=alt_)
            else:
                self._varrer_continuo(teste, desde_atual=True)
            if not achado:
                vista, total = self.cobertura
                if self._parar_tarefa.is_set():
                    return f"Parei a procura por {alvo} no meio, sem encontrar."
                if total and vista < total * 0.9:
                    return f"Não encontrei {alvo}, mas o vídeo falhou e só cobri {100 * vista / total:.0f}% do giro."
                return f"Olhei o quarto inteiro e não encontrei {'você' if eu else alvo}."
            if pessoa:
                self._parar_tarefa.clear()
                self._visto = time.time()                         # achou: a busca automática não dispara de novo em seguida
                self._ult_auto_proc = time.time()
                self._centralizar_rapido(lambda fr: (self.pose().pessoas(fr) or [None])[0])
            elif achado.get("caixa"):
                x, y, w, h = achado["caixa"]
                H, W = achado["frame"].shape[:2]
                self._mirar((x + w / 2) / W - 0.5, 0.5 - (y + h / 2) / H, achado["t"])
            try:
                r_ = self.onde_estou(self._quadro_apos(time.time() + LATENCIA))   # o nome do lugar vem do que ela VÊ
                if r_:
                    self.pan = min(max(r_[0], 0.0), _conf()["pan_total_s"])
            except Exception:
                pass
            lugar = self.nome_da_posicao(self.pan)
            extra = ""
            if achado.get("onde") and "." in achado["onde"]:
                extra = " " + achado["onde"].split(".", 1)[-1].strip()
            ok, jpg = cv2.imencode(".jpg", achado["frame"])
            G.avisar(None, False, jpg.tobytes() if ok else None)
            quem = "você" if eu else alvo
            if pessoa and seguir_depois:
                self.ocupada = None
                self.definir_modo("seguir")
                return f"Achei {quem} {lugar} do quarto. Agora estou te seguindo."
            return f"Achei {quem} {lugar} do quarto e deixei a câmera apontada.{extra}".strip()
        finally:
            if self.ocupada and self.ocupada.startswith("procurando"):
                self._fim_tarefa()

    def _mirar(self, ex, ey, t_quadro):
        """leva o ponto (ex, ey) — fração da tela a partir do centro, + direita / + cima — para o centro (pulsos, com preditor)."""
        c = _conf()
        ex -= self._giro_desde(t_quadro - LAT_VIDEO, "pan")
        ey -= self._giro_desde(t_quadro - LAT_VIDEO, "tilt")
        dp = ex / c["pan_v"] if abs(ex) > 0.06 else 0.0
        dt = ey / c["tilt_v"] if abs(ey) > 0.08 else 0.0
        if dp or dt:
            self.girar_s(dp, dt, esperar=False)

    def _centralizar_rapido(self, detector, tentativas=3):
        for _ in range(tentativas):
            cam = self.cam
            fr = self._quadro_apos(cam.mov_fim + LATENCIA if cam else time.time())
            if fr is None:
                return
            p = detector(fr)
            if not p:
                return
            x, y = self._ponto(p)
            ex, ey = x - 0.5, ALVO_Y - y
            if abs(ex) < 0.08 and abs(ey) < 0.10:
                return
            self._mirar(ex, ey, time.time())

    # ------------------------------------------------------------ SEGUIR em tempo real
    def _escolher(self, ps, t):
        """qual pessoa seguir: a que está perto de onde o alvo estava (já descontado o giro); senão o dono; senão a maior."""
        if not ps:
            return None
        if self.alvo and t - self.alvo["t"] < 4.0:   # trava lembra o alvo 4 s (1,5 s perdia ao virar de lado/sentar)
            gx = self._giro_desde(self.alvo["t"] - LAT_VIDEO, "pan") - self._giro_desde(t - LAT_VIDEO, "pan")
            gy = self._giro_desde(self.alvo["t"] - LAT_VIDEO, "tilt") - self._giro_desde(t - LAT_VIDEO, "tilt")
            dt_a = min(1.0, t - self.alvo["t"])                 # onde ele DEVE estar: cena anda ao contrário do giro + a velocidade dele
            vel_ = getattr(self, "_vel", (0.0, 0.0))            # _vel só existe depois do 1º passo do seguir
            px = self.alvo["x"] - gx + vel_[0] * dt_a
            py = self.alvo["y"] + gy - vel_[1] * dt_a     # _vel[1] é de ey (= ALVO_Y - y): sinal invertido em y
            perto = min(ps, key=lambda p: abs(self._ponto(p)[0] - px) + abs(self._ponto(p)[1] - py))
            if abs(self._ponto(perto)[0] - px) + abs(self._ponto(perto)[1] - py) < 0.35:
                return perto                                    # continua no MESMO alvo
            # longe de onde o alvo estava: é outra coisa -> passa pela checagem de alvo novo abaixo
        d0 = G.dono()
        if d0 and time.time() - d0[0] < 1.5:                    # rosto do DONO dentro da caixa: é gente, trava já (VLM parava o laço 1-2 s)
            dx0, dy0 = (d0[1][0] + d0[1][2]) / 2, (d0[1][1] + d0[1][3]) / 2
            q_d = self._dono_em(ps, 1.5)
            if q_d is not None:
                return q_d
        if G.sentado() and not any(self._dono_na_caixa(p_, 3.0) for p_ in ps):
            fr_c = getattr(self, "_fr_escolha", None)          # a nativa te vê sentado: alvo NOVO só com o SEU rosto ou a SUA roupa
            ps = [p_ for p_ in ps if self._cor_confere(fr_c, p_) is True]
            if not ps:
                return None
        fr = getattr(self, "_fr_escolha", None)
        if fr is not None:                                      # travando num alvo NOVO: só gente de verdade
            ps = [q for q in sorted(ps, key=lambda q: -q["conf"])[:2] if self._pessoa_real(fr, q)]
            if not ps:
                return None
        d = G.dono()
        if d and time.time() - d[0] < 3:
            dx = (d[1][0] + d[1][2]) / 2
            dy = (d[1][1] + d[1][3]) / 2
            q_d = self._dono_em(ps, 3.0)
            if q_d is not None:
                return q_d
        return max(ps, key=lambda p: (p["caixa"][2] - p["caixa"][0]) * (p["caixa"][3] - p["caixa"][1]))

    @staticmethod
    def _rosto_na_caixa(q, idade=2.0):
        """um rosto (de qualquer pessoa, YuNet ~1 Hz) dentro da caixa = gente de verdade. Antena da própria câmera, móvel e
        roupa não têm rosto; de PERTO (PTZ na mesa, ao lado do dono) o corpo enche o quadro e o VLM dizia "não" ao dono."""
        t_r, rs = G.rostos()
        x0, y0, x1, y1 = q["caixa"]
        if time.time() - t_r > idade or not rs or x1 > 1.5:
            return False
        for r in rs:
            cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            if r[3] - r[1] >= 0.05 and x0 <= cx <= x1 and y0 <= cy <= y1:   # rosto minúsculo (reflexo no espelho) não conta
                return True
        return False

    @staticmethod
    def _dono_em(ps, idade=2.5):
        """a pessoa cuja CABEÇA está no rosto reconhecido como o dono (ou None). Só "rosto dentro da caixa" não basta:
        de perto a caixa de um amigo em pé ao lado enche o quadro e engolia o rosto do dono (16/10)."""
        d = G.dono()
        if not d or time.time() - d[0] > idade:
            return None
        fx0, fy0, fx1, fy1 = d[1]
        cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
        tol = max(0.10, 1.2 * max(fx1 - fx0, fy1 - fy0))
        melhor, dist = None, 9.0
        for q in ps:
            x0, y0, x1, y1 = q["caixa"]
            if x1 > 1.5 or not (x0 <= cx <= x1 and y0 <= cy <= y1):
                continue
            hx, hy = q.get("cabeca") or ((x0 + x1) / 2, y0 + (y1 - y0) * 0.15)
            d_ = math.hypot(hx - cx, hy - cy)
            if d_ < tol and d_ < dist:
                melhor, dist = q, d_
        return melhor

    @staticmethod
    def _cor_confere(fr, q):
        """a roupa desta pessoa tem a cor da roupa do dono (nativa, < 30 min)? True/False; None = não dá para saber
        (quadro P&B do infravermelho, sem medida da nativa, tronco fora do quadro). De perto o rosto do dono pela PTZ
        não passa do limiar (0,05-0,31 medido 16/10) e o amigo de laranja virava "você": a cor separa os dois."""
        cd = G.camisa_dono()
        if not cd or time.time() - cd[0] > 1800 or fr is None:          # roupa vale 30 min (não muda em minutos)
            return None
        H, W = fr.shape[:2]
        x0, y0, x1, y1 = q["caixa"]
        if x1 <= 1.5:
            x0, x1, y0, y1 = x0 * W, x1 * W, y0 * H, y1 * H
        bw, bh = x1 - x0, y1 - y0
        reg = fr[int(y0 + 0.40 * bh):int(y0 + 0.75 * bh), int(x0 + 0.30 * bw):int(x1 - 0.30 * bw)]
        if reg.size < 300:
            return None
        hsv = cv2.cvtColor(np.ascontiguousarray(reg[::2, ::2]), cv2.COLOR_BGR2HSV).reshape(-1, 3)
        quadro_s = float(cv2.cvtColor(fr[::8, ::8], cv2.COLOR_BGR2HSV)[..., 1].mean())
        if quadro_s < 18:
            return None                                         # infravermelho (P&B): cor não diz nada
        h, s, _v = (float(v) for v in np.median(hsv, axis=0))
        dh, ds = cd[1][0], cd[1][1]
        if ds < 60:                                             # roupa do dono neutra (cinza/preto/branco)
            return s < 80
        if s < 50:
            return False
        return min(abs(h - dh), 180 - abs(h - dh)) < 18        # matiz OpenCV 0-180

    @staticmethod
    def _dono_na_caixa(q, idade=2.5):
        """o rosto do dono está na cabeça desta pessoa?"""
        return PTZ._dono_em([q], idade) is q

    def _pessoa_real(self, fr, q):
        """confirma com o modelo de visão que a detecção é gente de verdade (entalhe do guarda-roupa, roupa pendurada,
        pôster viravam "pessoa" e ela seguia o móvel). Falsos ficam marcados por posição (pan) por 10 min."""
        c = _conf()
        H, W = fr.shape[:2]
        x0, y0, x1, y1 = q["caixa"]
        onde = self.pan + ((x0 + x1) / 2 / (W if x1 > 1.5 else 1) - 0.5) / c["pan_v"]
        agora = time.time()
        if self._rosto_na_caixa(q):
            self._reais = [(p_, t_) for p_, t_ in getattr(self, "_reais", []) if agora - t_ < 20] + [(onde, agora)]
            self._fantasmas = [(p_, t_) for p_, t_ in getattr(self, "_fantasmas", []) if abs(p_ - onde) >= 1.5]
            log(f"checagem de pessoa em pan {onde:.1f}: rosto dentro da caixa (sem VLM)")
            return True
        self._fantasmas = [(p_, t_) for p_, t_ in getattr(self, "_fantasmas", []) if agora - t_ < 180]
        if sum(1 for p_, _ in self._fantasmas if abs(p_ - onde) < 1.5) >= 2:
            return False                                        # 2 "não" no mesmo ponto: é móvel (1 só = quadro borrado do dono)
        self._reais = [(p_, t_) for p_, t_ in getattr(self, "_reais", []) if agora - t_ < 20]
        if any(abs(p_ - onde) < 3 for p_, _ in self._reais):
            self._reais.append((onde, agora))
            return True                                         # já confirmei gente aqui há pouco: não pergunta de novo
        if x1 <= 1.5:                                           # caixa normalizada -> pixels
            x0, x1, y0, y1 = x0 * W, x1 * W, y0 * H, y1 * H
        rec = fr.copy()
        cv2.rectangle(rec, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 3)
        ok, jpg = cv2.imencode(".jpg", rec, [cv2.IMWRITE_JPEG_QUALITY, 90])
        r = (G.vlm(jpg.tobytes(), "O que está dentro do retângulo vermelho é uma pessoa de verdade (não estátua, desenho, "
                                  "entalhe, roupa pendurada, boneco ou foto)? Responda SÓ sim ou não.") or "").strip().lower() if ok else ""
        try:
            cv2.imwrite("/tmp/friday-checagem.jpg", rec)          # última checagem (quadro inteiro + retângulo)
        except Exception:
            pass
        log(f"checagem de pessoa em pan {onde:.1f} ({int(x1 - x0)}x{int(y1 - y0)} px): VLM {r[:20]!r}")
        if r.startswith("n"):
            self._fantasmas.append((onde, agora))
            try:
                cv2.imwrite("/tmp/friday-fantasma.jpg", rec if rec.size else fr)   # p/ conferir o que foi descartado
            except Exception:
                pass
            log(f"descartei falsa pessoa em pan {onde:.1f} (VLM: {r[:20]!r})")
            return False
        self._reais.append((onde, agora))
        self._fantasmas = [(p_, t_) for p_, t_ in self._fantasmas if abs(p_ - onde) >= 1.5]   # "sim" ali apaga os "não"
        return True                                             # sim ou VLM fora: não bloqueia o seguir

    @staticmethod
    def _ponto(p):
        """ponto a manter no centro: a cabeça (ou o alto do corpo)."""
        if p["cabeca"]:
            return p["cabeca"]
        x0, y0, x1, y1 = p["caixa"]
        return ((x0 + x1) / 2, y0 + (y1 - y0) * 0.2)

    def _ir_externo(self, t):
        """alvo perdido: as câmeras fixas sabem onde ele está? Gira para lá com um PULSO não bloqueante (o próprio vídeo
        assume e freia quando a pessoa reaparece). True = começou a girar."""
        if time.time() - getattr(self, "_ult_externo", 0.0) < 1.5 or getattr(self, "ocupada", None):
            return False
        h_ = getattr(self.cam, "hist", None)
        if h_ and h_[-1][1] is None:
            return False                                    # motor ainda girando: o pan integrado estaria defasado
        e = G.alvo_externo(self.pan)
        if not e or e["conf"] < 0.3:
            return False
        self._integrar()
        c = _conf()
        dp, dt = e["pan"] - self.pan, e["tilt"] - self.tilt
        if abs(dp) < 0.4 / c["pan_v"] and abs(dt) < 0.4 / c["tilt_v"]:
            return False                                    # já está no quadro: o problema é o detector, não a mira
        ult = getattr(self, "_ext_alvo", None)              # já fui para esse mesmo ponto há pouco e não te achei: não gira de novo
        if ult and abs(e["pan"] - ult[0]) < 5.0 and time.time() - ult[1] < 25:
            return False
        self._ext_alvo = (e["pan"], time.time())
        self._ult_externo = time.time()
        self._ext_fonte = "fixas"
        eixo_pan = abs(dp) >= 0.4 / c["pan_v"]
        d = dp if eixo_pan else dt
        log(f"mundo: alvo perdido; câmeras fixas ({'+'.join(e['cams'])}, {e['conf']:.0%}) apontam pan {e['pan']:.1f} tilt {e['tilt']:.1f}")
        if self.cam is None or not self.cam.pulso(math.copysign(1, d) if eixo_pan else 0, 0 if eixo_pan else math.copysign(1, d), abs(d)):
            return False
        self._eixo, self._sinal = "externo", (1 if d > 0 else -1)
        self._ext_fim = time.time() + abs(d) + LAT_MOTOR
        return True

    def _passo_externo(self, t):
        """giro pelas fixas em andamento: quando o pulso termina, dá ~1 s para o vídeo reencontrar antes da busca cega."""
        if time.time() < getattr(self, "_ext_fim", 0.0):
            return
        self._integrar()
        self._eixo, self._visto, self._lado = None, t, 0          # sem _lado: a busca cega não desfaz o apontamento
        if getattr(self, "_ext_fonte", "fixas") == "fixas":       # 2,5 s para o vídeo te achar ali; senão o mapa das fixas errou
            self._ext_conferir = time.time() + 2.5

    def apontar_externo(self):
        """vai para onde as câmeras fixas veem alguém e confirma no próprio vídeo. Devolve True se achou gente lá."""
        e = G.alvo_externo(None)
        if not e or e["conf"] < 0.3 or not self.disponivel():
            return False
        log(f"mundo: apontando pelas fixas ({'+'.join(e['cams'])}) pan {e['pan']:.1f} tilt {e['tilt']:.1f}")
        self._integrar()
        antes = (self.pan, self.tilt)
        self.ir(e["pan"], max(e["tilt"], _conf()["tilt_min_busca"]), esperar=True)
        self._integrar()
        if self._parar_tarefa.is_set() or (abs(e["pan"] - antes[0]) > 1 and abs(self.pan - antes[0]) < 0.3):
            return False                                    # cancelado ou o motor não andou: não confere pessoa no lugar errado
        for _ in range(3):
            fr = self._quadro_apos(time.time() + LATENCIA)
            ps = [q for q in self.pose().pessoas(fr) if q["conf"] >= 0.45 and q["kp"] >= 3] if fr is not None else []
            if ps and self._pessoa_real(fr, max(ps, key=lambda q: q["conf"])):
                self._centralizar_rapido(lambda f: (self.pose().pessoas(f) or [None])[0])
                return True
            time.sleep(0.4)
        if not self._parar_tarefa.is_set():
            n_ = G.refutar()
            log(f"mundo: apontei pelas fixas e não havia ninguém: apaguei {n_} par(es) errados")
        return False

    def zoom(self, fator=None, alvo="", pergunta=""):
        """zoom DIGITAL no quadro 1280x720 (a lente é fixa: ContinuousMove com Zoom é aceito e ignorado — medido 15/10/2026).
        Centra no alvo (pessoa/objeto detectado) se pedido; com pergunta, o VLM responde sobre o recorte."""
        try:
            fator = None if fator in (None, "", 0, "auto") else max(1.0, min(4.0, float(fator)))
        except (TypeError, ValueError):
            fator = None                                    # None = automático: o alvo ocupa ~45% da altura do quadro
        fr = G.quadro_hd()
        if fr is None:
            fr, _ = G.quadro()
        if fr is None:
            return "Sem imagem da câmera para dar zoom."
        h, w = fr.shape[:2]
        cx, cy, achou, alt_alvo = 0.5, 0.5, "", 0.0
        a = (alvo or "").strip().lower()
        if a:
            if re.search(r"pessoa|voc[eê]|gente|algu[eé]m|rosto|cara|homem|mulher", a):
                ps = self.pose().pessoas(fr)
                if ps:
                    q = max(ps, key=lambda q: q["conf"])
                    cx, cy = q["cabeca"] or ((q["caixa"][0] + q["caixa"][2]) / 2, (q["caixa"][1] + q["caixa"][3]) / 2)
                    achou = "pessoa"
                    alt_alvo = q["caixa"][3] - q["caixa"][1]
            else:
                for nome, conf, (x, y, bw, bh) in sorted(G.detectar(fr) or [], key=lambda d: -d[1]):
                    if a in str(nome).lower() or str(nome).lower() in a:
                        cx, cy, achou = (x + bw / 2) / w, (y + bh / 2) / h, str(nome)
                        alt_alvo = max(bh / h, bw / w)
                        break
        if fator is None:
            fator = min(4.0, max(1.5, 0.45 / max(0.05, alt_alvo))) if alt_alvo else 2.0
        cw, ch = int(w / fator), int(h / fator)
        x0 = int(min(max(0, cx * w - cw / 2), w - cw))
        y0 = int(min(max(0, cy * h - ch / 2), h - ch))
        rec = cv2.resize(fr[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=cv2.INTER_CUBIC if fator > 1 else cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", rec, [cv2.IMWRITE_JPEG_QUALITY, 90])
        jpg = buf.tobytes() if ok else None
        if jpg:
            with open("/tmp/friday-zoom.jpg", "wb") as f:
                f.write(jpg)
        onde = f" em {achou}" if achou else (f" (não achei {alvo} no quadro, zoom no centro)" if a else "")
        log(f"zoom {fator:.1f}x{onde} ({w}x{h})")
        if pergunta and jpg:
            r = G.vlm(jpg, pergunta + " Responda em português, curto.")
            return (r or "Não consegui analisar a imagem ampliada.").strip()
        return f"Zoom de {fator:.1f}x{onde}. Imagem em /tmp/friday-zoom.jpg."

    def _passo_seguir(self, fr, t):
        cam = self.cam
        if self._eixo == "externo" and time.time() < getattr(self, "_ext_fim", 0.0) - 1.0:
            return                                          # girando para onde as FIXAS te veem: nem detecta no caminho (entalhe/sombra paravam o giro)
        ps = self.pose().pessoas(fr, conf=0.35)
        if not (self.alvo and t - self.alvo["t"] < 4.0):
            ps = [q for q in ps if q["conf"] >= 0.5 and q["kp"] >= 4]      # travar exige pessoa de verdade (pontos do corpo)
        else:
            ps = [q for q in ps if q["kp"] >= 2 or q["conf"] >= 0.6]    # travado: aceita mais fraco (de lado, longe)
        self._pessoas = (t, [p["caixa"] for p in ps])
        self._fr_escolha = fr
        p = self._escolher(ps, t)
        if p is None:
            # sumiu: em 0,5 s pede às câmeras fixas (giro sem bloquear); sem estimativa e com o dono sentado (nativa),
            # volta ao lugar dele; senão procura para o lado onde foi visto por último
            if self._eixo == "externo":
                self._passo_externo(t)
                return
            if getattr(self, "_ext_conferir", 0.0) and time.time() > self._ext_conferir:
                self._ext_conferir = 0.0
                n_ = G.refutar()
                log(f"mundo: as fixas mandaram para pan {self.pan:.1f} e não havia ninguém: apaguei {n_} par(es) errados")
            if self.alvo and t - self.alvo["t"] > 12:             # limite absoluto: externo/sentado/busca não se realimentam
                if self._eixo:
                    cam.mover(0, 0)
                self._eixo = None; self.alvo = None
                return
            if self._eixo == "pan" and self.alvo and self._lado == self._sinal and t - self._visto > 0.4:
                self._eixo = "busca"                               # saiu pelo lado em que eu já girava: segue girando (o motor continua ligado)
            elif self._eixo in ("pan", "tilt") and t - self._visto > 0.8:
                cam.mover(0, 0); self._eixo = None
            # sem alvo também (entrou no quarto, sentou fora do quadro): as fixas guiam a PTZ o tempo todo no seguir
            if (not self.alvo or t - self._visto > 0.5) and not self._eixo and self._ir_externo(t):
                return
            if ((not self.alvo or t - self._visto > 1.2) and not self._eixo and time.time() - getattr(self, "_ult_sentado", 0.0) > 6
                    and G.sentado() and not G.alvo_externo(None) and self.achar_posicao("minha posição")):   # fixas sabem? elas mandam (antes as duas brigavam = vai-e-volta)
                self._ult_sentado = time.time()
                p_ = self.achar_posicao("minha posição")
                self._integrar()
                d_ = float(p_[0]) - self.pan
                if abs(d_) > 0.3 and cam.pulso(math.copysign(1, d_), 0, abs(d_)):
                    self._eixo, self._sinal, self._ext_fim = "externo", (1 if d_ > 0 else -1), time.time() + abs(d_) + LAT_MOTOR
                    self._ext_fonte = "minha posição"
                    log("seguir: alvo perdido e o dono está sentado (nativa): volto ao lugar dele")
                    return
            if self.alvo and t - self._visto > 1.2 and self._lado and not self._eixo:
                c = _conf()
                self._integrar()
                if (self._lado > 0 and self.pan < c["pan_total_s"] - 1) or (self._lado < 0 and self.pan > 1):
                    cam.mover(self._lado, 0); self._eixo, self._sinal = "busca", self._lado
            if self._eixo == "busca":
                self._integrar()
                c = _conf()
                e_ = G.alvo_externo(self.pan) if t - self._visto > 1.0 else None
                ult_ = getattr(self, "_ext_alvo", None)
                if (e_ and e_["conf"] >= 0.3 and abs(e_["pan"] - self.pan) >= 0.4 / c["pan_v"]
                        and not (ult_ and abs(e_["pan"] - ult_[0]) < 5.0 and time.time() - ult_[1] < 25)):
                    cam.mover(0, 0); self._eixo = None; self._lado = 0   # as fixas te veem: para (fecha o hist) e _ir_externo aponta nos próximos quadros
                    return
                if t - self._visto > 5 or self.pan <= 0.3 or self.pan >= c["pan_total_s"] - 0.3:
                    cam.mover(0, 0); self._eixo = None; self.alvo = None
            return
        x, y = self._ponto(p)
        self._ext_conferir = 0.0
        self.alvo = {"x": x, "y": y, "caixa": p["caixa"], "t": t}
        self._visto = t
        self._ext_alvo = None                               # achou: a histerese de 25 s só vale para apontamento que falhou
        if self._eixo == "busca" and (x - 0.5) * self._sinal > 0:
            self._eixo = "pan"                              # reapareceu à frente do giro: segue girando; o ramo pan freia na zona de chegada
        elif self._eixo in ("busca", "externo"):
            cam.mover(0, 0); self._eixo = None
            return
        # erro previsto AGORA: o quadro mostra a cena de ~LAT_VIDEO atrás; desconta o que a câmera girou desde então
        ex = (x - 0.5) - self._giro_desde(t - LAT_VIDEO, "pan")
        ey = (ALVO_Y - y) - self._giro_desde(t - LAT_VIDEO, "tilt")
        # velocidade da pessoa na cena: variação do erro + o que a câmera girou no intervalo (média móvel)
        agora = time.time()
        if self._ex_ant and 0.02 < agora - self._ex_ant[0] < 1.0:
            t0, ex0, ey0 = self._ex_ant
            dt_ = agora - t0
            vx = (ex - ex0 + self._giro_desde(t0, "pan")) / dt_
            vy = (ey - ey0 + self._giro_desde(t0, "tilt")) / dt_
            vx, vy = max(-0.6, min(0.6, vx)), max(-0.6, min(0.6, vy))
            self._vel = (0.6 * self._vel[0] + 0.4 * vx, 0.6 * self._vel[1] + 0.4 * vy)
        else:
            self._vel = (0.0, 0.0)
        self._ex_ant = (agora, ex, ey)
        rosto_ok = self._dono_na_caixa(p, 3.0)               # só ensina o mapa / "minha posição" com o rosto DO DONO no alvo (não amigo/espelho/móvel)
        if (rosto_ok and len(ps) == 1 and abs(ex) < 0.25 and abs(ey) < 0.25 and abs(self._vel[0]) < 0.12 and not self._eixo
                and not cam.movendo() and agora - cam.mov_fim > LATENCIA and agora - getattr(self, "_ancorado", 0.0) < 1800):   # âncora/relocalização ORB recente (180 s quase nunca valia: o mapa das fixas não crescia)
            self._integrar()
            c_ = _conf()
            if G.aprender(self.pan + ex / c_["pan_v"], self.tilt + ey / c_["tilt_v"], t - LAT_VIDEO):   # onde ELE está, no instante da cena
                self._aprendidos = getattr(self, "_aprendidos", 0) + 1
                if self._aprendidos % 25 == 1:
                    log(f"mundo: aprendi par fixas->PTZ em pan {self.pan:.1f} tilt {self.tilt:.1f} (total nesta sessão {self._aprendidos})")
        if abs(self._vel[0]) < 0.03 and abs(ex) < 0.1 and not self._eixo:
            self._parado_desde = getattr(self, "_parado_desde", 0.0) or agora
            if rosto_ok and agora - self._parado_desde > 20 and agora - getattr(self, "_ult_minha", 0.0) > 300:
                self._ult_minha = agora
                if "minha posição" not in (ipcam.ler_conf().get("posicoes_fixas") or []):
                    self.salvar_posicao("minha posição")
                ipcam.salvar_conf(tilt_horizonte=min(6.0, max(_conf()["tilt_min_busca"], round(self.tilt, 2))))
                log(f"minha posição aprendida: pan {self.pan:.1f}")
        else:
            self._parado_desde = 0.0
        # sumiu: procura primeiro para onde estava indo; parado, para o lado da tela em que estava
        # parado no meio do quadro (ex.: sentou e o detector perdeu a pose) NÃO procura: só se saiu andando ou pela borda
        self._lado = (1 if self._vel[0] > 0 else -1) if abs(self._vel[0]) > 0.08 else (1 if x > 0.8 else -1 if x < 0.2 else 0)
        # ANTECIPA: mira onde a pessoa vai estar quando o motor reagir (só com movimento claro, 70% do previsto)
        ant = 0.7 * (LAT_VIDEO + LAT_MOTOR)
        if abs(self._vel[0]) > 0.05:
            ex += self._vel[0] * ant
        if abs(self._vel[1]) > 0.05:
            ey += self._vel[1] * ant
        c = _conf()
        self._integrar()
        # Evita inclinar alto demais (tilt > teto aponta para a parede escura, acionando o filtro IR P&B da câmera)
        no_fim_pan = False
        hs_ = cam.hist
        h_ = hs_[-1] if hs_ else None
        aberto = (time.time() - h_[0]) if (h_ and h_[1] is None and h_[3]) else 0.0     # giro de tilt em curso, ainda fora do _integrar
        tilt_vivo = self.tilt + (math.copysign(aberto, h_[3]) * (-1 if cam.inv_tilt else 1) if aberto else 0.0)
        teto = float(c.get("tilt_teto", 22.0))          # PTZ na mesa (16/10): dono em pé = tilt bem alto; 8 não erguia a visão. Ajustável no camera_ptz.json
        no_fim_tilt = (ey > 0 and tilt_vivo >= teto)
        if self._eixo == "pan":
            # segue girando até o erro previsto entrar na zona de chegada (para antes: o motor ainda anda LAT_MOTOR)
            # você ainda andando para o mesmo lado: NÃO freia (o anda-para-anda com arranque do motor parecia lento)
            andando = self._vel[0] * self._sinal > 0.05 and ex * self._sinal > -0.08
            if (ex * self._sinal < 0.04 + c["pan_v"] * LAT_MOTOR and not andando) or no_fim_pan:
                cam.mover(0, 0); self._eixo = None
            return
        if self._eixo == "tilt":
            if (ey * self._sinal < 0.05 + c["tilt_v"] * LAT_MOTOR or (self._sinal > 0 and tilt_vivo >= teto)
                    or (abs(ex) > 0.22 and abs(ex) > 2 * abs(ey))):   # andando de lado: o pan é mais urgente que terminar o tilt
                cam.mover(0, 0); self._eixo = None
            return
        # parado: começa no eixo com mais erro (o motor não faz diagonal)
        fx = abs(ex) / (0.05 if abs(self._vel[0]) > 0.05 else 0.08) if not no_fim_pan else 0   # andando: arranca mais cedo
        fy = abs(ey) / 0.12 if not no_fim_tilt else 0
        if max(fx, fy) < 1.0 or time.time() - cam.mov_fim < 0.15:
            return
        if fx >= fy:
            self._eixo, self._sinal = "pan", (1 if ex > 0 else -1)
            cam.mover(self._sinal, 0)
        else:
            self._eixo, self._sinal = "tilt", (1 if ey > 0 else -1)
            cam.mover(0, self._sinal)

    # ------------------------------------------------------------ vigiar (ronda + movimento + pessoas)
    def _paradas(self):
        c = _conf()
        passo = 0.8 / c["pan_v"]
        n = max(3, int(math.ceil(c["pan_total_s"] / passo)) + 1)
        return [c["pan_total_s"] * i / (n - 1) for i in range(n)]

    def _passo_vigiar(self, agora):
        cam = self.cam
        paradas = self._paradas()
        if agora >= self._ronda_ate:
            self._ronda_i = (self._ronda_i + 1) % len(paradas)
            self.ir(paradas[self._ronda_i], _conf()["tilt_horizonte"], esperar=False)
            self._ronda_ate = time.time() + LATENCIA + (8.0 if self.modo == "vigiar" else 30.0)   # auto: ronda calma
            self._ronda_ref = None
            return
        if cam.movendo() or agora - cam.mov_fim < LATENCIA:
            return
        fr, t = G.quadro()
        if fr is None or t < cam.mov_fim + LATENCIA:
            return
        cinza = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(fr, (320, 180)), cv2.COLOR_BGR2GRAY), (7, 7), 0)
        cinza[:16, :130] = 0                              # relógio da câmera não é movimento
        if t - self._pessoas[0] > 0.5:
            self._pessoas = (t, [p["caixa"] for p in self.pose().pessoas(fr) if p["kp"] >= 4])
        if self._ronda_ref is None:
            self._ronda_ref = cinza
            return
        mov = float((cv2.absdiff(cinza, self._ronda_ref) > 28).mean())
        self._ronda_ref = cv2.addWeighted(self._ronda_ref, 0.8, cinza, 0.2, 0)
        tp, ps = self._pessoas
        if ps and tp != self._ult_conf_t:
            self._ult_conf_t = tp
            self._confirma += 1                           # 3 detecções seguidas (1 só = falso positivo comum)
            self._ronda_ate = max(self._ronda_ate, agora + 4)
        elif not ps:
            self._confirma = 0
        if self.modo != "vigiar":
            return                                        # automático só observa; alerta é do "vigiar" pedido pelo dono
        if ps and self._confirma >= 3 and agora - self._ult_alerta > 60:
            d = G.dono()
            if d and d[0] >= tp - 2:
                return                                    # é o dono: não alerta
            self._ult_alerta = agora
            self._ronda_ate = agora + 20
            self._alertar(fr, f"Atenção: tem uma pessoa no quarto, {self.nome_da_posicao(self.pan)}.", False)
        elif mov > 0.04 and agora - self._ult_mov_alerta > 120:
            self._ult_mov_alerta = agora
            self._ronda_ate = agora + 12
            self._alertar(fr, f"Movimento no quarto, {self.nome_da_posicao(self.pan)}.", False)

    def _alertar(self, fr, texto, falar):
        os.makedirs(PASTA_VIGIA, mode=0o700, exist_ok=True)
        try:
            fotos = sorted(f for f in os.listdir(PASTA_VIGIA) if f.endswith(".jpg"))
            for velho in fotos[:-300]:
                os.remove(os.path.join(PASTA_VIGIA, velho))
        except Exception:
            pass
        arq = os.path.join(PASTA_VIGIA, time.strftime("%Y%m%d-%H%M%S") + ".jpg")
        cv2.imwrite(arq, fr)
        log(f"vigia: {texto} -> {arq}")
        ok, jpg = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        G.avisar(texto, falar, jpg.tobytes() if ok else None)

    # ------------------------------------------------------------ laço dos modos contínuos
    def definir_modo(self, modo, salvar=True):
        if modo not in ("livre", "seguir", "vigiar", "auto"):
            return False
        if modo == "livre" and not salvar:
            self._pausa_ate = time.time() + 60          # "olhe para X": fica lá 1 min antes de voltar a seguir
        elif modo != "livre":
            self._pausa_ate = 0.0
        if salvar:
            self.modo_salvo = modo
            ipcam.salvar_conf(modo=modo)
        if modo != "livre":
            self._parar_tarefa.clear()
        mudou = modo != self.modo
        self.modo = modo
        self.alvo, self._eixo, self._lado = None, None, 0
        self._vel, self._ex_ant = (0.0, 0.0), None
        self._ronda_ate, self._ausente_desde = 0.0, None
        c = self.cam
        if c is not None and c.vel != (0.0, 0.0):
            c.mover(0, 0)
        if mudou:
            log(f"modo {modo}")
            G.modo_mudou(modo)
        return True

    def parar(self):
        self._parar_tarefa.set()
        self.definir_modo("livre", salvar=False)
        self._pausa_ate = time.time() + 600                # "pare": 10 min parada   # "pare" é momentâneo: não apaga o modo autônomo do reboot
        c = self.cam
        if c is not None:
            c.parar()

    def _laco(self):
        ult_t = 0.0
        while True:
            time.sleep(0.01)
            try:
                if self.modo == "livre" or self.ocupada or not self.disponivel():
                    time.sleep(0.2)
                    continue
                agora = time.time()
                modo = self.modo
                if modo == "auto":
                    tp, ps = self._pessoas
                    if G.presente() or (ps and agora - tp < 3 and self._confirma >= 3):
                        self._ausente_desde = None              # alguém no quarto (inclusive o dono dormindo): segue em silêncio
                        modo = "seguir"
                    else:
                        self._ausente_desde = self._ausente_desde or agora
                        modo = "vigiar" if agora - self._ausente_desde > 90 else "seguir"
                if modo == "seguir" and self._auto_procurar(agora):
                    continue
                if modo == "seguir":
                    fr, t = G.quadro()
                    if fr is None or t <= ult_t:
                        continue
                    ult_t = t
                    self._passo_seguir(fr, t)                 # todo quadro novo (~14 fps)
                elif modo == "vigiar":
                    self._passo_vigiar(agora)
                    time.sleep(0.2)
            except Exception as e:
                log(f"laço: {e!r}")
                time.sleep(1.0)

    def _auto_procurar(self, agora):
        """plano B automático (16/10: ela ficava parada olhando para cima): a nativa te vê sentado, mas a PTZ não te vê há
        20 s (mapa errado/sem "minha posição") -> varre sozinha atrás do seu rosto. No máximo 1 vez a cada 2 min."""
        if not G.sentado() or agora - getattr(self, "_visto", 0.0) < 20 or agora - getattr(self, "_ult_auto_proc", 0.0) < 120:
            return False
        if self.ocupada or agora < getattr(self, "_pausa_ate", 0.0):
            return False
        self._ult_auto_proc = agora
        log("seguir: a nativa te vê sentado e eu não te vejo há 20 s: procurando sozinha")
        threading.Thread(target=self.localizar_dono, daemon=True, name="ptz-auto-procura").start()
        return True

    # ------------------------------------------------------------ calibração pelo vídeo
    def _desloc(self, a, b):
        """deslocamento (dx, dy) em FRAÇÃO da tela do conteúdo de a para b (ORB + mediana) e pontos que bateram."""
        orb = cv2.ORB_create(1000)
        ga, gb = (cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (a, b))
        H, W = ga.shape
        ga[:int(H * 0.07), :int(W * 0.41)] = 0; gb[:int(H * 0.07), :int(W * 0.41)] = 0     # relógio
        ka, da = orb.detectAndCompute(ga, None)
        kb, db = orb.detectAndCompute(gb, None)
        if da is None or db is None:
            return None
        m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
        if len(m) < 12:
            return None
        d = np.array([np.subtract(kb[x.trainIdx].pt, ka[x.queryIdx].pt) for x in m])
        med = np.median(d, axis=0)
        bons = int((np.linalg.norm(d - med, axis=1) < 4).sum())
        return (float(med[0]) / W, float(med[1]) / H, bons) if bons >= 10 else None

    def _medir(self, vx, vy, dur):
        cam = self.cam
        a = self._quadro_apos(time.time())
        cam.pulso(vx, vy, dur)
        time.sleep(dur + 0.2)
        b = self._quadro_apos(time.time() + LATENCIA)
        return self._desloc(a, b) if (a is not None and b is not None) else None

    def _ate_o_fim(self, vx, vy, maximo=60.0):
        """gira até o fim de curso com "homem-morto": o motor só segue enquanto o VÍDEO confirma que está andando.
        -> (segundos de motor andando, None) ou (None, None)."""
        cam = self.cam
        eixo = 0 if vx else 1
        ant = self._quadro_apos(time.time())
        if ant is None:
            return None, None
        pq = lambda x: cv2.cvtColor(cv2.resize(x, (320, 180)), cv2.COLOR_BGR2GRAY)[14:].astype(np.int16)
        t_ant = t_inicio = time.time()
        ini = fim = None
        ult_mov = time.time()
        cam.mover(vx, vy)
        motivo = "máximo"
        while not self._parar_tarefa.is_set():
            time.sleep(0.12)
            agora = time.time()
            cur, t = G.quadro()
            if cur is not None and t > t_ant:
                dif = float(np.abs(pq(cur) - pq(ant)).mean())
                d = self._desloc(ant, cur)
                mexeu = (d is not None and abs(d[eixo]) > 0.0015) or (d is None and dif > 4.0)
                if mexeu:
                    ini = ini or t_ant
                    fim, ult_mov = t, agora
                ant, t_ant = cur, t
            if (ini and agora - ult_mov > LATENCIA + 0.9) or (not ini and agora - t_inicio > 8.0):
                motivo = "parou de mexer"
                break
            if agora - t_inicio > maximo:
                break
        cam.mover(0, 0)
        log(f"fim de curso ({vx},{vy}): {motivo}, motor {None if ini is None else round(fim - ini, 1)} s")
        time.sleep(0.6)
        if self._parar_tarefa.is_set() or not ini or motivo != "parou de mexer":
            return None, None
        return fim - ini, None

    def calibrar(self):
        """mede o curso total (tilt e pan) e a velocidade pelo vídeo. ~2 a 3 minutos. Deixa a câmera no centro."""
        if not self.disponivel():
            return "Não consigo calibrar: " + ipcam.status() + "."
        if not self._tarefa("calibrando"):
            return "A câmera já está ocupada."
        try:
            novo = {}
            self._ate_o_fim(0, -1, 40)
            tilt_total, _ = self._ate_o_fim(0, 1, 40)
            if tilt_total is None and not self._parar_tarefa.is_set() and _conf().get("tilt_total_s"):
                tilt_total = float(_conf()["tilt_total_s"])      # vídeo ruidoso no tilt (bateu no máximo): usa o curso já medido e segue p/ o pan
                log(f"calibrar: tilt sem fim claro, uso o curso salvo {tilt_total} s")
            if tilt_total is None:
                return "Calibração interrompida no tilt (parada ou o vídeo não mostrou movimento)."
            ipcam.salvar_conf(tilt_total_s=round(tilt_total, 1))
            self._integrar()
            self.tilt = tilt_total
            self.girar_s(0, -tilt_total * 0.55, esperar=True)
            self._ate_o_fim(-1, 0, 90)
            pan_total, _ = self._ate_o_fim(1, 0, 90)
            if self._parar_tarefa.is_set() or pan_total is None:
                return "Calibração interrompida no pan (parada ou o vídeo não mostrou movimento)."
            novo.update(pan_total_s=round(pan_total, 1), tilt_total_s=round(tilt_total, 1))
            ipcam.salvar_conf(pan_total_s=novo["pan_total_s"])
            self._integrar()
            self.pan = pan_total
            self.girar_s(-pan_total / 2, 0, esperar=True)
            res, sinal = {}, {}
            cam = self.cam
            for eixo, (vx, vy), dur in (("pan", (1, 0), 1.5), ("pan", (-1, 0), 1.5), ("tilt", (0, 1), 1.2), ("tilt", (0, -1), 1.2)):
                m = self._medir(vx, vy, dur)
                if m:
                    fr_ = m[0] if eixo == "pan" else m[1]
                    log(f"calibrar {eixo} v=({vx},{vy}) {dur}s -> dx={m[0]:.3f} dy={m[1]:.3f} ({m[2]} pts)")
                    if abs(fr_) > 0.02:
                        res.setdefault(eixo, []).append(abs(fr_) / max(0.1, dur - LAT_MOTOR))
                        ok_sent = (fr_ < 0) if eixo == "pan" else (fr_ > 0)
                        sinal.setdefault(eixo, []).append(ok_sent if (vx > 0 or vy > 0) else not ok_sent)
            for eixo, attr in (("pan", "inv_pan"), ("tilt", "inv_tilt")):
                vs = sinal.get(eixo) or []
                if len(vs) == 2 and vs[0] == vs[1] and not vs[0]:
                    setattr(cam, attr, not getattr(cam, attr))
                    novo["inverter_" + eixo] = getattr(cam, attr)
            if res.get("pan"):
                novo["pan_v"] = round(float(np.median(res["pan"])), 4)
            if res.get("tilt"):
                novo["tilt_v"] = round(float(np.median(res["tilt"])), 4)
            novo["calibrada"] = bool(res.get("pan"))
            ipcam.salvar_conf(**novo)
            self.calibrada = novo["calibrada"]
            log(f"calibrada: {novo}")
            return (f"Calibrei a câmera: o giro completo leva {pan_total:.0f} segundos e a inclinação {tilt_total:.0f}."
                    if self.calibrada else "Medi o curso, mas não a velocidade (pouca textura na imagem). Aponte para algo com detalhes e repita.")
        finally:
            self._fim_tarefa()

    def texto_hud(self):
        if not self.disponivel():
            return "PTZ: " + ("sem câmera" if self.cam is None else "sem motor")
        rot = {"livre": "LIVRE", "seguir": "SEGUINDO", "vigiar": "VIGIANDO", "auto": "AUTO"}[self.modo]
        if self.modo in ("seguir", "auto") and time.time() - self._visto < 1.5:
            rot += " · TRAVADO"
        return f"PTZ {rot}" + (f" · {self.ocupada.upper()}" if self.ocupada else "")


_inst = None
_inst_lock = threading.Lock()


def get_ptz(*_a, **_k):
    global _inst
    with _inst_lock:
        if _inst is None:
            _inst = PTZ()
        return _inst


def em_fundo(fn, *a, aviso=None):
    """roda uma tarefa da câmera fora do laço do daemon e entrega o texto em aviso()."""
    def run():
        try:
            txt = fn(*a)
        except Exception as e:
            log(f"tarefa {getattr(fn, '__name__', fn)}: {e!r}")
            txt = "Deu erro ao mexer a câmera."
        if aviso and txt:
            aviso(txt)
    threading.Thread(target=run, daemon=True, name="ptz-tarefa").start()


def _curta(p, fn):
    """movimento curto como tarefa: marca a câmera ocupada (o laço de seguir/vigiar não mexe junto)."""
    def run(*a):
        if not p._tarefa("virando"):
            return None
        try:
            fn(*a)
        finally:
            p._fim_tarefa()
    return run


def comando(a):
    """ação {"op": olhar|em_volta|procurar|localizar|seguir|vigiar|auto|parar|livre|salvar_posicao|ir_posicao|calibrar|estado|
    zoom|apontar|onde, "dir", "alvo", "nome", "fator", "pergunta", "pan", "tilt"}. Devolve (ok, mensagem). Tarefas longas rodam em fundo e entregam o resultado no HUD por G.avisar."""
    p = get_ptz()
    op = str(a.get("op") or "").strip().lower()
    falar = lambda txt: G.avisar(txt, False, None)
    if op == "estado":
        return True, p.estado()
    if op == "modo":
        op = str(a.get("modo") or "").strip().lower()
    if op in ("onde", "mundo"):
        txt = G.mundo_resumo()
        if a.get("falar", True):
            falar(txt)                               # atualiza texto no HUD sem emitir voz pela câmera
        return True, txt
    if op in ("parar", "livre"):
        p.parar()
        return True, "câmera parada, modo livre"
    if not p.disponivel():
        return False, "câmera com motor indisponível: " + ipcam.status()
    if op in ("seguir", "localizar"):
        if p.ocupada:
            p._parar_tarefa.set()
            time.sleep(0.5)
        d = G.dono()                             # já estou te vendo PELO ROSTO? (pose sozinha confundia entalhe do guarda-roupa)
        if d and time.time() - d[0] < 2:
            p.definir_modo("seguir")
            return True, "te vendo; seguindo seus movimentos"
        p.definir_modo("livre", salvar=False)
        if not p.ocupada:
            p._parar_tarefa.clear()                  # o "parar" da tarefa anterior não pode anular a busca nova
        em_fundo(p.localizar_dono, aviso=falar)
        return True, "procurando você: primeiro onde você costuma ficar, depois o quarto todo"
    if op in ("vigiar", "auto"):
        p.definir_modo(op)
        return True, {"vigiar": "vigiando o quarto (ronda + alertas)",
                      "auto": "automático: segue o dono presente e vigia quando ele sai"}[op]
    if p.ocupada:
        return False, f"a câmera já está ocupada ({p.ocupada})"
    if op == "olhar":
        d = str(a.get("dir") or a.get("alvo") or "").strip().lower()
        if d not in ("esquerda", "direita", "cima", "baixo", "centro", "frente", "meio"):
            if p.achar_posicao(d):
                p.definir_modo("livre", salvar=False)
                em_fundo(_curta(p, p.ir_posicao), d)
                return True, f"olhando para {d}"
            return False, "direção desconhecida (use esquerda, direita, cima, baixo, centro ou uma posição salva)"
        p.definir_modo("livre", salvar=False)
        em_fundo(_curta(p, p.olhar), d)
        return True, f"olhando para {d}"
    if op == "ir_posicao":
        nome = str(a.get("nome") or a.get("alvo") or "")
        if not p.achar_posicao(nome):
            return False, f"não tenho a posição '{nome}' salva (diga: decore o quarto)"
        p.definir_modo("livre", salvar=False)
        em_fundo(_curta(p, p.ir_posicao), nome)
        return True, f"virando para {nome}"
    if op == "salvar_posicao":
        nome = str(a.get("nome") or a.get("alvo") or "").strip()
        if not nome:
            return False, "falta o nome da posição"
        p.salvar_posicao(nome, fixa=True)
        return True, f"posição '{nome}' salva"
    if op == "mapear":
        p.definir_modo("livre", salvar=False)
        em_fundo(p.mapear, aviso=falar)
        return True, "girando pelo quarto para decorar portas, guarda-roupa, cama e onde você fica; aviso ao terminar"
    if op == "em_volta":
        p.definir_modo("livre", salvar=False)
        em_fundo(p.olhar_em_volta, aviso=falar)
        return True, "girando a câmera pelo quarto; falo o que vi ao terminar"
    if op == "procurar":
        alvo = str(a.get("alvo") or "").strip()
        if not alvo:
            return False, "falta dizer o que procurar"
        p.definir_modo("livre", salvar=False)
        em_fundo(p.procurar, alvo, aviso=falar)
        return True, f"procurando {alvo} com a câmera"
    if op == "zoom":
        alvo, perg = str(a.get("alvo") or "").strip(), str(a.get("pergunta") or "").strip()
        em_fundo(p.zoom, a.get("fator") or None, alvo, perg, aviso=(falar if perg else (lambda t: log(t))))
        return True, f"dando zoom{' em ' + alvo if alvo else ''}" + ("; respondo o que vir" if perg else "; imagem em /tmp/friday-zoom.jpg")
    if op == "apontar":
        try:
            c = _conf()
            pan, tilt = float(a.get("pan")), float(a.get("tilt", p.tilt))
            if str(a.get("unidade") or "").startswith("frac"):
                pan, tilt = pan * c["pan_total_s"], tilt * c["tilt_total_s"]
        except (TypeError, ValueError):
            nome = str(a.get("alvo") or a.get("nome") or "").strip()
            if nome and p.achar_posicao(nome):         # "aponta pra porta" = posição salva
                p.definir_modo("livre", salvar=False)
                em_fundo(_curta(p, p.ir_posicao), nome)
                return True, f"apontando para {nome}"
            if G.alvo_externo(None):                   # sem números: aponta para quem as câmeras fixas veem
                p.definir_modo("livre", salvar=False)
                em_fundo(_curta(p, p.apontar_externo))
                return True, "apontando para onde as câmeras fixas veem alguém"
            return False, "falta pan/tilt e as câmeras fixas não veem ninguém"
        p.definir_modo("livre", salvar=False)
        em_fundo(_curta(p, p.ir), pan, tilt)
        return True, f"apontando para pan {pan:.1f} tilt {tilt:.1f}"
    if op == "calibrar":
        p.definir_modo("livre", salvar=False)
        em_fundo(p.calibrar, aviso=falar)
        return True, "calibrando a câmera (cerca de 2 a 3 minutos)"
    return False, f"operação de câmera desconhecida: {op}"
