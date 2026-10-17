"""Nuestro formato JSON (v0): el contrato entre el Mac y el móvil."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = 0


@dataclass
class Window:
    """Una ventana de límite: cuánto llevo usado y cuándo se resetea.

    `kind="credit"` es un saldo en dinero (p. ej. los créditos de la nube de Claude): además del
    % trae lo gastado y el tope, y `resets_at` es cuándo caduca. No cuenta como límite del plan.
    """

    id: str                      # "5h", "7d", "7d_opus"…
    label: str                   # texto para enseñar
    used_pct: float | None       # 0–100
    resets_at: str | None        # ISO 8601 en UTC
    kind: str = "limit"          # "limit" | "credit"
    used: float | None = None    # solo créditos: gastado
    limit: float | None = None   # solo créditos: tope
    currency: str | None = None  # solo créditos: "USD"…


@dataclass
class Share:
    """Una parte del uso (p. ej. cuánto del semanal se fue en Claude Code)."""

    id: str
    label: str
    pct: float


@dataclass
class ModelCost:
    """Tokens consumidos por un modelo y su coste equivalente en API (None si no hay precio)."""

    model: str
    label: str
    input: int
    output: int
    cache_write: int
    cache_read: int
    cost_usd: float | None


@dataclass
class CostPeriod:
    """Coste equivalente en un periodo natural (hoy, semana, mes, año)."""

    id: str                      # "day", "week", "month", "year"
    label: str                   # "Hoy", "Esta semana", "Octubre", "2026"
    priced_usd: float
    models: list[ModelCost] = field(default_factory=list)


@dataclass
class Cost:
    """Coste equivalente del uso medible (Claude Code y Antigravity), por modelo y por periodo."""

    window_days: int
    priced_usd: float            # suma de lo que sé valorar (semana por defecto)
    models: list[ModelCost] = field(default_factory=list)
    prices_revised: str | None = None
    periods: list[CostPeriod] = field(default_factory=list)


@dataclass
class ProviderResult:
    id: str
    status: str = "ok"           # "ok" | "error"
    error: str | None = None
    windows: list[Window] = field(default_factory=list)
    breakdown: list[Share] = field(default_factory=list)   # reparto del uso, si el proveedor lo da
    cost: Cost | None = None                               # coste equivalente (tokens medibles)

    @classmethod
    def failed(cls, provider_id: str, message: str) -> "ProviderResult":
        return cls(id=provider_id, status="error", error=message)


@dataclass
class Snapshot:
    collected_at: str
    source_device: str
    providers: list[ProviderResult]
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        # schema_version primero, para que se lea bien
        return {"schema_version": d.pop("schema_version"), **d}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
