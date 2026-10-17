#!/usr/bin/env python3
"""Servidor de voz da F.R.I.D.A.Y.: Kyutai Pocket TTS (modelo português, CPU) com streaming.

Roda no .venv-tts (torch CPU), separado do daemon: se travar, o daemon cai na voz Piper.
Socket unix $XDG_RUNTIME_DIR/friday-tts.sock, uma fala por conexão:
  cliente -> {"texto": "...", "voz": "jane", "temp": 0.6}\n
  servidor -> {"ok": true, "sr": 24000}\n  seguido do PCM s16le mono em pedaços (~80 ms cada) até fechar.
Configuração (opcional) em memory/voz.json: {"tts_voz": "jane", "tts_temp": 0.6, "tts_threads": 4}.
"""
import json, os, socket, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "friday-tts.sock")


def cfg():
    try:
        return json.load(open(os.path.join(ROOT, "memory", "voz.json")))
    except Exception:
        return {}


def main():
    import fcntl
    trava = open(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "friday-tts.lock"), "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)      # uma instância só (run.sh e o daemon podem tentar subir juntos)
    except OSError:
        print("tts: já existe uma instância", flush=True); return
    import numpy as np, torch
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import fala_pt
    except Exception:
        fala_pt = None
    from pocket_tts import TTSModel
    from pocket_tts.utils.utils import get_predefined_voice
    c = cfg()
    torch.set_num_threads(int(c.get("tts_threads", 4)))
    temp = float(c.get("tts_temp", 0.6))
    t0 = time.time()
    model = TTSModel.load_model(language="portuguese", temp=temp)
    estados = {}

    def estado(voz):
        if voz not in estados:
            try:
                estados[voz] = model.get_state_for_audio_prompt(get_predefined_voice("portuguese", voz))
            except Exception:
                estados[voz] = model.get_state_for_audio_prompt(get_predefined_voice("portuguese", "jane"))
        return estados[voz]

    voz_init = "jane" if c.get("tts_voz") in ("dii", "piper") else c.get("tts_voz", "jane")
    estado(voz_init)
    list(model.generate_audio_stream(estado(voz_init), "Oi."))          # aquece (1ª fala sem atraso)
    print(f"tts pronto em {time.time() - t0:.1f}s ({SOCK})", flush=True)
    lock = threading.Lock()                 # o gerador não é thread-safe: uma fala por vez (rápido: ~4x tempo real)

    def _chunk_text(t, max_words=25):
        import re
        sentences = [s.strip() for s in re.split(r"(?<=[.!?;:\n])\s+", t) if s.strip()]
        final_chunks = []
        for s in sentences:
            words = s.split()
            if len(words) <= max_words:
                final_chunks.append(s)
            else:
                sub = [x.strip() for x in re.split(r"(?<=[,])\s+", s) if x.strip()]
                cur = []
                for item in sub:
                    if len(" ".join(cur).split()) + len(item.split()) <= max_words:
                        cur.append(item)
                    else:
                        if cur:
                            final_chunks.append(", ".join(cur))
                        cur = [item]
                if cur:
                    final_chunks.append(", ".join(cur))
        return final_chunks or [t]

    def atender(conn):
        try:
            f = conn.makefile("rb")
            req = json.loads(f.readline() or b"{}")
            texto = str(req.get("texto", "")).strip()
            if fala_pt is not None:
                texto = fala_pt.normalizar(texto)               # números/símbolos por extenso (o modelo não lê algarismos)
            if not texto:
                conn.sendall(b'{"ok": false}\n'); return
            voz = str(req.get("voz") or cfg().get("tts_voz", "jane"))
            with lock:
                st = estado(voz)
                conn.sendall((json.dumps({"ok": True, "sr": model.sample_rate}) + "\n").encode())
                parar = threading.Event()
                try:
                    for chunk in _chunk_text(texto):
                        if parar.is_set():
                            break
                        for ch in model.generate_audio_stream(st, chunk, stop=parar):
                            a = ch.squeeze().numpy()
                            conn.sendall((np.clip(a, -1, 1) * 32767).astype("<i2").tobytes())
                except (BrokenPipeError, ConnectionResetError):
                    parar.set()                      # "pare": interrompe a geração na hora (libera a vez da próxima fala)
        except (BrokenPipeError, ConnectionResetError):
            pass                            # "pare": o daemon fechou no meio
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
    if len(sys.argv) > 1 and sys.argv[1] == "falar":            # teste: tts_pocket.py falar "texto" > saida.raw
        s = socket.socket(socket.AF_UNIX); s.connect(SOCK)
        s.sendall((json.dumps({"texto": " ".join(sys.argv[2:])}) + "\n").encode())
        f = s.makefile("rb"); print(f.readline().decode().strip(), file=sys.stderr)
        sys.stdout.buffer.write(f.read())
    else:
        main()
