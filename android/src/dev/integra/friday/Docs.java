package dev.integra.friday;

import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.pdf.PdfDocument;
import android.net.Uri;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.Layout;
import android.text.StaticLayout;
import android.text.TextPaint;

import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Documentos criados pela Friday local: PDF (A4, paginado), DOCX (Word mínimo válido) ou TXT, em Documentos/Friday. */
final class Docs {
    private Docs() {}

    static String criar(Context c, String titulo, String formato, String conteudo) throws Exception {
        if (titulo == null || titulo.trim().isEmpty()) titulo = "Documento";
        if (conteudo == null) conteudo = "";
        formato = formato == null ? "pdf" : formato.toLowerCase(Locale.ROOT).replace(".", "").trim();
        if (titulo.matches("(?i).*\\.(pdf|docx|txt|md|html|py|json|csv|js)$")) {
            int dot = titulo.lastIndexOf('.');
            formato = titulo.substring(dot + 1).toLowerCase(Locale.ROOT);
            titulo = titulo.substring(0, dot);
        }
        if (!formato.matches("docx|txt|md|html|py|json|csv|js|pdf")) formato = "pdf";
        byte[] dados;
        String mime;
        switch (formato) {
            case "docx":
                dados = docx(titulo, conteudo);
                mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
                break;
            case "html":
                dados = conteudo.getBytes(StandardCharsets.UTF_8);
                mime = "text/html";
                break;
            case "json":
                dados = conteudo.getBytes(StandardCharsets.UTF_8);
                mime = "application/json";
                break;
            case "csv":
                dados = conteudo.getBytes(StandardCharsets.UTF_8);
                mime = "text/csv";
                break;
            case "py": case "js":
                dados = conteudo.getBytes(StandardCharsets.UTF_8);
                mime = "text/plain";
                break;
            case "txt": case "md":
                dados = (titulo + "\n\n" + conteudo + "\n").getBytes(StandardCharsets.UTF_8);
                mime = "text/plain";
                break;
            default:
                dados = pdf(titulo, conteudo);
                mime = "application/pdf";
        }
        String nome = titulo.replaceAll("[\\\\/:*?\"<>|]", "").trim();
        if (nome.isEmpty()) nome = "Documento";
        nome = nome + " " + new SimpleDateFormat("dd-MM HHmm", Locale.ROOT).format(new Date()) + "." + formato;
        ContentValues v = new ContentValues();
        v.put(MediaStore.MediaColumns.DISPLAY_NAME, nome);
        v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
        v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOCUMENTS + "/Friday");
        Uri u = null;
        try {
            u = c.getContentResolver().insert(MediaStore.Files.getContentUri("external"), v);
            if (u != null) {
                try (OutputStream o = c.getContentResolver().openOutputStream(u)) { o.write(dados); }
            }
        } catch (Exception ignored) {}
        if (u == null) {
            java.io.File dir = new java.io.File(c.getExternalFilesDir(null), "Documentos");
            dir.mkdirs();
            java.io.File arq = new java.io.File(dir, nome);
            java.nio.file.Files.write(arq.toPath(), dados);
            return "documento criado: " + arq.getAbsolutePath();
        }
        try {
            c.startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(u, mime)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_GRANT_READ_URI_PERMISSION));
        } catch (Exception ignored) {}
        return "documento criado: Documentos/Friday/" + nome;
    }

    private static byte[] pdf(String titulo, String corpo) throws Exception {
        PdfDocument doc = new PdfDocument();
        int W = 595, H = 842, M = 44;                       // A4 em pontos (595x842)
        int contentW = W - 2 * M;

        // Tintas do design Stark / Cyber
        Paint pOrange = new Paint(Paint.ANTI_ALIAS_FLAG);
        pOrange.setColor(Color.rgb(255, 119, 0)); // #ff7700

        Paint pCinza = new Paint(Paint.ANTI_ALIAS_FLAG);
        pCinza.setColor(Color.rgb(220, 224, 230));

        TextPaint tEye = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        tEye.setColor(Color.rgb(230, 100, 0));
        tEye.setTextSize(9f);
        tEye.setTypeface(Typeface.create(Typeface.MONOSPACE, Typeface.BOLD));

        TextPaint tTit = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        tTit.setColor(Color.rgb(15, 23, 42)); // Slate escuro
        tTit.setTextSize(20f);
        tTit.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));

        TextPaint tMeta = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        tMeta.setColor(Color.rgb(100, 116, 139));
        tMeta.setTextSize(9.5f);

        TextPaint tH1 = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        tH1.setColor(Color.rgb(15, 23, 42));
        tH1.setTextSize(14f);
        tH1.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));

        TextPaint tH2 = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        tH2.setColor(Color.rgb(30, 41, 59));
        tH2.setTextSize(12f);
        tH2.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));

        TextPaint tCorpo = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        tCorpo.setColor(Color.rgb(51, 65, 85));
        tCorpo.setTextSize(10.5f);

        TextPaint tFoot = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        tFoot.setColor(Color.rgb(148, 163, 184));
        tFoot.setTextSize(8.5f);

        // Prepara blocos de parágrafos
        String dataStr = new SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault()).format(new Date());
        String metaStr = "GERADO EM: " + dataStr + "  |  AUTONOMIA: NÍVEL 5  |  PROJETO PROMETHEUS";

        List<LayoutItem> itens = new ArrayList<>();
        String[] linhas = (corpo == null ? "" : corpo.replace("\r", "")).split("\n\n");
        for (String bloco : linhas) {
            bloco = bloco.trim();
            if (bloco.isEmpty()) continue;
            if (bloco.startsWith("# ")) {
                String txt = bloco.substring(2).trim();
                StaticLayout sl = StaticLayout.Builder.obtain(txt, 0, txt.length(), tH1, contentW - 14).build();
                itens.add(new LayoutItem(sl, true, 1));
            } else if (bloco.startsWith("## ")) {
                String txt = bloco.substring(3).trim();
                StaticLayout sl = StaticLayout.Builder.obtain(txt, 0, txt.length(), tH2, contentW).build();
                itens.add(new LayoutItem(sl, true, 2));
            } else {
                StaticLayout sl = StaticLayout.Builder.obtain(bloco, 0, bloco.length(), tCorpo, contentW)
                    .setAlignment(Layout.Alignment.ALIGN_NORMAL).setLineSpacing(2f, 1.18f).build();
                itens.add(new LayoutItem(sl, false, 0));
            }
        }

        StaticLayout ltTitulo = StaticLayout.Builder.obtain(titulo, 0, titulo.length(), tTit, contentW).build();

        int itemIdx = 0;
        int pagina = 1;
        while (itemIdx < itens.size() || pagina == 1) {
            PdfDocument.Page p = doc.startPage(new PdfDocument.PageInfo.Builder(W, H, pagina).create());
            Canvas cv = p.getCanvas();
            int y = M;

            // Barra topo Cyber Orange
            cv.drawRect(M, y, W - M, y + 3, pOrange);
            y += 12;

            if (pagina == 1) {
                // Eyebrow Stark
                cv.drawText("F.R.I.D.A.Y. INTEL REPORT  ·  SISTEMA AUTÔNOMO", M, y + 8, tEye);
                y += 16;

                // Título
                cv.save();
                cv.translate(M, y);
                ltTitulo.draw(cv);
                cv.restore();
                y += ltTitulo.getHeight() + 8;

                // Metadata
                cv.drawText(metaStr, M, y + 8, tMeta);
                y += 16;

                // Linha divisória
                cv.drawRect(M, y, W - M, y + 1, pCinza);
                y += 14;
            }

            int limiteY = H - M - 24; // Deixa espaço para rodapé
            while (itemIdx < itens.size()) {
                LayoutItem item = itens.get(itemIdx);
                int espacoExtra = item.ehH1 ? 16 : item.ehH2 ? 10 : 8;
                if (y + item.layout.getHeight() + espacoExtra > limiteY) {
                    break; // Passa para a próxima página
                }

                y += (item.ehH1 ? 10 : 4);
                if (item.ehH1) {
                    // Marcador laranja lateral para H1
                    cv.drawRect(M, y, M + 4, y + item.layout.getHeight(), pOrange);
                    cv.save();
                    cv.translate(M + 10, y);
                    item.layout.draw(cv);
                    cv.restore();
                } else {
                    cv.save();
                    cv.translate(M, y);
                    item.layout.draw(cv);
                    cv.restore();
                }
                y += item.layout.getHeight() + (item.ehH1 ? 10 : 6);
                itemIdx++;
            }

            // Rodapé da página
            int footY = H - M;
            cv.drawRect(M, footY - 14, W - M, footY - 13, pCinza);
            cv.drawText("F.R.I.D.A.Y. Commercial Edition  ·  Integra Code", M, footY, tFoot);
            String pStr = "Página " + pagina;
            float pw = tFoot.measureText(pStr);
            cv.drawText(pStr, W - M - pw, footY, tFoot);

            doc.finishPage(p);
            pagina++;
            if (itemIdx >= itens.size()) break;
        }

        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        doc.writeTo(bo);
        doc.close();
        return bo.toByteArray();
    }

    private static class LayoutItem {
        final StaticLayout layout;
        final boolean ehH1;
        final boolean ehH2;
        LayoutItem(StaticLayout l, boolean h, int nivel) {
            this.layout = l;
            this.ehH1 = h && nivel == 1;
            this.ehH2 = h && nivel == 2;
        }
    }

    private static String x(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    private static byte[] docx(String titulo, String corpo) throws Exception {
        StringBuilder b = new StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            + "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>");
        
        // Título estilizado em Cyber Orange
        b.append("<w:p><w:pPr><w:jc w:val=\"left\"/><w:spacing w:after=\"120\"/></w:pPr>")
         .append("<w:r><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/><w:b/><w:color w:val=\"FF7700\"/><w:sz w:val=\"40\"/></w:rPr>")
         .append("<w:t xml:space=\"preserve\">").append(x(titulo)).append("</w:t></w:r></w:p>");

        // Subtítulo / Metadados
        String dataStr = new SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault()).format(new Date());
        b.append("<w:p><w:pPr><w:spacing w:after=\"280\"/></w:pPr>")
         .append("<w:r><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/><w:color w:val=\"64748B\"/><w:sz w:val=\"20\"/></w:rPr>")
         .append("<w:t xml:space=\"preserve\">F.R.I.D.A.Y. Intel Report  ·  ").append(dataStr).append("  ·  Projeto Prometheus</w:t></w:r></w:p>");

        for (String l : (corpo == null ? "" : corpo.replace("\r", "")).split("\n", -1)) {
            l = l.trim();
            if (l.isEmpty()) continue;
            boolean h1 = l.startsWith("# ");
            boolean h2 = l.startsWith("## ");
            boolean item = l.startsWith("- ") || l.startsWith("• ") || l.startsWith("* ");

            if (h1) {
                String t = l.substring(2).trim();
                b.append("<w:p><w:pPr><w:spacing w:before=\"240\" w:after=\"120\"/></w:pPr>")
                 .append("<w:r><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/><w:b/><w:color w:val=\"0F172A\"/><w:sz w:val=\"28\"/></w:rPr>")
                 .append("<w:t xml:space=\"preserve\">").append(x(t)).append("</w:t></w:r></w:p>");
            } else if (h2) {
                String t = l.substring(3).trim();
                b.append("<w:p><w:pPr><w:spacing w:before=\"180\" w:after=\"80\"/></w:pPr>")
                 .append("<w:r><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/><w:b/><w:color w:val=\"1E293B\"/><w:sz w:val=\"24\"/></w:rPr>")
                 .append("<w:t xml:space=\"preserve\">").append(x(t)).append("</w:t></w:r></w:p>");
            } else if (item) {
                String t = l.replaceFirst("^[-*•]\\s+", "");
                b.append("<w:p><w:pPr><w:ind w:left=\"360\"/><w:spacing w:after=\"80\"/></w:pPr>")
                 .append("<w:r><w:rPr><w:color w:val=\"FF7700\"/><w:b/></w:rPr><w:t>• </w:t></w:r>")
                 .append("<w:r><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/><w:color w:val=\"334155\"/><w:sz w:val=\"21\"/></w:rPr>")
                 .append("<w:t xml:space=\"preserve\">").append(x(t)).append("</w:t></w:r></w:p>");
            } else {
                b.append("<w:p><w:pPr><w:spacing w:after=\"140\" w:line=\"276\" w:lineRule=\"auto\"/></w:pPr>")
                 .append("<w:r><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/><w:color w:val=\"334155\"/><w:sz w:val=\"21\"/></w:rPr>")
                 .append("<w:t xml:space=\"preserve\">").append(x(l)).append("</w:t></w:r></w:p>");
            }
        }
        b.append("<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar w:top=\"1134\" w:right=\"1134\" w:bottom=\"1134\" w:left=\"1134\"/></w:sectPr></w:body></w:document>");
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        try (ZipOutputStream z = new ZipOutputStream(bo)) {
            ent(z, "[Content_Types].xml", "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                + "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
                + "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
                + "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
                + "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/></Types>");
            ent(z, "_rels/.rels", "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                + "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
                + "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/></Relationships>");
            ent(z, "word/document.xml", b.toString());
        }
        return bo.toByteArray();
    }

    private static void ent(ZipOutputStream z, String nome, String s) throws Exception {
        z.putNextEntry(new ZipEntry(nome));
        z.write(s.getBytes(StandardCharsets.UTF_8));
        z.closeEntry();
    }
}
