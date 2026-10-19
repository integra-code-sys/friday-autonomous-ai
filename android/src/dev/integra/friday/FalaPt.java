package dev.integra.friday;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Texto -> fala pt-BR (port enxuto do daemon/fala_pt.py do PC): a voz neural não lê algarismos, então números, horas,
 *  datas, dinheiro, %, ordinais, documentos e telefones viram palavras antes de sintetizar. */
final class FalaPt {
    private FalaPt() {}

    private static final String[] UN = {"zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze",
        "doze", "treze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"};
    private static final String[] DZ = {"", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"};
    private static final String[] CT = {"", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
        "oitocentos", "novecentos"};
    private static final String[] MES = {"janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
        "outubro", "novembro", "dezembro"};
    private static final String[] ORD_U = {"", "primeiro", "segundo", "terceiro", "quarto", "quinto", "sexto", "sétimo", "oitavo", "nono"};
    private static final String[] ORD_D = {"", "décimo", "vigésimo", "trigésimo", "quadragésimo", "quinquagésimo", "sexagésimo",
        "septuagésimo", "octogésimo", "nonagésimo"};

    private static String ate999(int n) {
        if (n == 100) return "cem";
        StringBuilder s = new StringBuilder();
        int c = n / 100, r = n % 100;
        if (c > 0) s.append(CT[c]);
        if (r > 0) {
            if (s.length() > 0) s.append(" e ");
            if (r < 20) s.append(UN[r]);
            else { s.append(DZ[r / 10]); if (r % 10 > 0) s.append(" e ").append(UN[r % 10]); }
        }
        return s.toString();
    }

    static String cardinal(long n) {
        if (n < 0) return "menos " + cardinal(-n);
        if (n < 20) return UN[(int) n];
        long[] esc = {1_000_000_000_000L, 1_000_000_000L, 1_000_000L, 1000L};
        String[][] nom = {{"trilhão", "trilhões"}, {"bilhão", "bilhões"}, {"milhão", "milhões"}, {"mil", "mil"}};
        StringBuilder s = new StringBuilder();
        long resto = n;
        for (int i = 0; i < esc.length; i++) {
            long q = resto / esc[i];
            if (q == 0) continue;
            resto %= esc[i];
            if (s.length() > 0) s.append(", ");
            if (i == 3 && q == 1) s.append("mil");
            else s.append(cardinal(q)).append(' ').append(q == 1 ? nom[i][0] : nom[i][1]);
        }
        if (resto > 0) {
            if (s.length() > 0) s.append(resto < 100 || resto % 100 == 0 ? " e " : " ");
            s.append(ate999((int) resto));
        }
        return s.toString().replace(", ", " ");
    }

    /** cardinal feminino (hora é feminina): 1 -> "uma", 22 -> "vinte e duas", 200 -> "duzentas" */
    static String fem(long n) {
        return n >= 1000 ? cardinal(n) : cardinal(n).replaceAll("\\bum\\b", "uma").replaceAll("\\bdois\\b", "duas").replaceAll("entos\\b", "entas");
    }

    /** "às 12:00" -> "ao meio-dia", "00:30" -> "meia-noite e trinta", "21:45" -> "vinte e uma e quarenta e cinco", "às 1h" -> "à uma hora" */
    private static String hora(Matcher m) {
        String as = m.group(1);
        int h = Integer.parseInt(m.group(2)), mi = m.group(3) == null ? 0 : Integer.parseInt(m.group(3));
        boolean comMin = m.group(3) != null;
        if (h > 23 || mi > 59)                                         // não é hora do dia: duração ("48h") ou placar
            return (as == null ? "" : as + " ") + (comMin ? cardinal(h) + " e " + cardinal(mi) : fem(h) + " horas");
        boolean especial = comMin || as != null;                       // "12h" solto pode ser duração ("jejum de 12h")
        String fala = especial && h == 0 ? "meia-noite" : especial && h == 12 ? "meio-dia" : fem(h);
        if (comMin) fala += mi > 0 ? " e " + cardinal(mi) : h % 12 == 0 ? "" : " em ponto";
        else if (!fala.startsWith("mei")) fala += h == 1 ? " hora" : " horas";
        if (as == null) return fala;
        String art = h == 12 ? "ao" : h <= 1 ? "à" : as;               // "ao meio-dia", "à meia-noite", "à uma"
        return (Character.isUpperCase(as.charAt(0)) ? Character.toUpperCase(art.charAt(0)) + art.substring(1) : art) + " " + fala;
    }

    static String ordinal(int n) {
        if (n <= 0 || n >= 100) return cardinal(n);
        return (ORD_D[n / 10] + " " + ORD_U[n % 10]).trim();
    }

    private static String digitos(String s) {
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) if (Character.isDigit(c)) b.append(b.length() > 0 ? " " : "").append(UN[c - '0']);
        return b.toString();
    }

    private static String sub(String t, String re, java.util.function.Function<Matcher, String> f) {
        Matcher m = Pattern.compile(re).matcher(t);
        StringBuffer sb = new StringBuffer();
        while (m.find()) m.appendReplacement(sb, Matcher.quoteReplacement(f.apply(m)));
        m.appendTail(sb);
        return sb.toString();
    }

    private static String decimal(String inteiro, String frac) {
        String f = frac.startsWith("0") ? digitos(frac) : cardinal(Long.parseLong(frac));
        return cardinal(Long.parseLong(inteiro)) + " vírgula " + f;
    }

