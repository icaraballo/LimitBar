#!/bin/sh
# Una ronda del recolector desde cualquier sitio (lo usa «Actualizar ahora» de la barra).
cd "$(dirname "$0")/.." && exec /opt/homebrew/bin/python3 -m collector.main >> "$HOME/Library/Logs/LimitBar/collector.log" 2>&1
