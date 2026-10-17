"""Pose 3D do corpo (MediaPipe Pose, ONNX local): 33 pontos em px + coordenadas "mundo" em metros.
Usa o box da pessoa (YOLOv8-pose) como ROI; sem rotação. body.infer(bgr, box_xyxy) -> dict | None."""
import os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "models", "pose_estimation_mediapipe_2023mar.onnx")


class BodyPose:
    def __init__(self, thr=0.5):
        import cv2, onnxruntime as ort
        self.cv2 = cv2
        so = ort.SessionOptions(); so.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(MODEL, so, providers=["CPUExecutionProvider"])
        self.name = self.sess.get_inputs()[0].name
        self.thr = thr

    def infer(self, bgr, box, enlarge=1.25):
        """box = (x0, y0, x1, y1) em px. Retorna {"px": (33,5) [x,y,z,vis,pres], "w": (33,3), "conf": float}."""
        cv2 = self.cv2
        H, W = bgr.shape[:2]
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        side = max(box[2] - box[0], box[3] - box[1]) * enlarge
        x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
        s = int(round(side))
        if s < 32:
            return None
        pl, pt = max(0, -x0), max(0, -y0)
        pr, pb = max(0, x0 + s - W), max(0, y0 + s - H)
        crop = bgr[max(0, y0):min(H, y0 + s), max(0, x0):min(W, x0 + s)]
        if crop.size == 0:
            return None
        if pl or pt or pr or pb:
            crop = cv2.copyMakeBorder(crop, pt, pb, pl, pr, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        blob = cv2.cvtColor(cv2.resize(crop, (256, 256), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        blob = (blob.astype("float32") / 255.0)[None]
        outs = self.sess.run(None, {self.name: blob})
        lm, conf, _mask, _hm, lw = outs[0], outs[1], outs[2], outs[3], outs[4]
        c = float(np.ravel(conf)[0])
        if c < self.thr:
            return None
        L = lm[0].reshape(-1, 5).copy()[:33]
        W3 = lw[0].reshape(-1, 3).copy()[:33]
        L[:, 3:] = 1.0 / (1.0 + np.exp(-L[:, 3:]))
        k = s / 256.0
        L[:, 0] = x0 + L[:, 0] * k
        L[:, 1] = y0 + L[:, 1] * k
        L[:, 2] = L[:, 2] * k
        return {"px": L, "w": W3, "conf": c}
