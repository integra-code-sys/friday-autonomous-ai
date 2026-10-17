#!/usr/bin/env python3
"""Gerador de Ícones Holográficos Stark F.R.I.D.A.Y. (Projeto Prometheus).
Gera ícones padronizados, futuristas e personalizados em múltiplas resoluções:
- Android: mipmap-mdpi (48), hdpi (72), xhdpi (96), xxhdpi (144), xxxhdpi (192), play store (512)
- Windows: Friday.ico (multi-resolução: 256, 128, 64, 48, 32, 16)
- Linux: friday.svg e friday.png (512, 256, 128, 64)
- Shell & Web: friday_logo.png
"""
import math
import os
import sys
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def criar_reator_stark(tamanho=512):
    """Renderiza o Reator Arc Stark Mark 85 holográfico em altíssima definição."""
    # Renderiza em 2x para super-sampling anti-aliasing
    scale = 2
    size = tamanho * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size / 2.0, size / 2.0
    r_max = size * 0.46

    # 1. Fundo Circular Profundo (Dark Obsidian / Cyber Space)
    draw.ellipse([cx - r_max, cy - r_max, cx + r_max, cy + r_max],
                 fill=(2, 7, 12, 250), outline=(26, 143, 184, 180), width=int(3 * scale))

    # 2. Halo Exterior de Energia Cyan (Glow)
    glow_r = r_max * 0.94
    draw.ellipse([cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r],
                 outline=(0, 229, 255, 90), width=int(4 * scale))

    # 3. 12 Bobinas Magnéticas de Indução Periféricas (Stark Arc Magnets)
    for i in range(12):
        ang = i * (2 * math.pi / 12)
        r_bob_in = r_max * 0.72
        r_bob_out = r_max * 0.91
        larg_ang = 0.16

        p1 = (cx + r_bob_in * math.cos(ang - larg_ang), cy + r_bob_in * math.sin(ang - larg_ang))
        p2 = (cx + r_bob_out * math.cos(ang - larg_ang * 0.7), cy + r_bob_out * math.sin(ang - larg_ang * 0.7))
        p3 = (cx + r_bob_out * math.cos(ang + larg_ang * 0.7), cy + r_bob_out * math.sin(ang + larg_ang * 0.7))
        p4 = (cx + r_bob_in * math.cos(ang + larg_ang), cy + r_bob_in * math.sin(ang + larg_ang))

        # Bobinas em gradiente âmbar/cobre Stark com borda cyan
        draw.polygon([p1, p2, p3, p4], fill=(255, 138, 31, 230), outline=(0, 229, 255, 240))

    # 4. Anel Segmentado de Condução Intermediário
    r_mid = r_max * 0.68
    draw.ellipse([cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid],
                 outline=(0, 229, 255, 220), width=int(3.5 * scale))

    # 5. Dentes Internos de Alta Frequência (24 segmentos)
    for i in range(24):
        ang = i * (2 * math.pi / 24)
        r1 = r_mid * 0.88
        r2 = r_mid * 0.98
        p_a = (cx + r1 * math.cos(ang), cy + r1 * math.sin(ang))
        p_b = (cx + r2 * math.cos(ang), cy + r2 * math.sin(ang))
        draw.line([p_a, p_b], fill=(54, 214, 255, 200), width=int(2 * scale))

    # 6. Anel Central de Confinamento Magnético
    r_core_ring = r_max * 0.44
    draw.ellipse([cx - r_core_ring, cy - r_core_ring, cx + r_core_ring, cy + r_core_ring],
                 fill=(4, 27, 44, 255), outline=(0, 229, 255, 255), width=int(4 * scale))

    # 7. Triângulo Holográfico do Reator Arc (Stark Chevron Core)
    tri_r = r_core_ring * 0.75
    pts_tri = []
    for k in range(3):
        # Triângulo invertido característico do Arc Reactor
        ang_t = -math.pi / 2 + k * (2 * math.pi / 3) + math.pi
        pts_tri.append((cx + tri_r * math.cos(ang_t), cy + tri_r * math.sin(ang_t)))

    draw.polygon(pts_tri, fill=(0, 229, 255, 220), outline=(255, 255, 255, 255))

    # 8. Núcleo Interno de Plasma Branco/Cyan
    r_plasma = tri_r * 0.38
    draw.ellipse([cx - r_plasma, cy - r_plasma, cx + r_plasma, cy + r_plasma],
                 fill=(255, 255, 255, 255), outline=(0, 229, 255, 255), width=int(2 * scale))

    # Reduz de volta para o tamanho alvo com antialiasing LANCZOS de alta precisão
    final_img = img.resize((tamanho, tamanho), Image.Resampling.LANCZOS)
    return final_img


