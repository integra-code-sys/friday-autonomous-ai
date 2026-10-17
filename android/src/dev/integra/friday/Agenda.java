package dev.integra.friday;

import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.provider.CalendarContract;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** AGENDA ÚNICA PC <-> celular. A agenda do PC (memory/agenda.json) é a fonte principal; o celular guarda uma cópia
 *  (agenda_cache.json) e uma FILA de mudanças feitas offline (agenda_fila.json, vence o "mod" mais novo no PC).
 *  - celular -> PC: eventos do Google Agenda do celular viram espelho "fonte: google" lá (o PC também lembra deles);
 *  - PC -> celular: itens do PC são espelhados no calendário LOCAL "Sexta-Feira" (não vai p/ a nuvem; o app de agenda
 *    mostra e toca o lembrete). Prioridade (1 alta, 2 normal, 3 baixa), feito e nível do dia nos dois lados. */
final class Agenda {
    static final class Item {
        String id, titulo = "", local = "", fonte = "pc", tipo = "compromisso", extId;
        long ini, fim;
        int prio = 2, cor = Color.rgb(54, 214, 255), lembrar = 15;
        boolean feito, diaTodo, removido;
        double mod;
    }

    static final class Nivel {
        String nivel = "livre"; double pontos; int total, feitos, conflitos, livreMin;
        List<Item> foco = new ArrayList<>();
    }

    private static final String CAL_NOME = "Sexta-Feira";
    private static final Object trava = new Object();
    private static volatile long ultimaTentativa;
    private static volatile String ultimoErro = "";
    static volatile Runnable aoMudar;                         // a tela da agenda se redesenha quando a sincronização traz novidade

    private Agenda() {}

    // ------------------------------------------------------------------ arquivos
    private static File arq(Context c, String n) { return new File(c.getFilesDir(), n); }

    private static JSONObject lerJson(File f, String padrao) {
        try { return new JSONObject(new String(java.nio.file.Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8)); }
        catch (Exception e) { try { return new JSONObject(padrao); } catch (Exception x) { return new JSONObject(); } }
    }

