package dev.integra.friday;

import android.app.ActivityManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.BitmapShader;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffXfermode;
import android.graphics.RadialGradient;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.SweepGradient;
import android.graphics.Typeface;
import android.net.TrafficStats;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.PowerManager;
import android.os.StatFs;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.FileReader;
import java.io.InputStream;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Random;

/** Cena do papel de parede ao vivo (Stark HUD âmbar): Mark 85 girando com crossfade (quadros sob demanda num cache de 6), piso em perspectiva,
 *  pedestal holográfico com oclusão, reflexo, varredura com rótulos, brasas com paralaxe, relógio, telemetria e atalhos.
 *  Não depende do Engine: o Papel (ao vivo) e a rota /papel_png (síncrona, teste) usam a mesma cena. Zero alocação por quadro no desenho. */
final class PapelCena {
    static final String TAG = "FridayPapel";
    static final String[][] ATALHOS = {{"ASSIST", "assistente"}, {"CHAT", "conversa"}, {"VNC", "vnc"}, {"CÂMERAS", "cameras"},
        {"MODOS", "controles"}, {"AGENDA", "agenda"}, {"DEV", "dev"}};

    // ======================= AJUSTES DE LAYOUT (frações de W/H; dp/sp onde indicado) =======================
    // RETRATO
    static final float R_ARM_TOPO = 0.158f, R_ARM_ALT = 0.494f;                                   // armadura: topo e altura (de H)
    static final float R_HORIZ = 0.062f, R_PED_RX = 0.27f, R_PED_ACH = 0.2f, R_REFLEXO = 0.1f, R_COLUNA = 0.22f; // horizonte acima dos pés, pedestal (rx de W, ry/rx), reflexo, coluna de luz
    static final float R_REL_Y = 0.092f, R_DATA_Y = 0.114f, R_CHIP_Y = 0.133f, R_PROX_Y = 0.153f; // relógio (baseline), data, chips (centro), próximo
    static final float R_PAINEL_Y0 = 0.683f, R_PAINEL_Y1 = 0.813f, R_DOCK_Y = 0.848f, R_REL_SP = 84f; // cartão de métricas, centro dos atalhos (acima do dock do launcher, que ocupa de ~0.897H para baixo)
    // PAISAGEM
    static final float P_BUSTO_ALT = 0.92f, P_BUSTO_CX = 0.25f, P_CORTE = 0.5f;                   // busto (altura de H, centro x de W); recorte do corpo sem busto
    static final float P_COL_X0 = 0.51f, P_COL_X1 = 0.975f, P_REL_Y = 0.19f, P_DATA_Y = 0.245f, P_CHIP_Y = 0.295f, P_PROX_Y = 0.36f;
    static final float P_PAINEL_Y0 = 0.40f, P_PAINEL_Y1 = 0.75f, P_DOCK_Y = 0.85f, P_REL_SP = 64f;
    // COMUNS
    static final float MARGEM_DP = 14f, BOTAO_DP = 44f, FLUTUA_DP = 4f;
    static final float GRAUS_S = 12f, GRAUS_PAG = 120f, VARRE_PER = 7f, VARRE_DUR = 2.2f, ROT_DUR = 2.5f, ONDA_PER = 3.5f;
    static final int NB = 140, NCACHE = 6, NQ = 240;              // NQ = quadros por volta (assets/papel/*/f000..f239, 1,5° cada)
    static final float PASSO = 360f / NQ;
    // TEMA
    static final int LARANJA = 0xffff7700, LARANJA2 = 0xffff9d24, DOURADO = 0xffffc36b, BRANCO = 0xfffff3e6, FUNDO = 0xff070402, ALERTA = 0xffff5a6e, OK = 0xff3dff9a;

    private static final String[] ROT_TX = {"HUD · F.R.I.D.A.Y.", "REATOR ARC · 100%", "REPULSOR · PRONTO", "NANOTECH · 98%"};
    private static final float[] ROT_DY = {10f, -62f, 44f, 44f};                // dp: altura da linha do rótulo em relação à âncora
    private static final String[] G_ROT = {"CPU", "RAM", "DISCO", "BAT"};
    private static final String[] TERM = {"NORMAL", "LEVE", "MODERADO", "SEVERO", "CRÍTICO", "CRÍTICO", "CRÍTICO"};
    private static final int[] TERM_COR = {OK, DOURADO, LARANJA2, ALERTA, ALERTA, ALERTA, ALERTA};
    private static final int[][] ORDEM = {{0, 1, 2, 3, -1}, {0, 1, -1, -2, -3}};  // pré-decodificação no sentido da rotação
    private static final String[] D2 = new String[100], PCT = new String[101];
    static { for (int i = 0; i < 100; i++) D2[i] = (i < 10 ? "0" : "") + i; for (int i = 0; i <= 100; i++) PCT[i] = i + "%"; }
    private static final Locale PT = Locale.forLanguageTag("pt-BR");
    private static final PorterDuffXfermode ADD = new PorterDuffXfermode(PorterDuff.Mode.ADD), DST_IN = new PorterDuffXfermode(PorterDuff.Mode.DST_IN),
        SRC_ATOP = new PorterDuffXfermode(PorterDuff.Mode.SRC_ATOP);

    /** fonte de quadros (corpo/busto) com pontos normalizados no quadro f00 */
    private static final class Fonte {
        final String dir; final String[] nomes = new String[NQ]; int w = 665, h = 1130; float corte = 1f, px = .5f, py = .235f, ox = .5f, oy = .06f,
            m0x = .08f, m0y = .49f, m1x = .93f, m1y = .49f, pes = .985f;
        Fonte(String d) { dir = d; for (int k = 0; k < NQ; k++) nomes[k] = d + String.format(java.util.Locale.ROOT, "/f%03d.webp", k); }
        Fonte copia(float c) { Fonte f = new Fonte(dir); f.w = w; f.h = h; f.corte = c; f.px = px; f.py = py; f.ox = ox; f.oy = oy; f.m0x = m0x; f.m0y = m0y; f.m1x = m1x; f.m1y = m1y; f.pes = pes; return f; }
    }

    /** instantâneo das métricas (montado na thread de métricas, nunca alterado depois de publicado) */
    static final class Metricas {
        float cpu, ghz, ram, disco, bat, temp; final float[] nuc = new float[8]; int nNuc, termico = -1, pc = -1; boolean carregando, batOk;
        long ramUsado, ramTotal, discoLivre, rx = -1, tx = -1, uptime, ts; float[] hist = new float[0]; String proxTitulo; long proxIni, proxFim;
    }
    private static final class Prox { final String titulo; final long ini, fim; Prox(String t, long i, long f) { titulo = t; ini = i; fim = f; } }

    private final Context c; private final boolean sinc; private final float dp, sp; private final long base;
    private Fonte corpo, corpoBusto, busto, fonte; private volatile Fonte fonteQ;
    private int W, H; private boolean deitado, eco; private volatile boolean liberado;
    private Bitmap fundo; private final Bitmap[] spr = new Bitmap[4]; private Bitmap linhas;

    // ---- cache de quadros (trava protege cIdx/cBmp/uso0/uso1/geracao)
    private final Object trava = new Object();
    private final Bitmap[] cBmp = new Bitmap[NCACHE]; private final int[] cIdx = {-1, -1, -1, -1, -1, -1};
    private int uso0 = -1, uso1 = -1, geracao, pedidoPostado = -1; private volatile int pedido, sentido = 1;
    private final BitmapFactory.Options opc = new BitmapFactory.Options();
    private HandlerThread tQ, tM, tL; private Handler hQ, hM, hL; private volatile boolean ativo;

    // ---- estado de animação (só a thread de desenho)
    private double tUlt = -1; private float angUlt, deslAlvo = .5f, deslS = .5f, incXA, incYA, incXS, incYS, angForcado = Float.NaN;
    private final float[] rpX = new float[4], rpY = new float[4]; private final double[] rpT = {-9, -9, -9, -9}; private int rpN;

    // ---- layout (calculado em tamanho())
    private float armW, armH, armCx, armT0, pesY, pedRx, pedRy, reflH, colH, relX, relY, dataY, chipY, proxY, proxMaxW, colX0, colX1, rotL, rotR,
        gR, cabY, txX, txY, txPasso, dR, dCel, icoK, bandaH, interfH, varreX1;
    private boolean centro;
    private final RectF rArm = new RectF(), rArmCam = new RectF(), rRefl = new RectF(), rPainel = new RectF(), rSpark = new RectF(), rNuc = new RectF(),
        ov = new RectF(), ov2 = new RectF(), dst = new RectF();
    private final Rect src = new Rect();
    private final float[] gCx = new float[4], gCy = new float[4], dCx = new float[7], dCy = new float[7], gVal = new float[4], gAlvo = new float[4], nVal = new float[8];
    private final RectF[] gOv = {new RectF(), new RectF(), new RectF(), new RectF()};
    private float[] gTicks = new float[0], cantos = new float[0], grade = new float[0];
    private final float[] buf = new float[64 * 4], colch = new float[16];
    private final Path[] icone = new Path[7]; private final Bitmap[] feixeB = new Bitmap[3]; private final RectF[] feixeR = {new RectF(), new RectF(), new RectF()};
    private final Path pathSpark = new Path(), pathArea = new Path(); private float sparkPasso, sparkUltY = -1;
    private final Matrix mRefl = new Matrix();

    // ---- textos (recalculados só quando mudam)
    private final Calendar cal = Calendar.getInstance(), calP = Calendar.getInstance();
    private final SimpleDateFormat fData = new SimpleDateFormat("EEEE  ·  d 'de' MMMM", PT);
    private long segUlt = -1; private int minUlt = -1, diaUlt = -1;
    private String horaTx = "", segTx = "00", dataTx = "", proxPre = "AGENDA", proxTx = " · ···", upTx = "UPTIME —", rxTx = "↓ —", txTx = "↑ —", tempTx = "TEMP —", termTx = "";
    private final String[] gSub = {"", "", "", ""}; private int termCor = DOURADO; private float horaW, proxPreW, proxTxW, tempW, rotW[] = new float[4];
    private final float[] chipW = new float[5], subMax = new float[4], subK = {1, 1, 1, 1}, rotGK = {1, 1, 1, 1}; private float txXd, txK = 1, txKV = 1;
    private Metricas mUlt; private volatile Metricas met;

    // ---- partículas (estado sem integração: posição = função do tempo)
    private final float[] bX = new float[NB], bY = new float[NB], bV = new float[NB], bA = new float[NB], bF = new float[NB], bFase = new float[NB],
        bT = new float[NB], bAl = new float[NB], bS = new float[NB];
    private final int[] bProf = new int[NB], bCor = new int[NB]; private final int[] profIni = new int[4];

    // ---- tintas (shaders criados em tamanho())
    private final Paint pFundo = new Paint(Paint.FILTER_BITMAP_FLAG), pImg = tinta(0xffffffff, null), pRefl = tinta(0xffffffff, null), pBrasa = tinta(0xffffffff, ADD),
        pMascRefl = tinta(0xff000000, DST_IN), pMascBusto = tinta(0xff000000, DST_IN), pBanda = tinta(0xffffffff, SRC_ATOP), pBandaLinha = tinta(BRANCO, SRC_ATOP),
        pColuna = tinta(0xffffffff, ADD), pHalo = tinta(0xffffffff, ADD), pBrilho = tinta(0xffffffff, ADD), pDisco = tinta(0xffffffff, ADD), pGlow = tinta(0xffffffff, ADD),
        pLinhas = tinta(0xffffffff, null), pInterf = tinta(0xffffffff, ADD), pVarreLinha = tinta(0xffffffff, ADD), pVarreBrilho = tinta(0xffffffff, ADD),
        pVidro = tinta(0xa60d0804, null), pVidroBrilho = tinta(0xffffffff, null), pArea = tinta(0xffffffff, null), pPreen = tinta(0xffffffff, null), pPonto = tinta(0xffffffff, ADD);
    private final Paint[] pFeixe = {tinta(0xffffffff, ADD), tinta(0xffffffff, ADD), tinta(0xffffffff, ADD)},
        pArcoG = {traco(0xffffffff, 1, null), traco(0xffffffff, 1, null), traco(0xffffffff, 1, null), traco(0xffffffff, 1, null)};
    private final Paint pTraco = traco(LARANJA2, 1, ADD), pTracoN = traco(LARANJA2, 1, null), pIcone = traco(DOURADO, 1.6f, null), pSpark = traco(LARANJA2, 1, null),
        pArcoBr = traco(LARANJA2, 1, ADD);
    private final Paint pRel, pSeg, pData, pChip, pProx, pProxPre, pRot, pVal, pMini, pSub, pTx, pIcoTx, pCab;

