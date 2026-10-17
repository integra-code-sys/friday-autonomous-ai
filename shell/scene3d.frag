#version 440
// Passo 1 (robô HUMANOID articulado): ray marching em volumes de distância assados do modelo.
// Saída: R=sombra, G=material/4 (1=olhos/LED), B=profundidade, A=cobertura
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float aspect;
    float mouth;
    float smile;
    float browL;
    float browR;
    float blink;
    float cheek;
    float lookX;
    float lookY;
    float brist;
    float yaw;
    float pitch;
    float roll;
    float lipW;
    float armLs;   // braço esquerdo: elevação à frente
    float armLa;   // abdução (para fora)
    float armLe;   // flexão do cotovelo
    float armRs;
    float armRa;
    float armRe;
    float lean;    // tronco inclina à frente
    float sway;    // tronco inclina de lado
    float twist;   // tronco gira
    float armLr;   // rotação axial do braço (úmero)
    float armRr;
    float shrugL;  // elevação do ombro
    float shrugR;
    vec4 lFc;      // mão E: curvatura indicador, médio, anelar, mindinho (0..1)
    vec4 lSp;      // mão E: abertura lateral de cada dedo (rad, + = para fora)
    vec4 lWr;      // mão E: punho flexão, desvio, rotação (pronação) e curvatura do polegar
    vec4 rFc;
    vec4 rSp;
    vec4 rWr;
    float pxs;     // tamanho do pixel em unidades do modelo (anti-aliasing de borda)
};
layout(binding = 1) uniform sampler2D tHead;
layout(binding = 2) uniform sampler2D tNeck;
layout(binding = 3) uniform sampler2D tBust;
layout(binding = 4) uniform sampler2D tWeave;
layout(binding = 5) uniform sampler2D tPlates;
layout(binding = 6) uniform sampler2D tArmLu;
layout(binding = 7) uniform sampler2D tHand;   // folha única das peças da mão (direita; a esquerda é espelhada)
layout(binding = 8) uniform sampler2D tArmRu;
layout(binding = 10) uniform sampler2D tEye;    // olho original do HUMANOID: globo | parte brilhante (íris)

