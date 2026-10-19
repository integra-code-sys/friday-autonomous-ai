"""Motor Unificado de Visão Multimodal da Sexta-Feira (F.R.I.D.A.Y.).
Lê a tela interna (grim/Wayland), câmera nativa (/dev/video2) e câmera externa (/dev/video0),
com pré-processamento para ambientes escuros (CLAHE) e inferência neural VLM via GPU local (RTX 3050).
"""
import base64
import json
import os
import re
import subprocess
import time
import urllib.request

import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import win_compat
ROOT = os.path.dirname(HERE)

VLM_MODEL = os.environ.get("FRIDAY_VLM_MODEL", os.environ.get("FRIDAY_MODEL", "qwen3-vl:4b-instruct"))
OLLAMA_URL = os.environ.get("FRIDAY_OLLAMA", "http://127.0.0.1:11434")
NUM_GPU = int(os.environ.get("FRIDAY_NUM_GPU", "99"))
NUM_CTX = int(os.environ.get("FRIDAY_NUM_CTX", "16384"))   # igual ao friday.NUM_CTX
# mesmas opções do friday.py (num_ctx/num_gpu iguais e sem keep_alive): opção diferente faz o Ollama recarregar o modelo
OPCOES_BASE = {"num_ctx": NUM_CTX, "num_gpu": NUM_GPU}

DEV_NATIVA = "/dev/video2"
DEV_EXTERNA = "/dev/video0"
CAM_NATIVA = DEV_NATIVA
CAM_EXTERNA = DEV_EXTERNA

# fontes em memória: o daemon registra as câmeras que já estão abertas (não disputa o /dev/video com ele)
_FONTES = {}


def registrar_fonte(nome, quadro, ativa=None):
    """nome = "nativa"|"externa"; quadro() -> BGR recente ou None; ativa() -> True se o daemon está com a câmera ligada."""
    _FONTES[nome] = (quadro, ativa)


def _quadro_jpg(frame):
    import cv2
    frame = realcar_baixa_luz(frame)
    h, w = frame.shape[:2]
    scale = min(1024 / w, 768 / h, 1.0)
    if scale < 1.0:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok_jpg, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return jpg.tobytes() if ok_jpg else None


def _quadro(nome, dev):
    """quadro já em memória; só abre o /dev/video se a câmera do daemon estiver parada (ou fora do daemon)."""
    quadro, ativa = _FONTES.get(nome, (None, None))
    if quadro is not None:
        try:
            f = quadro()
            if f is not None:
                return _quadro_jpg(f)
            if ativa is None or ativa():
                return None                  # câmera ligada no daemon, só sem quadro recente: não briga pelo dispositivo
        except Exception:
            pass
    return capturar_camera(dev)


def quadro_nativa():
    return _quadro("nativa", _detectar_dispositivos()[0])


def quadro_externa():
    return _quadro("externa", _detectar_dispositivos()[1])



def _detectar_dispositivos():
    """Descobre os caminhos atuais das câmeras nativa e externa."""
    import glob
    nat, ext = None, None
    for p in sorted(glob.glob("/dev/v4l/by-id/*-video-index0")):
        real = os.path.realpath(p)
        if "integrated" in p.lower():
            nat = real
        else:
            ext = real
    return nat or DEV_NATIVA, ext or DEV_EXTERNA


def realcar_baixa_luz(frame):
    """Realce adaptativo de imagem para salas escuras ou iluminação noturna (CLAHE + Gama)."""
    import cv2
    import numpy as np
    m = float(frame.mean())
    if m < 85:
        g = np.clip(85.0 / max(m, 15.0), 1.0, 2.5)
        lut = (255.0 * (np.arange(256) / 255.0) ** (1.0 / g)).astype("uint8")
        frame = cv2.LUT(frame, lut)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(lab[:, :, 0])
        frame = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    return frame


_ULTIMA_TELA = [None]


def texto_da_tela(n=70):
    """OCR pt-BR da última captura em resolução real: o texto pequeno que o VLM não lê na tela reduzida a 1280x720."""
    try:
        import ocr_pt
        return ocr_pt.texto(_ULTIMA_TELA[0], n) if _ULTIMA_TELA[0] is not None else ""
    except Exception:
        return ""


