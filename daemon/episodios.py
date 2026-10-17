"""episodios — memória de tarefas que DERAM CERTO (F7): SQLite FTS5 em memory/episodios.sqlite.

Só grava tarefa com verificação ok (pedido, passos resumidos, resultado). Antes de uma tarefa nova o agente
recebe os 2 episódios mais parecidos (bm25) como exemplo. Sem modelo de embedding: poucos MB em disco.
friday.json "episodios": false desliga.
"""
import json, os, re, sqlite3, time, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "memory", "episodios.sqlite")
CFG = os.path.join(HERE, "..", "memory", "friday.json")
_PARE = set("a o as os um uma uns umas de do da dos das no na nos nas em por para pra pro com sem e ou que se me mim meu minha "
            "eu voce você ela ele isso isto esse essa aqui ali la lá ai aí agora favor sexta feira friday ja já tambem também so só "
            "mais muito pouco sobre the".split())


def ativo():
    try:
        return json.load(open(CFG)).get("episodios", True) is not False
    except Exception:
        return True


def _con(db=None):
    c = sqlite3.connect(db or DB, timeout=5)
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS ep USING fts5(pedido, passos, resultado, t UNINDEXED, "
              "tokenize='unicode61 remove_diacritics 2')")
    return c


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _termos(texto):
    return [w for w in re.findall(r"\w{3,}", _norm(texto)) if w not in _PARE][:12]


def gravar(pedido, passos, resultado, db=None):
    """só chame com a tarefa VERIFICADA. Pedido igual substitui o antigo (não duplica)."""
    pedido = re.split(r"\n\(Informações das etapas anteriores", str(pedido or ""))[0].strip()[:300]
    if len(_termos(pedido)) < 2 or not passos:
        return False
    c = _con(db)
    try:
        c.execute("DELETE FROM ep WHERE pedido = ?", (pedido,))
        c.execute("INSERT INTO ep(pedido, passos, resultado, t) VALUES (?,?,?,?)",
                  (pedido, str(passos)[:600], str(resultado or "")[:300], time.strftime("%Y-%m-%d %H:%M")))
        c.commit()
        return True
    finally:
        c.close()


def parecidos(pedido, n=2, db=None):
    """-> [{"pedido","passos","resultado","t","score"}] mais parecidos (bm25: menor = melhor)."""
    termos = _termos(pedido)
    if not termos or not (db or os.path.exists(DB)):
        return []
    q = " OR ".join('"' + w.replace('"', "") + '"' for w in termos)
    c = _con(db)
    try:
        rows = c.execute("SELECT pedido, passos, resultado, t, bm25(ep, 3.0, 1.0, 0.5) AS s FROM ep WHERE ep MATCH ? "
                         "ORDER BY s LIMIT ?", (q, n)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        c.close()
    return [{"pedido": r[0], "passos": r[1], "resultado": r[2], "t": r[3], "score": round(r[4], 3)} for r in rows]


def texto_prompt(pedido, n=2, db=None):
    """bloco curto para o prompt do agente ('' se não houver nada parecido)."""
    eps = parecidos(pedido, n, db)
    if not eps:
        return ""
    # só o COMO (passos): a resposta antiga NUNCA entra — os dados mudam e o modelo copiaria o resultado velho
    return "Da última vez que o dono pediu algo parecido, estes PASSOS funcionaram (repita a abordagem, mas leia a saída NOVA das ferramentas; " \
        "nunca reutilize respostas antigas):\n" + "\n".join(f"- pedido: {e['pedido'][:120]} | passos: {e['passos'][:220]}" for e in eps)