    PapelCena(Context ctx, boolean sincrono) {
        c = ctx; sinc = sincrono; DisplayMetrics dm = ctx.getResources().getDisplayMetrics(); dp = dm.density; sp = Math.min(dm.scaledDensity > 0 ? dm.scaledDensity : dm.density, dm.density * 1.15f);   // fonte grande do sistema não estoura o layout
        base = sincrono ? 0L : System.nanoTime();
        Typeface fino = Typeface.create("sans-serif-thin", Typeface.NORMAL), cond = Typeface.create("sans-serif-condensed", Typeface.NORMAL),
            medio = Typeface.create("sans-serif-medium", Typeface.NORMAL), mono = Typeface.create("monospace", Typeface.NORMAL);
        pRel = texto(BRANCO, R_REL_SP, fino, 0.02f); pRel.setShadowLayer(14 * dp, 0, 0, 0xc0ff7700);
        pSeg = texto(LARANJA2, 15, cond, 0.1f); pSeg.setShadowLayer(6 * dp, 0, 0, 0x90ff7700);
        pData = texto(DOURADO, 11, medio, 0.28f); pData.setShadowLayer(5 * dp, 0, 0, 0x80ff7700);
        pChip = texto(BRANCO, 9, medio, 0.14f); pProx = texto(BRANCO, 11, cond, 0.06f); pProxPre = texto(LARANJA2, 11, medio, 0.16f);
        pProx.setShadowLayer(4 * dp, 0, 0, 0xa0000000); pProxPre.setShadowLayer(5 * dp, 0, 0, 0x90ff7700);
        pRot = texto(BRANCO, 10, medio, 0.14f); pRot.setShadowLayer(5 * dp, 0, 0, 0xb0ff7700);
        pVal = texto(BRANCO, 13, cond, 0.02f); pVal.setTextAlign(Paint.Align.CENTER);
        pMini = texto(DOURADO, 8.5f, medio, 0.2f);
        pSub = texto(0xc0ffe6cc, 8.5f, cond, 0.02f);
        pTx = texto(0xe6fff3e6, 9, mono, 0f); pCab = texto(DOURADO, 8, medio, 0.3f);
        pIcoTx = texto(0xd8ffe0bf, 7.5f, medio, 0.16f); pIcoTx.setTextAlign(Paint.Align.CENTER);
        pIcone.setStrokeJoin(Paint.Join.ROUND);
        for (int i = 0; i < 4; i++) rotW[i] = pRot.measureText(ROT_TX[i]);
        String[] ct = {"PC ONLINE", "PC OFFLINE", "PC ···", "CARREGANDO", "MARK 85"}; for (int i = 0; i < 5; i++) chipW[i] = pChip.measureText(ct[i]);   // medidas fixas: nada de measureText por quadro
        lerInfo(); fonte = corpo; fonteQ = corpo;
        iniciarBrasas(); criarSprites(); criarIcones();
        if (!sinc) {
            tQ = new HandlerThread("papel-quadros", android.os.Process.THREAD_PRIORITY_DEFAULT); tQ.start(); hQ = new Handler(tQ.getLooper());
            tM = new HandlerThread("papel-metricas", android.os.Process.THREAD_PRIORITY_BACKGROUND); tM.start(); hM = new Handler(tM.getLooper());
            tL = new HandlerThread("papel-rede", android.os.Process.THREAD_PRIORITY_BACKGROUND); tL.start(); hL = new Handler(tL.getLooper());
        }
    }

