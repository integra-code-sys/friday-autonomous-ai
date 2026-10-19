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
        boolean ok = false;
        for (AccessibilityNodeInfo x = n; x != null; x = x.getParent()) {
            if (x.isClickable() && x.performAction(AccessibilityNodeInfo.ACTION_CLICK)) { ok = true; break; }
        }
        if (Acesso.inst != null && n != null) {
            android.graphics.Rect b = new android.graphics.Rect();
            n.getBoundsInScreen(b);
            if (b.width() > 8 && b.height() > 8) ok = Acesso.inst.toque(b.centerX(), b.centerY()) || ok;
        }
        return ok;
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

    private static String rotulo(AccessibilityNodeInfo n) {
        if (n == null) return "";
        if (n.getText() != null && n.getText().length() > 0) return n.getText().toString();
        return n.getContentDescription() == null ? "" : n.getContentDescription().toString();
    }

    /** Linhas da busca/lista cujo nome bate com o contato. Não inclui o campo de busca. */
    private static List<AccessibilityNodeInfo> linhasDeContato(String pkg, String alvo) {
        List<AccessibilityNodeInfo> out = new ArrayList<>();
        Map<String, AccessibilityNodeInfo> visto = new LinkedHashMap<>();
        coletarLinhas(raiz(pkg), pkg, alvo, visto);
        out.addAll(visto.values());
        return out;
    }

    private static void coletarLinhas(AccessibilityNodeInfo n, String pkg, String alvo, Map<String, AccessibilityNodeInfo> visto) {
        if (n == null || alvo.isEmpty()) return;
        String id = n.getViewIdResourceName() == null ? "" : n.getViewIdResourceName();
        if (!n.isEditable() && !id.contains("search") && !id.endsWith("/entry")) {
            String tn = Agenda.norm(rotulo(n));
            boolean bate = tn.equals(alvo) || tn.contains(alvo) || (tn.length() >= 3 && alvo.contains(tn))
                || (alvo.contains("integra") && tn.contains("integra"));
            if (tn.length() >= 2 && tn.length() < 60 && bate) visto.putIfAbsent(tn, n);
        }
        for (int i = 0; i < n.getChildCount(); i++) coletarLinhas(n.getChild(i), pkg, alvo, visto);
    }

    private static AccessibilityNodeInfo rotuloQueBate(String pkg, String... alvos) {
        return acharRotulo(raiz(pkg), alvos);
    }

    private static AccessibilityNodeInfo acharRotulo(AccessibilityNodeInfo n, String... alvos) {
        if (n == null) return null;
        String t = Agenda.norm(rotulo(n));
        for (String a : alvos) if (!t.isEmpty() && t.contains(a)) return n;
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo x = acharRotulo(n.getChild(i), alvos);
            if (x != null) return x;
        }
        return null;
    }

    private static AccessibilityNodeInfo editavel(AccessibilityNodeInfo n) {
        if (n == null) return null;
        if (n.isEditable()) return n;
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo x = editavel(n.getChild(i));
            if (x != null) return x;
        }
        return null;
    }

    private static AccessibilityNodeInfo esperarCampo(String pkg, long ms) {
        long fim = System.currentTimeMillis() + ms;
        while (System.currentTimeMillis() < fim) {
            for (String id : new String[]{"entry", "entry_text", "conversation_entry", "input"}) {
                AccessibilityNodeInfo n = porId(pkg, id);
                if (n != null) return n;
            }
            AccessibilityNodeInfo e = editavel(raiz(pkg));
            if (e != null) {
                String id = e.getViewIdResourceName() == null ? "" : e.getViewIdResourceName();
                if (!id.contains("search")) return e;
            }
            dormir(200);
        }
        return null;
    }

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
        // Número só se o dono falou o número. Nome nunca vira telefone da agenda: a busca é pelo nome, dentro do WhatsApp.
        boolean falouNumero = contato.matches("^[0-9+() -]{8,}$") && digContato.length() >= 8 && !Ferramentas.ehNumeroFalso(digContato);
        String num = falouNumero ? digContato : "";
        try {
            if (num.length() >= 8) {
                c.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://api.whatsapp.com/send?phone=" + num + "&text=" + URLEncoder.encode(msg, "UTF-8")))
                    .setPackage(pkg).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP));
                pendente = new String[]{pkg, contato, msg};
                pendenteT = System.currentTimeMillis();
                return "Abri o WhatsApp para o número que você falou, com a mensagem escrita. Posso enviar?";
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
            if (busca == null) busca = rotuloQueBate(pkg, "pesquisar", "search");
            if (busca == null) return "Abri o WhatsApp e não achei a busca. Não abri a tela de escolher contato.";
            clicar(busca);
            AccessibilityNodeInfo campo = esperar(pkg, "search_input", 2500);
            if (campo == null) campo = esperar(pkg, "search_src_text", 800);
            if (campo == null) {
                AccessibilityNodeInfo ed = editavel(raiz(pkg));
                if (ed != null) campo = ed;
            }
            if (campo == null) return "Abri a busca do WhatsApp e não achei o campo. A lista ficou como está.";
            escrever(campo, contato);
            dormir(1500);
            String alvo = Agenda.norm(contato);
            List<AccessibilityNodeInfo> candidatos = linhasDeContato(pkg, alvo);
            if (candidatos.isEmpty() && Acesso.inst != null) {
                android.graphics.Rect caixa = new android.graphics.Rect();
                campo.getBoundsInScreen(caixa);
                Acesso.inst.toque(caixa.centerX(), caixa.bottom + 110);
                dormir(900);
                AccessibilityNodeInfo entradaDireta = esperarCampo(pkg, 3500);
                if (entradaDireta != null && texto(entradaDireta).trim().isEmpty()) {
                    escrever(entradaDireta, msg);
                    pendente = new String[]{pkg, contato, msg};
                    pendenteT = System.currentTimeMillis();
                    return "Abri o primeiro contato da busca e escrevi a mensagem para " + contato + ". Posso enviar?";
                }
                return "A busca de " + contato + " ficou aberta e eu não achei a linha do contato. Não troquei isso pela tela de escolher contato.";
            }
            AccessibilityNodeInfo entrada = null;
            String real = contato;
            for (AccessibilityNodeInfo escolha : candidatos) {
                clicar(escolha);
                dormir(700);
                if (porId(pkg, "entry") == null) {
                    AccessibilityNodeInfo conversa = rotuloQueBate(pkg, "conversa", "mensagem", "message", "chat");
                    if (conversa != null) clicar(conversa);
                }
                entrada = esperarCampo(pkg, 4000);
                if (entrada != null) {
                    AccessibilityNodeInfo nome = porId(pkg, "conversation_contact_name");
                    if (nome == null) nome = porId(pkg, "conversation_contact");
                    if (nome != null && !texto(nome).isEmpty()) real = texto(nome);
                    break;
                }
            }
            if (entrada == null) return "Toquei o contato " + contato + ", mas a conversa não abriu. A lista continua na tela.";
            escrever(entrada, msg);                          // SET_TEXT troca o campo inteiro: rascunho velho não vai junto
            dormir(300);
            AccessibilityNodeInfo conf = porId(pkg, "entry");
            if (conf != null && !Agenda.norm(texto(conf)).equals(Agenda.norm(msg))) {
                escrever(conf, msg);                         // 2ª tentativa; se ainda não bater, não finge que escreveu
                dormir(400);
                conf = porId(pkg, "entry");
                if (conf != null && !Agenda.norm(texto(conf)).equals(Agenda.norm(msg)))
                    return "Abri a conversa com " + real + ", mas o campo não ficou com a mensagem certa; não deixei pronta para enviar.";
            }
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
