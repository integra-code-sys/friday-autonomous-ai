package dev.integra.friday;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.BatteryManager;
import android.content.IntentFilter;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Ponte do PC para o celular (pelo Tailscale). Roda dentro do Serviço de Acessibilidade: o Android o mantém vivo e o
 *  religa no boot. API HTTP na porta 8791, SÓ para IPs do Tailscale (100.64.0.0/10) e localhost, com o token do controle remoto.
 *  GET /estado · /acordar · /desbloquear?pin= · /global?a=voltar|inicio|recentes|notificacoes|rapidas|bloquear
 *  · /abrir?nome= · /apps · /toque?x=&y=&ms= · /arrastar?x0=&y0=&x1=&y1=&ms= · /texto?t= · /arvore · /tela · /manter?s= · /soltar
 *  · /transmitir?fps=&w=&kbps= (stream H.264 na porta 8792) · /parar_transmissao */
public class Acesso extends AccessibilityService {
    static final int PORTA = 8791;
    static volatile Acesso inst;
    private ServerSocket srv;
    private final Handler main = new Handler(Looper.getMainLooper());
    private PowerManager.WakeLock manter;

    @Override
    protected void onServiceConnected() {
        inst = this;
        new Thread(this::servir, "friday-ponte").start();
        if (getSharedPreferences("friday_local", MODE_PRIVATE).getBoolean("bolha", false)) Flutuante.bolha(this, true);  // bolha só se o dono pedir
        new Thread(() -> {                                   // VIGIA do Tailscale: o dono quer ligado -> se cair, religa (a cada 30 s)
            while (inst == this) {
                try {
                    Thread.sleep(30000);
                    if (Link.tsManter(this) && !Link.vpnAtiva(this)) { Link.enviarTs(this, true); android.util.Log.i("friday-ts", "Tailscale caiu: religando"); }
                } catch (Exception ignored) {}
            }
        }, "friday-tailscale").start();
        new Thread(() -> {                                   // VIGIA do Syncthing (Sistemas PC <-> celular): religa no Termux se cair
            while (inst == this) {
                try {
                    Thread.sleep(120000);
                    if (Dev.termuxInstalado(this) && Dev.permitido(this))
                        Dev.rodar(this, "pgrep -x syncthing >/dev/null || { termux-wake-lock; nohup syncthing serve --no-browser --no-restart "
                            + "--home=$HOME/.config/syncthing --gui-address=127.0.0.1:8384 > ~/.syncthing.log 2>&1 & }", 30);
                } catch (Exception ignored) {}
            }
        }, "friday-sync").start();
        Sincronizador.iniciarVigia(this);                    // Malha multi-nó: detecta conexão do PC em até 12s e sincroniza agenda, memórias e tarefas

        new Thread(() -> {                                   // Friday LOCAL: carrega e aquece o cérebro em 2º plano (1º pedido já rápido)
            try { Thread.sleep(15000); Cerebro.get(this).preparar(); } catch (Exception ignored) {}
        }, "friday-aquece").start();

        new Thread(() -> {                                   // Autonomia adaptativa proativa no Android (agenda e bateria)
            while (inst == this) {
                try {
                    Thread.sleep(60000);
                    Agenda.verificarLembretes(this);
                    verificarSaudeBateria();
                } catch (Exception ignored) {}
            }
        }, "friday-autonomia-android").start();
    }

    private long ultAlertaBateria = 0;
    private void verificarSaudeBateria() {
        try {
            IntentFilter ifilter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
            Intent b = registerReceiver(null, ifilter);
            if (b == null) return;
            int level = b.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
            int scale = b.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
            int status = b.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
            boolean carregando = (status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL);
            float pct = (level * 100f) / (float) scale;
            long agora = System.currentTimeMillis();
            if (!carregando && pct <= 15 && agora - ultAlertaBateria > 900000L) {
                ultAlertaBateria = agora;
                String msg = "Atenção: bateria do celular em " + (int) pct + "% e descarregando. Conecte o carregador.";
                Agenda.notificar(this, "Bateria Crítica", msg);
                try { Voz.get(this).falar(msg); } catch (Exception ignored) {}
            }
        } catch (Exception ignored) {}
    }

    @Override
    public boolean onUnbind(Intent i) {
        inst = null;
        pulsar(false);
        try { if (srv != null) srv.close(); } catch (Exception ignored) {}
        soltar();
        return super.onUnbind(i);
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent e) {}
    @Override public void onInterrupt() {}

    // ------------------------------------------------------------------ servidor HTTP mínimo
    private void servir() {
        while (inst == this) {
            try {
                srv = new ServerSocket(PORTA, 8, InetAddress.getByName("0.0.0.0"));
                while (inst == this) {
                    Socket s = srv.accept();
                    new Thread(() -> atender(s), "friday-req").start();
                }
            } catch (Exception e) {
                try { Thread.sleep(3000); } catch (InterruptedException ignored) {}
            }
        }
    }

    static boolean ipPermitido(InetAddress a) {
        if (a.isLoopbackAddress()) return true;
        byte[] b = a.getAddress();
        if (b.length == 16) {                                  // IPv4 mapeado em IPv6 (::ffff:100.x.y.z)
            boolean mapeado = true;
            for (int i = 0; i < 10; i++) if (b[i] != 0) mapeado = false;
            if (!mapeado || b[10] != (byte) 0xff || b[11] != (byte) 0xff) return false;
            b = new byte[]{b[12], b[13], b[14], b[15]};
        }
        return b.length == 4 && (b[0] & 0xff) == 100 && (b[1] & 0xc0) == 64;     // 100.64.0.0/10 = Tailscale
    }

    private boolean tokenOk(String t) {
        String certo = getSharedPreferences("ponte", MODE_PRIVATE).getString("tok", "");
        return !certo.isEmpty() && t != null && MessageDigest.isEqual(certo.getBytes(StandardCharsets.UTF_8), t.getBytes(StandardCharsets.UTF_8));
    }

