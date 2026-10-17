"""Lector de Claude: % usado de las ventanas de 5 h y semanal.

De dónde sale el dato (no oficial, puede cambiar):
- Claude Code guarda su sesión OAuth en el Llavero de macOS («Claude Code-credentials»),
  un JSON con `claudeAiOauth.accessToken` y `expiresAt` (ms). Si no está, en
  `~/.claude/.credentials.json`.
- GET https://api.anthropic.com/api/oauth/usage con `Authorization: Bearer <token>` y
  `anthropic-beta: oauth-2025-04-20` devuelve `five_hour`, `seven_day`… cada una con
  `utilization` (0–100) y `resets_at`.

Reglas: el token vive solo en memoria y es de solo lectura. Nunca se refresca ni se reescribe
(eso podría cerrar la sesión de Claude Code).
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from collector.providers.base import Provider, ProviderError
from collector.schema import ProviderResult, Window

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
RENEW_MSG = "Abre Claude Code para renovar la sesión"

# clave en la respuesta → (id, etiqueta). El orden es el de salida.
WINDOWS = [
    ("five_hour", "5h", "Sesión (5 h)"),
    ("seven_day", "7d", "Semanal"),
    ("seven_day_opus", "7d_opus", "Semanal · Opus"),
    ("seven_day_sonnet", "7d_sonnet", "Semanal · Sonnet"),
]
# Las dos principales salen siempre (aunque vengan vacías); las de modelo, solo si hay dato.
REQUIRED = {"five_hour", "seven_day"}


def _read_credentials_blob() -> str:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE.read_text()
    raise ProviderError("No encuentro la sesión de Claude Code (¿has iniciado sesión?)")


def read_access_token(blob: str | None = None, now_ms: int | None = None) -> str:
    """Saca el access token del JSON de credenciales. Nunca lo imprime."""
    blob = blob if blob is not None else _read_credentials_blob()
    try:
        oauth = json.loads(blob)["claudeAiOauth"]
        token = oauth["accessToken"]
    except (ValueError, KeyError, TypeError):
        raise ProviderError(f"Las credenciales no tienen sesión de Claude. {RENEW_MSG}") from None
    expires_at = oauth.get("expiresAt")
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if isinstance(expires_at, (int, float)) and expires_at <= now_ms:
        raise ProviderError(f"La sesión ha caducado. {RENEW_MSG}")
    return token


def fetch_usage(token: str) -> dict:
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": BETA_HEADER,
        "Accept": "application/json",
        "User-Agent": "LimitBar/0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ProviderError(f"Token rechazado. {RENEW_MSG}") from None
        if e.code == 429:
            raise ProviderError("Demasiadas peticiones; se reintentará en la próxima ronda") from None
        raise ProviderError(f"Error HTTP {e.code} al leer el uso") from None
    except urllib.error.URLError as e:
        raise ProviderError(f"Sin conexión con api.anthropic.com ({e.reason})") from None


def _to_utc_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_usage(data: dict) -> list[Window]:
    windows = []
    for key, wid, label in WINDOWS:
        raw = data.get(key)
        if not isinstance(raw, dict):
            if key in REQUIRED:
                windows.append(Window(wid, label, None, None))
            continue
        pct = raw.get("utilization")
        windows.append(Window(
            id=wid,
            label=label,
            used_pct=round(float(pct), 1) if pct is not None else None,
            resets_at=_to_utc_iso(raw.get("resets_at")),
        ))
    return windows


class ClaudeProvider(Provider):
    id = "claude"

    def fetch(self) -> ProviderResult:
        token = read_access_token()
        return ProviderResult(id=self.id, windows=parse_usage(fetch_usage(token)))
