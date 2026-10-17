package dev.integra.friday;

import android.annotation.SuppressLint;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Pesquisa na web SEM chave de API: um WebView invisível abre a busca do Google como um navegador de verdade (o Google
 *  exige JavaScript e o DuckDuckGo/Bing bloqueiam robôs) e devolve o TEXTO da página de resultados — inclusive o quadro
 *  de resposta. Reserva: Wikipédia (conhecimento geral). Quem chama NÃO pode estar na thread principal. */
final class BuscaWeb {
    private BuscaWeb() {}

    private static final Handler main = new Handler(Looper.getMainLooper());
    private static WebView wv;

    /** texto útil da busca (até ~3 mil caracteres) ou "" se não deu */
    static String buscar(Context c, String consulta, long timeoutMs) {
        if (Looper.myLooper() == Looper.getMainLooper()) return "";
        long t0 = System.currentTimeMillis();
        String t = google(c, consulta, timeoutMs);
        android.util.Log.i("friday-busca", "google " + t.length() + " chars em " + (System.currentTimeMillis() - t0) + " ms: " + consulta);
        if (t.length() < 80) {
            t = wikipedia(consulta);
            android.util.Log.i("friday-busca", "wikipédia " + t.length() + " chars");
        }
        return t;
    }

    @SuppressLint("SetJavaScriptEnabled")
    private static String google(Context c, String q, long timeoutMs) {
        final String[] r = {""};
        final CountDownLatch fim = new CountDownLatch(1);
        main.post(() -> {
            try {
                if (wv == null) {
                    wv = new WebView(c.getApplicationContext());
                    wv.getSettings().setJavaScriptEnabled(true);
                    wv.getSettings().setDomStorageEnabled(true);
                    wv.getSettings().setBlockNetworkImage(true);           // só o texto interessa
                }
                final boolean[] lido = {false};
                wv.setWebViewClient(new WebViewClient() {
                    @Override public void onPageFinished(WebView v, String url) {
                        if (lido[0] || url == null || !url.contains("/search")) return;
                        lido[0] = true;
                        main.postDelayed(() -> v.evaluateJavascript(
                            "(function(){var e=document.querySelector('#rso')||document.querySelector('#search')||document.querySelector('#main')||document.body;"
                                + "var a=document.querySelector('[data-attrid],.kp-header,.ifM9O');"
                                + "return ((a?a.innerText+'\\n':'')+(e?e.innerText:'')).slice(0,3500);})()",
                            val -> {
                                try { r[0] = new JSONArray("[" + val + "]").optString(0, ""); } catch (Exception ignored) {}
                                fim.countDown();
                            }), 700);
                    }
                });
                wv.loadUrl("https://www.google.com/search?hl=pt-BR&gl=br&q=" + URLEncoder.encode(q, "UTF-8"));
            } catch (Exception e) { android.util.Log.w("friday-busca", "webview: " + e); fim.countDown(); }
        });
        try { fim.await(timeoutMs, TimeUnit.MILLISECONDS); } catch (InterruptedException ignored) {}
        String t = r[0] == null ? "" : r[0];
        // tira menus e lixo de interface
        StringBuilder sb = new StringBuilder();
        for (String l : t.split("\n")) {
            String s = l.trim();
            if (s.length() < 3 || s.matches("(?i)(todas|imagens|vídeos|notícias|shopping|mais|ferramentas|maps|livros|voos|finanças|sobre este resultado|traduzir esta página|mais resultados|resultados da web)")) continue;
            sb.append(s).append('\n');
        }
        return sb.toString().trim();
    }

    private static String wikipedia(String q) {
        try {
            JSONObject s = new JSONObject(get("https://pt.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1&srsearch=" + URLEncoder.encode(q, "UTF-8")));
            JSONArray l = s.getJSONObject("query").getJSONArray("search");
            if (l.length() == 0) return "";
            String tit = l.getJSONObject(0).getString("title");
            JSONObject sm = new JSONObject(get("https://pt.wikipedia.org/api/rest_v1/page/summary/" + URLEncoder.encode(tit.replace(' ', '_'), "UTF-8").replace("+", "%20")));
            return "Wikipédia — " + tit + ": " + sm.optString("extract", "");
        } catch (Exception e) { return ""; }
    }

    private static String get(String u) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL(u).openConnection();
        h.setConnectTimeout(6000); h.setReadTimeout(8000);
        h.setRequestProperty("User-Agent", "FridayAndroid/1.0 (assistente pessoal)");
        try (java.io.InputStream in = h.getInputStream()) {
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] b = new byte[8192]; int n;
            while ((n = in.read(b)) > 0 && bo.size() < 400000) bo.write(b, 0, n);
            return new String(bo.toByteArray(), StandardCharsets.UTF_8);
        } finally { h.disconnect(); }
    }
}
