"""Configuração do serviço.

Todas as credenciais vêm de variáveis de ambiente (RNF02 — nunca em código
fonte). Veja ``.env.example`` na raiz do projeto para a lista completa.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Variável de ambiente obrigatória ausente: {name}")
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _as_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _as_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "sim", "y", "s"}


@dataclass(frozen=True)
class Settings:
    # Jira Cloud
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    # Clockwork Pro
    clockwork_api_token: str
    clockwork_base_url: str
    # Odoo
    odoo_url: str
    odoo_db: str
    odoo_username: str
    odoo_password: str
    # "addon" (Odoo.sh/on-premise com o addon jira_clockwork_sync) ou
    # "studio" (Odoo Online com modelos criados via Studio — ver
    # docs/odoo-online-studio.md)
    odoo_schema: str = "addon"
    # Comportamento
    sync_lookback_days: int = 7
    clockwork_chunk_days: int = 7
    log_success: bool = False
    allow_task_project_update: bool = False
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            jira_base_url=_required("JIRA_BASE_URL"),
            jira_email=_required("JIRA_EMAIL"),
            jira_api_token=_required("JIRA_API_TOKEN"),
            clockwork_api_token=_required("CLOCKWORK_API_TOKEN"),
            clockwork_base_url=_optional(
                "CLOCKWORK_BASE_URL", "https://api.clockwork.report/v1"
            ),
            odoo_url=_required("ODOO_URL"),
            odoo_db=_required("ODOO_DB"),
            odoo_username=_required("ODOO_USERNAME"),
            odoo_password=_required("ODOO_PASSWORD"),
            odoo_schema=_optional("ODOO_SCHEMA", "addon").lower(),
            sync_lookback_days=_as_int("SYNC_LOOKBACK_DAYS", 7),
            clockwork_chunk_days=_as_int("CLOCKWORK_CHUNK_DAYS", 7),
            log_success=_as_bool("SYNC_LOG_SUCCESS", False),
            allow_task_project_update=_as_bool("SYNC_ALLOW_TASK_PROJECT_UPDATE", False),
            dry_run=_as_bool("SYNC_DRY_RUN", False),
        )