    private void atender(Socket s) {
        try (Socket so = s) {
            so.setSoTimeout(15000);
            if (!ipPermitido(so.getInetAddress())) return;
            BufferedReader in = new BufferedReader(new InputStreamReader(so.getInputStream(), StandardCharsets.UTF_8));
            String linha = in.readLine();
            if (linha == null) return;
            String[] p = linha.split(" ");
            if (p.length < 2) return;
            String tok = null, h;
            int nLinhas = 0;
            while ((h = in.readLine()) != null && !h.isEmpty()) {
                int c = h.indexOf(':');
                if (c > 0 && h.substring(0, c).trim().equalsIgnoreCase("X-Token")) tok = h.substring(c + 1).trim();
                if (c > 0 && h.substring(0, c).trim().equalsIgnoreCase("X-Linhas")) try { nLinhas = Integer.parseInt(h.substring(c + 1).trim()); } catch (Exception ignored) {}
            }
            String alvo = p[1], rota = alvo;
            Map<String, String> q = new HashMap<>();
            int qi = alvo.indexOf('?');
            if (qi >= 0) {
                rota = alvo.substring(0, qi);
                for (String kv : alvo.substring(qi + 1).split("&")) {
                    int e = kv.indexOf('=');
                    if (e > 0) q.put(URLDecoder.decode(kv.substring(0, e), "UTF-8"), URLDecoder.decode(kv.substring(e + 1), "UTF-8"));
                }
            }
            if (tok == null) tok = q.get("t");
            OutputStream out = so.getOutputStream();
            if (!tokenOk(tok)) { responder(out, 401, "application/json", "{\"erro\":\"token inválido\"}".getBytes(StandardCharsets.UTF_8)); return; }
            if (rota.equals("/ide")) {                         // MODO DEV autônomo: lote de linhas stream-json do Claude (ide_ponte.py)
                for (int k = 0; k < Math.min(nLinhas, 200); k++) { String l = in.readLine(); if (l == null) break; Ide.evento(l); }
                responder(out, 200, "application/json", "{\"ok\":true}".getBytes(StandardCharsets.UTF_8));
                return;
            }
            if (rota.equals("/tela")) {
                byte[] jpg = tela();
                if (jpg == null) responder(out, 503, "application/json", "{\"erro\":\"captura indisponível\"}".getBytes(StandardCharsets.UTF_8));
                else responder(out, 200, "image/jpeg", jpg);
                return;
            }
            JSONObject r;
            try { r = rotear(rota, q); } catch (Exception e) { r = new JSONObject().put("ok", false).put("erro", String.valueOf(e)); }
            responder(out, 200, "application/json", r.toString().getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {}
    }

    private static void responder(OutputStream out, int cod, String tipo, byte[] corpo) throws Exception {
        String cab = "HTTP/1.1 " + cod + (cod == 200 ? " OK" : " ERRO") + "\r\nContent-Type: " + tipo + "; charset=utf-8\r\nContent-Length: "
            + corpo.length + "\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n";
        out.write(cab.getBytes(StandardCharsets.UTF_8));
        out.write(corpo);
        out.flush();
    }

    private static int num(Map<String, String> q, String k, int pad) {
        try { return (int) Math.round(Double.parseDouble(q.get(k))); } catch (Exception e) { return pad; }
    }

    JSONObject rotear(String rota, Map<String, String> q) throws Exception {
        switch (rota) {
            case "/pedir": {                                   // PC -> Friday LOCAL do celular (as duas cooperam quando ligadas)
                String t = q.get("t2") == null ? "" : q.get("t2");
                return new JSONObject().put("ok", true).put("resposta", Cerebro.get(this).pedir(t, "pc"));
            }
            case "/voz_cfg": {                                 // teste/ajuste: passos (qualidade x tempo) e XNNPACK
                android.content.SharedPreferences.Editor ed = getSharedPreferences("friday_local", MODE_PRIVATE).edit();
                if (q.get("passos") != null) ed.putInt("voz_passos", num(q, "passos", 5));
                if (q.get("xnn") != null) ed.putBoolean("voz_xnn", "1".equals(q.get("xnn")));
                if (q.get("voz") != null) ed.putString("voz", q.get("voz"));
                ed.commit(); Voz.get(this).recarregar(); return ok(true);
            }
            case "/voz_teste": {                               // teste do verificador de voz com um WAV 16 kHz em files/
                java.io.File f = new java.io.File(getExternalFilesDir(null), q.get("arq") == null ? "teste.wav" : q.get("arq"));
                byte[] w = java.nio.file.Files.readAllBytes(f.toPath());
                short[] pcm = new short[(w.length - 44) / 2];
                java.nio.ByteBuffer.wrap(w, 44, w.length - 44).order(java.nio.ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm);
                return new JSONObject().put("ok", true).put("score", new Ouvido(this).score(pcm));
            }
            case "/terminal":                                  // comando no Termux do celular (MODO DEV; só pela ponte com token)
                return new JSONObject().put("ok", true).put("saida", Dev.rodar(this, q.get("cmd") == null ? "true" : q.get("cmd"), num(q, "s", 120)));
            case "/flutuante": {                               // telas flutuantes (teste/uso pelo PC): tipo=agenda|bolha|texto
                String tp = q.get("tipo") == null ? "texto" : q.get("tipo");
                return new JSONObject().put("ok", true).put("msg", Ferramentas.flutuar(this, tp, q.get("titulo"), q.get("txt")));
            }
            case "/ide_cmd": {                                 // IDE do MODO DEV: iniciar|parar|pausar|continuar|mostrar|esconder
                String ac = q.get("acao") == null ? "mostrar" : q.get("acao");
                switch (ac) {
                    case "iniciar": return new JSONObject().put("ok", true).put("msg", Ide.iniciar(this, q.get("obj"), q.get("pasta")));
                    case "parar": Ide.parar(); break;
                    case "pausar": Ide.pausar(true); break;
                    case "continuar": Ide.pausar(false); break;
                    case "esconder": Flutuante.ide(this, false); break;
                    default: Flutuante.ide(this, true);
                }
                return new JSONObject().put("ok", true).put("estado", Ide.estado()).put("rodada", Ide.rodada());
            }
            case "/falar": Voz.get(this).falar(q.get("txt") == null ? "" : q.get("txt")); return ok(true);
            case "/log": {                                     // diagnóstico pela ponte (sem ADB): log do próprio app
                Process pr = Runtime.getRuntime().exec(new String[]{"logcat", "-d", "-v", "time", "-t", String.valueOf(num(q, "n", 120)),
                    "--pid=" + android.os.Process.myPid()});
                String txt = new String(pr.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
                return new JSONObject().put("ok", true).put("log", txt.length() > 60000 ? txt.substring(txt.length() - 60000) : txt);
            }
            case "/teste_stt": {                               // diagnóstico: passa files/teste/<arq> (PCM16 16 kHz mono) pelo reconhecimento real
                java.io.File f = new java.io.File(new java.io.File(getExternalFilesDir(null), "teste"), String.valueOf(q.get("arq")).replaceAll("[^A-Za-z0-9_.-]", ""));
                byte[] b = java.nio.file.Files.readAllBytes(f.toPath());
                short[] pcm = new short[b.length / 2];
                for (int k = 0; k < pcm.length; k++) pcm[k] = (short) ((b[2 * k] & 0xff) | (b[2 * k + 1] << 8));
                final String[] r = {"", ""};
                final java.util.concurrent.CountDownLatch fim = new java.util.concurrent.CountDownLatch(1);
                long t0 = System.currentTimeMillis();
                Voz.Ouviu cb = new Voz.Ouviu() {
                    @Override public void texto(String t, boolean parcial) { if (!parcial) { r[0] = t; fim.countDown(); } }
                    @Override public void erro(String e) { r[1] = e; fim.countDown(); }
                };
                try { Voz.variante = Integer.parseInt(String.valueOf(q.get("var"))); } catch (Exception e) { Voz.variante = 0; }
                if ("pc".equals(q.get("motor"))) Voz.get(this).transcreverNoPc(pcm, cb);
                else if ("auto".equals(q.get("motor"))) Voz.get(this).transcrever(pcm, cb);
                else Voz.get(this).reconhecerAudio(pcm, cb);
                fim.await(25, java.util.concurrent.TimeUnit.SECONDS);
                return new JSONObject().put("texto", r[0]).put("erro", r[1]).put("ms", System.currentTimeMillis() - t0).put("motor", Voz.ultimoMotor);
            }   // voz da Friday (Supertonic F5)
            case "/tocar_texto": return tocarTexto(q.get("txt") == null ? "" : q.get("txt"));
            case "/rolar": return rolar("cima".equals(q.get("dir")));
            case "/estado": return estado();
            case "/modelo": {                                  // cérebro local: lista instalados ou troca (?nome=arquivo.gguf) e carrega
                Cerebro cb = Cerebro.get(this);
                String nome = q.get("nome");
                JSONObject r = new JSONObject();
                if (nome != null && !nome.isEmpty()) {
                    if (!new java.io.File(cb.pasta(), nome).exists()) return r.put("ok", false).put("erro", "não instalado: " + nome);
                    cb.trocarModelo(nome);
                    new Thread(cb::preparar).start();          // carregar 1-2 GB leva segundos: não segura a ponte
                    r.put("carregando", nome);
                }
                org.json.JSONArray l = new org.json.JSONArray();
                for (String m : cb.modelos()) l.put(m);
                return r.put("ok", true).put("atual", cb.modelo()).put("instalados", l);
            }
            case "/acordar": return acordar();
            case "/desbloquear": return desbloquear(q.get("pin"));
            case "/global": return global(q.get("a"));
            case "/toque": {
                int ms = Math.max(40, Math.min(3000, num(q, "ms", 60)));
                return ok(gesto(num(q, "x", -1), num(q, "y", -1), num(q, "x", -1), num(q, "y", -1), ms));
            }
            case "/arrastar":
                return ok(gesto(num(q, "x0", -1), num(q, "y0", -1), num(q, "x1", -1), num(q, "y1", -1), Math.max(80, Math.min(3000, num(q, "ms", 350)))));
            case "/texto": return texto(q.get("t") == null ? "" : q.get("t"));
            case "/abrir": return abrir(q.get("nome") == null ? "" : q.get("nome"));
            case "/apps": {
                JSONArray a = new JSONArray();
                for (String[] ap : apps()) a.put(new JSONObject().put("nome", ap[0]).put("pacote", ap[1]));
                return new JSONObject().put("ok", true).put("apps", a);
            }
            case "/arvore": return new JSONObject().put("ok", true).put("itens", arvore(250));
            case "/manter": manterAcesa(Math.max(10, Math.min(3600, num(q, "s", 600)))); return estado();
            case "/soltar": soltar(); return estado();
            case "/transmitir": return transmitir(num(q, "fps", 60), num(q, "w", 720), num(q, "kbps", 6000));
            case "/parar_transmissao": {
                Intent i = new Intent(this, Transmissao.class); stopService(i);
                return new JSONObject().put("ok", true);
            }
            default: return new JSONObject().put("ok", false).put("erro", "rota desconhecida");
        }
    }

    private static JSONObject ok(boolean b) throws Exception { return new JSONObject().put("ok", b); }

    // ------------------------------------------------------------------ estado da tela
    private boolean telaAcesa() { return ((PowerManager) getSystemService(POWER_SERVICE)).isInteractive(); }
    private boolean bloqueado() { return ((KeyguardManager) getSystemService(KEYGUARD_SERVICE)).isKeyguardLocked(); }

    private JSONObject estado() throws Exception {
        DisplayMetrics m = new DisplayMetrics();
        ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(m);
        AccessibilityNodeInfo raiz = getRootInActiveWindow();
        return new JSONObject().put("ok", true).put("tela", telaAcesa()).put("bloqueado", bloqueado())
            .put("seguro", ((KeyguardManager) getSystemService(KEYGUARD_SERVICE)).isDeviceSecure())
            .put("w", m.widthPixels).put("h", m.heightPixels).put("manter", manter != null && manter.isHeld())
            .put("app", raiz != null && raiz.getPackageName() != null ? raiz.getPackageName().toString() : "")
            .put("versao", BuildConfigVersao.NOME);
    }

    // ------------------------------------------------------------------ acender a tela
    @SuppressWarnings("deprecation")
    private JSONObject acordar() throws Exception {
        if (!telaAcesa()) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            PowerManager.WakeLock wl = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP
                | PowerManager.ON_AFTER_RELEASE, "friday:acordar");
            wl.acquire(8000);
        }
        // activity transparente com turnScreenOn + pede o teclado do PIN (o serviço de acessibilidade pode abrir activity em 2º plano)
        Intent i = new Intent(this, Acordar.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION
            | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS);
        startActivity(i);
        for (int k = 0; k < 25 && !telaAcesa(); k++) Thread.sleep(100);
        return estado();
    }

    @SuppressWarnings("deprecation")
    private synchronized void manterAcesa(int seg) {
        soltar();
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        manter = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ON_AFTER_RELEASE, "friday:manter");
        manter.acquire(seg * 1000L);
    }

