import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))
import friday as fr

def test_pedido_longo_nao_vira_atalho():
    t = "pesquisa o preço do celular novo da samsung e depois monta uma tabela comparando com o iphone e me manda"
    assert fr.fast_intent(t)["acoes"] == [{"t": "tarefa", "pedido": t}]

def test_atalho_curto_continua():
    assert fr.fast_intent("desbloqueia o celular")["acoes"][0]["op"] == "desbloquear"
