"""Regressão da câmera PTZ (15/10/2026) — roda SEM câmera/VLM (tudo simulado):
    .venv/bin/python daemon/teste_ptz.py
Cobre: modo salvo no "pare", pausa após olhar, nomes por extenso/padrão, trava do seguir (continuidade + distância),
checagem de pessoa (cache/fantasma), localizar pela posição padrão, autolocalização pela imagem, normalização de fala."""
import os, re, sys, time, types
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, ipcam, ptz

CONF = {"pan_total_s": 54.9, "tilt_total_s": 34.0, "pan_v": 0.16, "tilt_v": 0.17, "tilt_horizonte": 9.0,
        "posicoes": {"porta 1": [0.0, 9.0], "porta 3": [34.19, 9.0], "guarda-roupa": [29.3, 9.0], "minha posição": [11.86, 1.52]},
        "posicoes_fixas": ["minha posição", "porta 3"], "modo": "auto"}
gravado = {}
ipcam.ler_conf = lambda: dict(CONF)
ipcam.salvar_conf = lambda **kw: (CONF.update(kw), gravado.update(kw))
ptz._conf = lambda: dict(ptz._PADRAO, **CONF)
ptz.log = lambda msg: None                               # não suja /tmp/friday-ptz.log (o daemon real usa)
falhas = []


def ok(cond, nome):
    print(("  ok  " if cond else "  FALHOU ") + nome)
    if not cond:
        falhas.append(nome)


def novo():
    p = ptz.PTZ.__new__(ptz.PTZ)
    p.pan, p.tilt, p.modo, p.modo_salvo, p.ocupada = 20.0, 9.0, "seguir", "auto", None
    p._parar_tarefa = types.SimpleNamespace(set=lambda: None, is_set=lambda: False, clear=lambda: None)
    p.alvo, p._fantasmas, p._reais = None, [], []
    p._giro_desde = lambda t0, eixo: 0.0
    p._integrar = lambda: None
    return p


print("modo / pausa")
p = novo()
ptz.G.modo_mudou = lambda m: None
p.cam_ = None
type(p).cam = property(lambda s: None)
p.parar()
ok(CONF["modo"] == "auto" and p.modo == "livre", '"pare" não grava modo livre (reboot volta ao automático)')
ok(p._pausa_ate - time.time() > 500, '"pare" segura o automático ~10 min')
p.definir_modo("livre", salvar=False)
ok(55 < p._pausa_ate - time.time() <= 60, '"olhe para X" segura o automático 60 s')
p.definir_modo("seguir")
ok(p._pausa_ate == 0.0, '"me siga" libera na hora')

print("nomes de posição")
A = ptz.PTZ.achar_posicao
ok(A("porta três") == [34.19, 9.0], "porta três -> porta 3")
ok(A("a porta um") == [0.0, 9.0], "a porta um -> porta 1")
ok(A("padrão") == [11.86, 1.52] and A("mim") == [11.86, 1.52], "padrão/mim -> minha posição")
ok(A("armário") == [29.3, 9.0], "armário -> guarda-roupa")
ok(A("porta 9") is None, "posição inexistente -> None")

print("checagem de pessoa (VLM simulado)")
fr = np.zeros((360, 640, 3), np.uint8)
q = {"caixa": (0.4, 0.2, 0.6, 0.9), "conf": 0.8, "kp": 8, "cabeca": (0.5, 0.25)}
chamadas = []
ptz.G.vlm = lambda jpg, perg: (chamadas.append(perg), resp[0])[1]
resp = ["sim."]
p = novo()
ok(p._pessoa_real(fr, q) is True, "VLM sim -> aceita")
ok(p._pessoa_real(fr, q) is True and len(chamadas) == 1, "confirmada há pouco: não pergunta de novo (cache)")
p = novo(); chamadas.clear(); resp[0] = "não."
ok(p._pessoa_real(fr, q) is False, "VLM não -> descarta (entalhe do guarda-roupa)")
ok(p._pessoa_real(fr, q) is False and len(chamadas) == 2, "1 'não' não basta para marcar (pergunta de novo)")
ok(p._pessoa_real(fr, q) is False and len(chamadas) == 2, "2 'não' no mesmo ponto: marcado, não pergunta mais")
p2 = novo(); p2._fantasmas = [(20.0, time.time())]; resp[0] = "sim."
ok(p2._pessoa_real(fr, q) is True and p2._fantasmas == [], "'sim' no ponto apaga o 'não' antigo (não perde o dono)")
resp[0] = "não."
ok("retângulo vermelho" in (chamadas[0] if chamadas else ""), "manda quadro inteiro com retângulo (não recorte minúsculo)")

