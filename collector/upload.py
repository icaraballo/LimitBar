"""Sube un Snapshot a Supabase: upsert en latest_status e inserción en usage_history.

Credenciales: en el Llavero de macOS, nunca en el repo ni en la salida.
  security add-generic-password -a limitbar -s limitbar-supabase-url -w 'https://xxxx.supabase.co'
  security add-generic-password -a limitbar -s limitbar-supabase-key -w   # pide la clave secreta
También valen las variables SUPABASE_URL y SUPABASE_KEY (para pruebas).
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request

from collector.schema import Snapshot


class UploadError(Exception):
    pass


def _keychain(service: str) -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-a", "limitbar", "-s", service, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def load_config() -> tuple[str, str] | None:
    """(url, key) o None si Supabase no está configurado."""
    url = os.environ.get("SUPABASE_URL") or _keychain("limitbar-supabase-url")
    key = os.environ.get("SUPABASE_KEY") or _keychain("limitbar-supabase-key")
    if not url or not key:
        return None
    return url.rstrip("/"), key


def build_rows(snapshot: Snapshot) -> tuple[list[dict], list[dict]]:
    """Filas para latest_status y usage_history.

    Si un proveedor falla, su fila de último estado solo actualiza status/error/checked_at:
    se conservan las últimas ventanas buenas y su updated_at.
    """
    latest, history = [], []
    for p in snapshot.providers:
        row = {
            "provider": p.id,
            "status": p.status,
            "error": p.error,
            "checked_at": snapshot.collected_at,
            "source_device": snapshot.source_device,
            "schema_version": snapshot.schema_version,
        }
        if p.status == "ok":
            row["windows"] = [w.__dict__ for w in p.windows]
            row["updated_at"] = snapshot.collected_at
            history += [{
                "collected_at": snapshot.collected_at,
                "provider": p.id,
                "window_id": w.id,
                "used_pct": w.used_pct,
                "resets_at": w.resets_at,
                "source_device": snapshot.source_device,
            } for w in p.windows if w.used_pct is not None]
        latest.append(row)
    return latest, history


def _post(url: str, key: str, path: str, rows: list[dict], prefer: str) -> None:
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    if key.startswith("eyJ"):  # clave antigua (JWT service_role)
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{url}/rest/v1/{path}", data=json.dumps(rows).encode(), headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise UploadError(f"Supabase respondió {e.code} en {path}: {detail}") from None
    except urllib.error.URLError as e:
        raise UploadError(f"Sin conexión con Supabase ({e.reason})") from None


def upload(snapshot: Snapshot, config: tuple[str, str]) -> int:
    """Sube el snapshot. Devuelve cuántas filas de histórico se insertaron."""
    url, key = config
    latest, history = build_rows(snapshot)
    # Las filas de un mismo upsert deben tener las mismas columnas: se agrupan por forma.
    for keys in {tuple(sorted(r)) for r in latest}:
        group = [r for r in latest if tuple(sorted(r)) == keys]
        _post(url, key, "latest_status?on_conflict=provider", group,
              "resolution=merge-duplicates,return=minimal")
    if history:
        _post(url, key, "usage_history", history, "return=minimal")
    return len(history)
