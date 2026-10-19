package dev.integra.friday;

import android.app.WallpaperManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Canvas;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.hardware.display.DisplayManager;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.service.wallpaper.WallpaperService;
import android.util.Log;
import android.view.Choreographer;
import android.view.Display;
import android.view.Surface;
import android.view.SurfaceHolder;
import java.util.Locale;

/** Papel de parede ao vivo da F.R.I.D.A.Y. (processo próprio :papel, longe do LLM). Motor: Choreographer (vsync) limitado a 30 fps (20 na economia
 *  de bateria), canvas de hardware com queda permanente para software, paralaxe pelo sensor de gravidade e atalhos por toque na área vazia da
 *  tela inicial (COMMAND_TAP). Tudo para quando invisível. O desenho fica em PapelCena (a rota /papel_png usa a mesma cena). */
public class Papel extends WallpaperService {
    static final String TAG = PapelCena.TAG;
    @Override public Engine onCreateEngine() { return new Motor(); }

    class Motor extends Engine implements Choreographer.FrameCallback, SensorEventListener {
        private PapelCena cena; private Choreographer coreo; private SensorManager sm; private Sensor sensor; private PowerManager pm;
        private boolean visivel, superficie, hw = true, agendado, eco, deitado, sensorLigado;
        private long ultQuadro, ultToque, ultLog, ultEco, somaNs, ultErro; private int quadros, nulos, rot;
        private boolean hwOk;                                                             // o canvas de hardware já funcionou nesta superfície?
        private final float[] g = new float[3]; private float bx, by; private boolean gIni;

        @Override public void onCreate(SurfaceHolder s) {
            super.onCreate(s);
            try {
                cena = new PapelCena(Papel.this, false); coreo = Choreographer.getInstance();
                sm = (SensorManager) getSystemService(Context.SENSOR_SERVICE);
                if (sm != null) { sensor = sm.getDefaultSensor(Sensor.TYPE_GRAVITY); if (sensor == null) sensor = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER); }
                pm = (PowerManager) getSystemService(Context.POWER_SERVICE); eco = pm != null && pm.isPowerSaveMode(); cena.economia(eco);
                setOffsetNotificationsEnabled(true);
            } catch (Throwable e) { Log.e(TAG, "onCreate", e); }
        }

        @Override public void onDestroy() {
            try { pausar(); if (cena != null) cena.liberar(); cena = null; } catch (Throwable e) { Log.e(TAG, "onDestroy", e); }
            super.onDestroy();
        }

        @Override public void onVisibilityChanged(boolean v) {
            try { visivel = v; if (v) retomar(); else pausar(); } catch (Throwable e) { Log.e(TAG, "visibilidade", e); }
        }

        @Override public void onSurfaceCreated(SurfaceHolder s) { super.onSurfaceCreated(s); superficie = true; hwOk = false; nulos = 0; }

        @Override public void onSurfaceChanged(SurfaceHolder s, int formato, int w, int h) {
            super.onSurfaceChanged(s, formato, w, h);
            try {
                superficie = true; deitado = w > h;
                try { DisplayManager dm = (DisplayManager) getSystemService(Context.DISPLAY_SERVICE); Display d = dm == null ? null : dm.getDisplay(Display.DEFAULT_DISPLAY); rot = d == null ? 0 : d.getRotation(); }
                catch (Throwable e) { rot = deitado ? Surface.ROTATION_90 : Surface.ROTATION_0; }        // rotação real: 270 não inverte a paralaxe
                if (cena != null) { cena.tamanho(w, h); desenhar(System.nanoTime()); } if (visivel) agendar();
            } catch (Throwable e) { Log.e(TAG, "onSurfaceChanged", e); }
        }

        @Override public void onSurfaceRedrawNeeded(SurfaceHolder s) {
            super.onSurfaceRedrawNeeded(s);
            try { if (cena != null && superficie) desenhar(System.nanoTime()); } catch (Throwable e) { Log.e(TAG, "redraw", e); }
        }

        @Override public void onSurfaceDestroyed(SurfaceHolder s) {
            try { superficie = false; if (coreo != null) coreo.removeFrameCallback(this); agendado = false; } catch (Throwable e) { Log.e(TAG, "onSurfaceDestroyed", e); }
            super.onSurfaceDestroyed(s);
        }

        @Override public void onOffsetsChanged(float xOff, float yOff, float xPasso, float yPasso, int xPx, int yPx) {
            try { if (cena != null) cena.deslocamento(xOff); } catch (Throwable e) { Log.e(TAG, "offsets", e); }
        }

        @Override public Bundle onCommand(String acao, int x, int y, int z, Bundle extras, boolean resultado) {
            try {
                if (cena == null || !WallpaperManager.COMMAND_TAP.equals(acao)) return null;
                long agora = SystemClock.uptimeMillis(); if (agora - ultToque < 500) return null; ultToque = agora;   // anti-repetição
                cena.toque(x, y); int i = cena.alvoEm(x, y);
                if (i >= 0) { vibrar(); abrir(PapelCena.ATALHOS[i][1]); }
            } catch (Throwable e) { Log.e(TAG, "toque", e); }
            return null;
        }

