package dev.integra.friday;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/** AUTO-APRENDIZADO da Friday do celular (sem mexer no código):
 *  1) VOZ: registra cada fala (score do dono, motor, texto); recalibra o limiar do "é o dono?" pelas falas confirmadas;
 *     "fui eu" guarda a amostra recusada no perfil; correções de palavras aprendidas ("não, eu disse X") valem nas próximas.
 *  2) PEDIDOS: o que deu certo vira RECEITA (pedido -> ferramentas usadas) e entra no prompt dos pedidos parecidos;
 *     o que o dono corrigiu ("não foi isso", "errado") vira FALHA a evitar — e, repetida, vira proposta de melhoria no
 *     código (o PC gera a proposta com o Claude; o dono aprova; o PC compila e instala o APK). */
final class Aprende {
    private Aprende() {}
    private static final Object trava = new Object();

    private static File arq(Context c, String n) { return new File(c.getFilesDir(), n); }

    private static String ler(File f) {
        try { return new String(java.nio.file.Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8); } catch (Exception e) { return ""; }
    }

    private static void gravar(File f, String s) {
        try { java.nio.file.Files.write(f.toPath(), s.getBytes(StandardCharsets.UTF_8)); } catch (Exception ignored) {}
    }

    private static void anexar(File f, JSONObject o, int maxLinhas) {
        synchronized (trava) {
            List<String> l = new ArrayList<>(Arrays.asList(ler(f).split("\n")));
            l.removeIf(String::isEmpty);
            l.add(o.toString());
            while (l.size() > maxLinhas) l.remove(0);
            gravar(f, String.join("\n", l) + "\n");
        }
    }

    private static List<JSONObject> linhas(File f) {
        List<JSONObject> r = new ArrayList<>();
        for (String s : ler(f).split("\n")) try { if (!s.isEmpty()) r.add(new JSONObject(s)); } catch (Exception ignored) {}
        return r;
    }

    static String norm(String s) { return Agenda.norm(s); }

    // =================================================================== 1) VOZ
    private static final Pattern LIXO = Pattern.compile("^(obrigad[oa]s?( por assistir)?|tchau|legendas?.*|inscreva.*|m[uú]sica|aplausos|risos|"
        + "hum+|ah+|eh+|uh+|ok|t[aá]|a volta|de volta|é|e|o|a|ai|ei|oi\\?)\\W*$", Pattern.CASE_INSENSITIVE);
    private static final Set<String> CMD_1 = new HashSet<>(Arrays.asList("pare", "para", "cancela", "cancelar", "sim", "nao", "não", "continua",
        "volta", "voltar", "ajuda", "obrigado", "valeu", "agenda", "lanterna", "repete"));

    /** transcrição que não deve virar pedido (ruído/alucinação do reconhecedor) */
    static boolean lixo(String t) {
        String s = t == null ? "" : t.trim();
        if (s.isEmpty() || LIXO.matcher(s).matches()) return true;
        String[] w = norm(s).split(" ");
        if (w.length == 1 && !CMD_1.contains(w[0]) && w[0].length() < 4) return true;
        if (w.length >= 4) {                                          // "a volta a volta a volta": repetição = alucinação
            Set<String> u = new HashSet<>(Arrays.asList(w));
            if (u.size() <= w.length / 3) return true;
        }
        return false;
    }

    /** correções fixas + aprendidas ("Sexta feira" -> "Sexta-Feira", "modo deve" -> "modo dev", o que o dono ensinou) */
    static String corrigir(Context c, String t) {
        if (t == null) return "";
        String r = t.replaceAll("(?i)\\b(sexta|cesta|sesta|texta)[ -]?feira\\b", "Sexta-Feira").replaceAll("(?i)\\bmodo (deve|devi|de vê|dévi)\\b", "modo dev")
            .replaceAll("(?i)\\bcl[oó]ud(e)?\\b", "Claude")
            .replaceAll("\\s*,\\s*\\.\\s*", ", ").replaceAll("\\s+([.,!?])", "$1");      // "Sexta-Feira, . Marca" (pausa vira pontuação solta)
        try {
            JSONObject m = new JSONObject(ler(arq(c, "correcoes.json")).isEmpty() ? "{}" : ler(arq(c, "correcoes.json")));
            for (Iterator<String> it = m.keys(); it.hasNext(); ) {
                String de = it.next();
                JSONObject o = m.optJSONObject(de);
                if (o == null || o.optInt("n") < 1) continue;
                r = Pattern.compile("(?i)(?<![\\p{L}\\d])" + Pattern.quote(de) + "(?![\\p{L}\\d])").matcher(r).replaceAll(java.util.regex.Matcher.quoteReplacement(o.optString("para")));
            }
        } catch (Exception ignored) {}
        return r;
    }