print("trava do seguir")
p = novo(); resp[0] = "sim."
p._fr_escolha = None
perto = {"caixa": (0.45, 0.2, 0.55, 0.9), "conf": 0.6, "kp": 3, "cabeca": (0.52, 0.3)}
longe = {"caixa": (0.0, 0.2, 0.1, 0.9), "conf": 0.9, "kp": 9, "cabeca": (0.05, 0.3)}
p.alvo = {"x": 0.5, "y": 0.3, "caixa": None, "t": 100.0}
ok(p._escolher([longe, perto], 103.0) is perto, "3 s sem ver: continua no mesmo alvo (antes perdia com 1,5 s)")
p._fr_escolha = fr; resp[0] = "não."
ok(p._escolher([longe], 103.0) is None, "só tem coisa longe do alvo: não pula para ela sem checar (VLM não)")

print("localizar pela posição padrão")
p = novo(); resp[0] = "sim."; idas = []
p.disponivel = lambda: True
p.ir_posicao = lambda n: idas.append(n)
p._quadro_apos = lambda t, espera=6.0: fr
p.pose = lambda: types.SimpleNamespace(pessoas=lambda f, conf=0.35: [q])
p._centralizar_rapido = lambda f: None
p.definir_modo = lambda m, salvar=True: setattr(p, "modo", m)
p.procurar = lambda *a, **k: "varreu"
r = p.localizar_dono()
ok(idas == ["minha posição"] and p.modo == "seguir" and "lugar de sempre" in r, "vai à posição padrão e segue sem varrer")
p.pose = lambda: types.SimpleNamespace(pessoas=lambda f, conf=0.35: [])
ok(p.localizar_dono() == "varreu", "não está lá: varre o quarto")

print("procura: faixa baixa primeiro")
p = novo(); voltas = []
p.disponivel = lambda: True
p._tarefa = lambda n: True
p._fim_tarefa = lambda: None
p._varrer_continuo = lambda f, foto_a_cada=None, desde_atual=False, tilt=None: voltas.append(tilt) or []
p.cobertura = (54.9, 54.9)
p.ancorar_tilt = lambda: None
p.ir = lambda pan, tilt, esperar=True: True
r = p.procurar("você", True)
ok(voltas == [8.0, 4.5, 11.0], f"PTZ na mesa: 1º altura do rosto sentado (8), depois baixo (piso 4,5) e alto (11) (voltas={voltas})")

print("altura real (batente de baixo)")
p = novo(); p.tilt = 1.51; giros = []
p.girar_s = lambda dp, dt, esperar=True: giros.append((dp, dt)) or True
p.ancorar_tilt()
ok(giros and giros[0][0] == 0 and giros[0][1] < -(1.51 + 8) and p.tilt == 0.0, f"desce além do batente e zera a altura (giro {giros})")
p = novo(); p.tilt = 1.51; ordem = []
p.disponivel = lambda: True; p._tarefa = lambda n: True; p._fim_tarefa = lambda: None; p.cobertura = (54.9, 54.9)
p.ancorar_tilt = lambda: ordem.append("ancora")
p.ir = lambda pan, tilt, esperar=True: ordem.append(("ir", tilt))
p._varrer_continuo = lambda f, foto_a_cada=None, desde_atual=False, tilt=None: ordem.append(("varre", tilt)) or []
p.procurar("você", True)
ok(ordem[:3] == ["ancora", ("ir", 8.0), ("varre", 8.0)], f"procura: ancora embaixo, sobe à altura do rosto sentado, varre (ordem {ordem[:3]})")

