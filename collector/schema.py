"""Nuestro formato JSON (v0): el contrato entre el Mac y el móvil."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = 0


@dataclass
class Window:
    """Una ventana de límite: cuánto llevo usado y cuándo se resetea."""

    id: str                      # "5h", "7d", "7d_opus"…
    label: str                   # texto para enseñar
    used_pct: float | None       # 0–100
    resets_at: str | None        # ISO 8601 en UTC


@dataclass
class ProviderResult:
    id: str
    status: str = "ok"           # "ok" | "error"
    error: str | None = None
    windows: list[Window] = field(default_factory=list)

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
