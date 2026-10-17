"""Compatibilidade multiplataforma Linux e Windows para a F.R.I.D.A.Y. (Projeto Prometheus).
Fornece abstrações uniformes para:
- Diretórios de runtime, temporários e dados
- IPC (Sockets Unix no Linux; TCP 127.0.0.1:8791 / AF_UNIX no Windows)
- Captura de tela rápida (grim no Wayland; mss / ImageGrab / BitBlt no Windows)
- Informações de janela em foco (niri no Wayland; Win32 API no Windows)
- Automação de cursor e teclado com curvas de Bézier (ydotool no Linux; SendInput no Windows)
- Captura de microfone 16kHz mono (parecord no Linux; sounddevice / WASAPI no Windows)
- Métricas de sistema (uptime, disco, rede, processos)
- Câmeras locais (V4L2 no Linux; DirectShow no Windows)
"""
import array
import ctypes
import json
import math
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time

IS_WINDOWS = sys.platform == "win32" or os.name == "nt"

# ----------------------------------------------------------------- Diretórios e Caminhos
def get_temp_dir():
    """Retorna diretório temporário apropriado para o SO."""
    return os.environ.get("TEMP", os.environ.get("TMP", tempfile.gettempdir()))


def get_runtime_dir():
    """Retorna diretório de runtime da Friday."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
        d = os.path.join(base, "Friday")
    else:
        d = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid() if hasattr(os, 'getuid') else 1000}")
    os.makedirs(d, exist_ok=True)
    return d


def get_painel_path():
    """Caminho do arquivo de painel compartilhado."""
    if IS_WINDOWS:
        return os.path.join(get_runtime_dir(), "friday-painel.json")
    return "/tmp/friday-painel.json"


# ----------------------------------------------------------------- IPC (Socket / Porta)
IPC_TCP_HOST = "127.0.0.1"
IPC_TCP_PORT = 8791


def get_ipc_address():
    """Retorna endereço IPC adequado: caminho do socket unix no Linux, ou (host, port) no Windows."""
    if IS_WINDOWS:
        # Se o Windows suportar AF_UNIX e o arquivo existir, usa; senão usa TCP localhost
        sock_path = os.path.join(get_runtime_dir(), "prometheus.sock")
        if hasattr(socket, "AF_UNIX") and os.path.exists(sock_path):
            return sock_path
        return (IPC_TCP_HOST, IPC_TCP_PORT)
    return os.path.join(get_runtime_dir(), "prometheus.sock")


def connect_ipc():
    """Conecta ao daemon local da Friday via socket (AF_UNIX ou TCP)."""
    addr = get_ipc_address()
    if isinstance(addr, tuple):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(addr)
        return s
    else:
        s = socket.socket(socket.AF_UNIX)
        s.connect(addr)
        return s


async def start_ipc_server(loop, client_connected_cb):
    """Inicia o servidor IPC no loop asyncio (Unix socket no Linux, TCP ou Unix no Windows)."""
    import asyncio
    addr = get_ipc_address()
    if isinstance(addr, tuple):
        host, port = addr
        srv = await asyncio.start_server(client_connected_cb, host, port)
        return srv
    else:
        try:
            if os.path.exists(addr):
                os.remove(addr)
        except OSError:
            pass
        srv = await asyncio.start_unix_server(client_connected_cb, path=addr)
        return srv


# ----------------------------------------------------------------- Janela em Foco
def janela_em_foco():
    """Retorna dicionário com dados da janela em foco:
    {"id": ..., "app_id": ..., "titulo": ..., "rect": [x, y, w, h], "pid": ...}"""
    if not IS_WINDOWS:
        try:
            w = json.loads(subprocess.run(["niri", "msg", "-j", "focused-window"],
                                           capture_output=True, text=True, timeout=3).stdout or "null")
            if w:
                return {
                    "id": str(w.get("id")),
                    "app_id": str(w.get("app_id") or ""),
                    "titulo": str(w.get("title") or ""),
                    "pid": w.get("pid"),
                    "rect": [0, 0, 1920, 1080]
                }
        except Exception:
            pass
        return {"id": "", "app_id": "", "titulo": "", "rect": [0, 0, 1920, 1080], "pid": None}

    # Implementação Nativa Windows via Win32 API (ctypes)
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"id": "", "app_id": "", "titulo": "", "rect": [0, 0, 1920, 1080], "pid": None}

        # Título
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        titulo = buf.value

        # PID
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # Nome do processo (app_id)
        app_id = ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if hproc:
            try:
                mod_buf = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_ulong(1024)
                if hasattr(kernel32, "QueryFullProcessImageNameW"):
                    if kernel32.QueryFullProcessImageNameW(hproc, 0, mod_buf, ctypes.byref(size)):
                        app_id = os.path.basename(mod_buf.value)
            finally:
                kernel32.CloseHandle(hproc)

        # Rect [x, y, w, h]
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        rect_struct = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect_struct))
        w = max(0, rect_struct.right - rect_struct.left)
        h = max(0, rect_struct.bottom - rect_struct.top)
        rect = [rect_struct.left, rect_struct.top, w, h]

        return {
            "id": str(hwnd),
            "app_id": app_id or "desconhecido",
            "titulo": titulo,
            "rect": rect,
            "pid": pid.value
        }
    except Exception as e:
        return {"id": "", "app_id": "", "titulo": "", "rect": [0, 0, 1920, 1080], "pid": None, "erro": str(e)}


# ----------------------------------------------------------------- Captura de Tela
def capturar_tela(rect=None):
    """Captura a tela inteira ou rect [x, y, w, h] -> array BGR do OpenCV (numpy) ou None."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    if not IS_WINDOWS:
        try:
            if rect:
                x, y, w, h = rect
                cmd = ["grim", "-g", f"{x},{y} {w}x{h}", "-s", "1", "-t", "ppm", "-"]
            else:
                cmd = ["grim", "-s", "1", "-t", "ppm", "-"]
            raw = subprocess.run(cmd, capture_output=True, timeout=5).stdout
            if raw:
                return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            pass

    # Windows ou fallback Linux
    # 1. Tentar via mss (alta performance)
    try:
        import mss
        with mss.mss() as sct:
            if rect:
                x, y, w, h = rect
                mon = {"top": int(y), "left": int(x), "width": int(w), "height": int(h)}
                img = np.array(sct.grab(mon))
            else:
                img = np.array(sct.grab(sct.monitors[1]))
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    except Exception:
        pass

    # 2. Tentar via PIL / Pillow ImageGrab
    try:
        from PIL import ImageGrab
        bbox = (rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]) if rect else None
        im = ImageGrab.grab(bbox=bbox)
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    except Exception:
        pass

    # 3. Windows Nativo BitBlt via ctypes (sem dependências externas)
    if IS_WINDOWS:
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

            if rect:
                x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
            else:
                x, y = 0, 0
                w = user32.GetSystemMetrics(0)
                h = user32.GetSystemMetrics(1)

            hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
            old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)
            SRCCOPY = 0x00CC0020
            gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', ctypes.c_uint32),
                    ('biWidth', ctypes.c_int32),
                    ('biHeight', ctypes.c_int32),
                    ('biPlanes', ctypes.c_uint16),
                    ('biBitCount', ctypes.c_uint16),
                    ('biCompression', ctypes.c_uint32),
                    ('biSizeImage', ctypes.c_uint32),
                    ('biXPelsPerMeter', ctypes.c_int32),
                    ('biYPelsPerMeter', ctypes.c_int32),
                    ('biClrUsed', ctypes.c_uint32),
                    ('biClrImportant', ctypes.c_uint32)
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h  # top-down
            bmi.biPlanes = 1
            bmi.biBitCount = 24
            bmi.biCompression = 0

            buf = ctypes.create_string_buffer(w * h * 3)
            gdi32.GetDIBits(hdc_mem, hbitmap, 0, h, buf, ctypes.byref(bmi), 0)

            # Limpeza handles GDI
            gdi32.SelectObject(hdc_mem, old_bmp)
            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)

            img = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 3))
            return img
        except Exception:
            pass

    return None


