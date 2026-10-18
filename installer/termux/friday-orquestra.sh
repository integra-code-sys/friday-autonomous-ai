#!/data/data/com.termux/files/usr/bin/bash
# F.R.I.D.A.Y. no celular (Termux): orquestrador sempre ligado.
# Religa o orquestrador 15 s depois de qualquer queda; uma instância só (flock; sem flock, pidfile).
# Log: ~/dev/Friday/memory/orquestra.log (gira para orquestra.log.1 acima de 5 MB).
#
# Uso:
#   bash friday-orquestra.sh                 # roda em primeiro plano (Ctrl+C para)
#   bash friday-orquestra.sh instalar-boot   # cria ~/.termux/boot/friday-orquestra (sobe sozinho no boot)
#   bash friday-orquestra.sh parar           # derruba a instância que estiver rodando
#   FRIDAY_DIR=/outro/caminho PYTHON=python3 bash friday-orquestra.sh
#
# Termux:Boot: instale o app Termux:Boot (MESMA origem do Termux: F-Droid ou GitHub), abra-o uma vez e rode
# 'bash friday-orquestra.sh instalar-boot'. Equivale a criar ~/.termux/boot/friday-orquestra com:
#   #!/data/data/com.termux/files/usr/bin/sh
#   termux-wake-lock
#   exec bash ~/dev/Friday/installer/termux/friday-orquestra.sh >/dev/null 2>&1
# e dar 'chmod +x' nele. O termux-wake-lock evita que o Android congele/mate o processo em segundo plano.
set -u
FRIDAY_DIR="${FRIDAY_DIR:-$HOME/dev/Friday}"
MEM="$FRIDAY_DIR/memory"
LOG="$MEM/orquestra.log"
PIDF="$MEM/orquestra.pid"
LOCK="$MEM/orquestra.lock"
PY="${PYTHON:-python}"
SCRIPT="$(readlink -f "$0" 2>/dev/null || echo "$0")"

log() { printf '%s [friday-orquestra] %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

rodando() {  # imprime o PID da instância viva (confere o cmdline: PID reaproveitado após reboot não conta)
    p="$(cat "$PIDF" 2>/dev/null)" || return 1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null && grep -aq friday-orquestra "/proc/$p/cmdline" 2>/dev/null && echo "$p"
}

case "${1:-}" in
    instalar-boot)
        mkdir -p "$HOME/.termux/boot"
        B="$HOME/.termux/boot/friday-orquestra"
        printf '#!/data/data/com.termux/files/usr/bin/sh\n# sobe o orquestrador da Friday no boot (Termux:Boot)\ntermux-wake-lock\nexec bash "%s" >/dev/null 2>&1\n' "$SCRIPT" >"$B"
        chmod +x "$B"
        echo "ok: $B"
        exit 0 ;;
    parar)
        p="$(rodando)" || { echo "não está rodando"; exit 0; }
        kill "$p" && echo "parado (PID $p)"
        exit 0 ;;
    "") ;;
    *)
        echo "uso: $0 [instalar-boot|parar]" >&2
        exit 2 ;;
esac

[ -f "$FRIDAY_DIR/daemon/orquestra_geral.py" ] || { echo "não achei $FRIDAY_DIR/daemon/orquestra_geral.py (defina FRIDAY_DIR)" >&2; exit 1; }
mkdir -p "$MEM" || exit 1

# uma instância só
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK"
    flock -n 9 || { echo "já está rodando"; exit 0; }
elif p="$(rodando)"; then
    echo "já está rodando (PID $p)"
    exit 0
fi
echo $$ >"$PIDF"

filho=""
sair() {
    trap - INT TERM HUP
    [ -n "$filho" ] && kill "$filho" 2>/dev/null && wait "$filho" 2>/dev/null
    log "supervisor parado"
    [ "$(cat "$PIDF" 2>/dev/null)" = "$$" ] && rm -f "$PIDF"
    exit 0
}
trap sair INT TERM HUP

cd "$FRIDAY_DIR" || exit 1
log "supervisor iniciado (PID $$, python: $PY)"
while :; do
    [ "$(wc -c 2>/dev/null <"$LOG" || echo 0)" -gt 5000000 ] && mv -f "$LOG" "$LOG.1"
    log "iniciando orquestrador"
    # 'orquestra_geral.py run --sempre' sem sessão imprime "falta o pedido" e sai com 2: chama o laço ocioso direto
    "$PY" -u -c 'import sys; sys.path.insert(0, "daemon"); import orquestra_geral as o; o.loop(sempre=True)' >>"$LOG" 2>&1 &
    filho=$!
    wait "$filho"
    rc=$?
    filho=""
    log "orquestrador saiu (código $rc); religando em 15 s"
    sleep 15 &
    wait $!
done
