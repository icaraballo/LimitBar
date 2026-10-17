"""Cuenta tokens y coste equivalente del uso de Claude Code, leyendo sus logs locales.

Claude Code guarda un JSONL por sesión en ~/.claude/projects/*/. Cada mensaje del asistente trae
`message.model` y `message.usage` (entrada, salida, creación y lectura de caché). Sumamos por
modelo en una ventana de días y le ponemos precio con la tabla de prices.py.

Es local: no toca credenciales ni red. Solo mide Claude Code (no los chats ni Cowork de la web).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collector import prices
from collector.schema import Cost, ModelCost

LOGS = Path.home() / ".claude" / "projects"


def _accumulate(records: dict, model: str, u: dict) -> None:
    acc = records.setdefault(model, {"input": 0, "output": 0, "cw5m": 0, "cw1h": 0, "read": 0})
    acc["input"] += u.get("input_tokens", 0) or 0
    acc["output"] += u.get("output_tokens", 0) or 0
    acc["read"] += u.get("cache_read_input_tokens", 0) or 0
    cc = u.get("cache_creation") or {}
    cw5m = cc.get("ephemeral_5m_input_tokens")
    cw1h = cc.get("ephemeral_1h_input_tokens")
    if cw5m is None and cw1h is None:   # logs viejos: solo el total, lo tratamos como 5 min
        acc["cw5m"] += u.get("cache_creation_input_tokens", 0) or 0
    else:
        acc["cw5m"] += cw5m or 0
        acc["cw1h"] += cw1h or 0


def scan(window_days: int = 7, now: datetime | None = None, root: Path = LOGS) -> dict:
    """Suma de tokens por modelo en los últimos `window_days` días. Deduplica por id de mensaje."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    records: dict[str, dict] = {}
    seen: set[str] = set()
    for path in root.glob("*/*.jsonl"):
        try:
            with path.open() as f:
                for line in f:
                    if '"usage"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("type") != "assistant":
                        continue
                    ts = d.get("timestamp")
                    if ts:
                        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if when < since:
                            continue
                    msg = d.get("message") or {}
                    model = msg.get("model")
                    usage = msg.get("usage")
                    if not model or model == "<synthetic>" or not isinstance(usage, dict):
                        continue
                    mid = msg.get("id")
                    if mid and mid in seen:
                        continue
                    if mid:
                        seen.add(mid)
                    _accumulate(records, model, usage)
        except OSError:
            continue
    return records


def read_cost(window_days: int = 7, now: datetime | None = None, root: Path = LOGS) -> Cost:
    records = scan(window_days, now, root)
    models = []
    for model, a in records.items():
        usd = prices.cost_usd(model, a["input"], a["output"], a["cw5m"], a["cw1h"], a["read"])
        models.append(ModelCost(
            model=prices.normalize(model),
            label=prices.label(model),
            input=a["input"],
            output=a["output"],
            cache_write=a["cw5m"] + a["cw1h"],
            cache_read=a["read"],
            cost_usd=round(usd, 2) if usd is not None else None,
        ))
    models.sort(key=lambda m: m.cost_usd or 0, reverse=True)
    priced = round(sum(m.cost_usd for m in models if m.cost_usd is not None), 2)
    return Cost(window_days=window_days, priced_usd=priced, models=models, prices_revised=prices.REVISED)
