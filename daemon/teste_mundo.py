"""Regressão das câmeras FIXAS -> PTZ (mundo.py) e do zoom digital (15/10/2026) — roda SEM câmera/VLM:
    .venv/bin/python daemon/teste_mundo.py
Cobre: aprendizado automático do mapa (só com 1 pessoa), interpolação, área desconhecida, fusão porta+nativa,
substituição de par velho, alvo perdido -> aponta pelas fixas, localizar pelas fixas primeiro, recorte do zoom."""
import os, sys, tempfile, threading, time, types
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, ipcam, mundo, ptz

mundo.ARQ = os.path.join(tempfile.mkdtemp(), "mundo_pares.json")      # nunca toca memory/ do daemon
CONF = {"pan_total_s": 55.0, "tilt_total_s": 34.0, "pan_v": 0.16, "tilt_v": 0.17, "tilt_horizonte": 9.0, "posicoes": {}, "modo": "auto"}
ipcam.ler_conf = lambda: dict(CONF)
ipcam.salvar_conf = lambda **kw: CONF.update(kw)
ptz._conf = lambda: dict(ptz._PADRAO, **CONF)
ptz.log = lambda msg: None
falhas = []


def ok(cond, nome):
    print(("  ok  " if cond else "  FALHOU ") + nome)
    if not cond:
        falhas.append(nome)


# mapa "verdadeiro" simulado: porta vê o quarto inteiro; nativa vê espelhado e só metade
verdade = {"porta": lambda u, v: (50 * u, 30 * (1 - v)), "nativa": lambda u, v: (25 + 25 * (1 - u), 30 * (1 - v))}

print("aprendizado")
M = mundo.Mundo()
M.pares = {}
for i, u in enumerate(np.linspace(0.1, 0.9, 7)):
    for v in (0.3, 0.5, 0.7):
        pan, tilt = verdade["porta"](u, v)
        M.observar("porta", time.time(), [(u, v, 0.9)])
        M._ult_aprendeu = 0
        M.aprender(pan, tilt)
ok(len(M.pares["porta"]) == 21, f"21 pares aprendidos com 1 pessoa ({len(M.pares.get('porta', []))})")
M.observar("porta", time.time(), [(0.5, 0.5, 0.9), (0.2, 0.5, 0.8)])
M._ult_aprendeu = 0
ok(M.aprender(10, 10) == 0, "2 pessoas na fixa: NÃO aprende (ambíguo)")
M.observar("porta", time.time() - 5, [(0.5, 0.5, 0.9)])
M._ult_aprendeu = 0
ok(M.aprender(10, 10) == 0, "observação velha (>1 s): NÃO aprende")

print("estimativa")
M.observar("porta", time.time(), [(0.42, 0.45, 0.9)])
e = M.melhor()
vp, vt = verdade["porta"](0.42, 0.45)
ok(e is not None and abs(e["pan"] - vp) < 3.0 and abs(e["tilt"] - vt) < 3.0,
   f"interpola entre pares: pan {e and round(e['pan'], 1)} (real {vp:.1f}) tilt {e and round(e['tilt'], 1)} (real {vt:.1f})")
M.observar("porta", time.time(), [(0.5, 0.98, 0.9)])
e2 = M.estimar()
ok(not e2 or e2[0]["conf"] < 0.5, "ponto longe de tudo que já viu: confiança baixa ou nenhuma")
M.observar("porta", time.time(), [])
ok(M.melhor() is None, "ninguém nas fixas: sem alvo")

print("fusão porta + nativa")
for u in np.linspace(0.1, 0.9, 7):
    for v in (0.3, 0.5, 0.7):
        pan, tilt = verdade["nativa"](u, v)
        M.pares.setdefault("nativa", []).append([u, v, pan, tilt, 0])
t = time.time()
up = 0.7                                                            # pessoa em pan 35 vista pelas duas
un = 1 - (35 - 25) / 25
M.observar("porta", t, [(up, 0.5, 0.9)])
M.observar("nativa", t, [(un, 0.5, 0.9)])
es = M.estimar()
ok(len(es) == 1 and sorted(es[0]["cams"]) == ["nativa", "porta"] and abs(es[0]["pan"] - 35) < 2.5,
   f"mesma pessoa nas duas câmeras = 1 alvo fundido ({[(round(x['pan'], 1), x['cams']) for x in es]})")
M.observar("nativa", t, [(0.95, 0.5, 0.9)])                         # nativa vê outra pessoa (pan ~26)
ok(len(M.estimar()) == 2, "pessoas diferentes = 2 alvos")
ok(abs(M.melhor(perto_de=27)["pan"] - 27) < abs(M.melhor(perto_de=27)["pan"] - 35), "perto_de escolhe o alvo mais próximo do último")

