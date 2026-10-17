"""Lector de Gemini (Google AI Pro): % usado de las ventanas de 5 h y semanal.

De dónde sale el dato:
- Gemini expone los límites de la cuenta en `https://gemini.google.com/usage` (Ajustes → Límites de
  uso), que internamente consulta `assistant.mobile.robin.RobinService/GetUsageInfo` y pinta las
  dos ventanas (`GXU_FIVE_HOURLY` = 5 h y `GXU_WEEKLY` = semanal) más los créditos de IA si existen.
- Como `Gemini.app` cifra su sesión con Tink y macOS bloquea leer el perfil principal de Chrome,
  usamos un perfil ligero propio en `data/chrome-gemini` con `--headless=new` y DevTools local
  (sin dependencias externas ni abrir ventanas, y cerrando el proceso en cuanto aparece el %).

Primera vez (y cada varias semanas si caduca la cookie de Google):
  python3 -m collector.providers.gemini --login
"""

from __future__ import annotations

import argparse
import base64
import html as html_lib
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collector.providers.base import Provider, ProviderError
from collector.schema import ProviderResult, Window

USAGE_URL = "https://gemini.google.com/usage"
CHROME_BIN = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "chrome-gemini"
LOGIN_CMD = "python3 -m collector.providers.gemini --login"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:usado|utilizado|used)", re.IGNORECASE)
_CREDITS_RE = re.compile(
    r"(?:quedan\s+(\d+)\s+cr[eé]ditos|(\d+)\s+credits\s+remaining)", re.IGNORECASE
)
# La página tiene dos bloques: «Current usage» (5 h) y «Weekly limit». En el semanal el % va
# DETRÁS de la hora de reset, así que se lee por bloques, no por el orden de los %.
_WEEKLY_RE = re.compile(r"weekly\s+limit|l[ií]mite\s+semanal", re.IGNORECASE)
_CLOCK = r"(\d{1,2}:\d{2}(?:\s*[ap]\.?\s*m\.?)?)"
_RESET_TIME_ONLY_RE = re.compile(
    rf"(?:resets\s+at|se\s+restablece\s+a\s+las)\s+{_CLOCK}", re.IGNORECASE
)
# «Resets on 20 Oct at 08:18», «Resets on Thu at 10:00 AM», «Se restablece el 20 oct a las 08:18»
_RESET_DAY_TIME_RE = re.compile(
    rf"(?:resets(?:\s+on)?|se\s+restablece(?:\s+el)?)\s+([^\n]+?)\s+(?:at|a\s+las)\s+{_CLOCK}",
    re.IGNORECASE,
)

_WEEKDAYS = {
    "lun": 0, "lunes": 0, "mon": 0, "monday": 0,
    "mar": 1, "martes": 1, "tue": 1, "tuesday": 1,
    "mié": 2, "mie": 2, "miércoles": 2, "miercoles": 2, "wed": 2, "wednesday": 2,
    "jue": 3, "jueves": 3, "thu": 3, "thursday": 3,
    "vie": 4, "viernes": 4, "fri": 4, "friday": 4,
    "sáb": 5, "sab": 5, "sábado": 5, "sabado": 5, "sat": 5, "saturday": 5,
    "dom": 6, "domingo": 6, "sun": 6, "sunday": 6,
}
# Tres primeras letras del mes, en inglés y en castellano.
_MONTHS = {
    "jan": 1, "ene": 1, "feb": 2, "mar": 3, "apr": 4, "abr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dec": 12, "dic": 12,
}


def _parse_clock(clock_str: str) -> tuple[int, int] | None:
    s = clock_str.strip().lower().replace(".", "")
    is_pm = "pm" in s or "p m" in s
    is_am = "am" in s or "a m" in s
    s = re.sub(r"[ap]\s*m", "", s).strip()
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if is_pm and hour < 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0
    return hour, minute


