#!/usr/bin/env bash
# Instalador Rápido do App Android F.R.I.D.A.Y. Commercial Edition
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$DIR")"
APK="$DIR/friday-commercial.apk"

echo "================================================================"
echo " 📱 F.R.I.D.A.Y. Commercial Edition — Instalador Android"
echo "================================================================"

if [ ! -f "$APK" ]; then
    echo "Compilando APK comercial..."
    sh "$DIR/build.sh"
fi

# Descobre IP e Token para pareamento
IP_LOCAL=$(hostname -I 2>/dev/null | awk '{print $1}')
TOKEN=""
if [ -f "$ROOT/memory/remoto.json" ]; then
    TOKEN=$(python3 -c "import json; print(json.load(open('$ROOT/memory/remoto.json')).get('token',''))" 2>/dev/null || true)
fi

if command -v adb >/dev/null 2>&1 && adb devices | grep -q "device$"; then
    echo "✔ Celular Android detectado via ADB! Instalando friday-commercial.apk..."
    adb install -r "$APK"
    echo "✔ App instalado com sucesso no Android!"
else
    echo "ℹ Nenhum celular conectado por cabo USB (ADB)."
    echo "Você pode instalar diretamente pelo navegador do celular acessando:"
    echo ""
    echo "   👉 http://${IP_LOCAL:-SEU_IP_DO_PC}:8790/download/friday-commercial.apk"
    echo ""
fi

echo "----------------------------------------------------------------"
echo " 🔗 DADOS DE PAREAMENTO PARA O APP ANDROID:"
echo "    Servidor (IP:Porta) : ${IP_LOCAL:-127.0.0.1}:8790"
echo "    Token de Acesso     : ${TOKEN:-(Inicie a Friday no PC para gerar)}"
echo "================================================================"
