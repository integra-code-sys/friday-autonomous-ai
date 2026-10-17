package dev.integra.friday;

import android.content.Intent;
import android.speech.RecognitionService;
import android.speech.SpeechRecognizer;

/** O Android exige um serviço de reconhecimento junto do assistente digital. A Friday ouve pelo reconhecedor on-device
 *  do sistema (Voz.java), então este só recusa educadamente quem tentar usá-lo como teclado de voz. */
public class Reconhecimento extends RecognitionService {
    @Override protected void onStartListening(Intent i, Callback cb) {
        try { cb.error(SpeechRecognizer.ERROR_RECOGNIZER_BUSY); } catch (Exception ignored) {}
    }
    @Override protected void onCancel(Callback cb) {}
    @Override protected void onStopListening(Callback cb) {}
}
