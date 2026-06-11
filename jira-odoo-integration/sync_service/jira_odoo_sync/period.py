"""Controle de competência fechada (seção 9 da especificação).

O parâmetro ``jira_clockwork_sync.closed_until`` (mantido no Odoo via
``ir.config_parameter``) define a data limite de fechamento mensal.
Worklogs com data menor ou igual a essa data não podem ser criados,
alterados ou cancelados automaticamente: viram pendência administrativa
com status ``CLOSED_PERIOD``.
"""
from __future__ import annotations

from datetime import date, datetime


def parse_closed_until(raw: str | None) -> date | None:
    """Interpreta o valor do parâmetro (string ``YYYY-MM-DD`` ou vazio)."""
    if not raw or not str(raw).strip():
        return None
    return datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d").date()


def is_in_closed_period(worklog_date: date, closed_until: date | None) -> bool:
    return closed_until is not None and worklog_date <= closed_until
