package dev.integra.friday;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** MODO DEV AUTÔNOMO (liberado pelo dono, opção 3): a Friday opera o Claude Code (Termux) sozinha até terminar — escreve o
 *  prompt, acompanha ao vivo (stream-json repassado pelo ide_ponte.py para a rota /ide da ponte), revisa o resultado e manda
 *  continuar (revisar/testar/corrigir, mesma conversa com -c) até ele responder FINALIZADO. Tudo aparece na IDE flutuante.
 *  Travas: no máximo MAX_RODADAS e botão PARAR (mata o claude no Termux). */
final class Ide {
    interface Tela { void linhas(List<String[]> novas); void estado(String estado, int rodada); }

    static final int MAX_RODADAS = 60;                                  // 19/10: igual ao PC (para em FINALIZADO, não no teto)
    private static final Object trava = new Object();
    private static final List<String[]> linhas = new ArrayList<>();     // [tipo, texto]
    private static volatile Tela tela;
    private static volatile String estado = "parada", objetivo = "", pasta = "~/dev", ultimoResultado = "";
    private static volatile int rodada;
    private static volatile boolean parar, pausada;
    private static volatile Thread laco;
    private static volatile Context ctx;

    private Ide() {}

    static void setTela(Tela t) { tela = t; }
    static String estado() { return estado; }
    static String objetivo() { return objetivo; }
    static int rodada() { return rodada; }
    static boolean pausada() { return pausada; }
    static boolean ativa() { return laco != null && laco.isAlive(); }
    static List<String[]> todas() { synchronized (trava) { return new ArrayList<>(linhas); } }

    static void add(String tipo, String texto) {
        if (texto == null || texto.trim().isEmpty()) return;
        String[] l = {tipo, texto.length() > 1200 ? texto.substring(0, 1200) + " …" : texto};
        synchronized (trava) { linhas.add(l); while (linhas.size() > 600) linhas.remove(0); }
        Tela t = tela;
        if (t != null) { List<String[]> n = new ArrayList<>(); n.add(l); t.linhas(n); }
    }

    private static void mudar(String e) {
        estado = e;
        Tela t = tela;
        if (t != null) t.estado(e, rodada);
    }

    // ------------------------------------------------------------------ eventos do Claude (stream-json, linha a linha)
    static void evento(String linha) {
        try {
            JSONObject j = new JSONObject(linha);
            String tipo = j.optString("type");
            if (tipo.equals("assistant")) {
                JSONArray cont = j.optJSONObject("message") == null ? null : j.getJSONObject("message").optJSONArray("content");
                for (int i = 0; cont != null && i < cont.length(); i++) {
                    JSONObject b = cont.getJSONObject(i);
                    if (b.optString("type").equals("text")) add("claude", b.optString("text").trim());
                    else if (b.optString("type").equals("tool_use")) ferramenta(b.optString("name"), b.optJSONObject("input"));
                }
            } else if (tipo.equals("user")) {
                JSONArray cont = j.optJSONObject("message") == null ? null : j.getJSONObject("message").optJSONArray("content");
                for (int i = 0; cont != null && i < cont.length(); i++) {
                    JSONObject b = cont.optJSONObject(i);
                    if (b == null || !b.optString("type").equals("tool_result")) continue;
                    Object c = b.opt("content");
                    String r = c instanceof JSONArray ? (((JSONArray) c).optJSONObject(0) == null ? "" : ((JSONArray) c).optJSONObject(0).optString("text"))
                        : String.valueOf(c);
                    String[] ls = r.trim().split("\n");
                    add(b.optBoolean("is_error") ? "erro" : "saida", ls.length > 4 ? ls[0] + "\n" + ls[1] + "\n… (" + ls.length + " linhas)" : r.trim());
                }
            } else if (tipo.equals("result")) {
                ultimoResultado = j.optString("result");
                add("fim", String.format(java.util.Locale.ROOT, "rodada %d concluída · %.0f s · US$ %.3f", rodada,
                    j.optDouble("duration_ms", 0) / 1000, j.optDouble("total_cost_usd", 0)));
            } else if (tipo.equals("system") && j.optString("subtype").equals("init")) {
                add("info", "Claude " + j.optString("model") + " em " + j.optString("cwd").replace("/data/data/com.termux/files/home", "~"));
            }
        } catch (Exception e) {
            if (!linha.trim().isEmpty()) add("saida", linha.trim());
        }
    }

