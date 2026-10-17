package dev.integra.friday;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.service.voice.VoiceInteractionService;
import android.service.voice.VoiceInteractionSession;
import android.service.voice.VoiceInteractionSessionService;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** F.R.I.D.A.Y. como ASSISTENTE DIGITAL PADRÃO (igual Gemini/ChatGPT/Claude). Botão lateral/gesto de assistente ->
 *  painel POR CIMA do app atual: núcleo de partículas que reage à voz dela e à do dono, legenda grande ao vivo, histórico
 *  e campo de texto; já começa ouvindo (só a voz do dono, ruído cancelado) e responde com o cérebro e a voz locais.
 *  Toque fora fecha. */
public class Assistente extends VoiceInteractionService {
    static volatile Assistente inst;

    @Override public void onReady() {
        super.onReady();
        inst = this;
        Cerebro.get(this);
    }

    @Override public void onShutdown() { inst = null; super.onShutdown(); }

    /** abre o painel do assistente (como o botão lateral) com uma dica na legenda, ex.: "+ Novo" da agenda */
    static void falarCom(Context c, String dica) {
        Bundle b = new Bundle();
        b.putString("dica", dica);
        Assistente a = inst;
        if (a != null) try { a.showSession(b, 0); return; } catch (Exception ignored) {}
        c.startActivity(new android.content.Intent(c, MainActivity.class).putExtra("assistente", true)
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK | android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP));
    }

    public static class Sessoes extends VoiceInteractionSessionService {
        @Override public VoiceInteractionSession onNewSession(Bundle args) { return new Sessao(this); }
    }

    static class Sessao extends VoiceInteractionSession {
        private static final int CIANO = Color.rgb(54, 214, 255), AMBAR = Color.rgb(255, 170, 70), TEAL = Color.rgb(70, 255, 214),
            VERDE = Color.rgb(108, 196, 143), VERMELHO = Color.rgb(255, 107, 107), TEXTO2 = Color.argb(150, 200, 220, 230);
        private final Handler main = new Handler(Looper.getMainLooper());
        private Particulas part;
        private LinearLayout msgs;
        private ScrollView rolo;
        private TextView status, legenda, mic, enviarBtn, fuiEuBtn, modeloTag, pararBtn;
        private View ponto, anelMic;
        private EditText campo;
        private Ouvido ouvido;
        private volatile boolean viva;
        private int estadoAtual;

        Sessao(Context c) { super(c); }

        private int dp(float v) { return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getContext().getResources().getDisplayMetrics()); }

        private GradientDrawable fundo(int cor, float raio, int borda) {
            GradientDrawable g = new GradientDrawable();
            g.setColor(cor); g.setCornerRadius(dp(raio));
            if (borda != 0) g.setStroke(dp(1), borda);
            return g;
        }

        private TextView tv(String t, int cor, float sp, int estilo) {
            TextView v = new TextView(getContext());
            v.setText(t); v.setTextColor(cor); v.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp); v.setTypeface(Typeface.DEFAULT, estilo);
            return v;
        }

        private String nomeModeloCurto() {
            String m = Cerebro.get(getContext()).modelo().replace(".gguf", "").replace("-q4_0", "").replace("-q4_k_m", "");
            return "[CORE] " + m.toUpperCase(java.util.Locale.ROOT);
        }

        private TextView chipAcao(String rotulo, int cor, Runnable acao) {
            TextView ch = tv(rotulo, Color.WHITE, 11.5f, Typeface.BOLD);
            ch.setPadding(dp(12), dp(7), dp(12), dp(7));
            ch.setSingleLine(true);
            ch.setBackground(fundo(Color.argb(34, Color.red(cor), Color.green(cor), Color.blue(cor)), 16,
                Color.argb(110, Color.red(cor), Color.green(cor), Color.blue(cor))));
            ch.setOnClickListener(v -> acao.run());
            return ch;
        }

        @Override public View onCreateContentView() {
            Context c = getContext();
            FrameLayout raiz = new FrameLayout(c);
            raiz.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{Color.argb(40, 0, 0, 0), Color.argb(165, 0, 5, 10), Color.argb(235, 0, 8, 14)}));
            raiz.setOnClickListener(v -> hide());                     // toque fora fecha
            LinearLayout folha = new LinearLayout(c);
            folha.setOrientation(LinearLayout.VERTICAL);
            folha.setPadding(dp(16), dp(10), dp(16), dp(16));
            GradientDrawable gf = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{Color.rgb(9, 22, 32), Color.rgb(3, 8, 13)});
            gf.setCornerRadius(dp(30)); gf.setStroke(dp(1), Color.argb(110, 54, 214, 255));
            folha.setBackground(gf);
            folha.setElevation(dp(18));
            folha.setClickable(true);                                 // toque na folha não fecha

            View alca = new View(c);
            alca.setBackground(fundo(Color.argb(75, 255, 255, 255), 3, 0));
            LinearLayout.LayoutParams la = new LinearLayout.LayoutParams(dp(42), dp(4)); la.gravity = Gravity.CENTER_HORIZONTAL;
            folha.addView(alca, la);

            // barra superior: selo VOZ DO DONO + marca F.R.I.D.A.Y. + seletor de modelo + abrir app
            LinearLayout topo = new LinearLayout(c);
            topo.setOrientation(LinearLayout.HORIZONTAL);
            topo.setGravity(Gravity.CENTER_VERTICAL);
            TextView seloVoz = tv("[STARK BIO] SÓ VOZ DO DONO", VERDE, 9.5f, Typeface.BOLD);
            seloVoz.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            seloVoz.setPadding(dp(9), dp(4), dp(9), dp(4));
            seloVoz.setBackground(fundo(Color.argb(32, 108, 196, 143), 12, Color.argb(100, 108, 196, 143)));
            topo.addView(seloVoz);

            TextView marca = tv("F.R.I.D.A.Y.", CIANO, 11, Typeface.BOLD);
            marca.setTypeface(Typeface.MONOSPACE, Typeface.BOLD); marca.setLetterSpacing(0.32f); marca.setGravity(Gravity.CENTER);
            topo.addView(marca, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));

            modeloTag = tv(nomeModeloCurto(), CIANO, 9.5f, Typeface.BOLD);
            modeloTag.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            modeloTag.setPadding(dp(9), dp(4), dp(9), dp(4));
            modeloTag.setBackground(fundo(Color.argb(30, 54, 214, 255), 12, Color.argb(95, 54, 214, 255)));
            modeloTag.setOnClickListener(v -> {
                String novo = Cerebro.get(getContext()).trocarModelo(null);
                modeloTag.setText(nomeModeloCurto());
                legenda("Modelo local alterado para " + novo + ".", false);
                new Thread(() -> Cerebro.get(getContext()).preparar()).start();
            });
            topo.addView(modeloTag);

            TextView abrirAppBtn = tv("↗ APP", Color.WHITE, 9.5f, Typeface.BOLD);
            abrirAppBtn.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            abrirAppBtn.setPadding(dp(9), dp(4), dp(9), dp(4));
            abrirAppBtn.setBackground(fundo(Color.argb(35, 255, 255, 255), 12, Color.argb(70, 255, 255, 255)));
            abrirAppBtn.setOnClickListener(v -> {
                hide();
                c.startActivity(new android.content.Intent(c, MainActivity.class)
                    .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK | android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP));
            });
            LinearLayout.LayoutParams lap = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lap.leftMargin = dp(6);
            topo.addView(abrirAppBtn, lap);

            LinearLayout.LayoutParams lmc = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lmc.topMargin = dp(8);
            folha.addView(topo, lmc);

            part = new Particulas(c);
            part.setOnClickListener(v -> ouvir());                   // toque no núcleo = falar
            folha.addView(part, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(200)));

            // pílula de estado + botão parar
            LinearLayout linhaEstado = new LinearLayout(c);
            linhaEstado.setOrientation(LinearLayout.HORIZONTAL);
            linhaEstado.setGravity(Gravity.CENTER);
            LinearLayout pilula = new LinearLayout(c);
            pilula.setOrientation(LinearLayout.HORIZONTAL);
            pilula.setGravity(Gravity.CENTER_VERTICAL);
            pilula.setPadding(dp(14), dp(6), dp(16), dp(6));
            pilula.setBackground(fundo(Color.argb(30, 54, 214, 255), 16, Color.argb(70, 54, 214, 255)));
            ponto = new View(c);
            GradientDrawable gp = new GradientDrawable(); gp.setShape(GradientDrawable.OVAL); gp.setColor(CIANO);
            ponto.setBackground(gp);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(7), dp(7)); lp.setMarginEnd(dp(8));
            pilula.addView(ponto, lp);
            status = tv("", CIANO, 11, Typeface.BOLD);
            status.setTypeface(Typeface.MONOSPACE, Typeface.BOLD); status.setLetterSpacing(0.16f); status.setSingleLine(true);
            status.setEllipsize(android.text.TextUtils.TruncateAt.END);
            pilula.addView(status);
            linhaEstado.addView(pilula);

            pararBtn = tv("■ PARAR", VERMELHO, 10, Typeface.BOLD);
            pararBtn.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            pararBtn.setPadding(dp(11), dp(6), dp(11), dp(6));
            pararBtn.setBackground(fundo(Color.argb(38, 255, 107, 107), 16, Color.argb(120, 255, 107, 107)));
            pararBtn.setVisibility(View.GONE);
            pararBtn.setOnClickListener(v -> {
                if (ouvido != null) ouvido.parar();
                Cerebro.get(getContext()).parar();
                Voz.get(getContext()).calar();
                estado(0, "PARADO · TOQUE PARA FALAR");
            });
            LinearLayout.LayoutParams lpr = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lpr.leftMargin = dp(8);
            linhaEstado.addView(pararBtn, lpr);
            folha.addView(linhaEstado);

            // legenda ao vivo (o que ele está dizendo / o que ela respondeu) — com links clicáveis
            legenda = tv("", Color.WHITE, 19, Typeface.NORMAL);
            legenda.setGravity(Gravity.CENTER);
            legenda.setLineSpacing(dp(2), 1f);
            legenda.setMaxLines(6); legenda.setEllipsize(android.text.TextUtils.TruncateAt.END);
            legenda.setPadding(dp(8), dp(12), dp(8), dp(6));
            legenda.setAutoLinkMask(android.text.util.Linkify.WEB_URLS);
            legenda.setLinksClickable(true);
            legenda.setLinkTextColor(CIANO);
            legenda.setMovementMethod(android.text.method.LinkMovementMethod.getInstance());
            folha.addView(legenda, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

            // "fui eu": aparece quando a voz foi recusada; ensina o perfil e recalibra o limiar
            fuiEuBtn = tv("FUI EU — ERA A MINHA VOZ", Color.WHITE, 12, Typeface.BOLD);
            fuiEuBtn.setLetterSpacing(0.12f); fuiEuBtn.setGravity(Gravity.CENTER);
            fuiEuBtn.setPadding(dp(18), dp(10), dp(18), dp(10));
            fuiEuBtn.setBackground(fundo(Color.argb(60, 54, 214, 255), 20, CIANO));
            fuiEuBtn.setVisibility(View.GONE);
            fuiEuBtn.setOnClickListener(v -> {
                fuiEuBtn.setVisibility(View.GONE);
                new Thread(() -> {
                    String r = Aprende.fuiEu(getContext(), ouvido, Ouvido.ultimaRecusada, Ouvido.ultimoScore);
                    legenda(r, false);
                    main.postDelayed(this::ouvir, 1200);
                }).start();
            });
            LinearLayout.LayoutParams lfe = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lfe.gravity = Gravity.CENTER_HORIZONTAL; lfe.topMargin = dp(6);
            folha.addView(fuiEuBtn, lfe);

            // histórico (anteriores, com links clicáveis)
            msgs = new LinearLayout(c);
            msgs.setOrientation(LinearLayout.VERTICAL);
            rolo = new ScrollView(c);
            rolo.setVerticalFadingEdgeEnabled(true); rolo.setFadingEdgeLength(dp(24));
            rolo.addView(msgs);
            LinearLayout.LayoutParams lr = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(115));
            lr.topMargin = dp(4);
            folha.addView(rolo, lr);

            // barra de atalhos rápidos (Agenda da Sexta-Feira, Modo Dev, Pesquisar, Criar PDF, WhatsApp)
            android.widget.HorizontalScrollView hsAtalhos = new android.widget.HorizontalScrollView(c);
            hsAtalhos.setHorizontalScrollBarEnabled(false);
            LinearLayout atalhos = new LinearLayout(c);
            atalhos.setOrientation(LinearLayout.HORIZONTAL);
            Object[][] chips = {
                {"[AGENDA]", CIANO, (Runnable) () -> pedir("abre minha agenda")},
                {"[MODO DEV]", AMBAR, (Runnable) () -> {
                    if (Acesso.inst != null) Flutuante.ide(Acesso.inst, true);
                    else c.startActivity(new android.content.Intent(c, MainActivity.class).putExtra("aba", "dev")
                        .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK | android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP));
                }},
                {"[PESQUISAR]", TEAL, (Runnable) () -> {
                    campo.setText("Pesquise no navegador ");
                    campo.setSelection(campo.getText().length());
                    campo.requestFocus();
                }},
                {"[CRIAR DOC]", CIANO, (Runnable) () -> {
                    campo.setText("Pesquise sobre inteligência artificial e crie um documento PDF");
                    campo.setSelection(campo.getText().length());
                }},
                {"[PESQUISA+ZAP]", VERDE, (Runnable) () -> {
                    campo.setText("Pesquise notícias de tecnologia hoje e envie para ");
                    campo.setSelection(campo.getText().length());
                    campo.requestFocus();
                }}
            };
            for (Object[] ch : chips) {
                TextView v = chipAcao((String) ch[0], (Integer) ch[1], (Runnable) ch[2]);
                LinearLayout.LayoutParams lch = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
                lch.setMarginEnd(dp(7));
                atalhos.addView(v, lch);
            }
            hsAtalhos.addView(atalhos);
            LinearLayout.LayoutParams lhs = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lhs.topMargin = dp(8);
            folha.addView(hsAtalhos, lhs);

            // entrada: campo + botão ENVIAR (>) + microfone circular que pulsa com a voz
            LinearLayout linha = new LinearLayout(c);
            linha.setOrientation(LinearLayout.HORIZONTAL);
            linha.setGravity(Gravity.CENTER_VERTICAL);
            campo = new EditText(c);
            campo.setHint("Escreva para a Sexta-Feira…");
            campo.setHintTextColor(Color.argb(115, 200, 220, 230)); campo.setTextColor(Color.WHITE);
            campo.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
            campo.setBackground(fundo(Color.argb(255, 13, 26, 34), 24, Color.argb(85, 54, 214, 255)));
            campo.setPadding(dp(16), dp(12), dp(16), dp(12));
            campo.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            campo.setImeOptions(EditorInfo.IME_ACTION_SEND);
            campo.setOnEditorActionListener((v, a, e) -> { enviarTexto(); return true; });
            linha.addView(campo, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));

            // Botão ENVIAR MENSAGEM visível e dedicado
            enviarBtn = tv(">", Color.rgb(4, 14, 20), 20, Typeface.BOLD);
            enviarBtn.setGravity(Gravity.CENTER);
            enviarBtn.setContentDescription("Enviar mensagem");
            GradientDrawable ge = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{Color.rgb(70, 255, 214), Color.rgb(54, 214, 255)});
            ge.setShape(GradientDrawable.OVAL);
            enviarBtn.setBackground(ge);
            enviarBtn.setElevation(dp(6));
            enviarBtn.setOnClickListener(v -> enviarTexto());
            LinearLayout.LayoutParams le = new LinearLayout.LayoutParams(dp(50), dp(50));
            le.leftMargin = dp(8);
            linha.addView(enviarBtn, le);

            FrameLayout micBox = new FrameLayout(c);
            anelMic = new View(c);
            GradientDrawable ga = new GradientDrawable(); ga.setShape(GradientDrawable.OVAL); ga.setColor(Color.argb(60, 54, 214, 255));
            anelMic.setBackground(ga);
            micBox.addView(anelMic, new FrameLayout.LayoutParams(dp(56), dp(56), Gravity.CENTER));
            mic = tv("●", Color.WHITE, 21, Typeface.BOLD);
            mic.setGravity(Gravity.CENTER);
            GradientDrawable gm = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{Color.rgb(40, 190, 240), Color.rgb(20, 110, 170)});
            gm.setShape(GradientDrawable.OVAL);
            mic.setBackground(gm);
            mic.setElevation(dp(6));
            mic.setOnClickListener(v -> ouvir());
            micBox.addView(mic, new FrameLayout.LayoutParams(dp(50), dp(50), Gravity.CENTER));
            LinearLayout.LayoutParams lm = new LinearLayout.LayoutParams(dp(60), dp(60)); lm.leftMargin = dp(6);
            linha.addView(micBox, lm);
            LinearLayout.LayoutParams ll = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            ll.topMargin = dp(10);
            folha.addView(linha, ll);

            FrameLayout.LayoutParams lf = new FrameLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM);
            lf.setMargins(dp(8), 0, dp(8), dp(8));
            raiz.addView(folha, lf);
            return raiz;
        }

        /** ~30 fps: anel do microfone pulsa com a voz e a pílula acompanha a fala dela */
        private final Runnable pulso = new Runnable() {
            @Override public void run() {
                if (!viva) return;
                float n = estadoAtual == 1 ? Ouvido.nivelMic : Voz.falandoAgora() ? Voz.nivel() : 0f;
                float s = estadoAtual == 1 ? 1f + 0.45f * n : 1f + 0.08f * (float) Math.sin(System.nanoTime() / 4e8);
                if (anelMic != null) { anelMic.setScaleX(s); anelMic.setScaleY(s); anelMic.setAlpha(estadoAtual == 1 ? 0.6f + 0.4f * n : 0.35f); }
                if (ponto != null) ponto.setAlpha(0.5f + 0.5f * (float) Math.abs(Math.sin(System.nanoTime() / 3e8)));
                main.postDelayed(this, 33);
            }
        };

        @Override public void onShow(Bundle args, int flags) {
            super.onShow(args, flags);
            viva = true;
            if (modeloTag != null) modeloTag.setText(nomeModeloCurto());
            try {                                                      // desfoca o app que está atrás (Android 12+)
                android.view.Window w = getWindow().getWindow();
                if (w != null && android.os.Build.VERSION.SDK_INT >= 31) {
                    w.addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND);
                    WindowManager.LayoutParams a = w.getAttributes();
                    a.setBlurBehindRadius(dp(22));
                    w.setAttributes(a);
                }
            } catch (Exception ignored) {}
            String dica = args == null ? null : args.getString("dica");
            if (dica != null && legenda != null) legenda(dica, false);
            else if (msgs != null && msgs.getChildCount() == 0 && legenda != null && legenda.getText().length() == 0)
                legenda("Oi, Iann. Estou ouvindo você (reconhecimento exclusivo da sua voz).", false);
            main.removeCallbacks(pulso);
            main.post(pulso);
            ouvir();
        }

        @Override public void onHide() {
            viva = false;
            main.removeCallbacks(pulso);
            if (ouvido != null) ouvido.parar();
            super.onHide();
        }

        private void estado(int e, String txt) {
            main.post(() -> {
                estadoAtual = e;
                if (part != null) part.estado(e);
                int cor = e == 2 ? AMBAR : e == 3 ? TEAL : CIANO;
                if (status != null) { status.setText(txt); status.setTextColor(cor); }
                if (ponto != null) ((GradientDrawable) ponto.getBackground()).setColor(cor);
                if (pararBtn != null) pararBtn.setVisibility(e == 1 || e == 2 || e == 3 ? View.VISIBLE : View.GONE);
            });
        }

        /** a fala atual vai para a legenda grande; a anterior desce para o histórico */
        private CharSequence legAnt;
        private boolean legAntMeu;

        private void legenda(String t, boolean meu) {
            main.post(() -> {
                if (legAnt != null && legAnt.length() > 0) historico(legAnt, legAntMeu);
                legAnt = t; legAntMeu = meu;
                legenda.setText(meu ? "“" + t + "”" : t);
                android.text.util.Linkify.addLinks(legenda, android.text.util.Linkify.WEB_URLS);
                legenda.setTextColor(meu ? Color.argb(220, 255, 225, 190) : Color.WHITE);
                legenda.setTextSize(TypedValue.COMPLEX_UNIT_SP, t.length() > 140 ? 15 : t.length() > 70 ? 17 : 19);
                legenda.setAlpha(0f); legenda.setTranslationY(dp(8));
                legenda.animate().alpha(1f).translationY(0).setDuration(220).start();
            });
        }

        private void parcial(String t) { main.post(() -> { legenda.setText("“" + t + "…”"); legenda.setTextColor(Color.argb(170, 255, 225, 190)); }); }

        private void historico(CharSequence t, boolean meu) {
            TextView b = tv("", meu ? Color.argb(190, 255, 225, 190) : Color.argb(200, 220, 238, 245), 13, Typeface.NORMAL);
            b.setText((meu ? "VOCÊ  " : "FRIDAY  ") + t);
            android.text.SpannableString sp = new android.text.SpannableString(b.getText());
            int n = meu ? 6 : 8;
            sp.setSpan(new android.text.style.ForegroundColorSpan(meu ? AMBAR : CIANO), 0, n, 0);
            sp.setSpan(new android.text.style.RelativeSizeSpan(0.75f), 0, n, 0);
            sp.setSpan(new android.text.style.StyleSpan(Typeface.BOLD), 0, n, 0);
            b.setText(sp);
            android.text.util.Linkify.addLinks(b, android.text.util.Linkify.WEB_URLS);
            b.setLinksClickable(true);
            b.setLinkTextColor(CIANO);
            b.setMovementMethod(android.text.method.LinkMovementMethod.getInstance());
            b.setPadding(dp(12), dp(7), dp(12), dp(7));
            b.setBackground(fundo(meu ? Color.argb(28, 255, 170, 70) : Color.argb(26, 54, 214, 255), 14, 0));
            LinearLayout.LayoutParams l = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            l.topMargin = dp(5);
            msgs.addView(b, l);
            while (msgs.getChildCount() > 30) msgs.removeViewAt(0);
            rolo.post(() -> rolo.fullScroll(View.FOCUS_DOWN));
        }

        private void ouvir() {
            if (ouvido == null) ouvido = new Ouvido(getContext());
            main.post(() -> { if (fuiEuBtn != null) fuiEuBtn.setVisibility(View.GONE); });
            estado(1, "OUVINDO · SÓ VOZ DO DONO");
            Voz.get(getContext()).ouvirComando(ouvido, new Voz.Escuta() {
                @Override public void texto(String t) { pedir(t); }
                @Override public void parcial(String t) { if (t.startsWith("entendendo")) estado(2, "ENTENDENDO"); else parcial(t); }
                @Override public void recusada(float sc) {
                    estado(0, String.format(java.util.Locale.ROOT, "VOZ BLOQUEADA (%.2f) · SÓ O DONO", sc));
                    main.post(() -> { if (fuiEuBtn != null) fuiEuBtn.setVisibility(View.VISIBLE); });
                }
                @Override public void erro(String e) { estado(0, e.toUpperCase()); }
            });
        }

        private void enviarTexto() {
            String t = campo.getText().toString().trim();
            if (t.isEmpty()) return;
            campo.setText("");
            if (ouvido != null) ouvido.parar();
            Voz.get(getContext()).pararDeOuvir();
            try {
                android.view.inputmethod.InputMethodManager imm = (android.view.inputmethod.InputMethodManager) getContext().getSystemService(Context.INPUT_METHOD_SERVICE);
                if (imm != null) imm.hideSoftInputFromWindow(campo.getWindowToken(), 0);
            } catch (Exception ignored) {}
            pedir(t);
        }

        private void pedir(String t) {
            if (t == null || t.trim().isEmpty()) { estado(0, "NÃO OUVI NADA · TOQUE PARA FALAR"); return; }
            legenda(t, true);
            estado(2, "PENSANDO");
            new Thread(() -> {
                String r = Cerebro.get(getContext()).pedir(t, "voz");
                legenda(r, false);
                if (!viva) return;
                estado(3, "FALANDO");
                Voz.get(getContext()).falar(r);
                long fim = System.currentTimeMillis() + 60000;          // volta ao repouso quando o áudio acabar de verdade
                try { Thread.sleep(300); while (viva && Voz.falandoAgora() && System.currentTimeMillis() < fim) Thread.sleep(120); }
                catch (InterruptedException ignored) {}
                if (viva) estado(0, "TOQUE PARA FALAR OU ESCREVA");
            }, "friday-sessao").start();
        }
    }
}
