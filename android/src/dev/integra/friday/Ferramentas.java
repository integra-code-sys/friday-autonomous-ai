package dev.integra.friday;

import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.hardware.camera2.CameraManager;
import android.media.AudioManager;
import android.net.Uri;
import android.provider.AlarmClock;
import android.provider.CalendarContract;
import android.provider.MediaStore;
import android.provider.Settings;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Locale;
import java.util.Map;

/** O que a Friday LOCAL sabe fazer no celular. Cada ferramenta devolve um texto curto com o resultado REAL
 *  (o modelo decide o próximo passo em cima disso). Navegação na tela usa o Serviço de Acessibilidade (Acesso). */
final class Ferramentas {
    static final String LISTA =
        "responder{texto} — fala final ao dono (sempre termine com ela)\n" +
        "calcular{expressao} — conta exata (ex.: 15*23, (1200-350)/4, 2^10, 15% de 80 = 0.15*80); use SEMPRE para contas\n" +
        "abrir_app{nome} — abre um app instalado (WhatsApp, YouTube, Câmera, Configurações...)\n" +
        "abrir_tela{tela: agenda|clima|alarmes|timers|contatos|galeria|mapas|mensagens|email|musica|downloads|camera|notificacoes}\n" +
        "flutuante{tipo: agenda|bolha|texto|fechar, titulo, texto} — mostra uma janela flutuante por cima de tudo (agenda dos próximos dias, nota, resultado)\n" +
        "abrir_site{url}\n" +
        "pesquisar{consulta, onde: google|google_us|ebay|amazon|mercadolivre|youtube|maps|playstore|spotify}\n" +
        "pesquisar_links{consulta} — pesquisa na internet e devolve os resultados: use para RESPONDER perguntas (quem, qual, quanto custa...)\n" +
        "ler_tela{} — lê o texto e os botões do app aberto\n" +
        "tocar{texto} — toca no botão/item com esse texto na tela\n" +
        "digitar{texto, enviar: true|false} — escreve no campo em foco\n" +
        "rolar{direcao: cima|baixo}\n" +
        "tecla{acao: voltar|inicio|recentes|notificacoes}\n" +
        "criar_documento{titulo, formato: pdf|docx|txt|md|html|py|json|csv, conteudo} — salva em Documentos/Friday e abre\n" +
        "alarme{hora, minuto, rotulo}\n" +
        "timer{segundos, rotulo}\n" +
        "agenda{op: novo|hoje|amanha|nivel|concluir|prioridade, titulo, quando: texto como 'amanhã 15h', prioridade: alta|normal|baixa, duracao_min} — AGENDA DA SEXTA-FEIRA sincronizada com o PC\n" +
        "evento{titulo, data: AAAA-MM-DD, hora: HH:MM, duracao_min} — adiciona evento na Agenda da Sexta-Feira\n" +
        "ligar{numero} — abre o discador com o número\n" +
        "whatsapp{contato, texto} — abre a conversa pelo NOME (ou número) e escreve a mensagem; o dono confirma o envio\n" +
        "compartilhar{texto}\n" +
        "lanterna{ligar: true|false}\n" +
        "volume{nivel: 0-100}\n" +
        "configuracao{tipo: wifi|bluetooth|tela|som|bateria|localizacao|aviao|apps}\n" +
        "foto{} — abre a câmera\n" +
        "lembrar{chave, valor} — guarda um fato do dono\n" +
        "memoria{busca} — consulta o que foi guardado\n" +
        "tailscale{ligar: true|false} — liga/desliga a VPN que liga o celular ao PC\n" +
        "dev{pedido} — MODO DEV: programação autônoma (Termux Claude, PC IDE ou geração local)\n" +
        "terminal{comando} — roda um comando Linux no Termux do celular e devolve a saída\n" +
        "pc{pedido} — manda a tarefa para a Friday do PC (só quando o PC estiver ligado; coisas do computador)";

    private final Context c;
    Ferramentas(Context c) { this.c = c.getApplicationContext(); }