def _day_date(day: str, now_local: datetime) -> datetime | None:
    """«thu», «20 oct», «oct 20» o «20 de oct» → fecha local (a medianoche) del próximo que toque."""
    words = re.findall(r"[a-záéíóúñ]+|\d+", day.lower())
    if not words:
        return None
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if words[0] in _WEEKDAYS:
        return midnight + timedelta(days=(_WEEKDAYS[words[0]] - now_local.weekday()) % 7)
    nums = [int(w) for w in words if w.isdigit()]
    months = [_MONTHS[w[:3]] for w in words if not w.isdigit() and w[:3] in _MONTHS]
    if not nums or not months:
        return None
    try:
        date = midnight.replace(month=months[0], day=nums[0])
    except ValueError:
        return None
    if date < midnight - timedelta(days=1):    # «5 ene» visto en diciembre es del año siguiente
        date = date.replace(year=date.year + 1)
    return date


def _resolve_reset_iso(text: str, now: datetime | None = None) -> str | None:
    now_local = (now or datetime.now(timezone.utc)).astimezone()
    m_day = _RESET_DAY_TIME_RE.search(text)
    if m_day:
        date = _day_date(m_day.group(1), now_local)
        clock = _parse_clock(m_day.group(2))
        if date is not None and clock:
            candidate = date.replace(hour=clock[0], minute=clock[1])
            if candidate <= now_local and m_day.group(1).lower().split()[0] in _WEEKDAYS:
                candidate += timedelta(days=7)
            return candidate.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    m_time = _RESET_TIME_ONLY_RE.search(text)
    if m_time:
        clock = _parse_clock(m_time.group(1))
        if clock:
            hour, minute = clock
            candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now_local:
                candidate += timedelta(days=1)
            return candidate.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def _visible_text(raw_html: str) -> str:
    no_scripts = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    text = _TAG_RE.sub("\n", no_scripts)
    return html_lib.unescape(text)


def _window(wid: str, label: str, block: str, now: datetime | None) -> Window:
    m = _PCT_RE.search(block)
    pct = round(float(m.group(1).replace(",", ".")), 1) if m else None
    return Window(id=wid, label=label, used_pct=pct, resets_at=_resolve_reset_iso(block, now=now))


def parse_usage_html(raw_html: str, now: datetime | None = None) -> list[Window]:
    """Extrae las ventanas de 5 h, semanal y créditos del texto/HTML de `gemini.google.com/usage`."""
    text = _visible_text(raw_html) if "<" in raw_html else raw_html
    joined = "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())

    if not _PCT_RE.search(joined):
        raise ProviderError(f"Sesión de Gemini no iniciada o caducada. Ejecuta: {LOGIN_CMD}")

    m_week = _WEEKLY_RE.search(joined)
    if m_week:
        session, weekly = joined[:m_week.start()], joined[m_week.end():]
    else:   # sin el título del bloque semanal: todo es de la sesión y el semanal queda «sin dato»
        session, weekly = joined, ""
    windows = [_window("5h", "Sesión (5 h)", session, now),
               _window("7d", "Semanal", weekly, now)]

    m_cred = _CREDITS_RE.search(joined)
    if m_cred:
        # La página solo dice cuántos quedan: sin tope ni %, así que no se pinta barra.
        windows.append(Window(
            id="ai_credits", label="Créditos IA", used_pct=None, resets_at=None,
            kind="credit", limit=float(m_cred.group(1) or m_cred.group(2)), currency="créditos",
        ))
    return windows


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _profile_in_use() -> bool:
    """¿Hay un Chrome vivo con nuestro perfil (p. ej. la ventana de --login abierta)?

    Chrome deja `SingletonLock` → «<equipo>-<pid>». Se mira que ese pid siga vivo Y sea un
    Chrome con nuestro perfil: si Chrome murió, macOS puede haber dado ese pid a otro programa.
    """
    lock = PROFILE_DIR / "SingletonLock"
    try:
        pid = int(os.readlink(lock).rsplit("-", 1)[1])
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return False
    return str(PROFILE_DIR) in cmd


