package dev.integra.friday;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.accessibility.AccessibilityNodeInfo;

import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** WhatsApp DE VERDADE pelo Serviço de Acessibilidade: abre o app, acha a conversa pelo NOME (busca do próprio WhatsApp,
 *  vale para contatos fora da agenda e grupos), escreve a mensagem e PARA: só envia depois do "sim" do dono (confirmar()).
 *  Antes o celular só abria um link wa.me sem número (contatos sem permissão) e dizia "enviei" — nada era enviado. */
final class Zap {
    private Zap() {}

    private static volatile String[] pendente;            // {pacote, nome da conversa, texto}
    private static volatile long pendenteT;

    static boolean temPendente() { return pendente != null && System.currentTimeMillis() - pendenteT < 180000; }

    static String pacote(Context c) {
        String pref = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getString("zap_pacote", "");
        if (!pref.isEmpty() && instalado(c, pref)) return pref;
        if (instalado(c, "com.whatsapp")) return "com.whatsapp";
        if (instalado(c, "com.whatsapp.w4b")) return "com.whatsapp.w4b";
        return null;
    }

    private static boolean instalado(Context c, String p) {
        try { c.getPackageManager().getPackageInfo(p, 0); return true; } catch (Exception e) { return false; }
    }

    // ------------------------------------------------------------------ nós da tela
    private static AccessibilityNodeInfo raiz(String pkg) {
        Acesso a = Acesso.inst;
        if (a == null) return null;
        AccessibilityNodeInfo r = a.getRootInActiveWindow();
        return r != null && pkg.contentEquals(r.getPackageName() == null ? "" : r.getPackageName()) ? r : null;
    }

    private static AccessibilityNodeInfo porId(String pkg, String id) {
        AccessibilityNodeInfo r = raiz(pkg);
        if (r == null) return null;
        List<AccessibilityNodeInfo> l = r.findAccessibilityNodeInfosByViewId(pkg + ":id/" + id);
        return l == null || l.isEmpty() ? null : l.get(0);
    }

    private static AccessibilityNodeInfo esperar(String pkg, String id, long ms) {
        long fim = System.currentTimeMillis() + ms;
        while (System.currentTimeMillis() < fim) {
            AccessibilityNodeInfo n = porId(pkg, id);
            if (n != null) return n;
            dormir(150);
        }
        return null;
    }

    private static void dormir(long ms) { try { Thread.sleep(ms); } catch (InterruptedException ignored) {} }

    private static boolean clicar(AccessibilityNodeInfo n) {
        for (AccessibilityNodeInfo x = n; x != null; x = x.getParent())
            if (x.isClickable()) return x.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        return false;
    }

