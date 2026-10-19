"""Bateria do roteador: a frase vira o assunto certo e o contato certo, sem abrir navegador nem mandar zap."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent
import friday
import plano


class _SemModelo:
    def llm(self, *a, **k):
        raise SystemExit("o plano chamou o modelo numa frase que já tem regra")


def _contato(texto):
    m = agent.COMPOSTA_ZAP_RE.search(texto or "")
    if not m:
        return ""
    c = m.group(1).strip()
    c = __import__("re").sub(r"(?i)\s+(?:no|pelo|via|por)\s+(?:whatsapp|zap(?:\s*zap)?|wpp).*$", "", c)
    return c.strip(" ,.!?")


def _plano(texto):
    return plano.planejar(texto, _SemModelo())


FALHAS = []


def ok(cond, msg):
    if not cond:
        FALHAS.append(msg)


TEMAS = [
    "a loja de itens do Fortnite de hoje",
    "o preço do dólar hoje",
    "as notícias de tecnologia de hoje",
    "a cotação do bitcoin",
    "o horário de funcionamento dos correios",
    "a tabela do brasileirão",
    "o clima em São Paulo amanhã",
    "receita de pão de queijo",
    "lançamento do filme Duna",
    "preço do café em Santos",
]
CAUDAS = [
    "e prepare a mensagem para integra code no zap com a lista",
    "e prepare a mensagem para integra code no zapzap com todos os itens que achar",
    "e escreva a mensagem para integra code no whatsapp",
    "e mande para integra code no zap dizendo o resumo",
    "e envie para integra code pelo whatsapp com o que achar",
]
PREFIXOS = [
    "",
    "Entre no navegador ",
    "Abre o navegador e ",
    "Sexta-feira, ",
]

compostas = []
for tema in TEMAS:
    for cauda in CAUDAS:
        for pref in PREFIXOS:
            compostas.append(f"{pref}pesquise {tema} {cauda}")

for tema in ("o resultado do jogo do Flamengo", "a agenda cultural de Recife", "quanto custa o PS5"):
    compostas.append(f"entre no navegador pesquise {tema} e prepare a mensagem para integra code no zap zap")
    compostas.append(f"pesquise {tema} e manda pro integra code no zapzap")

simples = [
    ("que horas são", "hora"),
    ("como está o clima", "clima"),
    ("qual a previsão do tempo", "clima"),
    ("abre o chromium", "abrir"),
    ("pesquise a cotação do dólar", "busca"),
    ("pesquise receita de bolo de cenoura", "busca"),
    ("manda no zap para integra code dizendo bom dia", "zap"),
    ("envia mensagem para integra code no whatsapp dizendo que cheguei", "zap"),
    ("cria um arquivo notas.md sobre café", "arquivo"),
    ("pesquise inteligência artificial e crie um documento", "doc"),
    ("pesquise o preço do café e anote na agenda amanhã 9h", "agenda"),
    ("toca Yellow no youtube", "youtube"),
]


def checar_composta(frase):
    termo = agent._limpar_termo_busca(frase)
    ok("mensagem" not in termo.lower() and "zap" not in termo.lower(), f"termo sujo: {frase!r} -> {termo!r}")
    ok(agent._eh_tarefa_composta(frase), f"não viu composta: {frase!r}")
    ok(_contato(frase).lower() == "integra code", f"contato: {frase!r} -> {_contato(frase)!r}")
    fi = friday.fast_intent(frase) or {}
    ac = (fi.get("acoes") or [{}])[0]
    ok(ac.get("t") == "tarefa", f"atalho não é tarefa: {frase!r} -> {ac}")
    ok(ac.get("op") != "ler", f"virou leitura de zap: {frase!r}")
    urls, _ = agent._urls_para_site_ou_busca("", frase)
    if "fortnite" in frase.lower() or "fortnite" in termo.lower():
        ok(urls and "fortnite.com" in urls[0], f"não foi na loja: {urls}")
        ok(not any("google.com/search" in u for u in urls), f"google da frase: {urls}")
    p = _plano(frase)
    tipos = [e["tipo"] for e in p["etapas"]]
    ok(tipos[:2] == ["pesquisar", "zap"], f"plano {tipos} em {frase!r}")
    ok((p["etapas"][1].get("contato") or "").lower() == "integra code", f"plano contato {p['etapas'][1].get('contato')!r}")
    if "fortnite" in frase.lower():
        ok("loja" in p["etapas"][0]["objetivo"].lower(), f"objetivo {p['etapas'][0]['objetivo']!r}")


def checar_simples(frase, tipo):
    termo = agent._limpar_termo_busca(frase)
    if tipo == "busca":
        ok("pesquise" not in termo.lower(), f"sobrou o verbo: {termo!r}")
        urls, _ = agent._urls_para_site_ou_busca("", frase)
        ok(urls and "google.com/search" in urls[0], f"busca simples sem google: {urls}")
    if tipo == "clima":
        ok("fortnite" not in termo.lower(), f"clima virou fortnite: {termo!r}")
        fi = friday.fast_intent(frase) or {}
        ac = (fi.get("acoes") or [{}])[0]
        ok(ac.get("op") != "ler", f"clima virou leitura: {ac}")
    if tipo == "zap":
        ok("integra code" in frase.lower(), frase)
    if tipo == "doc":
        p = _plano(frase)
        ok(any(e["tipo"] == "documento" for e in p["etapas"]), f"sem documento: {frase!r}")
    if tipo == "hora":
        fi = friday.fast_intent(frase) or {}
        ac = (fi.get("acoes") or [{}])[0]
        ok(ac.get("t") != "zap", f"hora virou zap: {ac}")


def main():
    for frase in compostas:
        try:
            checar_composta(frase)
        except SystemExit as e:
            FALHAS.append(f"{e}: {frase!r}")
        except Exception as e:
            FALHAS.append(f"{type(e).__name__}: {e} em {frase!r}")
    for frase, tipo in simples:
        try:
            checar_simples(frase, tipo)
        except SystemExit as e:
            FALHAS.append(f"{e}: {frase!r}")
        except Exception as e:
            FALHAS.append(f"{type(e).__name__}: {e} em {frase!r}")
    total = len(compostas) + len(simples)
    print(f"{total - len(FALHAS)}/{total} ok, {len(FALHAS)} falhas")
    for f in FALHAS[:30]:
        print(" -", f)
    return 1 if FALHAS else 0


if __name__ == "__main__":
    raise SystemExit(main())
