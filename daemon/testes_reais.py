"""Provas de execução: texto lido na tela, páginas reais, planilha e memória. Não envia WhatsApp."""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent
import plano

TELA_LOJA = """
Mova suas guias para o lado
THE PURGE BUNDLE
LADY LIBERTY
1,500
PURGE DRONE
300
HAZBIN HOTEL
ALASTOR'S STAFF
800
LEARN MORE
"""

TITULOS = [
    "Inteligência_artificial", "Fortnite", "WhatsApp", "Planilha_eletrônica", "CAD",
    "Desenho_vetorial", "Modelagem_tridimensional", "Blender", "Inkscape", "FreeCAD",
    "Python", "Linux", "Android", "Câmera_digital", "Microfone", "Navegador_web",
    "Correio_eletrônico", "São_Paulo", "Café", "Dólar", "Bitcoin", "Fotovoltaica",
    "Receita_culinária", "Pão_de_queijo", "Campeonato_Brasileiro_de_Futebol",
    "Instituto_Nacional_de_Pesquisas_Espaciais", "Amazônia", "Energia_eólica",
    "Vacina", "Antibiótico", "Tabela_periódica", "Buraco_negro", "Sistema_Solar",
    "Lua", "Marte_(planeta)", "Oceano_Atlântico", "Rio_Amazonas", "Pantanal",
    "Capoeira", "Bossa_nova", "Samba", "Literatura_brasileira", "Machado_de_Assis",
    "Clarice_Lispector", "Arquitetura", "Concreto", "Aço", "Impressão_3D",
    "Impressora", "Arduino", "Raspberry_Pi", "Git", "Linux_kernel", "Wayland",
    "Bluetooth", "Wi-Fi", "5G", "Satélite_artificial", "GPS", "OpenStreetMap",
    "Wikipedia", "Creative_Commons", "Software_livre", "Banco_de_dados", "SQL",
    "Planilha", "LibreOffice", "OnlyOffice", "PDF", "Markdown", "JSON", "CSV",
    "Criptografia", "HTTPS", "Certificado_digital", "Nota_fiscal", "PIX",
    "Banco_Central_do_Brasil", "Inflação", "IPCA", "Salário_mínimo", "CLT",
    "Férias", "Décimo_terceiro_salário", "Imposto_de_renda", "MEI", "CNPJ",
]


def wiki(titulo):
    url = "https://pt.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(titulo)
    req = urllib.request.Request(url, headers={"User-Agent": "FRIDAY-teste/1.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        d = json.loads(r.read().decode())
    return (d.get("extract") or "").strip()


def main():
    falhas = []
    linhas = agent._linhas_de_leitura(TELA_LOJA)
    if not any("LADY LIBERTY" in s for s in linhas):
        falhas.append("a leitura da loja perdeu LADY LIBERTY")
    if any("mova suas guias" in s.lower() or "learn more" in s.lower() for s in linhas):
        falhas.append("a leitura guardou aviso ou anúncio")
    ok_wiki = 0
    for t in TITULOS:
        time.sleep(0.4)
        try:
            texto = wiki(t)
        except Exception as e:
            falhas.append(f"wiki {t}: {e}")
            continue
        if len(texto) < 80:
            falhas.append(f"wiki curto {t}")
            continue
        if "vou pesquisar" in texto.lower():
            falhas.append(f"wiki genérico {t}")
            continue
        ok_wiki += 1
    try:
        import openpyxl
        caminho = os.path.expanduser("~/Documentos/Friday/teste-loja.xlsx")
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["item", "origem"])
        for s in linhas:
            ws.append([s, "tela"])
        wb.save(caminho)
        devolta = openpyxl.load_workbook(caminho, read_only=True).active
        nomes = [row[0] for row in devolta.iter_rows(values_only=True)]
        if "LADY LIBERTY" not in nomes:
            falhas.append("planilha não reabriu o item")
    except Exception as e:
        falhas.append(f"planilha: {e}")
    try:
        import memoria
        memoria.gravar("site", "https://fortnite.gg/shop", "loja lida na tela: " + ", ".join(linhas[:6]))
        achou = memoria.buscar("fortnite.gg", 3)
        if not achou:
            falhas.append("memória não devolveu o site")
    except Exception as e:
        falhas.append(f"memória: {e}")
    class F:
        def llm(self, *a, **k):
            raise SystemExit("modelo")
    ped = "pesquise ferramentas de IA para CAD vetorial e modelo 3D e prepare a mensagem para integra code no zap"
    p = plano.planejar(ped, F())
    if [e["tipo"] for e in p["etapas"]][:2] != ["pesquisar", "zap"]:
        falhas.append("plano da pesquisa composta")
    if (p["etapas"][1].get("contato") or "").lower() != "integra code":
        falhas.append("contato do plano")
    total = 1 + len(TITULOS) + 3
    print(f"{total - len(falhas)}/{total} provas ok, wiki {ok_wiki}/{len(TITULOS)}")
    for f in falhas[:20]:
        print(" -", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