    /** "não, eu disse X": guarda o trecho que mudou (até 3 palavras) como correção para as próximas transcrições */
    static String aprenderCorrecao(Context c, String errado, String certo) {
        String[] a = errado.trim().split("\\s+"), b = certo.trim().split("\\s+");
        int i = 0, j = 0;
        while (i < a.length && i < b.length && norm(a[i]).equals(norm(b[i]))) i++;
        while (j < a.length - i && j < b.length - i && norm(a[a.length - 1 - j]).equals(norm(b[b.length - 1 - j]))) j++;
        String de = String.join(" ", Arrays.copyOfRange(a, i, a.length - j)).trim(), para = String.join(" ", Arrays.copyOfRange(b, i, b.length - j)).trim();
        if (de.isEmpty() || para.isEmpty() || de.split(" ").length > 3 || para.split(" ").length > 4 || norm(de).equals(norm(para))) return null;
        de = de.toLowerCase(Locale.ROOT).replaceAll("[.,!?]", "");
        para = para.replaceAll("[.,!?]$", "");
        synchronized (trava) {
            try {
                String s = ler(arq(c, "correcoes.json"));
                JSONObject m = new JSONObject(s.isEmpty() ? "{}" : s);
                JSONObject o = m.optJSONObject(de) == null ? new JSONObject().put("n", 0) : m.getJSONObject(de);
                o.put("para", para).put("n", o.optInt("n") + 1).put("t", System.currentTimeMillis() / 1000);
                m.put(de, o);
                gravar(arq(c, "correcoes.json"), m.toString(1));
            } catch (Exception ignored) {}
        }
        return de + " → " + para;
    }

    static void logVoz(Context c, float score, float limiar, boolean dono, float dur, String motor, String texto, boolean lixo) {
        try {
            anexar(arq(c, "voz_log.jsonl"), new JSONObject().put("t", System.currentTimeMillis() / 1000).put("sc", Math.round(score * 1000) / 1000.0)
                .put("lim", limiar).put("dono", dono).put("dur", Math.round(dur * 10) / 10.0).put("motor", motor).put("txt", texto == null ? "" : texto)
                .put("lixo", lixo), 400);
        } catch (Exception ignored) {}
    }

    /** marca a última fala do dono como confirmada (o pedido seguiu sem correção) ou errada */
    static void confirmarUltimaVoz(Context c, boolean certa) {
        synchronized (trava) {
            File f = arq(c, "voz_log.jsonl");
            List<JSONObject> l = linhas(f);
            for (int k = l.size() - 1; k >= 0; k--) {
                JSONObject o = l.get(k);
                if (o.optBoolean("dono") && !o.optBoolean("lixo") && !o.has("ok")) {
                    try { o.put("ok", certa); } catch (Exception ignored) {}
                    StringBuilder sb = new StringBuilder();
                    for (JSONObject x : l) sb.append(x.toString()).append('\n');
                    gravar(f, sb.toString());
                    break;
                }
            }
        }
        if (certa) calibrar(c);                                        // cada fala confirmada afina o limiar do "é o dono?"
    }

    /** "fui eu": a fala recusada era do dono -> entra no perfil e o limiar se ajusta */
    static String fuiEu(Context c, Ouvido ouvido, short[] pcm, float score) {
        if (pcm == null) return "não tenho a última fala guardada";
        boolean ok = ouvido.aprender(pcm, true);
        try {
            anexar(arq(c, "voz_log.jsonl"), new JSONObject().put("t", System.currentTimeMillis() / 1000).put("sc", score).put("dono", true)
                .put("ok", true).put("fui_eu", true).put("motor", "-").put("txt", ""), 400);
        } catch (Exception ignored) {}
        float lim = calibrar(c);
        return (ok ? "Guardei essa amostra da sua voz" : "Amostra fora do padrão ou muito curta, mas anotei") + String.format(Locale.ROOT, "; limiar agora %.2f.", lim);
    }

