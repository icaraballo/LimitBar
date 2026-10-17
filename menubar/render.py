"""Pinta data/latest.json en el formato de SwiftBar (https://github.com/swiftbar/SwiftBar).

La barra no sabe nada de cada IA: recorre los proveedores y ventanas del JSON v0, así que un
proveedor o una ventana nuevos aparecen solos.

Formato SwiftBar: la primera línea es el título de la barra; tras «---», el menú. Cada línea
admite parámetros después de «|» (color, font, bash…).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data" / "latest.json"
COLLECT = REPO / "scripts" / "collect.sh"

NAMES = {"claude": "Claude", "gemini": "Gemini", "antigravity": "Antigravity",
         "chatgpt": "ChatGPT", "grok": "Grok", "deepseek": "DeepSeek", "muse": "Muse"}
STALE_MIN = 45          # más de 2 rondas sin datos → aviso
MONO = "font=Menlo size=12"


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _color(pct: float) -> str:
    if pct >= 90:
        return "#e5484d"    # rojo
    if pct >= 70:
        return "#f5a524"    # ámbar
    return ""


def _bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _ago(minutes: float) -> str:
    if minutes < 1:
        return "ahora mismo"
    if minutes < 60:
        return f"hace {int(minutes)} min"
    h = int(minutes // 60)
    return f"hace {h} h {int(minutes % 60)} min"


def _until(dt: datetime, now: datetime) -> str:
    mins = (dt - now).total_seconds() / 60
    if mins <= 0:
        return "ya"
    if mins < 60:
        return f"en {int(mins)} min"
    h, m = divmod(int(mins), 60)
    if h < 24:
        return f"en {h} h {m:02d}"
    return f"en {h // 24} d {h % 24} h"


def _reset_label(iso: str | None, now: datetime) -> str:
    dt = _parse(iso)
    if dt is None:
        return ""
    local = dt.astimezone()
    days = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    same_day = local.date() == now.astimezone().date()
    when = local.strftime("%H:%M") if same_day else f"{days[local.weekday()]} {local:%H:%M}"
    return f"reset {when} ({_until(dt, now)})"


def render(data: dict | None, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines: list[str] = []
    refresh = f"Actualizar ahora | bash={COLLECT} terminal=false refresh=true"

    if data is None:
        return "\n".join(["LB ?", "---", "Sin datos todavía", refresh])

    # Título: la ventana más gastada de todas, que es la que manda.
    worst = None
    for p in data.get("providers", []):
        for w in p.get("windows", []) if p.get("status") == "ok" else []:
            if w.get("used_pct") is not None and (worst is None or w["used_pct"] > worst["used_pct"]):
                worst = w
    collected = _parse(data.get("collected_at"))
    age = (now - collected).total_seconds() / 60 if collected else None
    stale = age is None or age > STALE_MIN

    if worst is None:
        title = "LB ✗"
    else:
        title = f"{worst['used_pct']:.0f}%"
    params = ["sfimage=gauge.with.dots.needle.33percent"]
    if worst is not None and _color(worst["used_pct"]):
        params.append(f"color={_color(worst['used_pct'])}")
    if stale:
        title += " ⏸"
    lines += [f"{title} | {' '.join(params)}", "---"]

    for p in data.get("providers", []):
        name = NAMES.get(p["id"], p["id"].capitalize())
        lines.append(f"{name} | size=13")
        if p.get("status") != "ok":
            lines.append(f"✗ {p.get('error') or 'Error'} | color=#e5484d")
            lines.append("---")
            continue
        for w in p.get("windows", []):
            pct = w.get("used_pct")
            if pct is None:
                lines.append(f"{w['label']:<16} sin dato | {MONO} color=#888888")
                continue
            color = _color(pct)
            extra = f" color={color}" if color else ""
            lines.append(f"{w['label']:<16} {_bar(pct)} {pct:3.0f}% | {MONO}{extra}")
            reset = _reset_label(w.get("resets_at"), now)
            if reset:
                lines.append(f"{'':<16} {reset} | font=Menlo size=11 color=#888888")
        lines.append("---")

    if age is None:
        lines.append("Sin hora de actualización | color=#888888")
    else:
        warn = " · ¿el Mac estuvo apagado?" if stale else ""
        lines.append(f"Actualizado {_ago(age)}{warn} | color=#888888")
    lines.append(refresh)
    return "\n".join(lines)


def load() -> dict | None:
    try:
        return json.loads(DATA.read_text())
    except (OSError, ValueError):
        return None


def main() -> None:
    print(render(load()))


if __name__ == "__main__":
    main()
