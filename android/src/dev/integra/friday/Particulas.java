package dev.integra.friday;

import android.content.Context;
import android.graphics.BlendMode;
import android.graphics.BlurMaskFilter;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.view.View;

/** Núcleo de partículas da Friday: plasma 3D em camadas com brilho aditivo (estética Stark).
 *  Camadas (fundo → frente): nebulosa + poeira orbital · esfera de plasma (Fibonacci + campo de ruído)
 *  · núcleo quente com halo · anéis orbitais inclinados com corredores e rastro · filamentos elétricos
 *  · anel espectral + HUD · faíscas · onda de choque na troca de estado.
 *  Estados: 0 espera (respira) · 1 ouvindo (Ouvido.nivelMic) · 2 pensando (redemoinho rumo aos polos)
 *  · 3 falando (Voz.nivel()). Enquanto ela fala, vira 3 sozinho.
 *  onDraw não aloca nada: tudo pré-alocado, desenho em lote (drawPoints/drawLines) agrupado por faixa. */
final class Particulas extends View {
    // ---------- seno por tabela (o laço quente não chama Math.sin) ----------
    private static final int TAB = 4096, TM = TAB - 1;
    private static final float DOIS_PI = 6.2831855f, TK = TAB / DOIS_PI, GRAU = 57.29578f;
    private static final float[] SEN = new float[TAB];
    static { for (int i = 0; i < TAB; i++) SEN[i] = (float) Math.sin(i * 2.0 * Math.PI / TAB); }
    private static float sn(float a) { return SEN[(int) (a * TK) & TM]; }
    private static float cn(float a) { return SEN[((int) (a * TK) + TAB / 4) & TM]; }

    // ---------- paleta por estado, igual à pílula do Assistente: espera azul-ciano · ouvindo CIANO · pensando AMBAR · falando TEAL ----------
    private static final float[][] TINTA = {{40, 168, 255}, {54, 214, 255}, {255, 160, 56}, {70, 255, 214}};
    private static final float LR = 255, LG = 138, LB = 31;      // laranja de acento
    private static final float GR = 216, GG = 246, GB = 255;     // branco-gelo
    private static final float FR = 24, FG = 62, FB = 170;       // azul profundo (partículas do fundo)
    private static final float DC = 5.2f, DCA = 6.5f, DN = 8f;  // distância da câmera: esfera/faíscas · anéis · poeira

    // ---------- esfera de plasma ----------
    private static final int N = 800, NZ = 6;                    // pontos · faixas de profundidade
    private final float[] ey = new float[N], elon = new float[N], fase = new float[N], vtw = new float[N];
    private final float[] sx = new float[N], sy = new float[N], sz = new float[N];   // projeção do quadro
    private final float[] dx = new float[N], dy = new float[N], dz = new float[N];   // direção no mundo
    private final int[] viz = new int[N];                        // vizinho mais próximo (filamentos)
    private final float[][] bufE = new float[NZ * 2][N * 2];
    private final int[] nE = new int[NZ * 2];
    private final Paint[] pE = new Paint[NZ * 2];

    // ---------- poeira / nebulosa ----------
    private static final int NP = 360, NBP = 5;
    private final float[] poR = new float[NP], poTh = new float[NP], poW = new float[NP], poFa = new float[NP], poTw = new float[NP];
    private final float[] poUx = new float[NP], poUy = new float[NP], poUz = new float[NP];
    private final float[] poVx = new float[NP], poVy = new float[NP], poVz = new float[NP];
    private final boolean[] poLar = new boolean[NP];
    private final float[][] bufP = new float[NBP + 1][NP * 2];
    private final int[] nP = new int[NBP + 1];
    private final Paint[] pP = new Paint[NBP + 1];

    // ---------- anéis orbitais ----------
    private static final int NA = 3, SEG = 64, CORR = 5, RAS = 9;          // anéis · segmentos · corredores/anel · posições do rastro
    private static final float[] A_RAIO = {1.45f, 1.80f, 2.20f}, A_INC = {0.80f, 1.25f, 1.48f}, A_ROL = {0.55f, -0.30f, 0.08f},
        A_VEL = {0.95f, -0.66f, 0.42f}, A_PREC = {0.22f, -0.06f, 0.035f};   // anel 0 gira no plano da tela (nunca fica de perfil)
    private final float[] aPrec = {0.4f, 2.1f, 4.0f}, base = new float[6];
    private final float[] cTh = new float[NA * CORR], cMul = new float[NA * CORR];
    private final float[][] bufA = new float[NA * 2][SEG * 4];
    private final int[] nA = new int[NA * 2];
    private final Paint[] pA = new Paint[NA * 2];
    private final float[][] bufR = new float[16][NA * CORR * 8];           // [família][idade][profundidade]
    private final int[] nR = new int[16];
    private final Paint[] pR = new Paint[16];
    private final float[][] bufCab = new float[2][NA * CORR * 2];
    private final int[] nCab = new int[2];
    private final Paint pCabBrilho, pCabNucleo;

    // ---------- filamentos de energia ----------
    private static final int NF = 9, SALTOS = 3, SUB = 4;
    private final int[] filNo = new int[NF];
    private final float[] filVida = new float[NF], filDur = new float[NF];
    private final Path[] filPath = {new Path(), new Path(), new Path()};
    private final boolean[] filUsado = new boolean[3];
    private final Paint pFilBrilho, pFilNucleo;

    // ---------- anel espectral + HUD ----------
    private static final int NB = 96;
    private final float[] barra = new float[NB], barPico = new float[NB], bCos = new float[NB], bSin = new float[NB];
    private final float[] bufB = new float[NB * 4], bufBP = new float[NB * 2];
    private float[] tickMen = new float[0], tickMai = new float[0];
    private final Paint pBarra, pPico, pTick, pTickM, pArco;
    private final RectF oval = new RectF();

    // ---------- faíscas ----------
    private static final int FAI = 90, NFV = 4;
    private final float[] fax = new float[FAI], fay = new float[FAI], faz = new float[FAI];
    private final float[] fvx = new float[FAI], fvy = new float[FAI], fvz = new float[FAI], fav = new float[FAI], fdec = new float[FAI];
    private final float[][] bufF = new float[NFV][FAI * 4];
    private final int[] nF = new int[NFV];
    private final Paint[] pF = new Paint[NFV];
    private final float[] bufFC = new float[FAI * 2];
    private final Paint pFaiC;

