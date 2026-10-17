package dev.integra.friday;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.view.Surface;
import android.view.WindowManager;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CopyOnWriteArrayList;

/** Captura a tela (MediaProjection), codifica em H.264 (MediaCodec, baixa latência) e serve o fluxo Annex-B
 *  cru em TCP 0.0.0.0:8792 para os clientes do Tailscale/loopback que mandarem o token. O PC relaya para o holograma. */
public class Transmissao extends Service {
    static final int PORTA = 8792;
    static volatile boolean ativo;
    static volatile int W, H, FPS;

    private MediaProjection projecao;
    private MediaProjection.Callback projCb;
    private VirtualDisplay display;
    private MediaCodec codec;
    private Surface entrada;
    private Thread saida, aceitador;
    private ServerSocket srv;
    private volatile boolean rodando;
    private byte[] configBytes;                 // SPS/PPS guardado (BUFFER_FLAG_CODEC_CONFIG)
    private volatile byte[] ultimoChave;        // último quadro-chave: quem conecta vê imagem na hora
    private final CopyOnWriteArrayList<Cliente> clientes = new CopyOnWriteArrayList<>();
    private volatile long semClientesDesde;     // quando a lista de clientes esvaziou (0 = tem cliente)
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override public IBinder onBind(Intent i) { return null; }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        subirForeground();                       // startForeground sempre (exigido em até ~5 s de startForegroundService)
        if (ativo) return START_NOT_STICKY;
        if (intent == null) { parar(); return START_NOT_STICKY; }
        int resultCode = intent.getIntExtra("resultCode", 0);
        Intent data = intent.getParcelableExtra("data");
        int fps = intent.getIntExtra("fps", 60);
        int w = intent.getIntExtra("w", 720);
        int kbps = intent.getIntExtra("kbps", 6000);
        if (data == null) { parar(); return START_NOT_STICKY; }
        try { iniciar(resultCode, data, fps, w, kbps); }
        catch (Exception e) { parar(); }
        return START_NOT_STICKY;
    }

    private void subirForeground() {
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel("transmissao", "Transmissão de tela", NotificationManager.IMPORTANCE_LOW);
            ch.setShowBadge(false);
            nm.createNotificationChannel(ch);
        }
        Notification.Builder b = (Build.VERSION.SDK_INT >= 26)
            ? new Notification.Builder(this, "transmissao") : new Notification.Builder(this);
        Notification n = b.setContentTitle("F.R.I.D.A.Y.").setContentText("Espelhando a tela no PC")
            .setSmallIcon(android.R.drawable.ic_menu_view).setOngoing(true).build();
        // foreground ANTES de getMediaProjection (Android 14 exige o tipo mediaProjection)
        if (Build.VERSION.SDK_INT >= 29) startForeground(42, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
        else startForeground(42, n);
    }

    private void iniciar(int resultCode, Intent data, int fps, int w, int kbps) throws Exception {
        fps = Math.max(10, Math.min(60, fps <= 0 ? 60 : fps));
        w = Math.max(240, Math.min(1080, w <= 0 ? 720 : w));
        kbps = Math.max(1000, Math.min(20000, kbps <= 0 ? 6000 : kbps));

        DisplayMetrics m = new DisplayMetrics();
        ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(m);
        int realW = m.widthPixels, realH = m.heightPixels, dpi = m.densityDpi;

        int largura = w - (w % 2);                                   // par
        int altura = Math.round((float) largura * realH / realW);
        altura = Math.round(altura / 16f) * 16;                      // múltiplo de 16
        if (altura <= 0) altura = 16;
        W = largura; H = altura; FPS = fps;

        // codificador H.264 de baixa latência
        MediaFormat f = MediaFormat.createVideoFormat("video/avc", largura, altura);
        f.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
        f.setInteger(MediaFormat.KEY_BIT_RATE, kbps * 1000);
        f.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
        f.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
        f.setLong(MediaFormat.KEY_REPEAT_PREVIOUS_FRAME_AFTER, 1_000_000L / fps);   // tela parada segue em fps
        f.setInteger(MediaFormat.KEY_PRIORITY, 0);                   // tempo real
        f.setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0);               // sem B-frames
        try { f.setFloat(MediaFormat.KEY_OPERATING_RATE, fps); } catch (Exception ignored) {}
        if (Build.VERSION.SDK_INT >= 30) { try { f.setInteger(MediaFormat.KEY_LOW_LATENCY, 1); } catch (Exception ignored) {} }

        codec = MediaCodec.createEncoderByType("video/avc");
        codec.configure(f, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        entrada = codec.createInputSurface();
        codec.start();

        MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        projecao = mpm.getMediaProjection(resultCode, data);
        if (projecao == null) throw new IllegalStateException("sem projeção");
        // registra o callback ANTES de createVirtualDisplay (Android 14)
        projCb = new MediaProjection.Callback() { @Override public void onStop() { parar(); } };
        projecao.registerCallback(projCb, main);
        display = projecao.createVirtualDisplay("friday-tela", largura, altura, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, entrada, null, null);

        rodando = true;
        ativo = true;
        semClientesDesde = System.currentTimeMillis();
        saida = new Thread(this::lacoSaida, "friday-enc");
        saida.start();
        aceitador = new Thread(this::servir, "friday-tx-srv");
        aceitador.start();
        if (Acesso.inst != null) Acesso.inst.pulsar(true);         // 60 fps mesmo com a tela parada
    }

    // ------------------------------------------------------------------ laço do codificador -> clientes
    private void lacoSaida() {
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        while (rodando) {
            int idx;
            try { idx = codec.dequeueOutputBuffer(info, 10000); }
            catch (Exception e) { break; }
            if (idx < 0) {
                // sem cliente há 60 s: economiza bateria
                if (semClientesDesde != 0 && System.currentTimeMillis() - semClientesDesde > 60000) { parar(); break; }
                continue;
            }
            try {
                ByteBuffer buf = codec.getOutputBuffer(idx);
                if (buf != null && info.size > 0) {
                    buf.position(info.offset);
                    buf.limit(info.offset + info.size);
                    byte[] pacote = new byte[info.size];
                    buf.get(pacote);
                    if ((info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0) {
                        configBytes = pacote;                        // SPS/PPS: guarda, não envia aqui
                    } else {
                        if ((info.flags & MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0) ultimoChave = pacote;
                        for (Cliente c : clientes) c.enviar(pacote);
                    }
                }
            } catch (Exception ignored) {
            } finally {
                try { codec.releaseOutputBuffer(idx, false); } catch (Exception ignored) {}
            }
        }
    }

    private void pedirKeyframe() {
        try {
            Bundle b = new Bundle();
            b.putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0);
            codec.setParameters(b);
        } catch (Exception ignored) {}
    }

    // ------------------------------------------------------------------ servidor TCP 8792
    private void servir() {
        try {
            srv = new ServerSocket(PORTA, 8, InetAddress.getByName("0.0.0.0"));
            while (rodando) {
                Socket s;
                try { s = srv.accept(); } catch (Exception e) { break; }
                new Thread(() -> autenticar(s), "friday-tx-auth").start();
            }
        } catch (Exception ignored) {}
    }

    private void autenticar(Socket s) {
        try {
            if (!Acesso.ipPermitido(s.getInetAddress())) { s.close(); return; }
            s.setSoTimeout(3000);
            InputStream in = s.getInputStream();
            StringBuilder sb = new StringBuilder();
            int ch;
            while ((ch = in.read()) != -1 && ch != '\n' && sb.length() < 512) sb.append((char) ch);
            String tok = sb.toString().trim();
            String certo = getSharedPreferences("ponte", MODE_PRIVATE).getString("tok", "");
            boolean ok = !certo.isEmpty() && MessageDigest.isEqual(
                certo.getBytes(StandardCharsets.UTF_8), tok.getBytes(StandardCharsets.UTF_8));
            if (!ok || !rodando) { s.close(); return; }
            s.setSoTimeout(0);
            Cliente c = new Cliente(s);
            clientes.add(c);
            semClientesDesde = 0;
            c.start();
            if (configBytes != null) c.enviar(configBytes);          // manda SPS/PPS atual
            if (ultimoChave != null) c.enviar(ultimoChave);          // + último quadro-chave (imagem imediata)
            pedirKeyframe();                                          // e pede keyframe novo p/ começar limpo
        } catch (Exception e) {
            try { s.close(); } catch (Exception ignored) {}
        }
    }

    void remover(Cliente c) {
        clientes.remove(c);
        if (clientes.isEmpty()) semClientesDesde = System.currentTimeMillis();
    }

    /** Um cliente TCP com fila própria: escreve num thread e descarta quando atrasa, sem travar o codificador. */
    private final class Cliente extends Thread {
        private final Socket sock;
        private final OutputStream out;
        private final ArrayBlockingQueue<byte[]> fila = new ArrayBlockingQueue<>(120);
        private volatile boolean vivo = true;

        Cliente(Socket s) throws Exception { sock = s; out = s.getOutputStream(); setName("friday-tx-cli"); }

        void enviar(byte[] p) {
            if (!vivo) return;
            if (!fila.offer(p)) { fila.poll(); fila.offer(p); }       // cheia: descarta o mais antigo
        }

        @Override
        public void run() {
            try {
                while (vivo && rodando) {
                    byte[] p = fila.take();
                    out.write(p);
                    out.flush();
                }
            } catch (Exception ignored) {
            } finally {
                vivo = false;
                try { sock.close(); } catch (Exception ignored) {}
                remover(this);
            }
        }

        void encerrar() { vivo = false; interrupt(); try { sock.close(); } catch (Exception ignored) {} }
    }

    // ------------------------------------------------------------------ parar tudo
    @Override public void onDestroy() { parar(); super.onDestroy(); }

    private synchronized void parar() {
        if (!rodando && !ativo) { try { stopSelf(); } catch (Exception ignored) {} return; }
        rodando = false;
        ativo = false;
        if (Acesso.inst != null) Acesso.inst.pulsar(false);
        for (Cliente c : clientes) c.encerrar();
        clientes.clear();
        try { if (srv != null) srv.close(); } catch (Exception ignored) {}
        try { if (display != null) display.release(); } catch (Exception ignored) {}
        try { if (codec != null) { codec.stop(); codec.release(); } } catch (Exception ignored) {}
        try { if (entrada != null) entrada.release(); } catch (Exception ignored) {}
        try { if (projecao != null) { if (projCb != null) projecao.unregisterCallback(projCb); projecao.stop(); } } catch (Exception ignored) {}
        srv = null; display = null; codec = null; entrada = null; projecao = null;
        try { if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_REMOVE); else stopForeground(true); } catch (Exception ignored) {}
        try { stopSelf(); } catch (Exception ignored) {}
    }
}
