"""Lector de Claude: % usado de las ventanas de 5 h y semanal.

De dónde sale el dato (no oficial, puede cambiar):
- Claude Code guarda su sesión OAuth en el Llavero de macOS («Claude Code-credentials»),
  un JSON con `claudeAiOauth.accessToken` y `expiresAt` (ms). Si no está, en
  `~/.claude/.credentials.json`.
- GET https://api.anthropic.com/api/oauth/usage con `Authorization: Bearer <token>` y
  `anthropic-beta: oauth-2025-04-20` devuelve `five_hour`, `seven_day`… cada una con
  `utilization` (0–100) y `resets_at`. Muchas claves son nombres en clave que van a `null`
  si la cuenta no tiene ese cupo; las que traen `limit_dollars` son créditos en dinero.
  `seven_day_breakdown.rows` reparte el semanal por producto (Claude Code, chats, Cowork…).

Reglas: el token vive solo en memoria y es de solo lectura. Nunca se refresca ni se reescribe
(eso podría cerrar la sesión de Claude Code).

Si ha caducado (= no estoy usando Claude Code), se **despierta a Claude Code** con un mensaje
mínimo (`claude -p ok --model haiku`, sin herramientas ni MCP, sin guardar sesión) para que sea
él quien lo renueve, y se vuelve a leer. Es como abrir otra terminal con Claude Code: no se pisa
con la sesión que tenga abierta. Coste: un mensaje de Haiku cada ~8 h de inactividad.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from collector.providers.base import Provider, ProviderError
from collector.schema import ProviderResult, Share, Window

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
RENEW_MSG = "Abre Claude Code para renovar la sesión"
# launchd no carga el PATH de la terminal: se busca el binario en rutas conocidas.
CLAUDE_BIN_CANDIDATES = [
    Path.home() / ".local" / "bin" / "claude",
    Path("/opt/homebrew/bin/claude"),
    Path("/usr/local/bin/claude"),
]
WAKE_ARGS = ["-p", "ok", "--model", "haiku", "--tools", "", "--strict-mcp-config",
             "--no-session-persistence"]
WAKE_TIMEOUT_S = 60


class SessionExpired(ProviderError):
    """El token ha caducado o la API lo rechaza: se puede intentar despertar a Claude Code."""

# clave en la respuesta → (id, etiqueta). El orden es el de salida.
WINDOWS = [
    ("five_hour", "5h", "Sesión (5 h)"),
    ("seven_day", "7d", "Semanal"),
    ("seven_day_opus", "7d_opus", "Semanal · Opus"),
    ("seven_day_sonnet", "7d_sonnet", "Semanal · Sonnet"),
]
# Las dos principales salen siempre (aunque vengan vacías); las de modelo, solo si hay dato.
REQUIRED = {"five_hour", "seven_day"}
# Nombres en clave ya identificados (comparando con claude.ai → Ajustes → Uso).
CODENAMES = {
    "iguana_necktie": ("cloud_credits", "Créditos nube"),   # «Créditos de sesión en la nube»
}
BREAKDOWN_LABELS = {"claude_code": "Claude Code", "chat": "Chats", "cowork": "Cowork",
                    "other": "Otros"}
# Ventanas que no conocemos (p. ej. `seven_day_fable` si un modelo pasa a tener cupo propio):
# se reconocen por el prefijo y salen detrás de las conocidas, en vez de perderse.
PREFIXES = [("five_hour_", "5h_", "Sesión (5 h)"), ("seven_day_", "7d_", "Semanal")]


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
        raise SessionExpired(f"La sesión ha caducado. {RENEW_MSG}")
    return token


def _find_claude_bin() -> Path | None:
    return next((p for p in CLAUDE_BIN_CANDIDATES if p.is_file()), None)


def wake_claude_code() -> bool:
    """Lanza un mensaje mínimo con Claude Code para que renueve él mismo su token.

    Se ejecuta en un directorio temporal (fuera de mis proyectos), sin herramientas, sin MCP y
    sin guardar la sesión. Devuelve True si Claude Code terminó bien.
    """
    claude_bin = _find_claude_bin()
    if claude_bin is None:
        return False
    try:
        out = subprocess.run(
            [str(claude_bin), *WAKE_ARGS],
            cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=WAKE_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


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
            raise SessionExpired(f"Token rechazado. {RENEW_MSG}") from None
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


def _unknown_windows(data: dict) -> list[tuple[str, str, str]]:
    known = {key for key, _, _ in WINDOWS}
    out = []
    for key, raw in data.items():
        if key in known or not isinstance(raw, dict) or raw.get("utilization") is None:
            continue
        if key in CODENAMES:
            out.append((key, *CODENAMES[key]))
            continue
        for prefix, id_prefix, label in PREFIXES:
            if key.startswith(prefix):
                name = key[len(prefix):]
                out.append((key, id_prefix + name, f"{label} · {name.replace('_', ' ').capitalize()}"))
                break
        else:
            out.append((key, key, key.replace("_", " ").capitalize()))
    return out


def parse_usage(data: dict) -> list[Window]:
    windows = []
    for key, wid, label in WINDOWS + _unknown_windows(data):
        raw = data.get(key)
        if not isinstance(raw, dict):
            if key in REQUIRED:
                windows.append(Window(wid, label, None, None))
            continue
        pct = raw.get("utilization")
        window = Window(
            id=wid,
            label=label,
            used_pct=round(float(pct), 1) if pct is not None else None,
            resets_at=_to_utc_iso(raw.get("resets_at")),
        )
        if raw.get("limit_dollars") is not None:
            window.kind = "credit"
            window.used = float(raw.get("used_dollars") or 0)
            window.limit = float(raw["limit_dollars"])
            window.currency = "USD"
        windows.append(window)
    return windows


def parse_breakdown(data: dict) -> list[Share]:
    rows = (data.get("seven_day_breakdown") or {}).get("rows") or []
    return [Share(
        id=r["key"],
        label=BREAKDOWN_LABELS.get(r["key"], r.get("display_name") or r["key"]),
        pct=float(r.get("percent") or 0),
    ) for r in rows if isinstance(r, dict) and r.get("key")]


class ClaudeProvider(Provider):
    id = "claude"

    @staticmethod
    def _fetch_usage_with_wake() -> dict:
        try:
            return fetch_usage(read_access_token())
        except SessionExpired:
            if not wake_claude_code():
                raise
        # Claude Code ya ha renovado el token en el Llavero: se lee de nuevo (un solo reintento).
        return fetch_usage(read_access_token())

    def fetch(self) -> ProviderResult:
        data = self._fetch_usage_with_wake()
        result = ProviderResult(id=self.id, windows=parse_usage(data), breakdown=parse_breakdown(data))
        try:    # el coste es local e independiente: si falla, no debe tumbar las ventanas
            from collector import usage_tokens
            result.cost = usage_tokens.read_cost()
        except Exception:   # noqa: BLE001
            pass
        return result
