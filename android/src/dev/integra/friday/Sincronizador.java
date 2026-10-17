package dev.integra.friday;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.Locale;

/** Sincronizador Mesh Bidirecional para F.R.I.D.A.Y. no Android.
 *  Permite operação 100% autônoma (offline) com IA local, agenda local, documentos e memória no celular.
 *  Quando qualquer PC (Linux ou Windows) ou servidor do cluster é ligado/conectado à rede,
 *  detecta automaticamente a presença e sincroniza bidirecionalmente:
 *  - Agenda (via Agenda.sincronizar com Last-Write-Wins e tombstones)
 *  - Fatos & Memória (memoria.sqlite do PC <-> SharedPreferences m:* do Android)
 *  - Tarefas (tarefas.json <-> tarefas_cache.json)
 *  - Lições & Receitas (licoes.json <-> receitas.json)
 */
public final class Sincronizador {
    private static final String TAG = "friday-sync";
    private static final Object TRAVA = new Object();
    private static volatile boolean vigiaAtivo = false;
    private static volatile boolean pcEstavaOnline = false;
    private static volatile long ultimaTentativa = 0;
    private static volatile long ultimaSyncSucesso = 0;

    private Sincronizador() {}

    private static File arq(Context c, String n) { return new File(c.getFilesDir(), n); }

