"""Central de Configuração Fácil e Gerenciador de Boot — F.R.I.D.A.Y. Commercial Edition.

Permite ao usuário configurar facilmente (via Interface Web/GUI em /config ou via CLI):
1. Ativar / Desativar inicialização automática no Boot (Linux systemd/XDG Autostart e Windows Registry/Startup).
2. Escolher provedor de Visão e Cérebro: Local (Ollama) ou Nuvem (Google Gemini, Anthropic Claude, OpenAI GPT).
3. Configurar o cenário de câmeras (Auto, 0 câmeras, 1 câmera, 2 câmeras, 3 câmeras + PTZ).
4. Gerenciar a Memória e Aprendizado do Zero (ver estatísticas ou executar Factory Reset).
5. Parear o aplicativo Android e nós da rede Mesh.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import camera_manager as CM
import cloud_providers as CP
import memoria_zero as MZ
import win_compat


# =====================================================================
# 1. GERENCIADOR DE INICIALIZAÇÃO NO BOOT (LINUX & WINDOWS)
# =====================================================================
LINUX_AUTOSTART_FILE = os.path.expanduser("~/.config/autostart/friday-commercial.desktop")


def status_boot():
    """Verifica se a inicialização automática no boot está ativa no SO atual."""
    cfg = MZ.carregar_config()
    if win_compat.IS_WINDOWS:
        startup_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming")),
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
        )
        lnk = os.path.join(startup_dir, "Friday_Commercial_Autostart.lnk")
        ativo = os.path.exists(lnk) or bool(cfg.get("boot", {}).get("iniciar_no_boot"))
        return {"ativo": ativo, "ativo_no_sistema": ativo, "plataforma": "windows", "caminho": lnk}
    else:
        autostart_file = LINUX_AUTOSTART_FILE
        systemd_file = os.path.expanduser("~/.config/systemd/user/friday-commercial.service")
        ativo = os.path.exists(autostart_file) or os.path.exists(systemd_file)
        return {"ativo": ativo, "ativo_no_sistema": ativo, "plataforma": "linux", "caminho": autostart_file}


def configurar_boot(ativar: bool, dry_run: bool = False):
    """Ativa ou desativa a inicialização da F.R.I.D.A.Y. no boot do sistema operacional."""
    MZ.salvar_config({"boot": {"iniciar_no_boot": bool(ativar)}})

    if dry_run:
        return {
            "ok": True,
            "ativo": bool(ativar),
            "plataforma": "windows" if win_compat.IS_WINDOWS else "linux",
            "modo": "dry_run"
        }

    if win_compat.IS_WINDOWS:
        startup_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming")),
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
        )
        os.makedirs(startup_dir, exist_ok=True)
        lnk = os.path.join(startup_dir, "Friday_Commercial_Autostart.lnk")
        vbs = os.path.join(ROOT, "start_friday_silent.vbs")
        if ativar:
            ps_cmd = (
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut('{lnk}'); "
                f"$s.TargetPath = 'wscript.exe'; "
                f"$s.Arguments = '\"{vbs}\"'; "
                f"$s.WorkingDirectory = '{ROOT}'; "
                f"$s.Description = 'F.R.I.D.A.Y. Commercial Autostart'; "
                f"$s.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True)
            return {"ok": True, "ativo": True, "plataforma": "windows", "caminho": lnk}
        else:
            if os.path.exists(lnk):
                try:
                    os.remove(lnk)
                except OSError:
                    pass
            return {"ok": True, "ativo": False, "plataforma": "windows", "caminho": lnk}
    else:
        autostart_dir = os.path.expanduser("~/.config/autostart")
        os.makedirs(autostart_dir, exist_ok=True)
        desktop_file = os.path.join(autostart_dir, "friday-commercial.desktop")
        run_script = os.path.join(ROOT, "run.sh")

        if ativar:
            conteudo_desktop = f"""[Desktop Entry]
