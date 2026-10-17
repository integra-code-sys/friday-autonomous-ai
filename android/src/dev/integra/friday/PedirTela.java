package dev.integra.friday;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;

/** Activity translúcida que só pede a permissão de captura de tela e, ao receber OK, sobe o serviço Transmissao.
 *  O diálogo do sistema é aceito sozinho pelo serviço de acessibilidade (Acesso.aceitarDialogoCaptura). */
public class PedirTela extends Activity {
    private static final int PEDIDO = 7001;
    private int fps, w, kbps;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        fps = getIntent().getIntExtra("fps", 60);
        w = getIntent().getIntExtra("w", 720);
        kbps = getIntent().getIntExtra("kbps", 6000);
        MediaProjectionManager mp = (MediaProjectionManager) getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        startActivityForResult(mp.createScreenCaptureIntent(), PEDIDO);
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == PEDIDO && res == RESULT_OK && data != null) {
            Intent s = new Intent(this, Transmissao.class)
                .putExtra("resultCode", res).putExtra("data", data)
                .putExtra("fps", fps).putExtra("w", w).putExtra("kbps", kbps);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(s); else startService(s);
        }
        finish();
    }
}
