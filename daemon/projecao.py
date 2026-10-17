"""Motor de Projeção Holográfica 3D da F.R.I.D.A.Y. (Modo Projeção).

Gera e projeta objetos holográficos 3D em segundos via comandos de voz, com suporte a
IA em nuvem e gerador paramétrico ultra-rápido de alta fidelidade Stark.

Comandos de Voz Suportados:
  - "Sexta-feira, modo projeção" / "ativar projeção"
  - "projete um [objeto]" (ex: reator arc, carro, drone, nave, satélite, robô, dna, motor, planeta...)
  - "modele [objeto]" / "modifique a projeção para [alteração]" (ex: aumente o reator, gire mais rápido, visão explodida, mude a cor para dourado)
  - "fechar projeção" / "dispensar holograma"
"""
import json, math, os, random, re, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_estado_projecao = {
    "ativo": False,
    "objeto_atual": None,
    "nome": "",
    "rot_x": 0.35,
    "rot_y": 0.0,
    "rot_speed": 0.8,
    "zoom": 1.0,
    "modo": "wireframe",      # wireframe | particulas | raio_x | explodido
    "cor": "#00d2ff",
    "explodir": 0.0,
}


def _rot3d(p, ax, ay, az=0.0):
    """Rotaciona ponto [x, y, z] nos eixos X, Y, Z."""
    x, y, z = p[0], p[1], p[2]
    # Rotação Y
    cy, sy = math.cos(ay), math.sin(ay)
    x1 = x * cy + z * sy
    z1 = -x * sy + z * cy
    y1 = y
    # Rotação X
    cx, sx = math.cos(ax), math.sin(ax)
    y2 = y1 * cx - z1 * sx
    z2 = y1 * sx + z1 * cx
    x2 = x1
    return [x2, y2, z2]


# =============================================================================
# BIBLIOTECA PROCEDURAL DE OBJETOS 3D STARK (Instantâneo: < 10ms)
# =============================================================================