# ----------------------------------------------------------------- Automação de Mouse e Teclado (Windows SendInput)
def obter_tamanho_tela():
    """Retorna (largura, altura) da tela principal."""
    if IS_WINDOWS:
        try:
            u = ctypes.windll.user32
            return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        except Exception:
            return 1920, 1080
    else:
        try:
            d = json.loads(subprocess.run(["niri", "msg", "-j", "outputs"],
                                           capture_output=True, text=True, timeout=2).stdout or "{}")
            o = next(iter(d.values()))["logical"]
            return o["width"], o["height"]
        except Exception:
            return 1920, 1080


def mouse_move(x, y, passos=15):
    """Move cursor até x, y de forma suave com curva humana."""
    if not IS_WINDOWS:
        return subprocess.run([os.path.join(os.path.dirname(__file__), "pc"), "move", str(x), str(y)],
                              capture_output=True).returncode == 0

    try:
        user32 = ctypes.windll.user32
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        x0, y0 = pt.x, pt.y

        # Interpolação suave
        for i in range(1, passos + 1):
            t = i / float(passos)
            # Curva suave ease-in-out
            s = 3 * t * t - 2 * t * t * t
            cx = int(x0 + (x - x0) * s)
            cy = int(y0 + (y - y0) * s)
            user32.SetCursorPos(cx, cy)
            time.sleep(0.008)
        user32.SetCursorPos(int(x), int(y))
        return True
    except Exception:
        return False


