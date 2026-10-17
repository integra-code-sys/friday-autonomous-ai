"""Foco na voz do dono: impressão vocal (TitaNet-L, NVIDIA NeMo, ONNX via sherpa-onnx) + decisão de aceitar/ignorar cada fala.

- Perfil em memory/voz_dono.json (0600): só EMBEDDINGS (vetores de 192 números), nunca áudio. Nada sai do PC.
- score = cosseno entre a fala e o centróide do perfil. Limiar calibrado contra uma coorte de outras vozes
  (models/spk/coorte.npy: 20 falantes do FLEURS pt-BR + a voz dela + ruído/eco do quarto) no cadastro.
- Falas longas são analisadas em janelas de 1,5 s: trechos de outra voz (TV, outra pessoa, eco dela) são silenciados
  antes da transcrição; se quase nada for do dono, a fala inteira é ignorada.
Medição (13/10/2026, mic C270): dono 0,56–0,75 · outras pessoas ≤ 0,30 · ruído/eco ≤ 0,23 (margem +0,26; ResNet34 antigo: +0,06).
"""
import json, os, threading, time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELO = os.path.join(ROOT, "models", "spk", "nemo_en_titanet_large.onnx")
COORTE = os.path.join(ROOT, "models", "spk", "coorte.npy")
PERFIL = os.path.join(ROOT, "memory", "voz_dono.json")
LOG = "/tmp/friday-voz.log"
SR = 16000
MAX_AMOSTRAS = 60
LIMIAR_PADRAO = 0.40


