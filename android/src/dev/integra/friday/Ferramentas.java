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

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
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
        "abrir_app{nome} — abre um app. navegador/chrome/internet abre o navegador do sistema por intent, mesmo que o rótulo seja Chrome ou Firefox\n" +
        "claude{pedido} — Claude Code no Termux, se o binário existir\n" +
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
        "alarme{hora: 0-23, minuto, quando: palavras do dono como 'amanhã 7h' ou 'daqui 10 minutos', rotulo}\n" +
        "timer{segundos ou minutos, rotulo}\n" +
        "agenda{op: novo|hoje|amanha|nivel|concluir|prioridade, titulo, quando: texto como 'amanhã 15h', prioridade: alta|normal|baixa, duracao_min} — AGENDA DA SEXTA-FEIRA sincronizada com o PC\n" +
        "evento{titulo, quando: palavras do dono como 'sábado 15h', 'amanhã 9h', '24/10 14h' (NÃO calcule a data), duracao_min} — adiciona evento na Agenda da Sexta-Feira\n" +
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
        "bateria{} — lê porcentagem e status de carregamento da bateria do aparelho\n" +
        "hora{} — data e hora exatas do sistema\n" +
        "pc{pedido} — manda a tarefa para a Friday do PC (só quando o PC estiver ligado; coisas do computador)";

    private final Context c;
    Ferramentas(Context c) { this.c = c.getApplicationContext(); }

    String executar(String acao, JSONObject a) {
        try {
            switch (acao) {
                case "calcular": return calcular(a.optString("expressao"));
                case "abrir_app": {
                    String nome = a.optString("nome", "");
                    if (nome.isEmpty()) nome = a.optString("name", "");
                    if (nome.isEmpty()) nome = a.optString("app", "");
                    return abrirApp(nome);
                }
                case "claude": return claude(a.optString("pedido"));
                case "abrir_tela": return abrirTela(a.optString("tela"));
                case "flutuante": return flutuar(c, a.optString("tipo", "texto"), a.optString("titulo"), a.optString("texto"));
                case "tailscale": return Link.tailscale(c, a.optBoolean("ligar", true));
                case "abrir_site": return ver(Uri.parse(url(a.optString("url"))), "site aberto: " + a.optString("url"));
                case "pesquisar": return investigar(a.optString("consulta", a.optString("q", "")), a.optString("onde", "google"));
                case "pesquisar_links": return extrairResumoWeb(a.optString("consulta"));
                case "ler_tela": return acesso() == null ? semAcesso() : Acesso.inst.telaTexto(70);
                case "detectar_dificuldade": return acesso() == null ? semAcesso() : Acesso.inst.detectarDificuldade();
                case "percepcao_celular": {
                    String dif = acesso() == null ? "Acessibilidade inativa" : Acesso.inst.detectarDificuldade();
                    return "Percepção do Celular:\n- " + dif + "\n- Estado: Operacional";
                }
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
                    // o modelo manda "07:30", "7h30", "3 da tarde", "amanhã 8h"... (optInt("hora") lia tudo isso como 0 -> alarme 00:00)
                    long agora = System.currentTimeMillis(), t = alvoAlarme(a, agora);
                    if (t <= agora) return "não entendi a hora do alarme: " + (a.optString("quando") + " " + a.optString("hora")).trim();
                    Calendar k = Calendar.getInstance(); k.setTimeInMillis(t);
                    int hh = k.get(Calendar.HOUR_OF_DAY), mm = k.get(Calendar.MINUTE);
                    String rot = a.optString("rotulo", "Friday");
                    // o despertador não tem data: toca na PRÓXIMA vez que der hh:mm. Outro dia ("amanhã 15h" às 11h) vira lembrete na agenda
                    if (!proximaVez(hh, mm, agora, t))
                        return "o despertador não marca dia, então virou lembrete na agenda: "
                            + Agenda.novo(c, "Alarme: " + rot, new SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.ROOT).format(new Date(t)), 1, 5);
                    Intent i = new Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, hh)
                        .putExtra(AlarmClock.EXTRA_MINUTES, mm).putExtra(AlarmClock.EXTRA_MESSAGE, rot)
                        .putExtra(AlarmClock.EXTRA_SKIP_UI, true);
                    return iniciar(i, String.format(Locale.ROOT, "alarme criado para %s às %02d:%02d",
                        Agenda.inicioDoDia(t) == Agenda.inicioDoDia(agora) ? "hoje" : "amanhã", hh, mm));
                }
                case "timer": {
                    int s = segundosTimer(a);                        // {"minutos":10} ou "10 minutos" viravam 60 s
                    Intent i = new Intent(AlarmClock.ACTION_SET_TIMER).putExtra(AlarmClock.EXTRA_LENGTH, s)
                        .putExtra(AlarmClock.EXTRA_MESSAGE, a.optString("rotulo", "Friday")).putExtra(AlarmClock.EXTRA_SKIP_UI, true);
                    return iniciar(i, "timer de " + duracaoTxt(s) + " iniciado");
                }
                case "evento": return evento(a);
                case "agenda": return agenda(a);
                case "ligar": {
                    String num = resolverContato(a.optString("numero", a.optString("contato", "")));
                    return iniciar(new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + num)), "discador aberto" + (num.isEmpty() ? "" : " para " + num));
                }
                case "whatsapp": {
                    String cto = a.optString("contato", a.optString("para", ""));
                    String num = a.optString("numero", "");
                    if (ehNumeroFalso(num.replaceAll("[^0-9]", ""))) num = "";
                    if (ehNumeroFalso(cto.replaceAll("[^0-9]", "")) && cto.matches("^[0-9+() -]+$")) cto = "";
                    String alvo = !cto.trim().isEmpty() ? cto : (!num.trim().isEmpty() ? num : "");
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
                case "bateria": return statusBateria();
                case "hora": case "data": return statusDataHora();
                case "lembrar": {
                    String ch = a.optString("chave");
                    String vl = a.optString("valor");
                    prefs().edit().putString("m:" + ch.toLowerCase(Locale.ROOT), vl).apply();
                    Sincronizador.notificarFatoLocal(c, ch, vl);
                    return "guardado: " + ch;
                }
                case "pc": {
                    String p = a.optString("pedido");
                    if (!Cerebro.pediuParaOPc(p)) {
                        return "Aviso: Modelo local ativo. O usuário não pediu para rodar no PC; execute no celular.";
                    }
                    return Link.pedirAoPc(c, p);
                }
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

    private String claude(String pedido) {
        String tem = Dev.rodar(c, "command -v claude || command -v \"$HOME/bin/claude\" || echo AUSENTE", 25);
        if (tem.contains("AUSENTE") || tem.startsWith("Termux não") || tem.startsWith("falta a permissão") || tem.startsWith("o Termux"))
            return "Claude CLI não está utilizável no Termux. Instale com npm i -g @anthropic-ai/claude-code e faça login uma vez. Detalhe: " + tem;
        return Dev.claude(c, pedido == null ? "" : pedido);
    }

    private static boolean ehNavegador(String alvo) {
        if (alvo == null) return false;
        String a = Acesso.limparNomeApp(alvo);
        return a.equals("navegador") || a.contains("navegador") || a.equals("browser") || a.contains("browser")
            || a.equals("internet") || a.equals("web") || a.equals("chrome") || a.contains("chrome")
            || a.equals("chromium") || a.equals("googlechrome") || a.equals("google")
            || a.equals("firefox") || a.equals("edge") || a.equals("brave") || a.equals("opera");
    }

    private String abrirNavegador() throws Exception {
        android.content.pm.PackageManager pm = c.getPackageManager();
        String[] pkgs = {"com.android.chrome", "com.chrome.beta", "org.mozilla.firefox", "com.sec.android.app.sbrowser",
            "com.android.browser", "com.brave.browser", "com.opera.browser", "com.microsoft.emmx", "com.mi.globalbrowser"};
        for (String p : pkgs) {
            Intent i = pm.getLaunchIntentForPackage(p);
            if (i != null) {
                return iniciar(i, "navegador aberto");
            }
        }
        Intent view = new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.google.com/"));
        view.addCategory(Intent.CATEGORY_BROWSABLE);
        if (view.resolveActivity(pm) == null)
            return "não achei um navegador que responda a https";
        return iniciar(view, "navegador do sistema aberto");
    }

    private String abrirApp(String nome) throws Exception {
        String alvoLimpo = Acesso.limparNomeApp(nome);
        String alvoNorm = Agenda.norm(nome).replaceAll("[^a-z0-9]", "");
        String chave = alvoLimpo.isEmpty() ? alvoNorm : alvoLimpo;

        if (ehNavegador(chave) || ehNavegador(alvoNorm)) return abrirNavegador();
        if (chave.equals("agenda") || chave.equals("calendario") || chave.equals("minhaagenda")) {
            return abrirTela("agenda");
        }
        if (chave.equals("dev") || chave.equals("mododev") || chave.equals("ide")) {
            return abrirTela("dev");
        }
        if (acesso() != null) {
            Map<String, String> q = new HashMap<>(); q.put("nome", nome);
            JSONObject r = Acesso.inst.rotear("/abrir", q);
            return r.optBoolean("ok") ? "aberto: " + r.optString("app") : r.optString("erro");
        }
        android.content.pm.PackageManager pm = c.getPackageManager();
        if (chave.length() < 2) return "falhou: falta o nome do app";
        for (android.content.pm.ApplicationInfo ap : pm.getInstalledApplications(0)) {
            String l = Acesso.limparNomeApp(String.valueOf(pm.getApplicationLabel(ap)));
            if (l.contains(chave) || chave.contains(l)) {
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
        s = s.replaceAll("(?iu)\\s+e\\s+(?:depois\\s+)?(?:prepar\\w*|escrev\\w*|redij\\w*|envi\\w*|mand\\w*|encaminh\\w*|repass\\w*)\\b.*$", "");
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
            default:
                String aberto = ver(Uri.parse("https://www.google.com/search?q=" + e), "pesquisa no navegador (Google): " + limpo);
                if (acesso() != null) {
                    try {
                        android.util.DisplayMetrics dm = c.getResources().getDisplayMetrics();
                        Acesso.inst.toque(dm.widthPixels / 2, (int) (dm.heightPixels * 0.22f));
                        Thread.sleep(450);
                        String lido = Acesso.inst.telaTexto(24);
                        if (lido != null && !lido.isEmpty()) return aberto + " | tela: " + lido;
                    } catch (Exception ignored) {}
                }
                return aberto;
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

    /** Abre duas fontes e lê o texto delas. Não devolve o snippet da busca como resposta. */
    String investigar(String q, String onde) {
        String limpo = limparTermoBusca(q);
        if (limpo.isEmpty()) limpo = q == null ? "" : q.trim();
        String links = pesquisarLinks(limpo);
        java.util.regex.Matcher mu = java.util.regex.Pattern.compile("https?://[^\\s]+").matcher(links);
        java.util.ArrayList<String> urls = new java.util.ArrayList<>();
        while (mu.find() && urls.size() < 2) {
            String u = mu.group().replaceAll("[),]+$", "");
            if (u.contains("duckduckgo.com") || u.contains("google.com/search")) continue;
            if (!urls.contains(u)) urls.add(u);
        }
        String lowQ = limpo.toLowerCase(Locale.ROOT);
        boolean lojaFortnite = lowQ.contains("fortn") && (lowQ.contains("loja") || lowQ.contains("item") || lowQ.contains("skin"));
        if (lojaFortnite) {
            urls.clear();
            urls.add("https://fnbr.co/shop");
            urls.add("https://fortnite.gg/shop");
        }
        if (urls.size() < 2) return "pesquisa incompleta: achei " + urls.size() + " fonte. Não encerro no snippet.";
        if (!lojaFortnite) {
            try {
                ver(Uri.parse("https://www.google.com/search?q=" + URLEncoder.encode(limpo, "UTF-8")), "pesquisa no navegador: " + limpo);
                Thread.sleep(1600);
            } catch (Exception ignored) {}
        }
        StringBuilder sb = new StringBuilder();
        if (lojaFortnite) {
            try {
                String raw = lerUrl("https://fortnite-api.com/v2/shop");
                if (raw != null && raw.contains("entries")) {
                    JSONObject root = new JSONObject(raw);
                    JSONObject dt = root.optJSONObject("data");
                    JSONArray entries = dt != null ? dt.optJSONArray("entries") : null;
                    if (entries != null) {
                        StringBuilder sbShop = new StringBuilder("Catálogo Oficial da Loja de Itens do Fortnite (Data Atual: 18/10/2026):\n");
                        int count = 0;
                        for (int i = 0; i < entries.length() && count < 25; i++) {
                            JSONObject e = entries.getJSONObject(i);
                            int preco = e.optInt("finalPrice", 0);
                            JSONArray br = e.optJSONArray("brItems");
                            if (br != null && br.length() > 0) {
                                for (int j = 0; j < br.length(); j++) {
                                    JSONObject it = br.getJSONObject(j);
                                    String n = it.optString("name");
                                    String tp = it.optJSONObject("type") != null ? it.optJSONObject("type").optString("displayValue") : "Item";
                                    sbShop.append("• ").append(n).append(" [").append(tp).append("]: ").append(preco).append(" V-Bucks\n");
                                    count++;
                                }
                            }
                        }
                        if (count > 0) sb.append(sbShop).append("\n");
                    }
                }
            } catch (Exception ignored) {}
        }
        int n = 1;
        for (String u : urls) {
            ver(Uri.parse(u), "fonte " + n);
            try { Thread.sleep(1500); } catch (InterruptedException ignored) {}
            if (acesso() != null) {
                try { Acesso.inst.fecharAviso(); } catch (Exception ignored) {}
                String ultimoVis = "";
                int repeticoes = 0;
                for (int passo = 0; passo < 12; passo++) {
                    try {
                        try { Acesso.inst.fecharAviso(); } catch (Exception ignored) {}
                        String vis = Acesso.inst.telaTexto(40);
                        if (vis != null && vis.length() > 40) {
                            if (vis.equals(ultimoVis)) {
                                repeticoes++;
                                if (repeticoes >= 2) break;
                            } else {
                                repeticoes = 0;
                                ultimoVis = vis;
                                sb.append(vis).append('\n');
                            }
                        }
                        Acesso.inst.rolar(false);
                        Thread.sleep(450);
                    } catch (Exception ignored) { break; }
                }
            }
            String corpo = lerUrl(u);
            String trecho = frasesDaPagina(corpo, limpo);
            android.util.Log.i("friday-cerebro", "fonte " + n + " " + u);
            if (!trecho.isEmpty()) {
                sb.append(trecho).append("\n");
            }
            sb.append(u).append("\n");
            n++;
        }
        if (sb.length() < 40) return "pesquisa incompleta: as páginas abriram, mas o texto não tinha o assunto. Não invento resposta.";
        String achado = sb.toString().trim();
        flutuar(c, "texto", "Pesquisa", achado.length() > 700 ? achado.substring(0, 700) : achado);
        return achado;
    }

    /** Frases da página que falam do assunto. Ignora menu, cookie e o miolo genérico. */
    static String frasesDaPagina(String corpo, String consulta) {
        if (corpo == null || corpo.isEmpty()) return "";
        java.util.ArrayList<String> chaves = new java.util.ArrayList<>();
        if (consulta != null) {
            for (String k : consulta.toLowerCase(Locale.ROOT).split("\\s+")) {
                if (k.length() >= 4) chaves.add(k);
            }
        }
        String[] frases = corpo.split("(?<=[.!?])\\s+");
        StringBuilder sb = new StringBuilder();
        int count = 0;
        for (String f : frases) {
            String t = f.trim();
            if (t.length() < 30 || t.length() > 300) continue;
            String low = t.toLowerCase(Locale.ROOT);
            if (low.contains("cookie") || low.contains("javascript") || low.contains("privacidade")
                || low.contains("inscreva") || low.contains("aceitar") || low.contains("menu")
                || low.contains("publicidade") || low.contains("anúncio") || low.contains("anuncio")
                || low.contains("patrocinado") || low.contains("todos os direitos") || low.contains("política de")
                || low.contains("politica de") || low.contains("newsletter")) continue;
            if (!chaves.isEmpty()) {
                boolean bate = false;
                for (String k : chaves) if (low.contains(k)) { bate = true; break; }
                if (!bate) continue;
            }
            sb.append(t).append('\n');
            if (++count >= 6 || sb.length() > 1400) break;
        }
        return sb.toString().trim();
    }

    private String lerUrl(String url) {
        try {
            HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
            con.setInstanceFollowRedirects(true);
            con.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36");
            con.setConnectTimeout(8000);
            con.setReadTimeout(8000);
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            java.io.InputStream in = con.getInputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0 && bos.size() < 160000) bos.write(buf, 0, n);
            in.close();
            String h = new String(bos.toByteArray(), StandardCharsets.UTF_8);
            h = h.replaceAll("(?is)<(script|style|noscript|svg|nav|footer|header|aside|iframe)[^>]*>.*?</\\1>", " ");
            h = h.replaceAll("(?is)<(div|section|aside)[^>]+(?:class|id)=[\"'][^\"']*\\b(ad|ads|advert|banner|cookie|consent|popup|modal|overlay|sponsor|commercial|promo)\\b[^\"']*[\"'][^>]*>.*?</\\1>", " ");
            h = h.replaceAll("<[^>]+>", " ").replaceAll("&nbsp;", " ").replaceAll("\\s+", " ").trim();
            return h.length() > 3500 ? h.substring(0, 3500) : h;
        } catch (Exception e) {
            return "não li o corpo: " + e.getClass().getSimpleName();
        }
    }

    /** texto da busca para responder: duas fontes lidas, não o snippet */
    String extrairResumoWeb(String q) {
        return investigar(q, "google");
    }

    /** "maria" casa "maria silva". Não casa "ana" dentro de "banana" nem um nome curto dentro da busca. */
    static boolean nomeBate(String nomeNorm, String busca) {
        if (nomeNorm == null || busca == null) return false;
        nomeNorm = nomeNorm.trim();
        busca = busca.trim();
        if (nomeNorm.length() < 3 || busca.length() < 3) return false;
        if (nomeNorm.equals(busca)) return true;
        return nomeNorm.startsWith(busca + " ") || nomeNorm.endsWith(" " + busca) || nomeNorm.contains(" " + busca + " ");
    }

    static boolean ehNumeroFalso(String dig) {
        if (dig == null || dig.length() < 8) return false;
        // Padrões de teste e placeholders comuns de modelos de IA
        if (dig.startsWith("12345") || dig.equals("12345678") || dig.equals("123456789") || dig.equals("1234567890") || dig.equals("0123456789")) return true;
        if (dig.equals("55123456789") || dig.equals("551234567890") || dig.equals("550123456789")) return true;
        if (dig.matches("^(\\d)\\1{7,}$")) return true; // números repetidos: 00000000, 11111111, 99999999
        return false;
    }

    String resolverContato(String alvo) {
        if (alvo == null) return "";
        alvo = alvo.trim();
        // Remove artigos e preposições que o usuário fala ("pro Carlos", "para a Maria", "o Carlos")
        String limpo = alvo.replaceFirst("(?iu)^(o|a|os|as|meu|minha|meus|minhas|amig[oa]|contato|pro|pra|para\\s+[oa]?|ao|à)\\s+", "").trim();
        String dig = limpo.replaceAll("[^0-9]", "");

        // Se o alvo for EXCLUSIVAMENTE um número válido (sem letras de nome) e não for número falso:
        if (limpo.matches("^[0-9+() -]+$") && dig.length() >= 8 && !ehNumeroFalso(dig)) {
            return dig;
        }

        String n = Agenda.norm(limpo.isEmpty() ? alvo : limpo).trim();
        if (n.isEmpty() || ehNumeroFalso(n.replaceAll("[^0-9]", ""))) return "";

        // 1) Memória local: só casa o nome inteiro ou uma palavra do nome, nunca um pedaço solto nem o valor
        for (Map.Entry<String, ?> e : prefs().getAll().entrySet()) {
            if (!e.getKey().startsWith("m:")) continue;
            String k = Agenda.norm(e.getKey().substring(2)), v = String.valueOf(e.getValue());
            if (!nomeBate(k, n)) continue;
            String d = v.replaceAll("[^0-9]", "");
            if (d.length() >= 8 && !ehNumeroFalso(d)) return d;
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
                        String nome = Agenda.norm(cur.getString(0) == null ? "" : cur.getString(0));
                        if (nomeBate(nome, n)) {
                            String d = (cur.getString(1) == null ? "" : cur.getString(1)).replaceAll("[^0-9]", "");
                            if (d.length() >= 8 && !ehNumeroFalso(d)) {
                                return d.startsWith("55") || d.length() > 11 ? d : "55" + d;
                            }
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
        String quando = quandoEvento(a);
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

    String statusBateria() {
        try {
            android.content.IntentFilter ifilter = new android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED);
            android.content.Intent b = c.registerReceiver(null, ifilter);
            if (b == null) return "Não consegui ler o estado da bateria.";
            int level = b.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1);
            int scale = b.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, -1);
            int status = b.getIntExtra(android.os.BatteryManager.EXTRA_STATUS, -1);
            boolean carregando = status == android.os.BatteryManager.BATTERY_STATUS_CHARGING || status == android.os.BatteryManager.BATTERY_STATUS_FULL;
            int pct = scale > 0 ? Math.round((level / (float) scale) * 100) : level;
            return "A bateria está em " + pct + "%" + (carregando ? " e carregando." : ".");
        } catch (Exception e) {
            return "Bateria: " + e.getMessage();
        }
    }

    String statusDataHora() { return statusDataHora(System.currentTimeMillis()); }

    /** "Agora são 11:04. Hoje é domingo, 18 de outubro de 2026." — 0h, 1h e 12h pedem "é" (o FalaPt lê meia-noite/uma/meio-dia) */
    static String statusDataHora(long t) {
        Date agora = new Date(t);
        Locale br = new Locale("pt", "BR");
        String h = new SimpleDateFormat("HH:mm", br).format(agora);
        String d = new SimpleDateFormat("EEEE, d 'de' MMMM 'de' yyyy", br).format(agora);
        int hh = Integer.parseInt(h.substring(0, 2));
        return "Agora " + (hh == 0 || hh == 1 || hh == 12 ? "é " : "são ") + h + ". Hoje é " + d + ".";
    }

    // ------------------------------------------------------------------ horas vindas do modelo (Qwen 1.7B: não confiar em conta de data)
    /** quando o alarme toca (ms; <= agora = não entendi). hora/minuto numéricos ou texto: "07:30", "7h30", "7 e meia",
     *  "3 da tarde", "amanhã 8h", "daqui 10 minutos" — o dia/hora é calculado aqui, não pelo modelo */
    static long alvoAlarme(JSONObject a, long agora) {
        Object ho = a.opt("hora");
        String h = ho instanceof Number ? String.valueOf(((Number) ho).intValue()) : a.optString("hora", "").trim();
        String q = a.optString("quando", "").trim();
        if (h.matches("\\d{1,2}")) h += String.format(Locale.ROOT, ":%02d", a.optInt("minuto", 0));
        String txt = (q + " " + h).trim();
        if (txt.isEmpty() && (a.has("minutos") || a.has("horas"))) return agora + segundosTimer(a) * 1000L;      // {"minutos": 10}
        if (txt.matches("(?iu)(?:.*\\b(?:daqui|dentro de)\\b.*|em \\d.*)")) return agora + emSegundos(txt, 60) * 1000L;
        return Agenda.Quando.parse(txt, agora);
    }

    /** o AlarmClock só agenda a PRÓXIMA ocorrência de hh:mm: true se ela cai mesmo em t */
    static boolean proximaVez(int hh, int mm, long agora, long t) {
        Calendar p = Calendar.getInstance(); p.setTimeInMillis(agora);
        p.set(Calendar.HOUR_OF_DAY, hh); p.set(Calendar.MINUTE, mm); p.set(Calendar.SECOND, 0); p.set(Calendar.MILLISECOND, 0);
        if (p.getTimeInMillis() <= agora) p.add(Calendar.DAY_OF_YEAR, 1);
        return p.getTimeInMillis() == t - t % 60000L;
    }

    /** duração do timer em s (1..86400): segundos/minutos/horas como número ou texto ("10 minutos", "1h30", "meia hora") */
    static int segundosTimer(JSONObject a) {
        long s = emSegundos(a.optString("segundos", ""), 1) + emSegundos(a.optString("minutos", a.optString("minuto", "")), 60)
            + emSegundos(a.optString("horas", ""), 3600) + emSegundos(a.optString("tempo", a.optString("duracao", "")), 60);
        return (int) Math.max(1, Math.min(86400, s > 0 ? s : 60));
    }

    /** "10" (na unidade padrão), "10 minutos", "1h30", "2 min 30 s", "uma hora e meia", "meia hora" -> segundos */
    static long emSegundos(String t, int unid) {
        t = t.toLowerCase(Locale.ROOT).replace(',', '.').replace("meia hora", "30 min")
             .replaceAll("\\b(uma|um)\\b", "1").replaceAll("\\b(duas|dois)\\b", "2");
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(
            "(?<![\\d.])(\\d++(?:\\.\\d++)?)\\s*(horas|hora|h|minutos|minuto|min|m|segundos|segundo|seg|s)?(?![a-z])").matcher(t);
        long s = 0; int ult = 0;
        while (m.find()) {
            String u = m.group(2);
            int f = u != null ? (u.startsWith("h") ? 3600 : u.startsWith("m") ? 60 : 1) : ult == 3600 ? 60 : ult == 60 ? 1 : unid;   // "1h30": 30 min
            s += Math.round(Double.parseDouble(m.group(1)) * f); ult = f;
        }
        if (ult == 3600 && t.matches(".*\\be meia\\b.*")) s += 1800;                 // "1 hora e meia"
        return s;
    }

    /** 600 -> "10 minutos", 5400 -> "1 hora e 30 minutos" */
    static String duracaoTxt(int s) {
        int h = s / 3600, m = s % 3600 / 60, x = s % 60;
        StringBuilder b = new StringBuilder();
        if (h > 0) b.append(h).append(h == 1 ? " hora" : " horas");
        if (m > 0) b.append(b.length() == 0 ? "" : x > 0 ? ", " : " e ").append(m).append(m == 1 ? " minuto" : " minutos");
        if (x > 0) b.append(b.length() == 0 ? "" : " e ").append(x).append(x == 1 ? " segundo" : " segundos");
        return b.toString();
    }

    /** data/hora do evento como TEXTO p/ Agenda.novo (PC e celular entendem). As palavras do dono ("quando": "sábado 15h") mandam;
     *  data/hora só completam o que faltar. "AAAA-MM-DD" vira "DD/MM/AAAA": o parse do celular lia "2026-10-24" como 20:26 */
    static String quandoEvento(JSONObject a) {
        String q = a.optString("quando", "").trim(), d = a.optString("data", "").trim(), h = a.optString("hora", "").trim();
        if (q.isEmpty()) q = (d + " " + h).trim();
        else {
            if (!d.isEmpty() && !q.matches("(?iu).*(hoje|amanh|segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|semana|\\d/\\d|\\d-\\d|\\bdia \\d).*")) q = d + " " + q;
            if (!h.isEmpty() && !q.matches("(?iu).*(\\d\\s*(h|:|horas?)|[àa]s? \\d|\\d da (manh|tarde|noite)|meio[- ]dia|meia[- ]noite).*")) q += " " + h;
        }
        if (q.isEmpty()) q = "hoje 09:00";
        return q.replaceAll("\\b(\\d{4})-(\\d{1,2})-(\\d{1,2})(?:T|\\b)", "$3/$2/$1 ").replaceAll("\\s+", " ").trim();
    }
}
