#!/bin/sh
# Instala o quita el recolector como agente de launchd (se ejecuta solo cada 20 min).
#   scripts/launchd.sh install    instala (o reinstala) y lanza una ronda ya
#   scripts/launchd.sh uninstall  lo quita
#   scripts/launchd.sh status     ¿está cargado? y últimas líneas del log
set -eu

LABEL="com.icaraballo.limitbar"
INTERVAL=1200   # segundos
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-/opt/homebrew/bin/python3}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/LimitBar/collector.log"
DOMAIN="gui/$(id -u)"

case "${1:-}" in
  install)
    mkdir -p "$(dirname "$LOG")" "$(dirname "$PLIST")"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string><string>-m</string><string>collector.main</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "Instalado: cada $((INTERVAL / 60)) min. Log: $LOG"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Quitado."
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E 'state|last exit code|run interval' || echo "No está cargado."
    [ -f "$LOG" ] && tail -n 8 "$LOG"
    ;;
  *)
    echo "Uso: $0 install|uninstall|status" >&2
    exit 2
    ;;
esac
