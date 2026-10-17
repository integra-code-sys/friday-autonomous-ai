"""Detector de objetos de VOCABULÁRIO ABERTO (YOLOE-11s, Ultralytics/AGPL, uso pessoal) com os objetos da casa embutidos.

Mesma interface do senses.ObjectDet: detect(bgr, conf) -> [(nome_pt, conf, [x, y, w, h] em px)].
O vocabulário (inglês -> português) fica em models/yoloe/vocab.json; para incluir um objeto novo, acrescente o par e rode
  .venv-yoloe/bin/python models/yoloe/exportar.py
que regrava models/yoloe/yoloe_casa.onnx (o daemon só precisa do onnxruntime, sem torch).
"""
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONNX = os.path.join(ROOT, "models", "yoloe", "yoloe_casa.onnx")
META = os.path.join(ROOT, "models", "yoloe", "yoloe_casa.json")


def disponivel():
    return os.path.exists(ONNX) and os.path.exists(META)


class DetYOLOE:
    def __init__(self, threads=3):
        import cv2
        import onnxruntime as ort
        self.cv2 = cv2
        o = ort.SessionOptions()
        o.intra_op_num_threads = threads
        o.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(ONNX, o, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name
        self.nomes = json.load(open(META))["classes_pt"]
        self.nc = len(self.nomes)

    def detect(self, bgr, conf=0.35):
        cv2 = self.cv2
        h, w = bgr.shape[:2]
        r = min(640 / w, 640 / h)
        nw, nh = int(round(w * r)), int(round(h * r))
        canvas = np.full((640, 640, 3), 114, np.uint8)
        canvas[:nh, :nw] = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype("float32") / 255.0
        out = self.sess.run(["output0"], {self.inp: blob})[0][0]          # (4 + nc + 32 máscaras, 8400)
        cls = out[4:4 + self.nc]
        ci = cls.argmax(0)
        sc = cls[ci, np.arange(cls.shape[1])]
        m = sc > conf
        if not m.any():
            return []
        cx, cy, bw, bh = out[0][m], out[1][m], out[2][m], out[3][m]
        boxes = np.stack([cx - bw / 2, cy - bh / 2, bw, bh], 1) / r
        sc, ci = sc[m], ci[m]
        keep = cv2.dnn.NMSBoxes(boxes.tolist(), sc.tolist(), conf, 0.5)
        return [(self.nomes[int(ci[i])], float(sc[i]), boxes[i].tolist()) for i in np.array(keep).ravel()]