Type=Application
Name=F.R.I.D.A.Y. AI Assistant
Comment=Assistente Autônoma Multimodal (Projeto Prometheus)
Exec=/bin/sh "{run_script}"
Path={ROOT}
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
"""
            with open(desktop_file, "w", encoding="utf-8") as f:
                f.write(conteudo_desktop)
            return {"ok": True, "ativo": True, "plataforma": "linux", "caminho": desktop_file}
        else:
            if os.path.exists(desktop_file):
                try:
                    os.remove(desktop_file)
                except OSError:
                    pass
            return {"ok": True, "ativo": False, "plataforma": "linux", "caminho": desktop_file}


# =====================================================================
# 2. INTERFACE WEB INTERATIVA DE CONFIGURAÇÃO (/config)
# =====================================================================
HTML_PAINEL_CONFIG = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>F.R.I.D.A.Y. — Central de Configuração</title>
<style>
  :root { --bg: #080d14; --card: #101926; --border: #1e324a; --accent: #36d6ff; --accent2: #ff8a1f; --text: #e6f4ff; --muted: #8aa4bf; --ok: #2ee59d; --danger: #ff4d6d; }
  * { box-sizing: border-box; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
  body { margin: 0; background: var(--bg); color: var(--text); padding: 24px; max-width: 1020px; margin-inline: auto; }
  header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }
  h1 { margin: 0; font-size: 1.5rem; letter-spacing: 1px; color: var(--accent); }
  .badge { background: rgba(54,214,255,0.12); color: var(--accent); border: 1px solid var(--accent); padding: 4px 10px; border-radius: 99px; font-size: 0.8rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(440px, 1fr)); gap: 20px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card h2 { margin-top: 0; font-size: 1.1rem; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 10px; }
  label { display: block; margin-top: 12px; font-size: 0.88rem; color: var(--muted); }
  input[type="text"], input[type="password"], select { width: 100%; padding: 10px; margin-top: 5px; border-radius: 8px; border: 1px solid var(--border); background: #0b121c; color: var(--text); }
  .row { display: flex; align-items: center; justify-content: space-between; margin-top: 14px; padding: 10px; background: rgba(255,255,255,0.02); border-radius: 8px; }
  button { cursor: pointer; padding: 10px 18px; border-radius: 8px; border: none; font-weight: 600; background: var(--accent); color: #041019; margin-top: 16px; transition: 0.15s; }
  button:hover { filter: brightness(1.12); }
  button.danger { background: var(--danger); color: #fff; }
  button.secondary { background: #1e324a; color: var(--text); }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; text-align: center; }
  .stat-box { background: #0b121c; padding: 12px; border-radius: 8px; border: 1px solid var(--border); }
  .stat-box b { display: block; font-size: 1.4rem; color: var(--ok); }
  #msg { position: fixed; bottom: 20px; right: 20px; background: var(--ok); color: #041019; padding: 12px 20px; border-radius: 8px; font-weight: bold; display: none; }
</style>
</head>
<body>
<header>
  <div>
    <h1>F.R.I.D.A.Y. // CENTRAL DE CONFIGURAÇÃO — INTEGRA CODE</h1>
    <small style="color:var(--muted)">Edição Comercial Multiplataforma (Linux · Windows · Android) · Desenvolvido por <b>Integra Code</b></small>
  </div>
  <span class="badge" id="status-badge">Online · Zero-Telemetry</span>
</header>

<div class="grid">
  <!-- 1. Usuário e Inicialização no Boot -->
  <div class="card">
    <h2>1. Perfil e Inicialização no Boot</h2>
    <label>Como a F.R.I.D.A.Y. deve chamar você:</label>
    <input type="text" id="usuario_nome" placeholder="Ex: Senhor, Ana, Carlos...">

    <div class="row">
      <div>
        <strong>Iniciar automaticamente no Boot do PC</strong><br>
        <small style="color:var(--muted)">Sobe em segundo plano ao ligar o Windows ou Linux</small>
      </div>
      <input type="checkbox" id="boot_ativo" style="width:22px;height:22px">
    </div>
    <button onclick="salvarGeral()">Salvar Perfil e Boot</button>
  </div>

  <!-- 2. Modelo de Visão e Cérebro (Local ou Nuvem) -->
  <div class="card">
    <h2>2. Inteligência Artificial e Visão (Local / Nuvem)</h2>
    <label>Provedor do Cérebro (Decisões e Ferramentas):</label>
    <select id="provedor_cerebro">
      <option value="ollama">100% Local (Ollama — Qwen3-VL / Gemma3)</option>
      <option value="gemini">Nuvem: Google Gemini (Gemini 2.5 Flash / Pro)</option>
      <option value="claude">Nuvem: Anthropic Claude (Claude 3.5 / 3.7 Sonnet)</option>
      <option value="openai">Nuvem: OpenAI GPT (GPT-4o / GPT-4o-mini)</option>
      <option value="auto">Híbrido Automático (Nuvem com Fallback Local)</option>
    </select>

    <label>Provedor de Visão (Leitura de Tela, Câmeras e Objetos):</label>
    <select id="provedor_visao">
      <option value="ollama">100% Local (Ollama — Qwen3-VL)</option>
      <option value="gemini">Nuvem: Google Gemini Vision</option>
      <option value="claude">Nuvem: Anthropic Claude Vision</option>
      <option value="openai">Nuvem: OpenAI GPT-4o Vision</option>
      <option value="auto">Híbrido Automático</option>
    </select>

    <label>Chave API Google Gemini (opcional):</label>
    <input type="password" id="gemini_api_key" placeholder="AIzaSy...">

    <label>Chave API Anthropic Claude (opcional):</label>
    <input type="password" id="claude_api_key" placeholder="sk-ant-...">

    <label>Chave API OpenAI GPT (opcional):</label>
    <input type="password" id="openai_api_key" placeholder="sk-proj-...">

    <button onclick="salvarIA()">Salvar Provedores de IA</button>
  </div>

  <!-- 3. Cenário de Câmeras (0, 1, 2 ou 3+ câmeras) -->
  <div class="card">
    <h2>3. Configuração de Câmeras e Sensores</h2>
    <label>Cenário de Hardware de Câmeras:</label>
    <select id="cameras_modo">
      <option value="auto">Detecção Automática (Recomendado)</option>
      <option value="sem_camera">0 Câmeras (PC Desktop sem webcam — Só Tela + Voz)</option>
      <option value="1_camera">1 Câmera (Apenas Webcam do Notebook/PC)</option>
      <option value="2_cameras">2 Câmeras (Webcam Frontal + Câmera Ambiente USB/IP)</option>
      <option value="3_cameras_ptz">3 Câmeras (Completa com Câmera PTZ Motorizada)</option>
    </select>

    <label>URL RTSP ou IP da Câmera PTZ (apenas se tiver câmera motorizada):</label>
    <input type="text" id="camera_ptz_rtsp" placeholder="Ex: rtsp://admin:senha@192.168.1.50:554/stream1">

    <button onclick="salvarCameras()">Aplicar Cenário de Câmeras</button>
  </div>

  <!-- 4. Memória e Aprendizado do Zero -->
  <div class="card">
    <h2>4. Memória Viva e Aprendizado do Zero</h2>
    <div class="stats">
      <div class="stat-box"><b id="st_fatos">0</b><small>Fatos</small></div>
      <div class="stat-box"><b id="st_ep">0</b><small>Episódios</small></div>
      <div class="stat-box"><b id="st_lic">0</b><small>Lições</small></div>
    </div>
    <p style="font-size:0.85rem;color:var(--muted);margin-top:14px">
      A F.R.I.D.A.Y. constrói sua própria memória factual, episódica e lições de auto-reflexão a partir do zero conforme interage com você.
    </p>
    <button class="danger" onclick="resetarMemoria()">Limpar Tudo e Reaprender do Zero</button>
  </div>
</div>

<!-- Termo de Uso e Garantia de Privacidade Integra Code -->
<div class="card" style="margin-top:20px; border-color:#2ee59d44">
  <h2 style="color:var(--ok)">🔒 Termo de Uso e Garantia de Privacidade — Integra Code (Zero Data Retention)</h2>
  <p style="font-size:0.88rem; color:var(--muted); line-height:1.5; margin:0">
    A <b>Integra Code</b> garante contratualmente e por arquitetura técnica (<i>Privacy Guard</i> ativo) que <b>NÃO coleta, NÃO armazena, NÃO intercepta e NÃO retém</b> nenhum dado pessoal, voz, imagem de câmera, captura de tela ou chave de API. Todo o processamento ocorre <b>100% localmente no seu dispositivo</b> ou diretamente entre sua máquina e o provedor de nuvem (Google Gemini, Anthropic Claude ou OpenAI) configurado por você.
  </p>
</div>

<div id="msg">Configuração salva!</div>

<script>
const tok = new URLSearchParams(location.search).get("t") || localStorage.getItem("tok") || "";
function aviso(txt) {
  const el = document.getElementById("msg");
  el.textContent = txt; el.style.display = "block";
  setTimeout(() => el.style.display = "none", 2600);
}
async function carregar() {
  const r = await fetch("/api/config/status?t=" + encodeURIComponent(tok));
  if (!r.ok) return;
  const d = await r.json();
  const c = d.config || {};
  document.getElementById("usuario_nome").value = (c.usuario && c.usuario.nome) || "Senhor";
  document.getElementById("boot_ativo").checked = !!(d.boot && d.boot.ativo);
  document.getElementById("provedor_cerebro").value = (c.ia && c.ia.provedor_cerebro) || "ollama";
  document.getElementById("provedor_visao").value = (c.ia && c.ia.provedor_visao) || "ollama";
  document.getElementById("gemini_api_key").value = (c.ia && c.ia.gemini_api_key) || "";
  document.getElementById("claude_api_key").value = (c.ia && c.ia.claude_api_key) || "";
  document.getElementById("openai_api_key").value = (c.ia && c.ia.openai_api_key) || "";
  document.getElementById("cameras_modo").value = (c.cameras && c.cameras.modo) || "auto";
  document.getElementById("camera_ptz_rtsp").value = (c.cameras && c.cameras.camera_ptz_rtsp) || "";
  if (d.memoria) {
    document.getElementById("st_fatos").textContent = d.memoria.fatos_aprendidos || 0;
    document.getElementById("st_ep").textContent = d.memoria.episodios_aprendidos || 0;
    document.getElementById("st_lic").textContent = d.memoria.licoes_auto_reflexao || 0;
  }
}
async function postConfig(payload) {
  const r = await fetch("/api/config/salvar?t=" + encodeURIComponent(tok), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (r.ok) { aviso("Configuração aplicada com sucesso!"); carregar(); }
}
function salvarGeral() {
  postConfig({
    usuario: { nome: document.getElementById("usuario_nome").value.trim() || "Senhor" },
    boot: { iniciar_no_boot: document.getElementById("boot_ativo").checked },
    onboarding_concluido: true
  });
}
function salvarIA() {
  postConfig({
    ia: {
      provedor_cerebro: document.getElementById("provedor_cerebro").value,
      provedor_visao: document.getElementById("provedor_visao").value,
      gemini_api_key: document.getElementById("gemini_api_key").value.trim(),
      claude_api_key: document.getElementById("claude_api_key").value.trim(),
      openai_api_key: document.getElementById("openai_api_key").value.trim()
    }
  });
}
function salvarCameras() {
  postConfig({
    cameras: {
      modo: document.getElementById("cameras_modo").value,
      camera_ptz_rtsp: document.getElementById("camera_ptz_rtsp").value.trim()
    }
  });
}
async function resetarMemoria() {
  if (!confirm("Tem certeza? Isso apagará todos os fatos, conversas e episódios atuais para a F.R.I.D.A.Y. começar a aprender do zero.")) return;
  const nome = document.getElementById("usuario_nome").value.trim() || "Senhor";
  const r = await fetch("/api/config/reset_memoria?t=" + encodeURIComponent(tok), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ nome })
  });
  if (r.ok) { aviso("Memória zerada! Aprendizado do zero iniciado."); carregar(); }
}
carregar();
</script>
</body>
</html>
"""