class VozDono:
    def __init__(self, threads=2):
        import sherpa_onnx
        self.ex = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODELO, num_threads=threads))
        self.lock = threading.Lock()
        self.dados = {"amostras": [], "limiar": LIMIAR_PADRAO, "criado": time.time()}
        try:
            self.dados.update(json.load(open(PERFIL)))
        except Exception:
            pass
        self._centro = None
        self.coorte = np.load(COORTE) if os.path.exists(COORTE) else None

    # ---------------------------------------------------------------- embeddings
    def embed(self, audio):
        """áudio float32 16 kHz -> vetor unitário (ou None se curto demais)."""
        if audio is None or len(audio) < int(0.5 * SR):
            return None
        with self.lock:
            s = self.ex.create_stream(); s.accept_waveform(SR, np.ascontiguousarray(audio, dtype="float32")); s.input_finished()
            e = np.array(self.ex.compute(s), dtype="float32")
        n = np.linalg.norm(e)
        return e / n if n > 0 else None

    @property
    def pronto(self):
        return len(self.dados["amostras"]) >= 3

    @property
    def limiar(self):
        return float(self.dados.get("limiar", LIMIAR_PADRAO))

    def centro(self):
        if self._centro is None and self.dados["amostras"]:
            c = np.mean([np.array(a["e"], dtype="float32") for a in self.dados["amostras"]], 0)
            self._centro = c / np.linalg.norm(c)
        return self._centro

    def score(self, emb):
        c = self.centro()
        return float(emb @ c) if (c is not None and emb is not None) else 0.0

    # ---------------------------------------------------------------- perfil
    def adicionar(self, emb, fonte="uso", salvar=True, max_uso_frac=None):
        if emb is None:
            return
        am = self.dados["amostras"]
        am.append({"e": [round(float(x), 5) for x in emb], "fonte": fonte, "t": int(time.time())})
        cad = [a for a in am if a["fonte"] != "uso"]                    # amostras de uso entram num rodízio; as do cadastro ficam
        uso = [a for a in am if a["fonte"] == "uso"][-max(0, MAX_AMOSTRAS - len(cad)):]
        if max_uso_frac is not None:                                     # 'uso' no máximo essa fração do perfil (cad/(1-f) total)
            n = int(len(cad) * max_uso_frac / (1 - max_uso_frac)) if max_uso_frac < 1 else len(uso)
            uso = uso[-n:] if n > 0 else []
        self.dados["amostras"] = cad + uso
        self._centro = None
        if salvar:
            self.salvar()

    def salvar(self):
        tmp = PERFIL + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.dados, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, PERFIL)

    def calibrar(self):
        """limiar entre a voz do dono (leave-one-out) e a coorte de outras vozes. Devolve um resumo."""
        E = [np.array(a["e"], dtype="float32") for a in self.dados["amostras"]]
        if len(E) < 3:
            return {"ok": False, "motivo": "poucas amostras"}
        gen = []
        for i in range(len(E)):
            c = np.mean([E[j] for j in range(len(E)) if j != i], 0); c /= np.linalg.norm(c)
            gen.append(float(E[i] @ c))
        self._centro = None
        c = self.centro()
        imp = [float(x @ c) for x in self.coorte] if self.coorte is not None and len(self.coorte) else [0.25]
        g_lo = float(np.percentile(gen, 10)); i_hi = float(max(imp))
        # meio do caminho entre o pior impostor e as falas mais fracas do dono, sem passar de 0,55 nem descer de 0,30
        lim = float(np.clip((g_lo + i_hi) / 2, 0.30, 0.55))
        self.dados.update(limiar=round(lim, 3), calib={"dono_med": round(float(np.mean(gen)), 3), "dono_p10": round(g_lo, 3),
                                                       "outros_max": round(i_hi, 3), "n": len(E), "t": int(time.time())})
        self.salvar()
        return {"ok": True, "limiar": lim, "dono_med": float(np.mean(gen)), "dono_p10": g_lo, "outros_max": i_hi, "margem": g_lo - i_hi}

    def esquecer(self):
        self.dados = {"amostras": [], "limiar": LIMIAR_PADRAO, "criado": time.time()}
        self._centro = None
        self.salvar()

    # ---------------------------------------------------------------- decisão por fala
    def decidir(self, audio, dono_recente=False, estrito=False):
        """-> (aceitar, audio_filtrado, info). Sem perfil: aceita tudo (só registra).
        estrito ("só a voz do dono"): sem descontos; em fala longa misturada devolve SÓ os trechos com a voz dele."""
        dur = len(audio) / SR
        emb = self.embed(audio)
        sc = self.score(emb) if emb is not None else 0.0
        info = {"dur": round(dur, 2), "score": round(sc, 3), "limiar": self.limiar, "emb": emb}
        if not self.pronto:
            info["motivo"] = "sem perfil"
            return True, audio, info
        if estrito:
            return self._decidir_estrito(audio, dur, sc, info)
        lim = self.limiar if dur >= 1.0 else self.limiar - 0.06               # falas curtas dão embedding mais ruidoso
        if dono_recente:
            lim -= 0.05
        if dur >= 2.5:                                                        # fala longa: análise por janelas
            win, hop = int(1.5 * SR), int(0.75 * SR)
            marc = np.zeros(len(audio), dtype=bool); n_ok = n_tot = 0; scs = []
            for i in range(0, max(1, len(audio) - win + 1), hop):
                seg = audio[i:i + win]
                if float(np.sqrt((seg ** 2).mean())) < 0.01:                   # silêncio: não conta
                    continue
                s_ = self.score(self.embed(seg)); scs.append(round(s_, 2)); n_tot += 1
                if s_ >= lim - 0.08:
                    marc[i:i + win] = True; n_ok += 1
            info["janelas"] = scs
            if n_tot and n_ok / n_tot < 0.35 and sc < lim:
                info["motivo"] = "outra voz (janelas)"
                return False, audio, info
            if n_tot and n_ok < n_tot:                                       # silencia só os trechos de outra voz (com rampa)
                filt = audio.copy()
                ramp = np.convolve(marc.astype("float32"), np.ones(800) / 800, mode="same")
                filt *= np.clip(ramp, 0, 1)
                info["motivo"] = f"recortado ({n_tot - n_ok}/{n_tot} trechos de outra voz)"
                return True, filt, info
        if sc >= lim:
            info["motivo"] = "dono"
            return True, audio, info
        info["motivo"] = "outra voz"
        return False, audio, info


    def _decidir_estrito(self, audio, dur, sc, info):
        """16/10: amigos falando (call/sala) passavam pela faixa média só por conter "Sexta-feira", e trechos de 22 s
        misturados iam inteiros para o STT. Aqui: janela de 1,5 s precisa ter a voz do dono (>= limiar real; vizinhas
        >= limiar-0,03 entram junto) e o STT recebe só esses trechos colados (0,25 s de silêncio entre eles)."""
        lim = self.limiar
        if dur < 2.5:
            ok = sc >= (lim if dur >= 1.0 else lim - 0.03)                   # curta: embedding mais ruidoso, desconto pequeno
            info["motivo"] = "só dono: dono" if ok else "só dono: outra voz"
            return ok, audio, info
        win, hop = int(1.5 * SR), int(0.75 * SR)
        marc = np.zeros(len(audio), dtype=bool); scs = []; forte = False
        for i in range(0, max(1, len(audio) - win + 1), hop):
            fim = len(audio) if i + hop + win > len(audio) else i + win      # a última janela vai até o fim (sobra < 0,75 s)
            seg = audio[i:fim]
            if float(np.sqrt((seg ** 2).mean())) < 0.01:
                continue
            s_ = self.score(self.embed(seg)); scs.append(round(s_, 2))
            forte = forte or s_ >= lim
            if s_ >= lim - 0.03:
                marc[i:fim] = True
        info["janelas"] = scs
        if not forte and sc < lim:
            info["motivo"] = "só dono: nenhum trecho com a voz dele"
            return False, audio, info
        if marc.all() or not marc.any():
            info["motivo"] = "só dono: dono"
            return True, audio, info
        pad = int(0.15 * SR)
        idx = np.flatnonzero(np.diff(np.concatenate([[0], marc.astype(np.int8), [0]])))
        partes = []
        for a, b in zip(idx[0::2], idx[1::2]):
            partes.append(audio[max(0, a - pad):min(len(audio), b + pad)])
            partes.append(np.zeros(int(0.25 * SR), dtype=audio.dtype))
        filt = np.concatenate(partes[:-1])
        info["motivo"] = f"só dono: recortado {len(filt) / SR:.1f}s de {dur:.1f}s"
        return True, filt, info


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:
        pass
