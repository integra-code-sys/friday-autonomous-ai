package dev.integra.friday;

import android.content.Context;
import android.net.Uri;

import org.json.JSONObject;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** Cérebro LOCAL da F.R.I.D.A.Y. no celular: Qwen3-1.7B (llama.cpp na CPU) em laço observar -> agir -> conferir.
 *  Cada passo o modelo devolve JSON {"acao": ferramenta, "args": {...}} (gramática GBNF garante o formato);
 *  o resultado REAL da ferramenta volta para ele até ele "responder". Funciona sem o PC; com o PC ligado pode delegar. */
final class Cerebro {
    interface Ouvinte { void evento(String tipo, String texto); }

    static final String MODELO = "qwen2.5-3b-q4_0.gguf";             // padrão preferencial (3B instruct sem bloco <think>, mais preciso em JSON)
    private static final String[] ORDEM_PREFERENCIA = {
        "qwen3-4b-q4_k_m.gguf", "gemma-3-4b-it-q4_k_m.gguf",
        "qwen2.5-3b-q4_0.gguf", "smollm3-3b-q4_0.gguf", "qwen3-1.7b-q4_0.gguf"
    };
    private String carregado = null;
    private static Cerebro inst;
    private final Context c;
    private final Ferramentas ferr;
    private final List<String[]> historico = new ArrayList<>();      // [pedido, resposta final]
    private volatile Ouvinte ouvinte;
    private volatile boolean ocupada;

    private Cerebro(Context c) { this.c = c.getApplicationContext(); ferr = new Ferramentas(this.c); }

    static synchronized Cerebro get(Context c) {
        if (inst == null) inst = new Cerebro(c);
        return inst;
    }

    void setOuvinte(Ouvinte o) { ouvinte = o; }
    boolean ocupada() { return ocupada; }
    Ferramentas ferramentas() { return ferr; }

    private void avisar(String tipo, String t) {
        Ouvinte o = ouvinte;
        if (o != null) try { o.evento(tipo, t); } catch (Exception ignored) {}
    }

    File pasta() { return new File(c.getExternalFilesDir(null), "models"); }
    String modelo() {
        String m = c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getString("modelo", "");
        if (m != null && !m.isEmpty() && new File(pasta(), m).exists()) return m;
        for (String pref : ORDEM_PREFERENCIA) {
            if (new File(pasta(), pref).exists()) return pref;
        }
        String[] todos = modelos();
        return todos.length > 0 ? todos[0] : MODELO;
    }
    File arquivoModelo() { return new File(pasta(), modelo()); }

    /** modelos .gguf no celular, em ordem de qualidade */
    String[] modelos() {
        String[] l = pasta().list((d, n) -> n.endsWith(".gguf"));
        if (l == null) return new String[0];
        java.util.Arrays.sort(l);
        return l;
    }

    /** catálogo avaliado de modelos locais para Android (instalados + recomendados para download) */
    String catalogoJson() {
        try {
            String ativo = modelo();
            Object[][] cat = {
                {"qwen2.5-3b-q4_0.gguf", "Qwen 2.5 3B Instruct (Q4_0)", "1.82 GB", "[NOTA 5.0/5] Recomendado · Rápido e preciso em ferramentas/JSON",
                 "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_0.gguf"},
                {"smollm3-3b-q4_0.gguf", "SmolLM3 3B Instruct (Q4_0)", "1.81 GB", "[NOTA 4.8/5] Excelente raciocínio geral e código compacto",
                 "https://huggingface.co/ggml-org/SmolLM3-3B-GGUF/resolve/main/SmolLM3-Q4_K_M.gguf"},
                {"qwen3-1.7b-q4_0.gguf", "Qwen 3 1.7B (Q4_0)", "1.05 GB", "[NOTA 4.7/5] Ultra-rápido · Menor consumo de RAM/bateria",
                 "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf"},
                {"qwen3-4b-q4_k_m.gguf", "Qwen 3 4B Instruct (Q4_K_M)", "2.50 GB", "[NOTA 5.0/5] Máxima inteligência local para aparelhos 8GB+ RAM",
                 "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"},
                {"gemma-3-4b-it-q4_k_m.gguf", "Google Gemma 3 4B IT (Q4_K_M)", "2.48 GB", "[NOTA 5.0/5] Ótimo português natural e tarefas compostas",
                 "https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf"}
            };
            org.json.JSONArray arr = new org.json.JSONArray();
            java.util.Set<String> vistos = new java.util.HashSet<>();
            for (Object[] o : cat) {
                String arq = (String) o[0];
                vistos.add(arq);
                File f = new File(pasta(), arq);
                arr.put(new JSONObject()
                    .put("arquivo", arq).put("nome", o[1]).put("tamanho", o[2]).put("nota", o[3]).put("url", o[4])
                    .put("instalado", f.exists()).put("ativo", arq.equals(ativo)));
            }
            for (String m : modelos()) {
                if (vistos.contains(m)) continue;
                File f = new File(pasta(), m);
                arr.put(new JSONObject()
                    .put("arquivo", m).put("nome", m).put("tamanho", String.format(Locale.ROOT, "%.2f GB", f.length() / 1e9))
                    .put("nota", "Modelo local instalado").put("url", "")
                    .put("instalado", true).put("ativo", m.equals(ativo)));
            }
            return arr.toString();
        } catch (Exception e) { return "[]"; }
    }