def _gerar_reator_arc():
    V = []
    E = []
    P = []
    # 1. Núcleo central emissor
    V.append([0.0, 0.0, 0.0])
    for i in range(12):
        a = i / 12.0 * math.pi * 2
        V.append([math.cos(a) * 0.18, math.sin(a) * 0.18, 0.0])
        E.append([0, i + 1])
        E.append([i + 1, (i + 1) % 12 + 1])

    # 2. Anel magnético interno
    offset1 = len(V)
    for i in range(16):
        a = i / 16.0 * math.pi * 2
        V.append([math.cos(a) * 0.42, math.sin(a) * 0.42, 0.05])
        V.append([math.cos(a) * 0.42, math.sin(a) * 0.42, -0.05])
        idx = offset1 + i * 2
        E.append([idx, idx + 1])
        E.append([idx, offset1 + ((i + 1) % 16) * 2])
        E.append([idx + 1, offset1 + ((i + 1) % 16) * 2 + 1])

    # 3. 10 Bobinas de cobre magnéticas periféricas
    offset2 = len(V)
    for i in range(10):
        a = i / 10.0 * math.pi * 2
        cx, cy = math.cos(a) * 0.68, math.sin(a) * 0.68
        for dz in (-0.08, 0.08):
            for dr in (-0.08, 0.08):
                bx = math.cos(a) * (0.68 + dr) - math.sin(a) * (dr * 0.5)
                by = math.sin(a) * (0.68 + dr) + math.cos(a) * (dr * 0.5)
                V.append([bx, by, dz])
        k = offset2 + i * 4
        E.append([k, k + 1]); E.append([k + 1, k + 3]); E.append([k + 3, k + 2]); E.append([k + 2, k])
        E.append([k, k + 2]); E.append([k + 1, k + 3])

    # 4. Anel de contenção externo
    offset3 = len(V)
    for i in range(24):
        a = i / 24.0 * math.pi * 2
        V.append([math.cos(a) * 0.95, math.sin(a) * 0.95, 0.0])
        idx = offset3 + i
        E.append([idx, offset3 + (i + 1) % 24])

    # Partículas de plasma fluindo
    for i in range(40):
        a = random.random() * math.pi * 2
        r = 0.2 + random.random() * 0.7
        P.append([math.cos(a) * r, math.sin(a) * r, (random.random() - 0.5) * 0.2, 2.0, "#00d2ff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "REATOR ARC MARK VII", "categoria": "ENERGIA"}


def _gerar_carro():
    V = [
        # Chassi inferior (8)
        [-0.45, -0.15, -0.9], [0.45, -0.15, -0.9], [0.45, -0.15, 0.9], [-0.45, -0.15, 0.9],
        [-0.42, 0.0, -0.85], [0.42, 0.0, -0.85], [0.42, 0.0, 0.85], [-0.42, 0.0, 0.85],
        # Cabine / Teto (4)
        [-0.32, 0.25, -0.2], [0.32, 0.25, -0.2], [0.30, 0.22, 0.35], [-0.30, 0.22, 0.35],
        # Aerofólio traseiro (4)
        [-0.38, 0.18, 0.88], [0.38, 0.18, 0.88], [0.38, 0.22, 0.95], [-0.38, 0.22, 0.95],
        # Faróis dianteiros (4)
        [-0.38, -0.05, -0.92], [-0.22, -0.05, -0.92], [0.22, -0.05, -0.92], [0.38, -0.05, -0.92]
    ]
    E = [
        # Linhas do chassi
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7],
        # Conexões da cabine
        [4, 8], [5, 9], [6, 10], [7, 11],
        [8, 9], [9, 10], [10, 11], [11, 8],
        # Pára-brisa e capô
        [8, 0], [9, 1],
        # Aerofólio
        [12, 13], [13, 14], [14, 15], [15, 12],
        [6, 12], [7, 13],
        # Faróis
        [16, 17], [18, 19]
    ]
    # 4 Rodas poligonais
    for wx, wz in ((-0.48, -0.55), (0.48, -0.55), (-0.48, 0.55), (0.48, 0.55)):
        base = len(V)
        for i in range(8):
            a = i / 8.0 * math.pi * 2
            V.append([wx, -0.15 + math.sin(a) * 0.14, wz + math.cos(a) * 0.14])
        for i in range(8):
            E.append([base + i, base + (i + 1) % 8])
            E.append([base + i, base + (i + 4) % 8])

    P = []
    for _ in range(30):
        P.append([(random.random() - 0.5) * 0.8, -0.1 + random.random() * 0.3, (random.random() - 0.5) * 1.6, 1.8, "#00d2ff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "VEÍCULO STARK CYBER-GT", "categoria": "TRANSPORTE"}


def _gerar_drone():
    V = [
        # Fuselagem central (octógono duplo)
        [-0.15, -0.05, -0.15], [0.15, -0.05, -0.15], [0.15, -0.05, 0.15], [-0.15, -0.05, 0.15],
        [-0.12, 0.06, -0.12], [0.12, 0.06, -0.12], [0.12, 0.06, 0.12], [-0.12, 0.06, 0.12],
        # Gimbal da câmera inferior
        [0.0, -0.14, 0.0], [0.0, -0.14, -0.08]
    ]
    E = [
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7],
        [0, 8], [1, 8], [2, 8], [3, 8], [8, 9]
    ]
    # 4 Braços com rotores
    rotores = [(-0.65, 0.02, -0.65), (0.65, 0.02, -0.65), (0.65, 0.02, 0.65), (-0.65, 0.02, 0.65)]
    for rx, ry, rz in rotores:
        arm_idx = len(V)
        V.append([rx, ry, rz])
        # Conecta braço ao centro
        E.append([arm_idx, 0 if rx < 0 and rz < 0 else 1 if rx > 0 and rz < 0 else 2 if rx > 0 and rz > 0 else 3])
        # Disco do rotor
        c_base = len(V)
        for i in range(10):
            a = i / 10.0 * math.pi * 2
            V.append([rx + math.cos(a) * 0.22, ry, rz + math.sin(a) * 0.22])
            E.append([c_base + i, c_base + (i + 1) % 10])
            if i % 2 == 0:
                E.append([arm_idx, c_base + i])

    P = []
    for rx, ry, rz in rotores:
        for _ in range(8):
            a = random.random() * math.pi * 2
            P.append([rx + math.cos(a) * 0.20, ry + (random.random() - 0.5) * 0.05, rz + math.sin(a) * 0.20, 2.0, "#00ffff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "DRONE AUTÔNOMO VIGILANTE", "categoria": "AEROPESPACIAL"}


def _gerar_nave():
    V = [
        # Nariz / Cabine
        [0.0, 0.0, -0.95], [0.0, 0.12, -0.6], [0.0, -0.06, -0.6],
        # Fuselagem média
        [-0.22, 0.08, -0.1], [0.22, 0.08, -0.1], [-0.22, -0.08, -0.1], [0.22, -0.08, -0.1],
        # Asas em delta
        [-0.92, 0.02, 0.45], [0.92, 0.02, 0.45],
        [-0.88, 0.16, 0.52], [0.88, 0.16, 0.52],  # Pontas verticais das asas
        # Turbinas traseiras gêmeas
        [-0.18, 0.0, 0.75], [0.18, 0.0, 0.75],
        [-0.18, 0.08, 0.85], [0.18, 0.08, 0.85]
    ]
    E = [
        [0, 1], [0, 2], [1, 3], [1, 4], [2, 5], [2, 6],
        [3, 4], [4, 6], [6, 5], [5, 3],
        # Asas
        [3, 7], [5, 7], [4, 8], [6, 8],
        [7, 9], [8, 10], [9, 11], [10, 12],
        # Turbinas
        [3, 11], [4, 12], [5, 11], [6, 12],
        [11, 13], [12, 14], [13, 14]
    ]
    P = []
    # Rastro de íons dos motores
    for tz in (0.75, 0.85, 0.95, 1.05, 1.15):
        for tx in (-0.18, 0.18):
            P.append([tx + (random.random() - 0.5) * 0.08, (random.random() - 0.5) * 0.08, tz, 2.4, "#00d2ff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "QUINJET HIPERSÔNICO STARK", "categoria": "AEROESPACIAL"}


def _gerar_satelite():
    V = [
        # Corpo central (cubo alongado)
        [-0.2, -0.2, -0.2], [0.2, -0.2, -0.2], [0.2, 0.2, -0.2], [-0.2, 0.2, -0.2],
        [-0.2, -0.2, 0.2], [0.2, -0.2, 0.2], [0.2, 0.2, 0.2], [-0.2, 0.2, 0.2],
        # Painel solar esquerdo
        [-0.3, 0.0, 0.0], [-0.95, 0.22, 0.0], [-0.95, -0.22, 0.0], [-0.3, -0.22, 0.0], [-0.3, 0.22, 0.0],
        # Painel solar direito
        [0.3, 0.0, 0.0], [0.95, 0.22, 0.0], [0.95, -0.22, 0.0], [0.3, -0.22, 0.0], [0.3, 0.22, 0.0],
        # Antena parabólica frontal
        [0.0, 0.0, -0.32], [0.0, 0.0, -0.45]
    ]
    E = [
        # Cubo
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7],
        # Painel solar esquerdo
        [0, 8], [8, 9], [9, 10], [10, 11], [11, 12], [12, 9],
        # Painel solar direito
        [1, 13], [13, 14], [14, 15], [15, 16], [16, 17], [17, 14],
        # Antena
        [2, 18], [18, 19]
    ]
    # Prato parabólico
    p_base = len(V)
    for i in range(12):
        a = i / 12.0 * math.pi * 2
        V.append([math.cos(a) * 0.25, math.sin(a) * 0.25, -0.45])
        E.append([p_base + i, p_base + (i + 1) % 12])
        E.append([p_base + i, 19])

    P = []
    for _ in range(25):
        P.append([(random.random() - 0.5) * 1.8, (random.random() - 0.5) * 0.6, (random.random() - 0.5) * 0.8, 1.5, "#7fe6ff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "SATÉLITE ORBITAL PROMETHEUS", "categoria": "TELEMETRIA"}


def _gerar_dna():
    V = []
    E = []
    P = []
    N = 28
    for i in range(N):
        a = i / float(N) * math.pi * 4
        y = (i / float(N) - 0.5) * 1.8
        x1, z1 = math.cos(a) * 0.45, math.sin(a) * 0.45
        x2, z2 = math.cos(a + math.pi) * 0.45, math.sin(a + math.pi) * 0.45
        idx = len(V)
        V.append([x1, y, z1])
        V.append([x2, y, z2])
        # Ponte de hidrogênio (degrau do DNA)
        E.append([idx, idx + 1])
        # Hélice longitudinal
        if i > 0:
            E.append([idx - 2, idx])
            E.append([idx - 1, idx + 1])
        # Átomos nas extremidades
        P.append([x1, y, z1, 3.0, "#00d2ff"])
        P.append([x2, y, z2, 3.0, "#ffaa00"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "DUPLA HÉLICE GENÉTICA", "categoria": "BIOLOGIA"}


def _gerar_robo():
    V = [
        # Cabeça / Capacete
        [-0.15, 0.55, -0.15], [0.15, 0.55, -0.15], [0.15, 0.55, 0.15], [-0.15, 0.55, 0.15],
        [-0.18, 0.78, -0.12], [0.18, 0.78, -0.12], [0.18, 0.78, 0.12], [-0.18, 0.78, 0.12],
        # Olhos / Visor
        [-0.10, 0.65, -0.16], [0.10, 0.65, -0.16],
        # Tronco / Reator Arc no Peito
        [-0.32, 0.15, -0.18], [0.32, 0.15, -0.18], [0.32, 0.15, 0.18], [-0.32, 0.15, 0.18],
        [-0.24, -0.25, -0.14], [0.24, -0.25, -0.14], [0.24, -0.25, 0.14], [-0.24, -0.25, 0.14],
        [0.0, 0.28, -0.20],  # Reator de peito
        # Braços
        [-0.52, 0.12, 0.0], [-0.55, -0.32, 0.0],
        [0.52, 0.12, 0.0], [0.55, -0.32, 0.0],
        # Pernas
        [-0.18, -0.75, 0.0], [0.18, -0.75, 0.0]
    ]
    E = [
        # Capacete
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7],
        [8, 9],
        # Tronco
        [10, 11], [11, 12], [12, 13], [13, 10],
        [14, 15], [15, 16], [16, 17], [17, 14],
        [10, 14], [11, 15], [12, 16], [13, 17],
        [0, 10], [1, 11], [18, 10], [18, 11],
        # Braços
        [10, 19], [19, 20], [11, 21], [21, 22],
        # Pernas
        [14, 23], [15, 24]
    ]
    P = [
        [0.0, 0.28, -0.20, 4.0, "#ffffff"],  # Brilho do reator de peito
        [-0.10, 0.65, -0.16, 2.5, "#00ffff"],
        [0.10, 0.65, -0.16, 2.5, "#00ffff"],
        [-0.55, -0.32, 0.0, 3.0, "#00d2ff"],
        [0.55, -0.32, 0.0, 3.0, "#00d2ff"]
    ]
    return {"vertices": V, "arestas": E, "particulas": P, "nome": "ARMADURA MARK LXXXV", "categoria": "ROBÓTICA"}


def _gerar_esfera_tecnologica():
    V = []
    E = []
    P = []
    rings = 14
    segs = 24
    for i in range(1, rings):
        th = i / float(rings) * math.pi
        r_ring = math.sin(th) * 0.85
        y = math.cos(th) * 0.85
        offset = len(V)
        for j in range(segs):
            ph = j / float(segs) * math.pi * 2
            V.append([r_ring * math.cos(ph), y, r_ring * math.sin(ph)])
            E.append([offset + j, offset + (j + 1) % segs])
            if i > 1:
                E.append([offset + j, offset - segs + j])
    for _ in range(40):
        th = random.random() * math.pi
        ph = random.random() * math.pi * 2
        r = 0.88
        P.append([r * math.sin(th) * math.cos(ph), r * math.cos(th), r * math.sin(th) * math.sin(ph), 2.2, "#00d2ff"])
    return {"vertices": V, "arestas": E, "particulas": P, "nome": "ESFERA QUÂNTICA TESSERACT", "categoria": "ENERGIA"}


def _gerar_tiranossauro():
    V = []; E = []; P = []
    def add_p(x, y, z):
        idx = len(V)
        V.append([round(x, 4), round(y, 4), round(z, 4)])
        return idx
    def add_e(a, b):
        E.append([a, b])

    # 1. Crânio e Mandíbula
    s_tip = add_p(0.0, 0.38, -0.92)       # 0: ponta do focinho superior
    s_tl = add_p(-0.11, 0.44, -0.72)      # 1: topo focinho esq
    s_tr = add_p(0.11, 0.44, -0.72)       # 2: topo focinho dir
    s_bl = add_p(-0.09, 0.32, -0.72)      # 3: base focinho esq
    s_br = add_p(0.09, 0.32, -0.72)       # 4: base focinho dir
    ey_l = add_p(-0.15, 0.52, -0.50)      # 5: órbita ocular esq
    ey_r = add_p(0.15, 0.52, -0.50)       # 6: órbita ocular dir
    sk_tl = add_p(-0.13, 0.50, -0.34)     # 7: topo crânio esq
    sk_tr = add_p(0.13, 0.50, -0.34)      # 8: topo crânio dir
    sk_bl = add_p(-0.11, 0.30, -0.34)     # 9: base crânio esq
    sk_br = add_p(0.11, 0.30, -0.34)      # 10: base crânio dir

    # Focinho e caixa craniana
    add_e(s_tip, s_tl); add_e(s_tip, s_tr); add_e(s_tip, s_bl); add_e(s_tip, s_br)
    add_e(s_tl, s_tr); add_e(s_bl, s_br); add_e(s_tl, s_bl); add_e(s_tr, s_br)
    add_e(s_tl, ey_l); add_e(s_tr, ey_r); add_e(ey_l, sk_tl); add_e(ey_r, sk_tr)
    add_e(sk_tl, sk_tr); add_e(sk_bl, sk_br); add_e(sk_tl, sk_bl); add_e(sk_tr, sk_br)
    add_e(s_bl, sk_bl); add_e(s_br, sk_br); add_e(ey_l, ey_r)

    # Olhos incandescentes
    P.append([-0.13, 0.48, -0.50, 3.2, "#ff2233"])
    P.append([0.13, 0.48, -0.50, 3.2, "#ff2233"])

    # Mandíbula inferior (boca semi-aberta de predador)
    j_tip = add_p(0.0, 0.22, -0.88)       # 11: ponta da mandíbula
    j_ml = add_p(-0.08, 0.23, -0.66)      # 12: mandíbula meio esq
    j_mr = add_p(0.08, 0.23, -0.66)       # 13: mandíbula meio dir
    j_hl = add_p(-0.10, 0.28, -0.36)      # 14: articulação esq
    j_hr = add_p(0.10, 0.28, -0.36)      # 15: articulação dir
    add_e(j_tip, j_ml); add_e(j_tip, j_mr)
    add_e(j_ml, j_hl); add_e(j_mr, j_hr)
    add_e(j_hl, sk_bl); add_e(j_hr, sk_br)
    # Dentes holográficos
    t1 = add_p(-0.05, 0.28, -0.74); t2 = add_p(0.05, 0.28, -0.74)
    add_e(s_bl, t1); add_e(s_br, t2); add_e(t1, j_ml); add_e(t2, j_mr)

    # 2. Pescoço em S
    n_t1 = add_p(0.0, 0.44, -0.20)        # 18: vértebra pescoço alta
    n_b1 = add_p(0.0, 0.20, -0.20)        # 19: garganta
    n_t2 = add_p(0.0, 0.36, -0.06)        # 20: cernelha
    n_b2 = add_p(0.0, 0.08, -0.06)        # 21: base do pescoço
    add_e(sk_tl, n_t1); add_e(sk_tr, n_t1)
    add_e(sk_bl, n_b1); add_e(sk_br, n_b1)
    add_e(n_t1, n_b1); add_e(n_t1, n_t2); add_e(n_b1, n_b2); add_e(n_t2, n_b2)

    # 3. Tronco e Caixa Torácica
    sp_1 = add_p(0.0, 0.38, 0.14)         # 22: espinha dorsal média
    sp_2 = add_p(0.0, 0.40, 0.34)         # 23: espinha dorsal pélvica
    bl_1 = add_p(0.0, -0.06, 0.14)        # 24: ventre médio
    bl_2 = add_p(0.0, 0.04, 0.34)         # 25: ventre posterior
    rb_l1 = add_p(-0.20, 0.12, 0.14)      # 26: costela esq
    rb_r1 = add_p(0.20, 0.12, 0.14)       # 27: costela dir
    rb_l2 = add_p(-0.22, 0.16, 0.28)      # 28: flanco esq
    rb_r2 = add_p(0.22, 0.16, 0.28)       # 29: flanco dir
    add_e(n_t2, sp_1); add_e(sp_1, sp_2)
    add_e(n_b2, bl_1); add_e(bl_1, bl_2)
    add_e(sp_1, rb_l1); add_e(sp_1, rb_r1); add_e(rb_l1, bl_1); add_e(rb_r1, bl_1)
    add_e(sp_2, rb_l2); add_e(sp_2, rb_r2); add_e(rb_l2, bl_2); add_e(rb_r2, bl_2)
    add_e(rb_l1, rb_l2); add_e(rb_r1, rb_r2)

    # 4. Braços pequenos característicos do T-Rex
    a_sl = add_p(-0.16, 0.04, 0.02); a_el = add_p(-0.18, -0.06, -0.04); a_cl = add_p(-0.19, -0.12, -0.02)
    a_sr = add_p(0.16, 0.04, 0.02); a_er = add_p(0.18, -0.06, -0.04); a_cr = add_p(0.19, -0.12, -0.02)
    add_e(n_b2, a_sl); add_e(a_sl, a_el); add_e(a_el, a_cl)
    add_e(n_b2, a_sr); add_e(a_sr, a_er); add_e(a_er, a_cr)

    # 5. Bacia e Pernas Poderosas
    hp_l = add_p(-0.22, 0.28, 0.36); hp_r = add_p(0.22, 0.28, 0.36)
    add_e(sp_2, hp_l); add_e(sp_2, hp_r); add_e(hp_l, bl_2); add_e(hp_r, bl_2)

    # Perna Esquerda
    kn_l = add_p(-0.25, -0.08, 0.24)      # joelho
    hk_l = add_p(-0.24, -0.38, 0.44)      # jarrete p/ trás
    ft_l = add_p(-0.22, -0.74, 0.32)      # metatarso
    t_l1 = add_p(-0.30, -0.78, 0.16); t_l2 = add_p(-0.22, -0.78, 0.10); t_l3 = add_p(-0.14, -0.78, 0.16)
    add_e(hp_l, kn_l); add_e(kn_l, hk_l); add_e(hk_l, ft_l)
    add_e(ft_l, t_l1); add_e(ft_l, t_l2); add_e(ft_l, t_l3)
    add_e(t_l1, t_l2); add_e(t_l2, t_l3)

    # Perna Direita
    kn_r = add_p(0.25, -0.06, 0.18); hk_r = add_p(0.24, -0.36, 0.38); ft_r = add_p(0.22, -0.74, 0.26)
    t_r1 = add_p(0.14, -0.78, 0.10); t_r2 = add_p(0.22, -0.78, 0.04); t_r3 = add_p(0.30, -0.78, 0.10)
    add_e(hp_r, kn_r); add_e(kn_r, hk_r); add_e(hk_r, ft_r)
    add_e(ft_r, t_r1); add_e(ft_r, t_r2); add_e(ft_r, t_r3)
    add_e(t_r1, t_r2); add_e(t_r2, t_r3)

    # 6. Cauda Articulada de Equilíbrio
    tl_1t = add_p(0.0, 0.32, 0.54); tl_1b = add_p(0.0, 0.12, 0.54)
    tl_1l = add_p(-0.14, 0.22, 0.54); tl_1r = add_p(0.14, 0.22, 0.54)
    add_e(sp_2, tl_1t); add_e(bl_2, tl_1b); add_e(hp_l, tl_1l); add_e(hp_r, tl_1r)
    add_e(tl_1t, tl_1l); add_e(tl_1t, tl_1r); add_e(tl_1b, tl_1l); add_e(tl_1b, tl_1r)

    tl_2t = add_p(0.0, 0.24, 0.72); tl_2b = add_p(0.0, 0.08, 0.72)
    tl_2l = add_p(-0.10, 0.16, 0.72); tl_2r = add_p(0.10, 0.16, 0.72)
    add_e(tl_1t, tl_2t); add_e(tl_1b, tl_2b); add_e(tl_1l, tl_2l); add_e(tl_1r, tl_2r)
    add_e(tl_2t, tl_2l); add_e(tl_2t, tl_2r); add_e(tl_2b, tl_2l); add_e(tl_2b, tl_2r)

    tl_3t = add_p(0.0, 0.18, 0.90); tl_3b = add_p(0.0, 0.06, 0.90)
    tl_3l = add_p(-0.06, 0.12, 0.90); tl_3r = add_p(0.06, 0.12, 0.90)
    add_e(tl_2t, tl_3t); add_e(tl_2b, tl_3b); add_e(tl_2l, tl_3l); add_e(tl_2r, tl_3r)
    add_e(tl_3t, tl_3l); add_e(tl_3t, tl_3r); add_e(tl_3b, tl_3l); add_e(tl_3b, tl_3r)

    tl_tip = add_p(0.0, 0.14, 1.05)
    add_e(tl_3t, tl_tip); add_e(tl_3b, tl_tip); add_e(tl_3l, tl_tip); add_e(tl_3r, tl_tip)

    # 7. Nanopartículas de Biotelemetria ao longo da Coluna
    spine_z = [-0.72, -0.50, -0.34, -0.20, -0.06, 0.14, 0.34, 0.54, 0.72, 0.90, 1.05]
    for sz in spine_z:
        sy = 0.48 - abs(sz - 0.2) * 0.28
        P.append([0.0, sy + 0.03, sz, 2.5, "#00ff88"])
    for _ in range(25):
        P.append([
            (random.random() - 0.5) * 0.5,
            (random.random() - 0.5) * 0.6 + 0.1,
            (random.random() - 0.5) * 1.5,
            1.8,
            "#00d2ff"
        ])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "TIRANOSSAURO REX HOLOGRÁFICO", "categoria": "PALEONTOLOGIA"}


def _gerar_espada():
    V = []; E = []; P = []
    def add_p(x, y, z):
        idx = len(V)
        V.append([round(x, 4), round(y, 4), round(z, 4)])
        return idx

    tip = add_p(0.0, 0.98, 0.0)
    n_segs = 6
    blade_nodes = []
    for s in range(n_segs):
        y = 0.82 - s * 0.17
        w = 0.06 * (1.0 - s * 0.08)
        th = 0.015
        p1 = add_p(-w, y, 0.0); p2 = add_p(w, y, 0.0)
        p3 = add_p(0.0, y, th); p4 = add_p(0.0, y, -th)
        blade_nodes.append((p1, p2, p3, p4))
        E.extend([[p1, p3], [p3, p2], [p2, p4], [p4, p1]])
        if s > 0:
            prev = blade_nodes[s - 1]
            E.extend([[prev[0], p1], [prev[1], p2], [prev[2], p3], [prev[3], p4]])
        else:
            E.extend([[tip, p1], [tip, p2], [tip, p3], [tip, p4]])

    g_y = -0.22
    g_l = add_p(-0.35, g_y, 0.0); g_r = add_p(0.35, g_y, 0.0)
    g_f = add_p(0.0, g_y, 0.08); g_b = add_p(0.0, g_y, -0.08)
    b_bot = blade_nodes[-1]
    E.extend([[b_bot[0], g_l], [b_bot[1], g_r], [b_bot[2], g_f], [b_bot[3], g_b]])
    E.extend([[g_l, g_f], [g_f, g_r], [g_r, g_b], [g_b, g_l]])

    h_top = add_p(0.0, -0.24, 0.0); h_bot = add_p(0.0, -0.65, 0.0)
    E.append([h_top, h_bot])
    for i in range(4):
        hy = -0.32 - i * 0.08
        r = 0.035
        c_base = len(V)
        for a_idx in range(6):
            ang = a_idx / 6.0 * math.pi * 2
            V.append([round(math.cos(ang) * r, 4), round(hy, 4), round(math.sin(ang) * r, 4)])
            E.append([c_base + a_idx, c_base + (a_idx + 1) % 6])

    pommel = add_p(0.0, -0.78, 0.0)
    for a_idx in range(6):
        ang = a_idx / 6.0 * math.pi * 2
        px = add_p(math.cos(ang) * 0.06, -0.70, math.sin(ang) * 0.06)
        E.append([h_bot, px]); E.append([px, pommel])

    for _ in range(30):
        py = -0.2 + random.random() * 1.15
        px = (random.random() - 0.5) * 0.12
        pz = (random.random() - 0.5) * 0.06
        P.append([px, py, pz, 2.2, "#00d2ff"])
    P.append([0.0, -0.78, 0.0, 4.0, "#ffaa00"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "ESPADA DE PLASMA EXCALIBUR", "categoria": "ARMAMENTO"}


def _gerar_escudo():
    V = []; E = []; P = []
    rings = [(0.0, 0.15, 1), (0.28, 0.10, 6), (0.55, 0.02, 12), (0.82, -0.12, 18)]
    ring_bases = []
    for r, z, cnt in rings:
        b = len(V)
        ring_bases.append(b)
        for i in range(cnt):
            ang = i / float(cnt) * math.pi * 2
            V.append([round(math.cos(ang) * r, 4), round(math.sin(ang) * r, 4), round(z, 4)])
            if cnt > 1:
                E.append([b + i, b + (i + 1) % cnt])

    for i in range(6): E.append([ring_bases[0], ring_bases[1] + i])
    for i in range(12): E.append([ring_bases[1] + (i // 2), ring_bases[2] + i])
    for i in range(18): E.append([ring_bases[2] + (i * 12 // 18), ring_bases[3] + i])

    for _ in range(35):
        ang = random.random() * math.pi * 2
        r = random.random() * 0.8
        P.append([math.cos(ang) * r, math.sin(ang) * r, (1.0 - r) * 0.12, 2.0, "#00ffcc"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "ESCUDO DE DEFLEXÃO HOLOGRÁFICO", "categoria": "DEFESA"}


def _gerar_planeta():
    V = []; E = []; P = []
    rings = 8; segs = 16; r_core = 0.50
    for i in range(1, rings):
        th = i / float(rings) * math.pi
        y = math.cos(th) * r_core
        r_ring = math.sin(th) * r_core
        b = len(V)
        for j in range(segs):
            ph = j / float(segs) * math.pi * 2
            V.append([round(r_ring * math.cos(ph), 4), round(y, 4), round(r_ring * math.sin(ph), 4)])
            E.append([b + j, b + (j + 1) % segs])
            if i > 1:
                E.append([b + j, b - segs + j])

    tilt = 0.38
    c_tilt, s_tilt = math.cos(tilt), math.sin(tilt)
    for r_ring in (0.72, 0.88, 1.02):
        b = len(V); r_segs = 28
        for i in range(r_segs):
            ang = i / float(r_segs) * math.pi * 2
            x = math.cos(ang) * r_ring; z = math.sin(ang) * r_ring
            y1 = -z * s_tilt; z1 = z * c_tilt
            V.append([round(x, 4), round(y1, 4), round(z1, 4)])
            E.append([b + i, b + (i + 1) % r_segs])

    for dist, ang_l, y_l, cor_l in ((0.85, 0.4, 0.25, "#ffffff"), (1.12, 3.2, -0.20, "#ffaa00")):
        lx = math.cos(ang_l) * dist; lz = math.sin(ang_l) * dist
        P.append([lx, y_l, lz, 4.0, cor_l])

    for _ in range(40):
        ang = random.random() * math.pi * 2
        r = 0.70 + random.random() * 0.35
        x = math.cos(ang) * r; z = math.sin(ang) * r
        P.append([x, -z * s_tilt, z * c_tilt, 1.6, "#7fe6ff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "GIGANTE GASOSO C/ ANÉIS", "categoria": "ASTRONOMIA"}


def _gerar_piramide():
    V = []; E = []; P = []
    apex = len(V); V.append([0.0, 0.78, 0.0])
    levels = [(0.60, 0.15), (0.42, 0.35), (0.24, 0.58), (-0.70, 0.85)]
    prev_corners = None
    for y, w in levels:
        b = len(V)
        V.extend([[-w, y, -w], [w, y, -w], [w, y, w], [-w, y, w]])
        E.extend([[b, b+1], [b+1, b+2], [b+2, b+3], [b+3, b]])
        if prev_corners:
            for k in range(4): E.append([prev_corners + k, b + k])
        else:
            for k in range(4): E.append([apex, b + k])
        prev_corners = b

    P.append([0.0, 0.78, 0.0, 5.0, "#ffaa00"])
    for _ in range(25):
        py = -0.7 + random.random() * 1.5
        w_at_y = 0.85 * (1.0 - (py + 0.7) / 1.5)
        P.append([(random.random() - 0.5) * w_at_y * 1.8, py, (random.random() - 0.5) * w_at_y * 1.8, 1.8, "#00ffcc"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "PIRÂMIDE QUÂNTICA GIZA", "categoria": "ARQUITETURA"}


def _gerar_castelo():
    V = []; E = []; P = []
    def add_p(x, y, z):
        idx = len(V); V.append([round(x, 4), round(y, 4), round(z, 4)]); return idx
    towers = [(-0.55, -0.55), (0.55, -0.55), (0.55, 0.55), (-0.55, 0.55)]
    tower_top_centers = []
    for tx, tz in towers:
        w = 0.14; b = len(V)
        for y in (-0.75, 0.35):
            V.extend([[tx - w, y, tz - w], [tx + w, y, tz - w], [tx + w, y, tz + w], [tx - w, y, tz + w]])
        E.extend([[b, b+1], [b+1, b+2], [b+2, b+3], [b+3, b]])
        E.extend([[b+4, b+5], [b+5, b+6], [b+6, b+7], [b+7, b+4]])
        for k in range(4): E.append([b + k, b + 4 + k])
        c_apex = add_p(tx, 0.65, tz)
        tower_top_centers.append(c_apex)
        for k in range(4): E.append([c_apex, b + 4 + k])

    b_c = len(V); w_c = 0.22
    for y in (-0.75, 0.55):
        V.extend([[-w_c, y, -w_c], [w_c, y, -w_c], [w_c, y, w_c], [-w_c, y, w_c]])
    E.extend([[b_c, b_c+1], [b_c+1, b_c+2], [b_c+2, b_c+3], [b_c+3, b_c]])
    E.extend([[b_c+4, b_c+5], [b_c+5, b_c+6], [b_c+6, b_c+7], [b_c+7, b_c+4]])
    for k in range(4): E.append([b_c + k, b_c + 4 + k])
    c_apex_big = add_p(0.0, 0.95, 0.0)
    for k in range(4): E.append([c_apex_big, b_c + 4 + k])

    walls = [(0, 1), (1, 2), (2, 3), (3, 0)]
    for t1, t2 in walls:
        p1x, p1z = towers[t1]; p2x, p2z = towers[t2]
        add_p(p1x, 0.10, p1z); b_w = len(V) - 1; b_w2 = add_p(p2x, 0.10, p2z)
        E.append([b_w, b_w2])

    for tt in tower_top_centers: P.append([V[tt][0], V[tt][1], V[tt][2], 3.0, "#ffaa00"])
    P.append([0.0, 0.95, 0.0, 4.0, "#00d2ff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "FORTALEZA MEDIEVAL HOLOGRÁFICA", "categoria": "ARQUITETURA"}


def _gerar_coracao():
    V = []; E = []; P = []
    steps = 22; layers = 9
    for l in range(layers):
        v = (l / float(layers - 1) - 0.5) * 1.5
        scale = math.sqrt(max(0.01, 1.0 - (v / 0.85) ** 2))
        b = len(V)
        for i in range(steps):
            t = i / float(steps) * math.pi * 2
            x = 0.045 * (16 * math.sin(t) ** 3) * scale
            y = 0.045 * (13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)) * scale + 0.1
            z = v * 0.45
            V.append([round(x, 4), round(y, 4), round(z, 4)])
            E.append([b + i, b + (i + 1) % steps])
            if l > 0:
                E.append([b + i, b - steps + i])

    aorta = len(V)
    for dz in (-0.08, 0.08):
        V.append([-0.12, 0.65, dz]); V.append([-0.05, 0.78, dz]); V.append([0.08, 0.74, dz])
    E.extend([[aorta, aorta+1], [aorta+1, aorta+2], [aorta+3, aorta+4], [aorta+4, aorta+5]])
    E.extend([[aorta, aorta+3], [aorta+1, aorta+4], [aorta+2, aorta+5]])

    for _ in range(40):
        t = random.random() * math.pi * 2; r = random.random() * 0.4
        x = 0.045 * (16 * math.sin(t) ** 3) * r
        y = 0.045 * (13 * math.cos(t) - 5 * math.cos(2*t)) * r + 0.1
        P.append([x, y, (random.random() - 0.5) * 0.3, 2.2, "#ff2244"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "CORAÇÃO CARDÍACO HOLOGRÁFICO", "categoria": "BIOMEDICINA"}


def _gerar_estrela():
    V = []; E = []; P = []
    center = len(V); V.append([0.0, 0.0, 0.0])
    tips = [[0.0, 0.95, 0.0], [0.0, -0.95, 0.0], [0.95, 0.0, 0.0], [-0.95, 0.0, 0.0], [0.0, 0.0, 0.95], [0.0, 0.0, -0.95]]
    tip_idxs = []
    for tp in tips:
        idx = len(V); V.append(tp); tip_idxs.append(idx); E.append([center, idx])

    d = 0.52
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                idx = len(V); V.append([sx * d, sy * d, sz * d]); E.append([center, idx])
                ax = 2 if sx > 0 else 3; ay = 0 if sy > 0 else 1; az = 4 if sz > 0 else 5
                E.extend([[idx, tip_idxs[ax]], [idx, tip_idxs[ay]], [idx, tip_idxs[az]]])

    for _ in range(45):
        ang1 = random.random() * math.pi * 2; ang2 = (random.random() - 0.5) * math.pi
        r = 0.3 + random.random() * 0.7
        P.append([
            math.cos(ang1) * math.cos(ang2) * r,
            math.sin(ang2) * r,
            math.sin(ang1) * math.cos(ang2) * r,
            2.0,
            random.choice(["#ffdd00", "#ff6600", "#ffffff", "#00ffff"])
        ])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "ESTRELA SUPERNOVA 3D", "categoria": "ASTRONOMIA"}


def _gerar_foguete():
    V = []; E = []; P = []
    apex = len(V); V.append([0.0, 0.95, 0.0])
    levels = [(0.72, 0.12, 10), (0.35, 0.20, 12), (-0.10, 0.20, 12), (-0.55, 0.20, 12), (-0.75, 0.14, 10)]
    prev_base = None; prev_cnt = 0
    for y, r, cnt in levels:
        b = len(V)
        for i in range(cnt):
            a = i / float(cnt) * math.pi * 2
            V.append([round(math.cos(a) * r, 4), round(y, 4), round(math.sin(a) * r, 4)])
            E.append([b + i, b + (i + 1) % cnt])
        if prev_base is None:
            for i in range(cnt): E.append([apex, b + i])
        else:
            for i in range(cnt): E.append([b + i, prev_base + (i * prev_cnt // cnt)])
        prev_base = b; prev_cnt = cnt

    for ang in (0.0, math.pi/2, math.pi, math.pi * 1.5):
        c, s = math.cos(ang), math.sin(ang)
        p1 = len(V); V.append([c * 0.20, -0.40, s * 0.20])
        p2 = len(V); V.append([c * 0.52, -0.75, s * 0.52])
        p3 = len(V); V.append([c * 0.20, -0.75, s * 0.20])
        E.extend([[p1, p2], [p2, p3], [p3, p1]])

    for _ in range(35):
        P.append([
            (random.random() - 0.5) * 0.16,
            -0.78 - random.random() * 0.45,
            (random.random() - 0.5) * 0.16,
            2.5,
            random.choice(["#ff3300", "#ffaa00", "#ffffff"])
        ])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": "FOGUETE ESPACIAL SATURNO V", "categoria": "AEROESPACIAL"}


def _gerar_quadrupede(nome):
    V = []; E = []; P = []
    b = len(V)
    V.extend([
        [-0.15, 0.15, -0.45], [0.15, 0.15, -0.45],
        [0.15, -0.15, -0.45], [-0.15, -0.15, -0.45],
        [-0.14, 0.14, 0.40], [0.14, 0.14, 0.40],
        [0.14, -0.14, 0.40], [-0.14, -0.14, 0.40]
    ])
    E.extend([[b, b+1], [b+1, b+2], [b+2, b+3], [b+3, b]])
    E.extend([[b+4, b+5], [b+5, b+6], [b+6, b+7], [b+7, b+4]])
    for k in range(4): E.append([b+k, b+4+k])

    h = len(V)
    V.extend([
        [-0.12, 0.35, -0.65], [0.12, 0.35, -0.65],
        [0.0, 0.18, -0.80],
        [-0.14, 0.50, -0.60], [0.14, 0.50, -0.60]
    ])
    E.extend([[b, h], [b+1, h+1], [h, h+1], [h, h+2], [h+1, h+2]])
    E.extend([[h, h+3], [h+1, h+4]])

    legs = [(-0.14, -0.42), (0.14, -0.42), (-0.14, 0.38), (0.14, 0.38)]
    for lx, lz in legs:
        p_top = len(V); V.append([lx, -0.15, lz])
        p_mid = len(V); V.append([lx * 1.1, -0.45, lz])
        p_foot = len(V); V.append([lx, -0.75, lz - 0.05])
        E.extend([[p_top, p_mid], [p_mid, p_foot]])

    t0 = len(V); V.append([0.0, 0.12, 0.40]); t1 = len(V); V.append([0.0, 0.25, 0.70])
    E.append([t0, t1])
    P.append([-0.08, 0.32, -0.66, 2.5, "#ffaa00"]); P.append([0.08, 0.32, -0.66, 2.5, "#ffaa00"])
    for _ in range(20):
        P.append([(random.random() - 0.5) * 0.4, (random.random() - 0.5) * 0.4, (random.random() - 0.5) * 0.8, 1.5, "#00ffcc"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": nome.upper(), "categoria": "FAUNA HOLOGRÁFICA"}


def _gerar_recipiente_ou_frasco(nome):
    V = []; E = []; P = []
    levels = [
        (-0.75, 0.35, 12), (-0.35, 0.38, 12), (0.20, 0.34, 12),
        (0.45, 0.18, 10), (0.70, 0.14, 8), (0.82, 0.18, 8)
    ]
    prev_b = None; prev_cnt = 0
    for y, r, cnt in levels:
        b = len(V)
        for i in range(cnt):
            a = i / float(cnt) * math.pi * 2
            V.append([round(math.cos(a) * r, 4), round(y, 4), round(math.sin(a) * r, 4)])
            E.append([b + i, b + (i + 1) % cnt])
        if prev_b is not None:
            for i in range(cnt): E.append([b + i, prev_b + (i * prev_cnt // cnt)])
        prev_b = b; prev_cnt = cnt

    for _ in range(30):
        a = random.random() * math.pi * 2; r = random.random() * 0.28
        y = -0.70 + random.random() * 1.2
        P.append([math.cos(a) * r, y, math.sin(a) * r, 2.0, "#ff007f"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": nome.upper(), "categoria": "OBJETO 3D"}


def _gerar_eletronico(nome):
    V = []; E = []; P = []
    b_t = len(V)
    V.extend([
        [-0.65, -0.10, 0.0], [0.65, -0.10, 0.0], [0.65, 0.65, 0.0], [-0.65, 0.65, 0.0],
        [-0.60, -0.05, 0.0], [0.60, -0.05, 0.0], [0.60, 0.60, 0.0], [-0.60, 0.60, 0.0]
    ])
    E.extend([[b_t, b_t+1], [b_t+1, b_t+2], [b_t+2, b_t+3], [b_t+3, b_t]])
    E.extend([[b_t+4, b_t+5], [b_t+5, b_t+6], [b_t+6, b_t+7], [b_t+7, b_t+4]])
    b_k = len(V)
    V.extend([[-0.65, -0.45, 0.50], [0.65, -0.45, 0.50], [0.65, -0.10, 0.0], [-0.65, -0.10, 0.0]])
    E.extend([[b_k, b_k+1], [b_k+1, b_k+2], [b_k+2, b_k+3], [b_k+3, b_k]])
    for row in range(3):
        y_r = -0.18 - row * 0.09; z_r = 0.12 + row * 0.12
        p1 = len(V); V.append([-0.55, y_r, z_r]); p2 = len(V); V.append([0.55, y_r, z_r])
        E.append([p1, p2])

    for _ in range(30):
        P.append([(random.random() - 0.5) * 1.1, (random.random() - 0.5) * 0.6 + 0.25, (random.random() - 0.5) * 0.1, 2.0, "#00d2ff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": nome.upper(), "categoria": "TECNOLOGIA"}


def _gerar_stark_core_universal(nome):
    V = []; E = []; P = []
    phi = (1.0 + math.sqrt(5.0)) / 2.0; s = 0.40
    raw_v = [
        [-1,  phi, 0], [ 1,  phi, 0], [-1, -phi, 0], [ 1, -phi, 0],
        [0, -1,  phi], [0,  1,  phi], [0, -1, -phi], [0,  1, -phi],
        [ phi, 0, -1], [ phi, 0,  1], [-phi, 0, -1], [-phi, 0,  1]
    ]
    b_core = len(V)
    for px, py, pz in raw_v:
        d = math.sqrt(px*px + py*py + pz*pz)
        V.append([round(px/d * s, 4), round(py/d * s, 4), round(pz/d * s, 4)])

    for i in range(12):
        for j in range(i + 1, 12):
            dx = V[b_core+i][0] - V[b_core+j][0]
            dy = V[b_core+i][1] - V[b_core+j][1]
            dz = V[b_core+i][2] - V[b_core+j][2]
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if abs(dist - 0.42) < 0.05:
                E.append([b_core + i, b_core + j])

    b_g1 = len(V); cnt_g = 20; r_g = 0.75
    for i in range(cnt_g):
        a = i / float(cnt_g) * math.pi * 2
        V.append([round(math.cos(a) * r_g, 4), round(math.sin(a) * r_g, 4), 0.0])
        E.append([b_g1 + i, b_g1 + (i + 1) % cnt_g])

    b_g2 = len(V)
    for i in range(cnt_g):
        a = i / float(cnt_g) * math.pi * 2
        V.append([round(math.cos(a) * (r_g + 0.12), 4), 0.0, round(math.sin(a) * (r_g + 0.12), 4)])
        E.append([b_g2 + i, b_g2 + (i + 1) % cnt_g])

    for _ in range(35):
        a = random.random() * math.pi * 2; r = 0.35 + random.random() * 0.55
        P.append([math.cos(a) * r, (random.random() - 0.5) * 0.3, math.sin(a) * r, 2.2, "#00d2ff"])

    return {"vertices": V, "arestas": E, "particulas": P, "nome": nome.upper(), "categoria": "MATRIZ HOLOGRÁFICA"}


def _gerar_generico_adaptativo(termo):
    t = (termo or "").strip().lower()
    if any(w in t for w in ("cachorro", "cao", "cão", "gato", "leao", "leão", "tigre", "lobo", "urso", "cavalo", "elefante", "bicho", "animal", "monstro")):
        return _gerar_quadrupede(termo)
    if any(w in t for w in ("perfume", "frasco", "copo", "xicara", "xícara", "caneca", "garrafa", "vaso", "pocao", "poção", "liquido", "remedio")):
        return _gerar_recipiente_ou_frasco(termo)
    if any(w in t for w in ("computador", "laptop", "notebook", "pc", "monitor", "tela", "celular", "smartphone", "tablet", "teclado")):
        return _gerar_eletronico(termo)
    return _gerar_stark_core_universal(termo)


def _gerar_smartphone():
    V = []; E = []; P = []
    w, h, d = 0.38, 0.76, 0.035
    for z in (-d, d):
        cr = 0.06
        pts = [
            [-w+cr, -h, z], [w-cr, -h, z],
            [w, -h+cr, z], [w, h-cr, z],
            [w-cr, h, z], [-w+cr, h, z],
            [-w, h-cr, z], [-w, -h+cr, z]
        ]
        base = len(V)
        V.extend(pts)
        for i in range(8):
            E.append([base + i, base + (i + 1) % 8])
    for i in range(8):
        E.append([i, i + 8])
    sw, sh, sz = 0.33, 0.68, d + 0.002
    sbase = len(V)
    spts = [[-sw, -sh, sz], [sw, -sh, sz], [sw, sh, sz], [-sw, sh, sz]]
    V.extend(spts)
    for i in range(4):
        E.append([sbase + i, sbase + (i + 1) % 4])
    for i in range(1, 4):
        y = -sh + i * (2 * sh / 4)
        v1 = len(V); V.append([-sw, y, sz])
        v2 = len(V); V.append([sw, y, sz])
        E.append([v1, v2])
    di_base = len(V)
    V.extend([[-0.08, sh - 0.04, sz], [0.08, sh - 0.04, sz]])
    E.append([di_base, di_base + 1])
    cb_base = len(V)
    cw, ch, cz = 0.14, 0.22, -d - 0.015
    V.extend([[-w+0.04, h-0.04, cz], [-w+0.04+cw, h-0.04, cz], [-w+0.04+cw, h-0.04-ch, cz], [-w+0.04, h-0.04-ch, cz]])
    for i in range(4):
        E.append([cb_base + i, cb_base + (i + 1) % 4])
        E.append([cb_base + i, 5 if i in (0, 3) else 4])
    for li, ly in enumerate([h-0.09, h-0.15, h-0.21]):
        lx = -w + 0.11
        lbase = len(V)
        for a_idx in range(6):
            ang = a_idx / 6.0 * math.pi * 2
            V.append([lx + math.cos(ang) * 0.03, ly + math.sin(ang) * 0.03, cz])
            E.append([lbase + a_idx, lbase + (a_idx + 1) % 6])
    for i in range(25):
        px = (i % 5 - 2) * 0.06
        py = (i // 5 - 2) * 0.12
        pz = sz + 0.03 + (i % 3) * 0.04
        P.append([px, py, pz, 1.8, "#00d2ff" if i % 2 == 0 else "#a6dcff"])
    return {"nome": "SMARTPHONE HOLOGRÁFICO", "categoria": "DISPOSITIVO MÓVEL", "vertices": V, "arestas": E, "particulas": P}


def _gerar_relogio():
    V = []; E = []; P = []
    N = 16; R = 0.36; d = 0.07
    for z in (-d, d):
        base = len(V)
        for i in range(N):
            a = i / N * math.pi * 2
            V.append([math.cos(a) * R, math.sin(a) * R, z])
            E.append([base + i, base + (i + 1) % N])
    for i in range(N):
        E.append([i, i + N])
    bbase = len(V)
    for i in range(12):
        a = i / 12.0 * math.pi * 2
        V.append([math.cos(a) * (R * 0.82), math.sin(a) * (R * 0.82), d + 0.005])
        V.append([math.cos(a) * (R * 0.94), math.sin(a) * (R * 0.94), d + 0.005])
        E.append([bbase + i * 2, bbase + i * 2 + 1])
    c_idx = len(V)
    V.append([0.0, 0.0, d + 0.01])
    ha = math.pi * 0.25
    h_idx = len(V); V.append([math.cos(ha) * 0.20, math.sin(ha) * 0.20, d + 0.01])
    E.append([c_idx, h_idx])
    ma = math.pi * 0.70
    m_idx = len(V); V.append([math.cos(ma) * 0.28, math.sin(ma) * 0.28, d + 0.01])
    E.append([c_idx, m_idx])
    sa = -math.pi * 0.40
    s_idx = len(V); V.append([math.cos(sa) * 0.32, math.sin(sa) * 0.32, d + 0.015])
    E.append([c_idx, s_idx])
    cr_base = len(V)
    V.extend([[R, -0.04, 0], [R + 0.08, -0.04, 0], [R + 0.08, 0.04, 0], [R, 0.04, 0]])
    for i in range(4):
        E.append([cr_base + i, cr_base + (i + 1) % 4])
    sw = 0.22
    for sdir in (1, -1):
        for seg in range(1, 4):
            sy = sdir * (R + seg * 0.15)
            s_b = len(V)
            V.extend([[-sw, sy, 0], [sw, sy, 0]])
            E.append([s_b, s_b + 1])
            if seg > 1:
                E.append([s_b, s_b - 2]); E.append([s_b + 1, s_b - 1])
    for i in range(24):
        a = i / 24.0 * math.pi * 2
        r = R * 1.18 + 0.02 * math.sin(i * 3)
        P.append([math.cos(a) * r, math.sin(a) * r, d + 0.02, 1.6, "#00ffcc" if i % 4 == 0 else "#00d2ff"])
    return {"nome": "CHRONOMETER STARK", "categoria": "HOROLOGIA DE PRECISÃO", "vertices": V, "arestas": E, "particulas": P}


def _gerar_perfume():
    V = []; E = []; P = []
    w, h_bot, d = 0.32, 0.45, 0.32
    y_bot = -0.55
    y_top = y_bot + h_bot
    for y in (y_bot, y_top):
        base = len(V)
        V.extend([[-w, y, -d], [w, y, -d], [w, y, d], [-w, y, d]])
        for i in range(4):
            E.append([base + i, base + (i + 1) % 4])
    for i in range(4):
        E.append([i, i + 4])
    lw, lh, ld = w * 0.82, h_bot * 0.75, d * 0.82
    ly_top = y_bot + lh
    for y in (y_bot + 0.03, ly_top):
        base = len(V)
        V.extend([[-lw, y, -ld], [lw, y, -ld], [lw, y, ld], [-lw, y, ld]])
        for i in range(4):
            E.append([base + i, base + (i + 1) % 4])
    for i in range(4):
        E.append([8 + i, 8 + i + 4])
    ny_start = y_top + 0.08
    nr = 0.10
    nbase = len(V)
    for i in range(8):
        a = i / 8.0 * math.pi * 2
        V.append([math.cos(a) * nr, ny_start, math.sin(a) * nr])
        E.append([nbase + i, nbase + (i + 1) % 8])
    for i, vi in enumerate([4, 5, 6, 7]):
        E.append([vi, nbase + i * 2])
    ny_end = ny_start + 0.16
    pbase = len(V)
    for i in range(8):
        a = i / 8.0 * math.pi * 2
        V.append([math.cos(a) * nr, ny_end, math.sin(a) * nr])
        E.append([pbase + i, pbase + (i + 1) % 8])
        E.append([nbase + i, pbase + i])
    cw, cd = 0.22, 0.22
    cy_start = ny_end
    cy_end = cy_start + 0.28
    for y in (cy_start, cy_end):
        base = len(V)
        V.extend([[-cw, y, -cd], [cw, y, -cd], [cw, y, cd], [-cw, y, cd]])
        for i in range(4):
            E.append([base + i, base + (i + 1) % 4])
    for i in range(4):
        E.append([pbase + 8 + i, pbase + 8 + i + 4])
    for i in range(35):
        t = i / 35.0
        dist = 0.12 + t * 0.55
        spread = t * 0.25
        px = dist
        py = ny_end - 0.02 + (i % 5 - 2) * spread * 0.4
        pz = (i % 7 - 3) * spread * 0.5
        P.append([px, py, pz, 1.6 + t * 1.2, "#ff2244" if i % 2 == 0 else "#ff5577"])
    return {"nome": "FRASCO DE PERFUME RED RUBY", "categoria": "DESIGN & LUXO", "vertices": V, "arestas": E, "particulas": P}


# Mapeamento de termos para geradores paramétricos
GERADORES = {
    # Dispositivos e Tecnologia Pessoal
    "celular": _gerar_smartphone,
    "smartphone": _gerar_smartphone,
    "telefone": _gerar_smartphone,
    "iphone": _gerar_smartphone,
    "android": _gerar_smartphone,
    "relogio": _gerar_relogio,
    "relógio": _gerar_relogio,
    "smartwatch": _gerar_relogio,
    "watch": _gerar_relogio,
    # Objetos Pessoais & Luxo
    "perfume": _gerar_perfume,
    "frasco": _gerar_perfume,
    # Dinossauros e Criaturas
    "tiranossauro": _gerar_tiranossauro,
    "trex": _gerar_tiranossauro,
    "t-rex": _gerar_tiranossauro,
    "dinossauro": _gerar_tiranossauro,
    "dragao": _gerar_tiranossauro,
    "dragão": _gerar_tiranossauro,
    "reptil": _gerar_tiranossauro,
    # Armamento e Defesa
    "espada": _gerar_espada,
    "sabre": _gerar_espada,
    "katana": _gerar_espada,
    "laser": _gerar_espada,
    "escudo": _gerar_escudo,
    "shield": _gerar_escudo,
    # Veículos e Aeroespacial
    "carro": _gerar_carro,
    "veiculo": _gerar_carro,
    "veículo": _gerar_carro,
    "automovel": _gerar_carro,
    "drone": _gerar_drone,
    "quadricoptero": _gerar_drone,
    "quadricóptero": _gerar_drone,
    "nave": _gerar_nave,
    "aviao": _gerar_nave,
    "avião": _gerar_nave,
    "caca": _gerar_nave,
    "caça": _gerar_nave,
    "jet": _gerar_nave,
    "foguete": _gerar_foguete,
    "missil": _gerar_foguete,
    "satelite": _gerar_satelite,
    "satélite": _gerar_satelite,
    "telescopio": _gerar_satelite,
    "telescópio": _gerar_satelite,
    # Arquitetura e Monumentos
    "castelo": _gerar_castelo,
    "fortaleza": _gerar_castelo,
    "torre": _gerar_castelo,
    "piramide": _gerar_piramide,
    "pirâmide": _gerar_piramide,
    # Biologia e Medicina
    "dna": _gerar_dna,
    "genoma": _gerar_dna,
    "molecula": _gerar_dna,
    "molécula": _gerar_dna,
    "coracao": _gerar_coracao,
    "coração": _gerar_coracao,
    # Robótica
    "robo": _gerar_robo,
    "robô": _gerar_robo,
    "armadura": _gerar_robo,
    "ironman": _gerar_robo,
    "homem de ferro": _gerar_robo,
    # Astronomia e Energia
    "reator": _gerar_reator_arc,
    "arc": _gerar_reator_arc,
    "esfera": _gerar_esfera_tecnologica,
    "globo": _gerar_esfera_tecnologica,
    "tesseract": _gerar_esfera_tecnologica,
    "planeta": _gerar_planeta,
    "saturno": _gerar_planeta,
    "jupiter": _gerar_planeta,
    "júpiter": _gerar_planeta,
    "estrela": _gerar_estrela,
    "supernova": _gerar_estrela,
    "sol": _gerar_estrela
}


def _gerar_via_ia(termo):
    """Gera um modelo 3D wireframe holográfico com fallback adaptativo instantâneo Stark (< 2ms)."""
    import urllib.request
    api_key = os.environ.get("OPENAI_API_KEY")
    t_clean = (termo or "").strip()
    if api_key and api_key.startswith("sk-"):
        prompt = f"""Gere um modelo 3D holográfico em wireframe minimalista para o objeto: '{t_clean}'.
Retorne APENAS um JSON válido no formato:
{{
  "nome": "{t_clean.upper()}",
  "categoria": "MODELO HOLOGRÁFICO",
  "vertices": [[x,y,z], ...],  // 30 a 70 vértices flutuantes entre -1.0 e 1.0
  "arestas": [[i,j], ...],     // conexões estruturais entre os índices dos vértices
  "particulas": [[x,y,z,raio,cor], ...] // 20 partículas decorativas orbitais, cor em hex como '#00d2ff'
}}"""
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps({
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.4
                }).encode(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode())
                content = data["choices"][0]["message"]["content"]
                mod = json.loads(content)
                if "vertices" in mod and "arestas" in mod:
                    mod.setdefault("particulas", [])
                    mod.setdefault("nome", t_clean.upper())
                    mod.setdefault("categoria", "STARK CLOUD CAD")
                    return mod
        except Exception as e:
            print("projecao cloud AI erro:", e, flush=True)

    # Fallback inteligente e instantâneo
    return _gerar_generico_adaptativo(t_clean)


# =============================================================================
# GERAÇÃO VIA IA EM NUVEM E DISPATCH
# =============================================================================

def criar_objeto_3d(termo, modificacao=None):
    """Cria ou modifica um objeto 3D holográfico a partir de comando de voz."""
    t_clean = (termo or "").lower().strip()

    # 1. Busca na biblioteca procedural ultra-rápida Stark (< 10ms)
    gerador = None
    for k, fn in GERADORES.items():
        if k in t_clean:
            gerador = fn
            break

    if gerador is not None:
        modelo = gerador()
    else:
        # 2. Se não estiver no catálogo pré-programado, invoca a IA em nuvem
        modelo = _gerar_via_ia(termo)

    # 3. Aplica modificações e modelagem requisitadas por voz
    if modificacao:
        mod_clean = modificacao.lower()
        # Modo estrutural
        if any(w in mod_clean for w in ("explod", "desmont", "visão explodida", "separar")):
            _estado_projecao["modo"] = "explodido"
            _estado_projecao["explodir"] = 0.6
        elif any(w in mod_clean for w in ("montar", "juntar", "recompor", "wireframe", "normal")):
            _estado_projecao["modo"] = "wireframe"
            _estado_projecao["explodir"] = 0.0
        elif any(w in mod_clean for w in ("raio-x", "raio x", "transparente", "interno")):
            _estado_projecao["modo"] = "raio_x"
        elif any(w in mod_clean for w in ("particula", "partícula", "pontos", "nano")):
            _estado_projecao["modo"] = "particulas"

        # Velocidade de rotação
        if any(w in mod_clean for w in ("rapido", "rápido", "gire mais", "aceler")):
            _estado_projecao["rot_speed"] = 1.8
        elif any(w in mod_clean for w in ("devagar", "lento", "desaceler")):
            _estado_projecao["rot_speed"] = 0.35
        elif any(w in mod_clean for w in ("parar", "estatico", "estático", "trave")):
            _estado_projecao["rot_speed"] = 0.0

        # Cor holográfica
        if any(w in mod_clean for w in ("dourad", "ouro", "amarelo")):
            _estado_projecao["cor"] = "#ffaa00"
        elif any(w in mod_clean for w in ("azul", "ciano", "stark")):
            _estado_projecao["cor"] = "#00d2ff"
        elif any(w in mod_clean for w in ("verde", "esmeralda")):
            _estado_projecao["cor"] = "#00ff88"
        elif any(w in mod_clean for w in ("vermelh", "alerta")):
            _estado_projecao["cor"] = "#ff3344"
        elif any(w in mod_clean for w in ("roxo", "violeta")):
            _estado_projecao["cor"] = "#bd00ff"
        elif any(w in mod_clean for w in ("branco", "prata")):
            _estado_projecao["cor"] = "#ffffff"

    _estado_projecao["ativo"] = True
    _estado_projecao["objeto_atual"] = modelo
    _estado_projecao["nome"] = modelo["nome"]

    # Constrói o spec para o HoloStage.qml
    spec = {
        "kind": "projecao_3d",
        "titulo": modelo["nome"],
        "sub": f"PROJEÇÃO HOLOGRÁFICA · {modelo['categoria']}",
        "vertices": modelo["vertices"],
        "arestas": modelo["arestas"],
        "particulas": modelo["particulas"],
        "rot_speed": _estado_projecao["rot_speed"],
        "cor": _estado_projecao["cor"],
        "modo": _estado_projecao["modo"],
        "explodir": _estado_projecao["explodir"],
        "telemetria": [
            {"label": "VÉRTICES", "valor": str(len(modelo["vertices"]))},
            {"label": "ARESTAS", "valor": str(len(modelo["arestas"]))},
            {"label": "NANOPARTÍCULAS", "valor": str(len(modelo["particulas"]))},
            {"label": "FPS MATRIZ", "valor": "60.0"}
        ]
    }
    return spec


def fechar_projecao():
    """Encerra o modo projeção."""
    _estado_projecao["ativo"] = False
    _estado_projecao["objeto_atual"] = None
    return None
