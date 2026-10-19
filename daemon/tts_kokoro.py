#!/usr/bin/env python3
"""Servidor de voz da F.R.I.D.A.Y.: Kokoro v1.0 ONNX (82M params, 24kHz, voz comercial adulta e humana).

Protocolo idêntico ao tts_kitsune.py e tts_supertonic.py:
  Socket $XDG_RUNTIME_DIR/friday-tts.sock
  Cliente -> {"texto": "...", "voz": "executiva"}\n
  Servidor -> {"ok": true, "sr": 24000}\n seguido de PCM s16le mono streaming.

Personas disponíveis:
  - executiva: blend Dora (65%) + Bella (35%) - tom executivo, formal e maduro (sem sotaque estrangeiro)
  - calorosa:  blend Dora (60%) + Heart (40%) - tom aveludado, empático e humano
  - dora:      Dora pura (PT-BR nativo comercial)
  - bella:     Bella (calma, corporativa)
  - sarah:     Sarah (articulada, tom de apresentadora)
  - heart:     Heart (internacional aveludada)
"""
import json, os, re, socket, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "friday-tts.sock")
MODEL_PATH = os.path.join(ROOT, "models", "kokoro", "kokoro-v1.0.int8.onnx")
VOICES_PATH = os.path.join(ROOT, "models", "kokoro", "voices-v1.0.bin")


def cfg():
    try:
        return json.load(open(os.path.join(ROOT, "memory", "voz.json")))
    except Exception:
        return {}


def frases(t):
    return [s.strip() for s in re.split(r"(?<=[.!?;\n])\s+", t) if s.strip()] or [t]


def main():
    import fcntl
    trava = open(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "friday-tts.lock"), "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("tts kokoro: já existe uma instância rodando", flush=True)
        return

    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import fala_pt
    except Exception:
        fala_pt = None

    from kokoro_onnx import Kokoro

    c = cfg()
    t0 = time.time()
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    sr = 24000

    # Pré-carrega e computa blends de alto padrão para uso comercial
    v_dora = kokoro.get_voice_style("pf_dora")
    v_bella = kokoro.get_voice_style("af_bella")
    v_heart = kokoro.get_voice_style("af_heart")
    v_sarah = kokoro.get_voice_style("af_sarah")

    estilos = {
        "executiva": (v_dora * 0.65 + v_bella * 0.35),
        "calorosa": (v_dora * 0.60 + v_heart * 0.40),
        "dora": v_dora,
        "bella": v_bella,
        "heart": v_heart,
        "sarah": v_sarah,
    }

    voz_padrao = c.get("kokoro_voz") or c.get("tts_voz") or "executiva"
    if voz_padrao not in estilos:
        voz_padrao = "executiva"

    # Aquecimento inicial
    kokoro.create("Oi.", voice=estilos[voz_padrao], lang="pt-br")
    print(f"tts kokoro pronto em {time.time() - t0:.1f}s, sr {sr} ({SOCK})", flush=True)
    lock = threading.Lock()

    def atender(conn):
        try:
            f = conn.makefile("rb")
            req = json.loads(f.readline() or b"{}")
            texto = str(req.get("texto", "")).strip()
            if fala_pt is not None:
                texto = fala_pt.normalizar(texto)
            if not texto:
                conn.sendall(b'{"ok": false}\n')
                return

            nome_v = str(req.get("voz") or cfg().get("kokoro_voz") or voz_padrao).lower()
            v_style = estilos.get(nome_v, estilos[voz_padrao])
            vel = float(cfg().get("kokoro_vel", 1.05))

            with lock:
                conn.sendall((json.dumps({"ok": True, "sr": sr}) + "\n").encode())
                pausa = np.zeros(int(sr * 0.10), dtype="<i2").tobytes()
                for fr in frases(texto):
                    samples, _ = kokoro.create(fr, voice=v_style, lang="pt-br", speed=vel)
                    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                    conn.sendall(pcm + pausa)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print("tts kokoro erro:", e, flush=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass

    srv = socket.socket(socket.AF_UNIX)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o600)
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=atender, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "falar":
        s = socket.socket(socket.AF_UNIX)
        s.connect(SOCK)
        s.sendall((json.dumps({"texto": " ".join(sys.argv[2:])}) + "\n").encode())
        f = s.makefile("rb")
        print(f.readline().decode().strip(), file=sys.stderr)
        sys.stdout.buffer.write(f.read())
    else:
        main()