def obter_status_completo():
    """Retorna dicionário completo com estado de configuração, câmeras, boot, dependências, privacidade e memória."""
    import privacy_guard
    import auto_deps
    cfg = MZ.carregar_config()
    cams = CM.detectar_cameras_fisicas()
    return {
        "ok": True,
        "organizacao": "Integra Code",
        "config": cfg,
        "boot": status_boot(),
        "cameras": cams,
        "cameras_detectadas": cams,
        "memoria": MZ.status_memoria(),
        "privacidade": privacy_guard.auditar_privacidade_instalacao(),
        "dependencias": auto_deps.relatorio_completo(),
        "hostname": socket.gethostname()
    }


def aplicar_atualizacao_config(dados: dict, dry_run_boot: bool = False):
    """Aplica mudanças vindas da interface Web ou CLI."""
    if "boot" in dados and "iniciar_no_boot" in dados["boot"]:
        configurar_boot(bool(dados["boot"]["iniciar_no_boot"]), dry_run=dry_run_boot)
    nova = MZ.salvar_config(dados)
    if dados.get("onboarding_concluido"):
        MZ.concluir_onboarding(
            nome_usuario=nova.get("usuario", {}).get("nome", "Senhor"),
            provedor_ia=nova.get("ia", {}).get("provedor_cerebro", "ollama"),
            modo_cameras=nova.get("cameras", {}).get("modo", "auto")
        )
    return obter_status_completo()