print("de perto: rosto confirma pessoa (16/10, PTZ na mesa ao lado do dono)")
resp[0] = "não."; chamadas.clear()
ptz.G.rostos = lambda: (time.time(), [(0.45, 0.25, 0.58, 0.45)])           # rosto grande dentro da caixa
p = novo()
ok(p._pessoa_real(fr, q) is True and not chamadas, "rosto na caixa -> pessoa, sem VLM (VLM dizia 'não' ao dono colado na câmera)")
ptz.G.rostos = lambda: (time.time(), [(0.50, 0.30, 0.52, 0.33)])           # rostinho (reflexo no espelho)
p = novo()
ok(p._pessoa_real(fr, q) is False and len(chamadas) == 1, "rosto minúsculo (reflexo) não conta: vai ao VLM")
ptz.G.rostos = lambda: (time.time() - 10, [(0.45, 0.25, 0.58, 0.45)])      # rosto velho
ok(ptz.PTZ._rosto_na_caixa(q) is False, "rosto de 10 s atrás não confirma")
ptz.G.rostos = staticmethod(lambda: (0.0, []))
ok(ptz.PTZ._rosto_na_caixa({"caixa": (0.1, 0.1, 0.3, 0.9)}) is False, "sem rosto (antena da câmera) não confirma")

print("amigos no quarto (16/10): só o rosto do dono trava")
amigo = {"caixa": (0.1, 0.1, 0.4, 0.9), "conf": 0.9, "kp": 9, "cabeca": (0.25, 0.2)}
dono_q = {"caixa": (0.6, 0.1, 0.9, 0.9), "conf": 0.7, "kp": 9, "cabeca": (0.75, 0.2)}
ptz.G.dono = staticmethod(lambda: (time.time(), (0.70, 0.15, 0.80, 0.30)))
ok(ptz.PTZ._dono_na_caixa(dono_q) and not ptz.PTZ._dono_na_caixa(amigo), "rosto do dono só dentro da caixa dele")
ptz.G.sentado = staticmethod(lambda: True)
p = novo(); p._fr_escolha = None
ptz.G.dono = staticmethod(lambda: None)
ok(p._escolher([amigo], time.time()) is None, "nativa te vê sentado e só o amigo aparece: não trava no amigo")
ptz.G.dono = staticmethod(lambda: (time.time(), (0.70, 0.15, 0.80, 0.30)))
ok(p._escolher([amigo, dono_q], time.time()) is dono_q, "amigo + dono no quadro: trava no dono")
amigo_grande = {"caixa": (0.05, 0.0, 1.0, 1.0), "conf": 0.9, "kp": 9, "cabeca": (0.40, 0.25)}   # amigo em pé enchendo o quadro
dono_borda = {"caixa": (0.82, 0.05, 1.0, 0.9), "conf": 0.5, "kp": 4, "cabeca": (0.92, 0.25)}
ptz.G.dono = staticmethod(lambda: (time.time(), (0.88, 0.18, 0.96, 0.32)))
ok(p._escolher([amigo_grande, dono_borda], time.time()) is dono_borda, "caixa do amigo engole o rosto do dono: trava no dono (cabeça)")
ok(not ptz.PTZ._dono_na_caixa(amigo_grande), "rosto do dono dentro da caixa do amigo, longe da cabeça dele: não é o amigo")
ptz.G.sentado = staticmethod(lambda: False); ptz.G.dono = staticmethod(lambda: None)

print("roupa do dono pela nativa (16/10: amigo de laranja virava 'você')")
quadro = np.full((360, 640, 3), (60, 140, 90), np.uint8)                   # fundo colorido (não é infravermelho)
quadro[:, 320:] = (128, 128, 128)                                           # metade direita: moletom cinza (dono)
quadro[:, :320] = (0, 120, 255)                                             # metade esquerda: camiseta laranja (amigo)
q_amigo = {"caixa": (0.0, 0.0, 0.5, 1.0)}; q_dono = {"caixa": (0.5, 0.0, 1.0, 1.0)}
ptz.G.camisa_dono = staticmethod(lambda: (time.time(), [0.0, 5.0, 128.0]))   # nativa: roupa cinza
ok(ptz.PTZ._cor_confere(quadro, q_dono) is True and ptz.PTZ._cor_confere(quadro, q_amigo) is False, "cinza = dono, laranja = amigo")
ok(ptz.PTZ._cor_confere(np.full((360, 640, 3), 120, np.uint8), q_dono) is None, "quadro P&B (infravermelho): cor não decide")
ptz.G.camisa_dono = staticmethod(lambda: None)

