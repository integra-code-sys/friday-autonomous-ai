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
import java.util.Date;
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
        int W = 595, H = 842, M = 50;                       // A4 em pontos
        TextPaint tp = new TextPaint(Paint.ANTI_ALIAS_FLAG); tp.setColor(Color.BLACK); tp.setTextSize(11.5f);
        TextPaint tt = new TextPaint(tp); tt.setTextSize(18f); tt.setTypeface(Typeface.DEFAULT_BOLD);
        StaticLayout lt = StaticLayout.Builder.obtain(titulo, 0, titulo.length(), tt, W - 2 * M).build();
        String texto = corpo == null ? "" : corpo.replace("\r", "");
        StaticLayout lc = StaticLayout.Builder.obtain(texto, 0, texto.length(), tp, W - 2 * M)
            .setAlignment(Layout.Alignment.ALIGN_NORMAL).setLineSpacing(2f, 1.15f).build();
        int linha = 0, pagina = 1;
        while (linha < lc.getLineCount() || pagina == 1) {
            PdfDocument.Page p = doc.startPage(new PdfDocument.PageInfo.Builder(W, H, pagina).create());
            Canvas cv = p.getCanvas();
            int y = M;
            if (pagina == 1) { cv.save(); cv.translate(M, y); lt.draw(cv); cv.restore(); y += lt.getHeight() + 18; }
            int topo = linha < lc.getLineCount() ? lc.getLineTop(linha) : 0, ate = linha;
            while (ate < lc.getLineCount() && lc.getLineBottom(ate) - topo <= H - M - y) ate++;
            if (ate > linha) {
                cv.save(); cv.translate(M, y - topo);
                cv.clipRect(0, topo, W - 2 * M, lc.getLineBottom(ate - 1));
                lc.draw(cv); cv.restore();
            }
            doc.finishPage(p);
            if (ate == linha && linha < lc.getLineCount()) break;   // nada coube (não deve acontecer)
            linha = ate; pagina++;
            if (linha >= lc.getLineCount()) break;
        }
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        doc.writeTo(bo); doc.close();
        return bo.toByteArray();
    }

    private static String x(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    private static byte[] docx(String titulo, String corpo) throws Exception {
        StringBuilder b = new StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            + "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>");
        b.append("<w:p><w:r><w:rPr><w:b/><w:sz w:val=\"36\"/></w:rPr><w:t xml:space=\"preserve\">").append(x(titulo)).append("</w:t></w:r></w:p>");
        for (String l : (corpo == null ? "" : corpo.replace("\r", "")).split("\n", -1)) {
            boolean tit = l.startsWith("#");
            String t = tit ? l.replaceFirst("^#+\\s*", "") : l.replaceFirst("^[-*]\\s+", "• ");
            b.append("<w:p><w:r>").append(tit ? "<w:rPr><w:b/><w:sz w:val=\"28\"/></w:rPr>" : "")
             .append("<w:t xml:space=\"preserve\">").append(x(t)).append("</w:t></w:r></w:p>");
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