    private static void ferramenta(String nome, JSONObject in) {
        if (in == null) in = new JSONObject();
        String arq = in.optString("file_path", in.optString("path", "")).replace("/data/data/com.termux/files/home", "~");
        switch (nome) {
            case "Edit": case "MultiEdit": {
                add("arquivo", "[EDIT] " + arq);
                for (String l : corta(in.optString("old_string"), 6)) add("menos", "- " + l);
                for (String l : corta(in.optString("new_string"), 8)) add("mais", "+ " + l);
                break;
            }
            case "Write": {
                String c = in.optString("content");
                add("arquivo", "[NEW] " + arq + " (" + c.split("\n").length + " linhas)");
                for (String l : corta(c, 6)) add("mais", "+ " + l);
                break;
            }
            case "Bash": add("bash", "$ " + in.optString("command")); break;
            case "Read": add("ler", "◎ ler " + arq); break;
            case "Glob": case "Grep": add("ler", "◎ " + nome.toLowerCase(java.util.Locale.ROOT) + " " + in.optString("pattern")); break;
            case "TodoWrite": {
                JSONArray t = in.optJSONArray("todos");
                for (int i = 0; t != null && i < t.length(); i++) {
                    JSONObject o = t.optJSONObject(i);
                    if (o == null) continue;
                    String st = o.optString("status");
                    add("todo", (st.equals("completed") ? "[OK] " : st.equals("in_progress") ? "[RUN] " : "[ ] ") + o.optString("content"));
                }
                break;
            }
            default: add("ferr", "[TOOL] " + nome + (arq.isEmpty() ? "" : " " + arq));
        }
    }

    private static String[] corta(String s, int max) {
        String[] l = (s == null ? "" : s).split("\n");
        if (l.length <= max) return l;
        String[] r = new String[max + 1];
        System.arraycopy(l, 0, r, 0, max);
        r[max] = "… (+" + (l.length - max) + " linhas)";
        return r;
    }

    // ------------------------------------------------------------------ ciclo autônomo
    static synchronized String iniciar(Context c, String obj, String dir) {
        if (ativa()) return "já estou trabalhando em: " + objetivo;
        ctx = c.getApplicationContext();
        objetivo = obj == null ? "" : obj.trim();
        pasta = dir == null || dir.trim().isEmpty() ? "~/dev" : dir.trim();
        parar = false; pausada = false; rodada = 0;
        synchronized (trava) { linhas.clear(); }
        if (Acesso.inst != null) Flutuante.ide(Acesso.inst, true);
        final boolean temTermux = Dev.termuxInstalado(c) && Dev.permitido(c);
        final boolean pediuPc = Cerebro.pediuParaOPc(obj);
        laco = new Thread(() -> {
            if (pediuPc && Link.pcOnline(ctx)) executarNoPc(ctx);
            else if (temTermux) executar(ctx);
            else executarLocal(ctx);
        }, "friday-ide");
        laco.start();
        String modo = (pediuPc && Link.pcOnline(c)) ? "IDE do PC" : temTermux ? "Termux Claude" : "Cérebro Local";
        return "comecei a trabalhar no MODO DEV (" + modo + "): " + objetivo;
    }

