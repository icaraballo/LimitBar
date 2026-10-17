"""Interfaz común de los lectores: cada proveedor traduce sus datos a ProviderResult."""

from __future__ import annotations

from abc import ABC, abstractmethod

from collector.schema import ProviderResult


class ProviderError(Exception):
    """Fallo esperado con un mensaje legible para enseñar al usuario."""


class Provider(ABC):
    id: str

    @abstractmethod
    def fetch(self) -> ProviderResult:
        """Lee el uso actual. Puede lanzar excepciones: main las convierte en status «error»."""