    private static boolean escrever(AccessibilityNodeInfo n, String t) {
        Bundle b = new Bundle();
        b.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, t);
        return n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, b);
    }

    private static void coletarTextos(AccessibilityNodeInfo n, String id, List<AccessibilityNodeInfo> out) {
        if (n == null) return;
        if (id.equals(n.getViewIdResourceName())) out.add(n);
        for (int i = 0; i < n.getChildCount(); i++) coletarTextos(n.getChild(i), id, out);
    }

    private static String texto(AccessibilityNodeInfo n) { return n == null || n.getText() == null ? "" : n.getText().toString(); }

    // ------------------------------------------------------------------ preparar (sem enviar)
    /** abre a conversa e deixa a mensagem escrita; devolve a pergunta de confirmação ou o motivo da falha */
    static String preparar(Context c, Ferramentas ferr, String contato, String msg) {
        String r = preparar(c, ferr, contato, msg, pacote(c));
        String outro = "com.whatsapp".equals(pacote(c)) ? "com.whatsapp.w4b" : "com.whatsapp";
        if (r.startsWith("falhou: não achei a conversa") && instalado(c, outro)) {     // tem os dois WhatsApp: tenta no outro
            String r2 = preparar(c, ferr, contato, msg, outro);
            if (!r2.startsWith("falhou")) return r2;
        }
        return r;
    }

    private static String preparar(Context c, Ferramentas ferr, String contato, String msg, String pkg) {
        if (contato == null || contato.trim().isEmpty()) return "Para quem eu mando a mensagem?";
        contato = contato.trim().replaceAll("(?iu)\\bintegrea\\b", "integra");
        String digContato = contato.replaceAll("[^0-9]", "");
        if (Ferramentas.ehNumeroFalso(digContato) && contato.matches("^[0-9+() -]+$")) {
            return "Para quem você quer enviar a mensagem? Me diga o nome do contato.";
        }
        if (msg == null || msg.trim().isEmpty()) return "O que eu escrevo para " + contato + "?";
        if (pkg == null) return "falhou: o WhatsApp não está instalado";
        msg = msg.trim();
        pendente = null;
        String num = ferr.resolverContato(contato);
        if (Ferramentas.ehNumeroFalso(num)) num = "";
        try {
            if (num.length() >= 8) {                                  // número conhecido: abre a conversa já com o texto
                c.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://api.whatsapp.com/send?phone=" + num + "&text=" + URLEncoder.encode(msg, "UTF-8")))
                    .setPackage(pkg).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP));
                pendente = new String[]{pkg, contato, msg};
                pendenteT = System.currentTimeMillis();
                return "Abri o WhatsApp para " + contato + " com a mensagem pronta. Posso enviar?";
            }
            if (Acesso.inst == null) {
                Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_TEXT, msg).setPackage(pkg)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
                c.startActivity(share);
                return "Abri o WhatsApp com a mensagem preparada. Escolha o contato para confirmar o envio.";
            }
            Intent i = c.getPackageManager().getLaunchIntentForPackage(pkg);
            if (i == null) return "falhou: não consegui abrir o WhatsApp";
            c.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP));
            // tela inicial (pode estar dentro de uma conversa: volta até a lista)
            for (int k = 0; k < 4 && esperar(pkg, "menuitem_search", 1500) == null; k++) Acesso.inst.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK);
            AccessibilityNodeInfo busca = porId(pkg, "menuitem_search");
            if (busca == null) {
                Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_TEXT, msg).setPackage(pkg)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
                c.startActivity(share);
                return "Abri o WhatsApp com a mensagem preparada. Escolha o contato na tela.";
            }
            clicar(busca);
            AccessibilityNodeInfo campo = esperar(pkg, "search_input", 2500);
            if (campo == null) campo = esperar(pkg, "search_src_text", 800);
            if (campo == null) {
                Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_TEXT, msg).setPackage(pkg)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
                c.startActivity(share);
                return "Abri o WhatsApp com a mensagem preparada.";
            }
            escrever(campo, contato);
            dormir(1300);
            AccessibilityNodeInfo r = raiz(pkg);
            List<AccessibilityNodeInfo> nomes = new ArrayList<>();
            coletarTextos(r, pkg + ":id/conversations_row_contact_name", nomes);
            if (nomes.isEmpty()) coletarTextos(r, pkg + ":id/contact_name", nomes);
            if (nomes.isEmpty()) coletarTextos(r, pkg + ":id/conversations_row_title", nomes);
            if (nomes.isEmpty()) coletarTextos(r, pkg + ":id/title", nomes);
            String alvo = Agenda.norm(contato);
            boolean ehDono = alvo.contains("integra") || alvo.contains("dono") || alvo.equals("eu") || alvo.equals("mim") || alvo.equals("voce");
            Map<String, AccessibilityNodeInfo> achados = new LinkedHashMap<>();
            AccessibilityNodeInfo exato = null;
            for (AccessibilityNodeInfo n : nomes) {
                String t = texto(n), tn = Agenda.norm(t);
                if (tn.equals(alvo)) exato = n;
                else if (ehDono && (tn.contains("voce") || tn.contains("integra") || tn.contains("mensagens salvas"))) exato = n;
                else if (tn.contains(alvo) || alvo.contains(tn)) achados.putIfAbsent(t, n);
            }
            if (exato == null && achados.size() > 1) {
                Acesso.inst.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK);
                return "Tenho mais de uma conversa parecida: " + String.join(" ou ", new ArrayList<>(achados.keySet()).subList(0, Math.min(3, achados.size()))) + ". Para qual?";
            }
            AccessibilityNodeInfo escolha = exato != null ? exato : achados.isEmpty() ? null : achados.values().iterator().next();
            if (escolha == null) {
                Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_TEXT, msg).setPackage(pkg)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
                c.startActivity(share);
                return "Abri o WhatsApp com a mensagem preparada. Escolha o contato para confirmar o envio.";
            }
            clicar(escolha);
            AccessibilityNodeInfo entrada = esperar(pkg, "entry", 6000);
            if (entrada == null) return "falhou: a conversa não abriu no WhatsApp";
            if (num.length() < 8 || texto(entrada).trim().isEmpty()) escrever(entrada, msg);
            dormir(300);
            AccessibilityNodeInfo nome = porId(pkg, "conversation_contact_name");
            String real = nome != null && !texto(nome).isEmpty() ? texto(nome) : contato;
            pendente = new String[]{pkg, real, msg};
            pendenteT = System.currentTimeMillis();
            return "Mensagem escrita para " + real + ": \"" + msg + "\". Posso enviar?";
        } catch (Exception e) {
            return "falhou no WhatsApp: " + e.getMessage();
        }
    }

    // ------------------------------------------------------------------ enviar / cancelar
    static String confirmar(Context c) {
        String[] p = pendente;
        if (p == null || !temPendente()) return "Não tenho nenhuma mensagem esperando para enviar.";
        pendente = null;
        AccessibilityNodeInfo env = esperar(p[0], "send", 2500);
        if (env == null) return "falhou: a conversa com " + p[1] + " não está mais aberta; não enviei";
        AccessibilityNodeInfo entrada = porId(p[0], "entry");
        if (entrada != null && !Agenda.norm(texto(entrada)).equals(Agenda.norm(p[2]))) return "falhou: o texto na conversa mudou; não enviei";
        clicar(env);
        dormir(900);
        AccessibilityNodeInfo depois = porId(p[0], "entry");
        boolean ok = depois != null && texto(depois).trim().isEmpty();
        return ok ? "Enviei para " + p[1] + "." : "Toquei em enviar para " + p[1] + ", mas não consegui confirmar; dá uma olhada no WhatsApp.";
    }

    static String cancelar() {
        String[] p = pendente;
        pendente = null;
        if (p != null) {                                          // apaga o rascunho que ficou escrito na conversa
            AccessibilityNodeInfo e = porId(p[0], "entry");
            if (e != null) escrever(e, "");
        }
        return p == null ? "Tudo bem." : "Cancelado, não enviei para " + p[1] + ".";
    }
}
