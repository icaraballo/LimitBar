"""Ejecuta todos los proveedores, enseña el resultado y lo guarda en data/latest.json.

Uso: python3 -m collector.main
"""

from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

from collector.providers.base import Provider, ProviderError
from collector.providers.claude import ClaudeProvider
from collector.schema import ProviderResult, Snapshot, utc_now_iso

PROVIDERS: list[Provider] = [ClaudeProvider()]
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "latest.json"


def run_provider(provider: Provider) -> ProviderResult:
    """Un proveedor que falla no rompe el resto."""
    try:
        return provider.fetch()
    except ProviderError as e:
        return ProviderResult.failed(provider.id, str(e))
    except Exception as e:  # noqa: BLE001 — cualquier fallo inesperado queda aislado
        return ProviderResult.failed(provider.id, f"Error inesperado: {type(e).__name__}")


def collect(providers: list[Provider] = PROVIDERS) -> Snapshot:
    device = socket.gethostname().split(".")[0].lower() or "mac"
    return Snapshot(
        collected_at=utc_now_iso(),
        source_device=device,
        providers=[run_provider(p) for p in providers],
    )


def _local(iso: str | None) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    return dt.strftime("%a %d %H:%M")


def render(snapshot: Snapshot) -> str:
    lines = [f"LimitBar · {_local(snapshot.collected_at)}"]
    for p in snapshot.providers:
        if p.status != "ok":
            lines.append(f"  {p.id:<8} ✗ {p.error}")
            continue
        lines.append(f"  {p.id}")
        for w in p.windows:
            if w.used_pct is None:
                lines.append(f"    {w.label:<18}  sin dato")
                continue
            filled = round(w.used_pct / 10)
            bar = "█" * filled + "░" * (10 - filled)
            lines.append(f"    {w.label:<18} {bar} {w.used_pct:5.1f} %  · reset {_local(w.resets_at)}")
    return "\n".join(lines)


def main() -> None:
    snapshot = collect()
    print(render(snapshot))
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2) + "\n")
    print(f"\nGuardado en {OUTPUT.relative_to(OUTPUT.parent.parent)}")


if __name__ == "__main__":
    main()