const vec3 H_O = vec3(-0.93000, 14.48000, -0.62000);
const vec3 H_S = vec3(1.86000, 2.46000, 2.37000);
const vec3 H_D = vec3(196.00000, 259.00000, 250.00000);
const vec2 H_G = vec2(19.0, 14.0);
const vec2 H_A = vec2(3724.0, 3626.0);
const float H_DM = 0.22;
const vec3 N_O = vec3(-0.85000, 13.85000, -0.40000);
const vec3 N_S = vec3(1.70000, 1.60000, 1.45000);
const vec3 N_D = vec3(170.00000, 160.00000, 146.00000);
const vec2 N_G = vec2(12.0, 13.0);
const vec2 N_A = vec2(2040.0, 2080.0);
const float N_DM = 0.22;
const vec3 B_O = vec3(-2.85000, 9.40000, -1.05000);
const vec3 B_S = vec3(5.70000, 5.25000, 2.45000);
const vec3 B_D = vec3(317.00000, 292.00000, 137.00000);
const vec2 B_G = vec2(12.0, 12.0);
const vec2 B_A = vec2(3804.0, 3504.0);
const float B_DM = 0.45;
const vec3 LU_O = vec3(-4.05000, 11.00000, -0.75000);
const vec3 LU_S = vec3(3.00000, 2.95000, 1.70000);
const vec3 LU_D = vec3(215.00000, 211.00000, 122.00000);
const vec2 LU_G = vec2(11.0, 12.0);
const vec2 LU_A = vec2(2365.0, 2532.0);
const float LU_DM = 0.3;
const vec3 RU_O = vec3(1.05000, 11.00000, -0.75000);
const vec3 RU_S = vec3(3.00000, 2.95000, 1.70000);
const vec3 RU_D = vec3(215.00000, 211.00000, 122.00000);
const vec2 RU_G = vec2(11.0, 12.0);
const vec2 RU_A = vec2(2365.0, 2532.0);
const float RU_DM = 0.3;
const vec3 FA_O = vec3(2.99635, 9.89577, -0.17433);
const vec3 FA_S = vec3(2.25322, 2.06545, 2.67419);
const vec3 FA_D = vec3(126.00000, 115.00000, 149.00000);
const vec2 FA_G = vec2(12.0, 13.0);
const vec2 FA_TW = vec2(1512.0, 1495.0);
const vec2 FA_OFF = vec2(5184.0, 0.0);
const float FA_DM = 0.3;
const vec3 PA_O = vec3(4.32532, 9.31089, 1.72785);
const vec3 PA_S = vec3(1.18147, 1.28756, 1.40337);
const vec3 PA_D = vec3(85.00000, 92.00000, 101.00000);
const vec2 PA_G = vec2(11.0, 10.0);
const vec2 PA_TW = vec2(935.0, 920.0);
const vec2 PA_OFF = vec2(2660.0, 1944.0);
const float PA_DM = 0.2;
const vec3 F0_O = vec3(4.49806, 9.26975, 2.69795);
const vec3 F0_S = vec3(0.75982, 0.88518, 1.04963);
const vec3 F0_D = vec3(70.00000, 81.00000, 96.00000);
const vec2 F0_G = vec2(11.0, 9.0);
const vec2 F0_TW = vec2(770.0, 729.0);
const vec2 F0_OFF = vec2(0.0, 1944.0);
const float F0_DM = 0.12;
const vec3 F1_O = vec3(4.64362, 8.95011, 2.44192);
const vec3 F1_S = vec3(0.85764, 1.18098, 1.11482);
const vec3 F1_D = vec3(78.00000, 108.00000, 102.00000);
const vec2 F1_G = vec2(12.0, 9.0);
const vec2 F1_TW = vec2(936.0, 972.0);
const vec2 F1_OFF = vec2(0.0, 0.0);
const float F1_DM = 0.12;
const vec3 F2_O = vec3(4.89981, 8.86690, 2.23838);
const vec3 F2_S = vec3(0.74529, 1.08164, 0.99477);
const vec3 F2_D = vec3(68.00000, 99.00000, 91.00000);
const vec2 F2_G = vec2(12.0, 8.0);
const vec2 F2_TW = vec2(816.0, 792.0);
const vec2 F2_OFF = vec2(3552.0, 0.0);
const float F2_DM = 0.12;
const vec3 F3_O = vec3(4.96295, 8.94161, 2.08974);
const vec3 F3_S = vec3(0.60917, 0.79396, 0.73119);
const vec3 F3_D = vec3(56.00000, 73.00000, 67.00000);
const vec2 F3_G = vec2(10.0, 7.0);
const vec2 F3_TW = vec2(560.0, 511.0);
const vec2 F3_OFF = vec2(1540.0, 1944.0);
const float F3_DM = 0.12;
const vec3 TH_O = vec3(4.12431, 9.61648, 2.21931);
const vec3 TH_S = vec3(1.00312, 0.91701, 1.25057);
const vec3 TH_D = vec3(84.00000, 77.00000, 105.00000);
const vec2 TH_G = vec2(10.0, 11.0);
const vec2 TH_TW = vec2(840.0, 847.0);
const vec2 TH_OFF = vec2(1872.0, 0.0);
const float TH_DM = 0.14;
const vec3 HB_O = vec3(2.99635, 8.86690, -0.17433);
const vec3 HB_S = vec3(2.64874, 3.09432, 3.92191);
const vec2 HAND_SHEET = vec2(8192.0, 3402.0);
const vec3 HW = vec3(4.69210, 10.26679, 2.04850);
const vec3 HF = vec3(0.35161, -0.60001, 0.71858);
const vec3 HS = vec3(-0.73728, 0.29551, 0.60752);
const vec3 HN = vec3(-0.60764, -0.68310, -0.40515);
const vec3 MCP0 = vec3(4.97178, 9.97962, 3.10399);
const vec3 MCP1 = vec3(5.16789, 9.80738, 2.85086);
const vec3 MCP2 = vec3(5.30259, 9.62612, 2.61545);
const vec3 MCP3 = vec3(5.38557, 9.50345, 2.45969);
const vec3 EY_O = vec3(0.07051, 15.58901, 1.09986);
const vec3 EY_S = vec3(0.44434, 0.42943, 0.35943);
const vec3 EY_D = vec3(56.00000, 54.00000, 45.00000);
const vec2 EY_G = vec2(7.0, 7.0);
const vec2 EY_TW = vec2(392.0, 378.0);
const vec2 EY_SHEET = vec2(784.0, 378.0);
const float EY_DM = 0.1;

const vec3 PIVH = vec3(0.0, 14.80, 0.35);     // articulação cabeça-pescoço (atlas/occipital)
const vec3 PIVN = vec3(0.0, 13.55, 0.15);     // base do pescoço (C7/T1): o pescoço dobra daqui, a cabeça vai junto
const vec3 PIVT = vec3(0.0, 9.60, 0.15);      // quadril: pivô do tronco
const vec3 SHL = vec3(-1.91, 13.60, 0.05);    // ombros
const vec3 SHR = vec3( 1.91, 13.60, 0.05);
const vec3 ELL = vec3(-3.39, 11.49, -0.05);   // cotovelos
const vec3 ELR = vec3( 3.39, 11.49, -0.05);
const float VIEW_H = 6.4;                     // altura da tela em unidades do modelo
const float VIEW_CY = 14.2;                   // y do modelo no centro da tela
const vec3 EYE_C = vec3(0.30, 15.805, 1.30);
const vec3 EYE_C0 = vec3(0.3007, 15.7976, 1.3403);              // centro do globo ocular (original)

