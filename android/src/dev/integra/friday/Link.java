package dev.integra.friday;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Ligação entre a Friday do CELULAR e a do PC (pelo Tailscale, com o token do controle remoto). Cada uma funciona sozinha;
 *  quando as duas estão ligadas o celular manda ao PC o que é do computador (/api/pedido) e o PC pede ao celular pelo /pedir. */
final class Link {
    private static volatile long ultimoTeste;
    private static volatile boolean online;
    private static volatile String hostAtivo;

    private Link() {}

    static SharedPreferences prefs(Context c) { return c.getSharedPreferences("ponte", Context.MODE_PRIVATE); }
    static String host(Context c) {
        String h = hostAtivo;
        return h != null && !h.isEmpty() ? h : prefs(c).getString("host", "100.110.230.55:8790");
    }
    static String token(Context c) { return prefs(c).getString("tok", ""); }

    /** o PC está ligado e alcançável? (cache de 15 s; testa Tailscale e Wi-Fi local automaticamente) */
    static boolean pcOnline(Context c) {
        if (System.currentTimeMillis() - ultimoTeste < 15000) return online;
        ultimoTeste = System.currentTimeMillis();
        String salvo = prefs(c).getString("host", "100.110.230.55:8790");
        String[] candidatos = new String[]{salvo, "192.168.15.8:8790", "100.110.230.55:8790"};
        for (String cand : candidatos) {
            if (cand == null || cand.isEmpty()) continue;
            try {
                HttpURLConnection h = (HttpURLConnection) new URL("http://" + cand + "/api/ping").openConnection();
                h.setConnectTimeout(1100); h.setReadTimeout(1100);
                h.setRequestProperty("X-Token", token(c));
                if (h.getResponseCode() == 200) {
                    h.disconnect();
                    hostAtivo = cand;
                    online = true;
                    return true;
                }
                h.disconnect();
            } catch (Exception ignored) {}
        }
        online = false;
        return false;
    }

    // ------------------------------------------------------------------ Tailscale (o app tem CONNECT_VPN/DISCONNECT_VPN públicos)
    static boolean vpnAtiva(Context c) {
        android.net.ConnectivityManager cm = (android.net.ConnectivityManager) c.getSystemService(Context.CONNECTIVITY_SERVICE);
        for (android.net.Network n : cm.getAllNetworks()) {
            android.net.NetworkCapabilities nc = cm.getNetworkCapabilities(n);
            if (nc != null && nc.hasTransport(android.net.NetworkCapabilities.TRANSPORT_VPN)) return true;
        }
        return false;
    }

    /** liga/desliga o Tailscale e grava a vontade do dono (o vigia do Acesso religa se cair) */
    static String tailscale(Context c, boolean ligar) {
        prefs(c).edit().putBoolean("ts_manter", ligar).apply();
        enviarTs(c, ligar);
        ultimoTeste = 0;
        return "Tailscale " + (ligar ? "ligando (fica ligado: se cair, eu religo)" : "desligado");
    }

    static void enviarTs(Context c, boolean ligar) {
        c.sendBroadcast(new android.content.Intent(ligar ? "com.tailscale.ipn.CONNECT_VPN" : "com.tailscale.ipn.DISCONNECT_VPN")
            .setClassName("com.tailscale.ipn", "com.tailscale.ipn.IPNReceiver"));
    }

    static boolean tsManter(Context c) { return prefs(c).getBoolean("ts_manter", true); }

    static String pedirAoPc(Context c, String pedido) {
        if (pedido == null || pedido.trim().isEmpty()) return "pedido vazio";
        ultimoTeste = 0;
        if (!pcOnline(c)) return "o PC está desligado ou fora do Tailscale agora; faça no celular ou avise o dono";
        try {
            HttpURLConnection h = (HttpURLConnection) new URL("http://" + host(c) + "/api/pedido").openConnection();
            h.setConnectTimeout(3000); h.setReadTimeout(8000);
            h.setRequestMethod("POST"); h.setDoOutput(true);
            h.setRequestProperty("X-Token", token(c));
            h.setRequestProperty("Content-Type", "application/json");
            byte[] corpo = new JSONObject().put("texto", pedido).put("origem", "celular").toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream o = h.getOutputStream()) { o.write(corpo); }
            int cod = h.getResponseCode();
            InputStream in = cod < 400 ? h.getInputStream() : h.getErrorStream();
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] b = new byte[4096]; int n;
            while (in != null && (n = in.read(b)) > 0) bo.write(b, 0, n);
            h.disconnect();
            JSONObject r = new JSONObject(bo.toString("UTF-8"));
            return r.optBoolean("ok") ? "a Friday do PC recebeu e está fazendo: " + pedido : "o PC recusou: " + r.optString("erro");
        } catch (Exception e) {
            return "falhou ao falar com o PC: " + e.getMessage();
        }
    }
}
