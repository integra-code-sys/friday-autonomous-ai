package dev.integra.friday;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.nio.FloatBuffer;
import java.nio.LongBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

/** A MESMA voz da Friday do PC (Supertonic 3, voz F5) rodando no celular: 4 modelos ONNX (duração, texto, estimador de
 *  vetores por fluxo, vocoder) no ONNX Runtime. Port de supertonic/core.py. Modelos em files/supertonic/{onnx,voice_styles}. */
final class SuperVoz {
    private final OrtEnvironment env = OrtEnvironment.getEnvironment();
    private final OrtSession dp, enc, est, voc;
    private final int[] indexer;
    private final float[] styleTtl, styleDp;
    private final long[] dimTtl, dimDp;
    private final int sr, baseChunk, ccf, ldim;
    private final Random rnd = new Random();

    static boolean existe(File base) { return new File(base, "onnx/vocoder.onnx").exists(); }

    SuperVoz(File base, String voz, boolean xnn) throws Exception {
        OrtSession.SessionOptions o = new OrtSession.SessionOptions();
        o.setIntraOpNumThreads(4);
        o.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
        if (xnn) try { java.util.Map<String, String> x = new HashMap<>(); x.put("intra_op_num_threads", "4"); o.addXnnpack(x); }
                 catch (Exception e) { android.util.Log.w("friday-voz", "XNNPACK indisponível: " + e); }
        File on = new File(base, "onnx");
        dp = env.createSession(new File(on, "duration_predictor.onnx").getAbsolutePath(), o);
        enc = env.createSession(new File(on, "text_encoder.onnx").getAbsolutePath(), o);
        est = env.createSession(new File(on, "vector_estimator.onnx").getAbsolutePath(), o);
        voc = env.createSession(new File(on, "vocoder.onnx").getAbsolutePath(), o);
        JSONObject cfg = new JSONObject(ler(new File(on, "tts.json")));
        sr = cfg.getJSONObject("ae").getInt("sample_rate");
        baseChunk = cfg.getJSONObject("ae").getInt("base_chunk_size");
        ccf = cfg.getJSONObject("ttl").getInt("chunk_compress_factor");
        ldim = cfg.getJSONObject("ttl").getInt("latent_dim");
        JSONArray ix = new JSONArray(ler(new File(on, "unicode_indexer.json")));
        indexer = new int[ix.length()];
        for (int i = 0; i < indexer.length; i++) indexer[i] = ix.getInt(i);
        JSONObject st = new JSONObject(ler(new File(base, "voice_styles/" + voz + ".json")));
        dimTtl = dims(st.getJSONObject("style_ttl")); styleTtl = dados(st.getJSONObject("style_ttl"));
        dimDp = dims(st.getJSONObject("style_dp")); styleDp = dados(st.getJSONObject("style_dp"));
    }

    int taxa() { return sr; }