vec3 rX(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(p.x, c * p.y - s * p.z, s * p.y + c * p.z); }
vec3 rY(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z); }
vec3 rZ(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(c * p.x - s * p.y, s * p.x + c * p.y, p.z); }

vec3 rotAxis(vec3 v, vec3 a, float ang) { float c = cos(ang), s = sin(ang); return v * c + cross(a, v) * s + a * dot(a, v) * (1.0 - c); }

// pescoço: flexão/rotação/inclinação em torno da BASE (C7), em proporção ao movimento da cabeça
vec3 neckInv(vec3 w) { return rY(rX(rZ(w - PIVN, roll * 0.35), pitch * 0.18), -yaw * 0.28) + PIVN; }
vec3 neckFwdN(vec3 n) { return rZ(rX(rY(n, yaw * 0.28), -pitch * 0.18), -roll * 0.35); }

vec3 torsoInv(vec3 w) { return PIVT + rZ(rX(rY(w - PIVT, -twist), -lean), -sway); }
vec3 torsoFwdN(vec3 n) { return rY(rX(rZ(n, sway), lean), twist); }

vec4 fetchVol(sampler2D t, vec3 pl, vec3 o, vec3 sz, vec3 dims, vec2 grid, vec2 atlas) {
    vec3 g = (pl - o) / sz * dims;
    float z = clamp(g.z - 0.5, 0.0, dims.z - 1.0);
    float z0 = floor(z), f = z - z0, z1 = min(z0 + 1.0, dims.z - 1.0);
    vec2 xy = clamp(g.xy, vec2(0.5), dims.xy - 0.5);
    vec2 t0 = vec2(mod(z0, grid.x), floor(z0 / grid.x));
    vec2 t1 = vec2(mod(z1, grid.x), floor(z1 / grid.x));
    vec4 a = texture(t, (t0 * dims.xy + xy) / atlas);
    vec4 b = texture(t, (t1 * dims.xy + xy) / atlas);
    return mix(a, b, f);
}
vec4 fetchVar(sampler2D t, vec3 pl, vec3 o, vec3 sz, vec3 dims, vec2 grid, vec2 tile, vec2 sheet, float variant, vec2 base) {
    vec3 g = (pl - o) / sz * dims;
    float z = clamp(g.z - 0.5, 0.0, dims.z - 1.0);
    float z0 = floor(z), f = z - z0, z1 = min(z0 + 1.0, dims.z - 1.0);
    vec2 xy = clamp(g.xy, vec2(0.5), dims.xy - 0.5);
    vec2 t0 = vec2(mod(z0, grid.x), floor(z0 / grid.x));
    vec2 t1 = vec2(mod(z1, grid.x), floor(z1 / grid.x));
    vec2 off = base + vec2(mod(variant, 2.0), floor(variant / 2.0)) * tile;
    vec4 a = texture(t, (off + t0 * dims.xy + xy) / sheet);
    vec4 b = texture(t, (off + t1 * dims.xy + xy) / sheet);
    return mix(a, b, f);
}
vec3 decN(vec4 v) { vec2 xy = v.rg * 2.0 - 1.0; return vec3(xy, sqrt(max(0.0, 1.0 - dot(xy, xy)))); }
float boxDist(vec3 p, vec3 o, vec3 sz) {
    vec3 q = abs(p - (o + sz * 0.5)) - sz * 0.5;
    return length(max(q, 0.0));
}

