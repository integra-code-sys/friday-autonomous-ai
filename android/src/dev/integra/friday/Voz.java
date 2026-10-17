package dev.integra.friday;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;

import java.util.ArrayList;
import java.util.Locale;

/** Ouvido e voz da Friday LOCAL com o que o Android já tem offline: reconhecimento de fala pt-BR e TTS do Google. */
final class Voz {
    interface Ouviu { void texto(String t, boolean parcial); void erro(String e); }

    private static Voz inst;
    private final Context c;
    private final Handler main = new Handler(Looper.getMainLooper());
    private SpeechRecognizer rec;
    private TextToSpeech tts;
    private boolean ttsOk;
    private volatile SuperVoz superVoz;                 // a mesma voz do PC (Supertonic F5), se os modelos estiverem no celular
    private final java.util.concurrent.ExecutorService fala = java.util.concurrent.Executors.newSingleThreadExecutor();

    private Voz(Context c) {
        this.c = c.getApplicationContext();
        tts = new TextToSpeech(this.c, s -> {
            ttsOk = s == TextToSpeech.SUCCESS;
            if (ttsOk) { tts.setLanguage(new Locale("pt", "BR")); tts.setSpeechRate(1.05f); }
        });
    }

    static synchronized Voz get(Context c) {
        if (inst == null) inst = new Voz(c);
        return inst;
    }

    java.io.File pastaSuper() { return new java.io.File(c.getExternalFilesDir(null), "supertonic"); }