    // ---------- núcleo / halo / onda ----------
    private final Paint pHalo, pGrad, pBlur, pOnda;
    private final RadialGradient[] gradHalo = new RadialGradient[4], gradNeb = new RadialGradient[2];
    private final RadialGradient[] gradBarras = new RadialGradient[4];
    private RadialGradient gradNucleo;
    private LinearGradient gradRaio;

    // ---------- estado ----------
    private final java.util.Random rnd = new java.util.Random(7);
    private volatile int estado;
    private int eAnt = -1, larg, alt;
    private final float[] peso = {1f, 0f, 0f, 0f};               // mistura suave dos 4 estados
    private float lvl, lvlAnt, pico, semVoz, esfria, acumFai, raio = 0.9f, ang, giro, onda = -1f;
    private float u = 1f, R0 = 1f, cx, cy, capHalo = 1f;
    private long ultimo;
    private final long t0 = System.nanoTime();

    Particulas(Context c) {
        super(c);
        // esfera de Fibonacci
        double ouro = Math.PI * (3 - Math.sqrt(5));
        for (int i = 0; i < N; i++) {
            double y = 1 - (i + 0.5) / N * 2, r = Math.sqrt(1 - y * y), th = ouro * i;
            ey[i] = (float) y; elon[i] = (float) (th % (2 * Math.PI));
            dx[i] = (float) (Math.cos(th) * r); dy[i] = (float) y; dz[i] = (float) (Math.sin(th) * r);
            fase[i] = rnd.nextFloat() * DOIS_PI; vtw[i] = 0.5f + rnd.nextFloat() * 2.5f;
        }
        // vizinho mais próximo "para a frente" (o filamento anda sem voltar)
        int[] passos = {3, 5, 8, 13, 21, 34, 55, 89, 144};
        for (int i = 0; i < N; i++) {
            float melhor = 9f; int bi = i > 0 ? i - 1 : 1;
            for (int o : passos) {
                int j = i + o < N ? i + o : i - o;
                if (j < 0) continue;
                float ax = dx[i] - dx[j], ay = dy[i] - dy[j], az = dz[i] - dz[j], d2 = ax * ax + ay * ay + az * az;
                if (d2 < melhor) { melhor = d2; bi = j; }
            }
            viz[i] = bi;
        }
        // poeira: 70% num disco largo (usa a largura da folha), 30% numa casca em volta do núcleo
        for (int i = 0; i < NP; i++) {
            boolean disco = i < NP * 7 / 10;
            float r = disco ? 1.3f + (float) Math.pow(rnd.nextFloat(), 0.8) * 2.6f : 1.15f + rnd.nextFloat() * 1.1f;
            double inc = disco ? (rnd.nextFloat() - 0.5f) * 0.36f : rnd.nextFloat() * Math.PI, no = rnd.nextFloat() * 2 * Math.PI;
            float ci = (float) Math.cos(inc), si = (float) Math.sin(inc), cno = (float) Math.cos(no), sno = (float) Math.sin(no);
            poUx[i] = cno; poUy[i] = 0f; poUz[i] = -sno;                 // base do plano da órbita
            poVx[i] = ci * sno; poVy[i] = -si; poVz[i] = ci * cno;
            poR[i] = r; poTh[i] = rnd.nextFloat() * DOIS_PI;
            poW[i] = (float) (0.32 / Math.pow(r, 1.5)) * (disco || rnd.nextBoolean() ? 1f : -1f);   // quase Kepler
            poFa[i] = rnd.nextFloat() * DOIS_PI; poTw[i] = 0.4f + rnd.nextFloat() * 3f;
            poLar[i] = rnd.nextFloat() < 0.06f;
        }
        for (int i = 0; i < NA * CORR; i++) { cTh[i] = (i % CORR) * DOIS_PI / CORR + rnd.nextFloat() * 0.7f; cMul[i] = 0.8f + rnd.nextFloat() * 0.5f; }
        for (int i = 0; i < NB; i++) { double a = i * 2 * Math.PI / NB - Math.PI / 2; bCos[i] = (float) Math.cos(a); bSin[i] = (float) Math.sin(a); }

        for (int i = 0; i < pE.length; i++) pE[i] = tinta(Paint.Style.STROKE);
        for (int i = 0; i < pP.length; i++) pP[i] = tinta(Paint.Style.STROKE);
        for (int i = 0; i < pA.length; i++) pA[i] = tinta(Paint.Style.STROKE);
        for (int i = 0; i < pR.length; i++) pR[i] = tinta(Paint.Style.STROKE);
        for (int i = 0; i < pF.length; i++) pF[i] = tinta(Paint.Style.STROKE);
        pCabBrilho = tinta(Paint.Style.STROKE); pCabNucleo = tinta(Paint.Style.STROKE);
        pFilBrilho = tinta(Paint.Style.STROKE); pFilNucleo = tinta(Paint.Style.STROKE);
        pBarra = tinta(Paint.Style.STROKE); pBarra.setStrokeCap(Paint.Cap.BUTT);
        pPico = tinta(Paint.Style.STROKE);
        pTick = tinta(Paint.Style.STROKE); pTick.setStrokeCap(Paint.Cap.BUTT);
        pTickM = tinta(Paint.Style.STROKE); pTickM.setStrokeCap(Paint.Cap.BUTT);
        pArco = tinta(Paint.Style.STROKE); pArco.setStrokeCap(Paint.Cap.BUTT);
        pFaiC = tinta(Paint.Style.STROKE);
        pHalo = tinta(Paint.Style.FILL); pGrad = tinta(Paint.Style.FILL); pBlur = tinta(Paint.Style.FILL);
        pOnda = tinta(Paint.Style.STROKE);
        setLayerType(LAYER_TYPE_HARDWARE, null);
    }

    void estado(int e) { estado = e; }
    void nivel(float n) {}                                     // compat: o nível agora vem direto do microfone/voz

    private static Paint tinta(Paint.Style st) {
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setStyle(st); p.setStrokeCap(Paint.Cap.ROUND);
        if (android.os.Build.VERSION.SDK_INT >= 29) p.setBlendMode(BlendMode.PLUS);   // sobreposição soma luz
        return p;
    }