    static void parar() {
        parar = true; pausada = false;
        mudar("parando");
        Context c = ctx;
        if (c != null) {
            new Thread(() -> {
                if (Dev.termuxInstalado(c) && Dev.permitido(c)) Dev.rodar(c, "pkill -f 'bin/claude' ; true", 15);
                if (Link.pcOnline(c)) {
                    try {
                        java.net.HttpURLConnection h = (java.net.HttpURLConnection) new java.net.URL("http://" + Link.host(c) + "/api/ide").openConnection();
                        h.setConnectTimeout(2000); h.setReadTimeout(3000); h.setRequestMethod("POST"); h.setDoOutput(true);
                        h.setRequestProperty("X-Token", Link.token(c)); h.setRequestProperty("Content-Type", "application/json");
                        try (java.io.OutputStream o = h.getOutputStream()) { o.write("{\"op\":\"parar\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8)); }
                        h.getResponseCode(); h.disconnect();
                    } catch (Exception ignored) {}
                }
            }).start();
        }
    }

    /** 19/10: "continua"/"sim"/"prossiga" do dono retoma a última tarefa na MESMA conversa do Claude (-c) — antes virava pedido novo */
    static String continuar(Context c) {
        if (ativa()) { pausada = false; mudar("trabalhando"); return "já estou trabalhando nisso: " + objetivo; }
        if (objetivo == null || objetivo.isEmpty()) return null;
        ctx = c.getApplicationContext();
        parar = false; pausada = false; retomar = true;
        if (rodada < 1) rodada = 1;                                     // garante o -c (continua a conversa)
        laco = new Thread(() -> executar(ctx), "friday-ide");
        laco.start();
        return "continuando no MODO DEV: " + objetivo;
    }

    private static volatile boolean retomar;

    static void pausar(boolean p) { pausada = p; mudar(p ? "pausada (termina a rodada atual)" : "trabalhando"); }

    static String jsonEstado() {
        try {
            JSONArray arr = new JSONArray();
            for (String[] l : todas()) arr.put(new JSONArray().put(l[0]).put(l[1]));
            return new JSONObject()
                .put("estado", estado)
                .put("objetivo", objetivo)
                .put("pasta", pasta)
                .put("rodada", rodada)
                .put("max_rodadas", MAX_RODADAS)
                .put("ativa", ativa())
                .put("pausada", pausada)
                .put("linhas", arr)
                .toString();
        } catch (Exception e) { return "{\"estado\":\"erro\"}"; }
    }

    private static String esc(String s) { return s.replace("'", "'\"'\"'"); }

    private static void executarNoPc(Context c) {
        try {
            rodada = 1;
            mudar("conectando à IDE do PC");
            add("info", "Delegando tarefa ao MODO DEV do PC (" + Link.host(c) + ")");
            add("prompt", objetivo);
            java.net.HttpURLConnection h = (java.net.HttpURLConnection) new java.net.URL("http://" + Link.host(c) + "/api/ide").openConnection();
            h.setConnectTimeout(4000); h.setReadTimeout(180000);
            h.setRequestMethod("POST"); h.setDoOutput(true);
            h.setRequestProperty("X-Token", Link.token(c));
            h.setRequestProperty("Content-Type", "application/json");
            byte[] body = new JSONObject().put("op", "enviar").put("texto", objetivo).put("autonomo", true).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
            try (java.io.OutputStream o = h.getOutputStream()) { o.write(body); }
            int cod = h.getResponseCode();
            java.io.InputStream in = cod < 400 ? h.getInputStream() : h.getErrorStream();
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096]; int n;
            while (in != null && (n = in.read(buf)) > 0) bo.write(buf, 0, n);
            h.disconnect();
            JSONObject r = new JSONObject(bo.toString("UTF-8"));
            JSONArray resps = r.optJSONArray("respostas");
            if (resps != null) {
                for (int i = 0; i < resps.length(); i++) {
                    JSONObject ev = resps.optJSONObject(i);
                    if (ev == null) continue;
                    String op = ev.optString("op");
                    if ("texto".equals(op)) add("claude", ev.optString("texto"));
                    else if ("ferramenta".equals(op)) add("ferr", "[TOOL] " + ev.optString("nome") + " " + ev.optString("detalhe"));
                    else if ("diff".equals(op)) add("arquivo", "[DIFF] " + ev.optString("caminho"));
                    else if ("fim".equals(op)) add("ok", "■ Concluído no PC (" + ev.optInt("ms") / 1000 + "s)");
                    else if ("erro".equals(op)) add("erro", ev.optString("msg"));
                }
            }
            mudar("finalizada");
            Voz.get(c).falar("Terminei a tarefa no Modo Dev do PC: " + objetivo);
        } catch (Exception e) {
            add("erro", "IDE do PC indisponível (" + e.getMessage() + ") — gerando localmente…");
            executarLocal(c);
        }
    }

    private static void executarLocal(Context c) {
        try {
            rodada = 1;
            mudar("gerando código local");
            add("info", "Motor local GGUF (" + Cerebro.get(c).modelo() + ") · salvando em Documentos/Friday/");
            add("prompt", objetivo);
            if (!Cerebro.get(c).preparar()) {
                add("erro", "Modelo local não encontrado para geração.");
                mudar("erro");
                return;
            }
            String p = "<|im_start|>system\nVocê é o motor MODO DEV da F.R.I.D.A.Y. Gere o código ou solução completa, limpa, comentada e pronta para uso para o pedido do usuário.\n<|im_end|>\n"
                + "<|im_start|>user\n" + objetivo + "<|im_end|>\n<|im_start|>assistant\n"
                + (Cerebro.get(c).modelo().startsWith("qwen2") ? "" : "<think>\n\n</think>\n\n");
            String codigo = Llm.gerar(p, 1200, 0.25f, "", null).trim();
            if (parar) { mudar("parada"); return; }
            add("claude", codigo);
            String ext = objetivo.toLowerCase(java.util.Locale.ROOT).contains("html") || objetivo.toLowerCase(java.util.Locale.ROOT).contains("site") ? "html"
                : objetivo.toLowerCase(java.util.Locale.ROOT).contains("python") || objetivo.toLowerCase(java.util.Locale.ROOT).contains("script") ? "py" : "md";
            String arq = Docs.criar(c, "Dev_" + objetivo.replaceAll("[^\\p{L}\\d]+", "_").substring(0, Math.min(24, objetivo.length())), ext, codigo);
            add("arquivo", "[NEW] " + arq);
            add("ok", "■ FINALIZADO localmente · salvo em " + arq);
            mudar("finalizada");
            Voz.get(c).falar("Pronto, gerei no Modo Dev local e salvei em " + arq + ".");
        } catch (Exception e) {
            add("erro", "falhou: " + e.getMessage());
            mudar("erro");
        }
    }

    private static void executar(Context c) {
        try {
            mudar("escrevendo o prompt");
            String prompt = retomar ? "Continue a tarefa de onde parou (" + objetivo + "): revise, teste, corrija e complete. Não pergunte nada. "
                + "Quando estiver tudo implementado E testado, responda com uma linha contendo só FINALIZADO e depois um resumo curto." : promptInicial(c);
            retomar = false;
            add("prompt", prompt);
            String tok = Link.token(c);
            while (rodada < MAX_RODADAS && !parar) {
                while (pausada && !parar) Thread.sleep(500);
                if (parar) break;
                rodada++;
                mudar("Claude trabalhando");
                ultimoResultado = "";
                String cmd = "export SHELL=" + Dev.BASH + " DISABLE_AUTOUPDATER=1; mkdir -p " + pasta + " && cd " + pasta + " && ~/bin/claude "
                    + (rodada > 1 ? "-c " : "") + "-p --verbose --output-format stream-json --dangerously-skip-permissions '" + esc(prompt)
                    + "' < /dev/null 2>&1 | python ~/dev/.friday/ide_ponte.py '" + esc(tok) + "'";
                String saida = Dev.rodar(c, cmd, 1800);
                if (saida.startsWith("o Termux") || saida.startsWith("falta")) { add("erro", saida); break; }
                if (parar) break;
                mudar("revisando");
                String r = ultimoResultado == null ? "" : ultimoResultado;
                if (r.contains("FINALIZADO")) {
                    add("ok", "■ FINALIZADO na rodada " + rodada);
                    String resumo = r.substring(r.indexOf("FINALIZADO") + 10).trim();
                    if (!resumo.isEmpty()) add("claude", resumo);
                    mudar("finalizada");
                    Voz.get(c).falar("Terminei: " + objetivo + ". " + (resumo.length() > 220 ? resumo.substring(0, 220) + "…" : resumo));
                    return;
                }
                if (r.isEmpty()) add("erro", "a rodada terminou sem resultado do Claude (veja as linhas acima)");
                prompt = "Continue sozinho. Revise o que foi feito até agora contra o objetivo (" + objetivo + "), rode os testes ou execute o "
                    + "programa para comprovar que funciona, corrija tudo o que falhar e complete o que faltar. Não pergunte nada: decida com bom senso. "
                    + "Quando estiver tudo implementado E testado, responda com uma linha contendo só FINALIZADO e depois um resumo curto do que fez e como testar.";
                add("prompt", "» rodada " + (rodada + 1) + ": a Friday revisou e pediu para revisar, testar, corrigir e completar");
            }
            mudar(parar ? "parada" : "limite de rodadas");
            if (!parar) Voz.get(c).falar("Parei no limite de " + MAX_RODADAS + " rodadas do MODO DEV; veja a IDE.");
        } catch (Exception e) {
            add("erro", "falhou: " + e.getMessage());
            mudar("erro");
        }
    }

    /** a Friday escreve o 1º prompt (critérios de pronto pelo cérebro local); se ele não estiver pronto, usa só o modelo fixo */
    private static String promptInicial(Context c) {
        String base = "Objetivo: " + objetivo + "\nPasta de trabalho: " + pasta + " (leia o CLAUDE.md de ~/dev para o contexto).\n"
            + "Trabalhe de forma AUTÔNOMA até o fim: entenda o código existente, planeje com uma lista de tarefas, implemente, rode/teste, "
            + "revise e corrija. Não pergunte nada: decida com bom senso. Quando estiver tudo implementado E testado, responda com uma "
            + "linha contendo só FINALIZADO e depois um resumo curto do que fez e como testar.";
        try {
            if (!Cerebro.get(c).preparar()) return base;
            String p = "<|im_start|>system\nVocê é a Friday. Escreva critérios de pronto objetivos e verificáveis para uma tarefa de programação. "
                + "Responda só com 3 a 6 itens começando com '- ', em português, sem introdução.<|im_end|>\n<|im_start|>user\nTarefa: " + objetivo
                + "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n";
            String crit = Llm.gerar(p, 220, 0.3f, "", null).trim();
            if (crit.contains("- ")) return base + "\nCritérios de pronto (escritos pela Friday):\n" + crit;
        } catch (Throwable ignored) {}
        return base;
    }
}
