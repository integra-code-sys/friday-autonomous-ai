"""OCR local em português: RapidOCR (detector PP-OCRv3) + reconhecedor PP-OCRv5 LATIN (acentos de pt-BR).

Medido 16/10/2026 numa tela 1920x1080 real: tesseract lia "variagées", "prdpria", "DIAGNGSTICO"; este lê "variações",
"própria", "DIAGNÓSTICO". Mesmo tempo (~3,8 s com o daemon ligado). Sem o modelo/pacote, devolve None e quem chama usa o tesseract.
Modelo: models/ocr/latin_rec.onnx + latin_dict.txt (huggingface.co/monkt/paddleocr-onnx, Apache 2.0).
"""
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_M = os.path.join(ROOT, "models", "ocr")
_lock = threading.Lock()
_ocr = [None]


def _motor():
    if _ocr[0] is None:
        from rapidocr_onnxruntime import RapidOCR
        from rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize import TextRecognizer
        o = RapidOCR()
        o.use_angle_cls = False                       # tela não tem texto de cabeça para baixo (economiza ~10%)
        o.text_recognizer = TextRecognizer({"model_path": os.path.join(_M, "latin_rec.onnx"),
                                            "keys_path": os.path.join(_M, "latin_dict.txt"),
                                            "rec_img_shape": [3, 48, 320], "rec_batch_num": 6, "use_cuda": False})
        _ocr[0] = o
    return _ocr[0]


def disponivel():
    return os.path.exists(os.path.join(_M, "latin_rec.onnx"))


def linhas(img, conf_min=0.5):
    """img BGR -> [{"t", "x0", "y0", "x1", "y1", "conf"}] em pixels da imagem, ordem de leitura. None se o OCR não existir."""
    if not disponivel():
        return None
    try:
        with _lock:
            r, _ = _motor()(img)
    except Exception as e:
        print("ocr_pt:", repr(e)[:120], flush=True)
        return None
    out = []
    for caixa, texto, conf in r or []:
        if float(conf) < conf_min or not str(texto).strip():
            continue
        xs, ys = [p[0] for p in caixa], [p[1] for p in caixa]
        out.append({"t": str(texto).strip(), "x0": int(min(xs)), "y0": int(min(ys)), "x1": int(max(xs)), "y1": int(max(ys)), "conf": float(conf)})
    out.sort(key=lambda d: ((d["y0"] + d["y1"]) // 36, d["x0"]))
    return out


def texto(img, n=80):
    """texto da imagem em linhas 'texto @x,y' (centro) para ir no prompt do modelo de visão/cérebro."""
    ls = linhas(img)
    if not ls:
        return ""
    return "\n".join(f"{d['t']} @{(d['x0'] + d['x1']) // 2},{(d['y0'] + d['y1']) // 2}" for d in ls[:n])