print("mapa das fixas: refutação")
import mundo as _mu
M = _mu.Mundo.__new__(_mu.Mundo)
import threading as _th
M._lock, M.obs, M._sujo, M._discorda = _th.Lock(), {}, False, {}
M.salvar = lambda: None
M.pares = {"nativa": [[0.50, 0.50, 7.0, 5.0, 0], [0.52, 0.55, 9.0, 5.0, 0], [0.90, 0.20, 40.0, 9.0, 0]]}
M.observar("nativa", time.time(), [(0.51, 0.52, 0.9)])
ok(M.refutar() == 2 and len(M.pares["nativa"]) == 1 and M.pares["nativa"][0][2] == 40.0,
   "foi ao pan do mapa e não havia ninguém: apaga só os pares perto do que a nativa vê agora")

print("autolocalização pela imagem")
rng = np.random.default_rng(1)
cena = cv2.GaussianBlur((rng.random((360, 1400)) * 255).astype(np.uint8), (0, 0), 2)
cena = cv2.cvtColor(cena, cv2.COLOR_GRAY2BGR)
def vista(pan):                                         # 1 s de motor = pan_v da largura (640 px)
    x = int(200 + pan * 0.16 * 640)
    return cena[:, x:x + 640]
p = novo(); p.pan = 40.0                                 # estimativa perdida
p._vistas = [(pv, cv2.resize(vista(pv), (320, 180))) for pv in (0.0, 2.0, 4.0)]
r = p.onde_estou(vista(2.7))
ok(r is not None and abs(r[0] - 2.7) < 0.15, f"acha pan 2,7 com estimativa em 40 (deu {r and round(r[0], 2)})")

print("fala -> pedido de câmera")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "prometheus.py")).read()
i = src.index("def _limpa_fala(txt):"); j = src.index("    rec = [b for t_, b in _ditas", i)
k = src.index("_NOMES_STT = ["); k2 = src.index("\n\n\ndef _limpa_fala", k)
ns = {"re": re}
exec(src[k:k2], ns)
exec(src[i:j] + "    return txt\n", ns)
L = ns["_limpa_fala"]
for t in ["Sexta-feira, me localize.", "Me achar.", "Sexta-feira, Miyashi.", "onde eu estou?", "Sutta Feira, me localize."]:
    ok("me localiza" in L(t) or "me ache com a câmera" in L(t), f"{t!r} -> me localiza")
ok("mapeie o quarto" in L("Sexta-feira, decora o quarto."), "decora o quarto -> mapeie")
for t in ["Sutta Feira, me localize.", "Sinta feira, me localize.", "Seta-feira, me localize.", "Danta fera, me localize."]:
    ok(L(t).startswith("Sexta-feira") , f"wake estropiado {t!r} -> {L(t)!r}")
ok(L("E agora, Danta fera?").endswith("Sexta-feira."), "wake estropiado no fim")
for t in ["Marque reunião na segunda-feira", "Terça-feira tenho dentista", "o que tem na quinta-feira"]:
    ok(L(t) == t, f"dia da semana não vira Sexta-feira: {t!r}")
ok(L("onde está minha chave na mesa") == "onde está minha chave na mesa", "frase normal não muda")

print("comandos (16/10): STT do celular e 2 pedidos na mesma fala")
for t in ["Desmoquear celular.", "Desmulquear o celular", "Desbloquear Navegador."]:
    ok(re.search(r"desbloque\w*\b.*\bcelular", L(t), re.I) is not None, f"{t!r} -> {L(t)!r}")
i2 = src.index("_WAKE_MEIO = "); j2 = src.index("    return pedacos[:3]", i2)
ns2 = {"re": re, "WAKE_RE": re.compile(r"\b(sexta[\s\-]*feira|friday)\b", re.I)}
exec(src[i2:j2] + "    return pedacos[:3]\n", ns2)
D = ns2["_dividir_comandos"]
ok(len(D("Desbloqueia o celular. Sexta-Feira, me localize.")) == 2, "2 pedidos na mesma fala viram 2")
ok(len(D("Ontem foi bom. Sexta-feira vai ter festa.")) == 1, "'sexta-feira' como dia não divide")
ok(len(D("Sexta-feira, toca Yellow.")) == 1, "1 pedido continua 1")

print(f"\n{'TUDO OK' if not falhas else str(len(falhas)) + ' FALHA(S)'}")
sys.exit(1 if falhas else 0)
