"""F6 — roteador de intenção da F.R.I.D.A.Y.: UMA chamada curta ao modelo local com JSON SCHEMA (enum fechado).
Substitui GATILHO/_grande quando memory/friday.json "roteador" = "ativo"; em "sombra" (padrão) só classifica e loga
em /tmp/friday-roteador.log ao lado da decisão real, para comparar. "off" desliga.
Critérios gerais no prompt + exemplos reais (memory/conversas.jsonl); NÃO resolver erro de intenção com regex nova."""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "..", "memory", "friday.json")
LOG = "/tmp/friday-roteador.log"

INTENCOES = ["conversa", "acao_simples", "tarefa", "plano", "ignorar", "esclarecer", "parar", "aprovar", "rejeitar"]

SCHEMA = {
    "type": "object",
    "properties": {
        "pedido_reescrito": {"type": "string"},          # 1º: reescrever antes de decidir ajuda o 4B
        "intencao": {"type": "string", "enum": INTENCOES},
        "confianca": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["pedido_reescrito", "intencao", "confianca"],
}

SYSTEM = """Você classifica a fala que o microfone da assistente Sexta-Feira (PC do dono, pt-BR) acabou de transcrever.
O microfone também capta TV, vídeos e outras pessoas, e a transcrição erra nomes. Escolha UMA intenção:
- ignorar: QUALQUER fala em inglês (o dono só fala português), frase sem sentido, comentário solto que não é dirigido à assistente, ruído, pedaço de frase.
- conversa: se resolve só falando: pergunta, curiosidade, quem é você; perguntas sobre o que as câmeras veem ou o que ele segura (ela enxerga pelas câmeras).
- acao_simples: UM comando direto que uma ação resolve: abrir/fechar app ou janela, volume, música, clima, agenda (ver, marcar, remover, limpar), painel, mostrar a tela do celular, mexer a câmera do quarto (olhar para um lado, olhar em volta, procurar um objeto, seguir o dono, vigiar o quarto).
- tarefa: precisa operar ferramentas em vários passos com UM resultado: qualquer coisa no CELULAR do dono, mandar UMA mensagem, navegar/clicar num site, ler a tela e agir, só pesquisar algo, criar UM documento sem pesquisar antes.
- plano: dois ou mais resultados encadeados: pesquisar E com isso criar documento ou mandar mensagem; abrir, pesquisar e enviar.
- esclarecer: só quando nenhuma outra serve: é com a assistente, mas falta o essencial (o quê, para quem, onde).
- parar: mandar parar, cancelar ou deixar para lá o que está em andamento ("pare", "para a tarefa", "chega", "deixa pra lá").
- aprovar / rejeitar: resposta curta autorizando ou cancelando algo que está esperando aprovação.
pedido_reescrito (sempre, exceto ignorar): a fala limpa em pt-BR, sem o nome "Sexta-Feira", corrigindo erros óbvios de transcrição (OnlyOffice, ChatGPT, ZapZap); "" se ignorar.
confianca: de 0 a 1, o quanto você tem certeza.
Exemplos reais:
"I wish." -> ignorar
"Is that right?" -> ignorar
"Ele vai matar um dedinho para você." -> ignorar
"Me diga uma curiosidade curta sobre o espaço." -> conversa
"O que eu tenho na mão?" -> conversa
"Sexta-Feira, quem é você e quais são suas capacidades de visão?" -> conversa
"Abra o ZapZap." -> acao_simples
"Olha pra esquerda." -> acao_simples
"Procura meu celular pelo quarto." -> acao_simples
"Vigia o quarto enquanto eu tô fora." -> acao_simples
"Ligue e desbloqueie meu celular." -> tarefa
"Eu quero que você prepare para enviar uma mensagem para Carlos perguntando se há disponibilidade para ir no banco" -> tarefa
"Pesquise o clima de Marília e faça um documento no OnlyOffice" -> plano
"Abra o Chromium, pesquise sobre a loja de itens do Fortnite e prepare para enviar uma mensagem para João Gaeta" -> plano
"ligar" -> esclarecer
"Quero que você pare a pesquisa. Deixe para lá." -> parar
"Aprovado" -> aprovar
Responda só o JSON."""


def modo():
    """'sombra' (padrão) | 'ativo' | 'off' — lido a cada fala (troca sem reiniciar)."""
    try:
        m = str(json.load(open(CFG)).get("roteador", "sombra")).strip().lower()
    except Exception:
        m = "sombra"
    return m if m in ("sombra", "ativo", "off") else "sombra"


def classificar(texto, ctx="", fr=None, timeout=20):
    """-> {"intencao", "pedido_reescrito", "confianca", "ms"} ou None (Ollama fora/JSON inválido)."""
    if fr is None:
        import friday as fr
    t0 = time.time()
    user = (f"Contexto: {ctx}\n" if ctx else "") + f"Fala transcrita: \"{str(texto or '').strip()[:400]}\""
    d = fr.llm(SYSTEM, user, None, True, 120, 0.1, timeout, schema=SCHEMA)
    if not isinstance(d, dict) or d.get("intencao") not in INTENCOES:
        return None
    try:
        c = max(0.0, min(1.0, float(d.get("confianca", 0))))
    except Exception:
        c = 0.0
    return {"intencao": d["intencao"], "pedido_reescrito": str(d.get("pedido_reescrito") or "").strip()[:400],
            "confianca": round(c, 2), "ms": int((time.time() - t0) * 1000)}


def log(texto, rot, real, real_classe="", modo_="sombra"):
    """uma linha JSON por fala: o que o roteador decidiu x o que o caminho atual fez."""
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps({"h": time.strftime("%d/%m %H:%M:%S"), "modo": modo_, "texto": str(texto)[:200],
                                "rot": rot, "real": real, "real_classe": real_classe,
                                "igual": bool(rot and real_classe and rot.get("intencao") == real_classe)}, ensure_ascii=False) + "\n")
    except Exception:
        pass