    private static String ler(File f) throws Exception { return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8); }
    private static long[] dims(JSONObject o) throws Exception {
        JSONArray d = o.getJSONArray("dims"); long[] r = new long[d.length()];
        for (int i = 0; i < r.length; i++) r[i] = d.getLong(i);
        return r;
    }
    private static float[] dados(JSONObject o) throws Exception {
        List<Float> l = new ArrayList<>();
        achatar(o.get("data"), l);
        float[] r = new float[l.size()];
        for (int i = 0; i < r.length; i++) r[i] = l.get(i);
        return r;
    }
    private static void achatar(Object x, List<Float> l) throws Exception {
        if (x instanceof JSONArray) { JSONArray a = (JSONArray) x; for (int i = 0; i < a.length(); i++) achatar(a.get(i), l); }
        else l.add(((Number) x).floatValue());
    }

    // ------------------------------------------------------------------ texto (igual ao UnicodeProcessor do Supertonic)
    private static final Pattern EMOJI = Pattern.compile("[\\x{1F000}-\\x{1FAFF}\\x{2600}-\\x{27BF}]+");
    private String preparar(String t) {
        t = Normalizer.normalize(t, Normalizer.Form.NFKD);
        t = EMOJI.matcher(t).replaceAll("");
        t = t.replace('–', '-').replace('—', '-').replace('_', ' ').replace('“', '"').replace('”', '"').replace('‘', '\'')
             .replace('’', '\'').replace('´', '\'').replace('`', '\'').replace('[', ' ').replace(']', ' ').replace('|', ' ')
             .replace('/', ' ').replace('#', ' ').replace('*', ' ');
        t = t.replaceAll(" ([,.!?;:'])", "$1").replaceAll("\\s+", " ").trim();
        if (!t.matches("(?s).*[.!?;:,'\")\\]}…]$")) t += ".";
        return "<pt>" + t + "</pt>";
    }

    /** sintetiza um trecho (<= ~300 caracteres) -> PCM float mono */
    float[] sintetizar(String texto, float velocidade, int passos) throws Exception {
        long t0 = System.nanoTime();
        try { return sintetizar0(texto, velocidade, passos); }
        finally { android.util.Log.i("friday-voz", "trecho " + texto.length() + " chars sintetizado em " + (System.nanoTime() - t0) / 1000000 + " ms (" + passos + " passos)"); }
    }

    private float[] sintetizar0(String texto, float velocidade, int passos) throws Exception {
        String t = preparar(texto);
        int L = t.length();
        long[] ids = new long[L];
        for (int i = 0; i < L; i++) { int c = t.charAt(i); ids[i] = c < indexer.length && indexer[c] >= 0 ? indexer[c] : 0; }
        float[] tm = new float[L];
        java.util.Arrays.fill(tm, 1f);
        try (OnnxTensor tIds = OnnxTensor.createTensor(env, LongBuffer.wrap(ids), new long[]{1, L});
             OnnxTensor tMask = OnnxTensor.createTensor(env, FloatBuffer.wrap(tm), new long[]{1, 1, L});
             OnnxTensor sDp = OnnxTensor.createTensor(env, FloatBuffer.wrap(styleDp), dimDp);
             OnnxTensor sTtl = OnnxTensor.createTensor(env, FloatBuffer.wrap(styleTtl), dimTtl)) {
            Map<String, OnnxTensor> in = new HashMap<>();
            in.put("text_ids", tIds); in.put("style_dp", sDp); in.put("text_mask", tMask);
            float dur;
            try (OrtSession.Result r = dp.run(in)) { dur = ((float[]) r.get(0).getValue())[0] / velocidade; }
            in.clear(); in.put("text_ids", tIds); in.put("style_ttl", sTtl); in.put("text_mask", tMask);
            try (OrtSession.Result re = enc.run(in)) {
                OnnxTensor emb = (OnnxTensor) re.get(0);
                int wavLen = (int) (dur * sr), chunk = baseChunk * ccf, lat = (wavLen + chunk - 1) / chunk, ld = ldim * ccf;
                float[] xt = new float[ld * lat];
                for (int i = 0; i < xt.length; i++) xt[i] = (float) rnd.nextGaussian();
                float[] lm = new float[lat];
                java.util.Arrays.fill(lm, 1f);
                try (OnnxTensor tLm = OnnxTensor.createTensor(env, FloatBuffer.wrap(lm), new long[]{1, 1, lat});
                     OnnxTensor tTot = OnnxTensor.createTensor(env, FloatBuffer.wrap(new float[]{passos}), new long[]{1})) {
                    for (int s = 0; s < passos; s++) {
                        try (OnnxTensor tX = OnnxTensor.createTensor(env, FloatBuffer.wrap(xt), new long[]{1, ld, lat});
                             OnnxTensor tCur = OnnxTensor.createTensor(env, FloatBuffer.wrap(new float[]{s}), new long[]{1})) {
                            Map<String, OnnxTensor> ve = new HashMap<>();
                            ve.put("noisy_latent", tX); ve.put("text_emb", emb); ve.put("style_ttl", sTtl); ve.put("text_mask", tMask);
                            ve.put("latent_mask", tLm); ve.put("current_step", tCur); ve.put("total_step", tTot);
                            try (OrtSession.Result rv = est.run(ve)) {
                                FloatBuffer fb = ((OnnxTensor) rv.get(0)).getFloatBuffer();
                                fb.get(xt);
                            }
                        }
                    }
                }
                Map<String, OnnxTensor> vi = new HashMap<>();
                try (OnnxTensor tX = OnnxTensor.createTensor(env, FloatBuffer.wrap(xt), new long[]{1, ld, lat})) {
                    vi.put("latent", tX);
                    try (OrtSession.Result rw = voc.run(vi)) {
                        FloatBuffer fb = ((OnnxTensor) rw.get(0)).getFloatBuffer();
                        int n = Math.min(fb.remaining(), wavLen);
                        float[] w = new float[n];
                        fb.get(w, 0, n);
                        return w;
                    }
                }
            }
        }
    }

    /** frases de até ~280 caracteres (o modelo foi treinado com trechos curtos) */
    static List<String> trechos(String t) {
        List<String> r = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        for (String f : t.split("(?<=[.!?;])\\s+")) {
            if (cur.length() > 0 && cur.length() + f.length() > 280) { r.add(cur.toString()); cur.setLength(0); }
            cur.append(cur.length() > 0 ? " " : "").append(f);
        }
        if (cur.length() > 0) r.add(cur.toString());
        return r;
    }

    // ------------------------------------------------------------------ falar (toca cada trecho assim que fica pronto)
    private volatile AudioTrack trilha;
    private volatile boolean parar;

    // envelope (RMS a cada 20 ms) do que foi ESCRITO na trilha: as partículas leem no ponto exato da reprodução
    private static final int ENV = 4096;
    private static final float[] envFala = new float[ENV];
    private static volatile long envN;                   // blocos escritos desde o play()
    private static volatile int envHop = 882;
    private static volatile AudioTrack atual;

    private static void envelope(float[] w, int hop) {
        for (int i = 0; i + hop <= w.length; i += hop) {
            double s = 0;
            for (int k = i; k < i + hop; k++) s += w[k] * w[k];
            float rms = (float) Math.sqrt(s / hop);
            envFala[(int) (envN % ENV)] = rms < 1e-4f ? 0f : Math.max(0f, Math.min(1f, (float) (20 * Math.log10(rms) + 42) / 30f));
            envN++;
        }
    }

    /** 0..1: volume da fala que está saindo no alto-falante AGORA */
    static float nivel() {
        AudioTrack at = atual;
        if (at == null) return 0f;
        try {
            long b = at.getPlaybackHeadPosition() / Math.max(1, envHop);
            if (b >= envN || b < envN - ENV) return 0f;
            return envFala[(int) (b % ENV)];
        } catch (Exception e) { return 0f; }
    }

    static boolean tocando() { return atual != null; }

    void falar(String texto, float velocidade, int passos) throws Exception {
        parar = false;
        int min = AudioTrack.getMinBufferSize(sr, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_FLOAT);
        AudioTrack at = new AudioTrack.Builder()
            .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setAudioFormat(new AudioFormat.Builder().setSampleRate(sr).setEncoding(AudioFormat.ENCODING_PCM_FLOAT)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setBufferSizeInBytes(Math.max(min, sr * 4)).setTransferMode(AudioTrack.MODE_STREAM).build();
        trilha = at;
        envHop = sr / 50; envN = 0;
        atual = at;
        at.play();
        try {
            float[] silencio = new float[(int) (0.25f * sr)];
            for (String tr : trechos(FalaPt.normalizar(texto))) {
                if (parar) break;
                float[] w = sintetizar(tr, velocidade, passos);
                if (parar) break;
                envelope(w, envHop);                          // antes do write bloqueante (que só volta quando há espaço)
                at.write(w, 0, w.length, AudioTrack.WRITE_BLOCKING);
                envelope(silencio, envHop);
                at.write(silencio, 0, silencio.length, AudioTrack.WRITE_BLOCKING);
            }
            if (!parar) Thread.sleep(150);
        } finally {
            try { at.stop(); } catch (Exception ignored) {}
            if (atual == at) atual = null;
            at.release();
            trilha = null;
        }
    }

    void calar() {
        parar = true;
        AudioTrack at = trilha;
        if (at != null) try { at.pause(); at.flush(); } catch (Exception ignored) {}
    }
}