    private static int cl(float v) { return v <= 0f ? 0 : v >= 255f ? 255 : (int) v; }
    private static int argb(float a, float r, float g, float b) { return Color.argb(cl(a), cl(r), cl(g), cl(b)); }

    @Override protected void onAttachedToWindow() { super.onAttachedToWindow(); ultimo = 0; invalidate(); }
    @Override protected void onDetachedFromWindow() { super.onDetachedFromWindow(); ultimo = 0; }

    /** recria shaders, blur e marcações só quando o tamanho muda */
    private void prepara(int w, int h) {
        larg = w; alt = h;
        float S = Math.min(w, h);
        u = S / 200f; R0 = S * 0.235f; cx = w * 0.5f; cy = h * 0.5f;
        capHalo = cy * 0.97f / (R0 * 2.1f);                       // o halo nunca encosta na borda de cima/baixo
        Shader.TileMode cla = Shader.TileMode.CLAMP;
        for (int s = 0; s < 4; s++) {
            int r = (int) TINTA[s][0], g = (int) TINTA[s][1], b = (int) TINTA[s][2];
            gradHalo[s] = new RadialGradient(0, 0, R0 * 2.1f,
                new int[]{Color.argb(118, r, g, b), Color.argb(44, r, g, b), Color.argb(12, r, g, b), Color.TRANSPARENT},
                new float[]{0f, 0.34f, 0.68f, 1f}, cla);
        }
        gradNeb[0] = new RadialGradient(0, 0, R0 * 1.7f, new int[]{Color.argb(46, 110, 80, 255), Color.argb(16, 90, 70, 230), Color.TRANSPARENT},
            new float[]{0f, 0.5f, 1f}, cla);
        gradNeb[1] = new RadialGradient(0, 0, R0 * 1.7f, new int[]{Color.argb(42, 30, 160, 255), Color.argb(14, 30, 120, 220), Color.TRANSPARENT},
            new float[]{0f, 0.5f, 1f}, cla);
        gradNucleo = new RadialGradient(0, 0, R0 * 0.55f,
            new int[]{Color.WHITE, Color.argb(235, 216, 246, 255), Color.argb(120, 54, 214, 255), Color.TRANSPARENT},
            new float[]{0f, 0.16f, 0.45f, 1f}, cla);
        float rb0 = R0 * 1.40f, rb1 = rb0 + R0 * 0.42f;           // barras: tinta do estado na base, gelo no meio, laranja na ponta
        for (int s = 0; s < 4; s++) {
            int cor = Color.rgb((int) TINTA[s][0], (int) TINTA[s][1], (int) TINTA[s][2]);
            gradBarras[s] = new RadialGradient(0, 0, rb1, new int[]{cor, cor, Color.rgb(216, 246, 255), Color.rgb(255, 138, 31)},
                new float[]{0f, rb0 / rb1, (rb0 + R0 * 0.2f) / rb1, 1f}, cla);
        }
        gradRaio = new LinearGradient(-R0 * 2.8f, 0, R0 * 2.8f, 0,
            new int[]{Color.TRANSPARENT, Color.rgb(216, 246, 255), Color.TRANSPARENT}, new float[]{0f, 0.5f, 1f}, cla);
        pBlur.setMaskFilter(new BlurMaskFilter(R0 * 0.30f, BlurMaskFilter.Blur.NORMAL));
        // marcações do HUD (giram com canvas.rotate: nada de trigonometria por quadro)
        int nt = 120, nMai = nt / 10, a1 = 0, a2 = 0;
        tickMen = new float[(nt - nMai) * 4]; tickMai = new float[nMai * 4];
        float rT = R0 * 1.86f;
        for (int i = 0; i < nt; i++) {
            double a = i * 2 * Math.PI / nt;
            float c = (float) Math.cos(a), s = (float) Math.sin(a);
            boolean mai = i % 10 == 0;
            float ri = mai ? R0 * 1.76f : R0 * 1.81f;
            float[] q = mai ? tickMai : tickMen; int k = mai ? a2 : a1;
            q[k] = c * ri; q[k + 1] = s * ri; q[k + 2] = c * rT; q[k + 3] = s * rT;
            if (mai) a2 += 4; else a1 += 4;
        }
    }

    /** base (u,v) do plano do anel k com precessão, rolagem e inclinação da câmera */
    private void planoAnel(int k, float cp, float sp) {
        float pre = k == 0 ? 0f : aPrec[k], rol = k == 0 ? A_ROL[0] + aPrec[0] : A_ROL[k];
        float ci = cn(A_INC[k]), si = sn(A_INC[k]), cpr = cn(pre), spr = sn(pre), cr = cn(rol), sr = sn(rol);
        for (int q = 0; q < 2; q++) {
            float x = q == 0 ? 1f : 0f, y = q == 0 ? 0f : ci, z = q == 0 ? 0f : si;
            float x1 = x * cpr + z * spr, z1 = -x * spr + z * cpr;      // precessão (Y)
            float x2 = x1 * cr - y * sr, y2 = x1 * sr + y * cr;         // rolagem (Z)
            float y3 = y2 * cp - z1 * sp, z3 = y2 * sp + z1 * cp;       // câmera (X)
            base[q * 3] = x2; base[q * 3 + 1] = y3; base[q * 3 + 2] = z3;
        }
    }