def gerar_svg_stark():
    """Gera o arquivo SVG vetorial oficial do Stark Arc Reactor."""
    return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <defs>
    <radialGradient id="spaceBg" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#0a2a44" stop-opacity="1"/>
      <stop offset="70%" stop-color="#04121e" stop-opacity="1"/>
      <stop offset="100%" stop-color="#02070c" stop-opacity="1"/>
    </radialGradient>
    <radialGradient id="corePlasma" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="45%" stop-color="#36d6ff"/>
      <stop offset="85%" stop-color="#00a8cc"/>
      <stop offset="100%" stop-color="#041b2c"/>
    </radialGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <!-- Fundo Circular Holográfico -->
  <circle cx="256" cy="256" r="236" fill="url(#spaceBg)" stroke="#1a8fb8" stroke-width="4"/>
  <circle cx="256" cy="256" r="224" fill="none" stroke="#00e5ff" stroke-width="2" stroke-opacity="0.4" stroke-dasharray="12 6"/>

  <!-- Halo de Energia -->
  <circle cx="256" cy="256" r="212" fill="none" stroke="#00e5ff" stroke-width="3" filter="url(#glow)"/>

  <!-- 12 Bobinas Magnéticas de Indução Arc -->
  <g id="magnets">
    <!-- Repetidas em ângulos de 30 graus -->
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" />
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(30 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(60 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(90 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(120 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(150 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(180 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(210 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(240 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(270 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(300 256 256)"/>
    <path d="M 238 34 L 234 68 L 278 68 L 274 34 Z" fill="#ff8a1f" stroke="#00e5ff" stroke-width="2.5" transform="rotate(330 256 256)"/>
  </g>

  <!-- Anel Intermediário de Condução -->
  <circle cx="256" cy="256" r="162" fill="none" stroke="#00e5ff" stroke-width="4"/>
  <circle cx="256" cy="256" r="148" fill="none" stroke="#1a8fb8" stroke-width="2" stroke-dasharray="6 4"/>

  <!-- Anel Central de Confinamento -->
  <circle cx="256" cy="256" r="105" fill="#041b2c" stroke="#00e5ff" stroke-width="5" filter="url(#glow)"/>

  <!-- Triângulo Invertido Central Stark -->
  <polygon points="256,325 186,204 326,204" fill="url(#corePlasma)" stroke="#ffffff" stroke-width="3"/>

  <!-- Núcleo de Plasma -->
  <circle cx="256" cy="244" r="28" fill="#ffffff" filter="url(#glow)"/>
</svg>'''


def exportar_todos_icones():
    print("[ÍCONES] Gerando pacote holográfico Stark padronizado...", flush=True)

    # 1. Base em alta resolução 512x512
    base_512 = criar_reator_stark(512)

    # 2. Android: Todas as densidades de Launcher
    android_dirs = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }

    # No projeto de desenvolvimento local
    for pasta, dim in android_dirs.items():
        caminho_dir = os.path.join(ROOT, "app-remoto", "res", pasta)
        os.makedirs(caminho_dir, exist_ok=True)
        img_dim = base_512.resize((dim, dim), Image.Resampling.LANCZOS)
        img_dim.save(os.path.join(caminho_dir, "ic_launcher.png"), "PNG")
        print(f"  ✓ Android: {pasta}/ic_launcher.png ({dim}x{dim})")

    # No repositório comercial
    for pasta, dim in android_dirs.items():
        caminho_dir = os.path.join(ROOT, "friday-commercial-github", "android", "res", pasta)
        os.makedirs(caminho_dir, exist_ok=True)
        img_dim = base_512.resize((dim, dim), Image.Resampling.LANCZOS)
        img_dim.save(os.path.join(caminho_dir, "ic_launcher.png"), "PNG")

    # Play Store icon (512x512)
    base_512.save(os.path.join(ROOT, "app-remoto", "res", "ic_launcher_512.png"), "PNG")
    base_512.save(os.path.join(ROOT, "friday-commercial-github", "android", "res", "ic_launcher_512.png"), "PNG")

    # 3. Windows: Friday.ico multi-resolução
    win_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    ico_destinos = [
        os.path.join(ROOT, "Friday.ico"),
        os.path.join(ROOT, "daemon", "Friday.ico"),
        os.path.join(ROOT, "friday-commercial-github", "Friday.ico"),
        os.path.join(ROOT, "friday-commercial-github", "daemon", "Friday.ico"),
    ]
    for d in ico_destinos:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        base_512.save(d, format="ICO", sizes=win_sizes)
        print(f"  ✓ Windows ICO: {os.path.relpath(d, ROOT)}")

    # 4. Linux: friday.svg e friday.png
    svg_content = gerar_svg_stark()
    svg_destinos = [
        os.path.join(ROOT, "shell", "friday.svg"),
        os.path.join(ROOT, "friday.svg"),
        os.path.join(ROOT, "friday-commercial-github", "shell", "friday.svg"),
        os.path.join(ROOT, "friday-commercial-github", "friday.svg"),
    ]
    for d in svg_destinos:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        with open(d, "w", encoding="utf-8") as f:
            f.write(svg_content)
        print(f"  ✓ Linux SVG: {os.path.relpath(d, ROOT)}")

    png_destinos = [
        os.path.join(ROOT, "shell", "friday.png"),
        os.path.join(ROOT, "friday.png"),
        os.path.join(ROOT, "friday-commercial-github", "shell", "friday.png"),
        os.path.join(ROOT, "friday-commercial-github", "friday.png"),
    ]
    for d in png_destinos:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        base_512.save(d, "PNG")
        print(f"  ✓ Linux PNG: {os.path.relpath(d, ROOT)}")

    # 5. Linux Desktop Entry: friday.desktop
    desktop_entry = f"""[Desktop Entry]
Name=F.R.I.D.A.Y.
Comment=Assistente de IA Pessoal Autônomo Multi-Nó (Projeto Prometheus)
Exec={ROOT}/run.sh
Icon={os.path.join(ROOT, "friday.png")}
Terminal=false
Type=Application
Categories=Utility;Development;AudioVideo;
StartupNotify=true
"""
    local_app_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(local_app_dir, exist_ok=True)
    with open(os.path.join(local_app_dir, "friday.desktop"), "w", encoding="utf-8") as f:
        f.write(desktop_entry)

    # Cria também modelo para o commercial repo
    commercial_desktop = """[Desktop Entry]
Name=F.R.I.D.A.Y.
Comment=Assistente de IA Pessoal Autônomo Multi-Nó (Integra Code)
Exec=./run.sh
Icon=friday.png
Terminal=false
Type=Application
Categories=Utility;Development;AudioVideo;
StartupNotify=true
"""
    with open(os.path.join(ROOT, "friday-commercial-github", "friday.desktop"), "w", encoding="utf-8") as f:
        f.write(commercial_desktop)

    print("[ÍCONES] Todos os ícones gerados e instalados com sucesso!", flush=True)


if __name__ == "__main__":
    exportar_todos_icones()