// ---- peças (todas recebem o ponto já em coordenadas do tronco) ----
float dHead(vec3 w, out vec3 nl, out vec3 lp) {
    vec3 wn = neckInv(w);                                           // 1º o pescoço (base fixa), 2º a cabeça em torno do atlas
    vec3 l = rY(rX(rZ(wn - PIVH, roll * 0.75), pitch * 0.22), -yaw * 0.32) + PIVH;
    lp = l;
    float bd = boxDist(l, H_O, H_S);
    if (false) {                                          // (desligado: a cabeça original já tem os olhos esculpidos)
                                // abre a casca da cabeça onde ficam os olhos originais (só dentro da caixa)
        for (int sg = -1; sg <= 1; sg += 2) {
            vec2 e = (l.xy - vec2(float(sg) * EYE_C0.x, EYE_C0.y)) / vec2(0.132, 0.126);
            if (dot(e, e) < 1.0) { nl = vec3(0.0, 0.0, 1.0); return 0.04; }
        }
    }
    nl = vec3(0.0, 0.0, 1.0);
    if (bd > 0.0) return bd + 0.02;
    vec4 v = fetchVol(tHead, l, H_O, H_S, H_D, H_G, H_A);
    nl = decN(v);
    return v.b * H_DM - 0.0105;
}
// olhos originais (globo + íris): giram para onde o avatar olha, achatam ao piscar/sorrir
float eyePiece(vec3 p, float xo, out vec3 nl) {
    vec3 q = EYE_C0 + rX(rY(p - EYE_C0, -lookX * 0.38), lookY * 0.30);
    nl = vec3(0.0, 0.0, 1.0);
    float bd = boxDist(q, EY_O, EY_S);
    if (bd > 0.0) return bd + 0.015;
    vec4 v = fetchVar(tEye, q, EY_O, EY_S, EY_D, EY_G, EY_TW, EY_SHEET, 0.0, vec2(xo, 0.0));
    nl = decN(v);
    return v.b * EY_DM - 0.004;
}
float dEyes(vec3 l, out vec3 nl, out float iris) {
    float best = 1e3; iris = 0.0; nl = vec3(0.0, 0.0, 1.0);
    float op = clamp(1.0 - blink, 0.05, 1.0) * (1.0 - 0.28 * max(smile, 0.0)) * (1.0 - 0.15 * max(brist, 0.0));
    for (int sg = -1; sg <= 1; sg += 2) {
        float S = float(sg);
        vec3 p = l - vec3(S * EYE_C0.x, EYE_C0.y, EYE_C0.z);
        if (length(p.xy) > 0.40 || abs(p.z) > 0.45) { best = min(best, length(max(abs(p) - vec3(0.2), 0.0)) + 0.01); continue; }
        p.x *= S;                                    // espelha p/ o olho esquerdo
        p.y /= op;                                   // piscar = globo achatado
        p += EYE_C0;
        vec3 n1, n2;
        float dS = eyePiece(p, 0.0, n1) * max(op, 0.35);
        float dI = eyePiece(p, EY_TW.x, n2) * max(op, 0.35);
        float d = min(dS, dI);
        if (d < best) {
            best = d;
            bool isI = dI < dS + 0.010;
            vec3 nn = isI ? n2 : n1;
            nn = rY(rX(nn, -lookY * 0.30), lookX * 0.38);
            nn.x *= S;
            nl = nn; iris = isI ? 1.0 : 0.0;
        }
    }
    return best;
}
float dNeck(vec3 w, out vec3 nl, out vec3 lp) {
    vec3 l = neckInv(w);
    lp = l;
    float bd = boxDist(l, N_O, N_S);
    nl = vec3(0.0, 0.0, 1.0);
    if (bd > 0.0) return bd + 0.02;
    vec4 v = fetchVol(tNeck, l, N_O, N_S, N_D, N_G, N_A);
    nl = decN(v);
    return v.b * N_DM - 0.0105;
}
float dBust(vec3 w, out vec3 nl, out vec3 lp) {
    lp = w;
    float bd = boxDist(w, B_O, B_S);
    nl = vec3(0.0, 0.0, 1.0);
    if (bd > 0.0) return bd + 0.03;
    vec4 v = fetchVol(tBust, w, B_O, B_S, B_D, B_G, B_A);
    nl = decN(v);
    return v.b * B_DM - 0.026;
}
// cadeia do braço: ombro (swing/abd) -> cotovelo (flex)
vec3 armAxis(float side) { return normalize(vec3(1.48 * side, -2.11, -0.10)); }
vec3 armUpperInv(vec3 w, vec3 S, float sw, float ab, float side, float ro, float sh) {
    vec3 S2 = S + vec3(0.0, sh, 0.0);
    return S + rotAxis(rZ(rX(w - S2, sw), -(ab * side)), armAxis(side), -ro * side);
}
vec3 armUpperFwdN(vec3 n, float sw, float ab, float side, float ro) {
    return rX(rZ(rotAxis(n, armAxis(side), ro * side), ab * side), -sw);
}