def capturar_tela():
    """Captura a tela interna (grim no Wayland ou win_compat no Windows) e redimensiona mantendo nitidez de textos."""
    import cv2
    if win_compat.IS_WINDOWS:
        img = win_compat.capturar_tela()
        if img is None:
            return None
        _ULTIMA_TELA[0] = img
        h, w = img.shape[:2]
        scale = min(1280 / w, 720 / h, 1.0)
        if scale < 1.0:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return jpg.tobytes() if ok else None

    tmp = "/tmp/friday_screen_capture.png"
    try:
        r = subprocess.run(["grim", tmp], capture_output=True, timeout=3)
        if r.returncode != 0 or not os.path.exists(tmp):
            return None
        img = cv2.imread(tmp)
        if img is None:
            return None
        _ULTIMA_TELA[0] = img                     # resolução REAL guardada p/ o OCR (o VLM recebe a reduzida)
        h, w = img.shape[:2]
        scale = min(1280 / w, 720 / h, 1.0)
        if scale < 1.0:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return jpg.tobytes() if ok else None
    except Exception as e:
        print("erro captura tela:", e, flush=True)
        return None
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def capturar_camera(dev_path):
    """Captura um quadro de uma câmera específica (/dev/video* ou DirectShow no Windows) com tratamento de luz."""
    import cv2
    if win_compat.IS_WINDOWS:
        idx = dev_path if isinstance(dev_path, int) else 0
        cap = win_compat.abrir_camera(idx)
    else:
        cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(dev_path)
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        return _quadro_jpg(frame)
    finally:
        cap.release()


def consultar_vlm(jpg_bytes, prompt, max_tokens=180, temp=0.1):
    """Envia uma imagem ao modelo multimodal Vision configurado (Gemini, Claude, OpenAI GPT ou Ollama Local)."""
    if not jpg_bytes:
        return None
    try:
        import cloud_providers
        return cloud_providers.consultar_vlm(jpg_bytes, prompt, max_tokens=max_tokens, temp=temp)
    except Exception as e:
        print("visão neural falhou:", str(e)[:120], flush=True)
        return None



def olhar_tela(pergunta="Descreva o que está aberto e visível nesta tela do computador.") -> str:
    """Lê a tela do usuário e retorna a interpretação visual do que está exibido."""
    jpg = capturar_tela()
    if not jpg:
        return "Não consegui capturar a tela do computador agora."
    ocr = texto_da_tela()
    dica = ("\nTexto lido na tela por OCR em resolução real (texto @x,y; use para ler nomes, números e textos pequenos "
            "com exatidão):\n" + ocr + "\n") if ocr else ""
    return consultar_vlm(jpg, "Observe a tela do computador e responda: " + pergunta + dica, max_tokens=260) or "Não consegui interpretar a tela agora."


def olhar_camera_nativa(pergunta="O que a câmera frontal/mãos está mostrando?") -> str:
    """Lê a câmera integrada do notebook (mãos no teclado, mesa, face do usuário)."""
    jpg = quadro_nativa()
    if not jpg:
        return "Não consegui abrir a câmera nativa do notebook."
    return consultar_vlm(jpg, "Observe a imagem da câmera frontal/nativa e responda: " + pergunta) or "Não consegui interpretar a câmera nativa agora."


def olhar_camera_externa(pergunta="O que a câmera ambiente está mostrando?") -> str:
    """Lê a câmera USB externa (sala, ambiente, postura do usuário)."""
    jpg = quadro_externa()
    if not jpg:
        return "Não consegui abrir a câmera externa do ambiente."
    return consultar_vlm(jpg, "Observe a imagem da câmera externa do ambiente e responda: " + pergunta) or "Não consegui interpretar a câmera externa agora."


def olhar_tudo(pergunta="Descreva o contexto geral observado.") -> str:
    """Visão multimodal integrada: combina tela do PC, câmera nativa e câmera externa em uma única leitura contextual."""
    partes = []
    tela_txt = olhar_tela("Quais aplicativos e conteúdos principais estão na tela?")
    if tela_txt and "não consegui" not in tela_txt.lower():
        partes.append(f"Na tela: {tela_txt}")
    cam_txt = olhar_camera_nativa("O que o usuário está fazendo ou segurando em frente ao PC?")
    if cam_txt and "não consegui" not in cam_txt.lower():
        partes.append(f"Na câmera frontal: {cam_txt}")
    cam_ext_txt = olhar_camera_externa("O que está visível ao redor ou no ambiente?")
    if cam_ext_txt and "não consegui" not in cam_ext_txt.lower():
        partes.append(f"Na câmera de ambiente: {cam_ext_txt}")
    return " | ".join(partes) or "Não foi possível obter dados dos sensores visuais agora."


def dispositivos_status():
    """Retorna o estado dos 3 canais de visão."""
    nat, ext = _detectar_dispositivos()
    return {
        "tela": os.path.exists("/usr/bin/grim"),
        "camera_nativa": os.path.exists(nat),
        "camera_externa": os.path.exists(ext),
        "dev_nativa": nat,
        "dev_externa": ext,
        "modelo_vlm": VLM_MODEL
    }