    private synchronized void soltar() {
        try { if (manter != null && manter.isHeld()) manter.release(); } catch (Exception ignored) {}
        manter = null;
    }

    // ------------------------------------------------------------------ desbloquear (PIN nos botões reais do teclado)
    private static final Pattern DIGITO = Pattern.compile("^\\s*(\\d)(\\s.*)?$", Pattern.DOTALL);
    private static final Pattern ENTER = Pattern.compile("(?i)^(enter|entrar|ok|confirmar|conclu[ií]do|done|desbloquear)$");

    private JSONObject desbloquear(String pin) throws Exception {
        if (pin == null || !pin.matches("\\d{4,16}")) return new JSONObject().put("ok", false).put("erro", "PIN inválido");
        if (!telaAcesa()) acordar();
        if (!bloqueado()) return estado().put("ok", true).put("msg", "já desbloqueado");
        Map<Character, AccessibilityNodeInfo> teclas = teclasPin();
        if (teclas.size() < 10) {                       // teclado ainda não apareceu: desliza para cima
            DisplayMetrics m = new DisplayMetrics();
            ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(m);
            gesto(m.widthPixels / 2, (int) (m.heightPixels * 0.85), m.widthPixels / 2, (int) (m.heightPixels * 0.30), 320);
            Thread.sleep(900);
            teclas = teclasPin();
        }
        if (teclas.size() < 10) {
            return new JSONObject().put("ok", false).put("erro", "teclado do PIN não encontrado").put("bloqueado", bloqueado())
                .put("itens", arvore(60));
        }
        for (char d : pin.toCharArray()) {
            AccessibilityNodeInfo n = teclas.get(d);
            if (!clicar(n)) return new JSONObject().put("ok", false).put("erro", "falhou ao tocar no dígito");
            Thread.sleep(140);
        }
        Thread.sleep(500);
        if (bloqueado()) {                              // sem confirmação automática: toca no Enter
            AccessibilityNodeInfo enter = acharEnter();
            if (enter != null) clicar(enter);
        }
        for (int k = 0; k < 20 && bloqueado(); k++) Thread.sleep(100);
        JSONObject r = estado();
        return r.put("ok", !bloqueado()).put("msg", bloqueado() ? "a tela de bloqueio continua" : "desbloqueado");
    }