float dArmU(sampler2D t, vec3 w, vec3 S, float sw, float ab, float side, float ro, float sh, vec3 O, vec3 SZ, vec3 D, vec2 G, vec2 A, float DM, out vec3 nl, out vec3 lp) {
    vec3 l = armUpperInv(w, S, sw, ab, side, ro, sh);
    lp = l;
    float bd = boxDist(l, O, SZ);
    nl = vec3(0.0, 0.0, 1.0);
    if (bd > 0.0) return bd + 0.03;
    vec4 v = fetchVol(t, l, O, SZ, D, G, A);
    nl = decN(v);
    return v.b * DM - 0.02;
}
// peça da mão: caixa + 4 variantes de curvatura em 2x2 tiles da folha única
float handPiece(vec3 p, vec3 O, vec3 SZ, vec3 D, vec2 G, vec2 TW, vec2 OFF, float cv, float nlev, float DM, out vec3 nl) {
    float bd = boxDist(p, O, SZ);
    nl = vec3(0.0, 0.0, 1.0);
    if (bd > 0.0) return bd + 0.02;
    float pos = clamp(cv, 0.0, 1.0) * (nlev - 1.0);
    float v0 = floor(pos), fr = pos - v0, v1 = min(v0 + 1.0, nlev - 1.0);
    vec4 v = fetchVar(tHand, p, O, SZ, D, G, TW, HAND_SHEET, v0, OFF);
    if (fr > 0.001 && v1 != v0) v = mix(v, fetchVar(tHand, p, O, SZ, D, G, TW, HAND_SHEET, v1, OFF), fr);
    nl = decN(v);
    return v.b * DM - 0.02;
}
float dArmHand(vec3 w, vec3 S, vec3 E, float sw, float ab, float fl, float side, float ro, float sh,
               vec4 fc, vec4 sp, vec4 wr, out vec3 nl, out vec3 lp) {
    vec3 u = armUpperInv(w, S, sw, ab, side, ro, sh);
    vec3 l = E + rX(u - E, fl);
    lp = l;
    vec3 m = vec3(l.x * side, l.y, l.z);              // espelha a mão esquerda p/ as coords da direita
    float bb = boxDist(m, HB_O, HB_S);
    nl = vec3(0.0, 0.0, 1.0);
    if (bb > 0.0) return bb + 0.04;
    vec3 nh, nb;
    bool hand = false;
    float d = handPiece(m, FA_O, FA_S, FA_D, FA_G, FA_TW, FA_OFF, 0.0, 1.0, FA_DM, nb);
    vec3 q = m - HW;                                   // punho: roll em F, flexão em S, desvio em N
    q = rotAxis(q, HF, -wr.z);
    q = rotAxis(q, HS, -wr.x);
    q = rotAxis(q, HN, -wr.y);
    vec3 p = HW + q;
    float v = handPiece(p, PA_O, PA_S, PA_D, PA_G, PA_TW, PA_OFF, 0.0, 1.0, PA_DM, nh);
    if (v < d) { d = v; nb = nh; hand = true; }
    vec3 pf = MCP0 + rotAxis(p - MCP0, HN, -sp.x * side);
    v = handPiece(pf, F0_O, F0_S, F0_D, F0_G, F0_TW, F0_OFF, fc.x, 4.0, F0_DM, nh);
    if (v < d) { d = v; nb = rotAxis(nh, HN, sp.x * side); hand = true; }
    pf = MCP1 + rotAxis(p - MCP1, HN, -sp.y * side);
    v = handPiece(pf, F1_O, F1_S, F1_D, F1_G, F1_TW, F1_OFF, fc.y, 4.0, F1_DM, nh);
    if (v < d) { d = v; nb = rotAxis(nh, HN, sp.y * side); hand = true; }
    pf = MCP2 + rotAxis(p - MCP2, HN, -sp.z * side);
    v = handPiece(pf, F2_O, F2_S, F2_D, F2_G, F2_TW, F2_OFF, fc.z, 4.0, F2_DM, nh);
    if (v < d) { d = v; nb = rotAxis(nh, HN, sp.z * side); hand = true; }
    pf = MCP3 + rotAxis(p - MCP3, HN, -sp.w * side);
    v = handPiece(pf, F3_O, F3_S, F3_D, F3_G, F3_TW, F3_OFF, fc.w, 4.0, F3_DM, nh);
    if (v < d) { d = v; nb = rotAxis(nh, HN, sp.w * side); hand = true; }
    v = handPiece(p, TH_O, TH_S, TH_D, TH_G, TH_TW, TH_OFF, wr.w, 4.0, TH_DM, nh);
    if (v < d) { d = v; nb = nh; hand = true; }
    if (hand) {                                        // volta do frame da mão ao frame do antebraço
        nb = rotAxis(nb, HN, wr.y);
        nb = rotAxis(nb, HS, wr.x);
        nb = rotAxis(nb, HF, wr.z);
    }
    nl = vec3(nb.x * side, nb.y, nb.z);
    return d;
}