# Handlers HTTP para aiohttp (remoto.py)
async def handle_config_page(req):
    from aiohttp import web
    return web.Response(text=HTML_PAINEL_CONFIG, content_type="text/html")


async def handle_config_status(req):
    from aiohttp import web
    return web.json_response(obter_status_completo())


async def handle_config_salvar(req):
    from aiohttp import web
    try:
        dados = await req.json()
    except Exception:
        return web.json_response({"ok": False, "erro": "JSON inválido"}, status=400)
    res = aplicar_atualizacao_config(dados)
    return web.json_response(res)


async def handle_config_reset_memoria(req):
    from aiohttp import web
    try:
        dados = await req.json()
    except Exception:
        dados = {}
    nome = str(dados.get("nome") or "Senhor").strip() or "Senhor"
    res = MZ.inicializar_do_zero(forcar=True, nome_usuario=nome, manter_config_ia=True)
    return web.json_response(res)


def main_cli():
    parser = argparse.ArgumentParser(description="Central de Configuração da F.R.I.D.A.Y. Commercial Edition (Integra Code)")
    parser.add_argument("--status", action="store_true", help="Exibe o status completo de configuração, câmeras e memória")
    parser.add_argument("--nome", type=str, help="Define o nome do usuário principal")
    parser.add_argument("--boot", choices=["on", "off"], help="Ativa ou desativa a inicialização automática no boot")
    parser.add_argument("--provider", choices=["ollama", "gemini", "claude", "openai", "auto"], help="Define o provedor de IA e Visão")
    parser.add_argument("--vision-provider", choices=["ollama", "gemini", "claude", "openai", "auto"], help="Define apenas o provedor de Visão")
    parser.add_argument("--api-key", type=str, help="Configura a chave de API do provedor selecionado em --provider")
    parser.add_argument("--gemini-key", type=str, help="Configura a chave de API do Google Gemini")
    parser.add_argument("--claude-key", type=str, help="Configura a chave de API do Anthropic Claude")
    parser.add_argument("--openai-key", type=str, help="Configura a chave de API da OpenAI (GPT)")
    parser.add_argument("--cameras", choices=["auto", "sem_camera", "1_camera", "2_cameras", "3_cameras_ptz"], help="Define o modo de câmeras")
    parser.add_argument("--reset-memory", action="store_true", help="Limpa o banco de dados e reinicia o aprendizado do zero")
    parser.add_argument("--install-deps", action="store_true", help="Verifica e instala automaticamente todas as dependências")
    parser.add_argument("--terms", action="store_true", help="Exibe os Termos de Uso e Garantia Zero-Telemetry da Integra Code")
    parser.add_argument("--gui", action="store_true", help="Abre a Central de Configuração no navegador")
    args = parser.parse_args()

    if args.terms:
        import privacy_guard
        print(json.dumps(privacy_guard.auditar_privacidade_instalacao(), indent=2, ensure_ascii=False))
        return

    if args.install_deps:
        import auto_deps
        print(json.dumps(auto_deps.bootstrap_completo(), indent=2, ensure_ascii=False))
        return

    alterou = {}
    if args.nome:
        alterou.setdefault("usuario", {})["nome"] = args.nome
        alterou["onboarding_concluido"] = True
    if args.boot:
        alterou.setdefault("boot", {})["iniciar_no_boot"] = (args.boot == "on")
    if args.provider:
        alterou.setdefault("ia", {})["provedor_cerebro"] = args.provider
        alterou.setdefault("ia", {})["provedor_visao"] = args.provider
        if args.api_key is not None and args.provider in ("gemini", "claude", "openai"):
            alterou.setdefault("ia", {})[f"{args.provider}_api_key"] = args.api_key
    if args.vision_provider:
        alterou.setdefault("ia", {})["provedor_visao"] = args.vision_provider
    if args.gemini_key is not None:
        alterou.setdefault("ia", {})["gemini_api_key"] = args.gemini_key
    if args.claude_key is not None:
        alterou.setdefault("ia", {})["claude_api_key"] = args.claude_key
    if args.openai_key is not None:
        alterou.setdefault("ia", {})["openai_api_key"] = args.openai_key
    if args.cameras:
        alterou.setdefault("cameras", {})["modo"] = args.cameras

    if alterou:
        aplicar_atualizacao_config(alterou)

    if args.reset_memory:
        nome_u = args.nome or MZ.carregar_config().get("usuario", {}).get("nome", "Senhor")
        MZ.inicializar_do_zero(forcar=True, nome_usuario=nome_u, manter_config_ia=True)

    if args.gui:
        tok = ""
        try:
            with open(os.path.join(ROOT, "memory", "remoto.json")) as f:
                tok = json.load(f).get("token", "")
        except Exception:
            pass
        url = f"http://127.0.0.1:8790/config?t={tok}"
        print(f"Abrindo Central de Configuração: {url}")
        webbrowser.open(url)
        return

    print(json.dumps(obter_status_completo(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main_cli()
