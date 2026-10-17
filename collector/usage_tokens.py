"""Cuenta tokens y coste equivalente de Claude Code y Antigravity, leyendo sus logs locales.

Claude Code guarda un JSONL por sesión en ~/.claude/projects/*/. Cada mensaje del asistente trae
`message.model` y `message.usage` (entrada, salida, creación y lectura de caché). Sumamos por
modelo en una ventana de días y le ponemos precio con la tabla de prices.py.

Antigravity (IDE y CLI) deja un transcript.jsonl por conversación en ~/.gemini/antigravity*/brain/:
cada respuesta trae sus tokens, pero no el modelo; el modelo sale del aviso «Model Selection» que
Antigravity mete en los mensajes del usuario al elegirlo o cambiarlo.

Es local: no toca credenciales ni red. No mide los chats ni Cowork de la web de Claude.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from collector import prices
from collector.schema import Cost, CostPeriod, ModelCost

LOGS = Path.home() / ".claude" / "projects"
ANTIGRAVITY_LOGS = (
    Path.home() / ".gemini" / "antigravity" / "brain",
    Path.home() / ".gemini" / "antigravity-cli" / "brain",
)
DAILY_HISTORY = Path(__file__).resolve().parent.parent / "data" / "cost_daily.json"
UNKNOWN_MODEL = "desconocido"   # sin precio: mejor «sin precio» que atribuir a otro modelo
# «…`Model Selection` from None to Gemini 3.8 Flash (High). No need to comment…»: el nombre lleva
# puntos, así que se corta en el «. No need» que cierra el aviso, no en el primer punto.
_MODEL_CHANGE_RE = re.compile(r"Model Selection` from .+? to (.+?)\.\s+No need")
MONTH_NAMES = ("", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")


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


def _local_day(ts: str) -> str | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date().isoformat()
    except ValueError:
        return None


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


def scan_daily(root: Path = LOGS) -> dict[str, dict[str, dict]]:
    """Suma de tokens por día local (YYYY-MM-DD) y modelo normalizado en todos los logs de Claude Code."""
    by_day: dict[str, dict[str, dict]] = {}
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
                    day = _local_day(ts) if ts else None
                    if not day:
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
                    _accumulate(by_day.setdefault(day, {}), prices.normalize(model), usage)
        except OSError:
            continue
    return by_day


def scan_antigravity(
    window_days: int = 7,
    now: datetime | None = None,
    roots: tuple[Path, ...] = ANTIGRAVITY_LOGS,
) -> dict:
    """Suma de tokens por modelo en los logs locales de Antigravity (IDE y CLI)."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    records: dict[str, dict] = {}
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*/.system_generated/logs/transcript.jsonl"):
            conv_id = path.parent.parent.parent.name
            model = UNKNOWN_MODEL   # hasta el aviso de «Model Selection» (suele ser el 1.er mensaje)
            try:
                with path.open() as f:
                    for line in f:
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        step_type = d.get("type")
                        if step_type == "USER_INPUT":
                            matches = _MODEL_CHANGE_RE.findall(d.get("content") or "")
                            if matches:
                                model = prices.normalize(matches[-1])
                            continue
                        if step_type != "PLANNER_RESPONSE":
                            continue
                        ts = d.get("created_at")
                        if ts:
                            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if when < since:
                                continue
                        step_idx = d.get("step_index")
                        dedup_key = f"{conv_id}:{step_idx}"
                        if step_idx is not None and dedup_key in seen:
                            continue
                        if step_idx is not None:
                            seen.add(dedup_key)
                        norm_model = prices.normalize(model)
                        acc = records.setdefault(
                            norm_model, {"input": 0, "output": 0, "cw5m": 0, "cw1h": 0, "read": 0}
                        )
                        acc["input"] += d.get("input_tokens", 0) or 0
                        acc["output"] += d.get("output_tokens", 0) or 0
                        acc["read"] += d.get("cache_read_tokens", 0) or 0
            except OSError:
                continue
    return records


