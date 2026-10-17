#version 440
// Passo 1: cena 3D (SDF + ray marching ortográfico). Saída: R=sombra, G=material/4, B=profundidade, A=cobertura
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
};

const float KS = 2.35;                 // unidades de tela por unidade de mundo
const vec3 PIV = vec3(0.0, -0.118, -0.01);   // base do pescoço

float smin(float a, float b, float k) { float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0); return mix(b, a, h) - k * h * (1.0 - h); }
float smax(float a, float b, float k) { return -smin(-a, -b, k); }
float sdE(vec3 p, vec3 r) { float k0 = length(p / r); float k1 = length(p / (r * r)); return k0 * (k0 - 1.0) / max(k1, 1e-5); }
float sdCap(vec3 p, vec3 a, vec3 b, float r) { vec3 pa = p - a, ba = b - a; return length(pa - ba * clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0)) - r; }
vec3 rX(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(p.x, c * p.y - s * p.z, s * p.y + c * p.z); }
vec3 rY(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z); }
vec3 rZ(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(c * p.x - s * p.y, s * p.x + c * p.y, p.z); }

// cabeça (coords locais da cabeça). m: material dominante (0 pele, 1 olho, 2 sobrancelha, 3 lábio, 4 boca interna)
float headD(vec3 p, out float m) {
    m = 0.0;
    float mo = mouth * 0.020;
    // crânio: mais largo nas têmporas, testa levemente saliente, nuca recuada
    float d = sdE(p - vec3(0.0, 0.024, -0.010), vec3(0.088, 0.108, 0.098));
    d = smin(d, sdE(p - vec3(0.0, 0.058, 0.026), vec3(0.074, 0.050, 0.070)), 0.040);          // testa
    d = smin(d, sdE(p - vec3(0.0, -0.040, 0.012), vec3(0.074, 0.080, 0.082)), 0.050);          // face média/inferior
    // mandíbula: ângulo da mandíbula + queixo, desce com a abertura
    vec3 pj = p - vec3(0.0, -mo * 0.85, -mo * 0.15);
    float jaw = sdE(pj - vec3(0.0, -0.080, 0.022), vec3(0.060, 0.040, 0.062));
    for (int s = -1; s <= 1; s += 2) {
        float S = float(s);
        jaw = smin(jaw, sdCap(pj, vec3(S * 0.060, -0.032, -0.030), vec3(S * 0.036, -0.088, 0.030), 0.013), 0.022);   // ramo
    }
    jaw = smin(jaw, sdE(pj - vec3(0.0, -0.104, 0.062), vec3(0.024, 0.021, 0.024)), 0.028);                       // queixo
    d = smin(d, jaw, 0.026);
    // maçãs do rosto (zigomático) e bochechas
    float up = (cheek * 0.014 + max(smile, 0.0) * 0.012);
    for (int s = -1; s <= 1; s += 2) {
        float S = float(s);
        d = smin(d, sdE(p - vec3(S * 0.054, -0.010 + up, 0.050), vec3(0.026, 0.020, 0.030)), 0.026);
        d = smin(d, sdE(p - vec3(S * 0.093, 0.004, -0.010), vec3(0.010, 0.032, 0.019)), 0.010);      // orelha
    }
    // nariz: raiz estreita, dorso, ponta, asas e narinas
    float nose = sdCap(p, vec3(0.0, 0.044, 0.082), vec3(0.0, -0.016, 0.104), 0.0082);
    nose = smin(nose, length(p - vec3(0.0, -0.024, 0.110)) - 0.0108, 0.010);
    nose = smin(nose, sdE(p - vec3( 0.0155, -0.022, 0.101), vec3(0.0105, 0.0095, 0.010)), 0.008);
    nose = smin(nose, sdE(p - vec3(-0.0155, -0.022, 0.101), vec3(0.0105, 0.0095, 0.010)), 0.008);
    d = smin(d, nose, 0.018);
    float nostril = min(length((p - vec3( 0.0085, -0.030, 0.108)) * vec3(1.0, 2.0, 1.0)) - 0.0042,
                        length((p - vec3(-0.0085, -0.030, 0.108)) * vec3(1.0, 2.0, 1.0)) - 0.0042);
    d = smax(d, -nostril, 0.003);
    // sobrancelhas (material 2): finas, ancoradas ao osso
    float brow = 1e3;
    for (int s = -1; s <= 1; s += 2) {
        float S = float(s);
        float b = (s < 0) ? browL : browR;
        float yy = 0.064 + b * 0.011;
        float tilt = brist * 0.011;
        vec3 a  = vec3(S * 0.014, yy - tilt, 0.099);
        vec3 mm = vec3(S * 0.044, yy + 0.0075 + b * 0.003 + tilt * 0.3, 0.094);
        vec3 c  = vec3(S * 0.073, yy - 0.006 + tilt * 0.1, 0.068);
        brow = min(brow, min(sdCap(p, a, mm, 0.0062), sdCap(p, mm, c, 0.0048)));
    }
    d = smin(d, brow - 0.0004, 0.004);
    // órbitas, pálpebras e globos oculares
    float eyeD = 1e3;
    for (int s = -1; s <= 1; s += 2) {
        float S = float(s);
        float b = (s < 0) ? browL : browR;
        float open = clamp((1.0 - blink) * (0.85 + 0.2 * b) + 0.04, 0.03, 1.2);
        vec3 ec = vec3(S * 0.036, 0.043, 0.084);
        d = smin(d, sdE(p - ec - vec3(0.0, 0.0125 + b * 0.002, 0.004), vec3(0.022, 0.0062, 0.015)), 0.010);        // pálpebra superior (prega)
        d = smin(d, sdE(p - ec - vec3(0.0, -0.0125, 0.002), vec3(0.019, 0.0045, 0.013)), 0.008);                   // pálpebra inferior
        float cav = sdE(p - ec - vec3(0.0, 0.0, 0.004), vec3(0.0185, 0.0118 * open + 0.0010, 0.011));
        d = smax(d, -cav, 0.0050);
        eyeD = min(eyeD, length(p - vec3(S * 0.036, 0.043, 0.080)) - 0.0128);
    }
    // boca: lábios cheios com arco de cupido, filtro, cavidade
    float mw = 0.027 + smile * 0.011 + mouth * 0.003 + lipW * 0.007;
    vec3 pm = p;
    float xr = clamp(p.x / (mw * 1.3), -1.2, 1.2);
    pm.y -= smile * (0.014 * xr * xr - 0.005);
    float lipU = sdE(pm - vec3(0.0, -0.0545, 0.086), vec3(mw, 0.0088, 0.0135));
    lipU = smin(lipU, length(pm - vec3(0.0, -0.0505, 0.0905)) - 0.0070, 0.006);                              // tubérculo/cupido
    float lipL = 1e3;
    vec3 pl = pm - vec3(0.0, -mo * 0.85, -mo * 0.15);
    lipL = sdE(pl - vec3(0.0, -0.0675, 0.083), vec3(mw * 0.90, 0.0112, 0.0150));
    d = smin(d, lipU, 0.006);
    d = smin(d, lipL, 0.006);
    d = smax(d, -sdCap(p, vec3(0.0, -0.034, 0.100), vec3(0.0, -0.047, 0.095), 0.0045), 0.004);            // filtro
    d = smax(d, -sdE(p - vec3(0.0, -0.1005 - mo * 0.85, 0.083), vec3(0.016, 0.0045, 0.015)), 0.006);     // sulco mento-labial
    float cavM = sdE(pm - vec3(0.0, -0.0608 - mo * 0.42, 0.078), vec3(mw * 0.86, mo * 0.5 + 0.0018, 0.032));
    d = smax(d, -cavM, 0.0030);
    // material
    float dm = d;
    if (brow < dm + 0.002) m = 2.0;
    if (lipU < dm + 0.0020 || lipL < dm + 0.0020) m = 3.0;
    if (eyeD < dm - 0.0005) m = 1.0;
    if (cavM < 0.0015 && mo > 0.004) m = 4.0;
    return d;
}

