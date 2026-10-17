#!/usr/bin/env bash
# ==============================================================================
# 🚀 F.R.I.D.A.Y. Commercial Edition — Instalador Automático (Integra Code)
# Suporta: Arch/Manjaro, Ubuntu/Debian/Mint/Pop!_OS, Fedora
# ==============================================================================
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=================================================================="
echo " 🤖 F.R.I.D.A.Y. (Projeto Prometheus) — Integra Code Edition"
echo "    Instalador Automático de Dependências, Modelos e Banco Limpo"
echo "=================================================================="

# 1. Dependências do sistema
if command -v pacman >/dev/null 2>&1; then
    echo "[1/5] Verificando pacotes base do sistema (Arch/Manjaro)..."
    sudo pacman -S --needed --noconfirm python python-virtualenv ffmpeg curl grim wl-clipboard >/dev/null 2>&1 || true
elif command -v apt-get >/dev/null 2>&1; then
    echo "[1/5] Verificando pacotes base do sistema (Ubuntu/Debian)..."
    sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv python3-pip ffmpeg curl grim wl-clipboard >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then
    echo "[1/5] Verificando pacotes base do sistema (Fedora)..."
    sudo dnf install -y python3 python3-pip ffmpeg curl grim wl-clipboard >/dev/null 2>&1 || true
fi

# 2. Ambiente Virtual Python (.venv)
echo "[2/5] Configurando ambiente virtual Python (.venv)..."
if [ ! -d "$ROOT/.venv" ]; then
    python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/pip" install --upgrade pip -q
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt" -q

# 3. Auto-Instalador de Dependências, Modelos ONNX e Memória Zero-State
echo "[3/5] Executando Auto-Instalador de Dependências e Modelos (auto_deps.py)..."
"$ROOT/.venv/bin/python" "$ROOT/daemon/auto_deps.py" --install-all --dry-run >/dev/null
"$ROOT/.venv/bin/python" "$ROOT/daemon/auto_deps.py"

# 4. Auditoria de Privacidade Zero-Telemetry (Integra Code)
echo "[4/5] Verificando Garantia de Privacidade Zero-Telemetry (Integra Code)..."
"$ROOT/.venv/bin/python" "$ROOT/daemon/privacy_guard.py" >/dev/null

# 5. Atalhos e Permissões
echo "[5/5] Configurando executáveis (run.sh e friday-config)..."
chmod +x "$ROOT/run.sh" "$ROOT/friday-config" "$ROOT/android/install_android.sh" 2>/dev/null || true

echo "=================================================================="
echo " ✅ INSTALAÇÃO INTEGRA CODE CONCLUÍDA COM SUCESSO!"
echo "------------------------------------------------------------------"
echo " ▶ Iniciar a F.R.I.D.A.Y.          : ./run.sh"
echo " ▶ Abrir Central de Configuração   : ./friday-config --gui"
echo " ▶ Ativar inicialização no Boot    : ./friday-config --boot on"
echo " ▶ Ver Termos e Privacidade        : ./friday-config --terms"
echo "=================================================================="
