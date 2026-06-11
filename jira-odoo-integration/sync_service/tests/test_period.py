from datetime import date

from jira_odoo_sync.period import is_in_closed_period, parse_closed_until


def test_parse_vazio():
    assert parse_closed_until(None) is None
    assert parse_closed_until("") is None
    assert parse_closed_until("  ") is None


def test_parse_data():
    assert parse_closed_until("2026-05-31") == date(2026, 5, 31)
    assert parse_closed_until("2026-05-31 00:00:00") == date(2026, 5, 31)


def test_competencia_fechada_inclusiva():
    closed_until = date(2026, 5, 31)
    assert is_in_closed_period(date(2026, 5, 31), closed_until) is True
    assert is_in_closed_period(date(2026, 5, 1), closed_until) is True
    assert is_in_closed_period(date(2026, 6, 1), closed_until) is False


def test_sem_fechamento_tudo_aberto():
    assert is_in_closed_period(date(2020, 1, 1), None) is False