print("mapa robusto (revisão 15/10)")
n0 = len(M.pares["porta"])
antigo = [p for p in M.pares["porta"] if abs(p[0] - 0.1) < 1e-6 and abs(p[1] - 0.3) < 1e-6][0][:4]
M.observar("porta", time.time(), [(0.1, 0.3, 0.9)])
M._ult_aprendeu = 0
M.aprender(40.0, 5.0)                                               # contradiz o mapa (pan ~5): 1 amostra não muda nada
ok(len(M.pares["porta"]) == n0 and antigo in [p[:4] for p in M.pares["porta"]], "1 amostra que contradiz o mapa é ignorada")
for _ in range(2):
    M.observar("porta", time.time(), [(0.1, 0.3, 0.9)])
    M._ult_aprendeu = 0
    M.aprender(40.0, 5.0)
ok(len(M.pares["porta"]) == n0 and [0.1, 0.3, 40.0, 5.0] == M.pares["porta"][-1][:4], "3 discordâncias coerentes: câmera mudou, troca o par")
M.observar("porta", time.time(), [(np.float32(0.55), np.float32(0.62), np.float32(0.9))])
M._ult_aprendeu = 0
M.aprender(np.float32(27.5), np.float32(11.2))
M._sujo = True
M.salvar()
ok(mundo.Mundo().pares["porta"][-1][:4] == [0.55, 0.62, 27.5, 11.2], "persistência no JSON (inclusive valores float32 do onnxruntime)")


# ---------------------------------------------------------------- PTZ usando as fixas
def novo():
    p = ptz.PTZ.__new__(ptz.PTZ)
    p.pan, p.tilt, p.modo, p.modo_salvo, p.ocupada = 20.0, 9.0, "seguir", "auto", None
    p.alvo, p._fantasmas, p._reais = None, [], []
    p._integrar = lambda: None
    p.idas = []
    p._parar_tarefa = threading.Event()
    def ir(pan, tilt, esperar=True):
        p.idas.append((pan, tilt)); p.pan, p.tilt = pan, tilt
    p.ir = ir
    class Cam:
        def __init__(s_): s_.pulsos, s_.movs, s_.ok, s_.motor = [], [], True, True
        def pulso(s_, vx, vy, dur): s_.pulsos.append((vx, vy, round(dur, 2))); return True
        def mover(s_, vx, vy): s_.movs.append((vx, vy)); return True
    cam_ = Cam()
    ptz.ipcam.atual = lambda: cam_
    p._eixo, p._sinal, p._visto, p._lado = None, 0, 0.0, 0
    return p


print("alvo perdido -> aponta pelas fixas")
p = novo()
ptz.G.alvo_externo = lambda perto_de=None: {"pan": 40.0, "tilt": 12.0, "conf": 0.8, "cams": ["porta"]}
ok(p._ir_externo(time.time()) and p.cam.pulsos == [(1.0, 0, 20.0)] and p._eixo == "externo",
   "longe do quadro atual: pulso NÃO bloqueante no sentido das fixas (20 s de motor p/ a direita)")
ok(not p.idas and p.ocupada is None, "sem salto bloqueante nem tarefa (o vídeo assume)")
ok(not p._ir_externo(time.time()), "não insiste antes de 1,5 s")
p._ext_fim = time.time() + 5
p._passo_externo(time.time())
ok(p._eixo == "externo", "pulso em andamento: continua girando")
p._ext_fim = time.time() - 0.1
t_ = time.time(); p._passo_externo(t_)
ok(p._eixo is None and p._visto == t_, "pulso terminou: libera e dá tempo de reencontrar antes da busca cega")
p = novo(); p.ocupada = "mapeando"
ptz.G.alvo_externo = lambda perto_de=None: {"pan": 40.0, "tilt": 12.0, "conf": 0.8, "cams": ["porta"]}
ok(not p._ir_externo(time.time()) and not p.cam.pulsos, "câmera ocupada: não gira por cima da tarefa")
p = novo(); p._lado = 1; p._ext_fim = 0
p._passo_externo(time.time())
ok(p._lado == 0, "fim do pulso externo zera _lado (busca cega não desfaz o apontamento)")
p = novo(); p.cam.hist = [(time.time() - 0.3, None, 1, 0)]
ok(not p._ir_externo(time.time()) and not p.cam.pulsos, "motor ainda girando (hist aberto): não calcula com pan defasado")
p = novo(); p.alvo = {"x": 0.5, "y": 0.5, "caixa": (0, 0, 1, 1), "t": time.time() - 13}; p._eixo = "busca"
p.pose = lambda: type("P", (), {"pessoas": lambda s_, fr, conf=0.4: []})()
p._escolher = lambda ps, t: None
p._passo_seguir(np.zeros((360, 640, 3), np.uint8), time.time())
ok(p.alvo is None and p._eixo is None and (0, 0) in p.cam.movs, "alvo sumido há > 12 s: solta o alvo e PARA o motor (sem vai-e-volta)")
p = novo(); p._parar_tarefa.set()
ok(p.apontar_externo() is False, "apontar cancelado: não confere pessoa no lugar errado")
p = novo()
ptz.G.alvo_externo = lambda perto_de=None: {"pan": 21.0, "tilt": 9.5, "conf": 0.8, "cams": ["porta"]}
ok(not p._ir_externo(time.time()) and not p.cam.pulsos, "alvo já dentro do quadro: não gira")
p = novo()
ptz.G.alvo_externo = lambda perto_de=None: {"pan": 40.0, "tilt": 12.0, "conf": 0.1, "cams": ["porta"]}
ok(not p._ir_externo(time.time()), "confiança baixa: não confia nas fixas")