def preparar():
    """Pré-aquecimento do modelo de visão (VLM) no Ollama para garantir baixa latência."""
    try:
        req = urllib.request.Request(
            OLLAMA_URL + "/api/generate",
            json.dumps({"model": VLM_MODEL, "prompt": "ok", "stream": False, "options": dict(OPCOES_BASE, num_predict=1)}).encode(),
            {"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


def _confere(desc, cx, cy, jpg, w, h):
    """zoom: recorta ao redor do ponto achado (~220 px reais, x4) e pergunta ao VLM se é mesmo o alvo (evita clique no lugar errado).
    Restaurado do visao.py.v1bak; falha do VLM não bloqueia (como antes)."""
    try:
        import cv2
        import numpy as np
        im = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        s = im.shape[1] / float(w)                        # a captura pode vir reduzida (1280x720)
        r = max(int(110 * s), 24)
        x, y = int(cx * s), int(cy * s)
        c = im[max(0, y - r):y + r, max(0, x - r):x + r]
        c = cv2.resize(c, (c.shape[1] * 880 // max(c.shape[1], 1), c.shape[0] * 880 // max(c.shape[1], 1)), interpolation=cv2.INTER_CUBIC)
        ok, b = cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 90])
        a = consultar_vlm(b.tobytes(), f"Does this image contain {desc}? Answer only YES or NO.", max_tokens=5, temp=0.0) if ok else None
        if a is None:
            return True
        a = a.strip().upper()
        return "YES" in a[:60] or a.startswith("S")       # "Sim" (o prompt pede português)
    except Exception:
        return True


def localizar(descricao: str, jpg_bytes=None, w=1920, h=1080, conferir=True):
    """Localiza na tela um elemento pela descrição visual e retorna {'x': int, 'y': int} em pixels reais.
    conferir: todo palpite passa pelo zoom (_confere); recusado -> None."""
    jpg = jpg_bytes or capturar_tela()
    if not jpg:
        return None
    p = _localizar(descricao, jpg, w, h)
    if p and not jpg_bytes:
        p = _refinar(descricao, p, w, h) or p
    if p and conferir and not _confere(descricao, p["x"], p["y"], jpg, w, h):
        print("localizar: zoom não confirmou", descricao[:60], p, flush=True)
        return None
    return p



def _refinar(desc, p, w, h, rw=640, rh=360):
    """2º passe: recorte em resolução REAL (sem a redução p/ 1280x720) ao redor do palpite -> erro de ~15 px cai p/ poucos px."""
    try:
        import cv2
        im = cv2.imread("/tmp/friday_screen_capture.png")   # gravada por capturar_tela() em tamanho real
        if im is None or im.shape[1] != w:
            return None
        x0 = min(max(p["x"] - rw // 2, 0), w - rw); y0 = min(max(p["y"] - rh // 2, 0), h - rh)
        ok, b = cv2.imencode(".jpg", im[y0:y0 + rh, x0:x0 + rw], [cv2.IMWRITE_JPEG_QUALITY, 92])
        raw = consultar_vlm(b.tobytes(), f"Locate {desc} in the image. Output only JSON: {{\"bbox_2d\": [x1, y1, x2, y2]}} normalized 0-1000. "
                            "If it is not in the image output {\"bbox_2d\": []}.", max_tokens=60, temp=0.0) if ok else None
        m = re.search(r"\[\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\]", raw or "")
        if not m:
            return None
        a = [float(v) for v in m.groups()]
        q = {"x": int(x0 + (a[0] + a[2]) / 2000 * rw), "y": int(y0 + (a[1] + a[3]) / 2000 * rh)}
        return q if abs(q["x"] - p["x"]) < rw * 0.45 and abs(q["y"] - p["y"]) < rh * 0.45 else None
    except Exception as e:
        print("refinar:", e, flush=True)
        return None

def _localizar(descricao, jpg, w, h):
    prompt = (
        f"Localize na tela o seguinte elemento: '{descricao}'. "
        "Retorne APENAS um objeto JSON no formato: {\"x\": <inteiro 0 a 1000>, \"y\": <inteiro 0 a 1000>} "
        "indicando as coordenadas do centro do elemento normalizadas de 0 a 1000, onde (0,0) é o canto superior esquerdo "
        "e (1000,1000) é o canto inferior direito. Sem explicações ou markdown, apenas o JSON."
    )
    raw = consultar_vlm(jpg, prompt, max_tokens=80, temp=0.0)
    if not raw:
        return None
    try:
        m = re.search(r"\{[^{}]*\}", raw)
        if m:
            d = json.loads(m.group(0))
            if "x" in d and "y" in d:
                nx = float(d["x"])
                ny = float(d["y"])
                if nx > 1000 or ny > 1000:
                    return {"x": int(min(max(nx, 0), w)), "y": int(min(max(ny, 0), h))}
                real_x = int(min(max(nx / 1000.0 * w, 0), w))
                real_y = int(min(max(ny / 1000.0 * h, 0), h))
                return {"x": real_x, "y": real_y}
            if "point" in d:
                p = d["point"]
                nx, ny = float(p[0]), float(p[1])        # Qwen-VL: [x, y]
                return {"x": int(min(max(nx / 1000.0 * w, 0), w)), "y": int(min(max(ny / 1000.0 * h, 0), h))}
            if "box_2d" in d:
                b = d["box_2d"]                          # Qwen-VL: [x1, y1, x2, y2]
                nx = (float(b[0]) + float(b[2])) / 2.0
                ny = (float(b[1]) + float(b[3])) / 2.0
                return {"x": int(min(max(nx / 1000.0 * w, 0), w)), "y": int(min(max(ny / 1000.0 * h, 0), h))}
    except Exception as e:
        print("erro parse localizar:", e, raw, flush=True)
    return None


def tela_com_erro():
    """OCR local (tesseract) da tela: True só se aparecer Traceback|Error (gatilho da ajuda proativa, sem VLM)."""
    tmp = "/tmp/friday_screen_ocr.png"
    try:
        if subprocess.run(["grim", tmp], capture_output=True, timeout=3).returncode != 0:
            return False
        r = subprocess.run(["tesseract", tmp, "stdout", "-l", "eng", "--psm", "11"], capture_output=True, text=True, timeout=12,
                           env=dict(os.environ, OMP_THREAD_LIMIT="1"))    # 1 núcleo: não disputa CPU com Whisper/TTS
        return bool(re.search(r"Traceback|Error", r.stdout or ""))
    except Exception:
        return False
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def analisar_ajuda_multimodal(jpg_tela=None, jpg_camera=None, rosto=False) -> dict:
    """Ajuda proativa: tela só por evento (OCR casando Traceback|Error); expressão do rosto só com rosto=True
    ("vigilia_rosto" em memory/friday.json, desligado por padrão)."""
    if not jpg_tela and tela_com_erro():
        jpg_tela = capturar_tela()
    if not rosto:
        jpg_camera = None
    elif not jpg_camera:
        jpg_camera = quadro_nativa()

    if not jpg_tela and not jpg_camera:
        return {"precisa_ajuda": False, "motivo": "", "oferta_texto": "", "tarefa": ""}

    res = {"precisa_ajuda": False, "motivo": "", "oferta_texto": "", "tarefa": ""}

    # 1. Analisa a tela em busca de erros no terminal ou falhas
    if jpg_tela:
        prompt_tela = (
            "Analise a tela do usuário. Verifique se há algum erro evidente (ex: traceback, falha de compilação, erro vermelho no terminal, página de erro, exceção). "
            "Se houver erro ou dificuldade aparente, determine se uma oferta de ajuda curta e proativa faz sentido. "
            "Responda SOMENTE um JSON: "
            "{\"erro_na_tela\": true|false, \"descricao_erro\": \"...\", \"oferta_sugerida\": \"frase curta em pt-BR oferecendo ajuda útil (ex: Vi que deu erro no terminal. Quer que eu analise e corrija?)\", \"tarefa\": \"ação concreta para resolver\"}. "
            "Se a tela estiver normal ou sem erros, retorne erro_na_tela: false."
        )
        raw_tela = consultar_vlm(jpg_tela, prompt_tela, max_tokens=150, temp=0.1)
        try:
            m = re.search(r"\{[^{}]*\}", raw_tela or "")
            if m:
                d = json.loads(m.group(0))
                if d.get("erro_na_tela") and d.get("oferta_sugerida") and d.get("tarefa"):
                    res["precisa_ajuda"] = True
                    res["motivo"] = d.get("descricao_erro", "erro na tela")
                    res["oferta_texto"] = d.get("oferta_sugerida", "")
                    res["tarefa"] = d.get("tarefa", "")
                    return res
        except Exception:
            pass

    # 2. Analisa a câmera em busca de expressões de frustração ou dúvida
    if jpg_camera:
        prompt_face = (
            "Observe a expressão facial da pessoa em frente ao computador. Ela parece demonstrar frustração, dúvida intensa ou confusão diante da tela? "
            "Responda SOMENTE JSON: {\"confuso_ou_frustrado\": true|false, \"expressao\": \"...\"}"
        )
        raw_face = consultar_vlm(jpg_camera, prompt_face, max_tokens=60, temp=0.1)
        try:
            mf = re.search(r"\{[^{}]*\}", raw_face or "")
            if mf:
                df = json.loads(mf.group(0))
                if df.get("confuso_ou_frustrado"):
                    res["precisa_ajuda"] = True
                    res["motivo"] = df.get("expressao", "expressão de dúvida/frustração")
                    res["oferta_texto"] = "Percebi que você parece com alguma dúvida ou dificuldade. Quer uma sugestão ou que eu assuma isso para você?"
                    res["tarefa"] = "ajudar o usuário com a tarefa atual na tela"
                    return res
        except Exception:
            pass

    return res