    private List<AccessibilityNodeInfo> raizes() {
        List<AccessibilityNodeInfo> r = new ArrayList<>();
        try {
            for (AccessibilityWindowInfo w : getWindows()) { AccessibilityNodeInfo n = w.getRoot(); if (n != null) r.add(n); }
        } catch (Exception ignored) {}
        if (r.isEmpty()) { AccessibilityNodeInfo n = getRootInActiveWindow(); if (n != null) r.add(n); }
        return r;
    }

    private static String rotulo(AccessibilityNodeInfo n) {
        CharSequence t = n.getText(), d = n.getContentDescription();
        if (t != null && t.length() > 0) return t.toString();
        return d != null ? d.toString() : "";
    }

    private Map<Character, AccessibilityNodeInfo> teclasPin() {
        Map<Character, AccessibilityNodeInfo> m = new HashMap<>();
        for (AccessibilityNodeInfo r : raizes()) varrer(r, 0, n -> {
            Matcher mt = DIGITO.matcher(rotulo(n));
            if (!mt.matches()) return;
            String id = n.getViewIdResourceName() == null ? "" : n.getViewIdResourceName();
            if (id.contains("clock") || id.contains("time") || id.contains("date")) return;      // relógio da tela de bloqueio
            AccessibilityNodeInfo c = clicavel(n);
            if (c != null) m.putIfAbsent(mt.group(1).charAt(0), c);
        });
        return m;
    }

    private AccessibilityNodeInfo acharEnter() {
        final AccessibilityNodeInfo[] achado = {null};
        for (AccessibilityNodeInfo r : raizes()) varrer(r, 0, n -> {
            if (achado[0] != null) return;
            String id = n.getViewIdResourceName() == null ? "" : n.getViewIdResourceName();
            if (id.endsWith("key_enter") || ENTER.matcher(rotulo(n).trim()).matches()) achado[0] = clicavel(n);
        });
        return achado[0];
    }

    private static AccessibilityNodeInfo clicavel(AccessibilityNodeInfo n) {
        for (int k = 0; n != null && k < 4; k++, n = n.getParent()) if (n.isClickable() && n.isEnabled()) return n;
        return null;
    }

