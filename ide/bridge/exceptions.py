"""Excepciones del IsyVM bridge."""
from __future__ import annotations


class IsolationViolation(Exception):
    """Levantada ante cualquier intento de fuga detectado por el bridge."""
    pass