        // ---------------------------------------------------------------- ciclo
        private void retomar() {
            if (cena == null) return;
            if (sm != null && sensor != null && !sensorLigado) { sensorLigado = sm.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI); gIni = false; }
            if (pm != null) { boolean e = pm.isPowerSaveMode(); if (e != eco) { eco = e; cena.economia(e); } }
            cena.ativo(true); ultLog = System.nanoTime(); quadros = 0; somaNs = 0; agendar();
        }

        private void pausar() {
            if (coreo != null) coreo.removeFrameCallback(this); agendado = false;
            if (sm != null && sensorLigado) { sm.unregisterListener(this); sensorLigado = false; }
            if (cena != null) cena.ativo(false);
        }

        private void agendar() { if (!agendado && coreo != null) { agendado = true; coreo.postFrameCallback(this); } }
        /** próximo vsync só perto da hora do quadro (em 90/120 Hz não acorda a cada vsync à toa) */
        private void agendar(long alvoNs) {
            if (agendado || coreo == null) return; agendado = true;
            long ms = (alvoNs - 6_000_000L - System.nanoTime()) / 1_000_000L;
            if (ms > 0) coreo.postFrameCallbackDelayed(this, Math.min(ms, 60)); else coreo.postFrameCallback(this);
        }

        @Override public void doFrame(long t) {
            agendado = false;
            try {
                if (!visivel || !superficie || cena == null) return;
                long intervalo = eco ? 50_000_000L : 33_333_333L;              // 30 fps (20 na economia), sincronizado ao vsync
                if (t - ultQuadro < intervalo - 4_000_000L) { agendar(ultQuadro + intervalo); return; }
                ultQuadro = t; agendar(t + intervalo); desenhar(t);            // agenda antes: uma exceção abaixo não congela o papel
                if (t - ultEco > 3_000_000_000L) { ultEco = t; boolean e = pm != null && pm.isPowerSaveMode(); if (e != eco) { eco = e; cena.economia(e); } }
                if (t - ultLog >= 10_000_000_000L) {
                    Log.d(TAG, String.format(Locale.US, "media %.2f ms/quadro, fps %.1f, hw=%b", quadros > 0 ? somaNs / 1e6 / quadros : 0.0, quadros * 1e9 / (t - ultLog), hw));
                    ultLog = t; quadros = 0; somaNs = 0;
                }
            } catch (Throwable e) { Log.e(TAG, "quadro", e); }
        }

        /** o SurfaceHolder do WallpaperService engole a exceção do lock e devolve null (dormindo até 100 ms): a queda para software é por contagem
         *  de nulls com a superfície válida, e só antes do 1º sucesso (depois de ligada ao EGL a superfície não aceita mais lockCanvas) */
        private void desenhar(long t) {
            SurfaceHolder s = getSurfaceHolder(); Canvas cv = null; long t0 = System.nanoTime(); int sc = -1;
            try {
                if (hw) {
                    try { cv = s.lockHardwareCanvas(); } catch (Throwable e) { cv = null; Log.w(TAG, "lockHardwareCanvas: " + e); }
                    if (cv != null) { hwOk = true; nulos = 0; }
                    else if (!hwOk && ++nulos >= 3) { Surface sf = s.getSurface(); if (sf != null && sf.isValid()) { hw = false; Log.w(TAG, "sem canvas de hardware, usando software"); } }
                }
                if (!hw && cv == null) cv = s.lockCanvas();
                if (cv == null) return;
                sc = cv.save(); cena.desenhar(cv, t);
            } catch (Throwable e) { if (t0 - ultErro > 5_000_000_000L) { ultErro = t0; Log.e(TAG, "desenhar", e); } }   // sem enxurrada de log a 30 fps
            finally {
                if (cv != null) { try { if (sc >= 0) cv.restoreToCount(sc); } catch (Throwable ignored) {}      // save/restore equilibrado mesmo com exceção no meio
                    try { s.unlockCanvasAndPost(cv); } catch (Throwable e) { Log.e(TAG, "post", e); } }
            }
            if (cv != null) { somaNs += System.nanoTime() - t0; quadros++; }
        }

        // ---------------------------------------------------------------- sensor (paralaxe)
        @Override public void onSensorChanged(SensorEvent e) {
            try {
                if (cena == null || e.values == null || e.values.length < 3) return;
                for (int i = 0; i < 3; i++) if (Float.isNaN(e.values[i]) || Float.isInfinite(e.values[i])) return;   // um NaN envenenaria o filtro para sempre
                if (!gIni) { System.arraycopy(e.values, 0, g, 0, 3); bx = g[0]; by = g[1]; gIni = true; }
                for (int i = 0; i < 3; i++) g[i] += (e.values[i] - g[i]) * 0.15f;              // passa-baixa
                bx += (g[0] - bx) * 0.006f; by += (g[1] - by) * 0.006f;                       // posição neutra se adapta devagar ao jeito de segurar
                float x = -(g[0] - bx) / 3.5f, y = (g[1] - by) / 3.5f, k = x;
                if (rot == Surface.ROTATION_90) { x = y; y = -k; }                            // eixos do sensor -> eixos da tela pela rotação real
                else if (rot == Surface.ROTATION_270) { x = -y; y = k; }
                else if (rot == Surface.ROTATION_180) { x = -x; y = -y; }
                cena.inclinacao(x, y);
            } catch (Throwable ex) { Log.e(TAG, "sensor", ex); }
        }
        @Override public void onAccuracyChanged(Sensor s, int a) {}

        // ---------------------------------------------------------------- atalhos
        private void vibrar() {
            try {
                Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE); if (v == null || !v.hasVibrator()) return;
                if (Build.VERSION.SDK_INT >= 29) v.vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK));
                else v.vibrate(VibrationEffect.createOneShot(16, VibrationEffect.DEFAULT_AMPLITUDE));
            } catch (Throwable ignored) {}
        }

        private void abrir(String alvo) {
            Intent i = new Intent(Papel.this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            if ("assistente".equals(alvo)) i.putExtra("assistente", true); else i.putExtra("aba", alvo);
            try { startActivity(i); } catch (Throwable e) { Log.e(TAG, "abrir " + alvo, e); }
        }
    }
}