    private SuperVoz superVoz() {
        if (superVoz == null && SuperVoz.existe(pastaSuper())) {
            try {
                String voz = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getString("voz", "F5");
                android.content.SharedPreferences pf = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE);
                superVoz = new SuperVoz(pastaSuper(), voz, pf.getBoolean("voz_xnn", false));
            } catch (Throwable e) { android.util.Log.w("friday-voz", "Supertonic indisponível: " + e); }
        }
        return superVoz;
    }

    void recarregar() { calar(); superVoz = null; preparar(); }

    /** carrega a voz em 2º plano (a 1ª fala sai sem esperar os modelos) */
    void preparar() { fala.submit(this::superVoz); }

    private static final java.util.concurrent.atomic.AtomicInteger pendentes = new java.util.concurrent.atomic.AtomicInteger();

    /** true do pedido de fala até o fim do áudio (inclui a síntese) */
    static boolean falandoAgora() {
        Voz v = inst;
        return pendentes.get() > 0 || SuperVoz.tocando() || (v != null && v.tts != null && v.ttsOk && v.tts.isSpeaking());
    }

    /** 0..1: volume da voz dela agora (Supertonic = envelope real; TTS do Google = ondulação sintética) */
    static float nivel() {
        if (SuperVoz.tocando()) return SuperVoz.nivel();
        Voz v = inst;
        if (v != null && v.tts != null && v.ttsOk && v.tts.isSpeaking())
            return 0.35f + 0.3f * (float) Math.abs(Math.sin(System.nanoTime() / 9e7));
        return 0f;
    }

    void falar(String t) {
        if (t == null || t.isEmpty()) return;
        String limpo = t.replaceAll("[*#_`]", "");
        calar();
        pendentes.incrementAndGet();
        fala.submit(() -> { try { falar0(limpo); } finally { pendentes.decrementAndGet(); } });
    }

    private void falar0(String limpo) {
        {
            SuperVoz sv = superVoz();
            if (sv != null) {
                try { long t0 = System.currentTimeMillis(); sv.falar(limpo, 1.0f, c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getInt("voz_passos", 5));
                      android.util.Log.i("friday-voz", "Supertonic: " + limpo.length() + " chars em " + (System.currentTimeMillis() - t0) + " ms");
                      return; }
                catch (Throwable e) { android.util.Log.w("friday-voz", "Supertonic falhou: " + e); }
            }
            main.post(() -> { if (ttsOk) tts.speak(FalaPt.normalizar(limpo), TextToSpeech.QUEUE_FLUSH, null, "friday"); });
        }
    }

    void calar() {
        SuperVoz sv = superVoz;
        if (sv != null) sv.calar();
        main.post(() -> { if (tts != null) tts.stop(); });
    }

    void ouvir(Ouviu cb) {
        main.post(() -> {
            calar();
            if (rec != null) rec.destroy();
            // on-device do sistema: sendo ELA o assistente padrão, o reconhecedor "padrão" vira o do assistente (stub)
            if (android.os.Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(c))
                rec = SpeechRecognizer.createOnDeviceSpeechRecognizer(c);
            else if (SpeechRecognizer.isRecognitionAvailable(c)) rec = SpeechRecognizer.createSpeechRecognizer(c, googleRec());
            else { cb.erro("reconhecimento de voz indisponível"); return; }
            rec.setRecognitionListener(new RecognitionListener() {
                @Override public void onResults(Bundle b) {
                    ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    cb.texto(r == null || r.isEmpty() ? "" : r.get(0), false);
                }
                @Override public void onPartialResults(Bundle b) {
                    ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    if (r != null && !r.isEmpty()) cb.texto(r.get(0), true);
                }
                @Override public void onError(int e) {
                    cb.erro(e == SpeechRecognizer.ERROR_NO_MATCH || e == SpeechRecognizer.ERROR_SPEECH_TIMEOUT ? "não ouvi nada" : "erro de reconhecimento " + e);
                }
                @Override public void onReadyForSpeech(Bundle b) {}
                @Override public void onBeginningOfSpeech() {}
                @Override public void onRmsChanged(float v) { Ouvido.nivelMic = Math.max(0f, Math.min(1f, (v + 2f) / 12f)); }
                @Override public void onBufferReceived(byte[] b) {}
                @Override public void onEndOfSpeech() { Ouvido.nivelMic = 0f; }
                @Override public void onEvent(int t, Bundle b) {}
            });
            Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "pt-BR")
                .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1200L);
            rec.startListening(i);
        });
    }

    static volatile String ultimoMotor = "";

    /** resultado de UMA escuta de comando */
    interface Escuta {
        void texto(String t);                              // texto final, já corrigido e sem lixo
        void parcial(String t);
        void recusada(float score);                        // não pareceu a voz do dono ("fui eu" resolve)
        void erro(String e);
    }

    private long ultAprendeu;

    /** ESCUTA DE COMANDO (botão lateral e app):
     *  Sempre passa pelo Ouvido (WeSpeaker ResNet34) quando o perfil do dono está ativo:
     *  bloqueia qualquer outra voz antes da transcrição (Whisper no PC ou reconhecedor on-device do Android). */
    void ouvirComando(Ouvido ouvido, Escuta cb) {
        calar();
        new Thread(() -> {
            float lim = ouvido.limiar();
            if (ouvido.pronto() && ouvido.temPerfil()) {
                ouvido.ouvirUmaFala(7000, 900, 15000, new Ouvido.Fim() {
                    @Override public void fala(short[] pcm, float sc, boolean dono) {
                        float dur = pcm.length / (float) Ouvido.SR;
                        boolean filtrar = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getBoolean("so_dono", true);
                        android.util.Log.i("friday-ouvido", String.format(Locale.ROOT, "fala %.1fs score %.2f (limiar %.2f) %s", dur, sc, lim, dono ? "DONO" : "outra voz"));
                        if (filtrar && !dono) {
                            Ouvido.ultimaRecusada = pcm; Ouvido.ultimoScore = sc;
                            Aprende.logVoz(c, sc, lim, false, dur, "-", "", false);
                            cb.recusada(sc);
                            return;
                        }
                        if (sc >= Math.max(0.66f, lim + 0.14f) && dur >= 1.6f && System.currentTimeMillis() - ultAprendeu > 60000) {
                            ultAprendeu = System.currentTimeMillis();   // o perfil se adapta ao microfone do celular (só com folga alta)
                            new Thread(() -> ouvido.aprender(pcm, false)).start();
                        }
                        cb.parcial("entendendo…");
                        transcrever(pcm, new Ouviu() {
                            @Override public void texto(String t, boolean parcial) {
                                boolean lx = Aprende.lixo(t);
                                Aprende.logVoz(c, sc, lim, true, dur, ultimoMotor, t, lx);
                                if (lx) cb.erro(t == null || t.trim().isEmpty() ? "não entendi, fala de novo?" : "não entendi (\"" + t.trim() + "\"), fala de novo?");
                                else cb.texto(t.trim());
                            }
                            @Override public void erro(String e) { cb.erro(e); }
                        });
                    }
                    @Override public void erro(String e) { cb.erro(e); }
                });
                return;
            }
            ouvir(new Ouviu() {
                @Override public void texto(String t, boolean parcial) {
                    if (parcial) { cb.parcial(t); return; }
                    String tc = Aprende.corrigir(c, t);
                    boolean lx = Aprende.lixo(tc);
                    ultimoMotor = "android-mic";
                    Aprende.logVoz(c, -2f, lim, true, 0f, ultimoMotor, tc, lx);
                    if (lx) cb.erro("não entendi, fala de novo?"); else cb.texto(tc.trim());
                }
                @Override public void erro(String e) { cb.erro(e); }
            });
        }, "friday-escuta").start();
    }

    /** STT da fala já captada: Whisper do PC (o mesmo modelo/vocabulário de lá, bem mais preciso) quando o PC está no ar;
     *  sem PC (ou falha de rede) usa o reconhecedor do Android. O texto sai com as correções aprendidas (Aprende.corrigir). */
    void transcrever(short[] pcm, Ouviu cb) {
        Ouviu fim = new Ouviu() {
            @Override public void texto(String t, boolean parcial) { cb.texto(Aprende.corrigir(c, t), parcial); }
            @Override public void erro(String e) { cb.erro(e); }
        };
        new Thread(() -> {
            if (Link.pcOnline(c)) {
                String[] r = noPc(pcm);
                if (r != null) { ultimoMotor = "whisper-pc"; fim.texto(r[0], false); return; }
            }
            ultimoMotor = "android";
            reconhecerAudio(pcm, fim);
        }, "friday-stt").start();
    }

    void transcreverNoPc(short[] pcm, Ouviu cb) {
        new Thread(() -> {
            String[] r = noPc(pcm);
            ultimoMotor = "whisper-pc";
            if (r == null) cb.erro("PC não respondeu"); else cb.texto(r[0], false);
        }, "friday-stt-pc").start();
    }

    /** -> {texto} ou null se o PC não respondeu (rede/erro) */
    private String[] noPc(short[] pcm) {
        try {
            java.net.HttpURLConnection h = (java.net.HttpURLConnection) new java.net.URL("http://" + Link.host(c) + "/api/stt").openConnection();
            h.setConnectTimeout(2500); h.setReadTimeout(15000);
            h.setRequestMethod("POST"); h.setDoOutput(true);
            h.setRequestProperty("X-Token", Link.token(c));
            h.setRequestProperty("Content-Type", "application/octet-stream");
            byte[] b = new byte[pcm.length * 2];
            for (int k = 0; k < pcm.length; k++) { b[2 * k] = (byte) pcm[k]; b[2 * k + 1] = (byte) (pcm[k] >> 8); }
            h.setFixedLengthStreamingMode(b.length);
            try (java.io.OutputStream o = h.getOutputStream()) { o.write(b); }
            if (h.getResponseCode() != 200) { h.disconnect(); return null; }
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            try (java.io.InputStream in = h.getInputStream()) { byte[] x = new byte[4096]; int n; while ((n = in.read(x)) > 0) bo.write(x, 0, n); }
            h.disconnect();
            org.json.JSONObject j = new org.json.JSONObject(bo.toString("UTF-8"));
            if (j.has("erro") && j.optString("texto").isEmpty() && !"áudio curto".equals(j.optString("erro"))) return null;
            return new String[]{j.optString("texto")};
        } catch (Exception e) {
            android.util.Log.w("friday-voz", "STT no PC falhou: " + e);
            return null;
        }
    }

    /** reconhece um áudio JÁ captado e filtrado (só a voz do dono) — Android 13+ aceita a fonte de áudio do app */
    static volatile int variante = 1;                   // padrão: blocos em ritmo com pré/pós-silêncio para o VAD do Android

    void reconhecerAudio(short[] pcm, Ouviu cb) {
        final int v = variante;
        main.post(() -> {
            try {
                if (rec != null) rec.destroy();
                rec = v < 2 && SpeechRecognizer.isOnDeviceRecognitionAvailable(c) ? SpeechRecognizer.createOnDeviceSpeechRecognizer(c)
                    : SpeechRecognizer.createSpeechRecognizer(c, googleRec());
                android.os.ParcelFileDescriptor[] tubo = android.os.ParcelFileDescriptor.createPipe();
                final java.util.concurrent.CountDownLatch pronto = new java.util.concurrent.CountDownLatch(1);
                rec.setRecognitionListener(new RecognitionListener() {
                    @Override public void onResults(Bundle b) {
                        ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                        cb.texto(r == null || r.isEmpty() ? "" : r.get(0), false);
                    }
                    @Override public void onPartialResults(Bundle b) {}
                    @Override public void onError(int e) { cb.erro("reconhecimento falhou (" + e + ")"); }
                    @Override public void onReadyForSpeech(Bundle b) { pronto.countDown(); }
                    @Override public void onBeginningOfSpeech() {}
                    @Override public void onRmsChanged(float v) {}
                    @Override public void onBufferReceived(byte[] b) {}
                    @Override public void onEndOfSpeech() { Ouvido.nivelMic = 0f; }
                    @Override public void onEvent(int t, Bundle b) {}
                });
                Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "pt-BR")
                    .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
                    .putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, tubo[0])
                    .putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, 1)
                    .putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, android.media.AudioFormat.ENCODING_PCM_16BIT)
                    .putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, Ouvido.SR);
                rec.startListening(i);
                new Thread(() -> {
                    try (java.io.OutputStream o = new android.os.ParcelFileDescriptor.AutoCloseOutputStream(tubo[1])) {
                        pronto.await(220, java.util.concurrent.TimeUnit.MILLISECONDS);
                        int preBytes = (Ouvido.SR / 5) * 2;                         // 200 ms de silêncio inicial
                        int posBytes = (Ouvido.SR * 3 / 5) * 2;                     // 600 ms de silêncio final
                        byte[] b = new byte[preBytes + pcm.length * 2 + posBytes];
                        for (int k = 0; k < pcm.length; k++) {
                            b[preBytes + 2 * k] = (byte) pcm[k];
                            b[preBytes + 2 * k + 1] = (byte) (pcm[k] >> 8);
                        }
                        if (v % 2 == 1) {                                           // em ritmo: blocos de 40 ms
                            for (int k = 0; k < b.length; k += 1280) {
                                o.write(b, k, Math.min(1280, b.length - k));
                                o.flush();
                                Thread.sleep(12);
                            }
                        } else o.write(b);
                    } catch (Exception ignored) {}
                    try { tubo[0].close(); } catch (Exception ignored) {}
                }, "friday-audio-rec").start();
            } catch (Exception e) { cb.erro("reconhecimento: " + e.getMessage()); }
        });
    }

    /** serviço de reconhecimento do Google (não o nosso, que é só o exigido para ser assistente padrão) */
    private android.content.ComponentName googleRec() {
        for (android.content.pm.ResolveInfo ri : c.getPackageManager().queryIntentServices(
                new Intent(android.speech.RecognitionService.SERVICE_INTERFACE), 0)) {
            if (!ri.serviceInfo.packageName.equals(c.getPackageName()))
                return new android.content.ComponentName(ri.serviceInfo.packageName, ri.serviceInfo.name);
        }
        return null;
    }

    void pararDeOuvir() { main.post(() -> { if (rec != null) rec.stopListening(); }); }
}
