package dev.integra.friday;

/** Ponte JNI para o llama.cpp (jni/friday_llm.cpp -> lib/arm64-v8a/libfriday_llm.so). Uma geração por vez. */
final class Llm {
    interface Fluxo { void pedaco(String s); }

    static boolean ok;
    static {
        try { System.loadLibrary("friday_llm"); ok = true; } catch (Throwable t) { ok = false; }
    }

    static native boolean carregar(String caminho, int nCtx, int threads);
    static native boolean pronto();
    static native void parar();
    static native void descarregar();
    static native String gerar(String prompt, int maxTokens, float temp, String gramatica, Fluxo cb);

    private Llm() {}
}
