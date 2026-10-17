package dev.integra.friday;

import android.content.Context;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.media.audiofx.AcousticEchoCanceler;
import android.media.audiofx.AutomaticGainControl;
import android.media.audiofx.NoiseSuppressor;

import org.json.JSONArray;

import java.io.File;
import java.nio.FloatBuffer;
import java.util.Collections;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

/** Ouvido da Friday no celular: microfone com supressor de ruído/eco do aparelho, detector de fala e verificação de que é
 *  o DONO falando (WeSpeaker ResNet34, o mesmo modelo/fbank do PC em senses.SpeakerID). Só a voz dele segue para o
 *  reconhecimento; amigos, TV e ruído ficam de fora. Perfil em files/voz_dono.json (começa com as amostras do PC). */
final class Ouvido {
    interface Fim { void fala(short[] pcm, float score, boolean dono); void erro(String e); }

    static final int SR = 16000;
    private final Context c;
    private final OrtEnvironment env = OrtEnvironment.getEnvironment();
    private OrtSession spk;
    private float[][] perfil;                  // embeddings do dono (unitários)
    private volatile boolean ouvindo;
    private final float[] janela = new float[400], fftRe = new float[512], fftIm = new float[512];
    private float[][] mel;

    Ouvido(Context c) { this.c = c.getApplicationContext(); }

    File arqModelo() { return new File(c.getExternalFilesDir(null), "speaker_wespeaker_resnet34.onnx"); }
    File arqPerfil() { return new File(c.getExternalFilesDir(null), "voz_dono.json"); }
    boolean pronto() { return arqModelo().exists(); }
    boolean temPerfil() { carregarPerfil(); return perfil != null && perfil.length > 0; }

    // ------------------------------------------------------------------ captura com detector de fala
    /** grava UMA fala (começa ao detectar voz, termina após `silMs` de silêncio ou `maxMs`) e verifica o dono. */
    /** 0..1: volume da voz captada agora (as partículas da Friday pulsam com ele) */
    static volatile float nivelMic;
    static volatile short[] ultimaRecusada;               // "fui eu": a última fala recusada como outra voz
    static volatile float ultimoScore;
    private volatile Thread atual;