    String executar(String acao, JSONObject a) {
        try {
            switch (acao) {
                case "calcular": return calcular(a.optString("expressao"));
                case "abrir_app": return abrirApp(a.optString("nome"));
                case "abrir_tela": return abrirTela(a.optString("tela"));
                case "flutuante": return flutuar(c, a.optString("tipo", "texto"), a.optString("titulo"), a.optString("texto"));
                case "tailscale": return Link.tailscale(c, a.optBoolean("ligar", true));
                case "abrir_site": return ver(Uri.parse(url(a.optString("url"))), "site aberto: " + a.optString("url"));
                case "pesquisar": return pesquisar(a.optString("consulta"), a.optString("onde", "google"));
                case "pesquisar_links": return extrairResumoWeb(a.optString("consulta"));
                case "ler_tela": return acesso() == null ? semAcesso() : Acesso.inst.telaTexto(70);
                case "tocar": return acesso() == null ? semAcesso() : Acesso.inst.tocarTexto(a.optString("texto")).toString();
                case "digitar": return digitar(a.optString("texto"), a.optBoolean("enviar", false));
                case "rolar": return acesso() == null ? semAcesso() : Acesso.inst.rolar("cima".equals(a.optString("direcao"))).toString();
                case "tecla": {
                    if (acesso() == null) return semAcesso();
                    Map<String, String> q = new HashMap<>(); q.put("a", a.optString("acao", "voltar"));
                    return Acesso.inst.rotear("/global", q).toString();
                }
                case "criar_documento": case "criar_arquivo":
                    return Docs.criar(c, a.optString("titulo", a.optString("nome", "Documento")),
                        a.optString("formato", "pdf"), a.optString("conteudo", a.optString("texto", "")));
                case "alarme": {
                    Intent i = new Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, a.optInt("hora"))
                        .putExtra(AlarmClock.EXTRA_MINUTES, a.optInt("minuto")).putExtra(AlarmClock.EXTRA_MESSAGE, a.optString("rotulo", "Friday"))
                        .putExtra(AlarmClock.EXTRA_SKIP_UI, true);
                    return iniciar(i, String.format(Locale.ROOT, "alarme criado para %02d:%02d", a.optInt("hora"), a.optInt("minuto")));
                }
                case "timer": {
                    Intent i = new Intent(AlarmClock.ACTION_SET_TIMER).putExtra(AlarmClock.EXTRA_LENGTH, a.optInt("segundos", 60))
                        .putExtra(AlarmClock.EXTRA_MESSAGE, a.optString("rotulo", "Friday")).putExtra(AlarmClock.EXTRA_SKIP_UI, true);
                    return iniciar(i, "timer de " + a.optInt("segundos", 60) + " s iniciado");
                }
                case "evento": return evento(a);
                case "agenda": return agenda(a);
                case "ligar": {
                    String num = resolverContato(a.optString("numero", a.optString("contato", "")));
                    return iniciar(new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + num)), "discador aberto" + (num.isEmpty() ? "" : " para " + num));
                }
                case "whatsapp": {
                    String alvo = a.optString("contato", a.optString("para", a.optString("numero", "")));
                    String txt = a.optString("texto", a.optString("mensagem", ""));
                    return Zap.preparar(c, this, alvo, txt);                 // abre a conversa e escreve; envia só com o "sim" do dono
                }
                case "compartilhar": {
                    Intent i = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, a.optString("texto"));
                    return iniciar(Intent.createChooser(i, "Compartilhar"), "tela de compartilhar aberta");
                }
                case "lanterna": {
                    CameraManager cm = (CameraManager) c.getSystemService(Context.CAMERA_SERVICE);
                    cm.setTorchMode(cm.getCameraIdList()[0], a.optBoolean("ligar", true));
                    return "lanterna " + (a.optBoolean("ligar", true) ? "ligada" : "desligada");
                }
                case "volume": {
                    AudioManager am = (AudioManager) c.getSystemService(Context.AUDIO_SERVICE);
                    int max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
                    int v = Math.max(0, Math.min(100, a.optInt("nivel", 50)));
                    am.setStreamVolume(AudioManager.STREAM_MUSIC, Math.round(max * v / 100f), AudioManager.FLAG_SHOW_UI);
                    return "volume em " + v + "%";
                }
                case "configuracao": return configuracao(a.optString("tipo"));
                case "foto": return iniciar(new Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA), "câmera aberta");
                case "lembrar": {
                    String ch = a.optString("chave");
                    String vl = a.optString("valor");
                    prefs().edit().putString("m:" + ch.toLowerCase(Locale.ROOT), vl).apply();
                    Sincronizador.notificarFatoLocal(c, ch, vl);
                    return "guardado: " + ch;
                }
                case "memoria": return memoria(a.optString("busca"));
                case "pc": return Link.pedirAoPc(c, a.optString("pedido"));
                case "dev": return Ide.iniciar(c, a.optString("pedido"), a.optString("pasta", null));
                case "terminal": return Dev.rodar(c, a.optString("comando"), 120);
                default: return "ferramenta desconhecida: " + acao;
            }
        } catch (Exception e) {
            return "falhou: " + e.getMessage();
        }
    }

    /** janelas flutuantes (desenhadas pelo serviço de acessibilidade; se desligado, abre a aba correspondente no app da Friday) */
    static String flutuar(Context c, String tipo, String titulo, String texto) {
        Context host = Acesso.inst != null ? Acesso.inst : null;
        if ("agenda".equals(tipo)) {
            if (host != null) { Flutuante.agendaPainel(host); return "agenda da Sexta-Feira flutuando na tela"; }
            c.startActivity(new Intent(c, MainActivity.class).putExtra("aba", "agenda")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP));
            return "agenda da Sexta-Feira aberta no app";
        }
        if (host == null) return "precisa do Serviço de Acessibilidade da Friday ligado";
        switch (tipo == null ? "texto" : tipo) {
            case "agenda_demo": Flutuante.agendaDemo(host); return "agenda de demonstração (eventos fictícios) na tela";
            case "bolha": {
                c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).edit().putBoolean("bolha", true).apply();
                Flutuante.bolha(host, true); return "bolha da Friday na tela";
            }
            case "fechar": {
                c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).edit().putBoolean("bolha", false).apply();
                Flutuante.fecharTudo(host); return "janelas flutuantes fechadas";
            }
            default:
                Flutuante.painel(host, "texto" + (System.currentTimeMillis() % 1000), titulo == null || titulo.isEmpty() ? "Friday" : titulo,
                    texto == null ? "" : texto);
                return "janela flutuante aberta";
        }
    }

    // ------------------------------------------------------------------ telas do sistema e da própria Friday
    private String abrirTela(String tela) throws Exception {
        String t = tela == null ? "" : tela.toLowerCase(Locale.ROOT).trim();
        switch (t) {
            case "agenda": case "calendario": case "calendário": {
                if (Acesso.inst != null) Flutuante.agendaPainel(Acesso.inst);
                c.startActivity(new Intent(c, MainActivity.class).putExtra("aba", "agenda")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP));
                return "agenda da Sexta-Feira aberta (" + Agenda.nivelFala(c, System.currentTimeMillis()) + ")";
            }
            case "dev": case "modo dev": case "ide": {
                if (Acesso.inst != null) Flutuante.ide(Acesso.inst, true);
                c.startActivity(new Intent(c, MainActivity.class).putExtra("aba", "dev")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP));
                return "Modo Dev da Sexta-Feira aberto";
            }
            case "clima": case "tempo": case "previsao": {
                Intent i = new Intent(Intent.ACTION_WEB_SEARCH).putExtra(android.app.SearchManager.QUERY, "clima");
                try { return iniciar(i, "previsão do tempo aberta"); }
                catch (Exception e) { return ver(Uri.parse("https://www.google.com/search?q=clima"), "previsão do tempo aberta"); }
            }
            case "alarmes": case "despertador": return iniciar(new Intent(AlarmClock.ACTION_SHOW_ALARMS), "alarmes abertos");
            case "timers": case "timer": return iniciar(new Intent(AlarmClock.ACTION_SHOW_TIMERS), "timers abertos");
            case "contatos": return ver(android.provider.ContactsContract.Contacts.CONTENT_URI, "contatos abertos");
            case "galeria": case "fotos": return ver(Uri.parse("content://media/external/images/media"), "galeria aberta");
            case "mapas": case "mapa": return ver(Uri.parse("geo:0,0?q="), "mapas aberto");
            case "camera": case "câmera": return iniciar(new Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA), "câmera aberta");
            case "downloads": case "arquivos": return iniciar(new Intent("android.intent.action.VIEW_DOWNLOADS"), "downloads abertos");
            case "notificacoes": case "notificações": {
                if (acesso() == null) return semAcesso();
                Map<String, String> q = new HashMap<>(); q.put("a", "notificacoes");
                return Acesso.inst.rotear("/global", q).optBoolean("ok") ? "notificações abertas" : "não consegui abrir as notificações";
            }
            default: {
                if (t.contains("agenda") || t.contains("calend")) return abrirTela("agenda");
                String cat = t.startsWith("mens") || t.equals("sms") ? Intent.CATEGORY_APP_MESSAGING : t.startsWith("e") ? Intent.CATEGORY_APP_EMAIL
                    : t.startsWith("mus") ? Intent.CATEGORY_APP_MUSIC : t.startsWith("naveg") ? Intent.CATEGORY_APP_BROWSER : null;
                if (cat != null) return iniciar(Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, cat), tela + " aberto");
                return abrirApp(tela);
            }
        }
    }

    // ------------------------------------------------------------------ calculadora exata (o modelo pequeno erra conta)
    private String calcular(String e) {
        try {
            String x = e.replaceAll("=.*$", "")                         // "15% de 80 = 0.15*80": fica só o lado esquerdo
                .replaceAll("(?i)\\s*por\\s*cento", "%").replaceAll("(?i)(\\d+(?:[.,]\\d+)?)\\s*%\\s*(?:de|do|da|sobre)\\s*", "($1/100)*")
                .replaceAll("(\\d+(?:[.,]\\d+)?)\\s*%", "($1/100)").replaceAll("(?i)\\bvezes\\b", "*").replaceAll("(?i)\\bdividido por\\b", "/")
                .replaceAll("(?i)\\bmais\\b", "+").replaceAll("(?i)\\bmenos\\b", "-");
            x = x.replace(",", ".").replace("×", "*").replace("x", "*").replace("÷", "/").replaceAll("\\s+", "");
            double[] pos = {0};
            double v = soma(x, pos);
            if (pos[0] < x.length()) return "não entendi a expressão: " + e;
            String r = v == Math.rint(v) && Math.abs(v) < 1e15 ? String.valueOf((long) v) : String.format(Locale.ROOT, "%.6f", v).replaceAll("0+$", "").replaceAll("\\.$", "");
            return e + " = " + r.replace(".", ",");
        } catch (Exception ex) { return "não consegui calcular: " + e; }
    }
    private static double soma(String s, double[] p) {
        double v = prod(s, p);
        while (p[0] < s.length()) {
            char c = s.charAt((int) p[0]);
            if (c == '+') { p[0]++; v += prod(s, p); } else if (c == '-') { p[0]++; v -= prod(s, p); } else break;
        }
        return v;
    }
    private static double prod(String s, double[] p) {
        double v = pot(s, p);
        while (p[0] < s.length()) {
            char c = s.charAt((int) p[0]);
            if (c == '*') { p[0]++; v *= pot(s, p); } else if (c == '/') { p[0]++; v /= pot(s, p); }
            else if (c == '%') { p[0]++; v /= 100; } else break;
        }
        return v;
    }
    private static double pot(String s, double[] p) {
        double b = un(s, p);
        if (p[0] < s.length() && s.charAt((int) p[0]) == '^') { p[0]++; return Math.pow(b, pot(s, p)); }
        return b;
    }
    private static double un(String s, double[] p) {
        if (p[0] < s.length() && s.charAt((int) p[0]) == '-') { p[0]++; return -un(s, p); }
        if (p[0] < s.length() && s.charAt((int) p[0]) == '(') { p[0]++; double v = soma(s, p); p[0]++; return v; }
        int i = (int) p[0];
        while (p[0] < s.length() && (Character.isDigit(s.charAt((int) p[0])) || s.charAt((int) p[0]) == '.')) p[0]++;
        return Double.parseDouble(s.substring(i, (int) p[0]));
    }

    // ------------------------------------------------------------------ apoio
    private SharedPreferences prefs() { return c.getSharedPreferences("friday_local", Context.MODE_PRIVATE); }
    private static Acesso acesso() { return Acesso.inst; }
    private static String semAcesso() { return "sem o Serviço de Acessibilidade ligado (Configurações > Acessibilidade > F.R.I.D.A.Y.)"; }
    private static String url(String u) { return u.matches("(?i)^[a-z]+://.*") ? u : "https://" + u; }

    private String iniciar(Intent i, String ok) {
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        c.startActivity(i);
        return ok;
    }

    private String ver(Uri u, String ok) { return iniciar(new Intent(Intent.ACTION_VIEW, u), ok); }

    private String abrirApp(String nome) throws Exception {
        if (acesso() != null) {
            Map<String, String> q = new HashMap<>(); q.put("nome", nome);
            JSONObject r = Acesso.inst.rotear("/abrir", q);
            return r.optBoolean("ok") ? "aberto: " + r.optString("app") : r.optString("erro");
        }
        android.content.pm.PackageManager pm = c.getPackageManager();
        String alvo = nome.toLowerCase(Locale.ROOT);
        for (android.content.pm.ApplicationInfo ap : pm.getInstalledApplications(0)) {
            String l = String.valueOf(pm.getApplicationLabel(ap)).toLowerCase(Locale.ROOT);
            if (l.contains(alvo)) {
                Intent i = pm.getLaunchIntentForPackage(ap.packageName);
                if (i != null) return iniciar(i, "aberto: " + pm.getApplicationLabel(ap));
            }
        }
        return "app não encontrado: " + nome;
    }

    static String limparTermoBusca(String q) {
        if (q == null) return "";
        String s = q.trim();
        s = s.replaceAll("(?iu)^\\s*(?:sexta[- ]?feira|friday)[,:\\s]*", "");
        s = s.replaceAll("(?iu)^\\s*(?:por\\s+favor[,:\\s]*)?(?:apenas\\s+|s[óo]\\s+)?(?:abr[ae](?:\\s+o\\s+navegador|\\s+o\\s+chrome|\\s+uma\\s+nova\\s+aba|\\s+nova\\s+aba)?\\s*(?:e\\s+)?)?(?:pesquis\\w*|busc\\w*|procur\\w*)\\s*(?:por|sobre|pelo|pela|pelos|pelas)?\\s*", "");
        s = s.replaceAll("(?iu)\\b(?:em\\s+uma\\s+nova\\s+aba|numa\\s+nova\\s+aba|na\\s+nova\\s+aba|em\\s+nova\\s+aba|no\\s+navegador|pelo\\s+navegador|no\\s+chrome|no\\s+google)\\b", " ");
        s = s.replaceAll("(?iu)\\s*(?:e\\s+)?(?:me\\s+)?(?:mostr\\w+|dig\\w+|fal\\w+|trag\\w+|resum\\w+)\\s+(?:o\\s+que|oque|tudo\\s+que)\\s+(?:achar|encontrar|ver).*$", "");
        s = s.replaceAll("(?iu)\\b(?:em\\s+sites?\\s+americanos?(?:\\s+como\\s+[\\w\\s,e]+)?|(?:no|na|em|nos|nas|como)\\s+(?:ebay(?:\\s+e\\s+amazon(?:\\s+global)?)?|amazon(?:\\s+global|\\s+brasil)?|mercado\\s*livre|mercadolivre|shopee|aliexpress|sites?\\s+americanos?|lojas?\\s+americanas?))\\b", " ");
        s = s.replaceAll("\\s+", " ").replaceAll("^[ ,.!?]+|[ ,.!?]+$", "");
        return s;
    }

    private String pesquisar(String q, String onde) throws Exception {
        String raw = ((q == null ? "" : q) + " " + (onde == null ? "" : onde)).toLowerCase(Locale.ROOT);
        String limpo = limparTermoBusca(q);
        if (limpo.isEmpty()) limpo = (q == null ? "" : q.trim());
        String e = URLEncoder.encode(limpo, "UTF-8");
        String o = onde == null ? "google" : onde.toLowerCase(Locale.ROOT).trim();
        if (o.equals("ebay") || raw.matches("(?s).*\\bebay\\b.*")) {
            return ver(Uri.parse("https://www.ebay.com/sch/i.html?_nkw=" + e), "pesquisa no eBay: " + limpo);
        }
        if (o.equals("amazon") || raw.matches("(?s).*\\bamazon\\b.*")) {
            return ver(Uri.parse("https://www.amazon.com/s?k=" + e), "pesquisa na Amazon: " + limpo);
        }
        if (o.equals("mercadolivre") || raw.matches("(?s).*\\bmercado\\s*livre\\b.*")) {
            return ver(Uri.parse("https://lista.mercadolivre.com.br/" + URLEncoder.encode(limpo.replace(" ", "-"), "UTF-8")), "pesquisa no Mercado Livre: " + limpo);
        }
        if (o.equals("google_us") || raw.matches("(?s).*\\b(sites?\\s+americanos?|lojas?\\s+americanas?|estados\\s+unidos)\\b.*")) {
            return ver(Uri.parse("https://www.google.com/search?q=" + e + "&hl=en&gl=us"), "pesquisa em sites americanos (Google US): " + limpo);
        }
        switch (o) {
            case "youtube": return ver(Uri.parse("https://www.youtube.com/results?search_query=" + e), "pesquisa no YouTube: " + limpo);
            case "maps": return ver(Uri.parse("geo:0,0?q=" + e), "Maps procurando: " + limpo);
            case "playstore": return ver(Uri.parse("market://search?q=" + e), "Play Store procurando: " + limpo);
            case "spotify": return ver(Uri.parse("spotify:search:" + e), "Spotify procurando: " + limpo);
            default: return ver(Uri.parse("https://www.google.com/search?q=" + e), "pesquisa no navegador (Google): " + limpo);
        }
    }

    private String pesquisarLinks(String q) {
        try {
            String limpo = limparTermoBusca(q);
            if (limpo.isEmpty()) limpo = q == null ? "" : q.trim();
            URL u = new URL("https://html.duckduckgo.com/html/?q=" + URLEncoder.encode(limpo, "UTF-8"));
            HttpURLConnection con = (HttpURLConnection) u.openConnection();
            con.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36");
            con.setConnectTimeout(8000);
            con.setReadTimeout(8000);
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            java.io.InputStream in = con.getInputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0 && bos.size() < 200000) bos.write(buf, 0, n);
            in.close();
            String htm = new String(bos.toByteArray(), StandardCharsets.UTF_8);
            java.util.regex.Matcher m = java.util.regex.Pattern.compile("(?s)<a[^>]*class=\"result__a\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>(?:.*?<a[^>]*class=\"result__snippet\"[^>]*>(.*?)</a>)?").matcher(htm);
            StringBuilder sb = new StringBuilder();
            int count = 0;
            while (m.find() && count < 4) {
                String href = m.group(1).replace("&amp;", "&");
                java.util.regex.Matcher mu = java.util.regex.Pattern.compile("[?&]uddg=([^&]+)").matcher(href);
                String link = mu.find() ? java.net.URLDecoder.decode(mu.group(1), "UTF-8") : href;
                if (link.contains("duckduckgo.com/y.js") || link.contains("/aclick?")) continue;
                String tit = m.group(2).replaceAll("<[^>]+>", "").replace("&quot;", "\"").replace("&amp;", "&").trim();
                String snip = m.group(3) == null ? "" : m.group(3).replaceAll("<[^>]+>", "").replace("&quot;", "\"").replace("&amp;", "&").trim();
                sb.append("• ").append(tit).append(snip.isEmpty() ? "" : " — " + snip).append("\n  ").append(link).append("\n");
                count++;
            }
            if (sb.length() == 0) return "Não encontrei links diretos para " + limpo + ".";
            return "Encontrei estes resultados para " + limpo + ":\n" + sb.toString().trim();
        } catch (Exception e) {
            return "falhou ao buscar links: " + e.getMessage();
        }
    }

    /** texto da busca (Google num WebView invisível; reserva Wikipédia e DuckDuckGo) para RESPONDER perguntas */
    String extrairResumoWeb(String q) {
        String limpo = limparTermoBusca(q);
        String t = BuscaWeb.buscar(c, limpo.isEmpty() ? q : limpo, 12000);
        if (t.length() >= 80) return "Resultados da busca por " + limpo + ":\n" + (t.length() > 2600 ? t.substring(0, 2600) : t);
        return pesquisarLinks(q);
    }

    String resolverContato(String alvo) {
        if (alvo == null) return "";
        String dig = alvo.replaceAll("[^0-9]", "");
        if (dig.length() >= 8) return dig;
        String n = Agenda.norm(alvo).trim();
        if (n.isEmpty()) return "";
        // 1) Procura na memória local da Friday
        for (Map.Entry<String, ?> e : prefs().getAll().entrySet()) {
            if (!e.getKey().startsWith("m:")) continue;
            String k = Agenda.norm(e.getKey().substring(2)), v = String.valueOf(e.getValue());
            if (k.contains(n) || Agenda.norm(v).contains(n)) {
                String d = v.replaceAll("[^0-9]", "");
                if (d.length() >= 8) return d;
            }
        }
        // 2) Procura nos contatos do Android se tiver permissão
        try {
            if (c.checkSelfPermission(android.Manifest.permission.READ_CONTACTS) == android.content.pm.PackageManager.PERMISSION_GRANTED) {
                try (android.database.Cursor cur = c.getContentResolver().query(
                        android.provider.ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                        new String[]{android.provider.ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                                     android.provider.ContactsContract.CommonDataKinds.Phone.NUMBER},
                        null, null, null)) {
                    while (cur != null && cur.moveToNext()) {
                        String nome = Agenda.norm(cur.getString(0));
                        if (nome.contains(n)) {
                            String d = (cur.getString(1) == null ? "" : cur.getString(1)).replaceAll("[^0-9]", "");
                            if (d.length() >= 8) return d.startsWith("55") || d.length() > 11 ? d : "55" + d;
                        }
                    }
                }
            }
        } catch (Exception ignored) {}
        return "";
    }

    private String digitar(String t, boolean enviar) throws Exception {
        if (acesso() == null) return semAcesso();
        Map<String, String> q = new HashMap<>(); q.put("t", t);
        JSONObject r = Acesso.inst.rotear("/texto", q);
        if (!r.optBoolean("ok")) return "não consegui digitar: " + r.optString("erro", "sem campo em foco (toque no campo antes)");
        if (enviar) {
            for (String b : new String[]{"Enviar", "Send", "Pesquisar", "Buscar", "Search", "Ir"}) {
                JSONObject t2 = Acesso.inst.tocarTexto(b);
                if (t2.optBoolean("ok")) return "digitado e enviado";
            }
            return "digitado (não achei o botão de enviar)";
        }
        return "digitado";
    }

    private static int prioDe(String p) {
        String t = Agenda.norm(p);
        return t.matches(".*(alta|urgente|importante|1).*") ? 1 : t.matches(".*(baixa|opcional|3).*") ? 3 : 2;
    }

    private String agenda(JSONObject a) {
        String op = Agenda.norm(a.optString("op", "hoje"));
        long agora = System.currentTimeMillis();
        switch (op) {
            case "novo": case "adicionar": case "marcar": {
                String res = Agenda.novo(c, a.optString("titulo"), a.optString("quando"), prioDe(a.optString("prioridade", "normal")), a.optInt("duracao_min", 60));
                if (Acesso.inst != null) Flutuante.agendaPainel(Acesso.inst);
                return res;
            }
            case "abrir": case "mostrar": case "ver": {
                try { return abrirTela("agenda"); } catch (Exception e) { return Agenda.nivelFala(c, agora); }
            }
            case "nivel":
                return Agenda.nivelFala(c, a.optString("quando").contains("amanh") ? agora + 86400000L : agora);
            case "concluir": case "prioridade": {
                Agenda.Item i = Agenda.buscar(c, a.optString("titulo"));
                if (i == null) return "não achei '" + a.optString("titulo") + "' na agenda";
                if (op.equals("concluir")) { Agenda.mudar(c, i.id, "feito", true); return "marquei " + i.titulo + " como feito"; }
                int p = prioDe(a.optString("prioridade", "alta"));
                Agenda.mudar(c, i.id, "prioridade", p);
                return i.titulo + " agora tem prioridade " + (p == 1 ? "alta" : p == 3 ? "baixa" : "normal");
            }
            default: {
                long d0 = Agenda.inicioDoDia(op.startsWith("amanh") ? agora + 86400000L : agora);
                java.util.List<Agenda.Item> l = Agenda.itens(c, d0, d0 + 86400000L);
                if (Acesso.inst != null) Flutuante.agendaPainel(Acesso.inst);
                if (l.isEmpty()) return (op.startsWith("amanh") ? "amanhã" : "hoje") + " está livre";
                StringBuilder sb = new StringBuilder(Agenda.nivelFala(c, d0)).append(" Itens:");
                SimpleDateFormat h = new SimpleDateFormat("HH:mm", Locale.ROOT);
                for (Agenda.Item i : l) sb.append("\n").append(i.diaTodo ? "dia todo" : h.format(new java.util.Date(i.ini))).append(" ")
                    .append(i.titulo).append(i.prio == 1 ? " (prioridade alta)" : "").append(i.feito ? " (feito)" : "");
                return sb.toString();
            }
        }
    }

    private String evento(JSONObject a) {
        String titulo = a.optString("titulo", "Compromisso");
        String quando = (a.optString("data", "") + " " + a.optString("hora", a.optString("quando", "hoje 09:00"))).trim();
        int prio = prioDe(a.optString("prioridade", "normal"));
        int dur = a.optInt("duracao_min", 60);
        String res = Agenda.novo(c, titulo, quando, prio, dur);
        if (Acesso.inst != null) Flutuante.agendaPainel(Acesso.inst);
        return res;
    }

    private String configuracao(String tipo) {
        String a;
        switch (tipo) {
            case "wifi": a = Settings.ACTION_WIFI_SETTINGS; break;
            case "bluetooth": a = Settings.ACTION_BLUETOOTH_SETTINGS; break;
            case "tela": a = Settings.ACTION_DISPLAY_SETTINGS; break;
            case "som": a = Settings.ACTION_SOUND_SETTINGS; break;
            case "bateria": a = Intent.ACTION_POWER_USAGE_SUMMARY; break;
            case "localizacao": a = Settings.ACTION_LOCATION_SOURCE_SETTINGS; break;
            case "aviao": a = Settings.ACTION_AIRPLANE_MODE_SETTINGS; break;
            case "apps": a = Settings.ACTION_APPLICATION_SETTINGS; break;
            default: a = Settings.ACTION_SETTINGS;
        }
        return iniciar(new Intent(a), "configurações de " + tipo + " abertas");
    }

    private String memoria(String busca) {
        StringBuilder sb = new StringBuilder();
        String b = busca.toLowerCase(Locale.ROOT);
        for (Map.Entry<String, ?> e : prefs().getAll().entrySet()) {
            if (!e.getKey().startsWith("m:")) continue;
            String k = e.getKey().substring(2), v = String.valueOf(e.getValue());
            if (b.isEmpty() || k.contains(b) || v.toLowerCase(Locale.ROOT).contains(b)) sb.append(k).append(": ").append(v).append('\n');
        }
        return sb.length() == 0 ? "nada guardado sobre isso" : sb.toString();
    }

    /** fatos guardados, para o prompt de sistema */
    String fatos(int max) {
        StringBuilder sb = new StringBuilder();
        int n = 0;
        for (Map.Entry<String, ?> e : prefs().getAll().entrySet()) {
            if (!e.getKey().startsWith("m:") || n++ >= max) continue;
            sb.append("- ").append(e.getKey().substring(2)).append(": ").append(e.getValue()).append('\n');
        }
        return sb.toString();
    }
}