    private static void gravar(File f, JSONObject j) {
        try {
            File tmp = new File(f.getPath() + ".tmp");
            java.nio.file.Files.write(tmp.toPath(), j.toString().getBytes(StandardCharsets.UTF_8));
            if (!tmp.renameTo(f)) java.nio.file.Files.write(f.toPath(), j.toString().getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {}
    }

    private static JSONObject cache(Context c) { return lerJson(arq(c, "agenda_cache.json"), "{\"itens\":[],\"sync\":0}"); }
    private static JSONObject fila(Context c) { return lerJson(arq(c, "agenda_fila.json"), "{\"m\":{}}"); }

    static long ultimaSync(Context c) { return cache(c).optLong("sync", 0); }
    static int pendentes(Context c) { return fila(c).optJSONObject("m") == null ? 0 : fila(c).optJSONObject("m").length(); }

    // ------------------------------------------------------------------ conversão PC (segundos) <-> Item (ms)
    private static Item deJson(JSONObject o) {
        Item i = new Item();
        i.id = o.optString("id");
        i.titulo = o.optString("titulo", "(sem título)");
        i.local = o.optString("local", "");
        i.tipo = o.optString("tipo", "compromisso");
        i.fonte = o.optString("fonte", "pc");
        i.ini = (long) (o.optDouble("inicio", 0) * 1000);
        i.fim = (long) (o.optDouble("fim", o.optDouble("inicio", 0) + 3600) * 1000);
        i.prio = Math.max(1, Math.min(3, o.optInt("prioridade", 2)));
        i.feito = o.optBoolean("feito");
        i.diaTodo = o.optBoolean("dia_todo");
        i.removido = o.optBoolean("removido");
        i.mod = o.optDouble("mod", 0);
        i.lembrar = o.optInt("lembrar_min", 15);
        return i;
    }

    private static JSONObject paraJson(Item i) throws Exception {
        return new JSONObject().put("id", i.id).put("titulo", i.titulo).put("local", i.local).put("tipo", i.tipo).put("fonte", i.fonte)
            .put("inicio", i.ini / 1000.0).put("fim", i.fim / 1000.0).put("prioridade", i.prio).put("feito", i.feito)
            .put("dia_todo", i.diaTodo).put("removido", i.removido).put("mod", i.mod).put("lembrar_min", i.lembrar);
    }

    static String gid(String extId) {
        try {
            byte[] h = MessageDigest.getInstance("SHA-1").digest(extId.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder("g");
            for (int k = 0; k < 5; k++) sb.append(String.format(Locale.ROOT, "%02x", h[k]));
            return sb.substring(0, 10);                       // "g" + 9 hex = mesmo id do PC
        } catch (Exception e) { return "g" + Math.abs(extId.hashCode()); }
    }

    // ------------------------------------------------------------------ leitura: Google do celular (sem o nosso calendário)
    private static boolean podeLer(Context c) {
        return c.checkSelfPermission(android.Manifest.permission.READ_CALENDAR) == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    private static boolean podeEscrever(Context c) {
        return c.checkSelfPermission(android.Manifest.permission.WRITE_CALENDAR) == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    static List<Item> google(Context c, long ini, long fim) {
        List<Item> l = new ArrayList<>();
        if (!podeLer(c)) return l;
        long nosso = calendarioId(c, false);
        Uri.Builder u = CalendarContract.Instances.CONTENT_URI.buildUpon();
        ContentUris.appendId(u, ini); ContentUris.appendId(u, fim);
        try (Cursor cur = c.getContentResolver().query(u.build(), new String[]{CalendarContract.Instances.EVENT_ID, CalendarContract.Instances.BEGIN,
                CalendarContract.Instances.END, CalendarContract.Instances.TITLE, CalendarContract.Instances.EVENT_LOCATION,
                CalendarContract.Instances.ALL_DAY, CalendarContract.Instances.DISPLAY_COLOR, CalendarContract.Instances.CALENDAR_ID},
                null, null, CalendarContract.Instances.BEGIN + " ASC")) {
            while (cur != null && cur.moveToNext() && l.size() < 300) {
                if (nosso > 0 && cur.getLong(7) == nosso) continue;          // espelho do PC: já está no cache
                Item i = new Item();
                i.extId = cur.getLong(0) + "_" + cur.getLong(1);
                i.id = gid(i.extId);
                i.ini = cur.getLong(1); i.fim = cur.getLong(2);
                i.titulo = cur.getString(3) == null ? "(sem título)" : cur.getString(3);
                i.local = cur.getString(4) == null ? "" : cur.getString(4);
                i.diaTodo = cur.getInt(5) == 1;
                if (i.diaTodo) {                                     // dia todo vem em UTC: traz p/ o dia local
                    java.util.TimeZone tz = java.util.TimeZone.getDefault();
                    i.ini -= tz.getOffset(i.ini); i.fim -= tz.getOffset(i.fim);
                }
                i.cor = cur.getInt(6) == 0 ? Color.rgb(54, 214, 255) : (cur.getInt(6) | 0xFF000000);
                i.fonte = "google";
                l.add(i);
            }
        } catch (Exception ignored) {}
        return l;
    }

    // ------------------------------------------------------------------ visão unificada (cache do PC + Google ao vivo + fila)
    static List<Item> itens(Context c, long ini, long fim) {
        Map<String, Item> m = new HashMap<>();
        JSONArray arr = cache(c).optJSONArray("itens");
        for (int k = 0; arr != null && k < arr.length(); k++) {
            Item i = deJson(arr.optJSONObject(k));
            m.put(i.id, i);
        }
        if (podeLer(c)) {                                             // espelho do Google que sumiu de lá: some daqui também
            List<String> velhos = new ArrayList<>();
            for (Item i : m.values()) if ("google".equals(i.fonte) && i.ini >= ini && i.ini < fim) velhos.add(i.id);
            for (String id : velhos) { Item i = m.remove(id); if (i != null) m.put("~" + id, i); }
        }
        for (Item g : google(c, ini, fim)) {                         // Google ao vivo manda no horário/título; o PC guarda prio/feito
            Item espelho = m.remove("~" + g.id);
            if (espelho == null) espelho = m.get(g.id);
            if (espelho != null) { g.prio = espelho.prio; g.feito = espelho.feito; g.mod = espelho.mod; }
            m.put(g.id, g);
        }
        JSONObject f = fila(c).optJSONObject("m");                  // mudanças locais ainda não enviadas
        if (f != null) for (java.util.Iterator<String> it = f.keys(); it.hasNext(); ) {
            String id = it.next();
            JSONObject o = f.optJSONObject(id);
            Item i = m.get(id);
            if (i == null) { if (o.has("titulo") && o.has("inicio")) m.put(id, deJson(o)); continue; }
            if (o.has("feito")) i.feito = o.optBoolean("feito");
            if (o.has("prioridade")) i.prio = o.optInt("prioridade", 2);
            if (o.has("removido")) i.removido = o.optBoolean("removido");
        }
        List<Item> l = new ArrayList<>();
        for (Map.Entry<String, Item> e : m.entrySet()) {
            Item i = e.getValue();
            if (!e.getKey().startsWith("~") && !i.removido && i.ini < fim && i.fim > ini - 1) l.add(i);
        }
        java.util.Collections.sort(l, (a, b) -> Long.compare(a.ini, b.ini));
        return l;
    }

    static long inicioDoDia(long t) {
        Calendar k = Calendar.getInstance();
        k.setTimeInMillis(t);
        k.set(Calendar.HOUR_OF_DAY, 0); k.set(Calendar.MINUTE, 0); k.set(Calendar.SECOND, 0); k.set(Calendar.MILLISECOND, 0);
        return k.getTimeInMillis();
    }

    // ------------------------------------------------------------------ nível do dia (mesma conta do PC: prom_ops.agenda_nivel)
    static Nivel nivel(List<Item> todos, long dia) {
        long ini = inicioDoDia(dia), fim = ini + 86400000L, agora = System.currentTimeMillis();
        Nivel n = new Nivel();
        List<Item> d = new ArrayList<>(), abertos = new ArrayList<>();
        for (Item i : todos) if (i.ini >= ini && i.ini < fim) { d.add(i); if (!i.feito) abertos.add(i); }
        double peso[] = {0, 3, 2, 1};
        for (Item i : abertos) n.pontos += peso[i.prio] * (i.diaTodo ? 1 : Math.max(0.5, (i.fim - i.ini) / 3600000.0));
        n.nivel = d.isEmpty() ? "livre" : n.pontos < 4 ? "leve" : n.pontos < 9 ? "moderado" : n.pontos < 15 ? "intenso" : "crítico";
        n.total = d.size(); n.feitos = d.size() - abertos.size();
        for (int k = 1; k < d.size(); k++)
            if (!d.get(k).diaTodo && !d.get(k - 1).diaTodo && d.get(k).ini < d.get(k - 1).fim) n.conflitos++;
        long j0 = Math.max(ini + 8 * 3600000L, (agora >= ini && agora < fim) ? agora : ini), j1 = ini + 22 * 3600000L, cur = j0, ocup = 0;
        for (Item i : d) {
            if (i.diaTodo || i.feito) continue;
            long a = Math.max(i.ini, cur), b = Math.min(i.fim, j1);
            if (b > a) { ocup += b - a; cur = b; }
        }
        n.livreMin = (int) Math.max(0, (Math.max(0, j1 - j0) - ocup) / 60000);
        List<Item> f = new ArrayList<>(abertos);
        java.util.Collections.sort(f, (a, b) -> a.prio != b.prio ? Integer.compare(a.prio, b.prio) : Long.compare(a.ini, b.ini));
        n.foco = f.subList(0, Math.min(3, f.size()));
        return n;
    }

    static int corNivel(String n) {
        switch (n) {
            case "crítico": return Color.rgb(255, 90, 110);
            case "intenso": return Color.rgb(255, 138, 31);
            case "moderado": return Color.rgb(255, 210, 127);
            case "leve": return Color.rgb(61, 255, 154);
            default: return Color.argb(150, 190, 205, 212);
        }
    }

    static String nivelFala(Context c, long dia) {
        long ini = inicioDoDia(dia);
        Nivel n = nivel(itens(c, ini, ini + 86400000L), ini);
        boolean hoje = ini == inicioDoDia(System.currentTimeMillis());
        if (n.total == 0) return (hoje ? "Hoje" : "Esse dia") + " está livre.";
        StringBuilder sb = new StringBuilder((hoje ? "Hoje é um dia " : "Será um dia ") + n.nivel + ": " + n.total + (n.total > 1 ? " compromissos" : " compromisso"));
        if (n.feitos > 0) sb.append(", ").append(n.feitos).append(n.feitos > 1 ? " feitos" : " feito");
        if (n.conflitos > 0) sb.append(", ").append(n.conflitos).append(n.conflitos > 1 ? " conflitos de horário" : " conflito de horário");
        sb.append('.');
        if (!n.foco.isEmpty()) {
            Item f = n.foco.get(0);
            sb.append(" Prioridade: ").append(f.titulo);
            if (!f.diaTodo) sb.append(" às ").append(new java.text.SimpleDateFormat("HH:mm", Locale.ROOT).format(new java.util.Date(f.ini)));
            sb.append('.');
        }
        if (n.livreMin >= 30) sb.append(" Você tem ").append(n.livreMin / 60).append('h').append(String.format(Locale.ROOT, "%02d", n.livreMin % 60)).append(" livres.");
        return sb.toString();
    }

    // ------------------------------------------------------------------ mudanças locais (vão para a fila e sobem na próxima sync)
    static void mudar(Context c, String id, String campo, Object valor) {
        synchronized (trava) {
            JSONObject f = fila(c);
            try {
                JSONObject m = f.optJSONObject("m") == null ? new JSONObject() : f.getJSONObject("m");
                JSONObject o = m.optJSONObject(id) == null ? new JSONObject().put("id", id) : m.getJSONObject(id);
                o.put(campo, valor).put("mod", System.currentTimeMillis() / 1000.0);
                m.put(id, o); f.put("m", m);
                gravar(arq(c, "agenda_fila.json"), f);
            } catch (Exception ignored) {}
        }
        sincronizarJa(c);
    }

    static String novo(Context c, String titulo, String quando, int prio, int durMin) {
        if (titulo == null || titulo.trim().isEmpty()) return "falta o título do compromisso";
        if (Link.pcOnline(c)) {                                       // o PC entende a data falada (parse_quando) e cuida da recorrência
            try {
                JSONObject r = post(c, "/api/agenda/add", new JSONObject().put("titulo", titulo).put("quando", quando).put("prioridade", prio).put("dur", durMin));
                if (r.optBoolean("ok")) {
                    sincronizarJa(c);
                    Item i = deJson(r.getJSONObject("item"));
                    return "anotado na agenda (PC e celular): " + i.titulo + ", " + quandoTxt(i.ini) + ("já estava na agenda".equals(r.optString("msg")) ? " (já estava)" : "");
                }
                if (r.has("erro") && r.optString("erro").contains("data")) return "não entendi a data: " + quando;
            } catch (Exception e) { ultimoErro = e.getMessage(); }
        }
        long t = Quando.parse(quando, System.currentTimeMillis());
        if (t <= 0) return "não entendi a data: " + quando;
        Item i = new Item();
        i.id = "c" + Long.toHexString(System.nanoTime() & 0xffffffL);
        i.titulo = titulo.trim(); i.ini = t; i.fim = t + Math.max(5, durMin) * 60000L; i.prio = Math.max(1, Math.min(3, prio));
        i.mod = System.currentTimeMillis() / 1000.0;
        synchronized (trava) {
            JSONObject f = fila(c);
            try {
                JSONObject m = f.optJSONObject("m") == null ? new JSONObject() : f.getJSONObject("m");
                m.put(i.id, paraJson(i)); f.put("m", m);
                gravar(arq(c, "agenda_fila.json"), f);
            } catch (Exception ignored) {}
        }
        sincronizarJa(c);
        return "anotado no celular: " + i.titulo + ", " + quandoTxt(i.ini) + " (sobe para o PC quando ele estiver ligado)";
    }

    static String quandoTxt(long t) {
        long d = (inicioDoDia(t) - inicioDoDia(System.currentTimeMillis())) / 86400000L;
        String h = new java.text.SimpleDateFormat("HH:mm", Locale.ROOT).format(new java.util.Date(t));
        return (d == 0 ? "hoje" : d == 1 ? "amanhã" : new java.text.SimpleDateFormat("EEEE dd/MM", new Locale("pt", "BR")).format(new java.util.Date(t))) + " às " + h;
    }

    /** acha um item (próximos 14 dias) pelo título falado */
    static Item buscar(Context c, String texto) {
        String alvo = norm(texto);
        if (alvo.isEmpty()) return null;
        long agora = System.currentTimeMillis();
        Item melhor = null; int nota = 0;
        for (Item i : itens(c, inicioDoDia(agora) - 86400000L, agora + 14 * 86400000L)) {
            String t = norm(i.titulo);
            int n = t.equals(alvo) ? 3 : (t.contains(alvo) || alvo.contains(t)) ? 2 : 0;
            if (n == 0) { int comum = 0; for (String w : alvo.split(" ")) if (w.length() > 2 && t.contains(w)) comum++; n = comum > 0 ? 1 : 0; }
            if (n > nota) { nota = n; melhor = i; }
        }
        return melhor;
    }

    static String norm(String s) {
        return Normalizer.normalize(s == null ? "" : s.toLowerCase(Locale.ROOT), Normalizer.Form.NFD).replaceAll("\\p{M}", "").replaceAll("[^a-z0-9 ]", " ").trim().replaceAll("\\s+", " ");
    }

    // ------------------------------------------------------------------ sincronização
    static void sincronizarJa(Context c) {
        Context app = c.getApplicationContext();
        new Thread(() -> sincronizar(app, true), "friday-agenda").start();
    }

    /** -> true se falou com o PC. forcar=false respeita 60 s entre tentativas */
    static boolean sincronizar(Context c, boolean forcar) {
        if (!forcar && System.currentTimeMillis() - ultimaTentativa < 60000) return false;
        synchronized (trava) {
            ultimaTentativa = System.currentTimeMillis();
            if (!Link.pcOnline(c)) { ultimoErro = "PC offline"; return false; }
            try {
                JSONObject f = fila(c);
                JSONObject m = f.optJSONObject("m") == null ? new JSONObject() : f.getJSONObject("m");
                JSONArray mud = new JSONArray();
                for (java.util.Iterator<String> it = m.keys(); it.hasNext(); ) mud.put(m.getJSONObject(it.next()));
                long hoje = inicioDoDia(System.currentTimeMillis());
                JSONArray goo = null;
                if (podeLer(c)) {
                    goo = new JSONArray();
                    for (Item g : google(c, hoje - 86400000L, hoje + 15 * 86400000L))
                        goo.put(new JSONObject().put("ext_id", g.extId).put("titulo", g.titulo).put("inicio", g.ini / 1000.0)
                            .put("fim", g.fim / 1000.0).put("local", g.local).put("dia_todo", g.diaTodo));
                }
                JSONObject corpo = new JSONObject().put("mudancas", mud).put("dias", 14);
                if (goo != null) corpo.put("google", goo);
                JSONObject r = post(c, "/api/agenda/sync", corpo);
                JSONArray itens = r.optJSONArray("itens");
                if (itens == null) { ultimoErro = r.optString("erro", "resposta inválida"); return false; }
                String antes = cache(c).optString("itens");
                gravar(arq(c, "agenda_cache.json"), new JSONObject().put("itens", itens).put("niveis", r.optJSONObject("niveis"))
                    .put("sync", System.currentTimeMillis()));
                gravar(arq(c, "agenda_fila.json"), new JSONObject().put("m", new JSONObject()));
                ultimoErro = "";
                espelhar(c, itens);
                Runnable cb = aoMudar;
                if (cb != null && (mud.length() > 0 || !antes.equals(itens.toString()))) cb.run();
                return true;
            } catch (Exception e) {
                ultimoErro = String.valueOf(e.getMessage());
                android.util.Log.w("friday-agenda", "sync: " + e);
                return false;
            }
        }
    }

    static String status(Context c) {
        long s = ultimaSync(c);
        int p = pendentes(c);
        String q = p > 0 ? " · " + p + (p > 1 ? " mudanças na fila" : " mudança na fila") : "";
        if (!ultimoErro.isEmpty() && !"PC offline".equals(ultimoErro) && ultimaTentativa > 0) return "falha ao sincronizar" + q;
        if ("PC offline".equals(ultimoErro)) return "PC offline · usando a cópia do celular" + q;
        if (s == 0) return "ainda não sincronizado com o PC" + q;
        long min = (System.currentTimeMillis() - s) / 60000;
        return "sincronizado com o PC " + (min < 1 ? "agora" : "há " + (min < 60 ? min + " min" : (min / 60) + " h")) + q;
    }

    private static JSONObject post(Context c, String rota, JSONObject corpo) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL("http://" + Link.host(c) + rota).openConnection();
        h.setConnectTimeout(3000); h.setReadTimeout(15000);
        h.setRequestMethod("POST"); h.setDoOutput(true);
        h.setRequestProperty("X-Token", Link.token(c));
        h.setRequestProperty("Content-Type", "application/json");
        try (OutputStream o = h.getOutputStream()) { o.write(corpo.toString().getBytes(StandardCharsets.UTF_8)); }
        int cod = h.getResponseCode();
        InputStream in = cod < 400 ? h.getInputStream() : h.getErrorStream();
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] b = new byte[8192]; int n;
        while (in != null && (n = in.read(b)) > 0) bo.write(b, 0, n);
        h.disconnect();
        return new JSONObject(bo.toString("UTF-8"));
    }

    // ------------------------------------------------------------------ espelho no calendário local "Sexta-Feira"
    private static Uri comoSync(Uri u) {
        return u.buildUpon().appendQueryParameter(CalendarContract.CALLER_IS_SYNCADAPTER, "true")
            .appendQueryParameter(CalendarContract.Calendars.ACCOUNT_NAME, CAL_NOME)
            .appendQueryParameter(CalendarContract.Calendars.ACCOUNT_TYPE, CalendarContract.ACCOUNT_TYPE_LOCAL).build();
    }

    static long calendarioId(Context c, boolean criar) {
        if (!podeLer(c)) return -1;
        try (Cursor cur = c.getContentResolver().query(CalendarContract.Calendars.CONTENT_URI, new String[]{CalendarContract.Calendars._ID},
                CalendarContract.Calendars.ACCOUNT_NAME + "=? AND " + CalendarContract.Calendars.ACCOUNT_TYPE + "=?",
                new String[]{CAL_NOME, CalendarContract.ACCOUNT_TYPE_LOCAL}, null)) {
            if (cur != null && cur.moveToFirst()) return cur.getLong(0);
        } catch (Exception ignored) {}
        if (!criar || !podeEscrever(c)) return -1;
        ContentValues v = new ContentValues();
        v.put(CalendarContract.Calendars.ACCOUNT_NAME, CAL_NOME);
        v.put(CalendarContract.Calendars.ACCOUNT_TYPE, CalendarContract.ACCOUNT_TYPE_LOCAL);
        v.put(CalendarContract.Calendars.NAME, "friday");
        v.put(CalendarContract.Calendars.CALENDAR_DISPLAY_NAME, CAL_NOME + " (PC)");
        v.put(CalendarContract.Calendars.CALENDAR_COLOR, Color.rgb(54, 214, 255));
        v.put(CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL, CalendarContract.Calendars.CAL_ACCESS_OWNER);
        v.put(CalendarContract.Calendars.OWNER_ACCOUNT, CAL_NOME);
        v.put(CalendarContract.Calendars.VISIBLE, 1);
        v.put(CalendarContract.Calendars.SYNC_EVENTS, 1);
        v.put(CalendarContract.Calendars.CALENDAR_TIME_ZONE, java.util.TimeZone.getDefault().getID());
        try {
            Uri u = c.getContentResolver().insert(comoSync(CalendarContract.Calendars.CONTENT_URI), v);
            return u == null ? -1 : ContentUris.parseId(u);
        } catch (Exception e) { android.util.Log.w("friday-agenda", "criar calendário: " + e); return -1; }
    }

    private static void espelhar(Context c, JSONArray itens) {
        long cal = calendarioId(c, true);
        if (cal < 0) return;
        ContentResolver cr = c.getContentResolver();
        Map<String, long[]> existentes = new HashMap<>();             // _SYNC_ID -> {_ID, mod*1000}
        try (Cursor cur = cr.query(comoSync(CalendarContract.Events.CONTENT_URI), new String[]{CalendarContract.Events._ID,
                CalendarContract.Events._SYNC_ID, CalendarContract.Events.SYNC_DATA1}, CalendarContract.Events.CALENDAR_ID + "=?",
                new String[]{String.valueOf(cal)}, null)) {
            while (cur != null && cur.moveToNext()) {
                long modv = 0;
                try { modv = Long.parseLong(cur.getString(2)); } catch (Exception ignored) {}
                existentes.put(cur.getString(1), new long[]{cur.getLong(0), modv});
            }
        } catch (Exception e) { android.util.Log.w("friday-agenda", "ler espelho: " + e); return; }
        Set<String> vivos = new HashSet<>();
        for (int k = 0; k < itens.length(); k++) {
            Item i = deJson(itens.optJSONObject(k));
            if ("google".equals(i.fonte) || i.removido) continue;
            vivos.add(i.id);
            long modv = (long) (i.mod * 1000);
            long[] ex = existentes.get(i.id);
            if (ex != null && ex[1] == modv) continue;               // igual: nada a fazer
            ContentValues v = new ContentValues();
            v.put(CalendarContract.Events.CALENDAR_ID, cal);
            v.put(CalendarContract.Events.TITLE, (i.feito ? "[CONCLUÍDO] " : i.prio == 1 ? "[ALTA] " : "") + i.titulo);
            v.put(CalendarContract.Events.DTSTART, i.ini);
            v.put(CalendarContract.Events.DTEND, Math.max(i.fim, i.ini + 60000));
            v.put(CalendarContract.Events.EVENT_TIMEZONE, java.util.TimeZone.getDefault().getID());
            v.put(CalendarContract.Events.EVENT_LOCATION, i.local);
            v.put(CalendarContract.Events.DESCRIPTION, "Agenda da Sexta-Feira (PC) · prioridade " + (i.prio == 1 ? "alta" : i.prio == 3 ? "baixa" : "normal"));
            v.put(CalendarContract.Events.ALL_DAY, i.diaTodo ? 1 : 0);
            v.put(CalendarContract.Events._SYNC_ID, i.id);
            v.put(CalendarContract.Events.SYNC_DATA1, String.valueOf(modv));
            v.put(CalendarContract.Events.HAS_ALARM, !i.feito && i.lembrar > 0 ? 1 : 0);
            try {
                long evId;
                if (ex == null) {
                    Uri u = cr.insert(comoSync(CalendarContract.Events.CONTENT_URI), v);
                    if (u == null) continue;
                    evId = ContentUris.parseId(u);
                } else {
                    evId = ex[0];
                    cr.update(comoSync(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, evId)), v, null, null);
                    cr.delete(comoSync(CalendarContract.Reminders.CONTENT_URI), CalendarContract.Reminders.EVENT_ID + "=?", new String[]{String.valueOf(evId)});
                }
                if (!i.feito && i.lembrar > 0) {
                    ContentValues r = new ContentValues();
                    r.put(CalendarContract.Reminders.EVENT_ID, evId);
                    r.put(CalendarContract.Reminders.MINUTES, i.lembrar);
                    r.put(CalendarContract.Reminders.METHOD, CalendarContract.Reminders.METHOD_ALERT);
                    cr.insert(comoSync(CalendarContract.Reminders.CONTENT_URI), r);
                }
            } catch (Exception e) { android.util.Log.w("friday-agenda", "espelhar " + i.id + ": " + e); }
        }
        long limite = inicioDoDia(System.currentTimeMillis()) - 86400000L;   // fora da janela recebida: não mexe
        for (Map.Entry<String, long[]> e : existentes.entrySet()) {
            if (vivos.contains(e.getKey())) continue;
            try {
                long ini = 0;
                try (Cursor cur = cr.query(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, e.getValue()[0]),
                        new String[]{CalendarContract.Events.DTSTART}, null, null, null)) {
                    if (cur != null && cur.moveToFirst()) ini = cur.getLong(0);
                }
                if (ini >= limite && ini <= System.currentTimeMillis() + 15 * 86400000L)
                    cr.delete(comoSync(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, e.getValue()[0])), null, null);
            } catch (Exception ignored) {}
        }
    }