    void ouvirUmaFala(int esperaMs, int silMs, int maxMs, Fim fim) {
        Thread ant = atual;                                // UMA escuta por vez: duas abriam o microfone juntas (escuta em loop)
        if (ant != null && ant.isAlive()) {
            ouvindo = false;
            try { ant.join(800); } catch (InterruptedException ignored) {}
        }
        atual = new Thread(() -> {
            int min = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            AudioRecord ar;
            try {
                ar = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SR, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, Math.max(min, SR));
            } catch (SecurityException e) { fim.erro("sem permissão de microfone"); return; }
            NoiseSuppressor ns = NoiseSuppressor.isAvailable() ? NoiseSuppressor.create(ar.getAudioSessionId()) : null;
            AcousticEchoCanceler aec = AcousticEchoCanceler.isAvailable() ? AcousticEchoCanceler.create(ar.getAudioSessionId()) : null;
            AutomaticGainControl agc = AutomaticGainControl.isAvailable() ? AutomaticGainControl.create(ar.getAudioSessionId()) : null;
            if (ns != null) ns.setEnabled(true);
            if (aec != null) aec.setEnabled(true);
            if (agc != null) agc.setEnabled(true);
            ouvindo = true;
            short[] buf = new short[SR * maxMs / 1000 + SR];
            short[] blk = new short[320];                      // 20 ms
            int n = 0, silencio = 0, espera = 0, falaMs = 0;
            float piso = 300f;                                 // nível de ruído (adapta nos primeiros blocos)
            boolean falando = false;
            short[] pre = new short[SR * 3 / 10];              // 300 ms antes do início da fala
            int preN = 0;
            try {
                ar.startRecording();
                while (ouvindo) {
                    int r = ar.read(blk, 0, blk.length);
                    if (r <= 0) break;
                    double s = 0;
                    for (int i = 0; i < r; i++) s += blk[i] * (double) blk[i];
                    float rms = (float) Math.sqrt(s / r);
                    nivelMic = Math.max(0f, Math.min(1f, (float) (20 * Math.log10(Math.max(1f, rms) / Math.max(150f, piso * 1.4f))) / 26f));
                    if (!falando) {
                        piso = 0.95f * piso + 0.05f * Math.min(rms, piso * 2);
                        System.arraycopy(pre, r, pre, 0, pre.length - r);
                        System.arraycopy(blk, 0, pre, pre.length - r, r);
                        preN = Math.min(pre.length, preN + r);
                        if (rms > Math.max(piso * 3.2f, 450f)) {
                            falando = true;
                            System.arraycopy(pre, pre.length - preN, buf, 0, preN); n = preN;
                        } else if ((espera += 20) > esperaMs) break;
                        continue;
                    }
                    if (n + r < buf.length) { System.arraycopy(blk, 0, buf, n, r); n += r; }
                    falaMs += 20;
                    silencio = rms < Math.max(piso * 2.2f, 350f) ? silencio + 20 : 0;
                    if (silencio >= silMs || falaMs >= maxMs) break;
                }
            } catch (Exception e) {
                fim.erro("microfone: " + e.getMessage());
                return;
            } finally {
                ouvindo = false;
                nivelMic = 0f;
                try { ar.stop(); } catch (Exception ignored) {}
                ar.release();
                if (ns != null) ns.release();
                if (aec != null) aec.release();
                if (agc != null) agc.release();
            }
            if (!falando || n < SR * 32 / 100) { fim.erro("não ouvi nada"); return; }
            short[] pcm = java.util.Arrays.copyOf(buf, n);
            float sc = score(pcm);
            boolean semFiltro = !pronto() || !temPerfil();
            fim.fala(pcm, sc, semFiltro || sc >= limiar());
        }, "friday-ouvido");
        atual.start();
    }

    void parar() { ouvindo = false; }

    static final float LIMIAR_PADRAO = 0.54f;
    static final float LIMIAR_MIN = 0.48f;
    static final float LIMIAR_MAX = 0.72f;

    float limiar() {
        float v = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getFloat("voz_limiar", LIMIAR_PADRAO);
        if (v < LIMIAR_MIN) {
            v = LIMIAR_PADRAO;
            c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).edit().putFloat("voz_limiar", v).apply();
        }
        return Math.max(LIMIAR_MIN, Math.min(LIMIAR_MAX, v));
    }

    // ------------------------------------------------------------------ verificação do dono
    /** cosseno robusto com o perfil (70% centroide + 30% média das 3 melhores amostras); -1 = áudio inválido (bloqueia) */
    synchronized float score(short[] pcm) {
        try {
            if (!pronto() || !temPerfil()) return -2f;
            float[] e = embed(pcm);
            if (e == null) return -1f;
            float[] media = new float[e.length];
            float m1 = -1f, m2 = -1f, m3 = -1f;
            for (float[] p : perfil) {
                float cs = dot(e, p);
                if (cs > m1) { m3 = m2; m2 = m1; m1 = cs; }
                else if (cs > m2) { m3 = m2; m2 = cs; }
                else if (cs > m3) { m3 = cs; }
                for (int i = 0; i < e.length; i++) media[i] += p[i];
            }
            unit(media);
            float top3 = m3 > -0.9f ? (m1 + m2 + m3) / 3f : m2 > -0.9f ? (m1 + m2) / 2f : m1;
            return 0.70f * dot(e, media) + 0.30f * top3;
        } catch (Throwable t) {
            android.util.Log.w("friday-ouvido", "verificação falhou: " + t);
            return -1f;
        }
    }

    /** acrescenta a fala ao perfil do dono (somente se coerente com a voz do dono, evitando contaminação) */
    synchronized boolean aprender(short[] pcm) {
        return aprender(pcm, false);
    }

    synchronized boolean aprender(short[] pcm, boolean forcar) {
        try {
            float[] e = embed(pcm);
            if (e == null) return false;
            carregarPerfil();
            if (perfil != null && perfil.length >= 3) {
                float[] media = new float[e.length];
                for (float[] p : perfil) for (int i = 0; i < e.length; i++) media[i] += p[i];
                unit(media);
                float sim = dot(e, media);
                if (sim < (forcar ? 0.45f : 0.64f)) {
                    android.util.Log.w("friday-ouvido", "amostra rejeitada do perfil (sim=" + sim + ")");
                    return false;
                }
            }
            JSONArray a = new JSONArray();
            int ini = perfil == null ? 0 : Math.max(0, perfil.length - 39);   // guarda as 40 mais recentes
            if (perfil != null) for (int k = ini; k < perfil.length; k++) a.put(arr(perfil[k]));
            a.put(arr(e));
            java.nio.file.Files.write(arqPerfil().toPath(), a.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            perfil = null;
            carregarPerfil();
            return true;
        } catch (Throwable t) { return false; }
    }

    private static JSONArray arr(float[] v) throws Exception { JSONArray a = new JSONArray(); for (float x : v) a.put((double) x); return a; }

    private void carregarPerfil() {
        if (perfil != null) return;
        if (!arqPerfil().exists()) {
            try (java.io.InputStream in = c.getAssets().open("voz_dono.json")) {
                byte[] b = new byte[in.available()];
                int n = in.read(b);
                if (n > 0) java.nio.file.Files.write(arqPerfil().toPath(), java.util.Arrays.copyOf(b, n));
            } catch (Exception ignored) {}
        }
        if (!arqPerfil().exists()) return;
        try {
            JSONArray a = new JSONArray(new String(java.nio.file.Files.readAllBytes(arqPerfil().toPath()), java.nio.charset.StandardCharsets.UTF_8));
            java.util.List<float[]> brutos = new java.util.ArrayList<>();
            for (int i = 0; i < a.length(); i++) {
                JSONArray v = a.getJSONArray(i);
                float[] vec = new float[v.length()];
                for (int k = 0; k < v.length(); k++) vec[k] = (float) v.getDouble(k);
                unit(vec);
                brutos.add(vec);
            }
            if (brutos.size() >= 4) {
                int dim = brutos.get(0).length;
                float[] media = new float[dim];
                for (float[] v : brutos) for (int i = 0; i < dim; i++) media[i] += v[i];
                unit(media);
                java.util.List<float[]> limpos = new java.util.ArrayList<>();
                for (float[] v : brutos) if (dot(v, media) >= 0.50f) limpos.add(v);
                if (limpos.size() >= 3) brutos = limpos;
            }
            perfil = brutos.toArray(new float[0][]);
        } catch (Exception e) { perfil = null; }
    }

    int totalAmostras() { carregarPerfil(); return perfil == null ? 0 : perfil.length; }

    private float[] embed(short[] pcm) throws Exception {
        float[][] f = fbank(pcm);
        if (f.length < 30) return null;                   // < 0,3 s: curto demais
        if (f.length < 64) {                              // 0,3 s .. 0,64 s: repete quadros para o ResNet34 ter janela suficiente
            float[][] pad = new float[64][80];
            for (int t = 0; t < 64; t++) System.arraycopy(f[t % f.length], 0, pad[t], 0, 80);
            f = pad;
        }
        if (spk == null) {
            OrtSession.SessionOptions o = new OrtSession.SessionOptions();
            o.setIntraOpNumThreads(2);
            spk = env.createSession(arqModelo().getAbsolutePath(), o);
        }
        float[] flat = new float[f.length * 80];
        for (int t = 0; t < f.length; t++) System.arraycopy(f[t], 0, flat, t * 80, 80);
        try (OnnxTensor x = OnnxTensor.createTensor(env, FloatBuffer.wrap(flat), new long[]{1, f.length, 80});
             OrtSession.Result r = spk.run(Collections.singletonMap("feats", x))) {
            float[] e = ((float[][]) r.get(0).getValue())[0];
            unit(e);
            return e;
        }
    }

    // ------------------------------------------------------------------ fbank Kaldi (port exato de senses.SpeakerID.fbank)
    private float[][] fbank(short[] pcm) {
        if (mel == null) {
            for (int i = 0; i < 400; i++) janela[i] = (float) Math.pow(0.5 - 0.5 * Math.cos(2 * Math.PI * i / 399.0), 0.85);
            mel = new float[80][257];
            double lo = melf(20.0), hi = melf(8000.0);
            for (int m = 0; m < 80; m++) {
                double l = lo + (hi - lo) * m / 81.0, ce = lo + (hi - lo) * (m + 1) / 81.0, r = lo + (hi - lo) * (m + 2) / 81.0;
                for (int b = 0; b < 257; b++) {
                    double mb = melf(b * 16000.0 / 512.0);
                    mel[m][b] = (float) Math.max(0.0, Math.min((mb - l) / (ce - l), (r - mb) / (r - ce)));
                }
            }
        }
        int len = Math.max(pcm.length, 400), nfr = 1 + (len - 400) / 160;
        float[][] out = new float[nfr][80];
        float[] fr = new float[400];
        for (int t = 0; t < nfr; t++) {
            double soma = 0;
            for (int i = 0; i < 400; i++) { int k = t * 160 + i; fr[i] = k < pcm.length ? pcm[k] : 0f; soma += fr[i]; }
            float med = (float) (soma / 400);
            for (int i = 0; i < 400; i++) fr[i] -= med;
            for (int i = 399; i >= 1; i--) fr[i] = fr[i] - 0.97f * fr[i - 1];
            fr[0] = fr[0] * (1 - 0.97f);
            java.util.Arrays.fill(fftRe, 0f); java.util.Arrays.fill(fftIm, 0f);
            for (int i = 0; i < 400; i++) fftRe[i] = fr[i] * janela[i];
            fft(fftRe, fftIm);
            for (int m = 0; m < 80; m++) {
                double e = 0;
                for (int b = 0; b < 257; b++) if (mel[m][b] > 0) e += mel[m][b] * (fftRe[b] * (double) fftRe[b] + fftIm[b] * (double) fftIm[b]);
                out[t][m] = (float) Math.log(Math.max(e, 1.1920929e-07));
            }
        }
        for (int m = 0; m < 80; m++) {                   // CMN
            double s = 0; for (float[] o : out) s += o[m];
            float mu = (float) (s / nfr); for (float[] o : out) o[m] -= mu;
        }
        return out;
    }

    private static double melf(double f) { return 1127.0 * Math.log(1.0 + f / 700.0); }

    private static void fft(float[] re, float[] im) {
        int n = re.length;
        for (int i = 1, j = 0; i < n; i++) {
            int bit = n >> 1;
            for (; (j & bit) != 0; bit >>= 1) j ^= bit;
            j ^= bit;
            if (i < j) { float t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
        }
        for (int l = 2; l <= n; l <<= 1) {
            double ang = -2 * Math.PI / l;
            float wr = (float) Math.cos(ang), wi = (float) Math.sin(ang);
            for (int i = 0; i < n; i += l) {
                float cr = 1f, ci = 0f;
                for (int k = 0; k < l / 2; k++) {
                    int a = i + k, b = a + l / 2;
                    float tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
                    re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
                    float ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
                }
            }
        }
    }

    private static float dot(float[] a, float[] b) { float s = 0; for (int i = 0; i < a.length; i++) s += a[i] * b[i]; return s; }
    private static void unit(float[] v) { double s = 0; for (float x : v) s += x * x; float n = (float) Math.sqrt(Math.max(s, 1e-12)); for (int i = 0; i < v.length; i++) v[i] /= n; }
}
