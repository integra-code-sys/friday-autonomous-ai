package dev.integra.friday;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** MODO DEV no CELULAR (independente do PC): a Friday manda o pedido ao Claude Code CLI dentro do Termux
 *  (API oficial com.termux.RUN_COMMAND) e recebe a saída. Projeto em ~/dev do Termux. Requer, uma vez:
 *  Termux instalado + `allow-external-apps=true` em ~/.termux/termux.properties + permissão "Executar comandos no Termux"
 *  dada à Friday + `claude` instalado e logado (ver friday-dev-setup.sh). */
final class Dev {
    private Dev() {}

    static final String TERMUX = "com.termux";
    static final String BASH = "/data/data/com.termux/files/usr/bin/bash";
    private static final AtomicInteger seq = new AtomicInteger(1);
    private static final Map<Integer, String[]> saidas = new ConcurrentHashMap<>();
    private static final Map<Integer, CountDownLatch> esperas = new ConcurrentHashMap<>();

    static boolean termuxInstalado(Context c) {
        try { c.getPackageManager().getPackageInfo(TERMUX, 0); return true; } catch (Exception e) { return false; }
    }

    static boolean permitido(Context c) {
        return c.checkSelfPermission("com.termux.permission.RUN_COMMAND") == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    /** roda um comando bash no Termux e devolve stdout (+stderr). Bloqueante (até `segundos`). */
    static String rodar(Context c, String comando, int segundos) {
        if (!termuxInstalado(c)) return "Termux não está instalado no celular";
        if (!permitido(c)) return "falta a permissão 'Executar comandos no Termux' para a Friday (Configurações do app > Permissões)";
        int id = seq.getAndIncrement();
        CountDownLatch fim = new CountDownLatch(1);
        esperas.put(id, fim);
        Intent volta = new Intent(c, Resultado.class).putExtra("id", id);
        PendingIntent pi = PendingIntent.getBroadcast(c, id, volta, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
        Intent i = new Intent("com.termux.RUN_COMMAND").setClassName(TERMUX, "com.termux.app.RunCommandService")
            .putExtra("com.termux.RUN_COMMAND_PATH", BASH)
            .putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{"-lc", comando})
            .putExtra("com.termux.RUN_COMMAND_WORKDIR", "/data/data/com.termux/files/home")
            .putExtra("com.termux.RUN_COMMAND_BACKGROUND", true)
            .putExtra("com.termux.RUN_COMMAND_PENDING_INTENT", pi);
        try {
            if (android.os.Build.VERSION.SDK_INT >= 26) c.startForegroundService(i); else c.startService(i);
        } catch (Exception e) {
            esperas.remove(id);
            return "o Termux recusou (" + e.getMessage() + "); no Termux: echo allow-external-apps=true >> ~/.termux/termux.properties";
        }
        try { fim.await(segundos, TimeUnit.SECONDS); } catch (InterruptedException ignored) {}
        esperas.remove(id);
        String[] r = saidas.remove(id);
        if (r == null) return "o Termux não respondeu em " + segundos + " s";
        String out = (r[0] == null ? "" : r[0]).trim(), err = (r[1] == null ? "" : r[1]).trim();
        return (out.isEmpty() ? err : out + (err.isEmpty() ? "" : "\n[erro] " + err)) + ("0".equals(r[2]) ? "" : "\n(código " + r[2] + ")");
    }

    /** pedido de programação para o Claude Code CLI (não interativo) no projeto ~/dev */
    static String claude(Context c, String pedido) {
        String p = pedido.replace("'", "'\"'\"'");
        return rodar(c, "export SHELL=" + BASH + " DISABLE_AUTOUPDATER=1; mkdir -p ~/dev && cd ~/dev && ~/bin/claude -p --dangerously-skip-permissions --output-format text '" + p + "' < /dev/null 2>&1 | tail -c 6000", 900);
    }

    /** abre o terminal do Termux com o Claude interativo (MODO DEV CLI na tela) */
    static void abrirTerminal(Context c) {
        Intent i = new Intent("com.termux.RUN_COMMAND").setClassName(TERMUX, "com.termux.app.RunCommandService")
            .putExtra("com.termux.RUN_COMMAND_PATH", BASH)
            .putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{"-lc", "export SHELL=" + BASH + " DISABLE_AUTOUPDATER=1; mkdir -p ~/dev && cd ~/dev && ~/bin/claude"})
            .putExtra("com.termux.RUN_COMMAND_BACKGROUND", false);
        try { c.startService(i); } catch (Exception e) {
            Intent l = c.getPackageManager().getLaunchIntentForPackage(TERMUX);
            if (l != null) c.startActivity(l.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        }
    }

    /** recebe o resultado do Termux (stdout/stderr/exitCode no bundle "result") */
    public static class Resultado extends BroadcastReceiver {
        @Override public void onReceive(Context c, Intent i) {
            int id = i.getIntExtra("id", -1);
            Bundle b = i.getBundleExtra("result");
            if (b != null) saidas.put(id, new String[]{b.getString("stdout"), b.getString("stderr"), String.valueOf(b.getInt("exitCode"))});
            CountDownLatch l = esperas.get(id);
            if (l != null) l.countDown();
        }
    }
}