def mouse_click(botao="left", duplo=False):
    """Executa clique de mouse (left, right, middle)."""
    if not IS_WINDOWS:
        cmd = [os.path.join(os.path.dirname(__file__), "pc"), "click"]
        if duplo: cmd.append("double")
        elif botao: cmd.append(botao)
        return subprocess.run(cmd, capture_output=True).returncode == 0

    try:
        user32 = ctypes.windll.user32
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_MIDDLEDOWN = 0x0020
        MOUSEEVENTF_MIDDLEUP = 0x0040

        flags_down = MOUSEEVENTF_LEFTDOWN
        flags_up = MOUSEEVENTF_LEFTUP
        if botao == "right":
            flags_down, flags_up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif botao == "middle":
            flags_down, flags_up = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP

        rep = 2 if duplo else 1
        for _ in range(rep):
            user32.mouse_event(flags_down, 0, 0, 0, 0)
            time.sleep(0.05)
            user32.mouse_event(flags_up, 0, 0, 0, 0)
            if rep > 1:
                time.sleep(0.08)
        return True
    except Exception:
        return False


def mouse_scroll(delta):
    """Rola o scroll verticalmente (positivo sobe, negativo desce)."""
    if not IS_WINDOWS:
        return subprocess.run([os.path.join(os.path.dirname(__file__), "pc"), "scroll", str(delta)],
                              capture_output=True).returncode == 0
    try:
        MOUSEEVENTF_WHEEL = 0x0800
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(delta * 120), 0)
        return True
    except Exception:
        return False


def type_text(texto):
    """Digita texto na janela em foco."""
    if not IS_WINDOWS:
        return subprocess.run([os.path.join(os.path.dirname(__file__), "pc"), "type", texto],
                              capture_output=True).returncode == 0
    try:
        # Usa pyautogui ou ctypes SendInput com VK_PACKET (Unicode real)
        try:
            import pyautogui
            pyautogui.write(texto, interval=0.02)
            return True
        except ImportError:
            pass

        user32 = ctypes.windll.user32
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        for ch in texto:
            code = ord(ch)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
            time.sleep(0.015)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)
        return True
    except Exception:
        return False


def press_key(key_comb):
    """Pressiona atalho ou tecla especial (ex.: 'enter', 'ctrl+c', 'alt+tab')."""
    if not IS_WINDOWS:
        return subprocess.run([os.path.join(os.path.dirname(__file__), "pc"), "key", key_comb],
                              capture_output=True).returncode == 0
    try:
        import pyautogui
        partes = [p.strip().lower() for p in key_comb.split("+")]
        pyautogui.hotkey(*partes)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------- Captura de Áudio (Microfone VAD)
