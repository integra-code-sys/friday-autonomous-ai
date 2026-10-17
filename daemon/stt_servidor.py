#!/usr/bin/env python3
"""Servidor de STT da F.R.I.D.A.Y. (Whisper fora do daemon).

Dentro do daemon o Whisper medium levava ~5,9 s por frase (as threads Python de câmera/pose/voz disputam o GIL com as
partes Python do faster-whisper); num processo próprio, preso aos núcleos P, leva ~3,5 s. Atende o microfone do PC e o
celular (/api/stt). Mesmo modelo/threads de memory/voz.json (whisper_model, stt_threads).

Protocolo (socket $XDG_RUNTIME_DIR/friday-stt.sock, uma fala por conexão):
  -> linha JSON {"n": bytes do áudio float32, "kw": {parâmetros do WhisperModel.transcribe}} + áudio float32 16 kHz mono
  <- linha JSON {"segs": [{"text", "avg_logprob", "no_speech_prob", "compression_ratio"}], "ms": int}
"""
import json, os, socket, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "friday-stt.sock")
KW_OK = {"language", "vad_filter", "vad_parameters", "beam_size", "condition_on_previous_text", "temperature", "initial_prompt",
         "no_speech_threshold", "log_prob_threshold", "compression_ratio_threshold", "without_timestamps"}


def cfg():
    try:
        return json.load(open(os.path.join(ROOT, "memory", "voz.json")))
    except Exception:
        return {}


def main():
    try:                                                   # núcleos P (0-11 no i5-13450HX); E-cores atrasam o passo sincronizado do CT2
        os.sched_setaffinity(0, [c for c in range(12) if c < os.cpu_count()])
    except Exception:
        pass
    import numpy as np
    from faster_whisper import WhisperModel
    nome = os.environ.get("FRIDAY_WHISPER_MODEL") or cfg().get("whisper_model", "medium")
    th = int(cfg().get("stt_threads", 6))
    t0 = time.time()
    m = WhisperModel(nome, device="cpu", compute_type="int8", download_root=os.path.join(ROOT, "models", "whisper"), cpu_threads=th)
    m.transcribe(np.zeros(16000, dtype="float32"), language="pt", beam_size=1)          # aquece
    print(f"stt whisper {nome} pronto em {time.time() - t0:.1f}s ({th} threads, núcleos P) em {SOCK}", flush=True)
    trava = threading.Lock()                               # uma transcrição por vez (todas as threads do CT2 nela)

    def atender(conn):
        with conn:
            f = conn.makefile("rb")
            try:
                req = json.loads(f.readline() or b"{}")
                n = int(req.get("n", 0))
                dados = f.read(n) if n > 0 else b""
                a = np.frombuffer(dados[: len(dados) // 4 * 4], dtype="<f4")
                kw = {k: v for k, v in (req.get("kw") or {}).items() if k in KW_OK}
                kw.setdefault("language", "pt")
                t1 = time.time()
                with trava:
                    segs = [{"text": s.text, "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob,
                             "compression_ratio": getattr(s, "compression_ratio", 0.0)} for s in m.transcribe(a, **kw)[0]] if len(a) else []
                conn.sendall((json.dumps({"segs": segs, "ms": int((time.time() - t1) * 1000)}, ensure_ascii=False) + "\n").encode())
            except Exception as e:
                try:
                    conn.sendall((json.dumps({"erro": repr(e)[:200]}) + "\n").encode())
                except Exception:
                    pass

    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX); srv.bind(SOCK); os.chmod(SOCK, 0o600); srv.listen(8)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=atender, args=(c,), daemon=True).start()


class Remoto:
    """mesma interface do WhisperModel.transcribe para o daemon: devolve (segmentos, None)."""
    def transcribe(self, audio, **kw):
        import numpy as np
        from types import SimpleNamespace
        a = np.asarray(audio, dtype="<f4").tobytes()
        s = socket.socket(socket.AF_UNIX); s.settimeout(60); s.connect(SOCK)
        with s:
            s.sendall((json.dumps({"n": len(a), "kw": {k: v for k, v in kw.items() if k in KW_OK}}, ensure_ascii=False) + "\n").encode() + a)
            r = json.loads(s.makefile("rb").readline() or b"{}")
        if "erro" in r:
            raise RuntimeError("stt servidor: " + r["erro"])
        return [SimpleNamespace(**x) for x in r.get("segs", [])], None


def disponivel():
    try:
        s = socket.socket(socket.AF_UNIX); s.settimeout(0.5); s.connect(SOCK); s.close()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
