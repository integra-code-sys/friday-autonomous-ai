"""OUVIDO: sons do ambiente (AudioSet, 527 classes) com o CED-mini int8 do sherpa_onnx (~10 ms por janela de 2 s, 1 thread).
Modelo em models/som/ced-mini (baixado 15/10/2026 de k2-fsa/sherpa-onnx releases "audio-tagging-models").
Roda em thread própria no microfone BRUTO (sem o supressor de ruído do PipeWire, que apaga batidas/alarmes), separado do STT."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "models", "som", "ced-mini")

# fundo/ruído que não interessa ao contexto
IGNORAR = {"Speech", "Silence", "Inside, small room", "Inside, large room or hall", "Static", "Noise", "Hum", "Mains hum",
           "White noise", "Pink noise", "Environmental noise", "Outside, urban or manmade", "Outside, rural or natural",
           "Male speech, man speaking", "Female speech, woman speaking", "Conversation", "Narration, monologue",
           "Speech synthesizer", "Sound effect", "Echo", "Reverberation", "Tick", "Clicking", "Computer keyboard", "Typing"}

# eventos que merecem aviso por voz (nome AudioSet -> fala)
NOTAVEIS = {
    "Doorbell": "a campainha", "Ding-dong": "a campainha", "Knock": "alguém batendo na porta",
    "Smoke detector, smoke alarm": "um alarme de fumaça", "Fire alarm": "um alarme de incêndio", "Alarm": "um alarme",
    "Siren": "uma sirene", "Glass": "vidro", "Shatter": "algo quebrando", "Screaming": "um grito", "Gunshot, gunfire": "um tiro",
    "Explosion": "uma explosão", "Baby cry, infant cry": "um bebê chorando", "Telephone bell ringing": "um telefone tocando",
    "Ringtone": "um celular tocando", "Alarm clock": "um despertador", "Crash": "uma batida forte",
}


class Ouvido:
    def __init__(self, threads=1):
        import sherpa_onnx
        cfg = sherpa_onnx.AudioTaggingConfig(
            model=sherpa_onnx.AudioTaggingModelConfig(ced=os.path.join(DIR, "model.int8.onnx"), num_threads=threads, provider="cpu"),
            labels=os.path.join(DIR, "class_labels_indices.csv"), top_k=5)
        self.at = sherpa_onnx.AudioTagging(cfg)

    def classificar(self, x16k, minimo=0.30, ignorar_fala=False):
        """x16k: float32 mono 16 kHz -> [(nome, prob, fala_pt|None)] relevantes, mais prováveis primeiro.
        ignorar_fala: a Friday está falando/tocando (o mic bruto a ouve): descarta voz e música."""
        s = self.at.create_stream()
        s.accept_waveform(16000, x16k)
        out = []
        for e in self.at.compute(s):
            if e.prob < minimo or e.name in IGNORAR:
                continue
            if ignorar_fala and (e.name.startswith(("Music", "Singing")) or "speech" in e.name.lower()):
                continue
            nota = NOTAVEIS.get(e.name)
            if nota and e.prob < 0.45:                  # aviso por voz só com mais certeza
                nota = None
            out.append((e.name, float(e.prob), nota))
        return out
