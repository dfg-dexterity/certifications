.PHONY: install test check sync backfill

install:
	pip install -r requirements.txt pytest

test:
	python -m pytest -v

check:
	PYTHONPATH=sync_service python -m jira_odoo_sync check

sync:
	PYTHONPATH=sync_service python -m jira_odoo_sync sync

# Uso: make backfill START=2026-05-01 END=2026-06-30
backfill:
	PYTHONPATH=sync_service python -m jira_odoo_sync backfill --start $(START) --end $(END)