vec3 triNormal(sampler2D t, vec3 p, vec3 n, float scale, float strength) {
    vec3 tx = texture(t, p.zy * scale).xyz * 2.0 - 1.0;
    vec3 ty = texture(t, p.xz * scale).xyz * 2.0 - 1.0;
    vec3 tz = texture(t, p.xy * scale).xyz * 2.0 - 1.0;
    tx.xy *= strength; ty.xy *= strength; tz.xy *= strength;
    tx = vec3(tx.xy + n.zy, abs(tx.z) * n.x);
    ty = vec3(ty.xy + n.xz, abs(ty.z) * n.y);
    tz = vec3(tz.xy + n.xy, abs(tz.z) * n.z);
    vec3 w = pow(abs(n), vec3(4.0)); w /= (w.x + w.y + w.z + 1e-5);
    return normalize(tx.zyx * w.x + ty.xzy * w.y + tz.xyz * w.z);
}
float hash3(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
float vnoise(vec3 p) {
    vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash3(i), hash3(i + vec3(1,0,0)), f.x), mix(hash3(i + vec3(0,1,0)), hash3(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash3(i + vec3(0,0,1)), hash3(i + vec3(1,0,1)), f.x), mix(hash3(i + vec3(0,1,1)), hash3(i + vec3(1,1,1)), f.x), f.y), f.z);
}

// d = mínimo entre peças. which: 0 cabeça, 1 pescoço, 2 tronco, 4 braço E sup, 5 antebraço E, 6 braço D sup, 7 antebraço D
float mapAll(vec3 world, out vec3 nl, out vec3 lp, out int which) {
    vec3 w = torsoInv(world);
    vec3 n, l;
    float d = dHead(w, nl, lp); which = 0;
    {
        vec3 hl = lp, ne; float ir;
        float de = dEyes(hl, ne, ir);
        // olhos originais esculpidos na malha da cabeça: nada a somar (dEyes mantido só p/ referência)
    }
    float v = dNeck(w, n, l);           if (v < d) { d = v; nl = n; lp = l; which = 1; }
    v = dBust(w, n, l);                 if (v < d) { d = v; nl = n; lp = l; which = 2; }
    v = dArmU(tArmLu, w, SHL, armLs, armLa, -1.0, armLr, shrugL, LU_O, LU_S, LU_D, LU_G, LU_A, LU_DM, n, l);
    if (v < d) { d = v; nl = n; lp = l; which = 4; }
    v = dArmHand(w, SHL, ELL, armLs, armLa, armLe, -1.0, armLr, shrugL, lFc, lSp, lWr, n, l);
    if (v < d) { d = v; nl = n; lp = l; which = 5; }
    v = dArmU(tArmRu, w, SHR, armRs, armRa, 1.0, armRr, shrugR, RU_O, RU_S, RU_D, RU_G, RU_A, RU_DM, n, l);
    if (v < d) { d = v; nl = n; lp = l; which = 6; }
    v = dArmHand(w, SHR, ELR, armRs, armRa, armRe, 1.0, armRr, shrugR, rFc, rSp, rWr, n, l);
    if (v < d) { d = v; nl = n; lp = l; which = 7; }
    return d;
}