    /** limiar = 10º percentil das falas CONFIRMADAS do dono - 0,03 (entre LIMIAR_MIN=0,48 e LIMIAR_MAX=0,72), e acima das vozes recusadas */
    static float calibrar(Context c) {
        List<Float> dono = new ArrayList<>(), outras = new ArrayList<>();
        for (JSONObject o : linhas(arq(c, "voz_log.jsonl"))) {
            float sc = (float) o.optDouble("sc", -9);
            if (sc < 0.1f) continue;
            if (o.optBoolean("ok") && (o.optBoolean("dono") || o.optBoolean("fui_eu")) && sc >= Ouvido.LIMIAR_MIN) dono.add(sc);
            else if (!o.optBoolean("dono") && !o.optBoolean("fui_eu")) outras.add(sc);
        }
        android.content.SharedPreferences pf = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE);
        float atual = Math.max(Ouvido.LIMIAR_MIN, pf.getFloat("voz_limiar", Ouvido.LIMIAR_PADRAO));
        if (dono.size() < 6) {
            pf.edit().putFloat("voz_limiar", atual).apply();
            return atual;
        }
        java.util.Collections.sort(dono);
        float p10 = dono.get(Math.max(0, (int) (dono.size() * 0.10f)));
        float novo = Math.max(Ouvido.LIMIAR_MIN, Math.min(Ouvido.LIMIAR_MAX, p10 - 0.03f));
        if (!outras.isEmpty()) {
            java.util.Collections.sort(outras);
            float p90o = outras.get(Math.min(outras.size() - 1, (int) (outras.size() * 0.9f)));
            novo = Math.max(novo, Math.min(Ouvido.LIMIAR_MAX, p90o + 0.04f));
        }
        novo = Math.max(Ouvido.LIMIAR_MIN, Math.min(Ouvido.LIMIAR_MAX, atual + (novo - atual) * 0.5f));
        pf.edit().putFloat("voz_limiar", novo).apply();
        android.util.Log.i("friday-aprende", String.format(Locale.ROOT, "limiar %.3f -> %.3f (dono n=%d p10=%.3f, outras n=%d)", atual, novo, dono.size(), p10, outras.size()));
        return novo;
    }

    // =================================================================== 2) PEDIDOS
    private static volatile JSONObject ultimo;                        // último pedido (para "não foi isso")

    private static final Pattern NEGA = Pattern.compile("^(n[aã]o[, ]+)?(n[aã]o (foi|era) (isso|esse|essa)|errad[oa]|t[aá] errad[oa]|"
        + "n[aã]o ([eé]|era) (isso|o que eu (pedi|falei|disse))|voc[eê] (entendeu|fez) errado|deu errado|n[aã]o funcionou)\\W*$", Pattern.CASE_INSENSITIVE);
    private static final Pattern EU_DISSE = Pattern.compile("^(?:n[aã]o[, ]+)?(?:eu )?(?:disse|falei|pedi)[: ,]+(.{3,})$", Pattern.CASE_INSENSITIVE);

    /** "não foi isso" -> true (a última ação foi marcada como falha) */
    static boolean ehNegacao(String t) { return t != null && NEGA.matcher(norm(t).isEmpty() ? t : t.trim()).matches(); }

    /** "não, eu disse X" -> X (e aprende a correção do STT) */
    static String euDisse(Context c, String t) {
        java.util.regex.Matcher m = EU_DISSE.matcher(t == null ? "" : t.trim());
        if (!m.matches()) return null;
        JSONObject u = ultimo;
        String certo = m.group(1).trim();
        if (u != null && System.currentTimeMillis() / 1000 - u.optLong("t") < 120) {
            String ap = aprenderCorrecao(c, u.optString("pedido"), certo);
            if (ap != null) android.util.Log.i("friday-aprende", "correção aprendida: " + ap);
            falhou(c, "entendi errado: '" + u.optString("pedido") + "' era '" + certo + "'");
        }
        return certo;
    }

    /** chamado pelo Cerebro ao terminar: passos = [acao, args] na ordem; ok = terminou sem erro de ferramenta */
    static void registrar(Context c, String pedido, List<String[]> passos, boolean ok, String resposta) {
        try {
            JSONArray ps = new JSONArray();
            for (String[] p : passos) ps.put(new JSONArray().put(p[0]).put(p[1]));
            ultimo = new JSONObject().put("t", System.currentTimeMillis() / 1000).put("pedido", pedido).put("passos", ps).put("ok", ok)
                .put("resposta", resposta == null ? "" : resposta.length() > 200 ? resposta.substring(0, 200) : resposta);
            if (ok && ps.length() > 0) salvarReceita(c, pedido, ps);
            if (!ok) falhou(c, "pedido '" + pedido + "' falhou: " + (resposta == null ? "" : resposta.length() > 160 ? resposta.substring(0, 160) : resposta));
            else confirmarUltimaVoz(c, true);
        } catch (Exception ignored) {}
    }

    private static void salvarReceita(Context c, String pedido, JSONArray passos) {
        synchronized (trava) {
            try {
                String s = ler(arq(c, "receitas.json"));
                JSONArray rs = new JSONArray(s.isEmpty() ? "[]" : s);
                String n = norm(pedido);
                for (int k = 0; k < rs.length(); k++) if (rs.getJSONObject(k).optString("norm").equals(n)) rs.remove(k--);
                rs.put(new JSONObject().put("pedido", pedido).put("norm", n).put("passos", passos).put("t", System.currentTimeMillis() / 1000));
                while (rs.length() > 120) rs.remove(0);
                gravar(arq(c, "receitas.json"), rs.toString());
            } catch (Exception ignored) {}
        }
    }

    /** o dono disse que a última ação deu errado: tira a receita dela e anota a falha */
    static String falhou(Context c, String motivo) {
        JSONObject u = ultimo;
        try {
            anexar(arq(c, "falhas.jsonl"), new JSONObject().put("t", System.currentTimeMillis() / 1000).put("texto", motivo)
                .put("pedido", u == null ? "" : u.optString("pedido")).put("passos", u == null ? new JSONArray() : u.optJSONArray("passos")), 200);
            if (u != null) {
                confirmarUltimaVoz(c, false);
                synchronized (trava) {
                    String s = ler(arq(c, "receitas.json"));
                    JSONArray rs = new JSONArray(s.isEmpty() ? "[]" : s);
                    String n = norm(u.optString("pedido"));
                    for (int k = 0; k < rs.length(); k++) if (rs.getJSONObject(k).optString("norm").equals(n)) rs.remove(k--);
                    gravar(arq(c, "receitas.json"), rs.toString());
                }
            }
        } catch (Exception ignored) {}
        return "Anotei que deu errado" + (u == null ? "." : ": " + u.optString("pedido") + ". Na próxima eu faço diferente.");
    }

    private static double parecido(String a, String b) {
        Set<String> x = new HashSet<>(Arrays.asList(norm(a).split(" "))), y = new HashSet<>(Arrays.asList(norm(b).split(" ")));
        x.removeIf(w -> w.length() < 3); y.removeIf(w -> w.length() < 3);
        if (x.isEmpty() || y.isEmpty()) return 0;
        Set<String> i = new HashSet<>(x); i.retainAll(y);
        Set<String> u = new HashSet<>(x); u.addAll(y);
        return i.size() / (double) u.size();
    }

    /** trecho para o prompt: o que já deu certo em pedidos parecidos e o que deu errado */
    static String contexto(Context c, String pedido) {
        StringBuilder sb = new StringBuilder();
        try {
            String s = ler(arq(c, "receitas.json"));
            JSONArray rs = new JSONArray(s.isEmpty() ? "[]" : s);
            List<Object[]> cand = new ArrayList<>();
            for (int k = 0; k < rs.length(); k++) {
                JSONObject r = rs.getJSONObject(k);
                double p = parecido(pedido, r.optString("pedido"));
                if (p >= 0.5) cand.add(new Object[]{p, r});
            }
            cand.sort((a, b) -> Double.compare((double) b[0], (double) a[0]));
            for (int k = 0; k < Math.min(2, cand.size()); k++) {
                JSONObject r = (JSONObject) cand.get(k)[1];
                boolean igual = (double) cand.get(k)[0] >= 0.9 && norm(pedido).equals(r.optString("norm"));
                StringBuilder ps = new StringBuilder();
                JSONArray pa = r.getJSONArray("passos");
                for (int j = 0; j < pa.length(); j++)                     // parecido: só a sequência de ferramentas (não copiar números antigos)
                    ps.append(j > 0 ? " -> " : "").append(pa.getJSONArray(j).optString(0)).append(igual ? pa.getJSONArray(j).optString(1) : "");
                sb.append("JÁ DEU CERTO para \"").append(r.optString("pedido")).append("\": ").append(ps).append('\n');
            }
            for (JSONObject f : linhas(arq(c, "falhas.jsonl"))) {
                if (parecido(pedido, f.optString("pedido")) >= 0.5) sb.append("DEU ERRADO antes (evite): ").append(f.optString("texto")).append('\n');
            }
        } catch (Exception ignored) {}
        String r = sb.toString();
        return r.length() > 700 ? r.substring(r.length() - 700) : r;
    }

    // =================================================================== 3) CÓDIGO (proposta feita pelo PC, aprovada pelo dono)
    static List<String> falhasRecentes(Context c, int n) {
        List<String> r = new ArrayList<>();
        List<JSONObject> l = linhas(arq(c, "falhas.jsonl"));
        for (int k = Math.max(0, l.size() - n); k < l.size(); k++) r.add(l.get(k).optString("texto"));
        return r;
    }

    /** a mesma falha 2+ vezes nas últimas 20 -> vale propor melhoria no código */
    static String falhaRepetida(Context c) {
        List<String> l = falhasRecentes(c, 20);
        for (int i = l.size() - 1; i >= 0; i--) {
            int n = 0;
            for (String s : l) if (parecido(s, l.get(i)) >= 0.6) n++;
            if (n >= 2) return l.get(i);
        }
        return null;
    }

    /** manda ao PC: o Claude propõe a mudança numa cópia, o dono aprova no PC/app, o PC compila e instala o APK */
    static String proporMelhoria(Context c, String pedido) {
        if (!Link.pcOnline(c)) return "Preciso do PC ligado para preparar uma melhoria no meu código.";
        try {
            JSONArray fal = new JSONArray();
            for (String s : falhasRecentes(c, 8)) fal.put(s);
            JSONObject corpo = new JSONObject().put("pedido", pedido == null || pedido.trim().isEmpty() ? "corrigir as falhas recentes do app do celular" : pedido)
                .put("falhas", fal).put("voz", resumoVoz(c));
            java.net.HttpURLConnection h = (java.net.HttpURLConnection) new java.net.URL("http://" + Link.host(c) + "/api/aprimorar").openConnection();
            h.setConnectTimeout(3000); h.setReadTimeout(8000);
            h.setRequestMethod("POST"); h.setDoOutput(true);
            h.setRequestProperty("X-Token", Link.token(c));
            h.setRequestProperty("Content-Type", "application/json");
            try (java.io.OutputStream o = h.getOutputStream()) { o.write(corpo.toString().getBytes(StandardCharsets.UTF_8)); }
            int cod = h.getResponseCode();
            h.disconnect();
            return cod == 200 ? "Mandei para o PC preparar a melhoria no meu código. A proposta aparece lá para você aprovar; aprovada, eu me atualizo sozinha."
                : "O PC recusou o pedido de melhoria (" + cod + ").";
        } catch (Exception e) { return "Falhou ao falar com o PC: " + e.getMessage(); }
    }

    static String resumoVoz(Context c) {
        int n = 0, rec = 0, lix = 0, ok = 0, err = 0;
        for (JSONObject o : linhas(arq(c, "voz_log.jsonl"))) {
            n++;
            if (!o.optBoolean("dono") && !o.optBoolean("fui_eu")) rec++;
            if (o.optBoolean("lixo")) lix++;
            if (o.has("ok")) { if (o.optBoolean("ok")) ok++; else err++; }
        }
        float lim = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getFloat("voz_limiar", 0.42f);
        return String.format(Locale.ROOT, "%d falas: %d recusadas como outra voz, %d descartadas como ruído, %d confirmadas, %d erradas; limiar %.2f", n, rec, lix, ok, err, lim);
    }
}
