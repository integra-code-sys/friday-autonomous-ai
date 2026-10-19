#!/usr/bin/env python3
"""Servidor de voz da F.R.I.D.A.Y.: Kitsune-TTS (VITS2-Slim PT-BR, ultra-leve, CPU fast_cpu).

Protocolo idêntico ao tts_supertonic.py e tts_pocket.py:
  Socket $XDG_RUNTIME_DIR/friday-tts.sock
  Cliente -> {"texto": "...", "voz": "frieren"}\n
  Servidor -> {"ok": true, "sr": 22050}\n seguido de PCM s16le mono streaming.

Personas disponíveis:
  - frieren: calma, serena, assistente polida
  - violet: formal, disciplinada, executiva
  - emilia: suave, aveludada, doce
  - zerotwo: enérgica, expressiva
  - hiro: masculina jovem
"""
import json, os, re, socket, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "friday-tts.sock")
CKPT = os.path.join(ROOT, "stage", "Kitsune-TTS", "model", "latest_model_fp16.pth")


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
        print("tts kitsune: já existe uma instância rodando", flush=True)
        return

    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import fala_pt
    except Exception:
        fala_pt = None

    from kitsune.api import KitsuneSynthesizer

    c = cfg()
    t0 = time.time()
    synth = KitsuneSynthesizer(checkpoint=CKPT, fast_cpu=True)
    sr = 22050

    voz_padrao = c.get("kitsune_voz") or c.get("tts_voz") or "frieren"
    if voz_padrao not in ("frieren", "violet", "emilia", "zerotwo", "hiro"):
        voz_padrao = "frieren"

    # Aquece o modelo (1ª geração rápida)
    synth.synthesize("Oi.", speaker=voz_padrao)
    print(f"tts kitsune pronto em {time.time() - t0:.1f}s, sr {sr} ({SOCK})", flush=True)
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

            voz = str(req.get("voz") or cfg().get("kitsune_voz") or voz_padrao).lower()
            if voz not in ("frieren", "violet", "emilia", "zerotwo", "hiro"):
                voz = voz_padrao

            with lock:
                conn.sendall((json.dumps({"ok": True, "sr": sr}) + "\n").encode())
                pausa = np.zeros(int(sr * 0.10), dtype="<i2").tobytes()
                for fr in frases(texto):
                    a = synth.synthesize(fr, speaker=voz)
                    pcm = (np.clip(a, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                    conn.sendall(pcm + pausa)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print("tts kitsune erro:", e, flush=True)
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
