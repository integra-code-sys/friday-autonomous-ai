#!/usr/bin/env bash
# Inicializador da F.R.I.D.A.Y. Commercial Edition — Integra Code (Linux)
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
    PY="python3"
fi

# Auto-verificação de dependências, modelos ONNX e banco de dados Zero-State
"$PY" "$ROOT/daemon/auto_deps.py" >/dev/null 2>&1 || true

echo "Iniciando F.R.I.D.A.Y. Commercial Edition (Integra Code)..."
echo "Painel de Configuração Web: http://127.0.0.1:8790/config"

if command -v quickshell >/dev/null 2>&1 && [ -f "$ROOT/shell/shell.qml" ]; then
    quickshell -p "$ROOT/shell/shell.qml" >/dev/null 2>&1 &
fi

exec "$PY" "$ROOT/daemon/prometheus.py" "$@"
