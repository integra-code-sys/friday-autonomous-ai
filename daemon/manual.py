"""Tarefas MANUAIS: a F.R.I.D.A.Y. usa o PC como um humano — olha a tela (captura + OCR local), decide o próximo passo com o
modelo local e executa com cursor e teclado reais (via `pc`: curva de Bézier, ritmo irregular).
Segurança: passos sensíveis (enviar, pagar, apagar, senhas...) NÃO são feitos sozinhos: ela para e pede para você concluir."""
import difflib
import json
import os
import re
import socket
import subprocess
import threading
import time

import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import win_compat

PC = os.path.join(HERE, "pc")
SHOT = os.path.join(win_compat.get_temp_dir(), "friday-manual.png")
STOP = os.path.join(win_compat.get_temp_dir(), "friday-manual.stop")
MAX_STEPS = 400                  # sem pausa: segue até concluir ou até o dono mandar parar (limite de segurança: 25 min)
MAX_SECONDS = 25 * 60

SENSIVEL = re.compile(r"\b(enviar|send|pagar|pay|pagamento|comprar|buy|purchase|finalizar|checkout|excluir|delete|apagar|remover|"
                      r"transferir|transfer|publicar|post|confirmar|senha|password|cartão|card|assinar|subscribe|sair|logout)\b", re.I)

# atalhos que bloqueiam/suspendem a sessão: nunca enviados pelo modo manual
LOCK_KEYS = re.compile(r"(?:super|meta|win|logo)\s*\+?\s*(?:l|escape|esc)\b|ctrl\+alt\+(?:l|delete|del)|\bsleep\b|\bpower\b", re.I)

_state = {"running": False, "goal": "", "step": 0, "log": []}


def running():
    return _state["running"]


def stop():
    try:
        open(STOP, "w").write("1")
    except Exception:
        pass


def _say(text):
    try:
        c = win_compat.connect_ipc()
        c.sendall((json.dumps({"type": "say", "text": text}) + "\n").encode())
        time.sleep(0.1); c.close()
    except Exception:
        pass


def _pc(*a, timeout=40):
    if win_compat.IS_WINDOWS:
        op = str(a[0]).lower() if a else ""
        if op == "move" and len(a) >= 3:
            win_compat.mouse_move(int(a[1]), int(a[2]))
            return "ok"
        elif op == "click":
            btn = a[1] if len(a) > 1 else "left"
            duplo = (btn == "double")
            win_compat.mouse_click(botao="left" if duplo else btn, duplo=duplo)
            return "ok"
        elif op == "clickat" and len(a) >= 3:
            win_compat.mouse_move(int(a[1]), int(a[2]))
            win_compat.mouse_click(botao="left")
            return "ok"
        elif op == "scroll" and len(a) >= 2:
            win_compat.mouse_scroll(int(a[1]))
            return "ok"
        elif op == "type" and len(a) >= 2:
            win_compat.type_text(str(a[1]))
            return "ok"
        elif op == "key" and len(a) >= 2:
            win_compat.press_key(str(a[1]))
            return "ok"
        elif op == "size":
            w, h = win_compat.obter_tamanho_tela()
            return f"{w} {h}"
        elif op == "shot":
            dest = a[1] if len(a) > 1 else os.path.join(win_compat.get_temp_dir(), "prometheus-shot.png")
            img = win_compat.capturar_tela()
            if img is not None:
                import cv2
                cv2.imwrite(dest, img)
            return "ok"
    return subprocess.run([PC, *map(str, a)], capture_output=True, text=True, timeout=timeout).stdout.strip()


