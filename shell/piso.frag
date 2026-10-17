#version 440
// Piso holográfico em perspectiva (F.R.I.D.A.Y.): grade infinita correndo na direção de quem olha, calculada na GPU.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float tempo;
    float energia;
    float horizonte;
    float focoX;
    float aspecto;
};
void main() {
    vec2 uv = qt_TexCoord0;
    float dy = uv.y - horizonte;
    if (dy <= 0.0015) { fragColor = vec4(0.0); return; }
    float z = 0.11 / dy;                                   // profundidade
    float x = (uv.x - focoX) * aspecto * z;                // posição lateral no plano
    float zz = z + tempo * (0.55 + energia * 1.4);         // correndo para frente
    vec2 g = vec2(x * 16.0, zz * 1.7);                    // ~10 linhas na largura perto de quem olha
    vec2 d = abs(fract(g - 0.5) - 0.5) / max(fwidth(g), vec2(1e-4));
    float linha = 1.0 - min(min(d.x, d.y), 1.0);
    float perto = smoothstep(0.0, 0.30, dy);               // some no horizonte
    float longe = 1.0 - smoothstep(1.2, 7.0, z);
    float laranja = step(0.94, fract(zz * 0.125));         // de vez em quando uma linha laranja
    vec3 cor = mix(vec3(0.56, 0.91, 1.0), vec3(1.0, 0.55, 0.15), laranja * step(d.y, d.x));
    float a = linha * perto * longe * (0.22 + energia * 0.25);
    float halo = exp(-dy * 70.0) * (0.06 + energia * 0.06);   // brilho do horizonte
    vec3 rgb = cor * a + vec3(0.30, 0.75, 1.0) * halo;
    fragColor = vec4(rgb, clamp(a + halo, 0.0, 1.0)) * qt_Opacity;
}
