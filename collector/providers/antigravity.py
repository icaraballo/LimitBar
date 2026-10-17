"""Lector de Antigravity: % usado por grupo de modelos (5 h y semanal) y coste en tokens locales.

De dónde sale el dato:
- Antigravity expone en local el RPC Connect/JSON
  `POST /exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary` con la cabecera
  `x-codeium-csrf-token` (que por dentro consulta `retrieveUserQuotaSummary` con su sesión OAuth).
- Si Antigravity o la extensión de VS Code están abiertas, se reutiliza el `language_server` o
  `agy --hub` que ya esté corriendo (~150 ms con `forceRefresh: true`).
- Si está todo cerrado, se arranca temporalmente `~/.gemini/bin/agy --hub` en un puerto libre
  (~2 s): el propio binario oficial refresca en memoria el token del Llavero (`svce="gemini"`,
  `acct="antigravity"`) sin tocar ni reescribir nada desde Python, devuelve el resumen de cuota y
  se cierra al terminar.
- Los tokens locales salen de `~/.gemini/antigravity*/brain/*/.system_generated/logs/transcript.jsonl`.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from collector.providers.base import Provider, ProviderError
from collector.schema import ProviderResult, Window

RPC_PATH = "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
AGY_CANDIDATES = (
    Path.home() / ".gemini" / "bin" / "agy",
    Path.home() / ".local" / "bin" / "agy",
    Path("/Applications/Antigravity.app/Contents/Resources/bin/language_server"),
)

# Cubos conocidos de RetrieveUserQuotaSummary: bucketId → (window_id, etiqueta).
# En cada grupo va primero la ventana de 5 h y luego la semanal, igual que en Claude y Gemini.
KNOWN_BUCKETS: list[tuple[str, str, str]] = [
    ("gemini-5h", "gemini_5h", "Gemini · 5 h"),
    ("gemini-weekly", "gemini_7d", "Gemini · semanal"),
    ("3p-5h", "claude_5h", "Claude · 5 h"),
    ("3p-weekly", "claude_7d", "Claude · semanal"),
    ("gemini-argon-wtu-weekly", "argon_4", "Argon 4 · semanal"),
]


def _to_utc_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fallback_label(group_name: str, bucket: dict) -> str:
    base = (group_name or bucket.get("displayName") or bucket.get("bucketId") or "Cuota").strip()
    win = bucket.get("window")
    if win == "5h":
        return f"{base} · 5 h"
    if win == "weekly":
        return f"{base} · semanal"
    return f"{base} · {win}" if win else base


def parse_usage(data: dict) -> list[Window]:
    """Traduce `RetrieveUserQuotaSummary` a las ventanas de 5 h y semanal de cada grupo.

    Mientras un cubo no se ha empezado a usar (`remainingFraction == 1`), Antigravity no tiene
    reseteo activo (la API devuelve `now + 5h` / `now + 7d` rodante y omite `description`), así
    que `resets_at` queda a `None` hasta que empiece el consumo.
    """
    groups = ((data.get("response") or data).get("groups")) or []
    by_bucket: dict[str, tuple[str, dict]] = {}
    for grp in groups:
        if not isinstance(grp, dict):
            continue
        g_name = str(grp.get("displayName") or "")
        for b in grp.get("buckets") or []:
            if isinstance(b, dict) and b.get("bucketId"):
                by_bucket[str(b["bucketId"])] = (g_name, b)

    known = {bid: (wid, label) for bid, wid, label in KNOWN_BUCKETS}
    order = [bid for bid, _, _ in KNOWN_BUCKETS if bid in by_bucket]
    order += [bid for bid in by_bucket if bid not in known]

    windows: list[Window] = []
    for bid in order:
        g_name, bucket = by_bucket[bid]
        wid, label = known.get(
            bid,
            (re.sub(r"[^a-z0-9]+", "_", bid.lower()).strip("_"), _fallback_label(g_name, bucket)),
        )
        rem = bucket.get("remainingFraction")
        raw_reset = _to_utc_iso(bucket.get("resetTime"))
        if isinstance(rem, (int, float)):
            used_pct = round(max(0.0, min(100.0, (1.0 - float(rem)) * 100.0)), 1)
            started = float(rem) < 1.0
        elif raw_reset is not None:
            # En Protobuf3 JSON, remainingFraction=0.0 se omite cuando el cupo está al 100 % usado.
            used_pct = 100.0
            started = True
        else:
            used_pct = None
            started = False
        resets_at = raw_reset if started else None
        windows.append(Window(id=wid, label=label, used_pct=used_pct, resets_at=resets_at))
    return windows


def _call_quota_summary(
    port: int, csrf: str, https: bool = False, force_refresh: bool = True, timeout: float = 3.0
) -> dict:
    scheme = "https" if https else "http"
    url = f"{scheme}://127.0.0.1:{port}{RPC_PATH}"
    headers = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
        "x-codeium-csrf-token": csrf,
    }
    body = json.dumps({"forceRefresh": True} if force_refresh else {}).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    ctx = None
    if https:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return json.load(resp)


def _running_endpoints() -> list[tuple[int, str, bool]]:
    """Busca en `ps` y `lsof` procesos `agy --hub` o `language_server` con `--csrf_token`."""
    try:
        ps_out = subprocess.run(
            ["ps", "-eo", "pid,command"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []

    endpoints: list[tuple[int, str, bool]] = []
    pids_need_lsof: dict[str, str] = {}
    for line in ps_out.splitlines():
        if "--csrf_token" not in line or "--use_host_auth" in line:
            continue
        if "agy" not in line and "language_server" not in line:
            continue
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        pid, cmd = parts
        csrf_m = re.search(r"--csrf_token[=\s]+([A-Za-z0-9_\-]+)", cmd)
        if not csrf_m:
            continue
        csrf = csrf_m.group(1)
        port_m = re.search(r"--hub-port[=\s]+(\d+)", cmd)
        if port_m:
            endpoints.append((int(port_m.group(1)), csrf, False))
        else:
            pids_need_lsof[pid] = csrf

    if pids_need_lsof:
        try:
            lsof_out = subprocess.run(
                ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in lsof_out.splitlines():
                cols = line.split()
                if len(cols) >= 9 and cols[1] in pids_need_lsof:
                    m = re.search(r":(\d+)$", cols[8])
                    if m:
                        port = int(m.group(1))
                        csrf = pids_need_lsof[cols[1]]
                        endpoints.append((port, csrf, False))
                        endpoints.append((port, csrf, True))
        except (OSError, subprocess.TimeoutExpired):
            pass
    return endpoints


def _find_agy_binary() -> str:
    for p in AGY_CANDIDATES:
        if p.exists():
            return str(p)
    found = shutil.which("agy")
    if found:
        return found
    raise ProviderError("No encuentro Antigravity (`agy`) instalado en este Mac")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _fetch_via_temporary_hub() -> dict:
    """Arranca `agy --hub` en segundo plano ~2 s para leer la cuota con la app cerrada."""
    binary = _find_agy_binary()
    port = _free_port()
    csrf = f"limitbar-{uuid.uuid4().hex}"
    cmd = [
        binary,
        "--hub",
        f"--hub-port={port}",
        "--app_data_dir=antigravity",
        f"--csrf_token={csrf}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 8.0
        last_data: dict | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.25)
            try:
                data = _call_quota_summary(port, csrf, https=False, force_refresh=False, timeout=2.0)
                last_data = data
                if (data.get("response") or {}).get("groups"):
                    return data
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                continue
        if last_data is not None:
            return last_data
        raise ProviderError("No pude leer la sesión de Antigravity (¿has iniciado sesión en agy?)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def fetch_status() -> dict:
    for port, csrf, https in _running_endpoints():
        for refresh in (True, False):
            try:
                data = _call_quota_summary(
                    port, csrf, https=https, force_refresh=refresh, timeout=3.0
                )
                if (data.get("response") or {}).get("groups"):
                    return data
            except Exception:  # noqa: BLE001 — probamos sin refresh, siguiente puerto o hub temporal
                continue
    return _fetch_via_temporary_hub()


class AntigravityProvider(Provider):
    id = "antigravity"

    def fetch(self) -> ProviderResult:
        data = fetch_status()
        windows = parse_usage(data)
        if not windows:
            raise ProviderError("Antigravity sin sesión activa (abre Antigravity o ejecuta `agy`)")
        result = ProviderResult(id=self.id, windows=windows)
        try:
            from collector import usage_tokens
            result.cost = usage_tokens.read_antigravity_cost()
        except Exception:  # noqa: BLE001
            pass
        return result
