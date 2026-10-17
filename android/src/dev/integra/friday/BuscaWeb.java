package dev.integra.friday;

import android.annotation.SuppressLint;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Pesquisa na web autônoma e à prova de bloqueios:
 *  1. DuckDuckGo API (respostas diretas e tópicos relacionados)
 *  2. DuckDuckGo Lite / HTML (links orgânicos sem rastreadores)
 *  3. Wikipédia REST API (resumo completo e contextualizado)
 *  4. Raspagem profunda dos artigos mais relevantes (extração de texto real)
 *  5. Fallback para WebView caso tudo falhe. */
final class BuscaWeb {
    private BuscaWeb() {}

    private static final Handler main = new Handler(Looper.getMainLooper());
    private static WebView wv;

    private static final String USER_AGENT = "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36";

    /** Pesquisa na web detalhada e estruturada com extração de conteúdo real */
    static String buscar(Context c, String consulta, long timeoutMs) {
        if (Looper.myLooper() == Looper.getMainLooper()) return "";
        if (consulta == null || consulta.trim().isEmpty()) return "";
        consulta = consulta.trim();
        long t0 = System.currentTimeMillis();

        StringBuilder resultado = new StringBuilder();

        // 1. DuckDuckGo Instant Answer API
        try {
            String ddgApi = duckDuckGoApi(consulta);
            if (!ddgApi.isEmpty()) {
                resultado.append(ddgApi).append("\n\n");
            }
        } catch (Exception e) {
            android.util.Log.d("friday-busca", "ddg-api: " + e);
        }

        // 2. Wikipédia (busca e extrato em português)
        try {
            String wiki = wikipedia(consulta);
            if (!wiki.isEmpty()) {
                resultado.append(wiki).append("\n\n");
            }
        } catch (Exception e) {
            android.util.Log.d("friday-busca", "wiki: " + e);
        }

        // 3. DuckDuckGo Lite / HTML + Leitura de páginas
        try {
            Map<String, String> links = duckDuckGoLinks(consulta);
            if (!links.isEmpty()) {
                resultado.append("Fontes e Descobertas:\n");
                int lidos = 0;
                for (Map.Entry<String, String> entry : links.entrySet()) {
                    String url = entry.getKey();
                    String titulo = entry.getValue();
                    resultado.append("• ").append(titulo).append("\n  ").append(url).append("\n");

                    // Raspa os 2 primeiros links para obter texto substancial
                    if (lidos < 2 && !url.contains("wikipedia.org")) {
                        String corpo = extrairTextoPagina(url);
                        if (corpo.length() > 150) {
                            resultado.append("  Trecho relevante: ").append(corpo).append("\n\n");
                            lidos++;
                        }
                    }
                }
            }
        } catch (Exception e) {
            android.util.Log.d("friday-busca", "ddg-links: " + e);
        }

        // 4. Se ainda tiver muito pouco conteúdo, recorre ao WebView
        if (resultado.length() < 120 && c != null) {
            try {
                String g = google(c, consulta, Math.min(timeoutMs, 8000));
                if (g.length() > 80) resultado.append(g);
            } catch (Exception e) {
                android.util.Log.d("friday-busca", "google-wv: " + e);
            }
        }

        String finalTxt = resultado.toString().trim();
        android.util.Log.i("friday-busca", "Busca concluída (" + finalTxt.length() + " chars em " + (System.currentTimeMillis() - t0) + " ms): " + consulta);
        return finalTxt;
    }

