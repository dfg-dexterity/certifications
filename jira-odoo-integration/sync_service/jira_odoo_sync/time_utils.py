"""Conversão de tempo: Clockwork/Jira trabalham em segundos, o Odoo em horas decimais."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def seconds_to_hours(seconds: int | None) -> float:
    """Converte segundos em horas decimais com 2 casas.

    3600 -> 1.00 | 1800 -> 0.50 | 900 -> 0.25
    """
    if not seconds:
        return 0.0
    hours = Decimal(int(seconds)) / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