    private boolean clicar(AccessibilityNodeInfo n) throws Exception {
        if (n == null) return false;
        if (n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true;
        Rect b = new Rect(); n.getBoundsInScreen(b);
        return gesto(b.centerX(), b.centerY(), b.centerX(), b.centerY(), 60);
    }

    interface Visita { void v(AccessibilityNodeInfo n); }

    private static void varrer(AccessibilityNodeInfo n, int prof, Visita f) {
        if (n == null || prof > 40) return;
        f.v(n);
        for (int i = 0; i < n.getChildCount(); i++) varrer(n.getChild(i), prof + 1, f);
    }

    // ------------------------------------------------------------------ abrir app pelo nome (sem depender do launcher)
    private List<String[]> apps() {
        android.content.pm.PackageManager pm = getPackageManager();
        Intent i = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        List<String[]> r = new ArrayList<>();
        for (android.content.pm.ResolveInfo ri : pm.queryIntentActivities(i, 0))
            r.add(new String[]{String.valueOf(ri.loadLabel(pm)), ri.activityInfo.packageName});
        return r;
    }

    public static String limparNomeApp(String s) {
        if (s == null) return "";
        String t = java.text.Normalizer.normalize(s, java.text.Normalizer.Form.NFD).replaceAll("\\p{M}", "")
            .toLowerCase(java.util.Locale.ROOT).trim();
        t = t.replaceAll("^(?:abrir|abra|abre|inicie|iniciar|inicia|execute|executar|roda|rodar|lancar|lance|acessar|acesse|ver|mostrar|mostre)\\s+", "");
        t = t.replaceAll("^(?:o|a|os|as|um|uma|uns|umas|meu|minha|meus|minhas|o\\s+meu|a\\s+minha)\\s+", "");
        t = t.replaceAll("^(?:aplicativo|aplicacao|app|programa|ferramenta)\\s+(?:de|do|da|dos|das)?\\s*", "");
        return t.replaceAll("[^a-z0-9]", "");
    }

    private static boolean ehNavegador(String alvo) {
        return alvo.equals("navegador") || alvo.contains("navegador") || alvo.equals("browser") || alvo.contains("browser")
            || alvo.equals("internet") || alvo.equals("web") || alvo.equals("chrome") || alvo.contains("chrome")
            || alvo.equals("chromium") || alvo.equals("googlechrome") || alvo.equals("google")
            || alvo.equals("firefox") || alvo.equals("edge") || alvo.equals("brave") || alvo.equals("opera");
    }

    private JSONObject abrirNavegador() throws Exception {
        android.content.pm.PackageManager pm = getPackageManager();
        String[] pkgs = {"com.android.chrome", "com.chrome.beta", "org.mozilla.firefox", "com.sec.android.app.sbrowser",
            "com.android.browser", "com.brave.browser", "com.opera.browser", "com.microsoft.emmx", "com.mi.globalbrowser"};
        for (String p : pkgs) {
            Intent i = pm.getLaunchIntentForPackage(p);
            if (i != null) {
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                return new JSONObject().put("ok", true).put("app", "Navegador").put("pacote", p);
            }
        }
        Intent view = new Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://www.google.com/"));
        view.addCategory(Intent.CATEGORY_BROWSABLE);
        view.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (view.resolveActivity(pm) != null) {
            startActivity(view);
            return new JSONObject().put("ok", true).put("app", "Navegador").put("pacote", "intent");
        }
        return new JSONObject().put("ok", false).put("erro", "não achei um navegador que responda a https");
    }

    private static String norm(String s) {
        return java.text.Normalizer.normalize(s == null ? "" : s, java.text.Normalizer.Form.NFD).replaceAll("\\p{M}", "")
            .toLowerCase(java.util.Locale.ROOT).replaceAll("[^a-z0-9]", "");
    }

    private JSONObject abrirPorCategoria(String alvo) {
        android.content.pm.PackageManager pm = getPackageManager();
        try {
            if (alvo.equals("calculadora") || alvo.contains("calculadora") || alvo.equals("calc")) {
                String[] calcPkgs = {"com.google.android.calculator", "com.sec.android.app.popupcalculator",
                    "com.android.calculator2", "com.motorola.calculator", "com.miui.calculator", "com.oneplus.calculator"};
                for (String p : calcPkgs) {
                    Intent i = pm.getLaunchIntentForPackage(p);
                    if (i != null) {
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                        return new JSONObject().put("ok", true).put("app", "Calculadora").put("pacote", p);
                    }
                }
                Intent ci = new Intent();
                ci.setAction(Intent.ACTION_MAIN);
                ci.addCategory(Intent.CATEGORY_APP_CALCULATOR);
                ci.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                if (ci.resolveActivity(pm) != null) {
                    startActivity(ci);
                    return new JSONObject().put("ok", true).put("app", "Calculadora").put("pacote", "categoria");
                }
            }
            if (alvo.equals("camera") || alvo.contains("camera") || alvo.equals("foto") || alvo.equals("tirarfoto")) {
                Intent cam = new Intent(android.provider.MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA);
                cam.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                if (cam.resolveActivity(pm) != null) {
                    startActivity(cam);
                    return new JSONObject().put("ok", true).put("app", "Câmera").put("pacote", "camera");
                }
            }
            if (alvo.equals("galeria") || alvo.contains("galeria") || alvo.equals("fotos") || alvo.equals("albuns")) {
                String[] galPkgs = {"com.google.android.apps.photos", "com.sec.android.gallery3d", "com.motorola.gallery", "com.android.gallery3d"};
                for (String p : galPkgs) {
                    Intent i = pm.getLaunchIntentForPackage(p);
                    if (i != null) {
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                        return new JSONObject().put("ok", true).put("app", "Galeria").put("pacote", p);
                    }
                }
                Intent gal = new Intent(Intent.ACTION_VIEW);
                gal.setType("image/*");
                gal.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                if (gal.resolveActivity(pm) != null) {
                    startActivity(gal);
                    return new JSONObject().put("ok", true).put("app", "Galeria").put("pacote", "intent");
                }
            }
            if (alvo.equals("configuracoes") || alvo.contains("config") || alvo.equals("ajustes") || alvo.equals("definicoes")) {
                Intent set = new Intent(android.provider.Settings.ACTION_SETTINGS);
                set.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(set);
                return new JSONObject().put("ok", true).put("app", "Configurações").put("pacote", "settings");
            }
            if (alvo.equals("arquivos") || alvo.contains("arquivo") || alvo.equals("meusarquivos") || alvo.equals("downloads")) {
                String[] arqPkgs = {"com.google.android.apps.nbu.files", "com.google.android.documentsui", "com.sec.android.app.myfiles"};
                for (String p : arqPkgs) {
                    Intent i = pm.getLaunchIntentForPackage(p);
                    if (i != null) {
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                        return new JSONObject().put("ok", true).put("app", "Arquivos").put("pacote", p);
                    }
                }
                Intent arq = new Intent(android.app.DownloadManager.ACTION_VIEW_DOWNLOADS);
                arq.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                if (arq.resolveActivity(pm) != null) {
                    startActivity(arq);
                    return new JSONObject().put("ok", true).put("app", "Arquivos").put("pacote", "downloads");
                }
            }
            if (alvo.equals("relogio") || alvo.contains("relogio") || alvo.equals("alarme") || alvo.equals("despertador")) {
                String[] clkPkgs = {"com.google.android.deskclock", "com.sec.android.app.clockpackage", "com.android.deskclock"};
                for (String p : clkPkgs) {
                    Intent i = pm.getLaunchIntentForPackage(p);
                    if (i != null) {
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                        return new JSONObject().put("ok", true).put("app", "Relógio").put("pacote", p);
                    }
                }
                Intent clk = new Intent(android.provider.AlarmClock.ACTION_SHOW_ALARMS);
                clk.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                if (clk.resolveActivity(pm) != null) {
                    startActivity(clk);
                    return new JSONObject().put("ok", true).put("app", "Relógio").put("pacote", "alarme");
                }
            }
            if (alvo.equals("contatos") || alvo.contains("contato")) {
                Intent cont = new Intent(Intent.ACTION_VIEW, android.provider.ContactsContract.Contacts.CONTENT_URI);
                cont.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                if (cont.resolveActivity(pm) != null) {
                    startActivity(cont);
                    return new JSONObject().put("ok", true).put("app", "Contatos").put("pacote", "contatos");
                }
            }
            if (alvo.equals("telefone") || alvo.contains("telefone") || alvo.equals("discar") || alvo.equals("chamadas")) {
                Intent tel = new Intent(Intent.ACTION_DIAL);
                tel.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(tel);
                return new JSONObject().put("ok", true).put("app", "Telefone").put("pacote", "dial");
            }
            if (alvo.equals("mensagens") || alvo.contains("mensagem") || alvo.equals("sms")) {
                String[] msgPkgs = {"com.google.android.apps.messaging", "com.samsung.android.messaging"};
                for (String p : msgPkgs) {
                    Intent i = pm.getLaunchIntentForPackage(p);
                    if (i != null) {
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                        return new JSONObject().put("ok", true).put("app", "Mensagens").put("pacote", p);
                    }
                }
            }
            if (alvo.equals("email") || alvo.contains("email") || alvo.equals("gmail") || alvo.equals("correio")) {
                Intent em = pm.getLaunchIntentForPackage("com.google.android.gm");
                if (em != null) {
                    em.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(em);
                    return new JSONObject().put("ok", true).put("app", "Gmail").put("pacote", "com.google.android.gm");
                }
            }
            if (alvo.equals("musica") || alvo.contains("musica") || alvo.equals("spotify")) {
                String[] musPkgs = {"com.spotify.music", "com.google.android.apps.youtube.music", "com.sec.android.app.music"};
                for (String p : musPkgs) {
                    Intent i = pm.getLaunchIntentForPackage(p);
                    if (i != null) {
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                        return new JSONObject().put("ok", true).put("app", "Música").put("pacote", p);
                    }
                }
            }
            if (alvo.equals("mapas") || alvo.contains("mapa") || alvo.equals("gps")) {
                Intent maps = pm.getLaunchIntentForPackage("com.google.android.apps.maps");
                if (maps != null) {
                    maps.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(maps);
                    return new JSONObject().put("ok", true).put("app", "Google Maps").put("pacote", "com.google.android.apps.maps");
                }
            }
            if (alvo.equals("playstore") || alvo.contains("playstore") || alvo.equals("loja") || alvo.equals("googleplay")) {
                Intent ps = pm.getLaunchIntentForPackage("com.android.vending");
                if (ps != null) {
                    ps.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(ps);
                    return new JSONObject().put("ok", true).put("app", "Google Play Store").put("pacote", "com.android.vending");
                }
            }
            if (alvo.equals("whatsapp") || alvo.contains("whatsapp") || alvo.equals("zap") || alvo.equals("zapzap")) {
                Intent wa = pm.getLaunchIntentForPackage("com.whatsapp");
                if (wa != null) {
                    wa.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(wa);
                    return new JSONObject().put("ok", true).put("app", "WhatsApp").put("pacote", "com.whatsapp");
                }
            }
            if (alvo.equals("youtube") || alvo.contains("youtube")) {
                Intent yt = pm.getLaunchIntentForPackage("com.google.android.youtube");
                if (yt != null) {
                    yt.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(yt);
                    return new JSONObject().put("ok", true).put("app", "YouTube").put("pacote", "com.google.android.youtube");
                }
            }
        } catch (Exception ignored) {}
        return null;
    }

    private JSONObject abrir(String nome) throws Exception {
        String alvoLimpo = limparNomeApp(nome);
        String alvo = norm(nome);
        if (alvoLimpo.isEmpty() && alvo.isEmpty()) return new JSONObject().put("ok", false).put("erro", "nome vazio");
        String chave = alvoLimpo.isEmpty() ? alvo : alvoLimpo;

        if (ehNavegador(chave) || ehNavegador(alvo)) return abrirNavegador();

        if (chave.equals("agenda") || chave.equals("calendario") || chave.equals("minhaagenda") || chave.contains("agendafriday")) {
            Intent i = new Intent(this, MainActivity.class)
                .putExtra("aba", "agenda")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            startActivity(i);
            try { Flutuante.agendaPainel(this); } catch (Exception ignored) {}
            return new JSONObject().put("ok", true).put("app", "Agenda da Sexta-Feira").put("pacote", getPackageName());
        }
        if (chave.equals("dev") || chave.equals("mododev") || chave.equals("ide")) {
            Intent i = new Intent(this, MainActivity.class)
                .putExtra("aba", "dev")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            startActivity(i);
            try { Flutuante.ide(this, true); } catch (Exception ignored) {}
            return new JSONObject().put("ok", true).put("app", "Modo Dev IDE").put("pacote", getPackageName());
        }

        JSONObject cat = abrirPorCategoria(chave);
        if (cat != null && cat.optBoolean("ok")) return cat;

        String[] melhor = null; int nota = 0;
        for (String[] ap : apps()) {
            String n = norm(ap[0]), nl = limparNomeApp(ap[0]), pk = ap[1].toLowerCase(java.util.Locale.ROOT);
            int v = (n.equals(chave) || nl.equals(chave)) ? 100 :
                    (n.startsWith(chave) || nl.startsWith(chave)) ? 80 :
                    (n.contains(chave) || nl.contains(chave)) ? 60 :
                    pk.contains(chave) ? 50 :
                    (chave.contains(n) && n.length() >= 4) ? 40 : 0;
            if (v > nota) { nota = v; melhor = ap; }
        }
        if (melhor == null) {
            JSONObject cat2 = abrirPorCategoria(alvo);
            if (cat2 != null && cat2.optBoolean("ok")) return cat2;
            return new JSONObject().put("ok", false).put("erro", "app não encontrado: " + nome);
        }
        Intent i = getPackageManager().getLaunchIntentForPackage(melhor[1]);
        if (i == null) return new JSONObject().put("ok", false).put("erro", "app sem tela inicial: " + melhor[0]);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
        startActivity(i);
        return new JSONObject().put("ok", true).put("app", melhor[0]).put("pacote", melhor[1]);
    }

    // ------------------------------------------------------------------ mexer
    private JSONObject global(String a) throws Exception {
        Map<String, Integer> m = new HashMap<>();
        m.put("voltar", GLOBAL_ACTION_BACK); m.put("inicio", GLOBAL_ACTION_HOME); m.put("recentes", GLOBAL_ACTION_RECENTS);
        m.put("notificacoes", GLOBAL_ACTION_NOTIFICATIONS); m.put("rapidas", GLOBAL_ACTION_QUICK_SETTINGS);
        m.put("bloquear", GLOBAL_ACTION_LOCK_SCREEN); m.put("energia", GLOBAL_ACTION_POWER_DIALOG);
        Integer g = m.get(a == null ? "" : a);
        if (g == null) return new JSONObject().put("ok", false).put("erro", "ação global desconhecida: " + a);
        return ok(performGlobalAction(g));
    }

    public boolean toque(int x, int y) {
        try { return gesto(x, y, x, y, 70); }
        catch (Exception e) { return false; }
    }

    private boolean gesto(int x0, int y0, int x1, int y1, int ms) throws Exception {
        if (x0 < 0 || y0 < 0 || x1 < 0 || y1 < 0) return false;
        Path p = new Path(); p.moveTo(x0, y0); if (x1 != x0 || y1 != y0) p.lineTo(x1, y1); else p.lineTo(x0 + 0.5f, y0 + 0.5f);
        GestureDescription g = new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(p, 0, ms)).build();
        CountDownLatch fim = new CountDownLatch(1);
        AtomicBoolean ok = new AtomicBoolean(false);
        main.post(() -> {
            boolean aceito = dispatchGesture(g, new GestureResultCallback() {
                @Override public void onCompleted(GestureDescription d) { ok.set(true); fim.countDown(); }
                @Override public void onCancelled(GestureDescription d) { fim.countDown(); }
            }, null);
            if (!aceito) fim.countDown();
        });
        fim.await(ms + 2500, TimeUnit.MILLISECONDS);
        return ok.get();
    }