    private static JSONObject lerJson(File f, String padrao) {
        try {
            if (f.exists()) {
                return new JSONObject(new String(java.nio.file.Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
            }
        } catch (Exception ignored) {}
        try { return new JSONObject(padrao); } catch (Exception e) { return new JSONObject(); }
    }

    private static void gravarJson(File f, JSONObject j) {
        try {
            File tmp = new File(f.getPath() + ".tmp");
            java.nio.file.Files.write(tmp.toPath(), j.toString().getBytes(StandardCharsets.UTF_8));
            if (!tmp.renameTo(f)) {
                java.nio.file.Files.write(f.toPath(), j.toString().getBytes(StandardCharsets.UTF_8));
            }
        } catch (Exception ignored) {}
    }

    /** Registra um fato aprendido offline pelo Android na fila para subir quando o PC ligar. */
    public static void notificarFatoLocal(Context c, String chave, String valor) {
        if (chave == null || chave.trim().isEmpty() || valor == null) return;
        synchronized (TRAVA) {
            File f = arq(c, "memoria_fila.json");
            JSONObject d = lerJson(f, "{\"fatos\":{}}");
            try {
                JSONObject fatos = d.optJSONObject("fatos");
                if (fatos == null) fatos = new JSONObject();
                fatos.put(chave.trim().toLowerCase(Locale.ROOT), new JSONObject()
                    .put("chave", chave.trim())
                    .put("resumo", valor.trim())
                    .put("mod", System.currentTimeMillis() / 1000.0));
                d.put("fatos", fatos);
                gravarJson(f, d);
            } catch (Exception e) {
                Log.w(TAG, "erro ao registrar fato na fila: " + e);
            }
        }
        sincronizarJa(c);
    }

    /** Dispara sincronização em thread secundária imediatamente. */
    public static void sincronizarJa(Context c) {
        final Context app = c.getApplicationContext();
        new Thread(() -> sincronizarTudo(app, true), "friday-mesh-sync").start();
    }

    /** Executa sincronização completa bidirecional de todos os dados do ecossistema. */
    public static boolean sincronizarTudo(Context c, boolean forcar) {
        long agora = System.currentTimeMillis();
        if (!forcar && agora - ultimaTentativa < 10000) return false;
        ultimaTentativa = agora;

        if (!Link.pcOnline(c)) {
            return false;
        }

        synchronized (TRAVA) {
            boolean agOk = false;
            boolean meshOk = false;
            try {
                // 1. Sincroniza Agenda
                agOk = Agenda.sincronizar(c, true);

                // 2. Sincroniza Fatos, Memória, Lições e Tarefas via /api/mesh/sync
                File stateFile = arq(c, "mesh_state.json");
                JSONObject state = lerJson(stateFile, "{\"last_sync\":0,\"fatos\":0,\"licoes\":0,\"tarefas\":0}");
                double sinceFatos = state.optDouble("fatos", 0.0);
                double sinceLicoes = state.optDouble("licoes", 0.0);
                double sinceTarefas = state.optDouble("tarefas", 0.0);

                // Prepara deltas locais de fatos pendentes
                File filaFatos = arq(c, "memoria_fila.json");
                JSONObject filaData = lerJson(filaFatos, "{\"fatos\":{}}");
                JSONObject fatosPendentes = filaData.optJSONObject("fatos");
                JSONArray ftArray = new JSONArray();
                if (fatosPendentes != null) {
                    for (Iterator<String> it = fatosPendentes.keys(); it.hasNext(); ) {
                        JSONObject fo = fatosPendentes.getJSONObject(it.next());
                        ftArray.put(new JSONObject()
                            .put("tipo", "fato")
                            .put("chave", fo.optString("chave"))
                            .put("resumo", fo.optString("resumo"))
                            .put("visto_ult", fo.optDouble("mod", System.currentTimeMillis() / 1000.0))
                            .put("vezes", 1));
                    }
                }

                // Monta requisição Mesh
                String nodeId = "FRIDAY-ANDROID-" + Build.MODEL.replaceAll("[^a-zA-Z0-9]", "");
                JSONObject payload = new JSONObject();
                payload.put("node_id", nodeId);
                payload.put("hostname", Build.MODEL);
                payload.put("os", "android");
                payload.put("port", 8791);
                payload.put("since", new JSONObject()
                    .put("fatos", sinceFatos)
                    .put("licoes", sinceLicoes)
                    .put("tarefas", sinceTarefas));
                payload.put("deltas", new JSONObject()
                    .put("fatos", ftArray));
                payload.put("now", System.currentTimeMillis() / 1000.0);

                JSONObject resp = postJson(c, "/api/mesh/sync", payload);
                if (resp != null && resp.optBoolean("ok")) {
                    meshOk = true;
                    // Limpa fila de fatos que foram entregues ao PC
                    gravarJson(filaFatos, new JSONObject().put("fatos", new JSONObject()));

                    JSONObject deltasRemotos = resp.optJSONObject("deltas");
                    if (deltasRemotos != null) {
                        // Aplica fatos vindos do PC no SharedPreferences local para uso offline
                        JSONArray ftNovos = deltasRemotos.optJSONArray("fatos");
                        if (ftNovos != null && ftNovos.length() > 0) {
                            SharedPreferences prefs = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE);
                            SharedPreferences.Editor ed = prefs.edit();
                            for (int i = 0; i < ftNovos.length(); i++) {
                                JSONObject ft = ftNovos.getJSONObject(i);
                                String ch = ft.optString("chave");
                                String res = ft.optString("resumo");
                                if (!ch.isEmpty() && !res.isEmpty()) {
                                    ed.putString("m:" + ch.toLowerCase(Locale.ROOT), res);
                                }
                            }
                            ed.apply();
                            Log.i(TAG, "Memória integrada do cluster: " + ftNovos.length() + " fatos atualizados");
                        }

                        // Aplica tarefas vindas do cluster
                        JSONArray tfNovas = deltasRemotos.optJSONArray("tarefas");
                        if (tfNovas != null && tfNovas.length() > 0) {
                            File tfArq = arq(c, "tarefas_cache.json");
                            gravarJson(tfArq, new JSONObject().put("itens", tfNovas));
                        }

                        // Aplica lições vindas do cluster
                        JSONArray lcNovas = deltasRemotos.optJSONArray("licoes");
                        if (lcNovas != null && lcNovas.length() > 0) {
                            File lcArq = arq(c, "licoes_cache.json");
                            gravarJson(lcArq, new JSONObject().put("itens", lcNovas));
                        }
                    }

                    double agoraSec = resp.optDouble("now", System.currentTimeMillis() / 1000.0);
                    state.put("last_sync", System.currentTimeMillis());
                    state.put("fatos", agoraSec);
                    state.put("licoes", agoraSec);
                    state.put("tarefas", agoraSec);
                    gravarJson(stateFile, state);
                    ultimaSyncSucesso = System.currentTimeMillis();
                }
            } catch (Exception e) {
                Log.w(TAG, "falha no ciclo de sincronização: " + e);
            }
            return agOk || meshOk;
        }
    }

    private static JSONObject postJson(Context c, String rota, JSONObject corpo) {
        try {
            HttpURLConnection h = (HttpURLConnection) new URL("http://" + Link.host(c) + rota).openConnection();
            h.setConnectTimeout(3000);
            h.setReadTimeout(12000);
            h.setRequestMethod("POST");
            h.setDoOutput(true);
            h.setRequestProperty("X-Token", Link.token(c));
            h.setRequestProperty("Content-Type", "application/json");
            try (OutputStream o = h.getOutputStream()) {
                o.write(corpo.toString().getBytes(StandardCharsets.UTF_8));
            }
            int cod = h.getResponseCode();
            InputStream in = cod < 400 ? h.getInputStream() : h.getErrorStream();
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n;
            while (in != null && (n = in.read(b)) > 0) bo.write(b, 0, n);
            h.disconnect();
            if (cod == 200) {
                return new JSONObject(bo.toString("UTF-8"));
            }
        } catch (Exception ignored) {}
        return null;
    }

    /** Inicia o supervisor automático em segundo plano que monitora conexão dos nós. */
    public static synchronized void iniciarVigia(final Context c) {
        if (vigiaAtivo) return;
        vigiaAtivo = true;
        final Context app = c.getApplicationContext();

        new Thread(() -> {
            Log.i(TAG, "Supervisor de malha multi-nó ativo (intervalo 12s)");
            try { Thread.sleep(8000); } catch (Exception ignored) {}

            while (vigiaAtivo) {
                try {
                    boolean onlineAgora = Link.pcOnline(app);
                    if (onlineAgora && !pcEstavaOnline) {
                        Log.i(TAG, "Nó do cluster (PC) detectado online! Disparando auto-sincronização...");
                        sincronizarTudo(app, true);
                    } else if (onlineAgora && (System.currentTimeMillis() - ultimaSyncSucesso > 180000)) {
                        // A cada 3 minutos faz heartbeat de sincronização se continuar online
                        sincronizarTudo(app, false);
                    }
                    pcEstavaOnline = onlineAgora;
                } catch (Exception e) {
                    Log.w(TAG, "erro no supervisor: " + e);
                }
                try { Thread.sleep(12000); } catch (Exception ignored) {}
            }
        }, "friday-mesh-vigia").start();
    }

    public static String status(Context c) {
        if (!Link.pcOnline(c)) return "Operando 100% Standalone (PC Offline)";
        if (ultimaSyncSucesso == 0) return "Conectado · Sincronizando dados…";
        long min = (System.currentTimeMillis() - ultimaSyncSucesso) / 60000;
        return "Cluster Conectado · Sincronizado " + (min < 1 ? "agora" : "há " + min + " min");
    }
}