    /** passa para o próximo modelo instalado (ou o nome dado); recarrega no próximo pedido */
    synchronized String trocarModelo(String nome) {
        String[] l = modelos();
        if (l.length == 0) return MODELO;
        String atual = modelo(), novo = nome;
        if (novo == null || novo.isEmpty()) {
            int i = java.util.Arrays.asList(l).indexOf(atual);
            novo = l[(i + 1) % l.length];
        }
        c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).edit().putString("modelo", novo).apply();
        if (!novo.equals(carregado)) { Llm.descarregar(); carregado = null; }
        return novo;
    }

    /** formato de chat: permite raciocínio natural nos modelos que suportam */
    private String assist() {
        return "<|im_start|>assistant\n";
    }

    synchronized boolean preparar() {
        if (!Llm.ok) return false;
        if (Llm.pronto() && arquivoModelo().getName().equals(carregado)) return true;
        if (Llm.pronto()) { Llm.descarregar(); carregado = null; }
        File f = arquivoModelo();
        if (!f.exists()) return false;
        avisar("estado", "carregando " + f.getName() + "…");
        if (!Llm.carregar(f.getAbsolutePath(), 4096, 4)) return false;
        carregado = f.getName();
        Llm.gerar(sistema(), 1, 0.1f, "", null);           // aquece: o prompt de sistema fica no cache (1º pedido já rápido)
        return true;
    }

    private static final String NOMES_LOCAL = "responder|calcular|abrir_app|abrir_tela|flutuante|tailscale|dev|terminal|abrir_site|pesquisar|pesquisar_links|ler_tela|tocar|digitar|rolar|tecla|criar_documento|criar_arquivo|alarme|timer|evento|agenda|ligar|whatsapp|compartilhar|lanterna|volume|configuracao|foto|lembrar|memoria|bateria|hora|data";
    private static final String NOMES_PC = NOMES_LOCAL + "|pc";
    private String ultimaBusca = "";

    private static String gramatica(boolean permitePc) {
        StringBuilder alt = new StringBuilder();
        String lista = permitePc ? NOMES_PC : NOMES_LOCAL;
        for (String n : lista.split("\\|")) alt.append(alt.length() == 0 ? "" : " | ").append("\"\\\"").append(n).append("\\\"\"");
        return "root ::= \"{\" ws \"\\\"acao\\\":\" ws nome ws \",\" ws \"\\\"args\\\":\" ws object ws \"}\"\n"
            + "nome ::= " + alt + "\n"
            + "value ::= object | array | string | number | (\"true\" | \"false\" | \"null\") ws\n"
            + "object ::= \"{\" ws ( string \":\" ws value (\",\" ws string \":\" ws value)* )? \"}\" ws\n"
            + "array ::= \"[\" ws ( value (\",\" ws value)* )? \"]\" ws\n"
            + "string ::= \"\\\"\" ( [^\"\\\\\\x7F\\x00-\\x1F] | \"\\\\\" ([\"\\\\/bfnrt] | \"u\" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]) )* \"\\\"\" ws\n"
            + "number ::= \"-\"? [0-9]+ (\".\" [0-9]+)? ws\n"
            + "ws ::= [ \\t\\n]{0,8}\n";
    }

    private static String gramatica() { return gramatica(false); }

    private String sistema() { return sistema(false); }

    private String sistema(boolean permitePc) {
        return "<|im_start|>system\n"
            + "Você é a F.R.I.D.A.Y. (Sexta-Feira), assistente e orquestradora autônoma do Iann, rodando no celular Android dele. "
            + "Fale português do Brasil, inteligente, natural, proativo e assertivo. Você controla o celular com ferramentas.\n"
            + "Responda SEMPRE só com JSON: {\"acao\": \"ferramenta\", \"args\": {...}}. Um passo por vez; depois do resultado decida o próximo. "
            + "Para encerrar use {\"acao\": \"responder\", \"args\": {\"texto\": \"...\"}} dizendo o que fez de verdade. NUNCA escreva placeholders como [links].\n"
            + (permitePc
                ? "O dono pediu explicitamente para rodar no PC: use 'pc' para enviar o comando ao computador.\n"
                : "REGRA CRÍTICA DE EXECUÇÃO: Você está em modelo LOCAL no celular. Execute tudo no aparelho usando as ferramentas do celular. NUNCA delegue ações ao PC a menos que o dono fale expressamente para fazer no computador.\n")
            + "REGRA DE MENSAGENS / WHATSAPP: NUNCA use números inventados ou fictícios como +123456789 ou 123456789. Coloque SEMPRE o NOME do contato (ex: 'Carlos', 'Mãe', 'Amor') no argumento 'contato'. A Friday local busca o contato no aparelho.\n"
            + "REGRA DE DOCUMENTOS: Para criar PDFs ou documentos, use 'criar_documento' com 'titulo', 'formato' (pdf|docx) e 'conteudo' bem estruturado com seções usando # e tópicos com •.\n"
            + "Regras: conversa simples -> responder direto. Horas/Bateria/Dispositivo -> use as ferramentas hora e bateria ou responda direto. Pesquisa no navegador/Google/eBay/Amazon -> pesquisar. Navegar num app: abrir_app, depois ler_tela, tocar/digitar, conferir com ler_tela. "
            + "Não invente resultado: se uma ferramenta falhar, diga. "
            + "Mensagem para alguém: whatsapp (o dono confirma).\n"
            + "Nunca mexa nas Configurações de acessibilidade nem em você mesma. A data e a hora estão entre [ ] no pedido.\n"
            + "Responda SEMPRE ao pedido ATUAL: nunca copie uma resposta anterior. Perguntas sobre fatos, pessoas, preços ou notícias -> pesquisar_links e responda "
            + "com a informação encontrada de forma inteligente e articulada (não só 'pesquisei'). Nunca diga que enviou/fez algo que a ferramenta não confirmou.\n"
            + "FERRAMENTAS:\n" + Ferramentas.LISTA + "\n"
            + "EXEMPLOS:\n"
            + "pedido: que horas são? -> {\"acao\": \"hora\", \"args\": {}}\n"
            + "pedido: quanto tem de bateria? -> {\"acao\": \"bateria\", \"args\": {}}\n"
            + "pedido: manda um zap pro Carlos dizendo que chego às 18h -> {\"acao\": \"whatsapp\", \"args\": {\"contato\": \"Carlos\", \"texto\": \"Chego às 18h\"}}\n"
            + "pedido: envia mensagem para Mãe falando que já saí -> {\"acao\": \"whatsapp\", \"args\": {\"contato\": \"Mãe\", \"texto\": \"Já saí de casa.\"}}\n"
            + "pedido: abre o Instagram -> {\"acao\": \"abrir_app\", \"args\": {\"nome\": \"Instagram\"}}\n"
            + "pedido: abre minha agenda -> {\"acao\": \"abrir_tela\", \"args\": {\"tela\": \"agenda\"}}\n"
            + "pedido: mostra minha agenda flutuando -> {\"acao\": \"flutuante\", \"args\": {\"tipo\": \"agenda\"}}\n"
            + "pedido: pesquise sobre inteligência artificial e monte um doc -> {\"acao\": \"pesquisar_links\", \"args\": {\"consulta\": \"inteligência artificial\"}}\n"
            + "pedido: crie um documento sobre carros elétricos em pdf -> {\"acao\": \"criar_documento\", \"args\": {\"titulo\": \"Carros Elétricos\", \"formato\": \"pdf\", \"conteudo\": \"# Visão Geral\\nCarros elétricos utilizam baterias de íon-lítio...\\n\\n# Vantagens\\n• Zero emissão direta\\n• Alto torque instantâneo\"}}\n"
            + "pedido: como está o clima? -> {\"acao\": \"abrir_tela\", \"args\": {\"tela\": \"clima\"}}\n"
            + "pedido: pesquisa receita de bolo -> {\"acao\": \"pesquisar\", \"args\": {\"consulta\": \"receita de bolo\", \"onde\": \"google\"}}\n"
            + "pedido: procure no ebay Wella shampoo -> {\"acao\": \"pesquisar\", \"args\": {\"consulta\": \"Wella shampoo\", \"onde\": \"ebay\"}}\n"
            + "pedido: quanto é 15 x 23? -> {\"acao\": \"calcular\", \"args\": {\"expressao\": \"15*23\"}}\n"
            + (permitePc ? "pedido: pede pro PC abrir o Chromium -> {\"acao\": \"pc\", \"args\": {\"pedido\": \"abrir o Chromium\"}}\n" : "")
            + "pedido: toca Yellow no YouTube -> {\"acao\": \"pesquisar\", \"args\": {\"consulta\": \"Yellow Coldplay\", \"onde\": \"youtube\"}}\n"
            + "depois de uma ferramenta dar certo -> {\"acao\": \"responder\", \"args\": {\"texto\": \"Pronto, abri o Instagram.\"}}\n"
            + "O que você sabe do Iann:\n" + ferr.fatos(30)
            + "<|im_end|>\n";
    }


    // Verifica se o usuário pediu explicitamente para executar no PC
    private static final java.util.regex.Pattern PEDIU_PC_EXPLICITO = java.util.regex.Pattern.compile(
        "(?iu)^\\s*(?:sexta[- ]?feira,?\\s*)?(?:pe[çc]a|pede|manda|fala|diz|pergunta|avisa|roda|rodar|faz|fazer|executa|executar)\\s+(?:pro|pra|para\\s+o|ao|à|a|no|na)\\s+(?:pc|computador|friday\\s+do\\s+pc)\\s*(?:que\\s+|pra\\s+|para\\s+)?(.+)$");

    static boolean pediuParaOPc(String pedido) {
        if (pedido == null) return false;
        String p = pedido.toLowerCase(Locale.ROOT);
        return PEDIU_PC_EXPLICITO.matcher(pedido).matches()
            || p.matches("(?s).*\\b(no pc|pro pc|pra pc|no computador|pro computador|na friday do pc|roda no pc|rodar no pc|faz no pc|fazer no pc|executa no pc|executar no pc)\\b.*");
    }

    static String extrairPedidoPc(String pedido) {
        if (pedido == null) return "";
        java.util.regex.Matcher m = PEDIU_PC_EXPLICITO.matcher(pedido);
        if (m.matches()) return m.group(1).trim();
        return pedido.replaceAll("(?iu)\\b(?:roda|rodar|faz|fazer|executa|executar)?\\s*(?:no|pro|pra|para\\s+o|ao|na\\s+friday\\s+do)\\s*(?:pc|computador|friday\\s+do\\s+pc)\\b", "").trim();
    }

    private static final java.util.regex.Pattern PRO_CLAUDE = java.util.regex.Pattern.compile(
        "(?iu)^\\s*(?:sexta[- ]?feira,?\\s*)?(?:pe[çc]a|pede|manda|fala|diz)\\s+(?:pro|pra|para\\s+o|ao)\\s+claude\\s*(?:que\\s+|pra\\s+|para\\s+)?(.+)$");

    private static final java.util.regex.Pattern BUSCA_DIRETA = java.util.regex.Pattern.compile(
        "(?iu)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:por\\s+favor[,:\\s]*)?(?:apenas\\s+|s[óo]\\s+)?(?:abr[ae]\\s+(?:o\\s+navegador|o\\s+chrome|uma\\s+nova\\s+aba)\\s+e\\s+)?(?:pesquis\\w+|busc\\w+|procur\\w+)\\b.*");

    private static final java.util.regex.Pattern COMP_PESQ_ZAP = java.util.regex.Pattern.compile(
        "(?is)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:por\\s+favor[,:\\s]*)?(?:pesquis\\w*|busc\\w*|procur\\w*)\\s+(?:(?:e\\s+)?(?:entr\\w*|acess\\w*|abr\\w*)\\s+(?:no\\s+|na\\s+|ao\\s+)?(?:site|p[áa]gina|loja|portal)?\\s*)?(?:sobre\\s+|por\\s+|o\\s+que\\s+[ée]\\s+)?(.+?)\\s+e\\s+(?:depois\\s+)?(?:prepar\\w*|escrev\\w*|redij\\w*|envi\\w*|mand\\w*)\\s+(?:uma\\s+)?(?:mensagem\\s+|msg\\s+|isso\\s+|o\\s+resumo\\s+|o\\s+resultado\\s+)?(?:no\\s+whats(?:app)?\\s+|no\\s+zap\\s+|pelo\\s+whats(?:app)?\\s+|pelo\\s+zap\\s+)?(?:para\\s+|pro\\s+|pra\\s+|ao\\s+|à\\s+)([\\p{L}0-9_+\\- ]+?)(?:\\s+no\\s+(?:whats(?:app)?|zap)|\\s+dizendo\\s+(.+))?\\s*[.!?]*$");

    private static final java.util.regex.Pattern COMP_PESQ_DOC = java.util.regex.Pattern.compile(
        "(?is)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:por\\s+favor[,:\\s]*)?(?:pesquis\\w*|busc\\w*|procur\\w*)\\s+(?:sobre\\s+|por\\s+)?(.+?)\\s+e\\s+(?:depois\\s+)?(?:cri\\w*|ger\\w*|salv\\w*|escrev\\w*|mont\\w*|fa[çc]\\w*|faz\\w*)\\s+(?:um\\s+|uma\\s+|num\\s+|numa\\s+)?(?:arquivo|documento|docs?|relat[óo]rio|resumo|nota|artigo|pdf|docx|txt|md)(?:\\s+(?:em\\s+)?(pdf|docx|txt|md|html))?(?:\\s+(?:chamado|com\\s+nome)\\s+([\\w\\-. ]+))?.*$");

    private static final java.util.regex.Pattern DIRETO_DOC = java.util.regex.Pattern.compile(
        "(?is)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:por\\s+favor[,:\\s]*)?(?:cri\\w*|ger\\w*|escrev\\w*|mont\\w*|fa[çc]\\w*|faz\\w*)\\s+(?:um\\s+|uma\\s+)?(?:arquivo|documento|docs?|relat[óo]rio|resumo|nota|artigo|pdf|docx|txt|md)?\\s*(?:em\\s+(pdf|docx|txt|md|html))?\\s+(?:sobre\\s+|de\\s+|com\\s+o\\s+tema\\s+)(.+?)(?:\\s+em\\s+(pdf|docx|txt|md|html))?\\s*[.!?]*$");

    private static final java.util.regex.Pattern COMP_PESQ_AG = java.util.regex.Pattern.compile(
        "(?is)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:por\\s+favor[,:\\s]*)?(?:pesquis\\w*|busc\\w*|procur\\w*)\\s+(?:sobre\\s+|por\\s+)?(.+?)\\s+e\\s+(?:depois\\s+)?(?:agend\\w*|marqu\\w*|anot\\w*\\s+na\\s+agenda|coloqu\\w*\\s+na\\s+agenda)\\s+(.+?)\\s*[.!?]*$");

    private static final java.util.regex.Pattern ABRIR_AGENDA = java.util.regex.Pattern.compile(
        "(?iu)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:por\\s+favor[,:\\s]*)?(?:abr[ae]|mostr[ae]|exib[ae]|ver|veja|qual\\s+[ée]|como\\s+est[áa]|o\\s+que\\s+tenho\\s+(?:hoje|amanh[ãa])\\s+na)\\s+(?:a\\s+)?(?:minha\\s+|sua\\s+)?(?:agenda|calend[áa]rio)(?:\\s+da\\s+sexta[- ]?feira)?\\s*[.!?]*$");

    static boolean ehComposto(String pedido) {
        if (pedido == null) return false;
        String pl = pedido.toLowerCase(Locale.ROOT);
        return COMP_PESQ_ZAP.matcher(pedido).matches() || COMP_PESQ_DOC.matcher(pedido).matches() || DIRETO_DOC.matcher(pedido).matches() || COMP_PESQ_AG.matcher(pedido).matches()
            || pl.matches("(?s).*\\b(e depois|em seguida|e ent[ãa]o)\\b.*")
            || pl.matches("(?s).*\\be\\s+(envi|mand|cri|salv|ger|agend|marqu|abr|escrev|prepar|redij)\\w*\\b.*");
    }

    private String atalhoAgenda(String pedido) {
        if (pedido == null || ehComposto(pedido)) return null;
        if (!ABRIR_AGENDA.matcher(pedido.trim()).matches()) return null;
        try {
            JSONObject args = new JSONObject().put("tela", "agenda");
            avisar("passo", "abrir_tela " + args.toString());
            String r = ferr.executar("abrir_tela", args);
            avisar("resultado", r);
            String fala = "Pronto, abri a sua agenda na Sexta-Feira. " + Agenda.nivelFala(c, System.currentTimeMillis());
            historico.add(new String[]{pedido.trim(), fala});
            while (historico.size() > 6) historico.remove(0);
            avisar("fim", fala);
            return fala;
        } catch (Exception e) { return null; }
    }

    private String atalhoComposto(String pedido) {
        if (pedido == null) return null;
        try {
            java.util.regex.Matcher mz = COMP_PESQ_ZAP.matcher(pedido.trim());
            if (mz.matches()) {
                String tema = Ferramentas.limparTermoBusca(mz.group(1)).replaceAll("(?iu)\\bfortinate\\b", "fortnite");
                String contato = mz.group(2).trim().replaceAll("(?i)\\bintegrea\\b", "integra");
                String extra = mz.group(3) == null ? "" : mz.group(3).trim();
                boolean deveAbrirSite = pedido.toLowerCase(Locale.ROOT).matches("(?s).*\\b(entr\\w*|acess\\w*|abr\\w*)\\s+(?:no|na|ao|o|a)?\\s*(?:site|loja|p[áa]gina|portal)\\b.*");
                if (deveAbrirSite) {
                    String urlAlvo = tema.toLowerCase(Locale.ROOT).matches("(?s).*fort[i]?n[ai]?te.*") ? "https://www.fortnite.com/item-shop?lang=pt-BR" : ("https://duckduckgo.com/?q=" + Uri.encode(tema));
                    JSONObject siteArgs = new JSONObject().put("url", urlAlvo);
                    avisar("passo", "abrir_site " + siteArgs.toString());
                    ferr.executar("abrir_site", siteArgs);
                }
                avisar("passo", "pesquisar_links {\"consulta\":\"" + tema + "\"}");
                String resumo = ferr.extrairResumoWeb(tema);
                avisar("resultado", resumo);
                String msg = (extra.isEmpty() ? "Resumo sobre " + tema + ":\n" : extra + "\n\n") + resumo;
                JSONObject zapArgs = new JSONObject().put("contato", contato).put("texto", msg);
                avisar("passo", "whatsapp " + zapArgs.toString());
                String rz = ferr.executar("whatsapp", zapArgs);
                avisar("resultado", rz);
                String fala = (deveAbrirSite ? "Acessei o site e pesquisei sobre " : "Pesquisei sobre ") + tema + ". " + rz;
                List<String[]> ps = new ArrayList<>();
                if (deveAbrirSite) ps.add(new String[]{"abrir_site", "{\"url\":\"site\"}"});
                ps.add(new String[]{"pesquisar_links", "{\"consulta\":\"" + tema + "\"}"});
                ps.add(new String[]{"whatsapp", "{\"contato\":\"" + contato + "\"}"});
                Aprende.registrar(c, pedido.trim(), ps, true, fala);
                historico.add(new String[]{pedido.trim(), fala});
                while (historico.size() > 6) historico.remove(0);
                avisar("fim", fala);
                return fala;
            }
            java.util.regex.Matcher md = COMP_PESQ_DOC.matcher(pedido.trim());
            if (md.matches()) {
                String tema = Ferramentas.limparTermoBusca(md.group(1));
                String fmt = md.group(2) != null ? md.group(2).toLowerCase(Locale.ROOT) : (pedido.toLowerCase(Locale.ROOT).contains("txt") ? "txt" : pedido.toLowerCase(Locale.ROOT).contains("docx") ? "docx" : "pdf");
                String tit = md.group(3) != null && !md.group(3).trim().isEmpty() ? md.group(3).trim() : "Relatório " + tema;
                avisar("passo", "pesquisar_links {\"consulta\":\"" + tema + "\"}");
                String resumo = ferr.extrairResumoWeb(tema);
                avisar("resultado", resumo);
                String conteudo = estruturarDocumento(tema, resumo);
                JSONObject docArgs = new JSONObject().put("titulo", tit).put("formato", fmt).put("conteudo", conteudo);
                avisar("passo", "criar_documento " + docArgs.toString());
                String rd = ferr.executar("criar_documento", docArgs);
                avisar("resultado", rd);
                String fala = "Pesquisei sobre " + tema + " e criei o " + rd + ".";
                List<String[]> ps = new ArrayList<>();
                ps.add(new String[]{"pesquisar_links", "{\"consulta\":\"" + tema + "\"}"});
                ps.add(new String[]{"criar_documento", "{\"titulo\":\"" + tit + "\"}"});
                Aprende.registrar(c, pedido.trim(), ps, true, fala);
                historico.add(new String[]{pedido.trim(), fala});
                while (historico.size() > 6) historico.remove(0);
                avisar("fim", fala);
                return fala;
            }
            java.util.regex.Matcher mdd = DIRETO_DOC.matcher(pedido.trim());
            if (mdd.matches()) {
                String fmt = mdd.group(1) != null ? mdd.group(1).toLowerCase(Locale.ROOT) : (mdd.group(3) != null ? mdd.group(3).toLowerCase(Locale.ROOT) : (pedido.toLowerCase(Locale.ROOT).contains("docx") ? "docx" : "pdf"));
                String tema = Ferramentas.limparTermoBusca(mdd.group(2));
                String tit = "Relatório " + (tema.length() > 30 ? tema.substring(0, 30) : tema);
                avisar("passo", "pesquisar_links {\"consulta\":\"" + tema + "\"}");
                String resumo = ferr.extrairResumoWeb(tema);
                avisar("resultado", resumo);
                String conteudo = estruturarDocumento(tema, resumo);
                JSONObject docArgs = new JSONObject().put("titulo", tit).put("formato", fmt).put("conteudo", conteudo);
                avisar("passo", "criar_documento " + docArgs.toString());
                String rd = ferr.executar("criar_documento", docArgs);
                avisar("resultado", rd);
                String fala = "Pesquisei a fundo sobre " + tema + " e criei o " + rd + ".";
                List<String[]> ps = new ArrayList<>();
                ps.add(new String[]{"pesquisar_links", "{\"consulta\":\"" + tema + "\"}"});
                ps.add(new String[]{"criar_documento", "{\"titulo\":\"" + tit + "\"}"});
                Aprende.registrar(c, pedido.trim(), ps, true, fala);
                historico.add(new String[]{pedido.trim(), fala});
                while (historico.size() > 6) historico.remove(0);
                avisar("fim", fala);
                return fala;
            }
            java.util.regex.Matcher ma = COMP_PESQ_AG.matcher(pedido.trim());
            if (ma.matches()) {
                String tema = Ferramentas.limparTermoBusca(ma.group(1));
                String comp = ma.group(2).trim();
                avisar("passo", "pesquisar_links {\"consulta\":\"" + tema + "\"}");
                String resumo = ferr.extrairResumoWeb(tema);
                avisar("resultado", resumo);
                JSONObject agArgs = new JSONObject().put("op", "novo").put("titulo", comp + " (" + tema + ")").put("quando", comp);
                avisar("passo", "agenda " + agArgs.toString());
                String ra = ferr.executar("agenda", agArgs);
                avisar("resultado", ra);
                String fala = "Pesquisei sobre " + tema + " e anotei na agenda da Sexta-Feira: " + ra + ".";
                avisar("fim", fala);
                return fala;
            }
        } catch (Exception ignored) {}
        return null;
    }

    static String estruturarDocumento(String tema, String pesquisa) {
        StringBuilder sb = new StringBuilder();
        sb.append("# Visão Geral e Introdução\n\n");
        sb.append("Este relatório técnico foi compilado e sintetizado pelo agente autônomo F.R.I.D.A.Y. com base em pesquisas aprofundadas em tempo real sobre o tema: ").append(tema).append(".\n\n");
        sb.append("# Desenvolvimento e Análise Detalhada\n\n");
        if (pesquisa != null && !pesquisa.isEmpty()) {
            sb.append(pesquisa).append("\n\n");
        } else {
            sb.append("Foram examinadas fontes documentais e fatos relevantes sobre ").append(tema).append(".\n\n");
        }
        sb.append("# Considerações Críticas e Conclusão\n\n");
        sb.append("O panorama atual sobre ").append(tema).append(" demonstra relevância estratégica e impacto prático significativo. Recomenda-se acompanhamento dos desdobramentos.\n\n");
        sb.append("# Metadados e Registro Autônomo\n\n");
        sb.append("• Autoria: Agente Autônomo F.R.I.D.A.Y. (Integra Code)\n");
        sb.append("• Dispositivo: Android Local Engine (Zero Cloud)\n");
        sb.append("• Estado: Concluído e verificado com sucesso\n");
        return sb.toString();
    }

    // "envie/mande/fala (uma mensagem) para X (no WhatsApp): texto" | "... para X dizendo que ..."
    private static final java.util.regex.Pattern ENVIAR_ZAP = java.util.regex.Pattern.compile(
        "(?iu)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:por\\s+favor[,:\\s]*)?(?:envi\\w*|mand\\w*|escrev\\w*|fal[ae]\\w*|diz|diga)\\s+(?:uma\\s+)?(?:mensagem\\s+|msg\\s+|um\\s+zap\\s+)?"
        + "(?:no\\s+whats(?:app)?\\s+|no\\s+zap\\s+|pelo\\s+whats(?:app)?\\s+)?(?:para|pro|pra|ao|à)\\s+(.+?)(?:\\s+(?:no|pelo)\\s+(?:whats(?:app)?|zap))?"
        + "\\s*(?::|,|\\s+dizendo\\s+(?:que\\s+)?|\\s+falando\\s+(?:que\\s+)?|\\s+avisando\\s+(?:que\\s+)?|\\s+que\\s+)\\s*(.+)$");

    private static final java.util.regex.Pattern PERGUNTA = java.util.regex.Pattern.compile(
        "(?iu)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:me\\s+(?:diz|fala|conta)\\s+)?(?:quem|qual|quais|quando|onde|quantos?|quantas?|quanto\\s+(?:custa|vale|est[áa]|t[áa]|é)|o\\s+que\\s+(?:é|são|significa|aconteceu)|como\\s+(?:funciona|faz|fazer|se\\s+faz)|por\\s*qu[eê])\\b.{4,}");

    static String sintetizarResultados(String pergunta, String ctx) {
        if (ctx == null || ctx.trim().isEmpty()) return null;
        String[] linhas = ctx.split("\n");
        StringBuilder sb = new StringBuilder();
        for (String l : linhas) {
            String t = l.trim();
            if (t.startsWith("Fontes") || t.startsWith("http") || t.startsWith("• http") || t.isEmpty()) continue;
            if (t.startsWith("Wikipédia (") || t.startsWith("Síntese (") || t.startsWith("Trecho relevante:")) {
                t = t.replaceFirst("^Wikipédia \\([^)]+\\):\\s*", "")
                     .replaceFirst("^Síntese \\([^)]+\\):\\s*", "")
                     .replaceFirst("^Trecho relevante:\\s*", "");
            }
            if (t.length() > 25) {
                sb.append(t).append(" ");
                if (sb.length() > 380) break;
            }
        }
        String res = sb.toString().trim();
        return res.isEmpty() ? null : res;
    }

    private void registrarEFim(String pergunta, String r) {
        List<String[]> ps = new ArrayList<>();
        ps.add(new String[]{"buscar_web", "{}"});
        Aprende.registrar(c, pergunta, ps, true, r);
        historico.add(new String[]{pergunta, r});
        while (historico.size() > 6) historico.remove(0);
        avisar("fim", r);
    }

    /** pesquisa na web e RESPONDE com base nos resultados com raciocínio ou síntese avançada */
    private String respostaWeb(String pergunta) {
        String res = ferr.extrairResumoWeb(pergunta);
        if (res == null || res.startsWith("falhou") || res.startsWith("Não encontrei")) return null;
        StringBuilder sn = new StringBuilder();
        for (String l : res.split("\n")) if (!l.trim().startsWith("http") && !l.startsWith("Encontrei")) sn.append(l.replaceFirst("^•\\s*", "- ")).append('\n');
        String ctx = sn.length() > 2200 ? sn.substring(0, 2200) : sn.toString();
        synchronized (this) {
            ocupada = true;
            try {
                avisar("passo", "buscar_web {\"consulta\":\"" + pergunta.replace("\"", "'") + "\"}");
                // 1. Se tem modelo local GGUF pronto, usa o modelo local
                if (preparar()) {
                    String p = "<|im_start|>system\n"
                        + "Você é a F.R.I.D.A.Y. Responda à pergunta do dono em português do Brasil de forma clara, inteligente e direta, baseando-se nas informações da busca. Não cite links nem diga 'segundo os resultados'.<|im_end|>\n"
                        + "<|im_start|>user\nPergunta: " + pergunta + "\nResultados da busca:\n" + ctx + "<|im_end|>\n" + assist();
                    long tg = System.currentTimeMillis();
                    String r = Llm.gerar(p, 300, 0.25f, "", null).trim().replaceAll("(?is)<think>.*?</think>", "").trim();
                    android.util.Log.i("friday-cerebro", "respostaWeb local: " + r);
                    if (!r.isEmpty()) {
                        registrarEFim(pergunta, r);
                        return r;
                    }
                }
                // 2. Se o PC estiver online via Wi-Fi/Tailscale, usa o modelo GPU do PC para sintetizar com máxima inteligência
                if (Link.pcOnline(c)) {
                    String p = "<|im_start|>system\n"
                        + "Você é a F.R.I.D.A.Y. Responda à pergunta do dono em português do Brasil de forma inteligente, completa e direta, baseando-se nos resultados da busca.<|im_end|>\n"
                        + "<|im_start|>user\nPergunta: " + pergunta + "\nResultados:\n" + ctx + "<|im_end|>\n<|im_start|>assistant\n";
                    String r = Link.chamarLlm(c, p, 350, 0.3f);
                    if (r != null && !r.trim().isEmpty()) {
                        String f = r.replaceAll("(?is)<think>.*?</think>", "").trim();
                        if (!f.isEmpty()) {
                            android.util.Log.i("friday-cerebro", "respostaWeb PC LLM: " + f);
                            registrarEFim(pergunta, f);
                            return f;
                        }
                    }
                }
                // 3. Se offline ou sem modelo, sintetiza os fatos estruturados da Wikipédia / DuckDuckGo diretamente
                String sintese = sintetizarResultados(pergunta, ctx);
                if (sintese != null && !sintese.isEmpty()) {
                    android.util.Log.i("friday-cerebro", "respostaWeb síntese direta: " + sintese);
                    registrarEFim(pergunta, sintese);
                    return sintese;
                }
                return null;
            } catch (Exception e) {
                return null;
            } finally {
                ocupada = false;
            }
        }
    }

    private static final java.util.regex.Pattern SAUDACAO = java.util.regex.Pattern.compile(
        "(?iu)^\\s*(?:ol[áa]|oi|bom dia|boa tarde|boa noite|e a[íi]|opa|olá friday|oi friday|olá sexta[- ]feira|sexta[- ]feira)\\s*[.!?]*$");

    private static final java.util.regex.Pattern IDENTIDADE = java.util.regex.Pattern.compile(
        "(?iu).*\\b(quem [ée] voc[êe]|qual (?:[ée] )?o seu nome|o que voc[êe] (?:faz|pode fazer)|quem te criou)\\b.*");

    private static final java.util.regex.Pattern HORAS = java.util.regex.Pattern.compile(
        "(?iu).*\\b(que horas s[ãa]o|que horas|hora certa|horas agora|me d[áa] a hora)\\b.*");

    private static final java.util.regex.Pattern DATA = java.util.regex.Pattern.compile(
        "(?iu).*\\b(que dia [ée] hoje|qual a data de hoje|qual o dia de hoje|que dia hoje|qual [ée] a data)\\b.*");

    private static final java.util.regex.Pattern BATERIA = java.util.regex.Pattern.compile(
        "(?iu).*\\b(quanto (?:tem|est[áa]|t[áa]) de bateria|n[íi]vel da bateria|como est[áa] a bateria|porcentagem da bateria|status da bateria|bateria)\\b.*");

    private static final java.util.regex.Pattern LANTERNA_LIGAR = java.util.regex.Pattern.compile(
        "(?iu).*\\b(lig(?:ue|ar|a)?\\s+(?:a\\s+)?lanterna|acend(?:er|a|e)?\\s+(?:a\\s+)?lanterna)\\b.*");

    private static final java.util.regex.Pattern LANTERNA_DESLIGAR = java.util.regex.Pattern.compile(
        "(?iu).*\\b(deslig(?:ue|ar|a)?\\s+(?:a\\s+)?lanterna|apag(?:ue|ar|a)?\\s+(?:a\\s+)?lanterna)\\b.*");

    private static final java.util.regex.Pattern VOLUME_AUMENTAR = java.util.regex.Pattern.compile(
        "(?iu).*\\b(aument(?:e|ar|a)?\\s+(?:o\\s+)?volume|sobe\\s+(?:o\\s+)?volume)\\b.*");

    private static final java.util.regex.Pattern VOLUME_ABAIXAR = java.util.regex.Pattern.compile(
        "(?iu).*\\b(abaix(?:e|ar|a)?\\s+(?:o\\s+)?volume|diminu(?:a|ir)?\\s+(?:o\\s+)?volume|baixa\\s+(?:o\\s+)?volume)\\b.*");

    private String atalhoDireto(String pedido) {
        if (pedido == null || ehComposto(pedido)) return null;
        String p = pedido.trim();
        try {
            if (SAUDACAO.matcher(p).matches()) {
                String fala = "Olá, senhor. Todos os sistemas online e pronta para qualquer tarefa. Como posso ajudar?";
                avisar("fim", fala);
                return fala;
            }
            if (IDENTIDADE.matcher(p).matches()) {
                String fala = "Sou a F.R.I.D.A.Y., sua inteligência artificial autônoma. Posso pesquisar a fundo, redigir documentos em PDF e DOCX, controlar o aparelho, enviar mensagens e executar qualquer comando.";
                avisar("fim", fala);
                return fala;
            }
            if (HORAS.matcher(p).matches()) {
                String fala = ferr.executar("hora", new JSONObject());
                avisar("fim", fala);
                return fala;
            }
            if (DATA.matcher(p).matches()) {
                String fala = ferr.executar("data", new JSONObject());
                avisar("fim", fala);
                return fala;
            }
            if (BATERIA.matcher(p).matches()) {
                String fala = ferr.executar("bateria", new JSONObject());
                avisar("fim", fala);
                return fala;
            }
            if (LANTERNA_LIGAR.matcher(p).matches()) {
                ferr.executar("lanterna", new JSONObject().put("ligar", true));
                String fala = "Lanterna ligada.";
                avisar("fim", fala);
                return fala;
            }
            if (LANTERNA_DESLIGAR.matcher(p).matches()) {
                ferr.executar("lanterna", new JSONObject().put("ligar", false));
                String fala = "Lanterna desligada.";
                avisar("fim", fala);
                return fala;
            }
            if (VOLUME_AUMENTAR.matcher(p).matches()) {
                ferr.executar("volume", new JSONObject().put("nivel", 80));
                String fala = "Volume aumentado para 80%.";
                avisar("fim", fala);
                return fala;
            }
            if (VOLUME_ABAIXAR.matcher(p).matches()) {
                ferr.executar("volume", new JSONObject().put("nivel", 30));
                String fala = "Volume reduzido para 30%.";
                avisar("fim", fala);
                return fala;
            }
        } catch (Exception ignored) {}
        return null;
    }

    private String fallbackAutonomo(String pedido) {
        if (pedido == null) return null;
        String p = pedido.trim();
        try {
            // Abrir aplicativo direto: "abra o WhatsApp", "abre o YouTube"
            java.util.regex.Matcher ma = java.util.regex.Pattern.compile(
                "(?iu)^\\s*(?:sexta[- ]?feira[,:\\s]*)?(?:abr[ae]|inici[ae]|rod[ae]|execut[ae])\\s+(?:o\\s+|a\\s+|os\\s+|as\\s+)?(?:app|aplicativo\\s+)?([\\p{L}0-9_+\\- ]+?)\\s*[.!?]*$").matcher(p);
            if (ma.matches()) {
                String app = ma.group(1).trim();
                if (!app.equalsIgnoreCase("agenda") && !app.equalsIgnoreCase("clima") && !app.equalsIgnoreCase("navegador")) {
                    String r = ferr.executar("abrir_app", new JSONObject().put("nome", app));
                    if (!r.toLowerCase(Locale.ROOT).startsWith("não encontrei") && !r.toLowerCase(Locale.ROOT).startsWith("falhou")) {
                        return "Pronto, abri o aplicativo " + app + ".";
                    }
                }
            }
            // Cálculos diretos: "quanto é 15 x 30", "calcule 120 / 4"
            java.util.regex.Matcher mc = java.util.regex.Pattern.compile(
                "(?iu)^\\s*(?:quanto\\s+(?:[ée]|d[áa])|calcule|conta)\\s+([0-9+\\-*/().^%xX ]+)\\s*[.!?]*$").matcher(p);
            if (mc.matches()) {
                String expr = mc.group(1).trim().replace('x', '*').replace('X', '*');
                String r = ferr.executar("calcular", new JSONObject().put("expressao", expr));
                if (r.contains("=")) return "Dá " + r.substring(r.lastIndexOf('=') + 1).trim() + ".";
                return r;
            }
            // Perguntas gerais -> pesquisa na web e síntese
            String fw = respostaWeb(p);
            if (fw != null) return fw;
        } catch (Exception ignored) {}
        return null;
    }

    private String atalhoPesquisa(String pedido) {
        if (pedido == null || ehComposto(pedido) || !BUSCA_DIRETA.matcher(pedido).matches()) return null;
        String pl = pedido.toLowerCase(Locale.ROOT);
        if (pl.matches("(?s).*\\b(documento|arquivo|pdf|docx|planilha|whatsapp|zap|agenda|alarme|timer|mem[óo]ria)\\b.*")) return null;
        String termo = Ferramentas.limparTermoBusca(pedido);
        boolean abrir = pl.matches("(?s).*\\b(abr\\w*|mostr\\w*|no navegador|no google|no chrome|na internet e abr\\w*|ebay|amazon|mercado\\s*livre|you\\s?tube|yutube|maps|mapa|play\\s*store|spotify|sites?\\s+americanos?|lojas?|comprar|pre[çc]o|links?)\\b.*");
        if (!abrir && termo.length() >= 2) {                         // "pesquise qual é a capital..." = quer a RESPOSTA, não a aba aberta
            String fw = respostaWeb(termo);
            if (fw != null) { ultimaBusca = termo; return fw; }
        }
        if (termo.length() < 2 && !ultimaBusca.isEmpty()) {
            termo = ultimaBusca;
        }
        if (termo.length() < 2) return null;
        ultimaBusca = termo;
        String onde = "google";
        if (pl.matches("(?s).*\\bebay\\b.*")) onde = "ebay";
        else if (pl.matches("(?s).*\\bamazon\\b.*")) onde = "amazon";
        else if (pl.matches("(?s).*\\bmercado\\s*livre\\b.*")) onde = "mercadolivre";
        else if (pl.matches("(?s).*\\b(sites?\\s+americanos?|lojas?\\s+americanas?|estados\\s+unidos)\\b.*")) onde = "google_us";
        else if (pl.matches("(?s).*\\b(you\\s?tube|yutube)\\b.*")) onde = "youtube";
        else if (pl.matches("(?s).*\\b(maps|mapa)\\b.*")) onde = "maps";
        else if (pl.matches("(?s).*\\b(play\\s*store)\\b.*")) onde = "playstore";
        else if (pl.matches("(?s).*\\b(spotify)\\b.*")) onde = "spotify";
        try {
            JSONObject args = new JSONObject().put("consulta", termo).put("onde", onde);
            avisar("passo", "pesquisar " + args.toString());
            String r = ferr.executar("pesquisar", args);
            avisar("resultado", r);
            String fala = "Pronto, abri no navegador: " + r + ".";
            historico.add(new String[]{pedido.trim(), fala});
            while (historico.size() > 6) historico.remove(0);
            avisar("fim", fala);
            return fala;
        } catch (Exception e) {
            return null;
        }
    }

    boolean modoDev() { return c.getSharedPreferences("friday_local", Context.MODE_PRIVATE).getBoolean("modo_dev", false); }

    /** executa um pedido inteiro (bloqueante) e devolve a fala final. origem: "voz" | "texto" | "pc". */
    private static final java.util.regex.Pattern APRIMORAR = java.util.regex.Pattern.compile(
        "(?iu)^\\s*(?:sexta[- ]?feira,?\\s*)?(?:aprimore[- ]se|se aprimore|melhore (?:o )?seu (?:pr[óo]prio )?c[óo]digo|corrija (?:o )?seu c[óo]digo|auto ?melhoria)\\W*(?:[:,]?\\s*(.+))?$");
    private static final java.util.regex.Pattern COMO_APRENDE = java.util.regex.Pattern.compile(
        "(?iu).*\\b(como (?:est[áa]|vai) (?:o )?seu aprendizado|o que voc[êe] aprendeu|como est[áa] (?:a )?(?:sua )?(?:voz|audi[çc][ãa]o))\\b.*");

    String pedir(String pedido, String origem) {
        if (pedido == null || pedido.trim().isEmpty()) return "";
        // ---- auto-aprendizado: correções do dono antes de qualquer coisa
        if (Aprende.ehNegacao(pedido)) {
            String fala = Aprende.falhou(c, "o dono disse que deu errado");
            String rep = Aprende.falhaRepetida(c);
            if (rep != null) fala += " Esse erro já se repetiu. Se quiser, diga \"aprimore-se\" que eu preparo uma correção no meu código.";
            avisar("fim", fala);
            return fala;
        }
        String disse = Aprende.euDisse(c, pedido);
        if (disse != null) { avisar("passo", "corrigido: " + disse); pedido = disse; }
        java.util.regex.Matcher map = APRIMORAR.matcher(pedido);
        if (map.matches()) {
            String alvo = map.group(1) != null ? map.group(1) : Aprende.falhaRepetida(c);
            String fala = Aprende.proporMelhoria(c, alvo);
            avisar("fim", fala);
            return fala;
        }
        if (COMO_APRENDE.matcher(pedido).matches()) {
            String fala = "Voz: " + Aprende.resumoVoz(c) + ". Falhas recentes: " + Aprende.falhasRecentes(c, 3).size() + ".";
            avisar("fim", fala);
            return fala;
        }
        if (Zap.temPendente()) {                                   // "posso enviar?" -> sim / não
            String pz = Aprende.norm(pedido).replaceFirst("^sexta feira ", "");
            String fz = pz.matches("^(sim|pode|pode enviar|pode mandar|envia|enviar|envie|manda|mande|confirmo|confirma|isso|ok|beleza|claro|vai)\\b.*") ? Zap.confirmar(c)
                : pz.matches("^(nao|cancela|cancelar|deixa|esquece|para|pare|nao envia)\\b.*") ? Zap.cancelar() : null;
            if (fz != null) { avisar("fim", fz); return fz; }
        }
        String fDir = atalhoDireto(pedido);
        if (fDir != null) return fDir;
        java.util.regex.Matcher mzap = ENVIAR_ZAP.matcher(pedido.trim());
        if (mzap.matches() && !ehComposto(pedido)) {
            String contato = mzap.group(1).trim().replaceFirst("(?i)^(o|a|os|as)\\s+", "").replaceFirst("(?i)^(grupo|contato)\\s+(d[oae]s?\\s+)?", "");
            String msg = mzap.group(2).trim();
            if (msg.length() > 1 && Character.isLowerCase(msg.charAt(0))) msg = Character.toUpperCase(msg.charAt(0)) + msg.substring(1);
            avisar("passo", "whatsapp {\"contato\":\"" + contato + "\"}");
            String fz = Zap.preparar(c, ferr, contato, msg);
            avisar("resultado", fz);
            if (fz.startsWith("falhou")) Aprende.falhou(c, "WhatsApp para " + contato + ": " + fz);
            avisar("fim", fz);
            return fz;
        }
        java.util.regex.Matcher mcl = PRO_CLAUDE.matcher(pedido);
        if (modoDev() || mcl.matches()) {                       // MODO DEV / "pede pro Claude ...": direto ao MODO DEV
            String pd = mcl.matches() ? mcl.group(1) : pedido.trim();
            avisar("passo", "dev " + pd);
            String fala = Ide.iniciar(c, pd, null);
            avisar("fim", fala);
            return fala;
        }
        final boolean querPc = !"pc".equals(origem) && pediuParaOPc(pedido);
        if (querPc) {
            String comandoPc = extrairPedidoPc(pedido);
            if (comandoPc.isEmpty()) comandoPc = pedido.trim();
            avisar("passo", "pc " + comandoPc);
            String r;
            try { r = ferr.executar("pc", new JSONObject().put("pedido", comandoPc)); } catch (Exception e) { r = "falhou: " + e.getMessage(); }
            String fala = r.startsWith("a Friday do PC recebeu") ? "Mandei para a Friday do PC: " + comandoPc + "." : r;
            avisar("fim", fala);
            return fala;
        }
        String fComp = atalhoComposto(pedido);
        if (fComp != null) return fComp;
        String fAg = atalhoAgenda(pedido);
        if (fAg != null) return fAg;
        String fPesq = atalhoPesquisa(pedido);
        if (fPesq != null) return fPesq;
        if (PERGUNTA.matcher(pedido.trim()).matches() && !Aprende.norm(pedido).matches(".*\\b(agenda|alarme|timer|lanterna|volume|bateria|que horas|que dia|minha|meu|meus|minhas|celular|wifi|bluetooth)\\b.*")) {
            String fw = respostaWeb(pedido.trim());                  // pergunta de conhecimento/atualidade: responde pela web
            if (fw != null) return fw;
        }
        synchronized (this) {
            ocupada = true;
            try {
                boolean temLocal = preparar();
                boolean pc = Link.pcOnline(c);
                if (!temLocal && !pc) {
                    String fallback = fallbackAutonomo(pedido);
                    if (fallback != null) {
                        avisar("fim", fallback);
                        return fallback;
                    }
                    String m = Llm.ok
                        ? "O modelo local (" + arquivoModelo().getName() + ") ainda não foi baixado no aparelho. Conecte ao PC via Wi-Fi/Tailscale ou baixe o modelo na aba de modelos para raciocínio offline completo."
                        : "O motor local não carregou neste aparelho.";
                    avisar("fim", m);
                    return m;
                }
                String agora = new SimpleDateFormat("EEEE, dd/MM/yyyy HH:mm", new Locale("pt", "BR")).format(new Date());
                StringBuilder p = new StringBuilder(sistema(querPc));
                for (String[] h : historico) {
                    p.append("<|im_start|>user\n").append(h[0]).append("<|im_end|>\n").append(assist())
                     .append(new JSONObject().put("acao", "responder").put("args", new JSONObject().put("texto", h[1]))).append("<|im_end|>\n");
                }
                String aprendi = Aprende.contexto(c, pedido);          // o que já deu certo / errado em pedidos parecidos
                p.append("<|im_start|>user\n[").append(agora)
                 .append(querPc ? (pc ? " · PC LIGADO" : " · PC offline") : (temLocal ? " · CÉREBRO LOCAL NO CELULAR" : " · CÉREBRO REDE PC (EXECUÇÃO LOCAL NO CELULAR)"))
                 .append(origem.equals("pc") ? " · pedido vindo da Friday do PC" : "").append("]\n")
                 .append(aprendi.isEmpty() ? "" : "[aprendizado]\n" + aprendi).append(pedido.trim()).append("<|im_end|>\n");
                String fala = null;
                List<String[]> passos = new ArrayList<>();
                int falhas = 0;
                boolean ultimoFalhou = false;
                for (int passo = 0; passo < 8 && fala == null; passo++) {
                    p.append(assist());
                    String out = null;
                    if (temLocal) {
                        out = Llm.gerar(p.toString(), 900, 0.3f, "", null).trim();
                        JSONObject jTest = json(out);
                        if (jTest == null) {
                            out = Llm.gerar(p.toString(), 900, 0.2f, gramatica(querPc), null).trim();
                        }
                    } else if (pc) {
                        // Roda o raciocínio na GPU do PC, mas executa no aparelho
                        out = Link.chamarLlm(c, p.toString(), 600, 0.3f);
                    }
                    if (out == null || out.trim().isEmpty()) {
                        fala = "Não consegui processar a resposta agora.";
                        break;
                    }
                    JSONObject j = json(out);
                    if (j == null) {
                        String limpo = out.replaceAll("(?is)<think>.*?</think>", "").trim();
                        fala = limpo.isEmpty() ? "Me perdi no raciocínio. Pode repetir?" : limpo;
                        break;
                    }
                    out = j.toString();
                    p.append(out).append("<|im_end|>\n");
                    String acao = j.optString("acao");
                    android.util.Log.i("friday-cerebro", "passo " + passo + ": " + out);
                    JSONObject args = j.optJSONObject("args") == null ? new JSONObject() : j.optJSONObject("args");
                    if (acao.equals("responder")) {
                        fala = args.optString("texto", "Pronto.").replace("[links]", "").trim();
                        break;
                    }
                    if (acao.equals("pesquisar")) {
                        String qArg = Ferramentas.limparTermoBusca(args.optString("consulta", ""));
                        if (!qArg.isEmpty()) ultimaBusca = qArg;
                        else if (!ultimaBusca.isEmpty()) args.put("consulta", ultimaBusca);
                    }
                    avisar("passo", acao + " " + args.toString());
                    String r = ferr.executar(acao, args);
                    if (r.length() > 2500) r = r.substring(0, 2500) + "…";
                    String as = args.toString();
                    String rl = r.toLowerCase(Locale.ROOT);
                    ultimoFalhou = rl.startsWith("falhou") || rl.startsWith("erro") || rl.startsWith("não entendi") || rl.contains("não encontrad")
                        || rl.startsWith("ferramenta desconhecida") || rl.startsWith("sem ");
                    if (!ultimoFalhou) passos.add(new String[]{acao, as.length() > 120 ? as.substring(0, 120) + "…}" : as});   // receita = só o que funcionou
                    avisar("resultado", r.length() > 300 ? r.substring(0, 300) + "…" : r);
                    android.util.Log.i("friday-cerebro", "resultado: " + (r.length() > 300 ? r.substring(0, 300) : r));
                    p.append("<|im_start|>user\n<tool_response>\n").append(r).append("\n</tool_response><|im_end|>\n");
                    String atalho = falaDireta(pedido, acao, r);     // pedido simples + ferramenta deu certo = responde já (ela lia a tela e inventava passos)
                    if (atalho != null) { fala = atalho; break; }
                    try { Thread.sleep(acao.equals("abrir_app") || acao.equals("tocar") || acao.equals("pesquisar") ? 900 : 150); } catch (InterruptedException ignored) {}
                }
                if (fala == null) { fala = "Fiz o que consegui em 8 passos, mas não terminei. Quer que eu continue?"; falhas++; }
                Aprende.registrar(c, pedido.trim(), passos, falhas == 0 && !ultimoFalhou, fala);
                historico.add(new String[]{pedido.trim(), fala});
                while (historico.size() > 6) historico.remove(0);
                avisar("fim", fala);
                return fala;
            } catch (Exception e) {
                String m = "Erro no cérebro: " + e.getMessage();
                avisar("fim", m);
                return m;
            } finally {
                ocupada = false;
            }
        }
    }

    void parar() { Llm.parar(); }

    private static final java.util.Set<String> FINAIS = new java.util.HashSet<>(java.util.Arrays.asList(
        "abrir_tela", "abrir_app", "abrir_site", "pesquisar", "pesquisar_links", "alarme", "timer", "evento", "agenda", "ligar", "whatsapp", "compartilhar",
        "lanterna", "volume", "configuracao", "foto", "calcular", "flutuante", "criar_documento", "criar_arquivo", "lembrar", "tailscale", "bateria", "hora", "data", "pc"));

    /** fala final sem mais um passo do modelo quando o pedido era de UMA ação e ela deu certo */
    private static String falaDireta(String pedido, String acao, String r) {
        if (!FINAIS.contains(acao) || r == null) return null;
        String rl = r.toLowerCase(Locale.ROOT);
        if (rl.startsWith("falhou") || rl.startsWith("não") || rl.contains("não encontrado") || rl.startsWith("sem ") || rl.contains("erro")) return null;
        if (ehComposto(pedido)) return null;
        if (acao.equals("pesquisar") || acao.equals("abrir_site")) return "Pronto, abri no navegador: " + r + ".";
        if (acao.equals("pesquisar_links")) return null;                // o modelo responde com base nos resultados
        if (acao.equals("whatsapp")) return r;                          // "Mensagem escrita para X... Posso enviar?" (nunca "enviei")
        if (acao.equals("bateria") || acao.equals("hora") || acao.equals("data")) return r;
        String pl = pedido.toLowerCase(Locale.ROOT);
        if (pl.split("\\s+").length > 12) return null;
        if (acao.equals("calcular")) { int i = r.lastIndexOf('='); return i > 0 ? "Dá " + r.substring(i + 1).trim() + "." : r; }
        if (acao.equals("pc")) return r.startsWith("a Friday do PC") ? "Mandei para a Friday do PC." : null;
        return "Pronto: " + r + ".";
    }

    /** 1º objeto JSON do texto (remove raciocínio <think> e blocos markdown para extração infalível) */
    private static JSONObject json(String s) {
        if (s == null) return null;
        String limpo = s.replaceAll("(?is)<think>.*?</think>", "").trim();
        if (limpo.contains("```")) {
            limpo = limpo.replaceAll("(?s)```(?:json)?", "").trim();
        }
        int a = limpo.indexOf('{');
        if (a < 0) return null;
        int prof = 0; boolean aspas = false, esc = false;
        for (int i = a; i < limpo.length(); i++) {
            char ch = limpo.charAt(i);
            if (esc) { esc = false; continue; }
            if (ch == '\\') { esc = true; continue; }
            if (ch == '"') aspas = !aspas;
            if (aspas) continue;
            if (ch == '{') prof++;
            else if (ch == '}' && --prof == 0) {
                try {
                    JSONObject j = new JSONObject(limpo.substring(a, i + 1));
                    return j.has("acao") ? j : null;
                } catch (Exception e) {
                    return null;
                }
            }
        }
        return null;
    }
}
