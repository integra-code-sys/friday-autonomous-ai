#version 440
// F.R.I.D.A.Y. — camada holográfica FORTE sobre as câmeras (PainelStark):
// luminância -> ciano, contornos (Sobel) brilhando, scanlines, faixa de varredura, ruído de partículas,
// glitch ocasional por faixas, aberração cromática leve, vinheta e borda luminosa. forca: 0 = imagem crua, 1 = holograma pleno.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 tamanho;       // px do item
    float tempo;        // s
    float forca;        // 0..1
    vec4 cor;           // tom do holograma (ciano)
};

layout(binding = 1) uniform sampler2D source;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

float lum(vec2 uv) { return dot(texture(source, uv).rgb, vec3(0.299, 0.587, 0.114)); }

void main() {
    vec2 uv = qt_TexCoord0;
    vec2 px = 1.0 / max(tamanho, vec2(1.0));

    // glitch: faixas horizontais deslocadas por instantes (~a cada 3 s)
    float faixa = floor(uv.y * 24.0);
    float janela = step(0.93, fract(tempo * 0.33 + hash(vec2(floor(tempo * 0.33), 1.0)) * 0.1));
    float desloc = (hash(vec2(faixa, floor(tempo * 12.0))) - 0.5) * 0.06 * janela * step(0.6, hash(vec2(faixa, 7.0)));
    vec2 uvg = vec2(uv.x + desloc * forca, uv.y);

    // aberração cromática leve
    float ab = 0.0025 * forca;
    vec3 orig = vec3(texture(source, uvg + vec2(ab, 0.0)).r, texture(source, uvg).g, texture(source, uvg - vec2(ab, 0.0)).b);
    float l = dot(orig, vec3(0.299, 0.587, 0.114));

    // contornos (Sobel) -> brilho de holograma
    float tl = lum(uvg + px * vec2(-1, -1)), t = lum(uvg + px * vec2(0, -1)), tr = lum(uvg + px * vec2(1, -1));
    float ml = lum(uvg + px * vec2(-1, 0)),                                  mr = lum(uvg + px * vec2(1, 0));
    float bl = lum(uvg + px * vec2(-1, 1)), b = lum(uvg + px * vec2(0, 1)), br = lum(uvg + px * vec2(1, 1));
    float gx = -tl - 2.0 * ml - bl + tr + 2.0 * mr + br;
    float gy = -tl - 2.0 * t - tr + bl + 2.0 * b + br;
    float borda = clamp(length(vec2(gx, gy)) * 1.6, 0.0, 1.0);

    // tom holográfico: luminância com contraste, mapeada no ciano; contornos quase brancos
    float lc = pow(clamp(l * 1.25, 0.0, 1.0), 0.85);
    vec3 holo = cor.rgb * (0.18 + 0.95 * lc) + vec3(0.75, 0.97, 1.0) * borda * 0.85;

    // scanlines finas + faixa de varredura descendo + cintilação
    float scan = 0.78 + 0.22 * sin(uv.y * tamanho.y * 3.14159 * 0.5);
    float varre = smoothstep(0.08, 0.0, abs(fract(uv.y - tempo * 0.18) - 0.5) - 0.42);
    holo *= scan;
    holo += cor.rgb * varre * 0.35;
    holo *= 0.94 + 0.06 * sin(tempo * 37.0);

    // partículas / ruído
    float n = hash(floor(uv * tamanho / 2.0) + floor(tempo * 20.0));
    holo += cor.rgb * step(0.985, n) * 0.6;
    holo += (n - 0.5) * 0.05;

    // vinheta + borda luminosa
    vec2 d = abs(uv - 0.5) * 2.0;
    float vin = 1.0 - smoothstep(0.55, 1.15, length(d));
    float aro = smoothstep(0.94, 1.0, max(d.x, d.y));
    holo = holo * (0.55 + 0.45 * vin) + cor.rgb * aro * 0.9;

    vec3 final = mix(orig, holo, forca);
    float alfa = mix(1.0, 0.92, forca);              // levemente translúcido (holograma)
    fragColor = vec4(final * alfa, alfa) * qt_Opacity;
}
