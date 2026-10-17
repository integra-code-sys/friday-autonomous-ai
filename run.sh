#!/bin/sh
# Inicia o daemon (usa .venv p/ câmera) e o rosto como wallpaper (camada Bottom). Chamado pelo niri (spawn-at-startup).
# Acesso total do claude (opt-in): PROMETHEUS_PERMISSION=bypassPermissions ./run.sh
D="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/prometheus-run.lock"
exec 9>"$LOCK"; flock -n 9 || exit 0            # evita instância duplicada
# espera o compositor (socket Wayland) estar pronto
for i in $(seq 1 60); do
    [ -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY:-wayland-1}" ] && break
    sleep 0.5
done
# cada serviço no PRÓPRIO grupo do systemd: se o oomd matar outro app (IDE, navegador...), a Friday não cai junto.
# (2026-10-14: o oomd matou o grupo do Antigravity e levou Ollama/daemon/voz, que tinham sido iniciados de dentro dele)
# serviço do systemd com Restart=always: o oomd mata o GRUPO inteiro (um laço "while" dentro dele morreria junto),
# então quem religa é o systemd, de fora. Herda o ambiente gráfico (Wayland/DBus) desta sessão.
# propriedades extras vão ANTES do comando: servico u log -p MemoryMax=5G ... comando (o systemd-run lê até o 1º não-opção)
servico() { u="$1"; log="$2"; shift 2
    systemctl --user reset-failed "$u.service" 2>/dev/null
    systemd-run --user --quiet --collect --unit="$u" -p Restart=always -p RestartSec=2 -p WorkingDirectory="$D" \
        -p StandardOutput="append:$log" -p StandardError="append:$log" \
        -E PATH -E HOME -E XDG_RUNTIME_DIR -E WAYLAND_DISPLAY -E DISPLAY -E DBUS_SESSION_BUS_ADDRESS -E XDG_CURRENT_DESKTOP -E NIRI_SOCKET "$@"; }
# VLM local (descrição da cena): Ollama só em 127.0.0.1
# se o oomd (ou um travamento) derrubar o Ollama, o systemd o religa em 2 s (sem ele ela "não consegue processar")
# F4 (16 GB/6 GB): 1 slot, KV q8_0 (exige flash attention), ctx 4096; LLAMA_ARG_CACHE_RAM=0 desliga o cache de
# prompts na RAM do llama-server (padrão 8 GB: chegou a 3,2 GB RSS + 6 GB swap). MemoryHigh/Max seguram o resto do PC;
# CACHE_RAM=1536: guarda o prompt do cérebro (~4,6 mil tokens) em RAM, com teto; chamadas de visão no meio não o obrigam a reprocessar tudo.
# FIT_TARGET=320: margem de VRAM livre do llama.cpp (padrão ~1,8 GB deixava o 8B com 22/37 camadas na GPU e 2,1 GB ociosos).
# Memória 6G/9G: modelos maiores (8B+, MoE tipo gpt-oss) precisam de RAM p/ as camadas que não cabem na GPU.
# OOMScoreAdjust=100 é o mínimo que o systemd --user aceita (padrão 200)
pgrep -x ollama >/dev/null || servico friday-ollama /tmp/friday-ollama.log -p MemoryHigh=6G -p MemoryMax=9G -p OOMScoreAdjust=100 \
    env OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_CONTEXT_LENGTH=4096 \
    OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 LLAMA_ARG_CACHE_RAM=1536 LLAMA_ARG_FIT_TARGET=320 OLLAMA_KEEP_ALIVE=-1 "$(command -v ollama)" serve
# ZapZap com o depurador local (comandos remotos por WhatsApp): sobe junto, em segundo plano
( sleep 20; "$D/.venv/bin/python" "$D/daemon/zap.py" launch >/dev/null 2>&1 ) &
# microfone limpo (eco/ruído cancelados no PipeWire, WebRTC): fonte friday_mic usada pelo daemon
"$D/daemon/audio/microfone" iniciar >/dev/null 2>&1 &
# voz da F.R.I.D.A.Y. (Kyutai Pocket TTS, CPU) supervisionada; sem ela o daemon usa a voz Piper
if grep -q '"tts_motor": *"supertonic"' "$D/memory/voz.json" 2>/dev/null; then     # voz Supertonic 3 F1 (16/10/2026)
    [ -x "$D/.venv-st/bin/python" ] && servico friday-tts /tmp/friday-tts.log "$D/.venv-st/bin/python" "$D/daemon/tts_supertonic.py"
else
    [ -x "$D/.venv-tts/bin/python" ] && servico friday-tts /tmp/friday-tts.log "$D/.venv-tts/bin/python" "$D/daemon/tts_pocket.py"
fi
# STT (Whisper) em processo próprio, nos núcleos P: dentro do daemon o GIL deixava cada frase ~5,9 s; aqui ~3,4 s (17/10/2026).
# Atende o microfone do PC e o celular (/api/stt). MemoryLow: o modelo não vai para o zram.
grep -q '"stt": *"whisper"' "$D/memory/voz.json" 2>/dev/null && \
    servico friday-stt /tmp/friday-stt.log -p MemoryLow=2G "$D/.venv/bin/python" "$D/daemon/stt_servidor.py"
# ydotool (injeção de eventos de mouse e gestos para modo mão livre): garante ativo
systemctl --user is-active --quiet ydotool 2>/dev/null || systemctl --user start ydotool 2>/dev/null || true
# daemon supervisionado: reinicia se cair. MemoryLow=3G (16/10): sem ele o Whisper ia p/ o zram (swappiness 150) e cada frase levava 9-11 s em vez de ~4 s
servico friday-daemon /tmp/prometheus-daemon.log -p KillMode=mixed -p TimeoutStopSec=8 -p MemoryLow=3G "$D/.venv/bin/python" -X faulthandler "$D/daemon/prometheus.py"
# rosto: reinicia se o quickshell cair (ex.: shell ainda subindo no boot) (na iGPU Intel: /etc/environment força NVIDIA p/ tudo)
while :; do env -u __NV_PRIME_RENDER_OFFLOAD -u __GLX_VENDOR_LIBRARY_NAME -u __VK_LAYER_NV_optimus DRI_PRIME=0 qs -p "$D/shell/shell.qml"; sleep 2; done