    private static Paint tinta(int cor, PorterDuffXfermode x) { Paint p = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG | Paint.DITHER_FLAG); p.setColor(cor); if (x != null) p.setXfermode(x); return p; }
    private static Paint traco(int cor, float w, PorterDuffXfermode x) { Paint p = tinta(cor, x); p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(w); p.setStrokeCap(Paint.Cap.ROUND); return p; }
    private Paint texto(int cor, float tamSp, Typeface tf, float esp) { Paint p = tinta(cor, null); p.setTextSize(tamSp * sp); p.setTypeface(tf); p.setLetterSpacing(esp); p.setSubpixelText(true); return p; }

    // =============================================== API ===============================================
    void deslocamento(float x) { if (!Float.isNaN(x)) deslAlvo = Math.max(0f, Math.min(1f, x)); if (sinc) deslS = deslAlvo; }
    void inclinacao(float x, float y) { if (Float.isNaN(x) || Float.isNaN(y)) return; incXA = Math.max(-1f, Math.min(1f, x)); incYA = Math.max(-1f, Math.min(1f, y)); if (sinc) { incXS = incXA; incYS = incYA; } }
    void forcarAngulo(float graus) { if (!Float.isInfinite(graus)) angForcado = graus; }
    void economia(boolean e) { eco = e; }
    void toque(float x, float y) { int k = rpN++ & 3; rpX[k] = x; rpY[k] = y; rpT[k] = tUlt < 0 ? 0 : tUlt; }

    int alvoEm(float x, float y) {
        if (W == 0) return -1;
        for (int i = 0; i < 7; i++) { float dx = Math.abs(x - dCx[i]), dy = y - dCy[i]; if (dx <= Math.min(dCel * 0.5f, dR * 1.5f) && dy >= -dR * 1.35f && dy <= dR + 16 * dp) return i; }
        return -1;
    }

    /** liga/desliga as threads de métricas (o desenho só acontece visível; a de quadros fica ociosa sem pedidos) */
    void ativo(boolean v) {
        if (sinc || liberado) return; ativo = v;
        hM.removeCallbacks(rMet); hL.removeCallbacks(rLento);
        if (v) { hL.post(rLento); hM.post(rMet); }
    }

    void amostrarMetricasJa() {
        try { lento(true); } catch (Throwable e) { Log.w(TAG, "lento", e); }
        try { amostrar(); SystemClock.sleep(250); amostrar(); } catch (Throwable e) { Log.w(TAG, "métricas", e); }
    }

    void liberar() {
        liberado = true; ativo = false;
        if (hQ != null) { hQ.removeCallbacksAndMessages(null); hM.removeCallbacksAndMessages(null); hL.removeCallbacksAndMessages(null); tQ.quitSafely(); tM.quitSafely(); tL.quitSafely(); }
        synchronized (trava) { for (int k = 0; k < NCACHE; k++) { cIdx[k] = -1; if (cBmp[k] != null && sinc) cBmp[k].recycle(); cBmp[k] = null; } }
        if (sinc && fundo != null) fundo.recycle(); fundo = null;
    }

    void tamanho(int w, int h) {
        if (w <= 0 || h <= 0 || (w == W && h == H && fundo != null)) return;
        W = w; H = h; deitado = w > h;
        Fonte nova = deitado ? (busto != null ? busto : corpoBusto) : corpo;
        if (fonte == null || !nova.dir.equals(fonte.dir)) synchronized (trava) { geracao++; for (int k = 0; k < NCACHE; k++) cIdx[k] = -1; }
        fonte = nova; fonteQ = nova; pedidoPostado = -1; mUlt = null; segUlt = -1; minUlt = -1; diaUlt = -1;
        layout(); criarShaders();
        fundo = null; try { fazerFundo(); } catch (Throwable e) { Log.w(TAG, "fundo", e); fundo = null; }
    }

    // =============================================== DESENHO ===============================================
    void desenhar(Canvas cv, long agoraNanos) {
        if (W == 0) { cv.drawColor(FUNDO); return; }
        double t = (agoraNanos - base) / 1e9; float dt = tUlt < 0 ? 1f : (float) Math.max(0, Math.min(0.25, t - tUlt)); tUlt = t;
        float kS = sinc ? 1f : 1f - (float) Math.exp(-dt * 5f);
        deslS += (deslAlvo - deslS) * kS; incXS += (incXA - incXS) * kS; incYS += (incYA - incYS) * kS;
        double angD = !Float.isNaN(angForcado) ? angForcado : GRAUS_S * t + (deslS - 0.5f) * GRAUS_PAG;
        float ang = (float) (((angD % 360.0) + 360.0) % 360.0), co = (float) Math.cos(Math.toRadians(ang));
        // ---- quadros: q0 = floor(ang/5), q1 = q0+1 com alpha = fração
        float a5 = ang / PASSO; int i0 = ((int) Math.floor(a5)) % NQ, i1 = (i0 + 1) % NQ; float fr = a5 - (float) Math.floor(a5);
        float da = ang - angUlt; if (da > 180) da -= 360; if (da < -180) da += 360; angUlt = ang; if (Math.abs(da) > 0.02f) sentido = da > 0 ? 1 : -1;
        pedido = i0;
        if (sinc) { carregar(i0); if (fr > 0.004f) carregar(i1); }
        else if (i0 != pedidoPostado && hQ != null) { pedidoPostado = i0; hQ.removeCallbacks(rQuadros); hQ.post(rQuadros); }
        Bitmap b0 = null, b1 = null;
        synchronized (trava) {
            int s0 = -1, s1 = -1, melhor = 99;
            for (int k = 0; k < NCACHE; k++) { int q = cIdx[k]; if (q == i0) s0 = k; else if (q == i1) s1 = k; }
            if (s0 < 0) { s1 = -1; for (int k = 0; k < NCACHE; k++) { int q = cIdx[k]; if (q < 0) continue; int d = dist(q, i0); if (d < melhor) { melhor = d; s0 = k; } } }
            uso0 = s0; uso1 = s1; if (s0 >= 0) b0 = cBmp[s0]; if (s1 >= 0) b1 = cBmp[s1];
        }
        if (b0 != null && b0.isRecycled()) b0 = null; if (b1 != null && b1.isRecycled()) b1 = null;
        // ---- métricas e textos
        Metricas m = met; if (m != mUlt) { mUlt = m; refazMet(m); segUlt = -1; }
        relogio();
        for (int i = 0; i < 4; i++) gVal[i] += (gAlvo[i] - gVal[i]) * (sinc ? 1f : 1f - (float) Math.exp(-dt * 4f));
        // ---- paralaxe: página (deslocamento) + inclinação, proporcional à profundidade
        float pagX = -(deslS - 0.5f) * W * 0.1f, inX = incXS * 16 * dp, inY = incYS * 10 * dp;
        float flut = (float) Math.sin(t * Math.PI / 3.0) * FLUTUA_DP * dp, ox = (pagX + inX) * 0.28f, oy = flut + inY * 0.28f;
        rArm.set(armCx - armW / 2 + ox, armT0 + oy, armCx + armW / 2 + ox, armT0 + oy + armH);
        rArmCam.set(rArm.left - 2 * dp, rArm.top - 2 * dp, rArm.right + 2 * dp, deitado ? H + 8 * dp : rArm.bottom + 2 * dp);
        double vs = t % VARRE_PER; float uV = vs < VARRE_DUR ? (float) (vs / VARRE_DUR) : -1f;

        if (fundo != null) cv.drawBitmap(fundo, 0, 0, pFundo); else cv.drawColor(FUNDO);
        feixes(cv, t);
        brasas(cv, t, 0, pagX, inX, inY); brasas(cv, t, 1, pagX, inX, inY);
        halo(cv, t, co);
        if (!deitado) { reflexo(cv, b0, b1, fr); pedestal(cv, t, false, ox); } else aneis(cv, t, co);
        armadura(cv, b0, b1, fr, uV);
        if (!deitado) pedestal(cv, t, true, ox);
        if (b0 != null) brilhos(cv, t, co);
        if (b0 != null) varredura(cv, vs, uV, ang);
        brasas(cv, t, 2, pagX, inX, inY);
        cv.drawRect(0, 0, W, H, pLinhas);
        float yi = (float) ((t % 9.0) / 9.0) * (H + 2 * interfH) - interfH; cv.save(); cv.translate(0, yi); cv.drawRect(0, -interfH, W, interfH, pInterf); cv.restore();
        hud(cv, t);
        painel(cv, t, m);
        dock(cv, t);
        ondas(cv, t);
    }

    private void glow(Canvas cv, float x, float y, float r, Paint p) { cv.save(); cv.translate(x, y); cv.scale(r / 100f, r / 100f); cv.drawCircle(0, 0, 100, p); cv.restore(); }
    private float px(float nx, float co) { return rArm.left + (0.5f + (nx - 0.5f) * co) * rArm.width(); }
    private float py(float ny) { return rArm.top + ny / fonte.corte * rArm.height(); }
    private static float lim(float v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }
    private static int a8(double v) { return v <= 0 ? 0 : (v >= 255 ? 255 : (int) v); }

    private void feixes(Canvas cv, double t) {
        for (int i = 0; i < 3; i++) { if (feixeB[i] == null) continue; pFeixe[i].setAlpha(a8(255 * (0.5 + 0.35 * Math.sin(t * 0.85 + i * 2.1) + 0.15 * Math.sin(t * 2.3 + i)))); cv.drawBitmap(feixeB[i], null, feixeR[i], pFeixe[i]); }
    }

    private void brasas(Canvas cv, double t, int prof, float pagX, float inX, float inY) {
        float k = prof == 0 ? 0.22f : (prof == 1 ? 0.55f : 1f), offX = (pagX + inX) * k, offY = inY * k, mg = 40 * dp, span = H + 2 * mg;
        for (int i = profIni[prof]; i < profIni[prof + 1]; i++) {
            if (eco && (i & 1) == 1) continue;
            float yy = (float) ((bY[i] * span + bV[i] * H * t) % span), y = H + mg - yy + offY;
            float x = bX[i] * W + bA[i] * dp * (float) Math.sin(bF[i] * t + bFase[i]) + offX; x = ((x % W) + W) % W;
            float u = y / H, fade = lim(u * 2.4f) * lim((1.04f - u) * 8f), tw = 0.55f + 0.45f * (float) Math.sin(bT[i] * t + bFase[i] * 3.1);
            int al = (int) (bAl[i] * fade * tw); if (al < 3) continue;
            float r = bS[i] * dp * 3.2f; dst.set(x - r, y - r, x + r, y + r); pBrasa.setAlpha(al); cv.drawBitmap(spr[bCor[i]], null, dst, pBrasa);
        }
    }

    private void halo(Canvas cv, double t, float co) {
        float pul = 0.5f + 0.5f * (float) Math.sin(t * 1.6);
        float x = px(fonte.px, 1f), y = deitado ? py(fonte.py) : py(fonte.py + 0.08f), r = armW * (deitado ? 0.62f : 0.72f) * (0.94f + 0.08f * pul);
        pHalo.setAlpha(a8(150 + 70 * pul)); glow(cv, x, y, r, pHalo);
    }

    private void reflexo(Canvas cv, Bitmap b0, Bitmap b1, float fr) {
        if (b0 == null) return;
        rRefl.set(rArm.left - 4 * dp, pesY, rArm.right + 4 * dp, pesY + reflH);
        int sl = cv.saveLayer(rRefl, null);
        float sx = rArm.width() / b0.getWidth(), sy = rArm.height() / (b0.getHeight() * fonte.corte);
        mRefl.setScale(sx, -sy); mRefl.postTranslate(rArm.left, 2 * pesY - rArm.top);
        pRefl.setAlpha(50); cv.drawBitmap(b0, mRefl, pRefl);
        if (b1 != null && fr > 0.01f) { pRefl.setAlpha(a8(50 * fr)); cv.drawBitmap(b1, mRefl, pRefl); }
        cv.drawRect(rRefl, pMascRefl);
        cv.restoreToCount(sl);
    }

    /** pedestal holográfico: metade de trás antes da armadura, metade da frente depois (oclusão 3D) */
    private void pedestal(Canvas cv, double t, boolean frente, float ox) {
        float cx = armCx + ox, cy = pesY, rx = pedRx, ry = pedRy, ini = frente ? 0f : 180f, pul = 0.82f + 0.18f * (float) Math.sin(t * 2.4);
        if (!frente) {
            cv.save(); cv.translate(cx, cy); cv.scale(rx * 0.62f / 100f, colH / 100f); pColuna.setAlpha(a8(200 * pul)); cv.drawRect(-100, -100, 100, 0, pColuna); cv.restore();
            cv.save(); cv.translate(cx, cy); cv.scale(rx * 0.55f / 100f, ry * 0.55f / 100f); pDisco.setAlpha(a8(235 * pul)); cv.drawCircle(0, 0, 100, pDisco); cv.restore();
        }
        float fa = frente ? 1.2f : 0.85f;
        for (int k = 0; k < 4; k++) {
            float e = k == 0 ? 1f : (k == 1 ? 0.8f : (k == 2 ? 0.6f : 0.36f));
            ov.set(cx - rx * e, cy - ry * e, cx + rx * e, cy + ry * e);
            pTraco.setStrokeWidth((k == 0 ? 1.6f : 1f) * dp); pTraco.setColor(k == 3 ? DOURADO : LARANJA2); pTraco.setAlpha(a8(Math.min(255, (k == 0 ? 170 : 110) * fa * pul)));
            cv.drawArc(ov, ini, 180, false, pTraco);
        }
        // segmentos que giram (anel médio, horário) e (anel interno, anti-horário)
        ov.set(cx - rx * 0.8f, cy - ry * 0.8f, cx + rx * 0.8f, cy + ry * 0.8f); pTraco.setStrokeWidth(3.2f * dp); pTraco.setColor(LARANJA2); pTraco.setAlpha(a8(150 * fa));
        float a0 = (float) ((t * 26) % 360); for (int s = 0; s < 5; s++) arcoMetade(cv, ov, a0 + s * 72, 30, frente, pTraco);
        ov.set(cx - rx * 0.6f, cy - ry * 0.6f, cx + rx * 0.6f, cy + ry * 0.6f); pTraco.setStrokeWidth(2f * dp); pTraco.setColor(DOURADO); pTraco.setAlpha(a8(160 * fa));
        a0 = (float) ((-t * 40) % 360); for (int s = 0; s < 3; s++) arcoMetade(cv, ov, a0 + s * 120, 50, frente, pTraco);
        // marcações correndo pela elipse externa
        int n = 0; double fase = (t * 0.32) % (2 * Math.PI);
        for (int i = 0; i < 64; i++) {
            double th = fase + i * (2 * Math.PI / 64); float s = (float) Math.sin(th); if ((s >= 0) != frente) continue;
            float cs = (float) Math.cos(th), L = (i % 8 == 0) ? 1.12f : 1.05f;
            buf[n++] = cx + cs * rx * 1.015f; buf[n++] = cy + s * ry * 1.015f; buf[n++] = cx + cs * rx * L; buf[n++] = cy + s * ry * L;
        }
        pTraco.setStrokeWidth(1.2f * dp); pTraco.setColor(DOURADO); pTraco.setAlpha(a8(190 * fa)); if (n > 0) cv.drawLines(buf, 0, n, pTraco);
        // onda que se expande a cada ONDA_PER s
        double fo = (t % ONDA_PER) / ONDA_PER; float e = 0.3f + 1.05f * (float) fo;
        ov.set(cx - rx * e, cy - ry * e, cx + rx * e, cy + ry * e); pTraco.setStrokeWidth((2.6f - 1.8f * (float) fo) * dp); pTraco.setColor(LARANJA2);
        pTraco.setAlpha(a8(230 * Math.pow(1 - fo, 1.6) * fa)); cv.drawArc(ov, ini, 180, false, pTraco);
    }

    /** desenha a parte do arco [a, a+len] que cai na metade pedida (trás = 180..360, frente = 0..180) */
    private static void arcoMetade(Canvas cv, RectF o, float a, float len, boolean frente, Paint p) {
        float h0 = frente ? 0f : 180f; a = ((a % 360) + 360) % 360; float a1 = a + len;
        for (int k = 0; k <= 1; k++) { float lo = Math.max(a, h0 + 360 * k), hi = Math.min(a1, h0 + 180 + 360 * k); if (hi > lo) cv.drawArc(o, lo, hi - lo, false, p); }
    }

    /** paisagem: anéis de HUD girando atrás do peito e da cabeça */
    private void aneis(Canvas cv, double t, float co) {
        float cx = px(fonte.px, 1f), cy = py(fonte.py), R = H * 0.33f;
        pTraco.setColor(LARANJA2);
        ov.set(cx - R, cy - R, cx + R, cy + R); pTraco.setStrokeWidth(1f * dp); pTraco.setAlpha(60); cv.drawOval(ov, pTraco);
        pTraco.setStrokeWidth(3f * dp); pTraco.setAlpha(150); float a0 = (float) ((t * 14) % 360);
        for (int s = 0; s < 3; s++) cv.drawArc(ov, a0 + s * 120, 64, false, pTraco);
        float R2 = R * 1.13f; int n = 0; double f2 = Math.toRadians(-t * 8);
        for (int i = 0; i < 60; i++) { double th = f2 + i * Math.PI / 30; float cs = (float) Math.cos(th), sn = (float) Math.sin(th), L = i % 5 == 0 ? 1.05f : 1.025f;
            buf[n++] = cx + cs * R2; buf[n++] = cy + sn * R2; buf[n++] = cx + cs * R2 * L; buf[n++] = cy + sn * R2 * L; }
        pTraco.setStrokeWidth(1.1f * dp); pTraco.setColor(DOURADO); pTraco.setAlpha(120); cv.drawLines(buf, 0, n, pTraco);
        float R3 = R * 0.8f; ov.set(cx - R3, cy - R3, cx + R3, cy + R3); pTraco.setColor(LARANJA2); pTraco.setStrokeWidth(1.4f * dp); pTraco.setAlpha(90);
        a0 = (float) ((-t * 30) % 360); cv.drawArc(ov, a0, 200, false, pTraco); pTraco.setStrokeWidth(4f * dp); pTraco.setAlpha(170); cv.drawArc(ov, a0 + 230, 18, false, pTraco);
        float hx = px(fonte.ox, 1f), hy = py(fonte.oy), r = H * 0.1f; ov.set(hx - r, hy - r, hx + r, hy + r);
        pTraco.setColor(DOURADO); pTraco.setStrokeWidth(1.2f * dp); pTraco.setAlpha(110); a0 = (float) ((t * 45) % 360);
        for (int s = 0; s < 4; s++) cv.drawArc(ov, a0 + s * 90, 52, false, pTraco);
    }

    private void armadura(Canvas cv, Bitmap b0, Bitmap b1, float fr, float uV) {
        if (b0 == null) return;
        boolean camada = deitado || uV >= 0; int sl = camada ? cv.saveLayer(rArmCam, null) : -1;
        src.set(0, 0, b0.getWidth(), Math.round(b0.getHeight() * fonte.corte));
        pImg.setAlpha(255); cv.drawBitmap(b0, src, rArm, pImg);
        if (b1 != null && fr > 0.004f) { src.set(0, 0, b1.getWidth(), Math.round(b1.getHeight() * fonte.corte)); pImg.setAlpha(a8(255 * fr)); cv.drawBitmap(b1, src, rArm, pImg); }
        if (uV >= 0) {                                            // faixa da varredura tinge só os pixels da armadura (SRC_ATOP)
            float y = varreY(uV); cv.save(); cv.translate(0, y); cv.drawRect(rArmCam.left, -bandaH, rArmCam.right, 0, pBanda); cv.restore();
            pBandaLinha.setAlpha(a8(235 * env(uV))); cv.drawRect(rArmCam.left, y - 1.4f * dp, rArmCam.right, y + 0.6f * dp, pBandaLinha);
        }
        if (deitado) { cv.save(); cv.translate(0, rArm.top); cv.drawRect(rArmCam.left, -4 * dp, rArmCam.right, H - rArm.top + 8 * dp, pMascBusto); cv.restore(); }
        if (camada) cv.restoreToCount(sl);
    }
    private float varreY(float u) { float y0 = rArm.top - 6 * dp, y1 = deitado ? Math.min(H, py(1f)) : py(fonte.pes) + 4 * dp; return y0 + (y1 - y0) * u; }
    private static float env(float u) { return Math.min(1f, Math.min(u * 10f, (1f - u) * 10f)); }

    private void brilhos(Canvas cv, double t, float co) {
        if (co <= 0.03f) return;
        float v = (float) Math.pow(co, 1.4), pul = 0.82f + 0.18f * (float) Math.sin(t * 2 * Math.PI / 2.4);
        float x = px(fonte.px, co), y = py(fonte.py);
        pGlow.setAlpha(a8(120 * v * pul)); glow(cv, x, y, armW * 0.2f, pGlow);
        pBrilho.setAlpha(a8(255 * v * pul)); glow(cv, x, y, armW * 0.055f * (0.92f + 0.12f * pul), pBrilho);
        float ex = armW * 0.0165f * co, ey = py(fonte.oy), fl = 0.88f + 0.12f * (float) Math.sin(t * 7.3) * (float) Math.sin(t * 3.1);
        pGlow.setAlpha(a8(90 * v * fl)); glow(cv, x, ey, armW * 0.09f, pGlow);
        pBrilho.setAlpha(a8(235 * v * fl)); glow(cv, x - ex, ey, armW * 0.017f, pBrilho); glow(cv, x + ex, ey, armW * 0.017f, pBrilho);
    }

    /** linha da varredura cruzando a tela + rótulos com linha-guia que aparecem quando ela passa por cabeça/peito/mãos */
    private void varredura(Canvas cv, double vs, float uV, float ang) {
        if (uV >= 0) {
            float y = varreY(uV), e = env(uV);
            pVarreBrilho.setAlpha(a8(255 * e)); cv.save(); cv.translate(0, y); cv.drawRect(0, -14 * dp, varreX1, 14 * dp, pVarreBrilho); cv.restore();
            pVarreLinha.setAlpha(a8(255 * e)); cv.drawRect(0, y - 0.7f * dp, varreX1, y + 0.7f * dp, pVarreLinha);
            float x0 = 8 * dp, x1 = varreX1 - 8 * dp, hh = 7 * dp, tk = 5 * dp; int n = 0;
            colch[n++] = x0; colch[n++] = y - hh; colch[n++] = x0; colch[n++] = y + hh; colch[n++] = x0; colch[n++] = y - hh; colch[n++] = x0 + tk; colch[n++] = y - hh;
            colch[n++] = x1; colch[n++] = y - hh; colch[n++] = x1; colch[n++] = y + hh; colch[n++] = x1; colch[n++] = y + hh; colch[n++] = x1 - tk; colch[n++] = y + hh;
            pTracoN.setColor(DOURADO); pTracoN.setStrokeWidth(1.5f * dp); pTracoN.setAlpha(a8(230 * e)); cv.drawLines(colch, 0, n, pTracoN);
            pCab.setAlpha(a8(220 * e)); pCab.setTextAlign(Paint.Align.RIGHT); cv.drawText("VARREDURA", x1 - 37 * dp, y - 5 * dp, pCab);
            pCab.setTextAlign(Paint.Align.LEFT); cv.drawText(PCT[(int) (uV * 100)], x1 - 30 * dp, y - 5 * dp, pCab); pCab.setAlpha(255);
        }
        float yTop = rArm.top - 6 * dp, yBot = varreY(1f) - yTop;
        for (int i = 0; i < 4; i++) {
            float ny = i == 0 ? fonte.oy : (i == 1 ? fonte.py : (i == 2 ? fonte.m0y : fonte.m1y)), nx = i == 0 ? fonte.ox : (i == 1 ? fonte.px : (i == 2 ? fonte.m0x : fonte.m1x));
            if (ny / fonte.corte > 0.97f) continue;
            float passa = (py(ny) - yTop) / yBot * VARRE_DUR, d = (float) vs - passa; if (d < 0 || d > ROT_DUR) continue;
            float a = Math.min(1f, Math.min(d / 0.22f, (ROT_DUR - d) / 0.6f)); if (a <= 0) continue;
            float co = (float) Math.cos(Math.toRadians(ang)), ax = px(nx, co), ay = py(ny);
            int lado; if (i == 0) lado = 1; else if (i == 1) lado = -1; else { double a0 = Math.toRadians(ang - GRAUS_S * d); lado = (nx - 0.5f) * Math.cos(a0) < 0 ? -1 : 1; }
            float ly = ay + ROT_DY[i] * dp, tw = rotW[i], ext = lado < 0 ? rotL : rotR, cot = ext - lado * (tw + 16 * dp);
            pTracoN.setColor(LARANJA2); pTracoN.setStrokeWidth(1.1f * dp); pTracoN.setAlpha(a8(220 * a));
            cv.drawLine(ax, ay, cot, ly, pTracoN); cv.drawLine(cot, ly, ext, ly, pTracoN);
            pPonto.setColor(DOURADO); pPonto.setAlpha(a8(255 * a)); cv.drawCircle(ax, ay, 2.4f * dp, pPonto);
            pTracoN.setStrokeWidth(1f * dp); cv.drawCircle(ax, ay, 6f * dp + 3f * dp * (1 - a), pTracoN);
            pRot.setAlpha(a8(255 * a)); pRot.setTextAlign(lado < 0 ? Paint.Align.LEFT : Paint.Align.RIGHT); cv.drawText(ROT_TX[i], ext + (lado < 0 ? 2 * dp : -2 * dp), ly - 5 * dp, pRot);
        }
    }

    private void hud(Canvas cv, double t) {
        Paint.Align al = centro ? Paint.Align.CENTER : Paint.Align.LEFT;
        pRel.setTextAlign(al); cv.drawText(horaTx, relX, relY, pRel);
        float rx0 = centro ? relX - horaW / 2 : relX, rx1 = rx0 + horaW;
        pSeg.setTextAlign(Paint.Align.LEFT); cv.drawText(segTx, rx1 + 5 * dp, relY - pRel.getTextSize() * 0.52f, pSeg);
        float ly = relY + 7 * dp, frac = (System.currentTimeMillis() % 60000L) / 60000f;
        pTracoN.setColor(LARANJA2); pTracoN.setStrokeWidth(1f * dp); pTracoN.setAlpha(55); cv.drawLine(rx0, ly, rx1, ly, pTracoN);
        pTracoN.setAlpha(220); cv.drawLine(rx0, ly, rx0 + (rx1 - rx0) * frac, ly, pTracoN);
        pPonto.setColor(DOURADO); pPonto.setAlpha(255); cv.drawCircle(rx0 + (rx1 - rx0) * frac, ly, 1.8f * dp, pPonto);
        pData.setTextAlign(al); cv.drawText(dataTx, relX, dataY, pData);
        // chips de estado
        Metricas m = mUlt; int pc = m == null ? -1 : m.pc; boolean carr = m != null && m.carregando;
        String c0 = pc == 1 ? "PC ONLINE" : (pc == 0 ? "PC OFFLINE" : "PC ···"); int k0 = pc == 1 ? OK : (pc == 0 ? ALERTA : DOURADO);
        float pad = 8 * dp, dot = 7 * dp, w0 = chipW[pc == 1 ? 0 : (pc == 0 ? 1 : 2)] + pad * 2 + dot, w1 = carr ? chipW[3] + pad * 2 + dot : 0, w2 = chipW[4] + pad * 2 + dot,
            gap = 6 * dp, tot = w0 + w2 + (carr ? w1 + gap : 0) + gap, x = centro ? W / 2f - tot / 2 : colX0;
        x = chip(cv, x, c0, k0, w0, pc == 1 ? 0.6f + 0.4f * (float) Math.sin(t * 3) : 1f) + gap;
        if (carr) x = chip(cv, x, "CARREGANDO", OK, w1, 0.5f + 0.5f * (float) Math.sin(t * 4)) + gap;
        chip(cv, x, "MARK 85", LARANJA, w2, 1f);
        // próximo compromisso
        float px0 = centro ? W / 2f - (proxPreW + proxTxW) / 2 : colX0;
        pProxPre.setTextAlign(Paint.Align.LEFT); pProx.setTextAlign(Paint.Align.LEFT);
        cv.drawText(proxPre, px0, proxY, pProxPre); cv.drawText(proxTx, px0 + proxPreW, proxY, pProx);
    }

    private float chip(Canvas cv, float x, String tx, int cor, float w, float pulso) {
        float h = 17 * dp, y0 = chipY - h / 2; ov.set(x, y0, x + w, y0 + h);
        pPreen.setColor(0x9a120a05); cv.drawRoundRect(ov, h / 2, h / 2, pPreen);
        pTracoN.setColor(cor); pTracoN.setStrokeWidth(1f * dp); pTracoN.setAlpha(110); cv.drawRoundRect(ov, h / 2, h / 2, pTracoN);
        float cx = x + 8 * dp + 2.5f * dp; pPonto.setColor(cor); pPonto.setAlpha(a8(255 * pulso)); cv.drawCircle(cx, chipY, 2.6f * dp, pPonto);
        pGlow.setAlpha(a8(110 * pulso)); glow(cv, cx, chipY, 8 * dp, pGlow);
        pChip.setTextAlign(Paint.Align.LEFT); cv.drawText(tx, x + 8 * dp + 7 * dp, chipY + pChip.getTextSize() * 0.36f, pChip);
        return x + w;
    }

    private void painel(Canvas cv, double t, Metricas m) {
        RectF r = rPainel; float rr = 10 * dp;
        cv.drawRoundRect(r, rr, rr, pVidro); cv.drawRoundRect(r, rr, rr, pVidroBrilho);
        pTracoN.setColor(LARANJA2); pTracoN.setStrokeWidth(1f * dp); pTracoN.setAlpha(55); cv.drawRoundRect(r, rr, rr, pTracoN);
        pTracoN.setColor(LARANJA2); pTracoN.setStrokeWidth(2f * dp); pTracoN.setAlpha(230); cv.drawLines(cantos, pTracoN);
        float pad = 10 * dp; pCab.setTextAlign(Paint.Align.LEFT); cv.drawText("TELEMETRIA  ·  MARK 85", r.left + pad + 4 * dp, cabY, pCab);
        pCab.setTextAlign(Paint.Align.RIGHT); cv.drawText(upTx, r.right - pad - 4 * dp, cabY, pCab);
        // medidores circulares (270°)
        pTracoN.setColor(LARANJA); pTracoN.setStrokeWidth(1f * dp); pTracoN.setAlpha(70); cv.drawLines(gTicks, pTracoN);
        for (int i = 0; i < 4; i++) {
            float v = lim(gVal[i]); RectF o = gOv[i];
            pTracoN.setColor(LARANJA); pTracoN.setStrokeWidth(3.2f * dp); pTracoN.setAlpha(45); cv.drawArc(o, 135, 270, false, pTracoN);
            int cor; boolean alerta = i == 3 ? (m != null && m.batOk && v < 0.15f && !m.carregando) : v > 0.85f, verde = i == 3 && m != null && m.carregando;
            Paint pa = pArcoG[i]; float pul = 1f;
            if (alerta) { cor = ALERTA; pul = 0.65f + 0.35f * (float) Math.sin(t * 5); } else if (verde) { cor = OK; pul = 0.6f + 0.4f * (float) Math.sin(t * 3); } else cor = LARANJA2;
            pa.setStrokeWidth(3.2f * dp);
            if (alerta || verde) { pa.setShader(null); pa.setColor(cor); pa.setAlpha(a8(255 * pul)); } else { pa.setShader(gShader[i]); pa.setAlpha(255); }
            float sw = Math.max(1.5f, 270 * v); cv.drawArc(o, 135, sw, false, pa);
            pArcoBr.setColor(cor); pArcoBr.setStrokeWidth(8 * dp); pArcoBr.setAlpha(a8(45 * pul)); cv.drawArc(o, 135, sw, false, pArcoBr);
            double a = Math.toRadians(135 + sw); float ex = gCx[i] + (float) Math.cos(a) * gR, ey = gCy[i] + (float) Math.sin(a) * gR;
            pPonto.setColor(alerta || verde ? cor : DOURADO); pPonto.setAlpha(255); cv.drawCircle(ex, ey, 2.2f * dp, pPonto);
            cv.drawText(PCT[Math.round(v * 100)], gCx[i], gCy[i] + pVal.getTextSize() * 0.36f, pVal);
            float lx = gCx[i] + gR + 9 * dp; textoK(cv, G_ROT[i], lx, gCy[i] - 1.5f * dp, pMini, rotGK[i]); textoK(cv, gSub[i], lx, gCy[i] + 10 * dp, pSub, subK[i]);
        }
        // sparkline de CPU (60 s) rolando suave
        pTracoN.setColor(LARANJA); pTracoN.setStrokeWidth(0.8f * dp); pTracoN.setAlpha(36); cv.drawLines(grade, pTracoN);
        pCab.setTextAlign(Paint.Align.LEFT); cv.drawText("CPU · 60 s", rSpark.left, rSpark.top - 4 * dp, pCab);
        if (m != null && m.hist.length > 1) {
            float fs = sinc ? 1f : lim((SystemClock.elapsedRealtime() - m.ts) / 1000f);
            cv.save(); cv.clipRect(rSpark); cv.translate(-sparkPasso * fs, 0); cv.drawPath(pathArea, pArea); cv.drawPath(pathSpark, pSpark);
            pPonto.setColor(DOURADO); pPonto.setAlpha(255); cv.drawCircle(rSpark.right + sparkPasso, sparkUltY, 2f * dp, pPonto); cv.restore();
        }
        // barras por núcleo
        cv.drawText("NÚCLEOS", rNuc.left, rNuc.top - 4 * dp, pCab);
        int nn = m == null ? 0 : m.nNuc;
        if (nn > 0) {
            float bw = rNuc.width() / nn, hh = rNuc.height();
            for (int k = 0; k < nn; k++) {
                nVal[k] += (m.nuc[k] - nVal[k]) * (sinc ? 1f : 0.2f); float v = lim(nVal[k]), x0 = rNuc.left + k * bw + bw * 0.18f, x1 = rNuc.left + (k + 1) * bw - bw * 0.18f;
                pPreen.setColor(0x26ff7700); cv.drawRect(x0, rNuc.top, x1, rNuc.bottom, pPreen);
                pPreen.setColor(v > 0.85f ? ALERTA : LARANJA2); pPreen.setAlpha(v > 0.85f ? 230 : 200); cv.drawRect(x0, rNuc.bottom - hh * Math.max(0.04f, v), x1, rNuc.bottom, pPreen);
            }
        }
        // rede, temperatura e térmico
        pTx.setTextAlign(Paint.Align.LEFT); pTx.setColor(0xe6fff3e6);
        float kx = Math.min(txK, txKV), ps = txPasso / txKV;                                     // bloco cabe até a borda do cartão e na altura das 3 linhas
        cv.save(); cv.translate(txXd, txY); if (kx < 0.999f || txKV < 0.999f) cv.scale(kx, txKV);
        cv.drawText(rxTx, 0, 0, pTx); cv.drawText(txTx, 0, ps, pTx); cv.drawText(tempTx, 0, 2 * ps, pTx);
        if (!termTx.isEmpty()) { pTx.setColor(termCor); cv.drawText(termTx, tempW, 2 * ps, pTx); }
        cv.restore();
    }

    /** texto estreitado (k < 1) para caber na largura livre, sem alocar */
    private static void textoK(Canvas cv, String s, float x, float y, Paint p, float k) {
        if (k >= 0.999f) { cv.drawText(s, x, y, p); return; }
        cv.save(); cv.translate(x, y); cv.scale(k, Math.min(1f, k + 0.15f)); cv.drawText(s, 0, 0, p); cv.restore();
    }
    private static float caber(float livre, float w) { return w <= 0 || livre <= 0 ? 1f : Math.min(1f, livre / w); }

    private void dock(Canvas cv, double t) {
        for (int i = 0; i < 7; i++) {
            float cx = dCx[i], cy = dCy[i], fl = 0f;
            for (int k = 0; k < 4; k++) { double age = t - rpT[k]; if (age >= 0 && age < 0.6 && Math.abs(rpX[k] - cx) < dCel * 0.5f && Math.abs(rpY[k] - cy) < dR * 2f) fl = Math.max(fl, 1f - (float) (age / 0.6)); }
            pPreen.setColor(0xb0120a05); cv.drawCircle(cx, cy, dR, pPreen);
            pGlow.setAlpha(a8(55 + 150 * fl)); glow(cv, cx, cy, dR * 1.5f, pGlow);
            pTracoN.setColor(LARANJA2); pTracoN.setStrokeWidth(1.1f * dp); pTracoN.setAlpha(a8(120 + 120 * fl)); cv.drawCircle(cx, cy, dR, pTracoN);
            ov.set(cx - dR - 3 * dp, cy - dR - 3 * dp, cx + dR + 3 * dp, cy + dR + 3 * dp);
            pTraco.setColor(DOURADO); pTraco.setStrokeWidth(1.5f * dp); pTraco.setAlpha(200); cv.drawArc(ov, (float) ((t * 35 + i * 51) % 360), 42, false, pTraco);
            if (icone[i] != null) { cv.save(); cv.translate(cx, cy); cv.scale(icoK, icoK); pIcone.setAlpha(a8(230 + 25 * fl)); cv.drawPath(icone[i], pIcone); cv.restore(); }
            cv.drawText(ATALHOS[i][0], cx, cy + dR + 12 * dp, pIcoTx);
        }
    }

    private void ondas(Canvas cv, double t) {
        for (int k = 0; k < 4; k++) {
            double age = t - rpT[k]; if (age < 0 || age >= 0.8) continue;
            float u = (float) (age / 0.8), r = 6 * dp + u * 64 * dp;
            pTraco.setColor(DOURADO); pTraco.setStrokeWidth((2.4f * (1 - u) + 0.6f) * dp); pTraco.setAlpha(a8(240 * (1 - u) * (1 - u)));
            cv.drawCircle(rpX[k], rpY[k], r, pTraco); pTraco.setAlpha(a8(120 * (1 - u))); cv.drawCircle(rpX[k], rpY[k], r * 0.6f, pTraco);
            pGlow.setAlpha(a8(160 * (1 - u))); glow(cv, rpX[k], rpY[k], 26 * dp * (0.6f + u), pGlow);
        }
    }

    // =============================================== TEXTOS ===============================================
    private void relogio() {
        long ms = System.currentTimeMillis(), seg = ms / 1000; if (seg == segUlt) return; segUlt = seg;
        cal.setTimeInMillis(ms); int h = cal.get(Calendar.HOUR_OF_DAY), mi = cal.get(Calendar.MINUTE), dia = cal.get(Calendar.YEAR) * 1000 + cal.get(Calendar.DAY_OF_YEAR);
        segTx = D2[cal.get(Calendar.SECOND)];
        if (h * 60 + mi != minUlt) { minUlt = h * 60 + mi; horaTx = D2[h] + ":" + D2[mi]; horaW = pRel.measureText(horaTx); }
        if (dia != diaUlt) { diaUlt = dia; dataTx = fData.format(new Date(ms)).toUpperCase(PT); }
        refazProx(ms);
    }

    private String hm(long t) { calP.setTimeInMillis(t); return D2[calP.get(Calendar.HOUR_OF_DAY)] + ":" + D2[calP.get(Calendar.MINUTE)]; }

    private void refazProx(long agora) {
        Metricas m = mUlt; String rabo = null, tit = null;
        if (m == null) { proxPre = "AGENDA"; proxTx = "  ···"; }
        else if (m.proxTitulo == null) { proxPre = "AGENDA"; proxTx = " LIVRE"; }
        else {
            long ini = m.proxIni;
            if (ini <= agora) { proxPre = "AGORA"; rabo = "até " + hm(m.proxFim); }
            else {
                long min = (ini - agora + 59999) / 60000;
                rabo = min < 60 ? "em " + min + " min" : (min < 2880 ? "em " + (min / 60) + "h" + D2[(int) (min % 60)] : "em " + (min / 1440) + " dias");
                cal.setTimeInMillis(agora); int dA = cal.get(Calendar.YEAR) * 1000 + cal.get(Calendar.DAY_OF_YEAR);
                cal.setTimeInMillis(agora + 86400000L); int dB = cal.get(Calendar.YEAR) * 1000 + cal.get(Calendar.DAY_OF_YEAR);
                calP.setTimeInMillis(ini); int dI = calP.get(Calendar.YEAR) * 1000 + calP.get(Calendar.DAY_OF_YEAR);
                proxPre = "PRÓXIMO " + (dI == dA ? "" : (dI == dB ? "AMANHÃ " : D2[calP.get(Calendar.DAY_OF_MONTH)] + "/" + D2[calP.get(Calendar.MONTH) + 1] + " ")) + hm(ini);
            }
            tit = m.proxTitulo;
        }
        proxPreW = pProxPre.measureText(proxPre);
        if (tit != null) {
            String fim = " · " + rabo; float livre = proxMaxW - proxPreW - pProx.measureText(" · ") - pProx.measureText(fim);
            if (pProx.measureText(tit) > livre) { int n = livre > 0 ? pProx.breakText(tit, true, livre - pProx.measureText("…"), null) : 0; tit = (n > 0 ? tit.substring(0, n).trim() : "") + "…"; }
            proxTx = " · " + tit + fim;
        }
        proxTxW = pProx.measureText(proxTx);
    }

    private void refazMet(Metricas m) {
        if (m == null) return;
        gAlvo[0] = m.cpu; gAlvo[1] = m.ram; gAlvo[2] = m.disco; gAlvo[3] = m.bat;
        gSub[0] = m.ghz > 0 ? String.format(PT, "%.1f GHz", m.ghz) : "—";
        gSub[1] = m.ramTotal > 0 ? String.format(PT, "%.1f/%.0f GB", m.ramUsado / 1e9, m.ramTotal / 1e9) : "—";
        gSub[2] = m.discoLivre > 0 ? bytes(m.discoLivre) + " livre" : "—";
        gSub[3] = m.batOk ? String.format(PT, "%.1f°C", m.temp) : "—";
        rxTx = "↓ " + taxa(m.rx); txTx = "↑ " + taxa(m.tx); tempTx = m.batOk ? String.format(PT, "TEMP %.1f°C", m.temp) : "TEMP —";
        tempW = pTx.measureText(tempTx); termTx = m.termico >= 0 ? " · " + TERM[Math.min(6, m.termico)] : ""; termCor = m.termico >= 0 ? TERM_COR[Math.min(6, m.termico)] : DOURADO;
        for (int i = 0; i < 4; i++) subK[i] = caber(subMax[i], pSub.measureText(gSub[i]));
        float wq = Math.max(Math.max(pTx.measureText(rxTx), pTx.measureText(txTx)), tempW + (termTx.isEmpty() ? 0 : pTx.measureText(termTx))), limX = rPainel.right - 14 * dp;
        txXd = Math.max(rNuc.right + 8 * dp, Math.min(txX, limX - wq)); txK = caber(limX - txXd, wq);
        long s = m.uptime / 1000, d = s / 86400, h = (s / 3600) % 24, mi = (s / 60) % 60;
        upTx = d > 0 ? "UPTIME " + d + "d " + D2[(int) h] + "h" + D2[(int) mi] : "UPTIME " + D2[(int) h] + "h" + D2[(int) mi];
        // sparkline: o ponto mais novo nasce fora (à direita) e entra rolando
        int n = m.hist.length; pathSpark.rewind(); pathArea.rewind(); sparkPasso = rSpark.width() / 59f;
        for (int j = 0; j < n; j++) {
            float x = rSpark.right + sparkPasso - (n - 1 - j) * sparkPasso, y = rSpark.bottom - lim(m.hist[j]) * rSpark.height() * 0.94f;
            if (j == 0) { pathSpark.moveTo(x, y); pathArea.moveTo(x, rSpark.bottom); pathArea.lineTo(x, y); } else { pathSpark.lineTo(x, y); pathArea.lineTo(x, y); }
            if (j == n - 1) { pathArea.lineTo(x, rSpark.bottom); pathArea.close(); sparkUltY = y; }
        }
    }
    private static String taxa(long b) { if (b < 0) return "—"; if (b < 1024) return b + " B/s"; if (b < 1048576) return String.format(PT, "%.0f KB/s", b / 1024.0); return String.format(PT, "%.1f MB/s", b / 1048576.0); }
    private static String bytes(long b) { return b >= 1e12 ? String.format(PT, "%.1fT", b / 1e12) : String.format(PT, "%.0fG", b / 1e9); }

    // =============================================== LAYOUT E CAMADAS ===============================================
    private void layout() {
        float m = MARGEM_DP * dp; Fonte f = fonte; float fw = f.w, fh = f.h * f.corte;
        if (!deitado) {
            armH = R_ARM_ALT * H; armW = armH * fw / fh; if (armW > W * 0.98f) { armW = W * 0.98f; armH = armW * fh / fw; }
            armCx = W / 2f; armT0 = R_ARM_TOPO * H; pesY = armT0 + f.pes / f.corte * armH;
            pedRx = R_PED_RX * W; pedRy = pedRx * R_PED_ACH; reflH = R_REFLEXO * H; colH = R_COLUNA * H;
            pRel.setTextSize(R_REL_SP * sp); centro = true; relX = W / 2f; relY = R_REL_Y * H; dataY = R_DATA_Y * H; chipY = R_CHIP_Y * H; proxY = R_PROX_Y * H;
            colX0 = m; colX1 = W - m; proxMaxW = W - 2 * m; rotL = m; rotR = W - m;
            rPainel.set(m, R_PAINEL_Y0 * H, W - m, R_PAINEL_Y1 * H);
            layoutDock(m, W - m, R_DOCK_Y * H);
        } else {
            armH = P_BUSTO_ALT * H; armW = armH * fw / fh; float maxW = (P_COL_X0 - 0.02f) * W; if (armW > maxW) { armW = maxW; armH = armW * fh / fw; }
            armCx = Math.max(P_BUSTO_CX * W, armW / 2f + 0.005f * W); armT0 = H - armH; pesY = H;
            pedRx = 0; pedRy = 0; reflH = 0; colH = 0;
            colX0 = P_COL_X0 * W; colX1 = P_COL_X1 * W;
            pRel.setTextSize(P_REL_SP * sp); centro = false; relX = colX0; relY = P_REL_Y * H; dataY = P_DATA_Y * H; chipY = P_CHIP_Y * H; proxY = P_PROX_Y * H;
            proxMaxW = colX1 - colX0; rotL = 0.015f * W; rotR = colX0 - 0.015f * W;
            rPainel.set(colX0, P_PAINEL_Y0 * H, colX1, P_PAINEL_Y1 * H);
            layoutDock(colX0, colX1, P_DOCK_Y * H);
        }
        bandaH = armH * 0.13f; interfH = H * 0.05f; varreX1 = deitado ? colX0 - 0.012f * W : W;
        layoutPainel();
        // feixes de luz vindos do alto em direção à armadura
        float[][] fx = deitado ? new float[][]{{0.06f, 0.03f, 0.2f, 0.2f}, {0.25f, 0.05f, 0.25f, 0.26f}, {0.44f, 0.03f, 0.31f, 0.2f}}
            : new float[][]{{0.16f, 0.035f, 0.42f, 0.3f}, {0.5f, 0.05f, 0.5f, 0.38f}, {0.86f, 0.035f, 0.6f, 0.3f}};
        float yb = deitado ? H : pesY;
        for (int i = 0; i < 3; i++) {
            float tx = fx[i][0] * W, tw = fx[i][1] * W / 2, bx = fx[i][2] * W, bw = fx[i][3] * W / 2;
            feixeB[i] = null; try { feixeB[i] = assarFeixe(tx, tw, bx, bw, yb, feixeR[i]); } catch (Throwable e) { Log.w(TAG, "feixe: " + e); }
        }
    }

    /** feixe de luz com bordas suaves: gradiente angular a partir do ápice virtual (acima da tela) x gradiente ao longo do comprimento */
    private Bitmap assarFeixe(float tx, float tw, float bx, float bw, float yb, RectF caixa) {
        float t = -2 * dp, l = Math.min(tx - tw, bx - bw) - 8 * dp, r = Math.max(tx + tw, bx + bw) + 8 * dp; caixa.set(l, t, r, yb);
        int w = Math.max(4, Math.round((r - l) / 3f)), h = Math.max(4, Math.round((yb - t) / 3f));
        Bitmap b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888); Canvas k = new Canvas(b); k.scale(w / (r - l), h / (yb - t)); k.translate(-l, -t);
        float s = tw / (tw - bw), ax = (tx - tw) + ((bx - bw) - (tx - tw)) * s, ay = t + (yb - t) * s;
        float fL = (float) (Math.atan2(yb - ay, (bx - bw) - ax) / (2 * Math.PI)), fR = (float) (Math.atan2(yb - ay, (bx + bw) - ax) / (2 * Math.PI)), fC = (fL + fR) / 2, m = (fL - fR) / 2;
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.DITHER_FLAG);
        p.setShader(new SweepGradient(ax, ay, new int[]{0, 0, 0x3cffa040, 0x6effb050, 0x3cffa040, 0, 0}, new float[]{0f, fR - m * 0.1f, fR + m * 0.45f, fC, fL - m * 0.45f, fL + m * 0.1f, 1f}));
        k.drawRect(l, t, r, yb, p);
        p.setXfermode(DST_IN); p.setShader(new LinearGradient(tx, t, bx, yb, new int[]{0xff000000, 0x60000000, 0x00000000}, new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP));
        k.drawRect(l, t, r, yb, p);
        return b;
    }

    private void layoutDock(float x0, float x1, float y) {
        float cel = (x1 - x0) / 7f; dCel = cel; dR = Math.min(BOTAO_DP / 2f * dp, cel * 0.4f); icoK = dR * 0.52f / 9.5f;
        for (int i = 0; i < 7; i++) { dCx[i] = x0 + cel * (i + 0.5f); dCy[i] = y; }
    }

    private void layoutPainel() {
        RectF r = rPainel; float pad = 10 * dp, w = r.width(); cabY = r.top + pad + 6 * dp;
        float y2, y3 = r.bottom - pad;
        if (!deitado) {
            float cw = (w - 2 * pad) / 4f; gR = Math.min(cw * 0.2f, 19 * dp); float gy = r.top + 23 * dp + gR;
            for (int i = 0; i < 4; i++) { gCx[i] = r.left + pad + cw * i + gR + 7 * dp; gCy[i] = gy; }
            y2 = gy + gR + 24 * dp;
            rSpark.set(r.left + pad + 4 * dp, y2, r.left + pad + (w - 2 * pad) * 0.5f, y3);
            rNuc.set(rSpark.right + 14 * dp, y2, rSpark.right + 14 * dp + (w - 2 * pad) * 0.15f, y3);
        } else {
            float lw = w * 0.42f, cw = (lw - pad) / 2f, ch = (r.height() - 20 * dp - pad) / 2f; gR = Math.min(Math.min(cw * 0.2f, ch * 0.32f), 19 * dp);
            for (int i = 0; i < 4; i++) { gCx[i] = r.left + pad + cw * (i % 2) + gR + 7 * dp; gCy[i] = r.top + 22 * dp + ch * (i / 2) + ch * 0.45f; }
            float sx0 = r.left + lw + 12 * dp, sx1 = r.right - pad - 4 * dp, ym = r.top + r.height() * 0.56f;
            rSpark.set(sx0, r.top + 34 * dp, sx1, ym);
            y2 = ym + 22 * dp; rNuc.set(sx0, y2, sx0 + (sx1 - sx0) * 0.32f, y3);
        }
        int cols = deitado ? 2 : 4; float fimCol = deitado ? r.left + w * 0.42f + 6 * dp : r.right - pad;
        for (int i = 0; i < 4; i++) { float lx = gCx[i] + gR + 9 * dp, fim = (i % cols) < cols - 1 ? gCx[i + 1] - gR - 9 * dp : fimCol; subMax[i] = fim - lx;
            rotGK[i] = caber(subMax[i], pMini.measureText(G_ROT[i])); subK[i] = 1f; }
        txX = rNuc.right + 16 * dp; txXd = txX; txK = 1f; txPasso = Math.max(6 * dp, Math.min(12 * dp, (y3 - y2) / 3f)); txY = y3 - 2 * txPasso - 1 * dp;
        txKV = Math.max(0.5f, Math.min(1f, txPasso / (pTx.getTextSize() * 1.12f)));          // tela baixa: as 3 linhas não se sobrepõem
        float tk0 = gR + 4.5f * dp, tk1 = gR + 6.5f * dp; gTicks = new float[4 * 28 * 4]; int n = 0;
        for (int i = 0; i < 4; i++) {
            gOv[i].set(gCx[i] - gR, gCy[i] - gR, gCx[i] + gR, gCy[i] + gR);
            for (int k = 0; k < 28; k++) { double a = Math.toRadians(135 + k * 10); float cs = (float) Math.cos(a), sn = (float) Math.sin(a), l = k % 9 == 0 ? tk1 + 1.5f * dp : tk1;
                gTicks[n++] = gCx[i] + cs * tk0; gTicks[n++] = gCy[i] + sn * tk0; gTicks[n++] = gCx[i] + cs * l; gTicks[n++] = gCy[i] + sn * l; }
        }
        float L = 14 * dp; cantos = new float[]{r.left, r.top + L, r.left, r.top, r.left, r.top, r.left + L, r.top, r.right - L, r.top, r.right, r.top, r.right, r.top, r.right, r.top + L,
            r.right, r.bottom - L, r.right, r.bottom, r.right, r.bottom, r.right - L, r.bottom, r.left + L, r.bottom, r.left, r.bottom, r.left, r.bottom, r.left, r.bottom - L};
        grade = new float[12]; for (int k = 0; k < 3; k++) { float y = rSpark.top + rSpark.height() * (k + 0.5f) / 3f; grade[k * 4] = rSpark.left; grade[k * 4 + 1] = y; grade[k * 4 + 2] = rSpark.right; grade[k * 4 + 3] = y; }
    }

    private final Shader[] gShader = new Shader[4];
    private void criarShaders() {
        pColuna.setShader(new RadialGradient(0, 0, 100, new int[]{0x60ffb060, 0x22ff8a20, 0x00ff7700}, new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));
        pDisco.setShader(new RadialGradient(0, 0, 100, new int[]{0xf0fff3e6, 0xb0ffb050, 0x50ff7700, 0x00ff7700}, new float[]{0f, 0.14f, 0.5f, 1f}, Shader.TileMode.CLAMP));
        pHalo.setShader(new RadialGradient(0, 0, 100, new int[]{0x58ff9d24, 0x26ff7700, 0x00ff7700}, new float[]{0f, 0.42f, 1f}, Shader.TileMode.CLAMP));
        pBrilho.setShader(new RadialGradient(0, 0, 100, new int[]{0xfffff3e6, 0xd0ffd28a, 0x60ff9d24, 0x00ff7700}, new float[]{0f, 0.2f, 0.48f, 1f}, Shader.TileMode.CLAMP));
        pGlow.setShader(new RadialGradient(0, 0, 100, new int[]{0x90ff9d24, 0x30ff7700, 0x00ff7700}, new float[]{0f, 0.35f, 1f}, Shader.TileMode.CLAMP));
        pInterf.setShader(new LinearGradient(0, -interfH, 0, interfH, new int[]{0x00ff9d24, 0x12ff9d24, 0x00ff9d24}, new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP));
        pVarreLinha.setShader(new LinearGradient(0, 0, varreX1, 0, new int[]{0x00ffc36b, 0xd0ffc36b, 0xd0ffc36b, 0x00ffc36b}, new float[]{0f, 0.12f, 0.88f, 1f}, Shader.TileMode.CLAMP));
        pVarreBrilho.setShader(new LinearGradient(0, -14 * dp, 0, 14 * dp, new int[]{0x00ff9d24, 0x34ff9d24, 0x00ff9d24}, new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP));
        pBanda.setShader(new LinearGradient(0, -bandaH, 0, 0, new int[]{0x00ff7700, 0x55ff9d24, 0xc0ffc36b}, new float[]{0f, 0.72f, 1f}, Shader.TileMode.CLAMP));
        pMascRefl.setShader(new LinearGradient(0, pesY, 0, pesY + Math.max(1, reflH), new int[]{0xff000000, 0x50000000, 0x00000000}, new float[]{0f, 0.4f, 1f}, Shader.TileMode.CLAMP));
        pMascBusto.setShader(new LinearGradient(0, armH * 0.68f, 0, armH * 0.97f, 0xff000000, 0x00000000, Shader.TileMode.CLAMP));
        pVidroBrilho.setShader(new LinearGradient(0, rPainel.top, 0, rPainel.top + 34 * dp, 0x22ff9d24, 0x00ff9d24, Shader.TileMode.CLAMP));
        pArea.setShader(new LinearGradient(0, rSpark.top, 0, rSpark.bottom, 0x80ff9d24, 0x00ff7700, Shader.TileMode.CLAMP));
        pSpark.setStrokeWidth(1.5f * dp); pSpark.setStrokeJoin(Paint.Join.ROUND); pSpark.setColor(LARANJA2);
        for (int i = 0; i < 4; i++) {
            SweepGradient sg = new SweepGradient(gCx[i], gCy[i], new int[]{LARANJA, LARANJA2, DOURADO, DOURADO}, new float[]{0f, 0.4f, 0.75f, 1f});
            Matrix mm = new Matrix(); mm.setRotate(135, gCx[i], gCy[i]); sg.setLocalMatrix(mm); gShader[i] = sg;
        }
        pLinhas.setShader(new BitmapShader(linhas, Shader.TileMode.REPEAT, Shader.TileMode.REPEAT));
    }

    private void criarSprites() {
        int[] cores = {0xffff7a1a, 0xffff9a3c, 0xffffb760, 0xffffd28a};
        for (int i = 0; i < 4; i++) {
            Bitmap b = Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888); Canvas k = new Canvas(b); Paint p = new Paint(Paint.ANTI_ALIAS_FLAG); int c0 = cores[i] & 0xffffff;
            p.setShader(new RadialGradient(32, 32, 32, new int[]{0xfffff3e6, 0xe0000000 | c0, 0x50000000 | c0, 0x00000000 | c0}, new float[]{0f, 0.14f, 0.4f, 1f}, Shader.TileMode.CLAMP));
            k.drawCircle(32, 32, 32, p); spr[i] = b;
        }
        int hl = Math.max(3, Math.round(3 * dp)); linhas = Bitmap.createBitmap(1, hl, Bitmap.Config.ARGB_8888);
        for (int y = 0; y < hl; y++) linhas.setPixel(0, y, y < Math.max(1, hl / 3) ? 0x2a000000 : 0x00000000);
    }

    private void iniciarBrasas() {
        Random r = new Random(85); int[] ini = {0, 56, 104, NB}; for (int p = 0; p < 4; p++) profIni[p] = ini[p];
        for (int p = 0; p < 3; p++) for (int i = ini[p]; i < ini[p + 1]; i++) {
            bProf[i] = p; bX[i] = r.nextFloat(); bY[i] = r.nextFloat(); bFase[i] = r.nextFloat() * 6.283f; bF[i] = 0.25f + r.nextFloat() * 0.6f; bT[i] = 1.2f + r.nextFloat() * 3.5f;
            bCor[i] = (i - ini[p]) * 4 / (ini[p + 1] - ini[p]);                       // cores em blocos (lotes no canvas de hardware)
            if (p == 0) { bV[i] = 0.010f + r.nextFloat() * 0.008f; bS[i] = 0.9f + r.nextFloat() * 0.9f; bA[i] = 6 + r.nextFloat() * 8; bAl[i] = 90 + r.nextFloat() * 70; }
            else if (p == 1) { bV[i] = 0.018f + r.nextFloat() * 0.012f; bS[i] = 1.4f + r.nextFloat() * 1.4f; bA[i] = 10 + r.nextFloat() * 12; bAl[i] = 130 + r.nextFloat() * 80; }
            else { bV[i] = 0.032f + r.nextFloat() * 0.02f; bS[i] = 2f + r.nextFloat() * 2.2f; bA[i] = 14 + r.nextFloat() * 18; bAl[i] = 160 + r.nextFloat() * 90;
                if (i >= ini[3] - 8) { bS[i] = 7f + r.nextFloat() * 6f; bAl[i] = 26 + r.nextFloat() * 22; bV[i] = 0.02f + r.nextFloat() * 0.01f; } }   // bokeh grande e fraco
        }
    }

    /** ícones vetoriais (caixa de -12..12) */
    private void criarIcones() {
        for (int i = 0; i < 7; i++) icone[i] = new Path();
        Path p = icone[0]; p.addRoundRect(new RectF(-3.4f, -9.5f, 3.4f, 2.5f), 3.4f, 3.4f, Path.Direction.CW); p.addArc(new RectF(-7f, -6f, 7f, 6.5f), 0, 180);
        p.moveTo(0, 6.5f); p.lineTo(0, 10f); p.moveTo(-4f, 10f); p.lineTo(4f, 10f);
        p = icone[1]; p.moveTo(-5.5f, -8.5f); p.lineTo(5.5f, -8.5f); p.quadTo(9.5f, -8.5f, 9.5f, -4.5f); p.lineTo(9.5f, 1f); p.quadTo(9.5f, 5f, 5.5f, 5f); p.lineTo(-0.5f, 5f);
        p.lineTo(-5.5f, 9.5f); p.lineTo(-4.5f, 5f); p.quadTo(-9.5f, 5f, -9.5f, 1f); p.lineTo(-9.5f, -4.5f); p.quadTo(-9.5f, -8.5f, -5.5f, -8.5f); p.close();
        p.addCircle(-4f, -1.8f, 0.45f, Path.Direction.CW); p.addCircle(0, -1.8f, 0.45f, Path.Direction.CW); p.addCircle(4f, -1.8f, 0.45f, Path.Direction.CW);
        p = icone[2]; p.addRoundRect(new RectF(-10.5f, -8.5f, 10.5f, 5f), 1.6f, 1.6f, Path.Direction.CW); p.moveTo(0, 5f); p.lineTo(0, 8.5f); p.moveTo(-5f, 9.5f); p.lineTo(5f, 9.5f);
        p.moveTo(-2.5f, -5f); p.lineTo(3.5f, -1.8f); p.lineTo(-2.5f, 1.4f); p.close();
        p = icone[3]; p.addRoundRect(new RectF(-10.5f, -5f, 10.5f, 8.5f), 2.2f, 2.2f, Path.Direction.CW); p.moveTo(-4.5f, -5f); p.lineTo(-3f, -8.5f); p.lineTo(3f, -8.5f); p.lineTo(4.5f, -5f);
        p.addCircle(0, 1.8f, 4f, Path.Direction.CW); p.addCircle(7.2f, -2f, 0.4f, Path.Direction.CW);
        p = icone[4]; p.addRoundRect(new RectF(-10f, -8.5f, 10f, -1.5f), 3.5f, 3.5f, Path.Direction.CW); p.addCircle(6.5f, -5f, 1.9f, Path.Direction.CW);
        p.addRoundRect(new RectF(-10f, 1.5f, 10f, 8.5f), 3.5f, 3.5f, Path.Direction.CW); p.addCircle(-6.5f, 5f, 1.9f, Path.Direction.CW);
        p = icone[5]; p.addRoundRect(new RectF(-9.5f, -7f, 9.5f, 9.5f), 2f, 2f, Path.Direction.CW); p.moveTo(-9.5f, -2.5f); p.lineTo(9.5f, -2.5f);
        p.moveTo(-4.5f, -10f); p.lineTo(-4.5f, -5f); p.moveTo(4.5f, -10f); p.lineTo(4.5f, -5f);
        for (int k = 0; k < 6; k++) p.addCircle(-4.5f + (k % 3) * 4.5f, 1.8f + (k / 3) * 3.8f, 0.45f, Path.Direction.CW);
        p = icone[6]; p.moveTo(-5f, -6.5f); p.lineTo(-10.5f, 0); p.lineTo(-5f, 6.5f); p.moveTo(5f, -6.5f); p.lineTo(10.5f, 0); p.lineTo(5f, 6.5f); p.moveTo(2.2f, -9f); p.lineTo(-2.2f, 9f);
    }

    /** camada estática (só em tamanho()): gradiente, brilho atrás da armadura, hexágonos, piso em perspectiva, réguas e vinheta */
    private void fazerFundo() {
        Bitmap b = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888); Canvas k = new Canvas(b); Paint p = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.DITHER_FLAG);
        p.setShader(new LinearGradient(0, 0, 0, H, new int[]{0xff120903, 0xff0a0502, 0xff070402, 0xff040201}, new float[]{0f, 0.4f, 0.75f, 1f}, Shader.TileMode.CLAMP));
        k.drawRect(0, 0, W, H, p);
        float cx = armCx, cy = armT0 + armH * (deitado ? 0.3f : 0.36f), r = Math.max(W, H) * (deitado ? 0.42f : 0.5f);
        p.setShader(new RadialGradient(cx, cy, r, new int[]{0x904a1c06, 0x48301003, 0x00000000}, new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));
        k.drawRect(0, 0, W, H, p);
        // hexágonos finos no alto (alpha baixo), alguns acesos
        float hr = 11 * dp, hw = (float) Math.sqrt(3) * hr, alt = H * (deitado ? 0.7f : 0.44f); Path hp = new Path(), hf = new Path(); Random rnd = new Random(7);
        for (int row = 0; row * 1.5f * hr < alt + hr; row++) for (float x = (row % 2) * hw / 2 - hw; x < W + hw; x += hw) {
            float y = row * 1.5f * hr; boolean aceso = rnd.nextFloat() < 0.05f;
            for (int v = 0; v <= 6; v++) { double a = Math.toRadians(30 + 60 * v); float vx = x + (float) Math.cos(a) * hr * 0.9f, vy = y + (float) Math.sin(a) * hr * 0.9f;
                if (v == 0) { hp.moveTo(vx, vy); if (aceso) hf.moveTo(vx, vy); } else { hp.lineTo(vx, vy); if (aceso) hf.lineTo(vx, vy); } }
            if (aceso) hf.close();
        }
        int sl = k.saveLayer(0, 0, W, alt, null);
        p.setShader(null); p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(0.8f * dp); p.setColor(0x2cff9d24); k.drawPath(hp, p);
        p.setStyle(Paint.Style.FILL); p.setColor(0x16ff9d24); k.drawPath(hf, p);
        p.setXfermode(DST_IN); p.setShader(new LinearGradient(0, 0, 0, alt, new int[]{0xff000000, 0x70000000, 0x00000000}, new float[]{0f, 0.4f, 1f}, Shader.TileMode.CLAMP)); k.drawRect(0, 0, W, alt, p);
        p.setXfermode(null); p.setShader(null); k.restoreToCount(sl);
        if (!deitado) piso(k, p);
        // réguas laterais
        p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(1f * dp); p.setColor(0x40ff9d24);
        float y0 = H * (deitado ? 0.12f : 0.22f), y1 = H * (deitado ? 0.88f : 0.68f), passo = 8 * dp; int i = 0;
        for (float y = y0; y <= y1; y += passo, i++) { float l = i % 5 == 0 ? 9 * dp : 4.5f * dp; k.drawLine(5 * dp, y, 5 * dp + l, y, p); if (!deitado) k.drawLine(W - 5 * dp, y, W - 5 * dp - l, y, p); }
        // vinheta
        p.setStyle(Paint.Style.FILL);
        p.setShader(new RadialGradient(W / 2f, H * 0.45f, Math.max(W, H) * 0.72f, new int[]{0x00000000, 0x00000000, 0xc8000000}, new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP));
        k.drawRect(0, 0, W, H, p); p.setShader(null);
        fundo = b;
    }

    /** piso em perspectiva sob os pés: grade que converge para o ponto de fuga e some no horizonte e nas laterais */
    private void piso(Canvas k, Paint p) {
        float yh = pesY - R_HORIZ * H, s = pesY - yh, f = 4f * s, cel = 0.12f, cx = W / 2f;
        int sl = k.saveLayer(0, yh, W, H, null);
        p.setShader(null); p.setXfermode(null); p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(Math.max(1f, 0.9f * dp)); p.setColor(0xc0ff7700);
        float zb = s / (H - yh);
        for (int i = -60; i < 600; i++) { float z = 1f + i * cel; if (z < zb) continue; float y = yh + s / z; if (s / z - s / (z + cel) < 2.2f * dp) break; k.drawLine(0, y, W, y, p); }
        for (int j = -40; j <= 40; j++) { float xb = cx + j * cel * f / zb; if (Math.abs(xb - cx) > 5 * W) continue; k.drawLine(cx, yh, xb, H, p); }
        p.setStyle(Paint.Style.FILL); p.setXfermode(DST_IN);
        RadialGradient rg = new RadialGradient(cx, pesY, W * 0.66f, new int[]{0xff000000, 0xa0000000, 0x00000000}, new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP);
        Matrix mm = new Matrix(); mm.setScale(1f, 0.5f, cx, pesY); rg.setLocalMatrix(mm); p.setShader(rg); k.drawRect(0, yh, W, H, p);
        p.setShader(new LinearGradient(0, yh, 0, yh + s * 1.1f, 0x00000000, 0xff000000, Shader.TileMode.CLAMP)); k.drawRect(0, yh, W, H, p);
        p.setXfermode(null); k.restoreToCount(sl);
        RadialGradient gl = new RadialGradient(cx, pesY, W * 0.45f, new int[]{0x46ff7700, 0x14ff7700, 0x00000000}, new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP);
        Matrix m2 = new Matrix(); m2.setScale(1f, 0.32f, cx, pesY); gl.setLocalMatrix(m2); p.setShader(gl); k.drawRect(0, yh, W, H, p); p.setShader(null);
    }

    // =============================================== QUADROS ===============================================
    private void lerInfo() {
        corpo = new Fonte("papel/corpo");
        try (InputStream in = c.getAssets().open("papel/info.json")) {
            ByteArrayOutputStream bo = new ByteArrayOutputStream(); byte[] bb = new byte[4096]; int n; while ((n = in.read(bb)) > 0) bo.write(bb, 0, n);
            JSONObject j = new JSONObject(bo.toString("UTF-8"));
            JSONObject o = j.optJSONObject("corpo"); if (o != null) aplicar(corpo, o);
            JSONObject b = j.optJSONObject("busto");
            if (b != null && b.optInt("w") > 0) {
                String[] l = c.getAssets().list("papel/busto"); int nq = 0; if (l != null) for (String s : l) if (s.endsWith(".webp")) nq++;
                if (nq >= NQ) { busto = new Fonte("papel/busto"); busto.m0x = .16f; busto.m1x = .84f; busto.m0y = busto.m1y = .5f; aplicar(busto, b);
                    if (!b.has("maos")) { busto.m0y = busto.m1y = Math.min(0.8f, busto.py + 0.16f); } }
            }
        } catch (Throwable e) { Log.w(TAG, "info.json: " + e); }
        corpoBusto = corpo.copia(P_CORTE);
    }
    private static void aplicar(Fonte f, JSONObject o) {
        int w = o.optInt("w", f.w), h = o.optInt("h", f.h); if (w > 0 && h > 0) { f.w = w; f.h = h; }       // 0 no json = divisão por zero no layout
        f.pes = (float) o.optDouble("pes", f.pes); JSONArray a;
        if ((a = o.optJSONArray("peito")) != null) { f.px = (float) a.optDouble(0, f.px); f.py = (float) a.optDouble(1, f.py); }
        if ((a = o.optJSONArray("olhos")) != null) { f.ox = (float) a.optDouble(0, f.ox); f.oy = (float) a.optDouble(1, f.oy); }
        if ((a = o.optJSONArray("maos")) != null && a.length() >= 2) {
            JSONArray m0 = a.optJSONArray(0), m1 = a.optJSONArray(1);
            if (m0 != null) { f.m0x = (float) m0.optDouble(0, f.m0x); f.m0y = (float) m0.optDouble(1, f.m0y); }
            if (m1 != null) { f.m1x = (float) m1.optDouble(0, f.m1x); f.m1y = (float) m1.optDouble(1, f.m1y); }
        }
    }

    private static int dist(int a, int b) { int d = Math.abs(a - b) % NQ; return Math.min(d, NQ - d); }
    private boolean querido(int q) { int d = ((q - pedido) % NQ + NQ) % NQ; if (d > NQ / 2) d -= NQ; return sentido > 0 ? (d >= -1 && d <= 3) : (d >= -3 && d <= 1); }
    private boolean temIdx(int q) { for (int k = 0; k < NCACHE; k++) if (cIdx[k] == q) return true; return false; }

    private final Runnable rQuadros = new Runnable() { @Override public void run() {
        try { for (int n = 0; n < 10 && !liberado; n++) { int q = faltando(); if (q < 0 || !carregar(q)) break; } } catch (Throwable e) { Log.w(TAG, "quadros", e); }
    } };
    private int faltando() {
        int p = pedido, s = sentido;
        synchronized (trava) { for (int j = 0; j < 5; j++) { int q = ((p + ORDEM[s > 0 ? 0 : 1][j]) % NQ + NQ) % NQ; if (!temIdx(q)) return q; } }
        return -1;
    }

    /** decodifica o quadro idx num slot livre (nunca um em exibição nem um dos desejados) */
    private boolean carregar(int idx) {
        int s = -1, g; Fonte f; Bitmap reuso;
        synchronized (trava) {
            if (temIdx(idx)) return true;
            int melhor = -2;
            for (int k = 0; k < NCACHE; k++) {
                if (k == uso0 || k == uso1) continue;
                int q = cIdx[k], v = q < 0 ? 1000 : (querido(q) ? -1 : dist(q, pedido));
                if (v > melhor) { melhor = v; s = k; }
            }
            if (s < 0 || melhor < 0) return false;
            cIdx[s] = -1; g = geracao; f = fonteQ; reuso = cBmp[s];
        }
        Bitmap b = decodificar(f, idx, reuso);
        if (b == null) return false;
        synchronized (trava) { cBmp[s] = b; if (g == geracao && !liberado) cIdx[s] = idx; }
        return true;
    }

    private Bitmap decodificar(Fonte f, int idx, Bitmap reuso) {
        BitmapFactory.Options o = opc; o.inMutable = true; o.inPreferredConfig = Bitmap.Config.ARGB_8888; o.inScaled = false;
        o.inBitmap = reuso != null && !reuso.isRecycled() ? reuso : null;
        for (int tent = 0; tent < 2; tent++) {
            try (InputStream in = c.getAssets().open(f.nomes[idx])) {
                Bitmap b = BitmapFactory.decodeStream(in, null, o);
                if (b != null) { o.inBitmap = null; if (!sinc) b.prepareToDraw(); return b; }
            } catch (OutOfMemoryError e) { o.inBitmap = null; Log.w(TAG, "sem memória no quadro " + idx); return null; }
            catch (Throwable e) { if (o.inBitmap == null) { Log.w(TAG, "quadro " + idx + ": " + e); return null; } }
            o.inBitmap = null;
        }
        return null;
    }

    // =============================================== MÉTRICAS ===============================================
    private final Runnable rMet = new Runnable() { @Override public void run() {
        try { amostrar(); } catch (Throwable e) { Log.w(TAG, "métricas", e); }
        if (ativo && !liberado) hM.postDelayed(this, 1000);
    } };
    private final Runnable rLento = new Runnable() { @Override public void run() {
        try { lento(false); } catch (Throwable e) { Log.w(TAG, "rede/agenda", e); }
        if (ativo && !liberado) hL.postDelayed(this, 30000);
    } };

    private final float[] hist = new float[60]; private int histN, histPos; private long ultRx = -1, ultTx = -1, ultRede, ultDisco = -99999, discoLivre; private float discoV;
    private final long[] maxF = new long[8]; private final String[] fCur = new String[8], fMax = new String[8];
    private final ActivityManager.MemoryInfo mi = new ActivityManager.MemoryInfo(); private final IntentFilter fBat = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
    private volatile int pcEstado = -1; private volatile Prox prox; private long proxConsulta;
    { for (int k = 0; k < 8; k++) { fCur[k] = "/sys/devices/system/cpu/cpu" + k + "/cpufreq/scaling_cur_freq"; fMax[k] = "/sys/devices/system/cpu/cpu" + k + "/cpufreq/cpuinfo_max_freq"; } }

    /** PC online (faz rede) e próximo compromisso: thread própria para não travar a amostragem de 1 s */
    private void lento(boolean ja) {
        long agora = System.currentTimeMillis();
        if (ja || agora - proxConsulta >= 59000) {
            proxConsulta = agora; Prox achado = null;
            try {
                List<Agenda.Item> l = Agenda.itens(c, agora, agora + 48 * 3600000L);
                if (l != null) for (Agenda.Item it : l) if (!it.feito && !it.removido && it.fim > agora) { achado = new Prox(it.titulo == null ? "(sem título)" : it.titulo, it.ini, it.fim); break; }
            } catch (Throwable e) { Log.w(TAG, "agenda: " + e); }
            prox = achado;
        }
        try { pcEstado = Link.pcOnline(c) ? 1 : 0; } catch (Throwable e) { Log.w(TAG, "pcOnline: " + e); }
    }

    private void amostrar() {
        Metricas m = new Metricas(); long agE = SystemClock.elapsedRealtime(); m.ts = agE; m.uptime = agE;
        float s = 0; long fs = 0; int n = 0;
        for (int k = 0; k < 8; k++) {
            if (maxF[k] == 0) maxF[k] = lerNum(fMax[k]);                              // -1 = núcleo inexistente (re-tenta só a cada 30 s, sem exceção por segundo)
            long cur = maxF[k] > 0 ? lerNum(fCur[k]) : -1; if (cur <= 0) continue;
            float v = Math.min(1f, (float) cur / maxF[k]); m.nuc[n++] = v; s += v; fs += cur;
        }
        m.nNuc = n; m.cpu = n > 0 ? s / n : 0; m.ghz = n > 0 ? fs / (float) n / 1e6f : 0;
        try { ActivityManager am = (ActivityManager) c.getSystemService(Context.ACTIVITY_SERVICE); am.getMemoryInfo(mi);
            m.ramTotal = mi.totalMem; m.ramUsado = mi.totalMem - mi.availMem; m.ram = mi.totalMem > 0 ? (float) m.ramUsado / mi.totalMem : 0; } catch (Throwable ignored) {}
        if (agE - ultDisco >= 30000) { ultDisco = agE; for (int k = 0; k < 8; k++) if (maxF[k] < 0) maxF[k] = 0; try { StatFs sf = new StatFs(Environment.getDataDirectory().getPath()); discoLivre = sf.getAvailableBytes(); discoV = 1f - (float) sf.getAvailableBytes() / sf.getTotalBytes(); } catch (Throwable ignored) {} }
        m.disco = discoV; m.discoLivre = discoLivre;
        try { Intent b = c.registerReceiver(null, fBat);
            if (b != null) { m.bat = b.getIntExtra(BatteryManager.EXTRA_LEVEL, 0) / (float) Math.max(1, b.getIntExtra(BatteryManager.EXTRA_SCALE, 100));
                m.temp = b.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10f; int st = b.getIntExtra(BatteryManager.EXTRA_STATUS, -1), pl = b.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0);
                m.carregando = st == BatteryManager.BATTERY_STATUS_CHARGING || (pl != 0 && st == BatteryManager.BATTERY_STATUS_FULL); m.batOk = true; } } catch (Throwable ignored) {}
        try { long rx = TrafficStats.getTotalRxBytes(), tx = TrafficStats.getTotalTxBytes(), dtm = agE - ultRede;
            if (ultRx >= 0 && rx >= ultRx && tx >= ultTx && dtm > 0) { m.rx = (rx - ultRx) * 1000 / dtm; m.tx = (tx - ultTx) * 1000 / dtm; }
            if (rx >= 0) { ultRx = rx; ultTx = tx; ultRede = agE; } } catch (Throwable ignored) {}
        if (Build.VERSION.SDK_INT >= 29) try { PowerManager pm = (PowerManager) c.getSystemService(Context.POWER_SERVICE); if (pm != null) m.termico = pm.getCurrentThermalStatus(); } catch (Throwable ignored) {}
        hist[histPos] = m.cpu; histPos = (histPos + 1) % 60; histN = Math.min(60, histN + 1);
        m.hist = new float[histN]; for (int j = 0; j < histN; j++) m.hist[j] = hist[((histPos - histN + j) % 60 + 60) % 60];
        m.pc = pcEstado; Prox p = prox; if (p != null) { m.proxTitulo = p.titulo; m.proxIni = p.ini; m.proxFim = p.fim; }
        met = m;
    }
    private static long lerNum(String arq) { try (BufferedReader r = new BufferedReader(new FileReader(arq))) { String l = r.readLine(); return l == null ? -1 : Long.parseLong(l.trim()); } catch (Throwable e) { return -1; } }
}