float bodyD(vec3 p, float breath) {
    // pescoço (curvando entre cabeça e tronco) + tendões
    vec3 q = p;
    float neck = sdCap(q, vec3(0.0, -0.068, -0.012), vec3(0.0, -0.170, -0.006), 0.053);
    for (int s = -1; s <= 1; s += 2) {
        float S = float(s);
        float tense = 0.0 + max(0.0, -S * yaw) * 0.006;
        neck = smin(neck, sdCap(q, vec3(S * 0.034, -0.090, 0.034), vec3(S * 0.016, -0.168, 0.030), 0.009 + tense), 0.012);
    }
    // tronco: ombros, trapézio, peitoral
    vec3 t = p - vec3(0.0, -0.292, -0.015);
    t.y /= (1.0 + breath * 0.012);
    float torso = sdE(t, vec3(0.185, 0.115, 0.100));
    float shoulders = sdCap(p, vec3(-0.150, -0.238, -0.012), vec3(0.150, -0.238, -0.012), 0.046 + breath * 0.002);
    torso = smin(torso, shoulders, 0.05);
    float trap = sdE(p - vec3(0.0, -0.205, -0.012), vec3(0.105, 0.045, 0.062));
    torso = smin(torso, trap, 0.04);
    neck = smin(neck, length(p - vec3(0.0, -0.118, 0.045)) - 0.011, 0.012);                                 // pomo de adão
    for (int s = -1; s <= 1; s += 2) {
        float S = float(s);
        torso = smin(torso, sdCap(p, vec3(S * 0.030, -0.186, 0.058), vec3(S * 0.120, -0.205, 0.040), 0.0075), 0.014); // clavículas
    }
    return smin(neck, torso, 0.055);
}

