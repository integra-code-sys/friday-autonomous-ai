"""Módulo central de parâmetros, matriz de autonomia e auto-conhecimento da Sexta-Feira (F.R.I.D.A.Y.).
Padroniza identidade, níveis de segurança, métodos de execução e percepção sensorial.
"""
import fnmatch
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARAM_FILE = os.path.join(ROOT, "memory", "parametros.json")

_CACHE = None
_CACHE_TIME = 0.0


def carregar():
    """Carrega os parâmetros configurados em memory/parametros.json com fallback seguro."""
    global _CACHE, _CACHE_TIME
    try:
        mtime = os.path.getmtime(PARAM_FILE)
        if _CACHE is not None and mtime <= _CACHE_TIME:
            return _CACHE
        with open(PARAM_FILE, "r", encoding="utf-8") as f:
            _CACHE = json.load(f)
            _CACHE_TIME = mtime
            return _CACHE
    except Exception:
        if _CACHE is not None:
            return _CACHE
        return {
            "versao": "2.0",
            "identidade": {"nome": "Sexta-Feira", "codinome": "F.R.I.D.A.Y."},
            "niveis_autonomia": {"gated_obrigatorio": ["wa.send_chat", "wa.reply", "mail.send", "sudo.*", "shell.escrever"]}
        }


def identidade() -> dict:
    """Retorna os dados de identidade da Sexta-Feira."""
    return carregar().get("identidade", {})


def metodo_tarefa(tipo: str) -> str:
    """Retorna o método operacional padrão para cada tipo de tarefa:
    - visual_humano: pesquisa web, navegação no Chromium, cliques e rolagem visíveis.
    - cli_direto: comandos complexos de sistema, scripts, diagnósticos.
    - cli_protocolar: mensageria e comunicação (WhatsApp, e-mail) via protocolos determinísticos.
    """
    p = carregar().get("modos_operacao", {})
    t = str(tipo or "").lower()
    if t in ("pesquisar", "web", "browser", "navegacao", "pesquisa_web"):
        return p.get("pesquisa_web", {}).get("metodo", "visual_humano")
    if t in ("zap", "whatsapp", "email", "sms", "comunicacao_mensageria"):
        return p.get("comunicacao_mensageria", {}).get("metodo", "cli_protocolar")
    if t in ("cli", "sistema", "script", "codigo", "sistema_complexo"):
        return p.get("sistema_complexo", {}).get("metodo", "cli_direto")
    return "visual_humano"


def nivel_autonomia(acao: str, destino: str = "") -> str:
    """Determina o nível de autonomia para uma dada ação:
    -> 'gated' (requer aprovação expressa do dono)
    -> 'supervisionado' (execução visual assistida)
    -> 'livre' (execução autônoma imediata)
    """
    p = carregar().get("niveis_autonomia", {})
    gated_pats = p.get("gated_obrigatorio", [])
    for pat in gated_pats:
        if fnmatch.fnmatch(acao, pat):
            return "gated"
    superv_pats = p.get("supervisionado_visual", [])
    for pat in superv_pats:
        if fnmatch.fnmatch(acao, pat):
            return "supervisionado"
    livre_pats = p.get("livre", [])
    for pat in livre_pats:
        if fnmatch.fnmatch(acao, pat):
            return "livre"
    return "desconhecido"


def prompt_sistema_identidade() -> str:
    """Texto pronto para ser injetado nos prompts de sistema de LLMs/VLMs."""
    cfg = carregar()
    ident = cfg.get("identidade", {})
    auto = cfg.get("auto_conhecimento", {})
    capacidades = "\n".join(f"- {c}" for c in auto.get("capacidades", []))
    limitacoes = "\n".join(f"- {l}" for l in auto.get("limitações_e_postura", []))
    
    return f"""IDENTIDADE E AUTO-CONHECIMENTO:
Você é a {ident.get('nome', 'Sexta-Feira')} ({ident.get('codinome', 'F.R.I.D.A.Y.')}): assistente holográfica inteligente inspirada na IA do Homem de Ferro, operando localmente no PC.
Tom: {ident.get('tom_de_voz', 'direta, perspicaz, leal e segura')}.

SEUS SENSORES E CAPACIDADES REAIS:
{capacidades}

LIMITAÇÕES E REGRAS INVIOLÁVEIS:
{limitacoes}
- NUNCA envie mensagens externas (WhatsApp/ZapZap, E-mail) sem aprovação expressa ('aprovado'). Toda mensagem é rascunhada primeiro.
- Em tarefas visuais na web, opere o navegador de forma visível ao dono.
- Para tarefas complexas de sistema, prefira a precisão do CLI.
- Para o WhatsApp, use sempre o canal CLI/CDP direto, nunca cliques arriscados na tela.
"""