    private JSONObject texto(String t) throws Exception {
        AccessibilityNodeInfo f = null;
        for (AccessibilityNodeInfo r : raizes()) { f = r.findFocus(AccessibilityNodeInfo.FOCUS_INPUT); if (f != null) break; }
        if (f == null) return new JSONObject().put("ok", false).put("erro", "nenhum campo de texto em foco");
        Bundle b = new Bundle();
        b.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, t);
        return ok(f.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, b));
    }

    private JSONArray arvore(int max) {
        JSONArray a = new JSONArray();
        for (AccessibilityNodeInfo r : raizes()) varrer(r, 0, n -> {
            if (a.length() >= max || !n.isVisibleToUser()) return;
            String t = rotulo(n).trim();
            if (t.isEmpty() && !n.isEditable()) return;
            Rect b = new Rect(); n.getBoundsInScreen(b);
            if (b.width() <= 0 || b.height() <= 0) return;
            try {
                a.put(new JSONObject().put("t", t.length() > 120 ? t.substring(0, 120) : t).put("x", b.centerX()).put("y", b.centerY())
                    .put("clique", n.isClickable() || clicavel(n) != null).put("campo", n.isEditable()));
            } catch (Exception ignored) {}
        });
        return a;
    }

    /** toca no elemento visível cujo texto/descrição combina com `t` (exato > começa > contém). */
    JSONObject tocarTexto(String t) throws Exception {
        String alvo = norm(t);
        if (alvo.isEmpty()) return new JSONObject().put("ok", false).put("erro", "texto vazio");
        final AccessibilityNodeInfo[] melhor = {null};
        final int[] nota = {0};
        for (AccessibilityNodeInfo r : raizes()) varrer(r, 0, n -> {
            if (!n.isVisibleToUser()) return;
            String l = norm(rotulo(n));
            if (l.isEmpty()) return;
            int v = l.equals(alvo) ? 100 : l.startsWith(alvo) ? 80 : l.contains(alvo) ? 60 : alvo.contains(l) && l.length() >= 4 ? 40 : 0;
            if (v > nota[0] && (clicavel(n) != null || n.isClickable())) { nota[0] = v; melhor[0] = n; }
        });
        if (melhor[0] == null) return new JSONObject().put("ok", false).put("erro", "não achei '" + t + "' na tela");
        if (norm(rotulo(melhor[0])).contains("friday"))      // 16/10: ela se desligou (Configurações) e abriu o próprio atalho
            return new JSONObject().put("ok", false).put("erro", "bloqueado: não toco em mim mesma (F.R.I.D.A.Y.)");
        AccessibilityNodeInfo c = clicavel(melhor[0]);
        return new JSONObject().put("ok", clicar(c != null ? c : melhor[0])).put("tocou", rotulo(melhor[0]));
    }

    JSONObject fecharAviso() throws Exception {
        final AccessibilityNodeInfo[] alvo = {null};
        final String[] nomeAlvo = {""};
        for (AccessibilityNodeInfo r : raizes()) {
            varrer(r, 0, n -> {
                if (alvo[0] != null || !n.isVisibleToUser()) return;
                String rot = norm(rotulo(n));
                String id = n.getViewIdResourceName() == null ? "" : n.getViewIdResourceName().toLowerCase(java.util.Locale.ROOT);
                if (rot.contains("friday")) return; // não toca em si mesma
                boolean fechar = false;
                if (rot.equals("x") || rot.equals("×") || rot.equals("✕") || rot.equals("close") || rot.equals("fechar")
                    || rot.equals("fechar anuncio") || rot.equals("close ad") || rot.equals("pular anuncio")
                    || rot.equals("skip ad") || rot.equals("pular") || rot.equals("skip")
                    || rot.equals("dispensar") || rot.equals("dismiss") || rot.equals("agora nao")
                    || rot.equals("not now") || rot.equals("recusar") || rot.equals("rejeitar")
                    || rot.equals("aceitar tudo") || rot.equals("accept all") || rot.equals("aceitar cookies")
                    || rot.equals("aceitar") || rot.equals("concordo") || rot.equals("entendi")
                    || rot.equals("continuar para o site") || rot.equals("prosseguir")
                    || rot.startsWith("fechar ") || rot.startsWith("pular ") || rot.startsWith("dispensar ")) {
                    fechar = true;
                } else if (!id.isEmpty() && (id.contains("close") || id.contains("dismiss") || id.contains("skip_ad")
                        || id.contains("btn_close") || id.contains("ad_close") || id.contains("cancel_ad") || id.contains("close_button"))) {
                    fechar = true;
                }
                if (fechar && (n.isClickable() || clicavel(n) != null || n.getViewIdResourceName() != null)) {
                    alvo[0] = n;
                    nomeAlvo[0] = rot.isEmpty() ? id : rot;
                }
            });
            if (alvo[0] != null) break;
        }
        if (alvo[0] != null) {
            AccessibilityNodeInfo c = clicavel(alvo[0]);
            boolean ok = clicar(c != null ? c : alvo[0]);
            if (ok) Thread.sleep(250);
            return new JSONObject().put("ok", ok).put("fechou", nomeAlvo[0]);
        }
        String[] alvos = {"fechar anúncio", "close ad", "pular anúncio", "skip ad", "dispensar", "dismiss", "aceitar tudo", "accept all", "aceitar cookies", "aceitar", "concordo", "entendi", "agora não", "fechar", "pular", "skip", "x"};
        for (String a : alvos) {
            try {
                JSONObject r = tocarTexto(a);
                if (r != null && r.optBoolean("ok")) return r;
            } catch (Exception ignored) {}
        }
        return new JSONObject().put("ok", false);
    }

    JSONObject rolar(boolean cima) throws Exception {
        DisplayMetrics m = new DisplayMetrics();
        ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(m);
        int x = m.widthPixels / 2, a = (int) (m.heightPixels * 0.70), b = (int) (m.heightPixels * 0.30);
        return ok(cima ? gesto(x, b, x, a, 350) : gesto(x, a, x, b, 350));
    }

    /** texto do que está na tela, compacto (para o cérebro local "ver" o app aberto) */
    String telaTexto(int max) {
        StringBuilder sb = new StringBuilder();
        JSONArray a = arvore(max);
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = a.optJSONObject(i);
            if (o == null) continue;
            sb.append(o.optBoolean("campo") ? "[campo] " : o.optBoolean("clique") ? "[botão] " : "").append(o.optString("t")).append('\n');
        }
        AccessibilityNodeInfo raiz = getRootInActiveWindow();
        String app = raiz != null && raiz.getPackageName() != null ? raiz.getPackageName().toString() : "?";
        return "app aberto: " + app + "\n" + sb;
    }

    /** analisa o conteúdo visível em busca de falhas, erros ou travamentos no celular */
    String detectarDificuldade() {
        String t = telaTexto(100).toLowerCase();
        if (t.contains("erro") || t.contains("falhou") || t.contains("parou") || t.contains("fechou inesperadamente") || t.contains("anr") || t.contains("crash")) {
            return "DIFICULDADE DETECTADA: Erro ou falha em aplicativo exibido na tela do celular.";
        }
        if (t.contains("sem conexão") || t.contains("sem internet") || t.contains("falha de rede") || t.contains("offline") || t.contains("network error")) {
            return "DIFICULDADE DETECTADA: Falha de conexão de rede ou internet.";
        }
        if (t.contains("obrigatório") || t.contains("inválido") || t.contains("preencha este campo") || t.contains("required")) {
            return "DIFICULDADE DETECTADA: Validação de campo ou formulário pendente na tela.";
        }
        return "Nenhuma dificuldade ou erro detectado na tela do celular.";
    }

    // ------------------------------------------------------------------ transmissão de tela (H.264) ao vivo
    private static final Pattern TELA_INTEIRA = Pattern.compile("(?i).*(tela inteira|a tela inteira|entire screen).*");
    private static final Pattern BOTAO_INICIAR = Pattern.compile(
        "(?i)^(iniciar|iniciar agora|come[çc]ar agora|start|start now|compartilhar tela|share screen)$");

    private JSONObject transmitir(int fps, int w, int kbps) throws Exception {
        fps = Math.max(10, Math.min(60, fps <= 0 ? 60 : fps));
        w = Math.max(240, Math.min(1080, w <= 0 ? 720 : w));
        kbps = Math.max(1000, Math.min(20000, kbps <= 0 ? 6000 : kbps));
        if (Transmissao.ativo) {
            return new JSONObject().put("ok", true).put("porta", 8792)
                .put("w", Transmissao.W).put("h", Transmissao.H).put("fps", Transmissao.FPS);
        }
        // pede a permissão de captura via activity; o diálogo do sistema é aceito por nós
        Intent i = new Intent(this, PedirTela.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
            | Intent.FLAG_ACTIVITY_NO_ANIMATION | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS);
        i.putExtra("fps", fps).putExtra("w", w).putExtra("kbps", kbps);
        startActivity(i);
        aceitarDialogoCaptura();
        for (int k = 0; k < 120 && !Transmissao.ativo; k++) Thread.sleep(100);   // até 12 s
        if (Transmissao.ativo) {
            return new JSONObject().put("ok", true).put("porta", 8792)
                .put("w", Transmissao.W).put("h", Transmissao.H).put("fps", Transmissao.FPS);
        }
        return new JSONObject().put("ok", false).put("erro", "transmissão não iniciou");
    }

    /** Aceita sozinho o diálogo "Compartilhar/gravar a tela": seleciona "Tela inteira" e toca em "Iniciar". */
    private void aceitarDialogoCaptura() {
        for (int k = 0; k < 40 && !Transmissao.ativo; k++) {                     // até 10 s (250 ms * 40)
            final boolean[] clicou = {false};
            for (AccessibilityNodeInfo r : raizes()) varrer(r, 0, n -> {
                if (clicou[0]) return;
                String lbl = rotulo(n).trim();
                if (TELA_INTEIRA.matcher(lbl).matches()) {                       // opção de tela inteira (spinner/lista)
                    AccessibilityNodeInfo c = clicavel(n);
                    if (c != null) try { clicar(c); } catch (Exception ignored) {}
                }
            });
            for (AccessibilityNodeInfo r : raizes()) varrer(r, 0, n -> {
                if (clicou[0]) return;
                if (BOTAO_INICIAR.matcher(rotulo(n).trim()).matches()) {
                    AccessibilityNodeInfo c = clicavel(n);
                    if (c != null) try { if (clicar(c)) clicou[0] = true; } catch (Exception ignored) {}
                }
            });
            if (clicou[0]) break;
            try { Thread.sleep(250); } catch (InterruptedException ignored) {}
        }
    }

    // ------------------------------------------------------------------ pulso: força 60 quadros/s na transmissão
    // O encoder da Motorola ignora KEY_REPEAT_PREVIOUS_FRAME_AFTER: com a tela parada o espelho não gera quadro nenhum.
    // Um ponto 1x1 quase transparente (alfa 1/255, invisível) redesenhado a cada vsync obriga o sistema a recompor a tela.
    private android.view.View pulso;

    void pulsar(boolean ligar) {
        main.post(() -> {
            android.view.WindowManager wm = (android.view.WindowManager) getSystemService(WINDOW_SERVICE);
            if (ligar && pulso == null) {
                pulso = new android.view.View(this) {
                    private boolean f;
                    @Override protected void onDraw(android.graphics.Canvas c) {
                        c.drawColor(f ? 0x01000000 : 0x02000000);
                        f = !f;
                        postInvalidateOnAnimation();
                    }
                };
                android.view.WindowManager.LayoutParams lp = new android.view.WindowManager.LayoutParams(1, 1,
                    android.view.WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                    android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | android.view.WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                        | android.view.WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                    android.graphics.PixelFormat.TRANSLUCENT);
                lp.gravity = android.view.Gravity.TOP | android.view.Gravity.START;
                try { wm.addView(pulso, lp); } catch (Exception e) { pulso = null; }
            } else if (!ligar && pulso != null) {
                try { wm.removeView(pulso); } catch (Exception ignored) {}
                pulso = null;
            }
        });
    }

    // ------------------------------------------------------------------ print (Android 11+), reduzido pela metade
    private byte[] tela() {
        if (Build.VERSION.SDK_INT < 30) return null;
        final byte[][] r = {null};
        CountDownLatch fim = new CountDownLatch(1);
        main.post(() -> takeScreenshot(Display.DEFAULT_DISPLAY, getMainExecutor(), new TakeScreenshotCallback() {
            @Override public void onSuccess(ScreenshotResult s) {
                try {
                    Bitmap hw = Bitmap.wrapHardwareBuffer(s.getHardwareBuffer(), s.getColorSpace());
                    Bitmap sw = hw.copy(Bitmap.Config.ARGB_8888, false);
                    Bitmap pq = Bitmap.createScaledBitmap(sw, sw.getWidth() / 2, sw.getHeight() / 2, true);
                    ByteArrayOutputStream o = new ByteArrayOutputStream();
                    pq.compress(Bitmap.CompressFormat.JPEG, 70, o);
                    r[0] = o.toByteArray();
                    s.getHardwareBuffer().close();
                } catch (Exception ignored) {}
                fim.countDown();
            }
            @Override public void onFailure(int e) { fim.countDown(); }
        }));
        try { fim.await(5, TimeUnit.SECONDS); } catch (InterruptedException ignored) {}
        return r[0];
    }

    /** chamado pela interface (JavaScript) para gravar o token que o PC usa. */
    static void salvarToken(Context c, String tok) {
        SharedPreferences.Editor e = c.getSharedPreferences("ponte", MODE_PRIVATE).edit();
        e.putString("tok", tok == null ? "" : tok.trim()).apply();
    }
}