    static String normalizar(String t) {
        if (t == null) return "";
        t = t.replace("Sra.", "senhora").replace("Sr.", "senhor").replace("Dra.", "doutora").replace("Dr.", "doutor")
             .replace("etc.", "etcétera").replace("WhatsApp", "uótsap").replace("Zap", "zap").replace("YouTube", "iutúbi")
             .replace("Google", "gúgou").replace("GitHub", "guít-rãb").replace("Meet", "míti").replace("Iann", "Ían")
             .replace("F.R.I.D.A.Y.", "Sexta-Feira").replace("PC", "pê cê").replace("PDF", "pê dê éfe").replace("CPF", "cê pê éfe")
             .replace("deploy", "deplói").replace("feedback", "fídibéqui").replace("setup", "sêtápi").replace("backup", "bécápi")
             .replace("dashboard", "déshbord").replace("layout", "laiáute").replace("bugs", "bãguis").replace("bug", "bãgui")
             .replace("download", "daunlôud").replace("upload", "apilôud").replace("call", "cól").replace("Wi-Fi", "uái-fái")
             .replace("WiFi", "uái-fái").replace("wifi", "uái-fái").replace("Bluetooth", "blutúfi")
             .replace("g/cm³", " gramas por centímetro cúbico").replace("g/cm3", " gramas por centímetro cúbico")
             .replace("kg/m³", " quilos por metro cúbico").replace("°C", " graus célsius").replace("°F", " graus fahrenheit");
        // documentos e telefones: dígito a dígito
        t = sub(t, "\\b\\d{3}\\.\\d{3}\\.\\d{3}-\\d{2}\\b", m -> String.join(", ", digitos(m.group().substring(0, 3)),
            digitos(m.group().substring(4, 7)), digitos(m.group().substring(8, 11)), digitos(m.group().substring(12))));
        t = sub(t, "\\(?\\b(\\d{2})\\)?\\s?(9?\\d{4})[-\\s](\\d{4})\\b", m -> cardinal(Integer.parseInt(m.group(1))) + ", "
            + digitos(m.group(2)) + ", " + digitos(m.group(3)));
        t = sub(t, "\\b\\d{7,}\\b", m -> digitos(m.group()));
        // datas e horas
        t = sub(t, "\\b(\\d{1,2})/(\\d{1,2})/(\\d{4})\\b", m -> {
            int d = Integer.parseInt(m.group(1)), mm = Integer.parseInt(m.group(2));
            return mm >= 1 && mm <= 12 ? (d == 1 ? "primeiro" : cardinal(d)) + " de " + MES[mm - 1] + " de " + cardinal(Long.parseLong(m.group(3))) : m.group();
        });
        t = sub(t, "\\b(\\d{1,2})/(\\d{1,2})\\b", m -> {
            int d = Integer.parseInt(m.group(1)), mm = Integer.parseInt(m.group(2));
            return mm >= 1 && mm <= 12 && d >= 1 && d <= 31 ? (d == 1 ? "primeiro" : cardinal(d)) + " de " + MES[mm - 1] : m.group();
        });
        // horas (antes "15h" ficava em algarismo, "21:45" virava "vinte e um", "00:30" "zero e trinta")
        t = sub(t, "(?<![\\p{L}\\d])(?:([àÀaA]s)\\s+)?(\\d{1,2})(?:[:h](\\d{2})|\\s?hs?)(?![\\p{L}\\d])", FalaPt::hora);
        t = sub(t, "(?<![\\d.,])\\b(\\d{1,3})\\s+(horas?)\\b", m -> fem(Long.parseLong(m.group(1))) + " " + m.group(2));   // "1 hora" -> "uma hora"
        t = t.replaceAll("\\b1 de (?=(?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\\b)", "primeiro de ");
        // dinheiro, porcentagem, graus, ordinais
        t = sub(t, "R\\$\\s*(\\d{1,3}(?:\\.\\d{3})*|\\d+)(?:,(\\d{1,2}))?", m -> {
            long r = Long.parseLong(m.group(1).replace(".", ""));
            int c = m.group(2) == null ? 0 : Integer.parseInt((m.group(2) + "0").substring(0, 2));
            String s = r > 0 ? cardinal(r) + (r == 1 ? " real" : " reais") : "";
            if (c > 0) s += (s.isEmpty() ? "" : " e ") + cardinal(c) + (c == 1 ? " centavo" : " centavos");
            return s.isEmpty() ? "zero reais" : s;
        });
        t = sub(t, "(\\d+)(?:,(\\d+))?\\s*%", m -> (m.group(2) == null ? cardinal(Long.parseLong(m.group(1))) : decimal(m.group(1), m.group(2))) + " por cento");
        t = sub(t, "(\\d+)\\s*°\\s*C?", m -> cardinal(Long.parseLong(m.group(1))) + " graus");
        t = sub(t, "\\b(\\d{1,2})\\s*[ºo](?!\\w)", m -> ordinal(Integer.parseInt(m.group(1))));
        t = sub(t, "\\b(\\d{1,2})\\s*ª", m -> ordinal(Integer.parseInt(m.group(1))).replaceAll("o\\b", "a"));
        // números soltos (milhar com ponto, decimal com vírgula)
        t = sub(t, "\\b\\d{1,3}(?:\\.\\d{3})+(?:,\\d+)?\\b|\\b\\d+(?:,\\d+)?\\b", m -> {
            String g = m.group().replace(".", "");
            int v = g.indexOf(',');
            return v > 0 ? decimal(g.substring(0, v), g.substring(v + 1)) : cardinal(Long.parseLong(g));
        });
        return t.replace("&", " e ").replace("+", " mais ").replace("=", " igual a ").replaceAll("\\s+", " ").trim();
    }
}
