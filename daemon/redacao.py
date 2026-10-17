"""Redação de mensagens pela Friday: o dono diz a INTENÇÃO ("avisa a Gilda que vou atrasar") e ela escreve o texto
como ele mandaria — 1ª pessoa do dono, no tom das conversas com aquele contato, sem copiar a frase ditada.

redigir(contato, intencao, contexto=None) -> {"texto": str, "redigido": bool}
  contexto: lista opcional de mensagens recentes [{"quem"/"saida", "texto"}] da conversa (tom + assunto).
  Sem modelo (Ollama fora) devolve a própria intenção arrumada (redigido=False): nunca trava o envio.
"""
import re

SISTEMA = (
    "Você redige mensagens de WhatsApp EM NOME do dono do usuário, na 1ª pessoa dele, em português do Brasil. "
    "Recebe a INTENÇÃO dita por ele (ex.: 'que vou atrasar 20 minutos') e escreve a mensagem final que ELE mandaria ao contato. "
    "Regras: não copie a frase ditada palavra por palavra — transforme em mensagem natural; nunca escreva instruções, aspas, "
    "'diga que', 'avise que', nem fale de você (assistente); não invente fatos, datas, valores ou promessas que não estejam na "
    "intenção; mantenha curto (1 a 3 frases), no tom das mensagens anteriores do dono com esse contato (informal se ele é informal); "
    "sem saudações genéricas tipo 'Espero que esteja bem'; pode cumprimentar pelo nome se combinar com o tom. "
    "Responda só JSON: {\"texto\": \"...\"}."
)
_SCHEMA = {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]}


def _limpa(t):
    t = re.sub(r"^\s*(?:que|se)\s+", "", str(t or "").strip(), flags=re.I).strip()
    return (t[0].upper() + t[1:]) if t else t


def _contexto_txt(contexto, contato):
    linhas = []
    for m in (contexto or [])[-10:]:
        quem = "Eu" if m.get("saida") else (m.get("quem") or contato)
        tx = str(m.get("texto") or "").strip()
        if tx:
            linhas.append(f"{quem}: {tx[:200]}")
    return "\n".join(linhas)


def redigir(contato, intencao, contexto=None, llm=None):
    base = _limpa(intencao)
    if not base:
        return {"texto": "", "redigido": False}
    if llm is None:
        try:
            import friday
            llm = friday.llm
        except Exception:
            return {"texto": base, "redigido": False}
    ctx = _contexto_txt(contexto, contato)
    user = (f"Contato: {contato}\n"
            + (f"Conversa recente (mais antiga primeiro):\n{ctx}\n" if ctx else "Sem histórico disponível.\n")
            + f"Intenção do dono: {base}")
    try:
        r = llm(SISTEMA, user, json_mode=True, num_predict=160, temperature=0.5, timeout=25, schema=_SCHEMA)
    except Exception:
        r = None
    texto = str((r or {}).get("texto") or "").strip() if isinstance(r, dict) else ""
    texto = texto.strip('"“” ')
    # proteção: saída vazia, metainstrução ou longa demais => fica a intenção arrumada
    if not texto or len(texto) > 600 or re.search(r"\b(diga|avise|fale)\s+(?:a|ao|para|pra)\b|\bassistente\b|\bsexta[- ]feira\b", texto, re.I):
        return {"texto": base, "redigido": False}
    return {"texto": texto, "redigido": True}


if __name__ == "__main__":                       # teste: python redacao.py "Gilda" "que vou atrasar 20 minutos"
    import sys, json
    print(json.dumps(redigir(sys.argv[1], " ".join(sys.argv[2:])), ensure_ascii=False))
