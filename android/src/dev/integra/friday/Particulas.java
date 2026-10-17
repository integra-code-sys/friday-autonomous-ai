package dev.integra.friday;

import android.content.Context;
import android.graphics.BlendMode;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.view.View;

/** Núcleo de partículas da Friday (esfera de Fibonacci com brilho aditivo, núcleo, anéis de HUD e faíscas).
 *  Estados: 0 espera (respira) · 1 ouvindo (segue o microfone: Ouvido.nivelMic) · 2 pensando (redemoinho, contrai)
 *  · 3 falando (segue a voz DELA no ponto exato da reprodução: Voz.nivel()). Enquanto ela fala, vira 3 sozinho. */
final class Particulas extends View {
    private static final int N = 520, FAI = 48;
    private final float[] px = new float[N], py = new float[N], pz = new float[N], lat = new float[N], lon = new float[N];
    private final float[] fx = new float[FAI], fy = new float[FAI], fvx = new float[FAI], fvy = new float[FAI], fv = new float[FAI];
    private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG), halo = new Paint(Paint.ANTI_ALIAS_FLAG), anel = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF oval = new RectF();
    private final java.util.Random rnd = new java.util.Random(7);
    private volatile int estado;
    private float ang, raioSuave = 1f, lvl, lvlAnt, pico, cr = 54, cg = 214, cb = 255, giro;
    private final long t0 = System.nanoTime();

    Particulas(Context c) {
        super(c);
        double ouro = Math.PI * (3 - Math.sqrt(5));
        for (int i = 0; i < N; i++) {
            double y = 1 - (i / (double) (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = ouro * i;
            px[i] = (float) (Math.cos(th) * r); py[i] = (float) y; pz[i] = (float) (Math.sin(th) * r);
            lat[i] = (float) Math.asin(y); lon[i] = (float) (th % (2 * Math.PI));
        }
        anel.setStyle(Paint.Style.STROKE); anel.setStrokeCap(Paint.Cap.ROUND);
        if (android.os.Build.VERSION.SDK_INT >= 29) {        // pontos que se sobrepõem somam luz (brilho)
            p.setBlendMode(BlendMode.PLUS); halo.setBlendMode(BlendMode.PLUS); anel.setBlendMode(BlendMode.PLUS);
        }
        setLayerType(LAYER_TYPE_HARDWARE, null);
    }

    void estado(int e) { estado = e; }
    void nivel(float n) {}                                     // compat: o nível agora vem direto do microfone/voz

    private int cor(float a, float mr, float mg, float mb) {
        return Color.argb((int) Math.max(0, Math.min(255, a)), (int) Math.min(255, cr * mr), (int) Math.min(255, cg * mg), (int) Math.min(255, cb * mb));
    }

    @Override protected void onDraw(Canvas cv) {
        float t = (System.nanoTime() - t0) / 1e9f;
        boolean fala = Voz.falandoAgora();
        int e = fala ? 3 : estado;
        // nível de áudio com ataque rápido e soltura lenta
        float alvoLvl = e == 3 ? Voz.nivel() : e == 1 ? Ouvido.nivelMic : 0f;
        if (e == 3 && alvoLvl == 0f && !SuperVoz.tocando()) alvoLvl = 0.12f + 0.08f * (float) Math.sin(t * 5);   // ainda sintetizando
        lvl += (alvoLvl - lvl) * (alvoLvl > lvl ? 0.55f : 0.12f);
        if (lvl - lvlAnt > 0.07f && lvl > 0.25f) soltaFaiscas(lvl);
        lvlAnt = lvl;
        pico = Math.max(lvl, pico * 0.94f);
        // cor por estado (transição suave)
        float tr = 54, tg = 214, tb = 255;
        if (e == 1) { tr = 110; tg = 232; tb = 255; }
        else if (e == 2) { tr = 255; tg = 170; tb = 70; }
        else if (e == 3) { tr = 70; tg = 255; tb = 214; }
        cr += (tr - cr) * 0.08f; cg += (tg - cg) * 0.08f; cb += (tb - cb) * 0.08f;

        float vel = e == 2 ? 2.6f : e == 1 ? 0.8f : e == 3 ? 1.0f + lvl : 0.35f;
        ang += 0.014f * vel;
        giro += e == 2 ? 0.05f : 0.004f;
        float angX = 0.38f + 0.14f * (float) Math.sin(t * 0.4);
        float alvo = e == 2 ? 0.74f + 0.04f * (float) Math.sin(t * 6) : e == 1 ? 0.94f + 0.30f * lvl : e == 3 ? 0.96f + 0.26f * lvl
            : 0.90f + 0.04f * (float) Math.sin(t * 1.3);
        raioSuave += (alvo - raioSuave) * 0.18f;
        float w = getWidth(), h = getHeight(), base = Math.min(w, h) * 0.30f, R = base * raioSuave, cx = w / 2, cy = h / 2;

        // halo de fundo
        float hr = R * (1.9f + 0.6f * pico);
        halo.setShader(new RadialGradient(cx, cy, hr, new int[]{cor(70 + 90 * pico, 1, 1, 1), cor(22 + 30 * pico, 1, 1, 1), Color.TRANSPARENT},
            new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));
        cv.drawCircle(cx, cy, hr, halo);

        // anéis de HUD (arcos tracejados girando em sentidos opostos)
        for (int k = 0; k < 3; k++) {
            float rr = R * (1.28f + 0.16f * k) * (1 + 0.10f * lvl * (k + 1));
            oval.set(cx - rr, cy - rr * 0.98f, cx + rr, cy + rr * 0.98f);
            anel.setStrokeWidth(k == 0 ? 3f : 1.6f);
            anel.setColor(cor((k == 0 ? 120 : 70) + 100 * lvl, 1, 1, 1));
            float rot = (float) Math.toDegrees(giro * (k % 2 == 0 ? 1 : -1.4f)) + k * 40;
            int segs = k == 0 ? 3 : k == 1 ? 6 : 12;
            float vao = 360f / segs;
            for (int s = 0; s < segs; s++) cv.drawArc(oval, rot + s * vao, vao * (k == 2 ? 0.25f : 0.62f), false, anel);
        }

        // esfera de partículas
        float ca = (float) Math.cos(ang), sa = (float) Math.sin(ang), cbx = (float) Math.cos(angX), sbx = (float) Math.sin(angX);
        for (int i = 0; i < N; i++) {
            float x0 = px[i], z0 = pz[i];
            if (e == 2) {                                         // pensando: faixas de latitude giram em velocidades diferentes
                float a2 = t * (0.8f + 1.6f * Math.abs(py[i]));
                float c2 = (float) Math.cos(a2), s2 = (float) Math.sin(a2);
                x0 = px[i] * c2 - pz[i] * s2; z0 = px[i] * s2 + pz[i] * c2;
            }
            float x = x0 * ca - z0 * sa, z = x0 * sa + z0 * ca, y = py[i];
            float y2 = y * cbx - z * sbx, z2 = y * sbx + z * cbx;
            float ond;
            if (e == 3) ond = 1f + lvl * 0.42f * (0.5f + 0.5f * (float) Math.sin(lat[i] * 5 + lon[i] * 2 + t * 9)) + 0.02f * (float) Math.sin(t * 3 + i);
            else if (e == 1) ond = 1f + lvl * 0.30f * (0.5f + 0.5f * (float) Math.sin(-lat[i] * 7 + t * 12)) + 0.015f * (float) Math.sin(t * 2 + i);
            else if (e == 2) ond = 1f + 0.05f * (float) Math.sin(lat[i] * 9 - t * 8);
            else ond = 1f + 0.02f * (float) Math.sin(t * 1.4f + i * 0.7f);
            float pr = (z2 + 1.8f) / 2.8f;                      // perspectiva (0,28..1)
            float sx = cx + x * R * ond * pr * 1.08f, sy = cy + y2 * R * ond * pr * 1.08f;
            float frente = (z2 + 1) / 2;
            p.setColor(cor(28 + 200 * frente * frente, 0.9f + 0.4f * lvl, 1, 1));
            cv.drawCircle(sx, sy, 1.1f + 2.4f * pr + 1.8f * lvl * frente, p);
        }

        // núcleo
        float nr = R * (0.30f + 0.35f * lvl);
        halo.setShader(new RadialGradient(cx, cy, nr, new int[]{Color.argb(230, 255, 255, 255), cor(160, 1, 1, 1), Color.TRANSPARENT},
            new float[]{0f, 0.35f, 1f}, Shader.TileMode.CLAMP));
        cv.drawCircle(cx, cy, nr, halo);

        // faíscas
        for (int i = 0; i < FAI; i++) {
            if (fv[i] <= 0) continue;
            fx[i] += fvx[i]; fy[i] += fvy[i]; fvx[i] *= 0.97f; fvy[i] *= 0.97f; fv[i] -= 0.022f;
            p.setColor(cor(255 * Math.max(0, fv[i]), 1.2f, 1.1f, 1));
            cv.drawCircle(cx + fx[i], cy + fy[i], 1.5f + 2f * fv[i], p);
        }
        postInvalidateOnAnimation();
    }

    private void soltaFaiscas(float forca) {
        float R = Math.min(getWidth(), getHeight()) * 0.30f;
        int n = 3 + (int) (forca * 6);
        for (int i = 0; i < FAI && n > 0; i++) {
            if (fv[i] > 0) continue;
            double a = rnd.nextDouble() * Math.PI * 2;
            float v = 2.5f + rnd.nextFloat() * 5f * forca;
            fx[i] = (float) Math.cos(a) * R * 0.9f; fy[i] = (float) Math.sin(a) * R * 0.9f;
            fvx[i] = (float) Math.cos(a) * v; fvy[i] = (float) Math.sin(a) * v; fv[i] = 1f;
            n--;
        }
    }
}
