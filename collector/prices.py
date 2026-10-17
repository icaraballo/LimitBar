"""Tabla de precios de la API de Claude, en $ por millón de tokens (MTok).

Sirve para el «coste equivalente»: lo que habría costado por API el uso que Claude Code registra
en sus logs. No es lo que pago (tengo plan de tarifa plana), es la referencia para decidir si el
plan compensa.

Revisado: 2026-10-17 (fuente: skill claude-api de Anthropic). Los precios cambian: al tocarlos,
actualizar REVISED. La lectura de caché va aparte porque es mucho más barata; la escritura de
caché se cobra sobre el precio de entrada (1.25x a 5 min, 2x a 1 hora).
"""

from __future__ import annotations

REVISED = "2026-10-17"
CACHE_WRITE_5M = 1.25     # x entrada
CACHE_WRITE_1H = 2.0      # x entrada

# modelo → (entrada, salida, lectura_cache) en $/MTok. La escritura sale de la entrada.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 1.0),
    "claude-fable-5":   (10.0, 50.0, 1.0),
    "claude-opus-5-5":  (4.0, 20.0, 0.20),
    "claude-opus-5":    (5.0, 25.0, 0.50),
    "claude-opus-4-8":  (5.0, 25.0, 0.50),
    "claude-opus-4-7":  (5.0, 25.0, 0.50),
    "claude-opus-4-6":  (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5":  (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.02),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}

# Nombre bonito para enseñar. Si un modelo no está, se usa su id tal cual.
LABELS = {
    "claude-fable-5-1": "Fable 5.1", "claude-fable-5": "Fable 5",
    "claude-opus-5-5": "Opus 5.5", "claude-opus-5": "Opus 5", "claude-opus-4-8": "Opus 4.8",
    "claude-opus-4-7": "Opus 4.7", "claude-opus-4-6": "Opus 4.6",
    "claude-sonnet-5-5": "Sonnet 5.5", "claude-sonnet-5": "Sonnet 5", "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-haiku-5-5": "Haiku 5.5", "claude-haiku-4-5": "Haiku 4.5",
}


def normalize(model: str) -> str:
    """Quita el sufijo de fecha (claude-haiku-4-5-20251001 → claude-haiku-4-5)."""
    import re
    return re.sub(r"-\d{8}$", "", model)


def label(model: str) -> str:
    return LABELS.get(normalize(model), normalize(model))


def cost_usd(model: str, input_: int, output: int, cache_write_5m: int,
             cache_write_1h: int, cache_read: int) -> float | None:
    """Coste en dólares de un reparto de tokens. None si no conozco el precio del modelo."""
    price = PRICES.get(normalize(model))
    if price is None:
        return None
    pin, pout, pread = price
    total = (
        input_ * pin
        + output * pout
        + cache_read * pread
        + cache_write_5m * pin * CACHE_WRITE_5M
        + cache_write_1h * pin * CACHE_WRITE_1H
    )
    return total / 1_000_000