    // ------------------------------------------------------------------ "amanhã às 15h" sem o PC
    static final class Quando {
        private static final String[] SEM = {"domingo", "segunda", "terca", "quarta", "quinta", "sexta", "sabado"};

        static long parse(String txt, long agora) {
            String t = norm(txt);
            if (t.isEmpty()) return -1;
            Calendar k = Calendar.getInstance();
            k.setTimeInMillis(agora); k.set(Calendar.SECOND, 0); k.set(Calendar.MILLISECOND, 0);
            boolean temDia = false;
            String resto = t;                                       // o que sobra p/ achar a hora (sem a data)
            if (t.contains("depois de amanha")) { k.add(Calendar.DAY_OF_YEAR, 2); temDia = true; }
            else if (t.contains("amanha")) { k.add(Calendar.DAY_OF_YEAR, 1); temDia = true; }
            else if (t.contains("hoje")) temDia = true;
            else {
                for (int d = 0; d < 7 && !temDia; d++) if (t.matches(".*\\b" + SEM[d] + "\\b.*")) {
                    int dif = ((d + 1) - k.get(Calendar.DAY_OF_WEEK) + 7) % 7;
                    k.add(Calendar.DAY_OF_YEAR, dif == 0 ? 7 : dif); temDia = true;
                }
                Matcher m = Pattern.compile("\\b(\\d{1,2}) (\\d{1,2})(?: (\\d{4}))?\\b").matcher(t);
                Matcher md = Pattern.compile("\\bdia (\\d{1,2})\\b").matcher(t);
                if (!temDia && txt.matches(".*\\d{1,2}/\\d{1,2}.*") && m.find()) {
                    k.set(Calendar.DAY_OF_MONTH, Integer.parseInt(m.group(1))); k.set(Calendar.MONTH, Integer.parseInt(m.group(2)) - 1);
                    if (m.group(3) != null) k.set(Calendar.YEAR, Integer.parseInt(m.group(3)));
                    else if (k.getTimeInMillis() < agora - 86400000L) k.add(Calendar.YEAR, 1);
                    resto = resto.replaceFirst(Pattern.quote(m.group(0)), " ");
                    temDia = true;
                } else if (!temDia && md.find()) {
                    int dia = Integer.parseInt(md.group(1));
                    if (dia < k.get(Calendar.DAY_OF_MONTH)) k.add(Calendar.MONTH, 1);
                    k.set(Calendar.DAY_OF_MONTH, dia); temDia = true;
                    resto = resto.replaceFirst(Pattern.quote(md.group(0)), " ");
                }
            }
            int h = -1, min = 0;
            if (t.contains("meio dia")) h = 12;
            else if (t.contains("meia noite")) h = 0;
            Matcher mh = Pattern.compile("\\b(?:as |a )?(\\d{1,2})(?: ?h| horas?| ?:)? ?(\\d{2})?\\b(?! (?:de|do) )").matcher(resto);
            if (h < 0) while (mh.find()) {
                int v = Integer.parseInt(mh.group(1));
                if (v > 23) continue;
                h = v; min = mh.group(2) != null ? Math.min(59, Integer.parseInt(mh.group(2))) : 0;
                break;
            }
            if (h >= 0 && h < 12 && (t.contains("da tarde") || t.contains("da noite"))) h += 12;
            if (t.contains("e meia") && min == 0) min = 30;
            if (h < 0) {
                if (!temDia) return -1;
                h = 9;                                                // só o dia: 9h
            }
            k.set(Calendar.HOUR_OF_DAY, h); k.set(Calendar.MINUTE, min);
            if (!temDia && k.getTimeInMillis() < agora) k.add(Calendar.DAY_OF_YEAR, 1);   // "às 8" já passou: amanhã
            return k.getTimeInMillis();
        }
    }
}