float map(vec3 p, out float m) {
    float breath = sin(time * 0.9);
    // tronco gira um pouco com a guinada; cabeça gira inteira em torno da base do pescoço
    vec3 pb = rY(p - vec3(0.0, -0.30, 0.0), -yaw * 0.22) + vec3(0.0, -0.30, 0.0);
    pb = rZ(pb - PIV, roll * 0.08) + PIV;
    float b = bodyD(pb, breath);
    // cabeça: transformação inversa (pitch/yaw/roll) + leve respiração
    vec3 h = p - PIV;
    h = rZ(h, roll * 1.1);
    h = rX(h, pitch * 0.40);
    h = rY(h, -yaw * 0.60);
    h += PIV + vec3(0.0, breath * 0.0012, 0.0);
    float hm;
    float hd = headD(h, hm);
    float d = smin(hd, b, 0.040);
    m = (hd <= b + 0.004) ? hm : 0.0;
    return d;
}

float mapD(vec3 p) { float m; return map(p, m); }

void main() {
    vec2 uv = qt_TexCoord0;
    vec2 s = vec2((uv.x - 0.5) * aspect, 0.5 - uv.y);
    vec2 w = (s - vec2(0.0, 0.07)) / KS;                         // coords de mundo (x,y)
    float t = 0.0, d = 1.0, m = 0.0;
    bool hit = false;
    vec3 ro = vec3(w, 0.60);
    for (int i = 0; i < 44; i++) {
        d = map(ro + vec3(0.0, 0.0, -t), m);
        if (d < 0.0006) { hit = true; break; }
        t += d * 0.9;
        if (t > 1.2) break;
    }
    if (!hit) { fragColor = vec4(0.0); return; }
    vec3 p = ro + vec3(0.0, 0.0, -t);
    vec2 e = vec2(0.0012, -0.0012);
    vec3 n = normalize(e.xyy * mapD(p + e.xyy) + e.yyx * mapD(p + e.yyx) + e.yxy * mapD(p + e.yxy) + e.xxx * mapD(p + e.xxx));
    vec3 L1 = normalize(vec3(-0.45 + yaw * 0.25, 0.55, 0.70));
    vec3 L2 = normalize(vec3(0.60, -0.20, 0.45));
    float d1 = clamp(dot(n, L1) * 0.85 + 0.15, 0.0, 1.0);
    float d2 = clamp(dot(n, L2), 0.0, 1.0);
    float rim = pow(1.0 - clamp(n.z, 0.0, 1.0), 2.4);
    vec3 H = normalize(L1 + vec3(0.0, 0.0, 1.0));
    float spec = pow(clamp(dot(n, H), 0.0, 1.0), 40.0);
    float ao = 1.0;
    for (int k = 1; k <= 3; k++) { float h = 0.010 * float(k); ao -= (h - mapD(p + n * h)) * (0.30 / float(k)); }
    ao = clamp(ao, 0.45, 1.0);
    float lum = (0.05 + 0.90 * pow(d1, 1.3) + 0.38 * d2) * ao + 0.55 * rim + 0.35 * spec * ao;
    // emendas de placas (robótico): linhas finas em coords locais da cabeça / pescoço
    vec3 hl = p - PIV;
    hl = rZ(hl, roll * 1.1); hl = rX(hl, pitch * 0.40); hl = rY(hl, -yaw * 0.60);
    hl += PIV;
    float seam = 0.0;
    seam += 1.0 - smoothstep(0.0006, 0.0014, abs(abs(hl.x) - 0.022)) * 1.0;             // junta vertical da testa
    seam *= smoothstep(0.075, 0.085, hl.y) * (1.0 - smoothstep(0.125, 0.135, hl.y));
    float seam2 = (1.0 - smoothstep(0.0005, 0.0012, abs(hl.y - 0.092))) * (1.0 - smoothstep(0.060, 0.075, abs(hl.x)));
    float seam3 = (1.0 - smoothstep(0.0005, 0.0012, abs(length(vec2(hl.x * 1.0, (hl.y + 0.01) * 1.25)) - 0.088))) * step(hl.z, 0.05) * step(0.0, hl.z + 0.02);
    float rings = 1.0 - smoothstep(0.0004, 0.0011, abs(fract((p.y + 0.12) / 0.016) - 0.5) - 0.46);
    rings *= step(p.y, -0.098) * step(-0.195, p.y) * (1.0 - smoothstep(0.045, 0.060, abs(p.x))) * step(0.0, p.z);   // anéis do pescoço
    float jawSeam = (1.0 - smoothstep(0.0005, 0.0013, abs(hl.y + 0.030 + 0.20 * (hl.x * hl.x)))) * step(0.040, abs(hl.x)) * step(abs(hl.x), 0.075) * step(0.0, hl.z);
    float cut = clamp(rings * 0.45, 0.0, 1.0);
    lum *= (1.0 - 0.75 * cut);
    if (m > 0.5 && m < 1.5) {                                      // olho: esclera/íris/pupila pelo olhar
        vec3 g = rY(rX(normalize(vec3(lookX * 0.50, lookY * 0.38, 1.0)), -pitch * 0.40), yaw * 0.60);
        float c = dot(n, g);
        lum = mix(0.20, 0.70, smoothstep(0.86, 0.93, c));
        lum = mix(lum, 0.05, smoothstep(0.972, 0.99, c));
        lum += smoothstep(0.993, 0.999, dot(n, normalize(vec3(-0.3, 0.4, 0.86)))) * 0.9;
    }
    if (m > 3.5) lum *= 0.25;                                     // interior da boca
    float zc = clamp((0.6 - t) * 0.9 + 0.5, 0.0, 1.0);
    fragColor = vec4(clamp(lum, 0.0, 1.4) / 1.4, m / 4.0, zc, 1.0);
}