void main() {
    vec2 uv = qt_TexCoord0;
    vec2 s = vec2((uv.x - 0.5) * aspect, 0.5 - uv.y);
    vec2 wxy = vec2(s.x * VIEW_H, VIEW_CY + s.y * VIEW_H);
    vec3 ro = vec3(wxy, 5.0);
    float t = 0.0, d = 1.0;
    int which = 0; vec3 nl = vec3(0.0, 0.0, 1.0), lp = vec3(0.0);
    bool hit = false;
    float bestD = 1e3, bestT = 0.0; vec3 bestN = vec3(0.0, 0.0, 1.0), bestL = vec3(0.0); int bestW = 0;
    for (int i = 0; i < 70; i++) {
        d = mapAll(ro + vec3(0.0, 0.0, -t), nl, lp, which);
        if (d < bestD) { bestD = d; bestT = t; bestN = nl; bestL = lp; bestW = which; }
        if (d < 0.0025) { hit = true; break; }
        t += max(d * 0.85, 0.004);
        if (t > 9.0) break;
    }
    float edgeA = 1.0;
    if (!hit) {                                           // borda suave: pixel que quase toca a superfície vira cobertura parcial
        float w = 1.6 * pxs;
        if (bestD > 0.0025 + w) { fragColor = vec4(0.0); return; }
        edgeA = 1.0 - smoothstep(0.0025, 0.0025 + w, bestD);
        t = bestT; nl = bestN; lp = bestL; which = bestW;
    }
    vec3 hp0 = ro + vec3(0.0, 0.0, -t);
    vec3 pT = torsoInv(hp0);

    // normal em coords do tronco (gira de volta cada peça), depois para o mundo
    vec3 n = nl;
    if (which == 0 || which == 3 || which == -1) { n = neckFwdN(rZ(rX(rY(nl, yaw * 0.32), -pitch * 0.22), -roll * 0.75)); }
    else if (which == 1) { n = neckFwdN(nl); }
    else if (which == 4) { n = armUpperFwdN(nl, armLs, armLa, -1.0, armLr); }
    else if (which == 6) { n = armUpperFwdN(nl, armRs, armRa, 1.0, armRr); }
    else if (which == 5) { n = armUpperFwdN(rX(nl, -armLe), armLs, armLa, -1.0, armLr); }
    else if (which == 7) { n = armUpperFwdN(rX(nl, -armRe), armRs, armRa, 1.0, armRr); }
    n = normalize(n);
    float spec_k = 1.0;
    vec3 nl0 = n;
    if (which == 3 || which == -1) {                      // olho original: liso e brilhante
        spec_k = 2.2;
    } else if (which == 2 || which >= 4) {                       // corpo: placas + trama
        vec3 np = triNormal(tPlates, lp, n, 0.55, 0.9);
        vec3 nw = triNormal(tWeave, lp, n, 5.0, 0.55);
        float reg = (which == 2) ? smoothstep(13.1, 13.4, lp.y) : 0.0;
        n = normalize(mix(nw, np, reg * 0.7 + 0.15));
        if (which >= 4) n = normalize(mix(nl0, nw, 0.30));      // braços: superfície lisa (sem sulcos/riscos escuros)
        spec_k = 1.4;
    } else if (which == 1) {
        n = triNormal(tWeave, lp, n, 9.0, 0.7);
        spec_k = 1.2;
    } else {
        vec3 q = (lp - PIVH) * 85.0;
        float e = 0.8;
        float b0 = vnoise(q);
        vec3 g = vec3(vnoise(q + vec3(e, 0, 0)) - b0, vnoise(q + vec3(0, e, 0)) - b0, vnoise(q + vec3(0, 0, e)) - b0);
        g += 0.5 * vec3(vnoise(q * 2.7 + 3.1) - 0.5);
        n = normalize(n - 0.09 * g);                      // pele lisa (antes 0.35: granulado/“pixelado”)
        spec_k = 0.8;
    }
    n = normalize(torsoFwdN(n));                          // mundo

    vec3 dummyN, dummyL; int dummyW;
    float aod = mapAll(hp0 + n * 0.07, dummyN, dummyL, dummyW);
    float ao = clamp(0.40 + 0.60 * clamp(aod / 0.07, 0.0, 1.0), 0.35, 1.0);
    if (which >= 4) ao = mix(1.0, ao, 0.20);

    vec3 L1 = normalize(vec3(-0.45 + yaw * 0.25, 0.55, 0.70));
    vec3 L2 = normalize(vec3(0.60, -0.20, 0.45));
    float d1 = clamp(dot(n, L1) * 0.85 + 0.15, 0.0, 1.0);
    float d2 = clamp(dot(n, L2), 0.0, 1.0);
    float rim = pow(1.0 - clamp(n.z, 0.0, 1.0), 2.2);
    vec3 H = normalize(L1 + vec3(0.0, 0.0, 1.0));
    float spec = pow(clamp(dot(n, H), 0.0, 1.0), 48.0);
    float lum = (0.08 + 0.85 * pow(d1, 1.2) + 0.30 * d2) * ao + 0.55 * rim + 0.40 * spec * spec_k;
    if (which == 1) lum += 0.30 * mouth * (0.5 + 0.5 * sin(time * 20.0));
    float mat = 0.0;
    float eyeB = 0.0;
    float zc = clamp((5.0 - t) / 9.0, 0.0, 1.0);

    // ---- expressão como emissão projetada no rosto (olhos, sobrancelhas de LED, boca) ----
    if (which == 0) {
        vec3 l = lp;
        if (l.z > 0.75 && l.y > 14.95) {
            float eg = 0.0, bg2 = 0.0, irisA = 0.0, pupA = 0.0, lid = 0.0, rimA = 0.0, lidm = 0.0, lnm = 0.0;
            for (int sg = -1; sg <= 1; sg += 2) {
                float S = float(sg);
                float b = (sg < 0) ? browL : browR;
                vec2 c0 = vec2(S * EYE_C.x, EYE_C.y);
                vec2 q = l.xy - c0;
                float ang = (b * -0.20 + brist * 0.50) * S;
                float ca = cos(ang), sa = sin(ang);
                q = vec2(ca * q.x - sa * q.y, sa * q.x + ca * q.y);
                float open = clamp((1.0 - blink) * (0.9 + 0.25 * b) + 0.05, 0.05, 1.3);
                float rx = 0.150 * (1.0 + 0.10 * max(smile, 0.0)), ry = 0.092 * open * (1.0 - 0.2 * max(-smile, 0.0));
                float e = length(vec2(q.x / rx, q.y / ry));
                float arc = length(vec2(q.x / (rx * 1.2), (q.y + 0.085 * smile) / (ry * 1.25)));
                float cut = clamp(smile * 2.0 - 0.3, 0.0, 1.0);
                float inside = 1.0 - smoothstep(0.88, 1.02, e);
                inside *= 1.0 - cut * (1.0 - smoothstep(0.88, 1.02, arc));
                eg = max(eg, inside);
                lid = max(lid, inside * smoothstep(0.55, 1.0, e));          // sombra suave da pálpebra
                rimA = max(rimA, smoothstep(0.96, 1.04, e) * (1.0 - smoothstep(1.06, 1.22, e)) * (1.0 - cut * 0.7));   // contorno (linha da pálpebra)
                // íris/pupila: seguem o olhar dentro da abertura; fixas ao globo (não ao contorno)
                vec2 ic = vec2(lookX * 0.050, lookY * 0.030);
                float di = length((q - ic) / vec2(0.078, 0.078));
                float irisM = 1.0 - smoothstep(0.90, 1.0, di);
                float pupM = 1.0 - smoothstep(0.40, 0.50, di);
                irisA = max(irisA, irisM * inside);
                pupA = max(pupA, pupM * inside);
                float e0 = length(vec2(q.x / 0.125, q.y / 0.050));
                lidm = max(lidm, 1.0 - smoothstep(0.65, 1.0, e0));
                lnm = max(lnm, (1.0 - smoothstep(0.0, 0.010, abs(q.y))) * (1.0 - smoothstep(0.75, 1.0, abs(q.x) / 0.125)));
                float byy = c0.y + lookY * 0.07 + 0.20 + b * 0.09;
                float tilt2 = brist * 0.10 * S * -1.0;
                vec2 bq = vec2(l.x - S * EYE_C.x, l.y - byy - tilt2 * (l.x - S * EYE_C.x) * 4.0 - 0.05 * (1.0 - pow((l.x - S * EYE_C.x) / 0.20, 2.0)));
                float bm = (1.0 - smoothstep(0.012, 0.024, abs(bq.y))) * (1.0 - smoothstep(0.17, 0.22, abs(bq.x)));
                bg2 = max(bg2, bm * 0.55);
            }
            float halfW = 0.215 * (1.0 + 0.22 * lipW) + 0.035 * max(smile, 0.0);
            float u = clamp(l.x / halfW, -1.0, 1.0);
            float yy = l.y - 15.078;
            float curve = smile * 0.040 * u * u - smile * 0.012;
            float openH = mouth * 0.15 * (1.0 - 0.45 * max(lipW, 0.0));
            float shp = pow(max(1.0 - u * u, 0.0), 0.8);
            float yU = curve + 0.004 + openH * 0.40 * shp;
            float yL = curve - 0.004 - openH * 0.60 * shp;
            float edge = (1.0 - smoothstep(0.85, 1.0, abs(u)));
            float lipU = (1.0 - smoothstep(0.007, 0.015, abs(yy - yU)));
            float lipL = (1.0 - smoothstep(0.008, 0.017, abs(yy - yL)));
            float mouthOn = clamp(0.35 + mouth * 1.2 + max(smile, 0.0) * 0.4, 0.0, 1.0);
            float cavity = step(yL, yy) * step(yy, yU) * edge * step(0.012, openH);
            float mg = max(lipU, lipL) * edge * mouthOn;
            float zf = smoothstep(0.75, 1.0, l.z);

            float closeK = clamp(blink + 0.30 * max(smile, 0.0), 0.0, 1.0);    // pálpebra: escurece a região e marca a linha dos olhos fechados
            lum *= 1.0 - closeK * zf * (0.28 * lidm + 0.50 * lnm);
            lum = max(lum, bg2 * zf * 0.40);
            lum = max(lum, mg * zf * 1.25);
            lum = mix(lum, 0.05, cavity * zf);
        }
    }
    if (which == -1) eyeB = 0.5;                          // íris (parte GLOW do olho original)
    fragColor = vec4(clamp(lum, 0.0, 1.4) / 1.4, mat / 4.0, eyeB, edgeA);
}