    // ------------------------------------------------------------------ DuckDuckGo API
    private static String duckDuckGoApi(String q) {
        try {
            String u = "https://api.duckduckgo.com/?q=" + URLEncoder.encode(q, "UTF-8") + "&format=json&no_html=1&skip_disambig=1";
            String json = getHttp(u, 5000);
            JSONObject o = new JSONObject(json);
            StringBuilder sb = new StringBuilder();
            String abstractText = o.optString("AbstractText", "");
            String heading = o.optString("Heading", "");
            if (!abstractText.isEmpty()) {
                if (!heading.isEmpty()) sb.append("Síntese (").append(heading).append("): ");
                sb.append(abstractText);
                return sb.toString();
            }
            JSONArray related = o.optJSONArray("RelatedTopics");
            if (related != null && related.length() > 0) {
                for (int i = 0; i < Math.min(2, related.length()); i++) {
                    JSONObject t = related.optJSONObject(i);
                    if (t != null && t.has("Text")) {
                        if (sb.length() > 0) sb.append("\n");
                        sb.append("• ").append(t.getString("Text"));
                    }
                }
            }
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    // ------------------------------------------------------------------ DuckDuckGo Links
    static Map<String, String> duckDuckGoLinks(String q) {
        Map<String, String> out = new LinkedHashMap<>();
        try {
            String u = "https://html.duckduckgo.com/html/?q=" + URLEncoder.encode(q, "UTF-8") + "&kl=br-pt";
            String html = getHttp(u, 7000);
            Matcher m = Pattern.compile("(?s)<a[^>]*class=\"result__a\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>(?:.*?<a[^>]*class=\"result__snippet\"[^>]*>(.*?)</a>)?").matcher(html);
            int count = 0;
            while (m.find() && count < 6) {
                String href = m.group(1).replace("&amp;", "&");
                Matcher mu = Pattern.compile("[?&]uddg=([^&]+)").matcher(href);
                String link = mu.find() ? java.net.URLDecoder.decode(mu.group(1), "UTF-8") : href;
                if (link.contains("duckduckgo.com/y.js") || link.contains("/aclick?") || link.contains("youtube.com") || link.contains("facebook.com")) continue;
                String tit = m.group(2).replaceAll("<[^>]+>", "").replace("&quot;", "\"").replace("&amp;", "&").trim();
                String snip = m.group(3) == null ? "" : m.group(3).replaceAll("<[^>]+>", "").replace("&quot;", "\"").replace("&amp;", "&").trim();
                out.put(link, tit + (snip.isEmpty() ? "" : " — " + snip));
                count++;
            }
        } catch (Exception ignored) {}
        return out;
    }

    // ------------------------------------------------------------------ Raspagem de Artigo
    private static String extrairTextoPagina(String urlStr) {
        try {
            String html = getHttp(urlStr, 5000);
            if (html.isEmpty()) return "";
            // Remove scripts, estilos e cabeçalhos desnecessários
            String semScripts = html.replaceAll("(?is)<script.*?</script>", " ")
                                    .replaceAll("(?is)<style.*?</style>", " ")
                                    .replaceAll("(?is)<nav.*?</nav>", " ")
                                    .replaceAll("(?is)<header.*?</header>", " ")
                                    .replaceAll("(?is)<footer.*?</footer>", " ");
            Matcher mp = Pattern.compile("(?is)<p[^>]*>(.*?)</p>").matcher(semScripts);
            StringBuilder sb = new StringBuilder();
            int count = 0;
            while (mp.find() && count < 6) {
                String p = mp.group(1).replaceAll("<[^>]+>", " ")
                                     .replaceAll("&nbsp;", " ")
                                     .replaceAll("&quot;", "\"")
                                     .replaceAll("&amp;", "&")
                                     .replaceAll("\\s+", " ").trim();
                if (p.length() > 60 && !p.toLowerCase().contains("cookie") && !p.toLowerCase().contains("assine")) {
                    sb.append(p).append(" ");
                    count++;
                }
            }
            String t = sb.toString().trim();
            return t.length() > 1000 ? t.substring(0, 1000) + "..." : t;
        } catch (Exception e) {
            return "";
        }
    }

    // ------------------------------------------------------------------ Wikipédia
    private static String wikipedia(String q) {
        try {
            String searchUrl = "https://pt.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=2&srsearch=" + URLEncoder.encode(q, "UTF-8");
            JSONObject s = new JSONObject(getHttp(searchUrl, 5000));
            JSONArray l = s.getJSONObject("query").getJSONArray("search");
            if (l.length() == 0) return "";
            String tit = l.getJSONObject(0).getString("title");

            String sumUrl = "https://pt.wikipedia.org/api/rest_v1/page/summary/" + URLEncoder.encode(tit.replace(' ', '_'), "UTF-8").replace("+", "%20");
            JSONObject sm = new JSONObject(getHttp(sumUrl, 5000));
            String extract = sm.optString("extract", "");
            if (extract.isEmpty()) return "";
            return "Wikipédia (" + tit + "):\n" + extract;
        } catch (Exception e) {
            return "";
        }
    }

    // ------------------------------------------------------------------ Fallback Google WebView
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
                    wv.getSettings().setUserAgentString(USER_AGENT);
                    wv.getSettings().setBlockNetworkImage(true);
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
            } catch (Exception e) { fim.countDown(); }
        });
        try { fim.await(timeoutMs, TimeUnit.MILLISECONDS); } catch (InterruptedException ignored) {}
        String t = r[0] == null ? "" : r[0];
        StringBuilder sb = new StringBuilder();
        for (String l : t.split("\n")) {
            String s = l.trim();
            if (s.length() < 3 || s.matches("(?i)(todas|imagens|vídeos|notícias|shopping|mais|ferramentas|maps|livros|voos|finanças|sobre este resultado|traduzir esta página|mais resultados|resultados da web)")) continue;
            sb.append(s).append('\n');
        }
        return sb.toString().trim();
    }

    private static String getHttp(String u, int timeoutMs) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL(u).openConnection();
        h.setConnectTimeout(timeoutMs);
        h.setReadTimeout(timeoutMs);
        h.setRequestProperty("User-Agent", USER_AGENT);
        h.setRequestProperty("Accept-Language", "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7");
        h.setRequestProperty("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8");
        try (InputStream in = h.getInputStream()) {
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] b = new byte[8192]; int n;
            while ((n = in.read(b)) > 0 && bo.size() < 300000) bo.write(b, 0, n);
            return new String(bo.toByteArray(), StandardCharsets.UTF_8);
        } finally {
            h.disconnect();
        }
    }
}