def screen_lines():
    """captura a tela e devolve linhas de texto com o centro: [{'t':..., 'x':..., 'y':...}, ...] (OCR local, tesseract)."""
    if win_compat.IS_WINDOWS:
        img = win_compat.capturar_tela()
        if img is not None:
            try:
                import ocr_pt
                ls = ocr_pt.linhas(img)
                if ls is not None:
                    out = [{"t": d["t"][:60], "x": (d["x0"] + d["x1"]) // 2, "y": (d["y0"] + d["y1"]) // 2, "x0": d["x0"], "x1": d["x1"]}
                           for d in ls if len(d["t"]) >= 2 and d["x1"] > 390]
                    out.sort(key=lambda z: (z["y"] // 18, z["x"]))
                    return out
            except Exception:
                pass
        return []
    subprocess.run(["grim", "-s", "1", SHOT], capture_output=True, timeout=10)
    try:                                                       # OCR pt-BR (ocr_pt) primeiro; tesseract eng é a reserva
        import cv2, ocr_pt
        ls = ocr_pt.linhas(cv2.imread(SHOT))
        if ls is not None:
            out = [{"t": d["t"][:60], "x": (d["x0"] + d["x1"]) // 2, "y": (d["y0"] + d["y1"]) // 2, "x0": d["x0"], "x1": d["x1"]}
                   for d in ls if len(d["t"]) >= 2 and d["x1"] > 390]
            out.sort(key=lambda z: (z["y"] // 18, z["x"]))
            return out
    except Exception:
        pass
    r = subprocess.run(["tesseract", SHOT, "-", "--psm", "11", "-l", "eng", "tsv"], capture_output=True, text=True, timeout=40)
    linhas = {}
    for row in r.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            conf = float(c[10])
        except ValueError:
            continue
        if conf < 45:
            continue
        key = (c[2], c[3], c[4])
        x, y, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        d = linhas.setdefault(key, {"w": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h})
        d["w"].append(c[11].strip()); d["x1"] = max(d["x1"], x + w); d["y1"] = max(d["y1"], y + h)
    out = []
    for d in linhas.values():
        t = " ".join(d["w"])
        if len(t) >= 2 and d["x1"] > 390:                      # ignora a coluna da própria F.R.I.D.A.Y. (20% da esquerda)
            out.append({"t": t[:60], "x": (d["x0"] + d["x1"]) // 2, "y": (d["y0"] + d["y1"]) // 2, "x0": d["x0"], "x1": d["x1"]})
    out.sort(key=lambda z: (z["y"] // 18, z["x"]))
    return out


def _find(alvo, linhas):
    a = alvo.lower().strip()
    best, score = None, 0.0
    for l in linhas:
        t = l["t"].lower()
        is_whole_word = bool(re.search(r"\b" + re.escape(a) + r"\b", t))
        if a == t:
            s = 1.0
        elif is_whole_word and len(a) >= 2:
            s = 0.92
        elif len(a) >= 6 and a in t:
            s = 0.75
        else:
            ratio = difflib.SequenceMatcher(None, a, t).ratio()
            min_r = 0.82 if len(a) <= 5 else 0.70
            s = ratio if ratio >= min_r else 0.0
        if a in t and a != t:
            s -= min(0.1, (len(t) - len(a)) / 400)
        if s > score:
            best, score = l, s
    return (best, score) if score >= 0.65 else (None, score)


def _janela_foco():
    try:
        w = json.loads(subprocess.run(["niri", "msg", "--json", "focused-window"], capture_output=True, text=True, timeout=3).stdout)
        return f"{(w.get('app_id') or '?')} — {(w.get('title') or '')[:60]}"
    except Exception:
        return "?"


SYSTEM = """Você controla um computador Linux como um HUMANO, um passo por vez, usando mouse e teclado. Objetivo: {goal}
Você recebe: a janela em foco, as linhas de texto visíveis na tela (OCR; cada uma com posição) e o histórico do que já fez.
Responda SOMENTE JSON: {{"pensamento":"curto","acao":"clicar|digitar|tecla|rolar|abrir|esperar|fim","alvo":"texto EXATO de uma linha visível",
"texto":"o que digitar","enter":false,"teclas":"ctrl+l","n":3,"fala":"frase curta ao terminar"}}
Regras: clicar usa "alvo" (copie o texto de uma linha da lista). abrir = abre um app pelo nome em "texto" (launcher). tecla usa combos como
ctrl+l, enter, tab, alt+left, ctrl+t. Para ir a um site: tecla ctrl+l, depois digitar a URL com enter=true. NUNCA envie, pague, apague, confirme
compra nem digite senha: se o próximo passo for assim, use acao "fim" explicando que ele deve concluir. Use "fim" quando o objetivo estiver feito
(ou impossível). Não repita a mesma ação sem efeito."""


def _decidir(fr, goal, linhas, hist):
    tela = "\n".join(f"- {l['t']}" for l in linhas[:45]) or "(nenhum texto legível)"
    user = f"Janela em foco: {_janela_foco()}\nHistórico: {' | '.join(hist[-6:]) or 'nada ainda'}\nTexto visível:\n{tela}"
    return fr.llm(SYSTEM.format(goal=goal), user, num_predict=200, temperature=0.2, timeout=60)


def _run(goal, fr):
    _state.update(running=True, goal=goal, step=0, log=[])
    try:
        os.remove(STOP)
    except OSError:
        pass
    hist = []
    final = "Terminei o que consegui, chefe."
    try:
        t_ini = time.time()
        for i in range(MAX_STEPS):
            if time.time() - t_ini > MAX_SECONDS:
                final = "Passei do tempo limite, chefe. Parei."
                break
            if os.path.exists(STOP):
                final = "Parei, como pediu."
                break
            _state["step"] = i + 1
            linhas = screen_lines()
            d = _decidir(fr, goal, linhas, hist)
            if not isinstance(d, dict):
                hist.append("falha ao decidir"); continue
            ac = str(d.get("acao", "")).lower()
            alvo, texto = str(d.get("alvo", "")).strip(), str(d.get("texto", ""))
            if ac == "fim":
                final = str(d.get("fala") or final)[:200]
                break
            if ac == "clicar" and alvo:
                if SENSIVEL.search(alvo):
                    final = f"O próximo passo é clicar em {alvo}, e isso eu deixo para você, chefe."
                    break
                l, sc = _find(alvo, linhas)
                if not l:
                    hist.append(f"não achei '{alvo}' na tela"); continue
                _pc("clickat", l["x"], l["y"])
                hist.append(f"cliquei em '{l['t']}'")
            elif ac == "digitar" and texto:
                if SENSIVEL.search(texto) and re.search(r"senha|password", texto, re.I):
                    final = "Isso parece uma senha; essa parte é com você, chefe."
                    break
                _pc("type", texto)
                if d.get("enter"):
                    time.sleep(0.2); _pc("key", "enter")
                hist.append(f"digitei '{texto[:40]}'" + (" + enter" if d.get("enter") else ""))
            elif ac == "tecla" and d.get("teclas") and LOCK_KEYS.search(str(d["teclas"])):
                hist.append("tecla bloqueada (poderia travar a tela)")
            elif ac == "tecla" and d.get("teclas"):
                _pc("key", *str(d["teclas"]).split())
                hist.append(f"tecla {d['teclas']}")
            elif ac == "rolar":
                _pc("scroll", int(d.get("n", 3) or 3))
                hist.append("rolei a página")
            elif ac == "abrir" and texto:
                _pc("launch", texto, timeout=60)
                hist.append(f"abri {texto}")
                try:
                    if fr.holo_mode():
                        fr.holo_live(texto, None)                  # janela vira holograma; o cursor atua por dentro dela
                except Exception:
                    pass
                time.sleep(2.0)
            elif ac == "esperar":
                time.sleep(1.5); hist.append("esperei")
            else:
                hist.append(f"ação inválida: {ac}")
            time.sleep(0.35)                                      # só o tempo da tela reagir
        else:
            final = "Cheguei no limite de passos, chefe."
    except Exception as e:
        final = f"Travei no meio do caminho: {str(e)[:60]}"
    finally:
        _state["running"] = False
        _state["log"] = hist
    _say(final)


def start(goal, fr):
    if _state["running"]:
        return False, "Já estou fazendo uma tarefa na mão, chefe."
    threading.Thread(target=_run, args=(goal, fr), daemon=True, name="manual").start()
    return True, None
