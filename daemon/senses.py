"""Sentidos locais do Prometheus: reconhecer rostos (SFace) e vozes (WeSpeaker) e lembrar de pessoas.

Tudo roda NO PC: os modelos são ONNX em models/, e os dados biométricos ficam em memory/people.json
(permissão 0600, nunca enviados a nenhum serviço). Só o NOME e o texto da conversa chegam ao LLM do agente.
"""
import json, math, os, threading, time
from collections import deque

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PEOPLE_FILE = os.path.join(ROOT, "memory", "people.json")
FACE_MODEL = os.path.join(ROOT, "models", "face_recognition_sface.onnx")
SPK_MODEL = os.path.join(ROOT, "models", "speaker_wespeaker_resnet34.onnx")

FACE_THR = 0.363        # cosseno recomendado p/ SFace (mesma pessoa >= 0.363)
VOICE_THR = 0.44        # cosseno WeSpeaker ResNet34 (mesma pessoa tipicamente > 0.55; TTS distintos < 0.45)
MAX_SAMPLES = 24


def _ort_opts(n=2):
    """SessionOptions enxutas: poucos threads e sem spin-wait (cada sessão sem limite criava 1 thread por núcleo girando em 100%)."""
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = n
    so.inter_op_num_threads = 1
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return so


def _unit(v):
    v = np.asarray(v, dtype="float32").ravel()
    return v / max(1e-9, float(np.linalg.norm(v)))


