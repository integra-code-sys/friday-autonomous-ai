"""Regressão do fala_pt (texto -> fala pt-BR). Rodar: ../.venv/bin/python teste_fala.py"""
import fala_pt

CASOS = {
    "o 123.456.789-09 é o dele": "o um dois três, quatro cinco seis, sete oito nove, zero nove é o dele",
    "o CNPJ é 12.345.678/0001-90": "o cê ene pê jota é um dois, três quatro cinco, seis sete oito, zero zero zero um, nove zero",
    "mora no 01310-100": "mora no zero um três um zero, um zero zero",
    "placa ABC1D23": "placa a bê cê um dê dois três",
    "versão 2.5.1": "versão dois ponto cinco ponto um",
    "Python 3.14": "Python três ponto catorze",
    "3.5 GB livres": "três vírgula cinco gigas livres",
    "uns 10-20 itens": "uns dez a vinte itens",
    "Dom Pedro II no século XXI": "Dom Pedro segundo no século vinte e um",
    "Rua XV de Novembro, 1500, ap. 32": "Rua quinze de Novembro, mil e quinhentos, apartamento trinta e dois",
    "R$ 1,5 mil e R$ 2 milhões": "um vírgula cinco mil reais e dois milhões de reais",
    "R$ 1.234,56": "mil duzentos e trinta e quatro reais e cinquenta e seis centavos",
    "24/7": "vinte e quatro horas por dia, sete dias por semana",
    "5x mais rápido": "cinco vezes mais rápido",
    "art. 5º, inciso IV": "artigo quinto, inciso quatro",
    "temperatura -5°C": "temperatura menos cinco graus",
    "1/2 xícara": "meia xícara",
    "Tel: (14) 99876-5432": "telefone catorze, nove nove oito sete seis, cinco quatro três dois",
    "PS5 e RTX 3050": "pê ésse cinco e érre tê xis trinta cinquenta",
    "dia 1 de março": "dia primeiro de março",
    "às 14:30 do dia 16/10/2026": "às catorze e trinta do dia dezesseis de outubro de dois mil e vinte e seis",
    "CEP: 17500-000": "cep um sete cinco zero zero, zero zero zero",
    "Meu CPF 123.456.789-09": "Meu cê pê éfe um dois três, quatro cinco seis, sete oito nove, zero nove",
    "no 5º andar": "no quinto andar",
    "Eu vi 3 carros": "Eu vi três carros",
    "Palmeiras 4 x 1 Corinthians": "Palmeiras quatro x um Corinthians",
    "Coloque num Doc X": "Coloque num Doc X",
    "Clima de Marília - 2024": "Clima de Marília - dois mil e vinte e quatro",
    "custa R$ 2.100.": "custa dois mil e cem reais.",
    "memoria-ddr5-32gb": "memoria-ddr5-32gb",
    "memória DDR5": "memória dê dê érre cinco",
}
falhas = 0
for e, esperado in CASOS.items():
    r = fala_pt.normalizar(e)
    if r != esperado:
        falhas += 1
        print(f"FALHA: {e!r}\n  veio:     {r!r}\n  esperado: {esperado!r}")
print(f"{len(CASOS) - falhas}/{len(CASOS)} ok")
raise SystemExit(1 if falhas else 0)