def scan_antigravity_daily(roots: tuple[Path, ...] = ANTIGRAVITY_LOGS) -> dict[str, dict[str, dict]]:
    """Suma de tokens por día local (YYYY-MM-DD) y modelo en los logs de Antigravity."""
    by_day: dict[str, dict[str, dict]] = {}
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*/.system_generated/logs/transcript.jsonl"):
            conv_id = path.parent.parent.parent.name
            model = UNKNOWN_MODEL
            try:
                with path.open() as f:
                    for line in f:
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        step_type = d.get("type")
                        if step_type == "USER_INPUT":
                            matches = _MODEL_CHANGE_RE.findall(d.get("content") or "")
                            if matches:
                                model = prices.normalize(matches[-1])
                            continue
                        if step_type != "PLANNER_RESPONSE":
                            continue
                        ts = d.get("created_at")
                        day = _local_day(ts) if ts else None
                        if not day:
                            continue
                        step_idx = d.get("step_index")
                        dedup_key = f"{conv_id}:{step_idx}"
                        if step_idx is not None and dedup_key in seen:
                            continue
                        if step_idx is not None:
                            seen.add(dedup_key)
                        norm_model = prices.normalize(model)
                        acc = by_day.setdefault(day, {}).setdefault(
                            norm_model, {"input": 0, "output": 0, "cw5m": 0, "cw1h": 0, "read": 0}
                        )
                        acc["input"] += d.get("input_tokens", 0) or 0
                        acc["output"] += d.get("output_tokens", 0) or 0
                        acc["read"] += d.get("cache_read_tokens", 0) or 0
            except OSError:
                continue
    return by_day


def _merge_history(provider_id: str, scanned: dict[str, dict[str, dict]], history_file: Path | None) -> dict[str, dict[str, dict]]:
    """Mezcla lo escaneado con el histórico en disco (conservando días ya borrados de los logs)."""
    if history_file is None:
        return scanned
    all_hist: dict = {}
    if history_file.exists():
        try:
            all_hist = json.loads(history_file.read_text())
        except (OSError, ValueError):
            all_hist = {}
    prov_hist: dict[str, dict[str, dict]] = dict(all_hist.get(provider_id) or {})
    prov_hist.update(scanned)
    all_hist[provider_id] = dict(sorted(prov_hist.items()))
    try:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history_file.write_text(json.dumps(all_hist, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        pass
    return prov_hist


def _models_from_records(records: dict) -> tuple[list[ModelCost], float]:
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
    models.sort(key=lambda m: (m.cost_usd or 0, m.input + m.output + m.cache_read), reverse=True)
    priced = round(sum(m.cost_usd for m in models if m.cost_usd is not None), 2)
    return models, priced


def _sum_days(by_day: dict[str, dict[str, dict]], start_iso: str, end_iso: str) -> dict[str, dict]:
    totals: dict[str, dict] = {}
    for day, models in by_day.items():
        if start_iso <= day <= end_iso:
            for model, a in models.items():
                acc = totals.setdefault(model, {"input": 0, "output": 0, "cw5m": 0, "cw1h": 0, "read": 0})
                for k in ("input", "output", "cw5m", "cw1h", "read"):
                    acc[k] += a.get(k, 0) or 0
    return totals


def _build_periods(by_day: dict[str, dict[str, dict]], today: date) -> list[CostPeriod]:
    today_iso = today.isoformat()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    month_start = today.replace(day=1).isoformat()
    year_start = today.replace(month=1, day=1).isoformat()
    specs = [
        ("day", "Hoy", today_iso),
        ("week", "Esta semana", week_start),
        ("month", MONTH_NAMES[today.month], month_start),
        ("year", str(today.year), year_start),
    ]
    periods = []
    for pid, label, start_iso in specs:
        models, priced = _models_from_records(_sum_days(by_day, start_iso, today_iso))
        periods.append(CostPeriod(id=pid, label=label, priced_usd=priced, models=models))
    return periods


def _build_cost(window_days: int, records: dict, periods: list[CostPeriod] | None = None) -> Cost:
    models, priced = _models_from_records(records)
    return Cost(
        window_days=window_days,
        priced_usd=priced,
        models=models,
        prices_revised=prices.REVISED,
        periods=periods or [],
    )


def read_cost(
    window_days: int = 7,
    now: datetime | None = None,
    root: Path = LOGS,
    history_file: Path | None = None,
) -> Cost:
    use_hist = DAILY_HISTORY if (history_file is None and root == LOGS) else history_file
    today = (now or datetime.now(timezone.utc)).astimezone().date()
    by_day = _merge_history("claude", scan_daily(root), use_hist)
    return _build_cost(window_days, scan(window_days, now, root), _build_periods(by_day, today))


def read_antigravity_cost(
    window_days: int = 7,
    now: datetime | None = None,
    roots: tuple[Path, ...] = ANTIGRAVITY_LOGS,
    history_file: Path | None = None,
) -> Cost:
    use_hist = DAILY_HISTORY if (history_file is None and roots == ANTIGRAVITY_LOGS) else history_file
    today = (now or datetime.now(timezone.utc)).astimezone().date()
    by_day = _merge_history("antigravity", scan_antigravity_daily(roots), use_hist)
    return _build_cost(window_days, scan_antigravity(window_days, now, roots), _build_periods(by_day, today))
