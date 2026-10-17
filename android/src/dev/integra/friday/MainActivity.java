package dev.integra.friday;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.os.Build;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.InputStream;

/** Casca nativa do controle remoto da F.R.I.D.A.Y.: a interface (HTML/Canvas) vem dos assets, servida em https://friday.app/
 *  (origem segura -> microfone e câmera liberados no WebView); a conversa com o PC é por HTTP/WebSocket no Tailscale. */
public class MainActivity extends Activity {
    private static final String ORIGEM = "https://friday.app/";
    private static final int REQ_PERM = 1, REQ_ARQ = 2;
    private WebView web;
    private PermissionRequest pendente;
    private ValueCallback<Uri[]> arquivosCb;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        web = new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);   // página https local -> PC em http/ws no Tailscale
        s.setAllowFileAccess(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                String u = r.getUrl().toString();
                if (!u.startsWith(ORIGEM)) return null;
                String caminho = r.getUrl().getPath();
                if (caminho == null || caminho.equals("/") || caminho.isEmpty()) caminho = "/index.html";
                try {
                    InputStream in = getAssets().open(caminho.substring(1));
                    String ext = MimeTypeMap.getFileExtensionFromUrl(caminho);
                    String mime = "js".equals(ext) ? "application/javascript" : MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
                    return new WebResourceResponse(mime == null ? "text/plain" : mime, "utf-8", in);
                } catch (Exception e) {
                    return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found", null, null);
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                String u = r.getUrl().toString();
                if (u.startsWith(ORIGEM)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, r.getUrl()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                } catch (Exception ignored) {}
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest req) {
                runOnUiThread(() -> {
                    if (temPermissoes()) req.grant(req.getResources());
                    else { pendente = req; pedirPermissoes(); }
                });
            }

            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (arquivosCb != null) arquivosCb.onReceiveValue(null);
                arquivosCb = cb;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("*/*");
                i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                startActivityForResult(Intent.createChooser(i, "Anexar para a Sexta-Feira"), REQ_ARQ);
                return true;
            }
        });
        web.addJavascriptInterface(new Nativo(), "Nativo");          // ponte do PC (Acesso): token + atalho p/ ativar
        Cerebro.get(this).setOuvinte((tipo, texto) -> {             // Friday LOCAL -> interface (e voz no fim)
            if ("fim".equals(tipo)) Voz.get(this).falar(texto);
            js(tipo, texto);
        });
        Voz.get(this).preparar();                                   // voz Supertonic (a mesma do PC) carrega em 2º plano
        Sincronizador.iniciarVigia(this);                           // auto-descoberta e sincronização bidirecional do cluster
        assistente(getIntent());
        setContentView(web);
        imersivo();
        if (!temPermissoes()) pedirPermissoes();
        String abaIni = getIntent() != null ? getIntent().getStringExtra("aba") : null;
        web.loadUrl(ORIGEM + "index.html" + (abaIni != null && !abaIni.isEmpty() ? "?aba=" + abaIni : ""));
    }

    /** chamada como assistente (gesto do sistema / botão) ou com aba direta (agenda/dev): abre a aba certa */
    private void assistente(Intent i) {
        if (i == null) return;
        String aba = i.getStringExtra("aba");
        if (aba != null && !aba.isEmpty()) {
            final String a = aba;
            for (long delay : new long[]{200, 500, 1000}) {
                web.postDelayed(() -> web.evaluateJavascript("window.abrirAba&&abrirAba(" + org.json.JSONObject.quote(a) + ")", null), delay);
            }
            return;
        }
        boolean asst = i.getBooleanExtra("assistente", false) || Intent.ACTION_ASSIST.equals(i.getAction())
            || Intent.ACTION_VOICE_COMMAND.equals(i.getAction());
        if (asst) web.postDelayed(() -> web.evaluateJavascript("window.modoAssistente&&modoAssistente()", null), 900);
    }

    @Override protected void onNewIntent(Intent i) { super.onNewIntent(i); setIntent(i); assistente(i); }

    private Ouvido ouvidoInst;
    private Ouvido ouvido() { if (ouvidoInst == null) ouvidoInst = new Ouvido(this); return ouvidoInst; }
    private long ultAprendeu;

    private final java.util.concurrent.ExecutorService trabalho = java.util.concurrent.Executors.newSingleThreadExecutor();

    private void js(String tipo, String texto) {
        String s_ = "window.fridayLocal&&fridayLocal(" + org.json.JSONObject.quote(tipo) + "," + org.json.JSONObject.quote(texto == null ? "" : texto) + ")";
        runOnUiThread(() -> web.evaluateJavascript(s_, null));
    }

    /** chamado pelo app.js. Só a página dos assets (https://friday.app/) carrega aqui: shouldOverrideUrlLoading bloqueia o resto. */
    private class Nativo {
        @JavascriptInterface public void configurar(String tok) { Acesso.salvarToken(MainActivity.this, tok); }
        /** o microfone com cancelamento de eco põe o Android em MODE_IN_COMMUNICATION; fone BT só em A2DP não serve
         *  para chamada, então o som ia para o alto-falante. Mantém a saída no fone (SCO/BLE se houver; senão modo normal). */
        @JavascriptInterface public void audioFone() {
            AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
            if (Build.VERSION.SDK_INT >= 31) {
                for (AudioDeviceInfo d : am.getAvailableCommunicationDevices()) {
                    int t = d.getType();
                    if (t == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || t == AudioDeviceInfo.TYPE_BLE_HEADSET
                        || t == AudioDeviceInfo.TYPE_WIRED_HEADSET || t == AudioDeviceInfo.TYPE_USB_HEADSET) {
                        am.setCommunicationDevice(d); return;
                    }
                }
            }
            for (AudioDeviceInfo d : am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)) {
                if (d.getType() == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP) {
                    am.setSpeakerphoneOn(false);
                    am.setMode(AudioManager.MODE_NORMAL); return;
                }
            }
        }
        @JavascriptInterface public boolean ponteAtiva() { return Acesso.inst != null; }
        @JavascriptInterface public void configurarHost(String h) { Link.prefs(MainActivity.this).edit().putString("host", h).apply(); }
        /** Friday LOCAL (cérebro no celular) */
        @JavascriptInterface public boolean localDisponivel() { return Llm.ok && Cerebro.get(MainActivity.this).arquivoModelo().exists(); }
        @JavascriptInterface public boolean localOcupada() { return Cerebro.get(MainActivity.this).ocupada(); }
        @JavascriptInterface public void local(String t) { trabalho.submit(() -> Cerebro.get(MainActivity.this).pedir(t, "texto")); }
        @JavascriptInterface public String modeloLocal() { return Cerebro.get(MainActivity.this).modelo(); }
        @JavascriptInterface public String catalogoModelos() { return Cerebro.get(MainActivity.this).catalogoJson(); }
        @JavascriptInterface public String trocarModelo() {
            String m = Cerebro.get(MainActivity.this).trocarModelo(null);
            trabalho.submit(() -> js("estado", Cerebro.get(MainActivity.this).preparar() ? "pronta: " + m : "falhou ao carregar " + m));
            return m;
        }
        @JavascriptInterface public String selecionarModelo(String arq) {
            String m = Cerebro.get(MainActivity.this).trocarModelo(arq);
            trabalho.submit(() -> js("estado", Cerebro.get(MainActivity.this).preparar() ? "pronta: " + m : "falhou ao carregar " + m));
            return m;
        }
        @JavascriptInterface public boolean tsAtivo() { return Link.vpnAtiva(MainActivity.this); }
        @JavascriptInterface public boolean tsManter() { return Link.tsManter(MainActivity.this); }
        @JavascriptInterface public void tsLigar(boolean on) { Link.tailscale(MainActivity.this, on); }
        @JavascriptInterface public boolean modoDev() { return Cerebro.get(MainActivity.this).modoDev(); }
        @JavascriptInterface public void setModoDev(boolean on) {
            getSharedPreferences("friday_local", MODE_PRIVATE).edit().putBoolean("modo_dev", on).apply();
            if (on && Dev.termuxInstalado(MainActivity.this) && !Dev.permitido(MainActivity.this))
                runOnUiThread(() -> requestPermissions(new String[]{"com.termux.permission.RUN_COMMAND"}, 3));
        }
        @JavascriptInterface public String devEstado() {
            if (Dev.termuxInstalado(MainActivity.this) && Dev.permitido(MainActivity.this)) return "pronto (Termux)";
            if (Link.pcOnline(MainActivity.this)) return "pronto (PC IDE)";
            return "pronto (Local GGUF)";
        }
        @JavascriptInterface public void devTerminal() { Dev.abrirTerminal(MainActivity.this); }
        @JavascriptInterface public String ideEstadoJson() { return Ide.jsonEstado(); }
        @JavascriptInterface public String ideIniciar(String obj, String pasta) { return Ide.iniciar(MainActivity.this, obj, pasta); }
        @JavascriptInterface public void idePausar(boolean p) { Ide.pausar(p); }
        @JavascriptInterface public void ideParar() { Ide.parar(); }
        @JavascriptInterface public void ideFlutuante() { if (Acesso.inst != null) Flutuante.ide(Acesso.inst, true); }

        // ---- AGENDA DA SEXTA-FEIRA (local + sincronizada com o PC, nunca abre Google Calendar)
        @JavascriptInterface public String agendaJson(int dias) {
            try {
                int d = Math.max(1, Math.min(14, dias));
                long hoje = Agenda.inicioDoDia(System.currentTimeMillis());
                java.util.List<Agenda.Item> todos = Agenda.itens(MainActivity.this, hoje - 86400000L, hoje + (d + 1) * 86400000L);
                org.json.JSONArray arrDias = new org.json.JSONArray();
                java.text.SimpleDateFormat fd = new java.text.SimpleDateFormat("EEE d/MM", new java.util.Locale("pt", "BR"));
                for (int k = 0; k < Math.min(7, d); k++) {
                    long d0 = hoje + k * 86400000L;
                    Agenda.Nivel nk = Agenda.nivel(todos, d0);
                    arrDias.put(new org.json.JSONObject()
                        .put("k", k)
                        .put("rotulo", k == 0 ? "HOJE" : k == 1 ? "AMANHÃ" : fd.format(new java.util.Date(d0)).replace(".", "").toUpperCase(new java.util.Locale("pt", "BR")))
                        .put("inicio", d0)
                        .put("nivel", nk.nivel)
                        .put("total", nk.total)
                        .put("feitos", nk.feitos)
                        .put("conflitos", nk.conflitos)
                        .put("livreMin", nk.livreMin));
                }
                org.json.JSONArray arrItens = new org.json.JSONArray();
                java.text.SimpleDateFormat fh = new java.text.SimpleDateFormat("HH:mm", java.util.Locale.ROOT);
                for (Agenda.Item it : todos) {
                    arrItens.put(new org.json.JSONObject()
                        .put("id", it.id).put("titulo", it.titulo).put("local", it.local == null ? "" : it.local)
                        .put("ini", it.ini).put("fim", it.fim)
                        .put("horaIni", it.diaTodo ? "dia todo" : fh.format(new java.util.Date(it.ini)))
                        .put("horaFim", it.diaTodo ? "" : fh.format(new java.util.Date(it.fim)))
                        .put("prio", it.prio).put("feito", it.feito).put("diaTodo", it.diaTodo).put("fonte", it.fonte));
                }
                return new org.json.JSONObject()
                    .put("status", Agenda.status(MainActivity.this))
                    .put("hoje", hoje)
                    .put("dias", arrDias)
                    .put("itens", arrItens)
                    .toString();
            } catch (Exception e) {
                return "{\"status\":\"erro\",\"dias\":[],\"itens\":[]}";
            }
        }
        @JavascriptInterface public String agendaNovo(String titulo, String quando, int prio, int dur) {
            return Agenda.novo(MainActivity.this, titulo, quando, Math.max(1, Math.min(3, prio)), Math.max(10, dur));
        }
        @JavascriptInterface public void agendaMudar(String id, String campo, String valor) {
            if ("feito".equals(campo)) Agenda.mudar(MainActivity.this, id, "feito", Boolean.parseBoolean(valor));
            else if ("prioridade".equals(campo)) Agenda.mudar(MainActivity.this, id, "prioridade", Integer.parseInt(valor));
            else if ("removido".equals(campo)) Agenda.mudar(MainActivity.this, id, "removido", Boolean.parseBoolean(valor));
        }
        @JavascriptInterface public void agendaSync() { Agenda.sincronizarJa(MainActivity.this); }
        @JavascriptInterface public void agendaFlutuante() { if (Acesso.inst != null) Flutuante.agendaPainel(Acesso.inst); }
        @JavascriptInterface public void meshSync() { Sincronizador.sincronizarJa(MainActivity.this); }
        @JavascriptInterface public String meshStatus() { return Sincronizador.status(MainActivity.this); }

        // ---- VOZ DO DONO (status e calibração estrita)
        @JavascriptInterface public String vozStatusJson() {
            try {
                Ouvido o = ouvido();
                return new org.json.JSONObject()
                    .put("pronto", o.pronto())
                    .put("temPerfil", o.temPerfil())
                    .put("amostras", o.totalAmostras())
                    .put("limiar", Math.round(o.limiar() * 100) / 100.0)
                    .put("soDono", getSharedPreferences("friday_local", MODE_PRIVATE).getBoolean("so_dono", true))
                    .put("ultimoScore", Math.round(Ouvido.ultimoScore * 100) / 100.0)
                    .put("resumo", Aprende.resumoVoz(MainActivity.this))
                    .toString();
            } catch (Exception e) { return "{}"; }
        }
        @JavascriptInterface public void setLimiarVoz(float lim) {
            float v = Math.max(Ouvido.LIMIAR_MIN, Math.min(Ouvido.LIMIAR_MAX, lim));
            getSharedPreferences("friday_local", MODE_PRIVATE).edit().putFloat("voz_limiar", v).apply();
        }

        @JavascriptInterface public void pararLocal() { Cerebro.get(MainActivity.this).parar(); Voz.get(MainActivity.this).calar(); }
        @JavascriptInterface public void prepararLocal() { trabalho.submit(() -> js("estado", Cerebro.get(MainActivity.this).preparar() ? "pronta" : "sem modelo")); }
        @JavascriptInterface public void ouvirLocal() {
            Voz.get(MainActivity.this).ouvirComando(ouvido(), new Voz.Escuta() {
                @Override public void texto(String t) { js("ouvi", t); trabalho.submit(() -> Cerebro.get(MainActivity.this).pedir(t, "voz")); }
                @Override public void parcial(String t) { js("parcial", t); }
                @Override public void recusada(float sc) {
                    js("recusada", "Voz bloqueada (" + String.format(java.util.Locale.ROOT, "%.2f", sc) + " · exclusivo para a voz do dono). Se foi você, toque em FUI EU.");
                }
                @Override public void erro(String e) { js("erro", e); }
            });
        }
        /** "fui eu": a fala recusada era do dono -> entra no perfil e o limiar se recalibra */
        @JavascriptInterface public void fuiEu() {
            trabalho.submit(() -> js("estado", Aprende.fuiEu(MainActivity.this, ouvido(), Ouvido.ultimaRecusada, Ouvido.ultimoScore)));
        }
        @JavascriptInterface public void pararOuvir() { Voz.get(MainActivity.this).pararDeOuvir(); ouvido().parar(); }
        /** cadastro da voz no celular: grava uma fala e acrescenta ao perfil (chamar 3-5 vezes) */
        @JavascriptInterface public void cadastrarVoz() {
            ouvido().ouvirUmaFala(8000, 1000, 12000, new Ouvido.Fim() {
                @Override public void fala(short[] pcm, float sc, boolean dono) {
                    js("estado", ouvido().aprender(pcm, true) ? "amostra da sua voz guardada (" + String.format(java.util.Locale.ROOT, "%.2f", sc) + " · total " + ouvido().totalAmostras() + ")" : "amostra fora do padrão ou curta, fale uma frase maior");
                }
                @Override public void erro(String e) { js("erro", e); }
            });
        }
        @JavascriptInterface public void abrirAcessibilidade() {
            runOnUiThread(() -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));
        }
        @JavascriptInterface public void abrirInfoApp() {        // Android 13+: "Permitir configurações restritas" fica no menu ⋮ daqui
            runOnUiThread(() -> startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName()))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));
        }
    }

    private boolean temPermissoes() {
        return checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
            && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
            && checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED;
    }

    private void pedirPermissoes() {
        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO, Manifest.permission.CAMERA, Manifest.permission.READ_CONTACTS}, REQ_PERM);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        if (code == REQ_PERM && pendente != null) {
            if (temPermissoes()) pendente.grant(pendente.getResources()); else pendente.deny();
            pendente = null;
        }
    }

    @Override
    protected void onActivityResult(int code, int res, Intent data) {
        if (code != REQ_ARQ || arquivosCb == null) return;
        Uri[] r = null;
        if (res == RESULT_OK && data != null) {
            if (data.getClipData() != null) {
                int n = data.getClipData().getItemCount();
                r = new Uri[n];
                for (int i = 0; i < n; i++) r[i] = data.getClipData().getItemAt(i).getUri();
            } else if (data.getData() != null) {
                r = new Uri[]{data.getData()};
            }
        }
        arquivosCb.onReceiveValue(r);
        arquivosCb = null;
    }

    private void imersivo() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
    }

    @Override
    public void onWindowFocusChanged(boolean f) {
        super.onWindowFocusChanged(f);
        if (f) imersivo();
    }

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("(function(){var s=document.querySelector('.sheet.open,#vnc.open,#painel.open');if(s){s.classList.remove('open');return 1}return 0})()",
            v -> { if ("0".equals(v)) MainActivity.super.onBackPressed(); });
    }
}
