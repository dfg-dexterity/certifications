from jira_odoo_sync.time_utils import seconds_to_hours


def test_examples_da_especificacao():
    assert seconds_to_hours(3600) == 1.00
    assert seconds_to_hours(1800) == 0.50
    assert seconds_to_hours(900) == 0.25


def test_uma_hora_e_meia():
    assert seconds_to_hours(5400) == 1.50


def test_arredondamento_duas_casas():
    assert seconds_to_hours(1000) == 0.28  # 0.2777... -> 0.28


def test_zero_e_none():
    assert seconds_to_hours(0) == 0.0
    assert seconds_to_hours(None) == 0.0
