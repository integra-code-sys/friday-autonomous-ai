package dev.integra.friday;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.provider.CalendarContract;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/** Telas FLUTUANTES da Friday por cima de qualquer app, mesmo com a Friday fechada: quem as desenha é o Serviço de
 *  Acessibilidade (sempre ativo), com janelas TYPE_ACCESSIBILITY_OVERLAY (não precisa da permissão de sobreposição).
 *  - bolha: toque = abre a Friday já ouvindo (modo assistente); segurar = esconde.
 *  - painéis arrastáveis: agenda (próximos eventos), texto livre (notas, resultado de uma tarefa...). Toque no X fecha. */
final class Flutuante {
    private Flutuante() {}

    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final Map<String, View> abertos = new HashMap<>();
    private static final int CIANO = Color.rgb(54, 214, 255), FUNDO = Color.rgb(8, 16, 22);

    private static int dp(Context c, float v) { return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, c.getResources().getDisplayMetrics()); }

    private static WindowManager.LayoutParams params(Context c, int x, int y, boolean foco) {
        WindowManager.LayoutParams p = new WindowManager.LayoutParams(WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS | (foco ? 0 : WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE),
            PixelFormat.TRANSLUCENT);
        p.gravity = Gravity.TOP | Gravity.START;
        p.x = x; p.y = y;
        return p;
    }

    /** arrastar pela própria view; `toque` roda no toque curto, `longo` ao segurar */
    @SuppressLint("ClickableViewAccessibility")
    private static void arrastavel(View alca, View janela, WindowManager wm, WindowManager.LayoutParams p, Runnable toque, Runnable longo) {
        final float[] ini = new float[4];
        final long[] t0 = {0};
        final boolean[] moveu = {false};
        Runnable segurou = () -> { if (!moveu[0] && longo != null) { moveu[0] = true; longo.run(); } };
        alca.setOnTouchListener((v, e) -> {
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    ini[0] = p.x; ini[1] = p.y; ini[2] = e.getRawX(); ini[3] = e.getRawY(); t0[0] = System.currentTimeMillis(); moveu[0] = false;
                    main.postDelayed(segurou, 650);
                    return true;
                case MotionEvent.ACTION_MOVE:
                    float dx = e.getRawX() - ini[2], dy = e.getRawY() - ini[3];
                    if (Math.abs(dx) + Math.abs(dy) > 12) { moveu[0] = true; main.removeCallbacks(segurou); }
                    if (moveu[0]) { p.x = (int) (ini[0] + dx); p.y = (int) (ini[1] + dy); try { wm.updateViewLayout(janela, p); } catch (Exception ignored) {} }
                    return true;
                case MotionEvent.ACTION_UP:
                    main.removeCallbacks(segurou);
                    if (!moveu[0] && toque != null) toque.run();
                    return true;
            }
            return false;
        });
    }

    private static void fechar(Context c, String id) {
        View v = abertos.remove(id);
        if (v != null) try { ((WindowManager) c.getSystemService(Context.WINDOW_SERVICE)).removeView(v); } catch (Exception ignored) {}
    }

    static boolean aberto(String id) { return abertos.containsKey(id); }

    static void fecharTudo(Context c) {
        main.post(() -> { for (String id : new java.util.ArrayList<>(abertos.keySet())) fechar(c, id); Ide.setTela(null); });
    }

    // ------------------------------------------------------------------ bolha da Friday
    static void bolha(Context c, boolean mostrar) {
        main.post(() -> {
            fechar(c, "bolha");
            if (!mostrar) return;
            WindowManager wm = (WindowManager) c.getSystemService(Context.WINDOW_SERVICE);
            TextView b = new TextView(c);
            b.setText("F");
            b.setTypeface(Typeface.DEFAULT_BOLD);
            b.setTextColor(CIANO);
            b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
            b.setGravity(Gravity.CENTER);
            GradientDrawable g = new GradientDrawable();
            g.setShape(GradientDrawable.OVAL); g.setColor(FUNDO); g.setStroke(dp(c, 2), CIANO);
            b.setBackground(g);
            int s = dp(c, 52);
            WindowManager.LayoutParams p = params(c, c.getResources().getDisplayMetrics().widthPixels - s - dp(c, 8), dp(c, 220), false);
            p.width = s; p.height = s;
            arrastavel(b, b, wm, p,
                () -> c.startActivity(new Intent(c, MainActivity.class).putExtra("assistente", true)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)),
                () -> { fechar(c, "bolha"); c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).edit().putBoolean("bolha", false).apply(); });
            try { wm.addView(b, p); abertos.put("bolha", b); } catch (Exception e) { android.util.Log.w("friday-flut", "bolha: " + e); }
        });
    }

    // ------------------------------------------------------------------ painel de texto
    static void painel(Context c, String id, String titulo, String texto) {
        main.post(() -> {
            fechar(c, id);
            WindowManager wm = (WindowManager) c.getSystemService(Context.WINDOW_SERVICE);
            LinearLayout caixa = new LinearLayout(c);
            caixa.setOrientation(LinearLayout.VERTICAL);
            int pd = dp(c, 12);
            caixa.setPadding(pd, dp(c, 8), pd, pd);
            GradientDrawable g = new GradientDrawable();
            g.setColor(FUNDO); g.setCornerRadius(dp(c, 14)); g.setStroke(dp(c, 1), Color.argb(160, 54, 214, 255));
            caixa.setBackground(g);
            LinearLayout topo = new LinearLayout(c);
            topo.setOrientation(LinearLayout.HORIZONTAL);
            topo.setGravity(Gravity.CENTER_VERTICAL);
            TextView t = new TextView(c);
            t.setText(titulo.toUpperCase(Locale.ROOT));
            t.setTextColor(CIANO); t.setTypeface(Typeface.MONOSPACE, Typeface.BOLD); t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
            t.setLetterSpacing(0.15f);
            topo.addView(t, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
            TextView x = new TextView(c);
            x.setText("X"); x.setTextColor(Color.argb(200, 255, 255, 255)); x.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
            x.setPadding(dp(c, 12), dp(c, 4), dp(c, 2), dp(c, 4));
            x.setOnClickListener(v -> fechar(c, id));
            topo.addView(x);
            caixa.addView(topo);
            TextView corpo = new TextView(c);
            corpo.setText(texto);
            corpo.setTextColor(Color.argb(235, 230, 240, 245)); corpo.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
            corpo.setLineSpacing(dp(c, 2), 1f);
            ScrollView rol = new ScrollView(c);
            rol.addView(corpo);
            caixa.addView(rol, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
            int w = (int) (c.getResources().getDisplayMetrics().widthPixels * 0.78f);
            WindowManager.LayoutParams p = params(c, dp(c, 16), dp(c, 140) + abertos.size() * dp(c, 40), false);
            p.width = w;
            p.height = WindowManager.LayoutParams.WRAP_CONTENT;
            caixa.setMinimumWidth(w);
            rol.setLayoutParams(new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                Math.min(dp(c, 360), Math.max(dp(c, 60), corpo.getLineHeight() * Math.min(18, texto.split("\n").length + 2)))));
            arrastavel(topo, caixa, wm, p, null, null);
            try { wm.addView(caixa, p); abertos.put(id, caixa); } catch (Exception e) { android.util.Log.w("friday-flut", "painel: " + e); }
        });
    }

    // ------------------------------------------------------------------ IDE do MODO DEV autônomo (Friday operando o Claude)
    // Layout: alça + cabeçalho (estado, objetivo, rodadas) | log ao vivo | barra de botões grandes com rótulo.
    private static TextView ideTexto, ideEstado, ideObj, idePausa, ideParar, ideRodada, ideAoVivo, ideAltura;
    private static View idePonto;
    private static LinearLayout ideSegs;
    private static ScrollView ideRolo;
    private static boolean ideSeguir = true, ideConfirma;
    private static final android.text.SpannableStringBuilder ideBuf = new android.text.SpannableStringBuilder();
    private static final int VERDE = Color.rgb(108, 196, 143), VERMELHO = Color.rgb(255, 107, 107), AMBAR = Color.rgb(255, 179, 71),
        TEXTO2 = Color.argb(150, 190, 205, 212);

    private static int corTipo(String t) {
        switch (t) {
            case "prompt": return AMBAR;
            case "claude": return Color.rgb(235, 242, 245);
            case "arquivo": case "ferr": return CIANO;
            case "mais": case "ok": return VERDE;
            case "menos": case "erro": return VERMELHO;
            case "bash": return Color.rgb(229, 192, 123);
            case "todo": return Color.rgb(192, 132, 252);
            case "fim": return Color.argb(200, 54, 214, 255);
            default: return TEXTO2;
        }
    }

    private static int corEstado(String e) {
        return e.startsWith("final") ? VERDE : e.startsWith("erro") || e.startsWith("parad") || e.startsWith("limite") ? VERMELHO
            : e.startsWith("paus") || e.startsWith("aguard") ? AMBAR : CIANO;
    }

    private static boolean noFim() {
        if (ideRolo == null || ideRolo.getChildCount() == 0) return true;
        return ideRolo.getScrollY() + ideRolo.getHeight() >= ideRolo.getChildAt(0).getHeight() - dp(ideRolo.getContext(), 40);
    }

    private static void ideAppend(java.util.List<String[]> ls) {
        for (String[] l : ls) {
            String t = l[0];
            boolean bloco = t.equals("claude") || t.equals("prompt") || t.equals("arquivo") || t.equals("fim") || t.equals("ok");
            if (bloco && ideBuf.length() > 0) {                        // respiro entre blocos (meia linha)
                int a = ideBuf.length();
                ideBuf.append("\n");
                ideBuf.setSpan(new android.text.style.RelativeSizeSpan(0.5f), a, ideBuf.length(), 0);
            }
            int ini = ideBuf.length();
            String pre = t.equals("claude") ? "◆ " : t.equals("prompt") ? "» " : t.equals("fim") ? "── " : "";
            ideBuf.append(pre).append(l[1]).append("\n");
            int fim = ideBuf.length();
            ideBuf.setSpan(new android.text.style.ForegroundColorSpan(corTipo(t)), ini, fim, 0);
            if (t.equals("claude") || t.equals("prompt")) {          // conversa: fonte normal, maior
                ideBuf.setSpan(new android.text.style.TypefaceSpan("sans-serif"), ini, fim, 0);
                ideBuf.setSpan(new android.text.style.RelativeSizeSpan(1.12f), ini, fim, 0);
            }
            if (t.equals("mais")) ideBuf.setSpan(new android.text.style.BackgroundColorSpan(Color.argb(40, 108, 196, 143)), ini, fim - 1, 0);
            if (t.equals("menos")) ideBuf.setSpan(new android.text.style.BackgroundColorSpan(Color.argb(40, 255, 107, 107)), ini, fim - 1, 0);
            if (t.equals("ok") || t.equals("arquivo") || t.equals("prompt") || t.equals("erro"))
                ideBuf.setSpan(new android.text.style.StyleSpan(Typeface.BOLD), ini, fim, 0);
        }
        if (ideBuf.length() > 60000) ideBuf.delete(0, ideBuf.length() - 50000);
        if (ideTexto == null) return;
        boolean seguir = ideSeguir && noFim();
        ideTexto.setText(ideBuf.length() == 0 ? vazio() : ideBuf);
        if (seguir) ideRolo.post(() -> ideRolo.fullScroll(View.FOCUS_DOWN));
        else if (ideAoVivo != null && !ls.isEmpty()) ideAoVivo.setVisibility(View.VISIBLE);
    }

    private static CharSequence vazio() {
        return "Nenhuma tarefa rodando.\n\nPeça por voz: \"modo dev: crie um site de receitas em ~/dev/receitas\" — eu escrevo o prompt, "
            + "acompanho o Claude aqui ao vivo e reviso até ficar pronto.";
    }

    private static void ideEstadoUi(String e, int r) {
        View pill0 = abertos.get("ide_min");
        if (pill0 instanceof TextView) {
            ((TextView) pill0).setText("●  IDE  " + r + "/" + Ide.MAX_RODADAS + "  ·  " + e);
            ((TextView) pill0).setTextColor(corEstado(e));
        }
        if (ideEstado == null) return;
        int cor = corEstado(e);
        ideEstado.setText(e.toUpperCase(new Locale("pt", "BR")));
        ideEstado.setTextColor(cor);
        ((GradientDrawable) idePonto.getBackground()).setColor(cor);
        ideRodada.setText("RODADA " + r + "/" + Ide.MAX_RODADAS);
        for (int i = 0; i < ideSegs.getChildCount(); i++)
            ((GradientDrawable) ideSegs.getChildAt(i).getBackground()).setColor(i < r ? (i == r - 1 ? cor : Color.argb(170, 54, 214, 255)) : Color.argb(45, 255, 255, 255));
        String obj = Ide.objetivo();
        ideObj.setText(obj.isEmpty() ? "Sem tarefa" : obj);
        boolean ativa = Ide.ativa();
        idePausa.setText(Ide.pausada() ? "Continuar" : "Pausar");
        idePausa.setEnabled(ativa); idePausa.setAlpha(ativa ? 1f : 0.35f);
        ideParar.setEnabled(ativa); ideParar.setAlpha(ativa ? 1f : 0.35f);
    }

    /** botão de toque confortável (48 dp), com fundo tingido e rótulo */
    private static TextView ideBotao(Context c, String t, int cor, Runnable r) {
        TextView b = tv(c, t, cor, 13, Typeface.BOLD);
        b.setGravity(Gravity.CENTER);
        b.setSingleLine(true);
        b.setMinHeight(dp(c, 48));
        b.setPadding(dp(c, 6), 0, dp(c, 6), 0);
        GradientDrawable g = new GradientDrawable();
        g.setColor(Color.argb(38, Color.red(cor), Color.green(cor), Color.blue(cor)));
        g.setStroke(dp(c, 1), Color.argb(110, Color.red(cor), Color.green(cor), Color.blue(cor)));
        g.setCornerRadius(dp(c, 12));
        b.setBackground(new android.graphics.drawable.RippleDrawable(android.content.res.ColorStateList.valueOf(Color.argb(90, 255, 255, 255)), g, null));
        b.setOnClickListener(v -> r.run());
        return b;
    }

    private static LinearLayout.LayoutParams peso(Context c, boolean ultimo) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        if (!ultimo) lp.setMarginEnd(dp(c, 8));
        return lp;
    }

    private static boolean ideGrande(Context c) { return c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getBoolean("ide_grande", false); }

    static void ide(Context c, boolean mostrar) {
        main.post(() -> {
            fechar(c, "ide"); fechar(c, "ide_min");
            if (!mostrar) { Ide.setTela(null); ideTexto = null; ideEstado = null; return; }
            WindowManager wm = (WindowManager) c.getSystemService(Context.WINDOW_SERVICE);
            int W = c.getResources().getDisplayMetrics().widthPixels, H = c.getResources().getDisplayMetrics().heightPixels;
            ideSeguir = true; ideConfirma = false;
            LinearLayout caixa = new LinearLayout(c);
            caixa.setOrientation(LinearLayout.VERTICAL);
            caixa.setPadding(dp(c, 14), dp(c, 6), dp(c, 14), dp(c, 14));
            GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{Color.rgb(12, 24, 32), Color.rgb(6, 10, 14)});
            g.setCornerRadius(dp(c, 22)); g.setStroke(dp(c, 1), Color.argb(120, 54, 214, 255));
            caixa.setBackground(g);
            caixa.setElevation(dp(c, 12));

            // ---- cabeçalho = alça de arrastar (toque duplo alterna tamanho)
            LinearLayout cab = new LinearLayout(c);
            cab.setOrientation(LinearLayout.VERTICAL);
            View alca = new View(c);
            GradientDrawable ga = new GradientDrawable(); ga.setColor(Color.argb(90, 255, 255, 255)); ga.setCornerRadius(dp(c, 3));
            alca.setBackground(ga);
            LinearLayout.LayoutParams lpa = new LinearLayout.LayoutParams(dp(c, 40), dp(c, 4));
            lpa.gravity = Gravity.CENTER_HORIZONTAL; lpa.bottomMargin = dp(c, 8);
            cab.addView(alca, lpa);
            LinearLayout l1 = new LinearLayout(c);
            l1.setOrientation(LinearLayout.HORIZONTAL);
            l1.setGravity(Gravity.CENTER_VERTICAL);
            idePonto = new View(c);
            GradientDrawable gp = new GradientDrawable(); gp.setShape(GradientDrawable.OVAL); gp.setColor(CIANO);
            idePonto.setBackground(gp);
            LinearLayout.LayoutParams lpp = new LinearLayout.LayoutParams(dp(c, 8), dp(c, 8)); lpp.setMarginEnd(dp(c, 8));
            l1.addView(idePonto, lpp);
            ideEstado = tv(c, "", CIANO, 11, Typeface.BOLD);
            ideEstado.setTypeface(Typeface.MONOSPACE, Typeface.BOLD); ideEstado.setLetterSpacing(0.08f); ideEstado.setSingleLine(true);
            ideEstado.setEllipsize(android.text.TextUtils.TruncateAt.END);
            l1.addView(ideEstado, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
            ideRodada = tv(c, "", TEXTO2, 10, Typeface.BOLD);
            ideRodada.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            l1.addView(ideRodada);
            ideAltura = tv(c, ideGrande(c) ? "REDUZIR" : "AMPLIAR", CIANO, 10, Typeface.BOLD);
            ideAltura.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            ideAltura.setGravity(Gravity.CENTER);
            GradientDrawable gz = new GradientDrawable(); gz.setCornerRadius(dp(c, 10)); gz.setStroke(dp(c, 1), Color.argb(110, 54, 214, 255));
            ideAltura.setBackground(gz);
            ideAltura.setOnClickListener(v -> {
                c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).edit().putBoolean("ide_grande", !ideGrande(c)).apply();
                ide(c, true);
            });
            LinearLayout.LayoutParams lpz = new LinearLayout.LayoutParams(dp(c, 84), dp(c, 36)); lpz.setMarginStart(dp(c, 10));
            l1.addView(ideAltura, lpz);
            cab.addView(l1);
            ideObj = tv(c, "", Color.WHITE, 15, Typeface.BOLD);
            ideObj.setMaxLines(2); ideObj.setEllipsize(android.text.TextUtils.TruncateAt.END);
            ideObj.setPadding(0, dp(c, 2), 0, dp(c, 8));
            cab.addView(ideObj);
            ideSegs = new LinearLayout(c);
            ideSegs.setOrientation(LinearLayout.HORIZONTAL);
            for (int i = 0; i < Ide.MAX_RODADAS; i++) {
                View s = new View(c);
                GradientDrawable gs = new GradientDrawable(); gs.setCornerRadius(dp(c, 2)); gs.setColor(Color.argb(45, 255, 255, 255));
                s.setBackground(gs);
                LinearLayout.LayoutParams lps = new LinearLayout.LayoutParams(0, dp(c, 4), 1f);
                if (i < Ide.MAX_RODADAS - 1) lps.setMarginEnd(dp(c, 4));
                ideSegs.addView(s, lps);
            }
            cab.addView(ideSegs);
            caixa.addView(cab);

            // ---- log ao vivo
            android.widget.FrameLayout quadro = new android.widget.FrameLayout(c);
            ideRolo = new ScrollView(c);
            GradientDrawable gt = new GradientDrawable();
            gt.setColor(Color.argb(255, 3, 6, 9)); gt.setCornerRadius(dp(c, 14)); gt.setStroke(dp(c, 1), Color.argb(30, 255, 255, 255));
            ideRolo.setBackground(gt);
            ideRolo.setVerticalScrollBarEnabled(true);
            ideRolo.setOnScrollChangeListener((v, x, y, ox, oy) -> {
                boolean f = noFim();
                ideSeguir = f;
                if (f && ideAoVivo != null) ideAoVivo.setVisibility(View.GONE);
            });
            ideTexto = tv(c, "", Color.WHITE, 12, Typeface.NORMAL);
            ideTexto.setTypeface(Typeface.MONOSPACE);
            ideTexto.setLineSpacing(dp(c, 2), 1f);
            ideTexto.setPadding(dp(c, 12), dp(c, 10), dp(c, 12), dp(c, 10));
            ideRolo.addView(ideTexto);
            quadro.addView(ideRolo);
            ideAoVivo = tv(c, "↓  ao vivo", Color.rgb(3, 6, 9), 12, Typeface.BOLD);
            ideAoVivo.setPadding(dp(c, 14), dp(c, 8), dp(c, 14), dp(c, 8));
            GradientDrawable gv = new GradientDrawable(); gv.setColor(CIANO); gv.setCornerRadius(dp(c, 16));
            ideAoVivo.setBackground(gv);
            ideAoVivo.setVisibility(View.GONE);
            ideAoVivo.setOnClickListener(v -> { ideSeguir = true; ideAoVivo.setVisibility(View.GONE); ideRolo.fullScroll(View.FOCUS_DOWN); });
            android.widget.FrameLayout.LayoutParams lpv = new android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.WRAP_CONTENT, android.widget.FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
            lpv.bottomMargin = dp(c, 10);
            quadro.addView(ideAoVivo, lpv);
            LinearLayout.LayoutParams lpq = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, (int) (H * (ideGrande(c) ? 0.62f : 0.36f)));
            lpq.topMargin = dp(c, 10); lpq.bottomMargin = dp(c, 10);
            caixa.addView(quadro, lpq);

            // ---- barra de ações (botões grandes, com rótulo)
            LinearLayout acoes = new LinearLayout(c);
            acoes.setOrientation(LinearLayout.HORIZONTAL);
            idePausa = ideBotao(c, "Pausar", AMBAR, () -> Ide.pausar(!Ide.pausada()));
            acoes.addView(idePausa, peso(c, false));
            ideParar = ideBotao(c, "Parar", VERMELHO, null);
            Runnable desarma = () -> { ideConfirma = false; if (ideParar != null) ideParar.setText("Parar"); };
            ideParar.setOnClickListener(v -> {                         // 2 toques: evita matar o Claude sem querer
                if (!ideConfirma) { ideConfirma = true; ideParar.setText("Confirmar?"); main.postDelayed(desarma, 3000); return; }
                main.removeCallbacks(desarma); desarma.run(); Ide.parar();
            });
            acoes.addView(ideParar, peso(c, false));
            acoes.addView(ideBotao(c, "Minimizar", CIANO, () -> ideMinimizar(c)), peso(c, false));
            acoes.addView(ideBotao(c, "Fechar", Color.argb(220, 210, 220, 226), () -> ide(c, false)), peso(c, true));
            caixa.addView(acoes);

            ideBuf.clear();
            ideAppend(Ide.todas());
            ideEstadoUi(Ide.estado(), Ide.rodada());
            Ide.setTela(new Ide.Tela() {
                @Override public void linhas(java.util.List<String[]> n) { main.post(() -> ideAppend(n)); }
                @Override public void estado(String e, int r) { main.post(() -> ideEstadoUi(e, r)); }
            });
            int w = W - dp(c, 16);
            WindowManager.LayoutParams p = params(c, (W - w) / 2, dp(c, 48), false);
            p.width = w;
            final long[] ultimoToque = {0};
            arrastavel(cab, caixa, wm, p, () -> {                     // toque duplo no cabeçalho = alterna tamanho
                long t = System.currentTimeMillis();
                if (t - ultimoToque[0] < 350) ideAltura.performClick();
                ultimoToque[0] = t;
            }, () -> ideMinimizar(c));
            try { wm.addView(caixa, p); abertos.put("ide", caixa); } catch (Exception e) { android.util.Log.w("friday-flut", "ide: " + e); }
        });
    }

    private static void ideMinimizar(Context c) {
        main.post(() -> {
            fechar(c, "ide"); fechar(c, "ide_min");
            ideEstado = null; ideTexto = null;
            Ide.setTela(new Ide.Tela() {
                @Override public void linhas(java.util.List<String[]> n) {}
                @Override public void estado(String e, int r) { main.post(() -> ideEstadoUi(e, r)); }
            });
            WindowManager wm = (WindowManager) c.getSystemService(Context.WINDOW_SERVICE);
            TextView pill = tv(c, "", CIANO, 12, Typeface.BOLD);
            pill.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            pill.setPadding(dp(c, 16), dp(c, 12), dp(c, 16), dp(c, 12));
            pill.setMinHeight(dp(c, 44));
            pill.setGravity(Gravity.CENTER_VERTICAL);
            GradientDrawable g = new GradientDrawable();
            g.setColor(Color.rgb(8, 14, 19)); g.setCornerRadius(dp(c, 24)); g.setStroke(dp(c, 1), Color.argb(150, 54, 214, 255));
            pill.setBackground(g);
            pill.setElevation(dp(c, 8));
            WindowManager.LayoutParams p = params(c, dp(c, 12), dp(c, 90), false);
            arrastavel(pill, pill, wm, p, () -> ide(c, true), () -> ide(c, false));   // toque = abre; segurar = fecha
            try { wm.addView(pill, p); abertos.put("ide_min", pill); } catch (Exception e) { android.util.Log.w("friday-flut", "pill: " + e); }
            ideEstadoUi(Ide.estado(), Ide.rodada());
        });
    }

    // ------------------------------------------------------------------ AGENDA flutuante (cartão completo)
    static final class Evento { String titulo, local; long ini, fim; boolean diaTodo; int cor; }

    static java.util.List<Evento> eventos(Context c, int dias) {
        java.util.List<Evento> l = new java.util.ArrayList<>();
        if (c.checkSelfPermission(android.Manifest.permission.READ_CALENDAR) != android.content.pm.PackageManager.PERMISSION_GRANTED) return null;
        Calendar hoje = Calendar.getInstance();
        hoje.set(Calendar.HOUR_OF_DAY, 0); hoje.set(Calendar.MINUTE, 0); hoje.set(Calendar.SECOND, 0);
        long ini = hoje.getTimeInMillis(), fim = ini + dias * 86400000L;
        android.net.Uri.Builder u = CalendarContract.Instances.CONTENT_URI.buildUpon();
        android.content.ContentUris.appendId(u, ini); android.content.ContentUris.appendId(u, fim);
        try (Cursor cur = c.getContentResolver().query(u.build(), new String[]{CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN,
                CalendarContract.Instances.END, CalendarContract.Instances.ALL_DAY, CalendarContract.Instances.EVENT_LOCATION,
                CalendarContract.Instances.DISPLAY_COLOR}, null, null, CalendarContract.Instances.BEGIN + " ASC")) {
            while (cur != null && cur.moveToNext() && l.size() < 40) {
                Evento e = new Evento();
                e.titulo = cur.getString(0) == null ? "(sem título)" : cur.getString(0);
                e.ini = cur.getLong(1); e.fim = cur.getLong(2); e.diaTodo = cur.getInt(3) == 1;
                e.local = cur.getString(4); e.cor = cur.getInt(5) == 0 ? CIANO : (cur.getInt(5) | 0xFF000000);
                l.add(e);
            }
        } catch (Exception ignored) {}
        return l;
    }

    private static TextView tv(Context c, String t, int cor, float sp, int estilo) {
        TextView v = new TextView(c);
        v.setText(t); v.setTextColor(cor); v.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp); v.setTypeface(Typeface.DEFAULT, estilo);
        return v;
    }

    private static java.util.List<Agenda.Item> demo;
    private static int agDia;                                       // dia escolhido (0 = hoje)
    private static LinearLayout agCorpo;
    private static TextView agStatus, agSub;

    /** só para conferir o visual: eventos fictícios (não toca na agenda real) */
    static void agendaDemo(Context c) {
        java.util.List<Agenda.Item> l = new java.util.ArrayList<>();
        long h = System.currentTimeMillis(), m = 60000;
        Object[][] d = {{"Reunião com cliente Cerealista", "Google Meet", -150, -90, Color.rgb(121, 134, 203), 1, true, "google"},
            {"Almoço", null, -60, 30, Color.rgb(51, 182, 121), 3, false, "pc"}, {"Revisão do APK da Friday", "Escritório", 70, 130, CIANO, 1, false, "pc"},
            {"Ligar para o contador", null, 100, 120, CIANO, 2, false, "pc"}, {"Academia", "Smart Fit", 300, 360, Color.rgb(246, 191, 38), 3, false, "pc"},
            {"Entrega NFS-e", null, 24 * 60 + 120, 24 * 60 + 180, Color.rgb(230, 124, 115), 1, false, "pc"},
            {"Dentista", "Centro", 48 * 60 + 60, 48 * 60 + 100, Color.rgb(142, 36, 170), 2, false, "google"}};
        for (Object[] o : d) {
            Agenda.Item e = new Agenda.Item();
            e.id = "demo" + l.size(); e.titulo = (String) o[0]; e.local = o[1] == null ? "" : (String) o[1];
            e.ini = h + (int) o[2] * m; e.fim = h + (int) o[3] * m; e.cor = (int) o[4]; e.prio = (int) o[5]; e.feito = (boolean) o[6]; e.fonte = (String) o[7];
            l.add(e);
        }
        demo = l; agDia = 0;
        agendaPainel(c);
    }

    static void agendaPainel(Context c) {
        main.post(() -> {
            fechar(c, "agenda");
            WindowManager wm = (WindowManager) c.getSystemService(Context.WINDOW_SERVICE);
            Locale br = new Locale("pt", "BR");
            int W = c.getResources().getDisplayMetrics().widthPixels;
            LinearLayout caixa = new LinearLayout(c);
            caixa.setOrientation(LinearLayout.VERTICAL);
            caixa.setPadding(dp(c, 16), dp(c, 6), dp(c, 16), dp(c, 16));
            GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{Color.rgb(12, 24, 32), Color.rgb(6, 10, 14)});
            g.setCornerRadius(dp(c, 24)); g.setStroke(dp(c, 1), Color.argb(110, 54, 214, 255));
            caixa.setBackground(g);
            caixa.setElevation(dp(c, 12));

            // ---- cabeçalho (alça): bloco do dia + mês + status da sincronização + fechar
            LinearLayout cab = new LinearLayout(c);
            cab.setOrientation(LinearLayout.VERTICAL);
            View alca = new View(c);
            GradientDrawable ga = new GradientDrawable(); ga.setColor(Color.argb(90, 255, 255, 255)); ga.setCornerRadius(dp(c, 3));
            alca.setBackground(ga);
            LinearLayout.LayoutParams lpa = new LinearLayout.LayoutParams(dp(c, 40), dp(c, 4));
            lpa.gravity = Gravity.CENTER_HORIZONTAL; lpa.bottomMargin = dp(c, 10);
            cab.addView(alca, lpa);
            LinearLayout topo = new LinearLayout(c);
            topo.setOrientation(LinearLayout.HORIZONTAL);
            topo.setGravity(Gravity.CENTER_VERTICAL);
            LinearLayout dia = new LinearLayout(c);
            dia.setOrientation(LinearLayout.VERTICAL);
            dia.setGravity(Gravity.CENTER);
            GradientDrawable gd = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{Color.rgb(40, 190, 240), Color.rgb(18, 100, 160)});
            gd.setCornerRadius(dp(c, 16));
            dia.setBackground(gd);
            TextView sem = tv(c, new SimpleDateFormat("EEE", br).format(new Date()).replace(".", "").toUpperCase(br), Color.argb(220, 255, 255, 255), 10, Typeface.BOLD);
            sem.setLetterSpacing(0.15f); sem.setGravity(Gravity.CENTER);
            dia.addView(sem, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
            TextView num = tv(c, new SimpleDateFormat("d", br).format(new Date()), Color.WHITE, 24, Typeface.BOLD);
            num.setIncludeFontPadding(false); num.setGravity(Gravity.CENTER);
            dia.addView(num, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
            topo.addView(dia, new LinearLayout.LayoutParams(dp(c, 58), dp(c, 58)));
            LinearLayout tit = new LinearLayout(c);
            tit.setOrientation(LinearLayout.VERTICAL);
            tit.setPadding(dp(c, 14), 0, 0, 0);
            TextView rot = tv(c, "AGENDA · PC + CELULAR", CIANO, 10, Typeface.BOLD);
            rot.setLetterSpacing(0.25f); rot.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            tit.addView(rot);
            String mes = new SimpleDateFormat("MMMM 'de' yyyy", br).format(new Date());
            tit.addView(tv(c, Character.toUpperCase(mes.charAt(0)) + mes.substring(1), Color.WHITE, 18, Typeface.BOLD));
            agStatus = tv(c, "", TEXTO2, 11, Typeface.NORMAL);
            agStatus.setSingleLine(true); agStatus.setEllipsize(android.text.TextUtils.TruncateAt.END);
            tit.addView(agStatus);
            topo.addView(tit, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
            TextView x = tv(c, "X", Color.argb(220, 255, 255, 255), 17, Typeface.NORMAL);
            x.setGravity(Gravity.CENTER);
            GradientDrawable gx = new GradientDrawable(); gx.setShape(GradientDrawable.OVAL); gx.setColor(Color.argb(30, 255, 255, 255));
            x.setBackground(gx);
            x.setOnClickListener(v -> fecharAgenda(c));
            topo.addView(x, new LinearLayout.LayoutParams(dp(c, 40), dp(c, 40)));
            cab.addView(topo);
            caixa.addView(cab);

            agCorpo = new LinearLayout(c);
            agCorpo.setOrientation(LinearLayout.VERTICAL);
            caixa.addView(agCorpo, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

            // ---- ações
            LinearLayout acoes = new LinearLayout(c);
            acoes.setOrientation(LinearLayout.HORIZONTAL);
            acoes.setPadding(0, dp(c, 12), 0, 0);
            acoes.addView(ideBotao(c, "＋  Novo", CIANO, () -> Assistente.falarCom(c, "Diga o compromisso: \"reunião amanhã às 15h, prioridade alta\".")), peso(c, false));
            acoes.addView(ideBotao(c, "↻  Sincronizar", VERDE, () -> {
                if (agStatus != null) agStatus.setText("sincronizando…");
                Agenda.sincronizarJa(c);
                main.postDelayed(() -> agendaRender(c), 4000);
            }), peso(c, false));
            acoes.addView(ideBotao(c, "↗  No App", Color.argb(220, 210, 220, 226), () -> abrir(c, new Intent(c, MainActivity.class)
                .putExtra("aba", "agenda").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP))), peso(c, true));
            caixa.addView(acoes);

            int w = W - dp(c, 16);
            WindowManager.LayoutParams p = params(c, (W - w) / 2, dp(c, 70), false);
            p.width = w;
            arrastavel(cab, caixa, wm, p, null, () -> fecharAgenda(c));
            try { wm.addView(caixa, p); abertos.put("agenda", caixa); } catch (Exception e) { android.util.Log.w("friday-flut", "agenda: " + e); }
            agendaRender(c);
            if (demo == null) {
                Agenda.aoMudar = () -> main.post(() -> agendaRender(c));
                Agenda.sincronizarJa(c);
            }
        });
    }

    private static void fecharAgenda(Context c) {
        Agenda.aoMudar = null; demo = null; agDia = 0;
        fechar(c, "agenda");
    }

    /** redesenha o miolo (dias, nível, foco, próximo, linha do tempo) sem mexer na janela */
    private static void agendaRender(Context c) {
        final java.util.List<Agenda.Item> dm = demo;
        new Thread(() -> {
            long hoje = Agenda.inicioDoDia(System.currentTimeMillis());
            java.util.List<Agenda.Item> todos = dm != null ? dm : Agenda.itens(c, hoje - 86400000L, hoje + 8 * 86400000L);
            String st = dm != null ? "demonstração · eventos fictícios" : Agenda.status(c);
            main.post(() -> agendaRender(c, todos, st));
        }, "friday-agenda-ui").start();
    }

    private static void agendaRender(Context c, java.util.List<Agenda.Item> todos, String status) {
        if (agCorpo == null || !abertos.containsKey("agenda")) return;
        Locale br = new Locale("pt", "BR");
        int H = c.getResources().getDisplayMetrics().heightPixels;
        long agora = System.currentTimeMillis(), hoje = Agenda.inicioDoDia(agora), diaSel = hoje + agDia * 86400000L;
        SimpleDateFormat fh = new SimpleDateFormat("HH:mm", Locale.ROOT);
        agStatus.setText((status.startsWith("sincronizado") ? "● " : "○ ") + status);
        agStatus.setTextColor(status.startsWith("sincronizado") ? Color.argb(200, 108, 196, 143) : status.startsWith("demonstra") ? TEXTO2 : Color.argb(220, 255, 179, 71));
        agCorpo.removeAllViews();

        // ---- dias (chips com o nível de cada dia)
        android.widget.HorizontalScrollView hs = new android.widget.HorizontalScrollView(c);
        hs.setHorizontalScrollBarEnabled(false);
        LinearLayout dias = new LinearLayout(c);
        dias.setOrientation(LinearLayout.HORIZONTAL);
        for (int k = 0; k < 7; k++) {
            final int kk = k;
            long d0 = hoje + k * 86400000L;
            Agenda.Nivel nk = Agenda.nivel(todos, d0);
            boolean sel = k == agDia;
            LinearLayout chip = new LinearLayout(c);
            chip.setOrientation(LinearLayout.VERTICAL);
            chip.setGravity(Gravity.CENTER);
            chip.setPadding(dp(c, 12), dp(c, 6), dp(c, 12), dp(c, 7));
            GradientDrawable gc = new GradientDrawable(); gc.setCornerRadius(dp(c, 14));
            gc.setColor(sel ? Color.argb(60, 54, 214, 255) : Color.argb(18, 255, 255, 255));
            gc.setStroke(dp(c, 1), sel ? CIANO : Color.argb(25, 255, 255, 255));
            chip.setBackground(gc);
            String nome = k == 0 ? "HOJE" : k == 1 ? "AMANHÃ" : new SimpleDateFormat("EEE d", br).format(new Date(d0)).replace(".", "").toUpperCase(br);
            TextView tn = tv(c, nome, sel ? Color.WHITE : Color.argb(190, 220, 235, 240), 11, Typeface.BOLD);
            tn.setLetterSpacing(0.08f);
            chip.addView(tn);
            LinearLayout lin = new LinearLayout(c);
            lin.setOrientation(LinearLayout.HORIZONTAL);
            lin.setGravity(Gravity.CENTER_VERTICAL);
            View bola = new View(c);
            GradientDrawable gb = new GradientDrawable(); gb.setShape(GradientDrawable.OVAL); gb.setColor(Agenda.corNivel(nk.nivel));
            bola.setBackground(gb);
            lin.addView(bola, new LinearLayout.LayoutParams(dp(c, 6), dp(c, 6)));
            TextView qt = tv(c, " " + (nk.total == 0 ? "livre" : nk.total + (nk.total > 1 ? " itens" : " item")), TEXTO2, 9, Typeface.NORMAL);
            lin.addView(qt);
            chip.addView(lin);
            chip.setOnClickListener(v -> { agDia = kk; agendaRender(c, todos, status); });
            LinearLayout.LayoutParams lc = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lc.setMarginEnd(dp(c, 6));
            dias.addView(chip, lc);
        }
        hs.addView(dias);
        LinearLayout.LayoutParams lhs = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lhs.topMargin = dp(c, 12);
        agCorpo.addView(hs, lhs);
        if (agDia > 2) hs.post(() -> hs.smoothScrollTo((int) (dias.getWidth() * (agDia - 1) / 7f), 0));

        // ---- nível do dia
        Agenda.Nivel n = Agenda.nivel(todos, diaSel);
        int cn = Agenda.corNivel(n.nivel);
        LinearLayout nc = new LinearLayout(c);
        nc.setOrientation(LinearLayout.VERTICAL);
        nc.setPadding(dp(c, 14), dp(c, 12), dp(c, 14), dp(c, 12));
        GradientDrawable gn = new GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
            new int[]{Color.argb(45, Color.red(cn), Color.green(cn), Color.blue(cn)), Color.argb(12, 255, 255, 255)});
        gn.setCornerRadius(dp(c, 16)); gn.setStroke(dp(c, 1), Color.argb(90, Color.red(cn), Color.green(cn), Color.blue(cn)));
        nc.setBackground(gn);
        LinearLayout l1 = new LinearLayout(c);
        l1.setOrientation(LinearLayout.HORIZONTAL);
        l1.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout tt = new LinearLayout(c);
        tt.setOrientation(LinearLayout.VERTICAL);
        TextView rotN = tv(c, "NÍVEL DO DIA", TEXTO2, 9, Typeface.BOLD);
        rotN.setLetterSpacing(0.25f);
        tt.addView(rotN);
        tt.addView(tv(c, n.nivel.substring(0, 1).toUpperCase(br) + n.nivel.substring(1), cn, 20, Typeface.BOLD));
        l1.addView(tt, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        int idx = n.nivel.equals("crítico") ? 4 : n.nivel.equals("intenso") ? 3 : n.nivel.equals("moderado") ? 2 : n.nivel.equals("leve") ? 1 : 0;
        for (int k = 0; k < 4; k++) {
            View sg = new View(c);
            GradientDrawable gs = new GradientDrawable(); gs.setCornerRadius(dp(c, 3));
            gs.setColor(k < idx ? cn : Color.argb(35, 255, 255, 255));
            sg.setBackground(gs);
            LinearLayout.LayoutParams ls = new LinearLayout.LayoutParams(dp(c, 16), dp(c, 8 + k * 4));
            ls.setMarginStart(dp(c, 4)); ls.gravity = Gravity.BOTTOM;
            l1.addView(sg, ls);
        }
        nc.addView(l1);
        String est = n.total == 0 ? "Nada marcado. Bom dia para adiantar o que está pendente."
            : n.feitos + " de " + n.total + " concluídos" + (n.conflitos > 0 ? "  ·  [!] " + n.conflitos + (n.conflitos > 1 ? " conflitos" : " conflito") : "")
              + (n.livreMin >= 30 ? "  ·  " + n.livreMin / 60 + "h" + String.format(Locale.ROOT, "%02d", n.livreMin % 60) + " livres" : "");
        TextView te = tv(c, est, n.conflitos > 0 ? VERMELHO : Color.argb(200, 220, 235, 240), 12, Typeface.NORMAL);
        te.setPadding(0, dp(c, 4), 0, 0);
        nc.addView(te);
        if (n.total > 0) {                                           // barra de progresso do dia
            android.widget.FrameLayout pb = new android.widget.FrameLayout(c);
            View fundoPb = new View(c); fundoPb.setBackgroundColor(Color.argb(30, 255, 255, 255));
            pb.addView(fundoPb, new android.widget.FrameLayout.LayoutParams(android.widget.FrameLayout.LayoutParams.MATCH_PARENT, dp(c, 4)));
            View cheio = new View(c);
            GradientDrawable gpb = new GradientDrawable(); gpb.setColor(VERDE); gpb.setCornerRadius(dp(c, 2));
            cheio.setBackground(gpb);
            final float frac = n.feitos / (float) n.total;
            pb.addView(cheio, new android.widget.FrameLayout.LayoutParams(0, dp(c, 4)));
            pb.post(() -> { android.view.ViewGroup.LayoutParams lp = cheio.getLayoutParams(); lp.width = (int) (pb.getWidth() * frac); cheio.setLayoutParams(lp); });
            LinearLayout.LayoutParams lpb = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(c, 4));
            lpb.topMargin = dp(c, 8);
            nc.addView(pb, lpb);
        }
        if (!n.foco.isEmpty()) {                                     // foco do dia
            TextView rf = tv(c, "FOCO", AMBAR, 9, Typeface.BOLD);
            rf.setLetterSpacing(0.25f); rf.setPadding(0, dp(c, 10), 0, dp(c, 2));
            nc.addView(rf);
            for (Agenda.Item f : n.foco) {
                TextView tf = tv(c, (f.prio == 1 ? "[ALTA] " : "•  ") + (f.diaTodo ? "" : fh.format(new Date(f.ini)) + "  ") + f.titulo,
                    f.prio == 1 ? Color.WHITE : Color.argb(200, 220, 235, 240), 13, f.prio == 1 ? Typeface.BOLD : Typeface.NORMAL);
                tf.setSingleLine(true); tf.setEllipsize(android.text.TextUtils.TruncateAt.END);
                tf.setPadding(0, dp(c, 2), 0, dp(c, 2));
                nc.addView(tf);
            }
        }
        LinearLayout.LayoutParams lnc = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lnc.topMargin = dp(c, 10);
        agCorpo.addView(nc, lnc);

        // ---- linha do tempo do dia escolhido
        LinearLayout lista = new LinearLayout(c);
        lista.setOrientation(LinearLayout.VERTICAL);
        java.util.List<Agenda.Item> doDia = new java.util.ArrayList<>();
        for (Agenda.Item i : todos) if (i.ini >= diaSel && i.ini < diaSel + 86400000L) doDia.add(i);
        if (doDia.isEmpty()) {
            TextView vz = tv(c, agDia == 0 ? "Dia livre. Toque em ＋ Novo para marcar algo." : "Nada marcado neste dia.", TEXTO2, 13, Typeface.NORMAL);
            vz.setPadding(0, dp(c, 16), 0, dp(c, 8)); vz.setGravity(Gravity.CENTER);
            lista.addView(vz);
        } else {
            boolean agoraPosto = agDia != 0;
            for (Agenda.Item e : doDia) {
                if (!agoraPosto && !e.diaTodo && e.ini > agora) { lista.addView(linhaAgora(c, fh.format(new Date(agora)))); agoraPosto = true; }
                lista.addView(itemAgenda(c, e, fh, !e.diaTodo && e.fim < agora, !e.diaTodo && e.ini <= agora && e.fim > agora, todos, status));
            }
            if (!agoraPosto) lista.addView(linhaAgora(c, fh.format(new Date(agora))));
        }
        // ---- próximos fora do dia escolhido: evento marcado p/ outro dia não some ("marcou mas não apareceu", 18/10/2026)
        java.util.List<Agenda.Item> prox = new java.util.ArrayList<>();
        for (Agenda.Item i : todos) if (i.ini >= diaSel + 86400000L && !i.feito) prox.add(i);
        java.util.Collections.sort(prox, (a, b) -> Long.compare(a.ini, b.ini));
        if (!prox.isEmpty()) {
            TextView rp = tv(c, "PRÓXIMOS", CIANO, 9, Typeface.BOLD);
            rp.setLetterSpacing(0.25f); rp.setPadding(0, dp(c, 12), 0, dp(c, 4));
            lista.addView(rp);
            SimpleDateFormat fd = new SimpleDateFormat("EEE dd/MM", br);
            for (int k = 0; k < Math.min(5, prox.size()); k++) {
                final Agenda.Item p = prox.get(k);
                TextView tp = tv(c, fd.format(new Date(p.ini)).replace(".", "").toUpperCase(br) + (p.diaTodo ? "" : " · " + fh.format(new Date(p.ini)))
                    + "   " + (p.prio == 1 ? "[ALTA] " : "") + p.titulo, Color.argb(220, 220, 235, 240), 13, Typeface.NORMAL);
                tp.setSingleLine(true); tp.setEllipsize(android.text.TextUtils.TruncateAt.END);
                tp.setPadding(0, dp(c, 5), 0, dp(c, 5));
                final int alvo = (int) Math.max(0, Math.min(6, (Agenda.inicioDoDia(p.ini) - hoje) / 86400000L));
                tp.setOnClickListener(v -> { agDia = alvo; agendaRender(c, todos, status); });
                lista.addView(tp);
            }
        }
        ScrollView rol = new ScrollView(c);
        rol.setVerticalFadingEdgeEnabled(true); rol.setFadingEdgeLength(dp(c, 20));
        rol.addView(lista);
        LinearLayout.LayoutParams lrol = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            doDia.size() + Math.min(5, prox.size()) < 5 ? LinearLayout.LayoutParams.WRAP_CONTENT : (int) (H * 0.34f));
        lrol.topMargin = dp(c, 8);
        agCorpo.addView(rol, lrol);
    }

    private static View linhaAgora(Context c, String hora) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        l.setPadding(0, dp(c, 4), 0, dp(c, 4));
        TextView t = tv(c, hora, VERMELHO, 11, Typeface.BOLD);
        t.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        l.addView(t, new LinearLayout.LayoutParams(dp(c, 52), LinearLayout.LayoutParams.WRAP_CONTENT));
        View bola = new View(c);
        GradientDrawable gb = new GradientDrawable(); gb.setShape(GradientDrawable.OVAL); gb.setColor(VERMELHO);
        bola.setBackground(gb);
        l.addView(bola, new LinearLayout.LayoutParams(dp(c, 9), dp(c, 9)));
        View fio = new View(c);
        fio.setBackgroundColor(VERMELHO);
        l.addView(fio, new LinearLayout.LayoutParams(0, dp(c, 2), 1f));
        return l;
    }

    private static int corPrio(int p) { return p == 1 ? VERMELHO : p == 3 ? Color.argb(150, 190, 205, 212) : AMBAR; }

    private static View itemAgenda(Context c, Agenda.Item e, SimpleDateFormat fh, boolean passou, boolean emCurso,
                                   java.util.List<Agenda.Item> todos, String status) {
        boolean apagado = passou || e.feito;
        LinearLayout lin = new LinearLayout(c);
        lin.setOrientation(LinearLayout.HORIZONTAL);
        // coluna da hora
        LinearLayout hc = new LinearLayout(c);
        hc.setOrientation(LinearLayout.VERTICAL);
        hc.setPadding(0, dp(c, 12), 0, 0);
        TextView h1 = tv(c, e.diaTodo ? "dia" : fh.format(new Date(e.ini)), apagado ? Color.argb(90, 255, 255, 255) : Color.WHITE, 13, Typeface.BOLD);
        h1.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        hc.addView(h1);
        TextView h2 = tv(c, e.diaTodo ? "todo" : fh.format(new Date(e.fim)), Color.argb(apagado ? 60 : 120, 255, 255, 255), 11, Typeface.NORMAL);
        h2.setTypeface(Typeface.MONOSPACE);
        hc.addView(h2);
        lin.addView(hc, new LinearLayout.LayoutParams(dp(c, 52), LinearLayout.LayoutParams.WRAP_CONTENT));
        // trilho com o ponto da prioridade
        android.widget.FrameLayout trilho = new android.widget.FrameLayout(c);
        View fio = new View(c);
        fio.setBackgroundColor(Color.argb(40, 255, 255, 255));
        trilho.addView(fio, new android.widget.FrameLayout.LayoutParams(dp(c, 2), android.widget.FrameLayout.LayoutParams.MATCH_PARENT, Gravity.CENTER_HORIZONTAL));
        View bola = new View(c);
        GradientDrawable gb = new GradientDrawable(); gb.setShape(GradientDrawable.OVAL);
        gb.setColor(apagado ? Color.rgb(40, 50, 58) : corPrio(e.prio)); gb.setStroke(dp(c, 2), Color.rgb(8, 14, 19));
        bola.setBackground(gb);
        android.widget.FrameLayout.LayoutParams lb = new android.widget.FrameLayout.LayoutParams(dp(c, 12), dp(c, 12), Gravity.CENTER_HORIZONTAL | Gravity.TOP);
        lb.topMargin = dp(c, 16);
        trilho.addView(bola, lb);
        lin.addView(trilho, new LinearLayout.LayoutParams(dp(c, 12), LinearLayout.LayoutParams.MATCH_PARENT));
        // cartão: selos + título + local | botão de concluir
        LinearLayout card = new LinearLayout(c);
        card.setOrientation(LinearLayout.HORIZONTAL);
        card.setGravity(Gravity.CENTER_VERTICAL);
        card.setPadding(dp(c, 12), dp(c, 9), dp(c, 6), dp(c, 9));
        GradientDrawable gc = new GradientDrawable();
        gc.setCornerRadius(dp(c, 14));
        int cp = corPrio(e.prio);
        gc.setColor(emCurso && !e.feito ? Color.argb(45, Color.red(cp), Color.green(cp), Color.blue(cp)) : Color.argb(apagado ? 10 : 24, 255, 255, 255));
        if (emCurso && !e.feito) gc.setStroke(dp(c, 1), cp);
        else if (e.prio == 1 && !apagado) gc.setStroke(dp(c, 1), Color.argb(90, Color.red(cp), Color.green(cp), Color.blue(cp)));
        card.setBackground(gc);
        LinearLayout txt = new LinearLayout(c);
        txt.setOrientation(LinearLayout.VERTICAL);
        LinearLayout selos = new LinearLayout(c);
        selos.setOrientation(LinearLayout.HORIZONTAL);
        if (emCurso && !e.feito) selos.addView(selo(c, "EM ANDAMENTO", VERDE));
        if (e.prio != 2) selos.addView(selo(c, e.prio == 1 ? "ALTA" : "BAIXA", cp));
        if ("google".equals(e.fonte)) selos.addView(selo(c, "GOOGLE", Color.argb(170, 190, 205, 212)));
        if (selos.getChildCount() > 0) txt.addView(selos);
        TextView t = tv(c, e.titulo, apagado ? Color.argb(110, 255, 255, 255) : Color.WHITE, 15, Typeface.BOLD);
        if (e.feito) t.setPaintFlags(t.getPaintFlags() | android.graphics.Paint.STRIKE_THRU_TEXT_FLAG);
        txt.addView(t);
        if (e.local != null && !e.local.trim().isEmpty()) txt.addView(tv(c, "[LOCAL] " + e.local, Color.argb(apagado ? 80 : 160, 200, 220, 230), 12, Typeface.NORMAL));
        card.addView(txt, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        TextView ok = tv(c, e.feito ? "OK" : "", e.feito ? Color.rgb(6, 10, 14) : Color.WHITE, 16, Typeface.BOLD);
        ok.setGravity(Gravity.CENTER);
        GradientDrawable go = new GradientDrawable(); go.setShape(GradientDrawable.OVAL);
        go.setColor(e.feito ? VERDE : Color.TRANSPARENT); go.setStroke(dp(c, 2), e.feito ? VERDE : Color.argb(120, 255, 255, 255));
        ok.setBackground(go);
        ok.setOnClickListener(v -> {                                   // concluir / reabrir
            e.feito = !e.feito;
            if (demo == null) Agenda.mudar(c, e.id, "feito", e.feito);
            agendaRender(c, todos, status);
        });
        android.widget.FrameLayout okBox = new android.widget.FrameLayout(c);       // área de toque de 48 dp
        okBox.addView(ok, new android.widget.FrameLayout.LayoutParams(dp(c, 28), dp(c, 28), Gravity.CENTER));
        okBox.setOnClickListener(v -> ok.performClick());
        card.addView(okBox, new LinearLayout.LayoutParams(dp(c, 48), dp(c, 48)));
        LinearLayout.LayoutParams lcd = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        lcd.setMarginStart(dp(c, 10)); lcd.topMargin = dp(c, 4); lcd.bottomMargin = dp(c, 4);
        lin.addView(card, lcd);
        card.setOnClickListener(v -> {
            e.feito = !e.feito;
            if (demo == null) Agenda.mudar(c, e.id, "feito", e.feito);
            agendaRender(c, todos, status);
        });
        card.setOnLongClickListener(v -> {                             // segurar = troca a prioridade (alta -> normal -> baixa -> alta)
            e.prio = e.prio == 1 ? 2 : e.prio == 2 ? 3 : 1;
            if (demo == null) Agenda.mudar(c, e.id, "prioridade", e.prio);
            agendaRender(c, todos, status);
            return true;
        });
        return lin;
    }

    private static TextView selo(Context c, String t, int cor) {
        TextView s = tv(c, t, cor, 9, Typeface.BOLD);
        s.setLetterSpacing(0.12f);
        s.setPadding(dp(c, 6), dp(c, 1), dp(c, 6), dp(c, 1));
        GradientDrawable g = new GradientDrawable(); g.setCornerRadius(dp(c, 8)); g.setStroke(dp(c, 1), cor);
        s.setBackground(g);
        LinearLayout.LayoutParams l = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        l.setMarginEnd(dp(c, 5)); l.bottomMargin = dp(c, 3);
        s.setLayoutParams(l);
        return s;
    }

    private static void abrir(Context c, Intent i) {
        try { c.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); fecharAgenda(c); } catch (Exception ignored) {}
    }

    // ------------------------------------------------------------------ agenda em texto (para a fala)
    static String agenda(Context c, int dias) {
        if (c.checkSelfPermission(android.Manifest.permission.READ_CALENDAR) != android.content.pm.PackageManager.PERMISSION_GRANTED)
            return "(sem permissão de agenda)";
        long ini = System.currentTimeMillis(), fim = ini + dias * 86400000L;
        android.net.Uri.Builder u = CalendarContract.Instances.CONTENT_URI.buildUpon();
        android.content.ContentUris.appendId(u, ini); android.content.ContentUris.appendId(u, fim);
        StringBuilder sb = new StringBuilder();
        SimpleDateFormat dia = new SimpleDateFormat("EEE dd/MM", new Locale("pt", "BR")), hora = new SimpleDateFormat("HH:mm", Locale.ROOT);
        String ultDia = "";
        try (Cursor cur = c.getContentResolver().query(u.build(), new String[]{CalendarContract.Instances.TITLE,
                CalendarContract.Instances.BEGIN, CalendarContract.Instances.ALL_DAY}, null, null, CalendarContract.Instances.BEGIN + " ASC")) {
            int n = 0;
            while (cur != null && cur.moveToNext() && n++ < 25) {
                Date d = new Date(cur.getLong(1));
                String dd = dia.format(d);
                if (!dd.equals(ultDia)) { sb.append(sb.length() > 0 ? "\n" : "").append(dd).append('\n'); ultDia = dd; }
                sb.append(cur.getInt(2) == 1 ? "  dia todo  " : "  " + hora.format(d) + "  ").append(cur.getString(0)).append('\n');
            }
        } catch (Exception e) { return "(não consegui ler a agenda: " + e.getMessage() + ")"; }
        return sb.length() == 0 ? "Nada marcado nos próximos " + dias + " dias." : sb.toString().trim();
    }
}
