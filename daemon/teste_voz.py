"""Regressão do filtro "só a voz do dono" (voz.decidir estrito) — sem microfone/modelo: o "embedding" é o próprio volume
do trecho (amplitude 0.5 = voz do dono, 0.2 = outra pessoa). Rodar: ../.venv/bin/python teste_voz.py"""
import numpy as np
import voz

SR = voz.SR
class _V(voz.VozDono):
    limiar = 0.43
    pronto = True


V = _V.__new__(_V)
V.embed = lambda a: float(np.abs(a).mean()) if len(a) else 0.0
V.score = lambda e: 0.9 if e > 0.3 else (0.1 if e is not None else 0.0)     # trecho alto = dono
fal = []


def ok(c, nome):
    print(("  ok  " if c else "  FALHOU ") + nome)
    if not c:
        fal.append(nome)


def fala(seg):
    return np.concatenate([np.full(int(d * SR), amp, dtype="float32") * np.sign(np.sin(np.arange(int(d * SR)))) for amp, d in seg])


a = fala([(0.2, 3.0)])                                       # amigo falando 3 s ("Sexta-feira, ..." na voz dele)
r = V.decidir(a, dono_recente=True, estrito=True)
ok(r[0] is False, "amigo (fala longa) recusado mesmo com o dono ativo há pouco")
a = fala([(0.2, 1.2)])
ok(V.decidir(a, estrito=True)[0] is False, "amigo (fala curta) recusado")
a = fala([(0.5, 1.3)])
ok(V.decidir(a, estrito=True)[0] is True, "dono (fala curta) aceito")
a = fala([(0.2, 15.0), (0.5, 3.0), (0.2, 4.0)])             # 22 s: amigos + 3 s do dono no meio
r = V.decidir(a, estrito=True)
ok(r[0] is True and len(r[1]) / SR < 6.5, f"mistura de 22 s: só os trechos do dono vão ao STT ({len(r[1]) / SR:.1f} s)")
ok(float(np.abs(r[1]).mean()) > 0.3, "o recorte é a voz do dono (não a dos amigos)")
a = fala([(0.5, 4.0)])
r = V.decidir(a, estrito=True)
ok(r[0] is True and len(r[1]) == len(a), "dono falando sozinho: áudio inteiro, sem recorte")
print("TUDO OK" if not fal else f"{len(fal)} FALHA(S)")
raise SystemExit(1 if fal else 0)
