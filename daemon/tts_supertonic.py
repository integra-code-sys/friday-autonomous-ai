#!/usr/bin/env python3
"""Servidor de voz da F.R.I.D.A.Y.: Supertonic 3 (Supertone, ONNX na CPU, voz feminina F1, lang "pt").

Mesmo protocolo do tts_pocket.py (o daemon não muda): socket $XDG_RUNTIME_DIR/friday-tts.sock, uma fala por conexão:
  cliente -> {"texto": "...", "voz": "F1"}\n
  servidor -> {"ok": true, "sr": 44100}\n  seguido do PCM s16le mono, uma frase por vez (streaming por frase), até fechar.
Roda no .venv-st. Config em memory/voz.json: {"tts_motor": "supertonic", "st_voz": "F1", "st_passos": 8, "st_vel": 1.0, "tts_threads": 6}.
"""
import json, os, re, socket, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "friday-tts.sock")


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
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)      # uma instância só (mesma trava do tts_pocket)
    except OSError:
        print("tts: já existe uma instância", flush=True); return
    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import fala_pt
    except Exception:
        fala_pt = None
    from supertonic import TTS
    c = cfg()
    t0 = time.time()
    n = int(c.get("tts_threads", 6))
    tts = TTS(auto_download=True, intra_op_num_threads=n, inter_op_num_threads=1)
    estilos = {}

    def estilo(v):
        if v not in estilos:
            try:
                estilos[v] = tts.get_voice_style(v)
            except Exception:
                estilos[v] = tts.get_voice_style("F1")
        return estilos[v]

    def gerar(texto, voz):
        c_ = cfg()
        wav, _ = tts.synthesize(texto, voice_style=estilo(voz), lang="pt", total_steps=int(c_.get("st_passos", 8)),
                                speed=float(c_.get("st_vel", 1.0)), silence_duration=0.15)
        return np.asarray(wav, dtype=np.float32).reshape(-1)

    sr = int(getattr(tts, "sample_rate", 44100))
    gerar("Oi.", c.get("st_voz", "F1"))                        # aquece (1ª fala sem atraso)
    print(f"tts supertonic pronto em {time.time() - t0:.1f}s, sr {sr} ({SOCK})", flush=True)
    lock = threading.Lock()                                     # uma fala por vez

    def atender(conn):
        try:
            f = conn.makefile("rb")
            req = json.loads(f.readline() or b"{}")
            texto = str(req.get("texto", "")).strip()
            if fala_pt is not None:
                texto = fala_pt.normalizar(texto)
            if not texto:
                conn.sendall(b'{"ok": false}\n'); return
            voz = str(req.get("voz") or cfg().get("st_voz", "F1"))
            if not re.fullmatch(r"[FM][1-5]", voz):
                voz = cfg().get("st_voz", "F1")
            with lock:
                conn.sendall((json.dumps({"ok": True, "sr": sr}) + "\n").encode())
                pausa = np.zeros(int(sr * 0.12), dtype="<i2").tobytes()
                for fr in frases(texto):                        # 1ª frase toca enquanto a próxima é gerada no servidor
                    a = gerar(fr, voz)
                    conn.sendall((np.clip(a, -1, 1) * 32767).astype("<i2").tobytes() + pausa)
        except (BrokenPipeError, ConnectionResetError):
            pass                                                # "pare": o daemon fechou no meio
        except Exception as e:
            print("tts erro:", e, flush=True)
        finally:
            try: conn.close()
            except Exception: pass

    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX); srv.bind(SOCK); os.chmod(SOCK, 0o600); srv.listen(8)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=atender, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "falar":            # teste: tts_supertonic.py falar "texto" > saida.raw
        s = socket.socket(socket.AF_UNIX); s.connect(SOCK)
        s.sendall((json.dumps({"texto": " ".join(sys.argv[2:])}) + "\n").encode())
        f = s.makefile("rb"); print(f.readline().decode().strip(), file=sys.stderr)
        sys.stdout.buffer.write(f.read())
    else:
        main()
