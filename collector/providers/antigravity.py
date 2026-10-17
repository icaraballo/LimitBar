"""Lector de Antigravity: % usado por familia de modelo y coste equivalente en tokens locales.

De dónde sale el dato:
- Antigravity expone en local el RPC Connect/JSON
  `POST /exa.language_server_pb.LanguageServerService/GetUserStatus` con la cabecera
  `x-codeium-csrf-token`.
- Si Antigravity o la extensión de VS Code están abiertas, se reutiliza el `language_server` o
  `agy --hub` que ya esté corriendo (~10 ms).
- Si está todo cerrado, se arranca temporalmente `~/.gemini/bin/agy --hub` en un puerto libre
  (~0,6 s): el propio binario oficial refresca en memoria el token del Llavero (`svce="gemini"`,
  `acct="antigravity"`) sin tocar ni reescribir nada desde Python, devuelve `GetUserStatus` y se
  cierra al terminar.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collector.providers.base import Provider, ProviderError
from collector.schema import ProviderResult, Window

RPC_PATH = "/exa.language_server_pb.LanguageServerService/GetUserStatus"
AGY_CANDIDATES = (
    Path.home() / ".gemini" / "bin" / "agy",
    Path.home() / ".local" / "bin" / "agy",
    Path("/Applications/Antigravity.app/Contents/Resources/bin/language_server"),
)

# Familias conocidas: etiqueta sin nivel de esfuerzo → (window_id, nombre). Fijan el orden de arriba.
# Los ids no llevan el periodo: la API no lo da y se deduce de la hora de reset (ver _period).
KNOWN_FAMILIES: list[tuple[str, str, str]] = [
    ("gemini 3.8 flash", "flash_3_8", "Flash 3.8"),
    ("gemini 4 argon", "argon_4", "Argon 4"),
    ("claude opus 5.5", "opus_5_5", "Claude Opus 5.5"),
    ("claude sonnet 5.5", "sonnet_5_5", "Claude Sonnet 5.5"),
    ("gpt-oss 120b", "gpt_oss_120b", "GPT-OSS 120B"),
]
_TIER_SUFFIX = re.compile(r"\s*\((?:Low|Medium|High|Extra Low)\)$", re.IGNORECASE)


def _to_utc_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _period(reset_iso: str | None, now: datetime) -> str | None:
    """«5 h» o «semanal» según lo lejos que quede el reset (la API solo da la hora)."""
    if not reset_iso:
        return None
    try:
        reset = datetime.fromisoformat(reset_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return "semanal" if reset - now > timedelta(hours=24) else "5 h"


def parse_usage(data: dict, now: datetime | None = None) -> list[Window]:
    """Traduce `GetUserStatus` a una ventana por familia de modelo (sin repetir Low/Medium/High)."""
    now = now or datetime.now(timezone.utc)
    configs = (
        (data.get("userStatus") or {})
        .get("cascadeModelConfigData", {})
        .get("clientModelConfigs")
        or []
    )
    by_family: dict[str, tuple[str, dict]] = {}
    for cfg in configs:
        if not isinstance(cfg, dict) or not cfg.get("label"):
            continue
        base = _TIER_SUFFIX.sub("", cfg["label"].strip())
        quota = cfg.get("quotaInfo") if isinstance(cfg.get("quotaInfo"), dict) else {}
        if base.lower() not in by_family or quota:
            by_family[base.lower()] = (base, quota)

    known = {fam: (wid, name) for fam, wid, name in KNOWN_FAMILIES}
    order = [fam for fam, _, _ in KNOWN_FAMILIES if fam in by_family]
    order += [fam for fam in by_family if fam not in known]

    windows: list[Window] = []
    for fam in order:
        base, quota = by_family[fam]
        wid, name = known.get(fam, (re.sub(r"[^a-z0-9]+", "_", fam).strip("_"), base))
        rem = quota.get("remainingFraction")
        reset_iso = _to_utc_iso(quota.get("resetTime"))
        if isinstance(rem, (int, float)):
            used_pct = round(max(0.0, min(100.0, (1.0 - float(rem)) * 100.0)), 1)
        elif reset_iso is not None:
            # En Protobuf3 JSON, remainingFraction=0.0 se omite cuando el cupo está al 100 % usado.
            used_pct = 100.0
        else:
            used_pct = None
        period = _period(reset_iso, now)
        label = f"{name} · {period}" if period else name
        windows.append(Window(id=wid, label=label, used_pct=used_pct, resets_at=reset_iso))
    return windows


def _call_get_user_status(port: int, csrf: str, https: bool = False, timeout: float = 3.0) -> dict:
    scheme = "https" if https else "http"
    url = f"{scheme}://127.0.0.1:{port}{RPC_PATH}"
    headers = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
        "x-codeium-csrf-token": csrf,
    }
    body = json.dumps({
        "metadata": {"ideName": "antigravity", "extensionName": "antigravity", "locale": "es"}
    }).encode()
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
    """Arranca `agy --hub` en segundo plano ~0,6 s para leer la cuota con la app cerrada."""
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
                data = _call_get_user_status(port, csrf, https=False, timeout=1.5)
                last_data = data
                configs = (
                    (data.get("userStatus") or {})
                    .get("cascadeModelConfigData", {})
                    .get("clientModelConfigs")
                )
                if configs:
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
        try:
            data = _call_get_user_status(port, csrf, https=https, timeout=2.0)
            configs = (
                (data.get("userStatus") or {})
                .get("cascadeModelConfigData", {})
                .get("clientModelConfigs")
            )
            if configs:
                return data
        except Exception:  # noqa: BLE001 — probamos el siguiente o levantamos hub temporal
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