    @Override protected void onDraw(Canvas cv) {
        long agora = System.nanoTime();
        float dt = ultimo == 0 ? 1f / 60f : (agora - ultimo) / 1e9f;
        ultimo = agora;
        if (dt > 0.05f) dt = 0.05f; else if (dt < 0f) dt = 0f;
        float t = ((agora - t0) % 1_800_000_000_000L) / 1e9f;      // volta a cada 30 min (precisão do float)
        int w = getWidth(), h = getHeight();
        if (w <= 0 || h <= 0) { postInvalidateOnAnimation(); return; }
        if (w != larg || h != alt) prepara(w, h);

        // ---------- estado efetivo e nível de áudio (ataque rápido, soltura lenta) ----------
        int e = Voz.falandoAgora() ? 3 : estado;
        if (e < 0 || e > 3) e = 0;
        float bruto = e == 3 ? Voz.nivel() : e == 1 ? Ouvido.nivelMic : 0f;
        if (e == 3 && bruto <= 0f) { semVoz += dt; if (semVoz > 0.25f) bruto = 0.12f + 0.08f * sn(t * 5f); }   // ainda sintetizando
        else semVoz = 0f;
        bruto = bruto < 0f ? 0f : bruto > 1f ? 1f : bruto;
        lvl += (bruto - lvl) * (1f - (float) Math.exp(-dt * (bruto > lvl ? 48f : 7.7f)));
        esfria -= dt;
        if (lvl - lvlAnt > 4.2f * dt && lvl > 0.25f && esfria <= 0f) { soltaFaiscas(lvl, 4 + (int) (lvl * 7)); esfria = 0.06f; }   // pico de voz
        lvlAnt = lvl;
        pico = Math.max(lvl, pico * (float) Math.exp(-dt * 3.7f));

        // ---------- transição suave entre estados (~300 ms) ----------
        if (e != eAnt) { if (eAnt >= 0) onda = 1f; eAnt = e; }
        float kE = 1f - (float) Math.exp(-dt * 11f), tr = 0f, tg = 0f, tb = 0f;
        for (int s = 0; s < 4; s++) {
            peso[s] += ((s == e ? 1f : 0f) - peso[s]) * kE;
            tr += peso[s] * TINTA[s][0]; tg += peso[s] * TINTA[s][1]; tb += peso[s] * TINTA[s][2];
        }
        float w0 = peso[0], w1 = peso[1], w2 = peso[2], w3 = peso[3];
        float acento = w0 * 0.10f + w1 * 0.12f + w2 * 0.85f + w3 * (0.45f + 0.5f * lvl);
        float inten = w0 * 0.80f + w1 * (0.92f + 0.25f * lvl) + w2 * 0.95f + w3 * (0.98f + 0.3f * lvl);
        float vel = w0 * 0.30f + w1 * 0.60f + w2 * 2.0f + w3 * (0.8f + 1.0f * lvl);
        float alvoR = w0 * (0.90f + 0.035f * sn(t * 1.3f)) + w1 * (0.97f + 0.15f * lvl) + w2 * (0.80f + 0.03f * sn(t * 6f)) + w3 * (0.95f + 0.22f * lvl);
        raio += (alvoR - raio) * (1f - (float) Math.exp(-dt * 12f));
        ang = (ang + dt * 0.84f * vel) % DOIS_PI;
        giro = (giro + dt * (0.22f + 2.2f * w2 + 0.8f * w3 * lvl)) % (DOIS_PI * 10f);   // múltiplos de 0,1 de giro fecham a volta
        float pitch = 0.34f + 0.10f * sn(t * 0.4f), cp = cn(pitch), sp = sn(pitch);
        float Rp = R0 * raio;

        cv.save();
        cv.translate(cx, cy);

        // ---------- 1a. nebulosa: manchas suaves derivando + halo tingido por estado ----------
        pGrad.setShader(gradNeb[0]); pGrad.setAlpha(cl(255 * inten * (0.7f + 0.5f * w2)));
        cv.save(); cv.translate(R0 * 1.5f * sn(t * 0.11f), R0 * 0.35f * sn(t * 0.17f + 1f)); cv.scale(1.5f, 1f);
        cv.drawCircle(0, 0, R0 * 1.7f, pGrad); cv.restore();
        pGrad.setShader(gradNeb[1]); pGrad.setAlpha(cl(255 * inten));
        cv.save(); cv.translate(-R0 * 1.6f * sn(t * 0.09f + 2f), R0 * 0.3f * sn(t * 0.13f)); cv.scale(1.6f, 1f);
        cv.drawCircle(0, 0, R0 * 1.7f, pGrad); cv.restore();
        float esc = raio * (1f + 0.25f * pico);
        for (int s = 0; s < 4; s++) {                              // 1 desenho; 2 durante a transição
            if (peso[s] < 0.01f) continue;
            pHalo.setShader(gradHalo[s]); pHalo.setAlpha(cl(255 * peso[s] * (0.5f + 0.5f * inten)));
            cv.save(); cv.scale(esc, Math.min(esc, capHalo)); cv.drawCircle(0, 0, R0 * 2.1f, pHalo); cv.restore();
        }

        // ---------- 1b. poeira orbital: órbitas lentas e amplas, cintilação individual ----------
        float velNeb = 0.35f + 0.9f * w2 + 0.35f * w3 * (0.5f + lvl);
        for (int b = 0; b <= NBP; b++) nP[b] = 0;
        float fBy = 1f / (cy * 0.28f), fBx = 1f / (cx * 0.16f);
        for (int i = 0; i < NP; i++) {
            float th = poTh[i] + poW[i] * velNeb * dt;
            if (th > DOIS_PI) th -= DOIS_PI; else if (th < 0f) th += DOIS_PI;
            poTh[i] = th;
            float c = cn(th) * poR[i], s = sn(th) * poR[i];
            float x = c * poUx[i] + s * poVx[i], y = c * poUy[i] + s * poVy[i], z = c * poUz[i] + s * poVz[i];
            float y2 = y * cp - z * sp, z2 = y * sp + z * cp;
            float pr = DN / (DN - z2) * R0, px = x * pr, py = y2 * pr;
            float ef = Math.min(1f, (cy - Math.abs(py)) * fBy) * Math.min(1f, (cx - Math.abs(px)) * fBx);   // apaga perto da borda
            if (ef <= 0.02f) continue;
            int b;
            if (poLar[i] && ef > 0.7f) b = NBP;
            else {
                float prof = 0.5f + 0.5f * z2 / poR[i], cint = 0.5f + 0.5f * sn(poFa[i] + t * poTw[i]);
                b = (int) ((0.15f + 0.85f * prof) * (0.3f + 0.7f * cint) * ef * NBP);
                if (b >= NBP) b = NBP - 1; else if (b < 0) b = 0;
            }
            float[] bf = bufP[b]; int n = nP[b];
            bf[n] = px; bf[n + 1] = py; nP[b] = n + 2;
        }
        float mr = tr + (GR - tr) * 0.45f, mg = tg + (GG - tg) * 0.45f, mb = tb + (GB - tb) * 0.45f;
        for (int b = 0; b < NBP; b++) {
            float f = (b + 0.5f) / NBP;
            pP[b].setColor(argb((16 + 160 * f * f) * inten, FR + (mr - FR) * f, FG + (mg - FG) * f, FB + (mb - FB) * f));
            pP[b].setStrokeWidth(u * (0.6f + 1.3f * f));
            if (nP[b] > 0) cv.drawPoints(bufP[b], 0, nP[b], pP[b]);
        }
        pP[NBP].setColor(argb((70 + 110 * acento) * inten, LR, LG, LB)); pP[NBP].setStrokeWidth(u * 1.3f);
        if (nP[NBP] > 0) cv.drawPoints(bufP[NBP], 0, nP[NBP], pP[NBP]);

        // ---------- 4. anéis orbitais inclinados + corredores com rastro ----------
        for (int b = 0; b < NA * 2; b++) nA[b] = 0;
        for (int b = 0; b < 16; b++) nR[b] = 0;
        nCab[0] = 0; nCab[1] = 0;
        float velAnel = 0.5f + 0.9f * vel;
        for (int k = 0; k < NA; k++) {
            aPrec[k] = (aPrec[k] + dt * A_PREC[k] * (1f + 2f * w2)) % DOIS_PI;
            planoAnel(k, cp, sp);
            float rr = A_RAIO[k] * (1f + 0.04f * sn(t * 0.7f + k) + 0.06f * lvl);
            float x0 = 0f, y0 = 0f, z0 = 0f;
            for (int s = 0; s <= SEG; s++) {                       // contorno (o anel externo é tracejado)
                float th = s * (DOIS_PI / SEG), c = cn(th) * rr, sv = sn(th) * rr;
                float X = c * base[0] + sv * base[3], Y = c * base[1] + sv * base[4], Z = c * base[2] + sv * base[5];
                float pr = DCA / (DCA - Z) * R0, px = X * pr, py = Y * pr;
                if (s > 0 && (k != 2 || (s & 1) == 0)) {
                    int b = k * 2 + (Z + z0 > 0f ? 1 : 0);
                    float[] bf = bufA[b]; int n = nA[b];
                    bf[n] = x0; bf[n + 1] = y0; bf[n + 2] = px; bf[n + 3] = py; nA[b] = n + 4;
                }
                x0 = px; y0 = py; z0 = Z;
            }
            int fam = k == 1 ? 1 : 0;
            for (int j = 0; j < CORR; j++) {                       // corredores: cabeça + cauda de RAS posições
                int id = k * CORR + j;
                float om = A_VEL[k] * cMul[id] * velAnel;
                float th = (cTh[id] + om * dt) % DOIS_PI;
                cTh[id] = th;
                float passo = Math.max(0.03f, Math.min(0.14f, Math.abs(om) * 0.06f)) * (om >= 0f ? 1f : -1f);
                float qx = 0f, qy = 0f;
                for (int m = 0; m < RAS; m++) {
                    float a = th - m * passo, c = cn(a) * rr, sv = sn(a) * rr;
                    float X = c * base[0] + sv * base[3], Y = c * base[1] + sv * base[4], Z = c * base[2] + sv * base[5];
                    float pr = DCA / (DCA - Z) * R0, px = X * pr, py = Y * pr;
                    int frente = Z > 0f ? 1 : 0;
                    if (m == 0) {
                        float[] bf = bufCab[frente]; int n = nCab[frente];
                        bf[n] = px; bf[n + 1] = py; nCab[frente] = n + 2;
                    } else {
                        int b = fam * 8 + ((m - 1) >> 1) * 2 + frente;
                        float[] bf = bufR[b]; int n = nR[b];
                        bf[n] = qx; bf[n + 1] = qy; bf[n + 2] = px; bf[n + 3] = py; nR[b] = n + 4;
                    }
                    qx = px; qy = py;
                }
            }
        }
        for (int k = 0; k < NA; k++) {
            float r = tr, g = tg, b = tb;
            if (k == 1) { float m = 0.2f + 0.65f * acento; r += (LR - r) * m; g += (LG - g) * m; b += (LB - b) * m; }
            else if (k == 2) { r += (GR - r) * 0.5f; g += (GG - g) * 0.5f; b += (GB - b) * 0.5f; }
            Paint atras = pA[k * 2], frente = pA[k * 2 + 1];
            atras.setColor(argb((22 + 18 * lvl) * inten, r, g, b)); atras.setStrokeWidth(u * 0.7f);
            frente.setColor(argb((62 + 60 * lvl) * inten, r, g, b)); frente.setStrokeWidth(u * 1.1f);
            if (nA[k * 2] > 0) cv.drawLines(bufA[k * 2], 0, nA[k * 2], atras);
            if (nA[k * 2 + 1] > 0) cv.drawLines(bufA[k * 2 + 1], 0, nA[k * 2 + 1], frente);
        }
        for (int f = 0; f < 2; f++) {                              // rastros: família 0 tinta→gelo (puxa p/ laranja) · 1 laranja
            float r, g, b, famA;
            if (f == 0) {
                r = tr + (GR - tr) * 0.35f; g = tg + (GG - tg) * 0.35f; b = tb + (GB - tb) * 0.35f;
                float m = acento * 0.45f; r += (LR - r) * m; g += (LG - g) * m; b += (LB - b) * m; famA = 1f;
            } else { r = LR + (GR - LR) * 0.15f; g = LG + (GG - LG) * 0.15f; b = LB + (GB - LB) * 0.15f; famA = 0.45f + 0.55f * acento; }
            for (int ida = 0; ida < 4; ida++) {
                float v = 1f - ida / 4f; v *= (float) Math.sqrt(v);
                for (int pz = 0; pz < 2; pz++) {
                    int id = f * 8 + ida * 2 + pz;
                    Paint p = pR[id];
                    p.setColor(argb(205 * v * (pz == 0 ? 0.40f : 1f) * famA * inten, r, g, b));
                    p.setStrokeWidth(u * (0.9f + 1.2f * v) * (pz == 0 ? 0.8f : 1f));
                    if (nR[id] > 0) cv.drawLines(bufR[id], 0, nR[id], p);
                }
            }
        }
        float ma = acento * 0.5f;
        pCabBrilho.setStrokeWidth(u * 5.5f); pCabNucleo.setStrokeWidth(u * 2.0f);
        for (int pz = 0; pz < 2; pz++) {
            if (nCab[pz] == 0) continue;
            pCabBrilho.setColor(argb((pz == 0 ? 28 : 72) * inten, tr + (LR - tr) * ma, tg + (LG - tg) * ma, tb + (LB - tb) * ma));
            cv.drawPoints(bufCab[pz], 0, nCab[pz], pCabBrilho);
            pCabNucleo.setColor(argb((pz == 0 ? 110 : 250) * inten, GR, GG, GB));
            cv.drawPoints(bufCab[pz], 0, nCab[pz], pCabNucleo);
        }

        // ---------- 2. esfera de plasma: Fibonacci deformada por campo de ruído ----------
        for (int b = 0; b < NZ * 2; b++) nE[b] = 0;
        float ca = cn(ang), sa = sn(ang);
        float amR = w0 * 0.045f + w1 * (0.05f + 0.10f * lvl) + w2 * 0.035f + w3 * (0.04f + 0.05f * lvl);
        float amFala = w3 * lvl * 0.34f, amOuve = w1 * lvl * 0.28f, rotPolo = t * 0.17f;
        for (int i = 0; i < N; i++) {
            float y = ey[i], lon = elon[i], rf = 1f, apaga = 1f;
            if (w2 > 0.004f) {                                     // pensando: faixas espiralam para os polos e contraem
                float s = Math.abs(y) + rotPolo; s -= (int) s;
                y += ((ey[i] >= 0f ? s : -s) - y) * w2;
                lon += w2 * (t * (0.5f + 1.8f * s) + 4f * s);
                rf -= w2 * 0.16f * s;
                float bd = s < 0.1f ? s * 10f : s > 0.88f ? (1f - s) * 8.3f : 1f;   // some ao renascer no equador
                apaga = 1f - w2 * (1f - bd);
            }
            float rxz = (float) Math.sqrt(Math.max(0f, 1f - y * y));
            float ox = rxz * cn(lon), oz = rxz * sn(lon);
            float d = amR * (0.45f * sn(2.7f * ox + 1.3f * t) * cn(2.3f * y - 0.9f * t)
                + 0.35f * sn(3.9f * oz + 2.1f * y + 1.1f * t) + 0.2f * sn(5.3f * (ox - oz) - 1.7f * t));   // respira
            if (amFala > 0.002f) d += amFala * (0.55f + 0.45f * sn(y * 7.5f - t * 10f)) * (0.7f + 0.3f * sn(lon * 3f + t * 4f));   // ondas por latitude
            float x1 = ox * ca - oz * sa, z1 = ox * sa + oz * ca;
            float y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
            if (amOuve > 0.002f) d += amOuve * (0.5f + 0.5f * sn(z2 * 9f - t * 13f));   // ouvindo: anéis entrando rumo ao centro
            float rad = rf * (1f + d), pr = DC / (DC - z2 * rad) * Rp * rad;
            float px = x1 * pr, py = y2 * pr;
            sx[i] = px; sy[i] = py; sz[i] = z2; dx[i] = x1; dy[i] = y2; dz[i] = z2;
            int bz = (int) ((z2 + 1f) * 0.5f * apaga * NZ);
            if (bz >= NZ) bz = NZ - 1; else if (bz < 0) bz = 0;
            int b = bz * 2 + (d > 0.15f || sn(fase[i] + t * vtw[i]) > 0.985f ? 1 : 0);   // crista da voz ou cintilação = ponto quente
            float[] bf = bufE[b]; int n = nE[b];
            bf[n] = px; bf[n + 1] = py; nE[b] = n + 2;
        }
        float lq = w3 * lvl * 0.5f + w2 * 0.35f;
        float fr = FR + (96f - FR) * w2, fg = FG + (34f - FG) * w2, fb = FB + (10f - FB) * w2;   // fundo: azul profundo · brasa no pensando
        for (int z = 0; z < NZ; z++) {
            float f = (z + 0.5f) / NZ, g = Math.max(0f, f - 0.55f) * 0.9f;   // fundo escuro e apagado · frente puxa p/ gelo
            float r = fr + (tr - fr) * f, gg = fg + (tg - fg) * f, bb = fb + (tb - fb) * f;
            r += (GR - r) * g; gg += (GG - gg) * g; bb += (GB - bb) * g;
            Paint pn = pE[z * 2], pq = pE[z * 2 + 1];
            pn.setColor(argb((16 + 215 * f * f) * inten, r, gg, bb));
            pn.setStrokeWidth(u * (0.75f + 1.45f * f) * (1f + 0.2f * lvl));
            pq.setColor(argb((50 + 180 * f) * inten, GR + (LR - GR) * lq, GG + (LG - GG) * lq, GB + (LB - GB) * lq));
            pq.setStrokeWidth(u * (1.0f + 1.5f * f) * (1f + 0.25f * lvl));
            if (nE[z * 2] > 0) cv.drawPoints(bufE[z * 2], 0, nE[z * 2], pn);
            if (nE[z * 2 + 1] > 0) cv.drawPoints(bufE[z * 2 + 1], 0, nE[z * 2 + 1], pq);
        }

        // ---------- 3. núcleo brilhante: brasa tingida (blur) + acento laranja (blur) + centro branco + raio anamórfico ----------
        float resp = 0.5f + 0.5f * sn(t * 1.6f);
        if (android.os.Build.VERSION.SDK_INT >= 28) {              // BlurMaskFilter no acelerado só a partir do 28
            pBlur.setColor(argb((105 + 70 * pico) * inten, tr, tg, tb));
            cv.drawCircle(0, 0, Rp * (0.34f + 0.20f * lvl + 0.04f * resp), pBlur);
            float lar = w3 * (0.35f + 0.65f * lvl) + w2 * 0.3f;
            if (lar > 0.02f) { pBlur.setColor(argb(140 * lar, LR, LG, LB)); cv.drawCircle(0, 0, Rp * (0.15f + 0.14f * lvl), pBlur); }
        }
        float ec = raio * (0.58f + 0.32f * lvl + 0.06f * resp);
        pGrad.setShader(gradNucleo); pGrad.setAlpha(cl((150 + 60 * pico) * inten));
        cv.save(); cv.scale(ec, ec); cv.drawCircle(0, 0, R0 * 0.55f, pGrad); cv.restore();
        float ra = 0.25f + 0.75f * pico, hh = u * (0.6f + 1.6f * ra);
        pGrad.setShader(gradRaio); pGrad.setAlpha(cl(110 * ra * inten));
        cv.drawRect(-R0 * 2.8f, -hh, R0 * 2.8f, hh, pGrad);

        // ---------- 5. filamentos de energia: arcos elétricos entre vizinhos da superfície ----------
        float taxa = 0.8f + 9f * w2 + w3 * (3f + 16f * lvl) + w1 * 6f * lvl;   // arcos por segundo
        for (int b = 0; b < 3; b++) { filPath[b].reset(); filUsado[b] = false; }
        for (int k = 0; k < NF; k++) {
            if (filVida[k] <= 0f) {
                if (rnd.nextFloat() >= taxa * dt / NF * 3f) continue;
                filNo[k] = rnd.nextInt(N); filDur[k] = 0.12f + rnd.nextFloat() * 0.3f; filVida[k] = 1f;
            }
            filVida[k] -= dt / filDur[k];
            if (filVida[k] <= 0f) continue;
            int a = filNo[k];
            float forca = filVida[k] * (0.55f + 0.45f * rnd.nextFloat()) * (0.25f + 0.75f * (0.5f + 0.5f * sz[a]));   // tremula; atrás apaga
            int b = forca > 0.6f ? 0 : forca > 0.3f ? 1 : 2;
            Path pa = filPath[b];
            pa.moveTo(sx[a], sy[a]); filUsado[b] = true;
            for (int sal = 0; sal < SALTOS; sal++) {
                int c = viz[a];
                float ax = sx[a], ay = sy[a], ddx = sx[c] - ax, ddy = sy[c] - ay;
                float len = (float) Math.sqrt(ddx * ddx + ddy * ddy);
                if (len > Rp * 0.45f || len < 0.5f) break;
                float nx = -ddy / len, ny = ddx / len;
                for (int q = 1; q <= SUB; q++) {
                    float fq = q / (float) SUB, mx = ax + ddx * fq, my = ay + ddy * fq;
                    if (q < SUB) {
                        float arco = sn(fq * 3.1415927f) * len * 0.35f;      // sobe da superfície
                        float rm = (float) Math.sqrt(mx * mx + my * my) + 1e-3f, jit = (rnd.nextFloat() - 0.5f) * len * 0.55f;
                        mx += mx / rm * arco + nx * jit; my += my / rm * arco + ny * jit;
                    }
                    pa.lineTo(mx, my);
                }
                a = c;
            }
        }
        float fm = acento * 0.4f;
        pFilBrilho.setStrokeWidth(u * 3.2f); pFilNucleo.setStrokeWidth(u * 0.9f);
        for (int b = 0; b < 3; b++) {
            if (!filUsado[b]) continue;
            float f = b == 0 ? 1f : b == 1 ? 0.6f : 0.3f;
            pFilBrilho.setColor(argb(75 * f * inten, tr + (LR - tr) * fm, tg + (LG - tg) * fm, tb + (LB - tb) * fm));
            cv.drawPath(filPath[b], pFilBrilho);
            pFilNucleo.setColor(argb(235 * f, GR, GG, GB));
            cv.drawPath(filPath[b], pFilNucleo);
        }

        // ---------- 6. anel espectral (equalizador radial) ----------
        float lb = w0 * (0.05f + 0.03f * sn(t * 1.1f)) + w1 * (0.07f + 0.7f * lvl) + w3 * (0.08f + 0.95f * lvl);
        float rb0 = R0 * 1.40f, lmax = R0 * 0.40f, kb = 1f - (float) Math.exp(-dt * 30f), kq = dt * 0.55f;
        int nb = 0, nbp = 0;
        for (int i = 0; i < NB; i++) {
            float a = i * (DOIS_PI / NB);
            float esp = 0.5f + 0.5f * sn(a * 5f + t * 2.1f) * cn(a * 3f - t * 1.3f);    // variação por ângulo
            float alvo = lb * (0.18f + 0.82f * esp * esp) * (0.75f + 0.5f * rnd.nextFloat());   // perfil irregular, não um anel cheio
            if (w2 > 0.01f) { float dv = cn(a - giro * 3f); if (dv > 0f) { dv *= dv; dv *= dv; alvo += w2 * 0.55f * dv * dv; } }   // pensando: varredura
            barra[i] += (alvo - barra[i]) * (alvo > barra[i] ? kb : kb * 0.35f);
            barPico[i] = Math.max(barra[i], barPico[i] - kq);
            float c = bCos[i], s = bSin[i], r1 = rb0 + u * 1.5f + lmax * Math.min(1f, barra[i]);
            bufB[nb] = c * rb0; bufB[nb + 1] = s * rb0; bufB[nb + 2] = c * r1; bufB[nb + 3] = s * r1; nb += 4;
            if (barPico[i] > 0.1f) { float rp = rb0 + u * 4f + lmax * Math.min(1f, barPico[i]); bufBP[nbp] = c * rp; bufBP[nbp + 1] = s * rp; nbp += 2; }
        }
        int sDom = 0; for (int s = 1; s < 4; s++) if (peso[s] > peso[sDom]) sDom = s;
        pBarra.setShader(gradBarras[sDom]); pBarra.setAlpha(cl((110 + 130 * pico) * inten)); pBarra.setStrokeWidth(Math.max(1f, rb0 * DOIS_PI / NB * 0.34f));
        cv.drawLines(bufB, 0, nb, pBarra);
        if (nbp > 0) { pPico.setColor(argb(200 * inten, LR, 170, 80)); pPico.setStrokeWidth(u * 1.6f); cv.drawPoints(bufBP, 0, nbp, pPico); }

        // ---------- HUD: marcações finas e segmentos girando em sentidos opostos ----------
        cv.save(); cv.rotate(-giro * 0.6f * GRAU);
        pTick.setStrokeWidth(u * 0.7f); pTick.setColor(argb(55 * inten, tr, tg, tb));
        cv.drawLines(tickMen, 0, tickMen.length, pTick);
        pTickM.setStrokeWidth(u * 1.1f); pTickM.setColor(argb(130 * inten, GR, GG, GB));
        cv.drawLines(tickMai, 0, tickMai.length, pTickM);
        cv.restore();
        float rot = giro * GRAU, ri = R0 * 1.30f, re = R0 * 1.93f;
        oval.set(-ri, -ri, ri, ri);
        pArco.setStrokeWidth(u * 1.2f); pArco.setColor(argb((55 + 70 * lvl) * inten, tr, tg, tb));
        for (int s = 0; s < 6; s++) cv.drawArc(oval, rot + s * 60f, 34f, false, pArco);
        pArco.setStrokeWidth(u * 2.0f); pArco.setColor(argb((30 + 180 * acento) * inten, LR, LG, LB));
        cv.drawArc(oval, -rot * 2f + 90f, 10f + 22f * acento, false, pArco);
        oval.set(-re, -re, re, re);
        pArco.setStrokeWidth(u * 1.5f); pArco.setColor(argb(70 * inten, tr, tg, tb));
        for (int s = 0; s < 3; s++) cv.drawArc(oval, -rot * 1.5f + s * 120f, 76f, false, pArco);
        pArco.setStrokeWidth(u * 2.2f); pArco.setColor(argb((40 + 170 * acento) * inten, LR, LG, LB));
        cv.drawArc(oval, rot * 2f + 200f, 14f + 20f * acento, false, pArco);

        // ---------- ouvindo: ondas de sonar entrando (o som chega ao núcleo) ----------
        if (w1 > 0.02f) {
            float am = w1 * (0.35f + 0.65f * lvl);
            pOnda.setStrokeWidth(u * 1.3f);
            for (int q = 0; q < 3; q++) {
                float p = t * 0.75f + q / 3f; p -= (int) p;            // 0 → 1: de fora para dentro
                pOnda.setColor(argb(120 * am * sn(p * 3.1415927f) * inten, tr, tg, tb));
                cv.drawCircle(0, 0, R0 * (1.90f - 0.72f * p), pOnda);
            }
        }

        // ---------- 7. faíscas / ejeções ----------
        acumFai += dt * w3 * Math.max(0f, lvl - 0.3f) * 30f;       // garoa contínua em voz forte
        while (acumFai >= 1f) { soltaFaiscas(lvl, 1); acumFai -= 1f; }
        float arrasto = (float) Math.exp(-dt * 2.4f);
        for (int b = 0; b < NFV; b++) nF[b] = 0;
        int nc = 0;
        for (int i = 0; i < FAI; i++) {
            if (fav[i] <= 0f) continue;
            fax[i] += fvx[i] * dt; fay[i] += fvy[i] * dt; faz[i] += fvz[i] * dt;
            fvx[i] *= arrasto; fvy[i] *= arrasto; fvz[i] *= arrasto;
            fav[i] -= dt * fdec[i];
            if (fav[i] <= 0f) continue;
            float pr = DC / Math.max(1.2f, DC - faz[i]) * R0, hx = fax[i] * pr, hy = fay[i] * pr;
            float zt = faz[i] - fvz[i] * 0.07f, pr2 = DC / Math.max(1.2f, DC - zt) * R0;
            float tx = (fax[i] - fvx[i] * 0.07f) * pr2, ty = (fay[i] - fvy[i] * 0.07f) * pr2;
            float ef = Math.min(1f, (cy - Math.abs(hy)) * fBy) * Math.min(1f, (cx - Math.abs(hx)) * fBx);   // some antes da borda
            if (ef <= 0.05f) { fav[i] = 0f; continue; }
            int b = (int) (fav[i] * ef * NFV); if (b >= NFV) b = NFV - 1;
            float[] bf = bufF[b]; int n = nF[b];
            bf[n] = tx; bf[n + 1] = ty; bf[n + 2] = hx; bf[n + 3] = hy; nF[b] = n + 4;
            if (fav[i] * ef > 0.5f) { bufFC[nc] = hx; bufFC[nc + 1] = hy; nc += 2; }
        }
        for (int b = 0; b < NFV; b++) {
            if (nF[b] == 0) continue;
            float f = (b + 0.5f) / NFV, g = f * f;
            pF[b].setColor(argb(255 * f * inten, LR + (GR - LR) * g, LG + (GG - LG) * g, LB + (GB - LB) * g));
            pF[b].setStrokeWidth(u * (0.8f + 1.4f * f));
            cv.drawLines(bufF[b], 0, nF[b], pF[b]);
        }
        if (nc > 0) { pFaiC.setStrokeWidth(u * 1.8f); pFaiC.setColor(argb(220, 255, 240, 220)); cv.drawPoints(bufFC, 0, nc, pFaiC); }

        // ---------- 8. onda de choque ao mudar de estado ----------
        if (onda > -0.2f) {
            onda -= dt * 1.6f;
            for (int q = 0; q < 2; q++) {
                float p = 1f - onda - q * 0.16f;
                if (p <= 0f || p >= 1f) continue;
                float v = 1f - p;
                pOnda.setStrokeWidth(u * (0.6f + 3f * v));
                pOnda.setColor(q == 0 ? argb(210 * v * v * inten, GR, GG, GB) : argb(170 * v * v * inten, tr, tg, tb));
                cv.drawCircle(0, 0, Math.min(Rp * (1.05f + 1.1f * p), cy * 0.96f), pOnda);
            }
        }

        cv.restore();
        postInvalidateOnAnimation();
    }

    /** ejeta n faíscas da superfície em direções da esfera (sem alocar) */
    private void soltaFaiscas(float forca, int n) {
        for (int i = 0; i < FAI && n > 0; i++) {
            if (fav[i] > 0f) continue;
            int k = rnd.nextInt(N);
            float ux = dx[k], uy = dy[k], uz = dz[k], v = 1.4f + 2.6f * forca + rnd.nextFloat() * 1.2f, r0 = raio * 1.02f;
            fax[i] = ux * r0; fay[i] = uy * r0; faz[i] = uz * r0;
            fvx[i] = ux * v + (rnd.nextFloat() - 0.5f) * 0.6f; fvy[i] = uy * v + (rnd.nextFloat() - 0.5f) * 0.6f; fvz[i] = uz * v;
            fav[i] = 1f; fdec[i] = 0.9f + rnd.nextFloat() * 0.9f;
            n--;
        }
    }
}