print("localizar: fixas primeiro")
p = novo()
p.disponivel = lambda: True
p.apontar_externo = lambda: True
modos = []
p.definir_modo = lambda m, salvar=True: modos.append(m)
r = p.localizar_dono()
ok("câmeras fixas" in r and modos == ["seguir"], "fixas viram o dono: segue sem varrer o quarto")

p = novo()
p.disponivel = lambda: True
p.apontar_externo = lambda: False
p.achar_posicao = lambda n: [11.86, 1.52]
p.ir_posicao = lambda n: True
p._quadro_apos = lambda t: None
p.procurar = lambda *a: (_ for _ in ()).throw(AssertionError("varreu o quarto"))
ptz.G.sentado = lambda: True
modos = []
p.definir_modo = lambda m, salvar=True: modos.append(m)
_sl = time.sleep; time.sleep = lambda s_: None
try:
    r = p.localizar_dono()
    ok("sentado" in r and modos == ["seguir"], "nativa vê o dono sentado: vai ao lugar dele e NÃO varre o quarto")
except AssertionError as e:
    ok(False, f"nativa vê o dono sentado: {e}")
finally:
    time.sleep = _sl
ptz.G.sentado = lambda: False

print("entrada pela porta / gesto (mundo.py)")
M2 = mundo.Mundo()
ok(not M2.entrada("porta", 0.0, 1) and not M2.entrada("porta", 0.4, 1), "ao ligar com alguém na porta: não avisa")
r_ = [M2.entrada("porta", float(t), 0) for t in range(1, 26)]
ok(not any(r_), "porta vazia: nada")
ok(not M2.entrada("porta", 26.0, 1), "1 leitura com pessoa: ainda não (falso positivo de 1 quadro)")
ok(M2.entrada("porta", 26.4, 1), "2 leituras seguidas após 20 s vazia: AVISA")
ok(not M2.entrada("porta", 26.8, 1), "continua lá: não repete")
M2.entrada("porta", 27.0, 0); M2.entrada("porta", 30.0, 0)
ok(not M2.entrada("porta", 31.0, 1) and not M2.entrada("porta", 31.4, 1), "saiu e voltou em < 20 s: não avisa de novo")
ok([M2.gesto("porta", t, True) for t in range(4)] == [False, False, True, False], "mão levantada 3 leituras: gesto 1 vez")
M2.gesto("porta", 5, False)
ok([M2.gesto("porta", t, True) for t in range(6, 9)] == [False, False, True], "baixou e levantou de novo: novo gesto")

print("mão levantada (keypoints COCO)")
k = np.zeros((17, 3), np.float32); k[:, 2] = 0.9
k[0][1] = 100; k[5][1] = k[6][1] = 150; k[9][1] = k[10][1] = 300
ok(not ptz.mao_alta(k), "pulsos abaixo do nariz: não")
k[10][1] = 60
ok(ptz.mao_alta(k), "pulso direito acima do nariz: sim")
k[0][2] = 0.1; k[10][1] = 140
ok(ptz.mao_alta(k), "sem nariz: usa os ombros")
k[10][2] = 0.1
ok(not ptz.mao_alta(k), "pulso sem confiança: não")

print("zoom digital")
img = np.zeros((720, 1280, 3), np.uint8)
cv2.circle(img, (1000, 200), 30, (0, 0, 255), -1)                    # "celular" no canto superior direito
ptz.G.quadro_hd = lambda: img
ptz.G.detectar = lambda fr: [("celular", 0.9, (970, 170, 60, 60))]
p = novo()
r = p.zoom(3, "celular")
z = cv2.imread("/tmp/friday-zoom.jpg")
ok(z is not None and z.shape[:2] == (720, 1280), "recorte ampliado de volta a 1280x720")
ok(z is not None and z[360, 640, 2] > 200, "o alvo detectado fica no centro do zoom")
ok("celular" in r, f"resposta cita o alvo: {r!r}")
r = p.zoom(9, "")
ok("4.0x" in r, "fator limitado a 4x")
ptz.G.vlm = lambda jpg, perg: "Um círculo vermelho."
ok(p.zoom(2, "celular", "o que é isso?") == "Um círculo vermelho.", "com pergunta: o VLM responde sobre o recorte")

print(f"\n{'TUDO OK' if not falhas else str(len(falhas)) + ' FALHA(S)'}")
sys.exit(1 if falhas else 0)