class WindowsAudioStream:
    """Emulador de stream s16le 16kHz mono para Windows com interface .read(n)."""
    def __init__(self, rate=16000, chunk=480):
        self.rate = rate
        self.chunk = chunk
        self.running = True
        self.queue = []
        import threading
        self.lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="WinAudioWorker")
        self._thread.start()

    def _worker(self):
        try:
            import sounddevice as sd
            def callback(indata, frames, time_info, status):
                if not self.running:
                    return
                # Converte float32 ou int16 para bytes int16 s16le
                if indata.dtype == "float32":
                    s16 = (indata[:, 0] * 32767).clip(-32768, 32767).astype("int16").tobytes()
                else:
                    s16 = indata[:, 0].tobytes()
                with self.lock:
                    self.queue.append(s16)
                    # Limita fila a ~2 segundos se ninguém estiver lendo
                    if len(self.queue) > 70:
                        self.queue.pop(0)

            with sd.InputStream(samplerate=self.rate, channels=1, dtype="int16",
                                blocksize=self.chunk, callback=callback):
                while self.running:
                    time.sleep(0.05)
        except Exception as e:
            # Fallback mudo se microfone não estiver disponível
            silence = b"\x00" * (self.chunk * 2)
            while self.running:
                with self.lock:
                    self.queue.append(silence)
                    if len(self.queue) > 70:
                        self.queue.pop(0)
                time.sleep(self.chunk / self.rate)

    def read(self, n_bytes):
        """Retorna exatamente n_bytes ou espera chegarem."""
        needed = n_bytes
        buf = bytearray()
        while self.running and len(buf) < needed:
            chunk = None
            with self.lock:
                if self.queue:
                    chunk = self.queue.pop(0)
            if chunk:
                buf.extend(chunk)
            else:
                time.sleep(0.005)
        return bytes(buf[:needed])

    def close(self):
        self.running = False


class WindowsAudioProcess:
    """Wrapper com atributo .stdout para compatibilidade 1:1 com subprocess.Popen."""
    def __init__(self, rate=16000, chunk=480):
        self.stdout = WindowsAudioStream(rate=rate, chunk=chunk)

    def terminate(self):
        self.stdout.close()

    def kill(self):
        self.stdout.close()


def criar_gravador_mic(rate=16000, chunk=480, dev=None):
    """Cria gravador de microfone apropriado para o SO atual."""
    if not IS_WINDOWS:
        cmd = ["parecord", "--raw", "--format=s16le", f"--rate={rate}", "--channels=1", "--latency-msec=30"]
        if dev:
            cmd.append(f"--device={dev}")
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    else:
        return WindowsAudioProcess(rate=rate, chunk=chunk)


# ----------------------------------------------------------------- Câmera Local
def abrir_camera(dev_idx=0):
    """Abre dispositivo de captura de câmera (cv2.VideoCapture) com backend adequado."""
    import cv2
    if IS_WINDOWS:
        # No Windows, CAP_DSHOW inicializa rapidamente sem travar
        cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(dev_idx)
        return cap
    else:
        try:
            cap = cv2.VideoCapture(dev_idx, cv2.CAP_V4L2)
            if cap.isOpened():
                return cap
        except Exception:
            pass
        return cv2.VideoCapture(dev_idx)


# ----------------------------------------------------------------- Métricas de Sistema
def obter_uptime_segundos():
    """Uptime do sistema em segundos."""
    if IS_WINDOWS:
        try:
            return int(ctypes.windll.kernel32.GetTickCount64() // 1000)
        except Exception:
            return 3600
    try:
        return int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        return 3600


def obter_uso_disco():
    """Porcentagem de uso do disco principal."""
    try:
        import shutil
        total, used, free = shutil.disk_usage(os.path.abspath(os.sep))
        p = int((used / total) * 100)
        return f"{p}%"
    except Exception:
        return "10%"


def obter_nome_rede():
    """Nome da rede / conexão ativa."""
    if IS_WINDOWS:
        try:
            return socket.gethostname()
        except Exception:
            return "Windows-LAN"
    try:
        out = subprocess.run("nmcli -t -f NAME,DEVICE connection show --active | head -1",
                             shell=True, capture_output=True, text=True, timeout=2).stdout
        return out.strip().split(":")[0] if out else "LAN"
    except Exception:
        return "LAN"


def obter_processos(n=5):
    """Lista dos n processos consumindo mais CPU."""
    if not IS_WINDOWS:
        try:
            out = subprocess.run(f"ps -eo comm,%cpu,rss --sort=-%cpu --no-headers | head -{n}",
                                 shell=True, capture_output=True, text=True, timeout=3).stdout
            return [l.split() for l in out.splitlines() if len(l.split()) == 3]
        except Exception:
            return []
    # Windows
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(['name', 'cpu_percent', 'memory_info']):
            try:
                name = p.info['name'] or 'proc'
                cpu = p.info['cpu_percent'] or 0.0
                rss = (p.info['memory_info'].rss if p.info['memory_info'] else 0) // 1024
                procs.append([name, str(cpu), str(rss)])
            except Exception:
                pass
        procs.sort(key=lambda x: float(x[1]), reverse=True)
        return procs[:n]
    except Exception:
        return [["System", "1.0", "10240"]]