def _clear_stale_singleton_locks() -> None:
    """Borra los bloqueos que deja un Chrome que ya no existe. Nunca mata procesos."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = PROFILE_DIR / name
        if p.is_symlink() or p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def _ws_eval_text(ws_url: str, expression: str, timeout: float = 3.0) -> str:
    """Evalúa una expresión JS por WebSocket CDP usando solo la biblioteca estándar."""
    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"

    with socket.create_connection((host, port), timeout=timeout) as sock:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode("ascii"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                return ""
            buf += chunk

        payload = json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        }).encode("utf-8")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", 0x81, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, length)
        sock.sendall(header + mask + masked)

        # Leemos el frame de respuesta
        resp_buf = buf.split(b"\r\n\r\n", 1)[1]
        while True:
            if len(resp_buf) >= 2:
                b1 = resp_buf[1] & 0x7F
                offset = 2
                if b1 == 126:
                    if len(resp_buf) >= 4:
                        flen = struct.unpack("!H", resp_buf[2:4])[0]
                        offset = 4
                    else:
                        flen = None
                elif b1 == 127:
                    if len(resp_buf) >= 10:
                        flen = struct.unpack("!Q", resp_buf[2:10])[0]
                        offset = 10
                    else:
                        flen = None
                else:
                    flen = b1
                if flen is not None and len(resp_buf) >= offset + flen:
                    frame_data = resp_buf[offset:offset + flen]
                    resp_buf = resp_buf[offset + flen:]
                    try:
                        msg = json.loads(frame_data.decode("utf-8", errors="replace"))
                        if msg.get("id") == 1:
                            return (
                                msg.get("result", {})
                                .get("result", {})
                                .get("value")
                                or ""
                            )
                    except ValueError:
                        pass
                    continue
            chunk = sock.recv(8192)
            if not chunk:
                break
            resp_buf += chunk
    return ""


def _complete(text: str) -> bool:
    """La página ya trae los dos % (el semanal se pinta un poco después que el de la sesión)."""
    try:
        return all(w.used_pct is not None for w in parse_usage_html(text)[:2])
    except ProviderError:
        return False


def fetch_usage_html() -> str:
    if not CHROME_BIN.exists():
        raise ProviderError("No encuentro Google Chrome en /Applications para leer Gemini")
    if not PROFILE_DIR.exists():
        raise ProviderError(f"Sin sesión de Gemini. Ejecuta: {LOGIN_CMD}")

    if _profile_in_use():
        raise ProviderError("La ventana de login de Gemini sigue abierta: ciérrala (⌘Q)")
    _clear_stale_singleton_locks()
    port = _free_port()
    cmd = [
        str(CHROME_BIN),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={PROFILE_DIR}",
        USAGE_URL,
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )
    try:
        deadline = time.monotonic() + 30.0
        last_text = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1.5) as r:
                    tabs = json.load(r)
                page_tabs = [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if not page_tabs:
                    continue
                ws_url = page_tabs[0]["webSocketDebuggerUrl"]
                txt = _ws_eval_text(ws_url, "document.body ? document.body.innerText : ''")
                if txt:
                    last_text = txt
                    if _complete(txt):
                        return txt
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                continue
        if last_text:
            return last_text
        raise ProviderError("No pude leer gemini.google.com/usage (¿sigue abierta la ventana de login?)")
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        _clear_stale_singleton_locks()


class GeminiProvider(Provider):
    id = "gemini"

    def fetch(self) -> ProviderResult:
        raw_html = fetch_usage_html()
        return ProviderResult(id=self.id, windows=parse_usage_html(raw_html))


def login() -> int:
    """Abre una ventana con el perfil de LimitBar para iniciar sesión en Google una sola vez."""
    if not CHROME_BIN.exists():
        print("✗ No encuentro /Applications/Google Chrome.app", file=sys.stderr)
        return 1
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    if _profile_in_use():
        print("✗ El perfil de LimitBar ya está abierto (¿otra ventana de login?)", file=sys.stderr)
        return 1
    _clear_stale_singleton_locks()
    print(f"Abriendo {USAGE_URL} en el perfil de LimitBar ({PROFILE_DIR})…")
    print("Inicia sesión en tu cuenta de Google, comprueba que se ven los límites y cierra Chrome (⌘Q).")
    subprocess.run([
        str(CHROME_BIN),
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={PROFILE_DIR}",
        USAGE_URL,
    ], check=False)
    _clear_stale_singleton_locks()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lector de Gemini para LimitBar")
    parser.add_argument("--login", action="store_true", help="abrir navegador para iniciar sesión")
    args = parser.parse_args()
    if args.login:
        return login()
    res = GeminiProvider().fetch()
    for w in res.windows:
        print(f"{w.label}: {w.used_pct}% (reset {w.resets_at})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
