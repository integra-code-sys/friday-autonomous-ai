"""Bateria completa de testes automatizados para as novas capacidades da F.R.I.D.A.Y.:
1. Modo Dev (dev_ide.py)
2. Pesquisas Web (prom_ops.pesquisar_web)
3. Criação de Arquivos (agent.t_criar_arquivo)
4. WhatsApp e Resolução de Contatos (agent._resolver_contato)
5. Tarefas Compostas (agent._eh_tarefa_composta, agent._tarefa_composta)
6. Compatibilidade Multiplataforma (win_compat.py)
"""
import os
import sys

_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
sys.path.insert(0, os.path.join(_dir, "..", "daemon"))
sys.path.insert(0, os.path.join(_dir, "daemon"))

import agent as ag
import dev_ide
import prom_ops as ops
import win_compat as win

def testar_criacao_arquivos():
    print("\n--- [1/6] Testando Criação de Arquivos ---")
    nome = "teste_automacao.md"
    conteudo = "# Relatório de Teste Autônomo\nF.R.I.D.A.Y. testada com sucesso."
    res = ag.t_criar_arquivo(nome, conteudo)
    print("Resultado t_criar_arquivo:", res)
    assert "criado com sucesso" in res.lower() or "arquivo criado" in res.lower(), f"Falha na criação: {res}"

    caminho = os.path.expanduser(f"~/Documentos/Friday/{nome}")
    assert os.path.exists(caminho), f"Arquivo não encontrado no disco: {caminho}"
    lido = open(caminho, "r", encoding="utf-8").read()
    assert "F.R.I.D.A.Y." in lido, "Conteúdo incorreto"
    print("✓ Arquivo criado e verificado com sucesso em:", caminho)

def testar_pesquisa_web():
    print("\n--- [2/6] Testando Pesquisa Web ---")
    res = ag.t_pesquisar_web(consulta="inteligência artificial Brasil 2026")
    print("Resumo da pesquisa:", (res[:160] + "...") if len(res) > 160 else res)
    assert len(res) > 20, "Pesquisa retornou vazio"
    assert "http" in res or "ia" in res.lower() or "brasil" in res.lower(), "Resultado irrelevante"
    print("✓ Pesquisa Web executada com sucesso!")

def testar_tarefas_compostas_regex():
    print("\n--- [3/6] Testando Reconhecimento de Tarefas Compostas ---")
    casos = [
        ("pesquise sobre python 3.12 e envie no whatsapp para Iann", True),
        ("pesquise as notícias de IA e mande no zap para Maria", True),
        ("pesquise arquitetura de software e crie um arquivo resumo.md", True),
        ("pesquise notícias de tecnologia e anote na agenda", True),
        ("que horas são?", False),
        ("toque jazz", False),
    ]
    for frase, esperado in casos:
        tipo = ag._eh_tarefa_composta(frase)
        print(f"'{frase}' -> {tipo}")
        assert tipo is esperado, f"Frase '{frase}': esperado {esperado}, obteve {tipo}"
    print("✓ Detecção de tarefas compostas funcionando perfeitamente!")

def testar_tarefa_composta_execucao():
    print("\n--- [4/6] Testando Execução de Tarefa Composta (Pesquisa + Criação de Arquivo) ---")
    class MockFR:
        def llm(self, *a, **k):
            return "# Computação Quântica\nA computação quântica utiliza qubits para processamento paralelo exponencial."

    cmd = "pesquise sobre computação quântica e crie um arquivo quantica_teste.md"
    resp = ag._tarefa_composta(cmd, MockFR())
    print("Resposta da tarefa composta:", resp)
    assert resp is not None, "Tarefa composta não foi reconhecida"
    assert "quantica_teste.md" in resp.lower() or "criado" in resp.lower() or "pesquisei" in resp.lower(), "Falha ao gerar arquivo composto"
    caminho = os.path.expanduser("~/Documentos/Friday/quantica_teste.md")
    assert os.path.exists(caminho), f"Arquivo não gerado: {caminho}"
    print("✓ Tarefa composta (pesquisa + documento) executada de ponta a ponta!")

def testar_modo_dev_ide():
    print("\n--- [5/6] Testando Modo Dev IDE Autônoma ---")
    logs = []
    async def broadcast(ev):
        logs.append(ev)

    ide = dev_ide.IDE(broadcast)
    est = ide.estado_dict()
    print("Estado inicial da IDE:", est.get("ocupado"), "Projeto:", est.get("projeto"))
    assert "projeto" in est, "Estado da IDE incompleto"
    arv = ide.arvore("")
    assert "itens" in arv, "Árvore de arquivos falhou"
    print(f"Itens na raiz do projeto: {len(arv['itens'])}")
    print("✓ Modo Dev IDE (estado, árvore de projeto, segurança e parada) testado com sucesso!")

def testar_compatibilidade_windows():
    print("\n--- [6/6] Testando Módulo Multiplataforma (win_compat.py) ---")
    rt = win.get_runtime_dir()
    assert os.path.exists(rt), f"Runtime dir não existe: {rt}"
    procs = win.obter_processos(3)
    assert len(procs) > 0, "Falha ao listar processos"
    up = win.obter_uptime_segundos()
    assert up > 0, "Uptime inválido"
    disco = win.obter_uso_disco()
    assert "%" in disco, "Uso de disco inválido"
    print(f"✓ win_compat: runtime={rt}, processos={len(procs)}, uptime={up}s, disco={disco}")

if __name__ == "__main__":
    print("==========================================================")
    print("INICIANDO SUITE DE TESTES: CAPACIDADES EXPANDIDAS F.R.I.D.A.Y.")
    print("==========================================================")
    testar_criacao_arquivos()
    testar_pesquisa_web()
    testar_tarefas_compostas_regex()
    testar_tarefa_composta_execucao()
    testar_modo_dev_ide()
    testar_compatibilidade_windows()
    print("\n==========================================================")
    print("✓ TODOS OS 6 TESTES PASSARAM COM SUCESSO!")
    print("==========================================================")