class People:
    """Banco de pessoas conhecidas: {id: {nome, faces[[...]], vozes[[...]], primeira, visto, vezes}}."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {"pessoas": {}}
        try:
            self.data = json.load(open(PEOPLE_FILE))
        except Exception:
            pass

    def _save(self):
        os.makedirs(os.path.dirname(PEOPLE_FILE), exist_ok=True)
        tmp = PEOPLE_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f)
        os.replace(tmp, PEOPLE_FILE)
        os.chmod(PEOPLE_FILE, 0o600)

    def names(self):
        with self.lock:
            return [p["nome"] for p in self.data["pessoas"].values()]

    def _best(self, key, emb, thr):
        """pontuação por pessoa = 0,5*melhor + 0,5*média das 3 melhores amostras (robusto a uma amostra ruim);
        com UMA pessoa cadastrada o limiar é relaxado (a chance de confundir com outra é nula)."""
        emb = _unit(emb)
        best, best_s = None, -1.0
        for pid, p in self.data["pessoas"].items():
            amostras = [x for k in (key if isinstance(key, tuple) else (key,)) for x in p.get(k, [])]
            sims = sorted((float(np.dot(emb, _unit(s))) for s in amostras), reverse=True)
            if not sims:
                continue
            sc = sims[0] if len(sims) == 1 else 0.5 * sims[0] + 0.5 * float(np.mean(sims[:3]))
            if sc > best_s:
                best, best_s = pid, sc
        if len(self.data["pessoas"]) <= 1 and "faces" not in (key if isinstance(key, tuple) else (key,)):
            thr = thr * 0.80                  # rosto NÃO relaxa (16/10: amigo no quarto virava "Chefe" com 0,29 e a PTZ seguia ele)
        if best is not None and best_s >= thr:
            return best, best_s
        return None, best_s

    def sim_to(self, key, pid, emb):
        """melhor similaridade do embedding com as amostras de `pid` (-1 se não houver)."""
        with self.lock:
            p = self.data["pessoas"].get(pid)
            if not p or not p.get(key):
                return -1.0
            e = _unit(emb)
            return max(float(np.dot(e, _unit(x))) for x in p[key])

    def match_face(self, feat, ptz=False):
        """ptz=True: compara também com o cadastro feito PELA câmera PTZ (de perto/de lado/infravermelho o rosto do
        dono dava 0,10-0,27 contra o cadastro da nativa — nunca era reconhecido; 16/10)."""
        with self.lock:
            pid, s = self._best(("faces", "faces_ptz") if ptz else "faces", feat, FACE_THR)
            return (self.data["pessoas"][pid]["nome"] if pid else None), s, pid

    def match_voice(self, emb):
        with self.lock:
            pid, s = self._best("vozes", emb, VOICE_THR)
            return (self.data["pessoas"][pid]["nome"] if pid else None), s, pid

    def find_by_name(self, nome):
        n = nome.strip().lower()
        for pid, p in self.data["pessoas"].items():
            if p["nome"].strip().lower() == n:
                return pid
        return None

    def enroll(self, nome, face=None, voice=None):
        """Cria/atualiza a pessoa `nome` com uma amostra de rosto e/ou voz. Devolve o id."""
        nome = nome.strip()[:40]
        if not nome:
            return None
        with self.lock:
            pid = self.find_by_name(nome)
            if pid is None:
                pid = f"p{int(time.time() * 1000)}"
                self.data["pessoas"][pid] = {"nome": nome, "faces": [], "vozes": [], "primeira": time.time(),
                                             "visto": time.time(), "vezes": 0}
            self._add(pid, face, voice)
            self._save()
            return pid

    def _add(self, pid, face=None, voice=None):
        p = self.data["pessoas"][pid]
        for key, v in (("faces", face), ("vozes", voice)):
            if v is None:
                continue
            lst = p.setdefault(key, [])
            lst.append([round(float(x), 5) for x in _unit(v)])
            if len(lst) > MAX_SAMPLES:
                del lst[0]                    # mantém as amostras mais recentes (acompanha mudanças na aparência)

    def learn_ptz(self, pid, face):
        """amostra do rosto do dono vista pela PTZ (lista própria: não empurra para fora as amostras da nativa)"""
        with self.lock:
            p = self.data["pessoas"].get(pid)
            if not p or face is None:
                return
            lst = p.setdefault("faces_ptz", [])
            lst.append([round(float(x), 5) for x in _unit(face)])
            del lst[:-MAX_SAMPLES]
            self._save()

    def learn(self, pid, face=None, voice=None):
        with self.lock:
            if pid in self.data["pessoas"]:
                self._add(pid, face, voice)
                self._save()

    def touch(self, pid):
        with self.lock:
            p = self.data["pessoas"].get(pid)
            if p:
                p["visto"] = time.time(); p["vezes"] = p.get("vezes", 0) + 1
                self._save()

    def forget(self, nome):
        with self.lock:
            pid = self.find_by_name(nome)
            if pid:
                del self.data["pessoas"][pid]; self._save()
            return bool(pid)


class FaceID:
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.rec = cv2.FaceRecognizerSF.create(FACE_MODEL, "")

    def feature(self, frame_bgr, face_row):
        """face_row: linha do YuNet (x,y,w,h, 5 pontos, score) já na escala de frame_bgr."""
        al = self.rec.alignCrop(frame_bgr, face_row.astype("float32"))
        return self.rec.feature(al).ravel()


class SpeakerID:
    def __init__(self):
        import onnxruntime as ort
        self.sess = ort.InferenceSession(SPK_MODEL, _ort_opts(2), providers=["CPUExecutionProvider"])
        self.name = self.sess.get_inputs()[0].name
        n_fft, n_mels, sr = 512, 80, 16000
        self.win = self._povey(400)
        self.mel = self._mel_bank(n_mels, n_fft, sr, 20.0, sr / 2)

    @staticmethod
    def _povey(n):
        return np.power(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1)), 0.85).astype("float32")

    @staticmethod
    def _mel_bank(n_mels, n_fft, sr, lo, hi):
        mel = lambda f: 1127.0 * np.log(1.0 + f / 700.0)
        pts = np.linspace(mel(lo), mel(hi), n_mels + 2)
        bins = np.arange(n_fft // 2 + 1) * (sr / n_fft)
        mb = mel(bins)
        fb = np.zeros((n_mels, n_fft // 2 + 1), dtype="float32")
        for i in range(n_mels):
            l, c, r = pts[i], pts[i + 1], pts[i + 2]
            up = (mb - l) / (c - l)
            dn = (r - mb) / (r - c)
            fb[i] = np.maximum(0.0, np.minimum(up, dn))
        return fb

    def fbank(self, pcm_f32):
        """Fbank estilo Kaldi (80 mel, 25 ms/10 ms) a partir de amostras float [-1,1] a 16 kHz."""
        x = pcm_f32.astype("float32") * 32768.0
        if len(x) < 400:
            x = np.pad(x, (0, 400 - len(x)))
        n = 1 + (len(x) - 400) // 160
        idx = np.arange(400)[None, :] + 160 * np.arange(n)[:, None]
        fr = x[idx]
        fr = fr - fr.mean(axis=1, keepdims=True)                          # remove DC
        fr = np.concatenate([fr[:, :1] * (1 - 0.97), fr[:, 1:] - 0.97 * fr[:, :-1]], axis=1)   # pré-ênfase
        fr = fr * self.win
        spec = np.abs(np.fft.rfft(fr, n=512, axis=1)) ** 2
        mel = np.log(np.maximum(spec @ self.mel.T, 1.1920929e-07))
        return (mel - mel.mean(axis=0, keepdims=True)).astype("float32")   # CMN

    def embed(self, pcm_f32):
        f = self.fbank(pcm_f32)
        if len(f) < 60:                                                   # < 0,6 s: pouco confiável
            return None
        e = self.sess.run(None, {self.name: f[None]})[0][0]
        return _unit(e)


OBJ_MODEL = os.path.join(ROOT, "models", "object_yolox_m.onnx")      # YOLOX-m (COCO); mesmo formato do -s
if not os.path.exists(OBJ_MODEL):
    OBJ_MODEL = os.path.join(ROOT, "models", "object_yolox.onnx")
COCO_PT = ["pessoa", "bicicleta", "carro", "moto", "avião", "ônibus", "trem", "caminhão", "barco", "semáforo",
           "hidrante", "placa de pare", "parquímetro", "banco", "pássaro", "gato", "cachorro", "cavalo", "ovelha", "vaca",
           "elefante", "urso", "zebra", "girafa", "mochila", "guarda-chuva", "bolsa", "gravata", "mala", "frisbee",
           "esquis", "snowboard", "bola", "pipa", "taco de beisebol", "luva de beisebol", "skate", "prancha de surfe",
           "raquete de tênis", "garrafa", "taça de vinho", "copo", "garfo", "faca", "colher", "tigela", "banana",
           "maçã", "sanduíche", "laranja", "brócolis", "cenoura", "cachorro-quente", "pizza", "rosquinha", "bolo",
           "cadeira", "sofá", "planta", "cama", "mesa", "vaso sanitário", "TV/monitor", "notebook", "mouse",
           "controle remoto", "teclado", "celular", "micro-ondas", "forno", "torradeira", "pia", "geladeira",
           "livro", "relógio", "vaso", "tesoura", "ursinho de pelúcia", "secador de cabelo", "escova de dentes"]


class ObjectDet:
    """YOLOX-m (COCO, 80 classes; cai p/ -s se faltar) em ONNX: objetos à vista, tudo local."""

    def __init__(self):
        import cv2, onnxruntime as ort
        self.cv2 = cv2
        self.sess = ort.InferenceSession(OBJ_MODEL, _ort_opts(3), providers=["CPUExecutionProvider"])
        self.name = self.sess.get_inputs()[0].name
        g = []
        for st in (8, 16, 32):
            n = 640 // st
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            g.append((np.stack([xv, yv], -1).reshape(-1, 2), np.full((n * n, 1), st)))
        self.grid = np.concatenate([a for a, _ in g]).astype("float32")
        self.strides = np.concatenate([b for _, b in g]).astype("float32")

    def detect(self, bgr, conf=0.45):
        cv2 = self.cv2
        h, w = bgr.shape[:2]
        r = min(640 / w, 640 / h)
        img = cv2.resize(bgr, (int(w * r), int(h * r)))
        canvas = np.full((640, 640, 3), 114, np.uint8)
        canvas[:img.shape[0], :img.shape[1]] = img
        blob = canvas.transpose(2, 0, 1)[None].astype("float32")
        out = self.sess.run(None, {self.name: blob})[0][0]
        xy = (out[:, :2] + self.grid) * self.strides
        wh = np.exp(out[:, 2:4]) * self.strides
        cls = out[:, 5:]
        ci = cls.argmax(1)
        sc = out[:, 4] * cls[np.arange(len(cls)), ci]
        m = sc > conf
        if not m.any():
            return []
        xy, wh, sc, ci = xy[m], wh[m], sc[m], ci[m]
        boxes = np.concatenate([xy - wh / 2, wh], axis=1) / r
        keep = cv2.dnn.NMSBoxes(boxes.tolist(), sc.tolist(), conf, 0.5)
        res = []
        for i in np.array(keep).ravel():
            res.append((COCO_PT[int(ci[i])], float(sc[i]), boxes[i].tolist()))
        return res


def detector_objetos():
    """YOLOE com o vocabulário da casa (objetos_yoloe, 16/10: 2x mais rápido e vê mochila/óculos/travesseiro/garrafa que o
    YOLOX-COCO não via); sem o modelo exportado ou com FRIDAY_DET=yolox, o YOLOX de 80 classes."""
    if os.environ.get("FRIDAY_DET", "yoloe") == "yoloe":
        try:
            import objetos_yoloe
            if objetos_yoloe.disponivel():
                return objetos_yoloe.DetYOLOE()
        except Exception as e:
            print("YOLOE indisponível, uso YOLOX:", repr(e)[:120], flush=True)
    return ObjectDet()


def classes_objetos():
    """nomes (pt) que o detector ativo sabe achar — p/ o "procurar X" da câmera."""
    if os.environ.get("FRIDAY_DET", "yoloe") == "yoloe":
        try:
            import objetos_yoloe
            if objetos_yoloe.disponivel():
                return json.load(open(objetos_yoloe.META))["classes_pt"]
        except Exception:
            pass
    return COCO_PT


def color_name_pt(bgr_pixels, ref=None):
    """Nome da cor dominante (mediana em HSV) de uma região BGR (N,3 uint8) — medido, não adivinhado."""
    import cv2
    px = np.asarray(bgr_pixels, dtype="uint8").reshape(-1, 1, 3)
    if len(px) < 30:
        return None
    if ref is not None:                                  # balanço de branco "mundo cinza": tira a dominante de cor da câmera/luz
        m = np.asarray(ref, dtype="float32").reshape(-1, 3).mean(axis=0)
        gain = m.mean() / np.maximum(m, 1.0)
        px = np.clip(px.astype("float32") * gain, 0, 255).astype("uint8")
    hsv = cv2.cvtColor(px, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype("float32")
    h, s, v = (float(np.median(hsv[:, i])) for i in range(3))
    if v < 55:
        return "preta"
    if s < 55:
        return "branca" if v > 190 else "cinza"
    if v < 150 and s < 135:                              # pouca luz + saturação moderada: quase sempre cinza com dominante da luz
        return "cinza (levemente azulada pela luz)" if 100 <= h * 2.0 < 260 else "cinza"
    hue = h * 2.0                                        # OpenCV: 0-180 -> graus
    if hue < 15 or hue >= 345:
        n = "vermelha"
    elif hue < 40:
        n = "laranja" if v > 120 else "marrom"
    elif hue < 70:
        n = "amarela"
    elif hue < 160:
        n = "verde"
    elif hue < 200:
        n = "ciano"
    elif hue < 255:
        n = "azul"
    elif hue < 300:
        n = "roxa"
    else:
        n = "rosa"
    if v < 110 and n in ("azul", "verde", "vermelha", "roxa"):
        n += " escura"
    elif s < 90 and v > 150 and n in ("azul", "verde", "vermelha", "roxa"):
        n += " clara"
    return n


PALM_MODEL = os.path.join(ROOT, "models", "palm_detection_mediapipe_2023feb.onnx")
HAND_MODEL = os.path.join(ROOT, "models", "handpose_estimation_mediapipe_2023feb.onnx")


class HandTracker:
    """MediaPipe Hands (palma + 21 pontos) em ONNX, tudo local. detect(frame_bgr) -> [{lm(21x2 px), conf, cx}]."""

    def __init__(self):
        import cv2, onnxruntime as ort
        self.cv2 = cv2
        so = _ort_opts(2)
        self.palm = ort.InferenceSession(PALM_MODEL, so, providers=["CPUExecutionProvider"])
        self.hand = ort.InferenceSession(HAND_MODEL, so, providers=["CPUExecutionProvider"])
        a = []
        for st, reps in ((8, 2), (16, 6)):
            n = 192 // st
            for y in range(n):
                for x in range(n):
                    for _ in range(reps):
                        a.append(((x + 0.5) / n, (y + 0.5) / n))
        self.anchors = np.array(a, dtype="float32")             # 2016

    def _landmarks(self, pad, ctr, u, size, ox, oy):
        """recorta a mão (ROI orientada), roda o modelo de 21 pontos -> (pts px do quadro, z, conf) | None."""
        cv2 = self.cv2
        r = np.array([-u[1], u[0]])
        k = size / 224.0
        src = np.array([ctr + r * (0 - 112) * k - u * (0 - 112) * k,
                        ctr + r * (224 - 112) * k - u * (0 - 112) * k,
                        ctr + r * (0 - 112) * k - u * (224 - 112) * k], dtype="float32")
        dst = np.array([[0, 0], [224, 0], [0, 224]], dtype="float32")
        M = cv2.getAffineTransform(src, dst)
        crop = cv2.warpAffine(pad, M, (224, 224))[:, :, ::-1].astype("float32") / 255.0
        o = self.hand.run(None, {"input_1": crop[None]})
        conf = float(o[1][0, 0])
        fast_mode = getattr(self, 'fast', False)
        if conf < (0.20 if fast_mode else 0.35):      # modo mouse: aceita mão em movimento/perspectiva sem derrubar tracking
            return None
        lm3 = o[0][0].reshape(21, 3)
        Mi = cv2.invertAffineTransform(M)
        pts = (Mi[:, :2] @ lm3[:, :2].T).T + Mi[:, 2]
        pts = pts - np.array([ox, oy], dtype="float32")
        zs = lm3[:, 2] * float(np.hypot(Mi[0, 0], Mi[1, 0]))
        return pts, zs, conf

    def detect(self, bgr, max_hands=2, palm_thr=0.30):
        fast_mode = getattr(self, 'fast', False)
        if fast_mode:
            palm_thr = max(palm_thr, 0.30)       # 0.20 achava "mão" no escuro em 30/30 quadros (F5)
        """Rastreia por ROI invariante dos pontos anteriores (robusto a punho e dedos abertos) e re-detecta a palma quando falta mão."""
        cv2 = self.cv2
        h, w = bgr.shape[:2]
        side = max(h, w)
        pad = np.full((side, side, 3), 0, np.uint8)
        oy, ox = (side - h) // 2, (side - w) // 2
        pad[oy:oy + h, ox:ox + w] = bgr
        off = np.array([ox, oy], dtype="float32")
        res = []
        new_tracks = []

        # 1) Mãos já rastreadas: ROI calculada sobre a estrutura óssea rígida (não encolhe ao fechar os dedos)
        raw_tracks = getattr(self, "_tracks", [])
        for tr_item in raw_tracks:
            # Compatibilidade se tr_item for ndarray ou dict
            pts = (tr_item["lm"] if isinstance(tr_item, dict) else tr_item) + off
            lost = tr_item.get("lost", 0) if isinstance(tr_item, dict) else 0

            wr, mid = pts[0], pts[9]
            u = mid - wr; nu = np.linalg.norm(u)
            if nu < 1e-3:
                continue
            u = u / nu

            # Escala estrutural óssea invariante: punho->médio e nó indicador->nó mínimo
            d_palm = float(np.linalg.norm(pts[9] - pts[0]))
            d_knuckles = float(np.linalg.norm(pts[17] - pts[5]))
            d_base = max(d_palm, d_knuckles * 1.15, 30.0)

            bw = pts[:, 0].max() - pts[:, 0].min()
            bh = pts[:, 1].max() - pts[:, 1].min()

            # Tamanho da caixa de corte: SEMPRE garante cobertura total da mão aberta mesmo se o punho estiver fechado
            size = max(bw * 1.5, bh * 1.5, d_base * 2.85, 160.0)
            if lost > 0:
                size *= 1.25 # Margem extra se perdeu no quadro anterior

            ctr = pts[0] + u * (d_base * 1.15)
            o = self._landmarks(pad, ctr, u, size, ox, oy)
            if o is None:
                if lost < 2:
                    # Tolerância temporal: mantém o foco contínuo da mão sem interrupções por motion blur momentâneo
                    last_lm = tr_item["lm"] if isinstance(tr_item, dict) else tr_item
                    last_z = tr_item.get("z", np.zeros(21, dtype="float32")) if isinstance(tr_item, dict) else np.zeros(21, dtype="float32")
                    new_tracks.append({"lm": last_lm, "z": last_z, "lost": lost + 1})
                    res.append({"lm": last_lm, "z": last_z, "conf": 0.45, "cx": float(last_lm[:, 0].mean())})
                continue

            p_, z_, c_ = o
            if any(np.linalg.norm(p_.mean(0) - r_["lm"].mean(0)) < 0.35 * size for r_ in res):
                continue
            res.append({"lm": p_, "z": z_, "conf": c_, "cx": float(p_[:, 0].mean())})
            new_tracks.append({"lm": p_, "z": z_, "lost": 0})

        # 2) Palma: re-detecta se ainda falta mão
        self._n = getattr(self, '_n', 0) + 1
        step = 1 if not res else (2 if fast_mode else 4)
        if len(res) < max_hands and self._n % step == 0:
            inp = cv2.resize(pad, (192, 192))[:, :, ::-1].astype("float32") / 255.0   # o modelo 2023feb espera 0..1
            out = self.palm.run(None, {"input_1": inp[None]})
            raw, sc = out[0][0], 1.0 / (1.0 + np.exp(-np.clip(out[1][0, :, 0], -50, 50)))
            m = sc > palm_thr
            if m.any():
                raw, sc, anc = raw[m], sc[m], self.anchors[m]
                c = raw[:, :2] / 192.0 + anc
                wh = raw[:, 2:4] / 192.0
                boxes = np.concatenate([(c - wh / 2) * side, wh * side], axis=1)
                keep = cv2.dnn.NMSBoxes(boxes.tolist(), sc.tolist(), palm_thr, 0.3)
                for i in np.array(keep).ravel():
                    if len(res) >= max_hands:
                        break
                    kp = (raw[i, 4:18].reshape(7, 2) / 192.0 + anc[i]) * side
                    wrist, mid = kp[0], kp[2]
                    u = mid - wrist; nu = np.linalg.norm(u)
                    if nu < 1e-3:
                        continue
                    u /= nu
                    cbox = boxes[i, :2] + boxes[i, 2:] / 2
                    size = max(boxes[i, 2], boxes[i, 3]) * (2.7 if fast_mode else 2.6)
                    ctr = cbox + u * 0.5 * max(boxes[i, 2], boxes[i, 3])
                    o = self._landmarks(pad, ctr, u, size, ox, oy)
                    if o is None:
                        continue
                    p_, z_, c_ = o
                    if any(np.linalg.norm(p_.mean(0) - r_["lm"].mean(0)) < 0.35 * size for r_ in res):
                        continue
                    res.append({"lm": p_, "z": z_, "conf": c_, "cx": float(p_[:, 0].mean())})
                    new_tracks.append({"lm": p_, "z": z_, "lost": 0})

        self._tracks = new_tracks
        for r_ in res:                           # brilho médio do recorte da mão: o mouse por gestos rejeita mão no escuro
            try:
                x0, y0 = np.clip(r_["lm"].min(0).astype(int), 0, [w - 1, h - 1])
                x1, y1 = np.clip(r_["lm"].max(0).astype(int) + 1, 1, [w, h])
                r_["lum"] = float(bgr[y0:y1, x0:x1].mean()) if x1 > x0 and y1 > y0 else 0.0
            except Exception:
                pass
        return res


def hand_pose(lm):
    """Classifica a forma da mão a partir de 21 pontos (px): aberta | punho | joinha | paz | apontar | ok | None."""
    d = lambda a, b: float(np.linalg.norm(lm[a] - lm[b]))
    palm = max(d(0, 9), 1e-3)                                   # punho -> base do médio
    ext = []
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):      # indicador..mindinho esticado?
        ext.append(d(tip, 0) > d(pip, 0) * 1.12)
    thumb_ext = d(4, 5) > d(3, 5) * 1.02 and d(4, 17) > palm * 0.9
    n = sum(ext)
    pinch = d(4, 8) < palm * 0.35
    if pinch and ext[1] and ext[2] and ext[3]:
        return "ok"
    if n == 0 and thumb_ext and lm[4][1] < lm[0][1] - palm * 0.25:
        return "joinha"
    if n == 0:
        return "punho"
    if ext[0] and ext[1] and not ext[2] and not ext[3]:
        return "paz"
    if ext[0] and not ext[1] and not ext[2] and not ext[3]:
        return "apontar"
    if n >= 4 or (n == 3 and thumb_ext):
        return "aberta"
    return None


# ---------- visão do rosto (YuNet) p/ a msg "visao": sorriso, yaw/pitch/roll, "olhando a tela" — matemática pura, sem E/S ----------
SORRISO_ESCALA = 0.15     # razão boca/olhos acima da linha de base que vale sorriso pleno (1,0)
YAW_ESCALA = 0.50         # deslocamento do nariz / distância entre olhos que vale ±1 (~45°)
PITCH_ESCALA = 0.28       # variação da altura do nariz (fração olhos -> boca) que vale ±1 (~30°)
ROLL_ESCALA = math.pi / 4  # inclinação da linha dos olhos que vale ±1 (45°)


def _lim(v, a=-1.0, b=1.0):
    return a if v < a else b if v > b else v


def _base_adapt(amostras, pct, tipico, peso=8):
    """linha de base: percentil das amostras recentes, puxado p/ o valor típico enquanto há poucas (peso = nº de amostras do típico)."""
    n = len(amostras) if amostras else 0
    if not n:
        return tipico
    p = float(np.percentile(np.asarray(amostras, dtype="float64"), pct))
    return (tipico * peso + p * n) / (peso + n)


def caixa_norm(box, W, H):
    """[x,y,w,h] em px -> 0..1 do quadro WxH, recortada no quadro (3 casas)."""
    x, y, w, h = [float(a) for a in box[:4]]
    x0, y0 = _lim(x / W, 0.0, 1.0), _lim(y / H, 0.0, 1.0)
    x1, y1 = _lim((x + w) / W, 0.0, 1.0), _lim((y + h) / H, 0.0, 1.0)
    return [round(x0, 3), round(y0, 3), round(x1 - x0, 3), round(y1 - y0, 3)]


def metricas_rosto(linha, estado, W=320, H=240, aspecto=1.0, agora=None):
    """Métricas de UM rosto do YuNet. linha = x,y,w,h, olho dir, olho esq, ponta do nariz, canto dir da boca, canto esq da boca[, score]
    nas coordenadas do quadro WxH que foi ao detector; aspecto = largura/altura real de 1 px desse quadro (1280x720 reduzido a
    320x240 -> 4/3), p/ a geometria não sair achatada. estado = dict mutável DA PESSOA (linhas de base adaptativas, suavização,
    histerese) — comece com {}. Devolve None se os pontos não formam um rosto plausível, senão
    {"box":[x,y,w,h] 0..1 ESPELHADO, "sorriso":0..1, "yaw":-1..1, "pitch":-1..1, "roll":-1..1, "olhando":bool}.
    Convenções na imagem espelhada (como o dono se vê na miniatura): yaw + = rosto virado p/ a direita da imagem (o lado direito
    dele); pitch + = olhando p/ cima; roll + = cabeça inclinada no sentido horário (p/ o ombro direito dele), 1,0 = 45°."""
    try:
        v = [float(a) for a in list(linha)[:14]]
    except Exception:
        return None
    if len(v) < 14 or not all(math.isfinite(a) for a in v) or W <= 0 or H <= 0:
        return None
    agora = time.time() if agora is None else float(agora)
    x, y, w, h = v[:4]
    (ax, ay), (bx, by), (nx, ny), (c1x, c1y), (c2x, c2y) = [(v[4 + 2 * i] * aspecto, v[5 + 2 * i]) for i in range(5)]
    d = math.hypot(bx - ax, by - ay)                           # distância entre os olhos (px "quadrados")
    if d < 2.0:
        return None
    ux, uy = (bx - ax) / d, (by - ay) / d
    if ux < 0:                                                 # eixo dos olhos sempre p/ a direita da imagem original (não depende da ordem)
        ux, uy = -ux, -uy
    vx, vy = -uy, ux                                           # eixo "p/ baixo" do rosto (o y da imagem cresce p/ baixo)
    mx, my = (ax + bx) / 2, (ay + by) / 2                      # meio dos olhos
    n_u = (nx - mx) * ux + (ny - my) * uy                      # nariz ao longo da linha dos olhos
    n_v = (nx - mx) * vx + (ny - my) * vy                      # nariz descendo a partir dos olhos
    m_v = ((c1x + c2x) / 2 - mx) * vx + ((c1y + c2y) / 2 - my) * vy     # meio da boca descendo a partir dos olhos
    boca = math.hypot(c2x - c1x, c2y - c1y)
    if m_v < 0.3 * d or boca < 0.25 * d:
        return None
    r = boca / d                                               # ~0,8 com a boca neutra; o sorriso estica os cantos
    tn = n_v / m_v                                             # altura do nariz entre olhos (0) e boca (1): ~0,5 de frente
    yaw_b = -n_u / d                                           # espelhado: nariz p/ a esquerda da imagem original = direita do espelho
    roll_b = -math.atan2(uy, ux)                               # espelhar inverte o sentido da rotação
    # suavização leve (a interface ainda anima): constante de tempo em s, independe do fps
    dt = agora - estado.get("t", -1e9)
    estado["t"] = agora
    novo = dt > 1.0 or dt < 0                                  # 1º quadro ou voltou depois de sumir: sem arrasto do valor velho

    def ema(k, alvo, tau):
        if novo or k not in estado:
            estado[k] = alvo
        else:
            estado[k] += (alvo - estado[k]) * (1.0 - math.exp(-dt / tau))
        return estado[k]
    rs, rl = ema("r", r, 0.15), ema("r_lento", r, 0.5)
    ys, ts, rr = ema("yaw", yaw_b, 0.12), ema("tn", tn, 0.12), ema("roll", roll_b, 0.12)
    # linhas de base por pessoa (2 amostras/s dos últimos ~2 min): a boca neutra é das mais estreitas (percentil 35 — sorrir só
    # alarga; falar às vezes estreita); a altura do nariz usa a mediana com o rosto de frente (a pose de sempre, olhando a tela)
    if agora - estado.get("t_am", -1e9) >= 0.5:
        estado["t_am"] = agora
        estado.setdefault("am_r", deque(maxlen=240)).append(rl)
        if abs(ys) < 0.2:
            estado.setdefault("am_t", deque(maxlen=240)).append(ts)
        estado["base_r"] = _lim(_base_adapt(estado["am_r"], 35, 0.80), 0.6, 1.0)
        estado["base_t"] = _lim(_base_adapt(estado.get("am_t"), 50, 0.50), 0.3, 0.7)
    sorriso = _lim((rs - estado.get("base_r", 0.80) - 0.015) / SORRISO_ESCALA, 0.0, 1.0)
    yaw = _lim(ys / YAW_ESCALA)
    pitch = _lim((estado.get("base_t", 0.50) - ts) / PITCH_ESCALA)
    roll = _lim(rr / ROLL_ESCALA)
    olh = estado.get("olhando", True)                          # de frente p/ a tela, com histerese (não pisca na fronteira)
    olh = abs(yaw) < (0.48 if olh else 0.38) and abs(pitch) < (0.52 if olh else 0.40)
    estado["olhando"] = olh
    x0, x1 = _lim(1.0 - (x + w) / W, 0.0, 1.0), _lim(1.0 - x / W, 0.0, 1.0)      # espelha e recorta no quadro
    y0, y1 = _lim(y / H, 0.0, 1.0), _lim((y + h) / H, 0.0, 1.0)
    return {"box": [round(x0, 3), round(y0, 3), round(x1 - x0, 3), round(y1 - y0, 3)], "sorriso": round(sorriso, 3) + 0.0,
            "yaw": round(yaw, 3) + 0.0, "pitch": round(pitch, 3) + 0.0, "roll": round(roll, 3) + 0.0, "olhando": bool(olh)}   # + 0.0: sem "-0.0"


class VisaoRostos:
    """Rostos da câmera nativa p/ a msg "visao": acompanha cada caixa do YuNet entre quadros (suavização e linhas de base POR
    PESSOA), junta a identidade da thread do SFace (scene["faces"], ~0,7 s, caixas em 640x480 = 2x as do YuNet) por centro e
    segura uma falha de detecção de 1-2 quadros (o rosto não pisca). Sem E/S: testável com dados sintéticos."""

    def __init__(self, W=320, H=240, segura=0.4, max_rostos=3):
        self.W, self.H, self.segura, self.max = float(W), float(H), float(segura), int(max_rostos)
        self.trilhas = []          # [{"id","c":(cx,cy),"t","area","nome","t_nome","sim","chave","saida"}]
        self.estados = {}          # chave da pessoa -> estado de metricas_rosto (quem tem nome mantém a linha de base entre aparições)
        self._seq = 0

    def atualizar(self, faces, ident=(), dono="", agora=None, aspecto=1.0, ident_escala=2.0):
        """faces: saída do YuNet (N x 15, coords WxH) ou None; ident: scene["faces"] recente ([] se velho); dono: nome do dono.
        Devolve até max_rostos dicts do contrato "visao" {nome,dono,sim,box,sorriso,yaw,pitch,roll,olhando}, maior primeiro."""
        agora = time.time() if agora is None else float(agora)
        W, H = self.W, self.H
        dono = str(dono or "").strip().lower()
        linhas = []
        for f in (faces if faces is not None else ()):
            try:
                f = [float(a) for a in list(f)[:15]]
            except Exception:
                continue
            if len(f) >= 14 and f[2] > 1 and f[3] > 1:
                linhas.append(f)
        linhas = sorted(linhas, key=lambda f: -f[2] * f[3])[:self.max]
        ids = []                                               # identidades do SFace, de volta à escala do YuNet
        for e in ident or ():
            try:
                bx = [float(a) / ident_escala for a in (e.get("box") or [])[:4]]
                sm = float(e.get("sim") or 0.0)
                if len(bx) == 4 and all(math.isfinite(a) for a in bx):
                    ids.append((bx, str(e.get("nome") or "").strip(), sm if math.isfinite(sm) else 0.0))
            except Exception:
                continue
        usadas_t, usadas_i, chaves = set(), set(), set()
        for f in linhas:
            x, y, w, h = f[:4]
            cx, cy, tam = (x + w / 2) / W, (y + h / 2) / H, max(w / W, h / H)
            tr, dmin = None, max(0.08, 0.6 * tam)              # 1) trilha mais próxima ainda livre (o rosto anda pouco entre quadros)
            for t_ in self.trilhas:
                dd = math.hypot(t_["c"][0] - cx, t_["c"][1] - cy)
                if t_["id"] not in usadas_t and dd < dmin:
                    tr, dmin = t_, dd
            if tr is None:
                self._seq += 1
                tr = {"id": self._seq, "nome": "", "t_nome": 0.0, "sim": 0.0, "chave": "", "saida": None}
                self.trilhas.append(tr)
            usadas_t.add(tr["id"])
            tr.update(c=(cx, cy), t=agora, area=w * h)
            bi, bd = None, 0.6                                 # 2) identidade: caixa do SFace de centro mais perto (relativo ao tamanho)
            for k, (bx, _nm, _sm) in enumerate(ids):
                dc = math.hypot((bx[0] + bx[2] / 2) / W - cx, (bx[1] + bx[3] / 2) / H - cy) / max(tam, 1e-3)
                if k not in usadas_i and dc < bd:
                    bi, bd = k, dc
            if bi is not None:
                usadas_i.add(bi)
                nm, sm = ids[bi][1], ids[bi][2]
                if nm:
                    tr.update(nome=nm, t_nome=agora, sim=sm)
                elif agora - tr["t_nome"] > 5.0:               # SFace diz "desconhecido" há um tempo: solta o nome
                    tr.update(nome="", sim=sm)
            elif tr["nome"] and agora - tr["t_nome"] > 5.0:
                tr.update(nome="", sim=0.0)
            chave = ("n:" + tr["nome"].strip().lower()) if tr["nome"] else ("t:%d" % tr["id"])
            if chave in chaves:                                # 2 rostos com o mesmo nome: não mistura a suavização
                chave = "t:%d" % tr["id"]
            chaves.add(chave)
            if chave != tr["chave"] and tr["chave"].startswith("t:"):
                est_ant = self.estados.pop(tr["chave"], None)
                if est_ant is not None and chave not in self.estados:
                    self.estados[chave] = est_ant              # ganhou nome: herda a linha de base da trilha
            tr["chave"] = chave
            m = metricas_rosto(f, self.estados.setdefault(chave, {}), W, H, aspecto, agora)
            if m is not None:
                nome = tr["nome"]
                tr["saida"] = {"nome": nome, "dono": bool(nome) and nome.strip().lower() == dono,
                               "sim": round(_lim(float(tr["sim"]), 0.0, 1.0), 3) + 0.0, **m}
        vivas = []                                             # sem detecção agora: segura a última saída por um instante
        for t_ in self.trilhas:
            if agora - t_["t"] <= self.segura:
                vivas.append(t_)
            elif t_["chave"].startswith("t:"):
                self.estados.pop(t_["chave"], None)            # anônimo que sumiu: esquece a suavização dele
        self.trilhas = vivas
        if len(self.estados) > 16:                             # nomes demais: fica com os 16 vistos por último
            for k in sorted(self.estados, key=lambda k: self.estados[k].get("t", 0.0))[:-16]:
                del self.estados[k]
        saida = [t_["saida"] for t_ in sorted(self.trilhas, key=lambda t_: -t_.get("area", 0.0)) if t_.get("saida")]
        return saida[:self.max]
