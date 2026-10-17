#version 440
// F.R.I.D.A.Y. — Shader Holográfico de Janela 100% Partículas (Monocromático Azul/Ciano)
// Converte a textura capturada do aplicativo nativo em uma malha densa de nanopartículas
// luminosas azuis/ciano com scanlines e sweep vertical, sem cores externas.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 windowSize;
    float tempo;
    float burst;        // 0 = montada, 1 = explodida em partículas
    float lumBoost;     // 1.0 normal, 1.2 alto contraste
    float scanSpeed;
};

layout(binding = 1) uniform sampler2D source;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
    vec2 uv = qt_TexCoord0;
    vec2 pix = uv * windowSize;

    // Tamanho da célula da nanopartícula (~3.0 a 3.5 pixels)
    float cellSize = 3.2;
    vec2 cell = floor(pix / cellSize);
    vec2 cellCenter = (cell + 0.5) * cellSize;
    vec2 sampleUv = cellCenter / windowSize;

    // Se estiver em fase de explosão/montagem (burst > 0): partículas se dispersam
    if (burst > 0.001) {
        float h = hash(cell);
        vec2 dir = vec2(cos(h * 6.28318), sin(h * 6.28318));
        float dist = burst * (40.0 + h * 120.0);
        pix -= dir * dist;
        cell = floor(pix / cellSize);
        cellCenter = (cell + 0.5) * cellSize;
        sampleUv = cellCenter / windowSize;
    }

    // Limites da janela
    if (sampleUv.x < 0.0 || sampleUv.x > 1.0 || sampleUv.y < 0.0 || sampleUv.y > 1.0) {
        fragColor = vec4(0.0);
        return;
    }

    // Amostra a imagem original do app
    vec4 src = texture(source, sampleUv);

    // Luminância do pixel da janela
    float l = dot(src.rgb, vec3(0.299, 0.587, 0.114)) * lumBoost;

    // Distância do ponto ao centro da partícula
    vec2 delta = pix - cellCenter;
    float d = length(delta);

    // Paleta 100% AZUL / CIANO HOLOGRÁFICO
    vec3 cNavy = vec3(0.015, 0.045, 0.095);     // fundo escuro da janela
    vec3 cCyan = vec3(0.0, 0.82, 1.0);           // ciano elétrico puro (#00d2ff)
    vec3 cCyanGlow = vec3(0.25, 0.88, 1.0);       // ciano brilhante (#40e0ff)
    vec3 cWhiteCyan = vec3(0.88, 0.97, 1.0);      // destaque quente (#e0f7ff)

    // Efeito de varredura holográfica (scanlines horizontais suaves)
    float scan = 0.86 + 0.14 * sin(pix.y * 1.5 + tempo * 2.5);

    // Feixe vertical de varredura (sweep)
    float sweepY = fract(tempo * 0.12) * windowSize.y;
    float sweep = exp(-pow(pix.y - sweepY, 2.0) * 0.004) * 0.28;

    vec3 finalRgb = vec3(0.0);
    float finalAlpha = 0.0;

    if (l < 0.06) {
        // Áreas escuras / fundo do app: véu transparente com partículas bem sutis
        float microAlpha = exp(-d * 2.2) * 0.12 * (0.6 + 0.4 * hash(cell));
        finalRgb = (cNavy + vec3(0.0, 0.15, 0.3) * sweep) * scan;
        finalAlpha = 0.45 * (1.0 - burst) + microAlpha;
    } else {
        // Elementos visuais (texto, janelas, botões, ícones, imagens):
        // Renderizados puramente como nanopartículas ciano/azul com tamanho proporcional à luminância
        float pRadius = clamp(l * 1.45, 0.55, cellSize * 0.48);
        float pAlpha = smoothstep(pRadius, pRadius - 0.7, d);
        float glow = exp(-d * 1.4 / max(pRadius, 0.5)) * clamp(l * 0.5, 0.0, 0.45);

        // Degrade de cor 100% azul: de ciano elétrico até ciano-branco nas partes mais brilhantes
        vec3 pColor = mix(cCyan, cWhiteCyan, smoothstep(0.45, 0.95, l));
        pColor += cCyanGlow * sweep;

        finalRgb = pColor * ((pAlpha + glow) * scan + sweep * 0.5);
        finalAlpha = clamp((pAlpha * 0.95 + glow * 0.65 + 0.25) * (1.0 - burst), 0.0, 1.0);
    }

    // Borda de interferência holográfica nas laterais
    float edgeX = min(pix.x, windowSize.x - pix.x);
    float edgeY = min(pix.y, windowSize.y - pix.y);
    float edgeMin = min(edgeX, edgeY);
    if (edgeMin < 2.0) {
        finalRgb += cCyan * 0.75;
        finalAlpha = max(finalAlpha, 0.85 * (1.0 - burst));
    }

    fragColor = vec4(finalRgb, finalAlpha) * qt_Opacity;
}
