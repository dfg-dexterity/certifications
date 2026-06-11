"""Entidades de domínio da integração.

Os valores dos enums correspondem aos códigos gravados nos campos
``selection`` do addon Odoo (``jira_clockwork_sync``). O nome em
maiúsculas (``IntegrationStatus.ERROR_USER_MAPPING.name``) corresponde
à nomenclatura usada na especificação funcional.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class IntegrationStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    ERROR_USER_MAPPING = "error_user_mapping"
    ERROR_PROJECT_MAPPING = "error_project_mapping"
    ERROR_ANALYTIC_MAPPING = "error_analytic_mapping"
    ERROR_ODOO = "error_odoo"
    ERROR_JIRA = "error_jira"
    SKIPPED = "skipped"
    CLOSED_PERIOD = "closed_period"
    CANCELLED_SOURCE = "cancelled_source"


class AllocationMode(str, Enum):
    DIRECT_PROJECT = "direct_project"
    BY_ISSUE_FIELD = "by_issue_field"
    IGNORE = "ignore"
    ERROR_IF_EMPTY = "error_if_empty"


@dataclass
class Worklog:
    """Apontamento de horas vindo do Clockwork Pro (1 worklog = 1 timesheet)."""

    worklog_id: str
    issue_key: str
    started: date
    time_spent_seconds: int
    issue_id: str | None = None
    jira_account_id: str | None = None
    author_display_name: str = ""
    clockwork_user_id: str | None = None
    comment: str = ""
    updated_at: datetime | None = None


@dataclass
class JiraIssue:
    """Issue do Jira com os campos necessários para a alocação."""

    issue_id: str
    key: str
    summary: str
    project_key: str
    status: str = ""
    assignee_account_id: str | None = None
    url: str = ""
    fields: dict = field(default_factory=dict)


@dataclass
class UserMapping:
    """De-para usuário Jira/Clockwork -> funcionário Odoo."""

    id: int
    jira_account_id: str
    odoo_employee_id: int | None = None
    odoo_user_id: int | None = None
    jira_display_name: str = ""
    jira_email: str = ""
    active: bool = True

    @property
    def is_complete(self) -> bool:
        """Um de-para só é utilizável quando aponta para um funcionário."""
        return bool(self.active and self.odoo_employee_id)


@dataclass
class ProjectMapping:
    """De-para projeto Jira -> projeto/conta analítica Odoo."""

    id: int
    jira_project_key: str
    allocation_mode: AllocationMode = AllocationMode.DIRECT_PROJECT
    odoo_project_id: int | None = None
    odoo_analytic_account_id: int | None = None
    decision_field_id: str = ""
    decision_field_name: str = ""
    active: bool = True


@dataclass
class FieldAllocation:
    """Regra de alocação por valor de campo da issue (projetos especiais)."""

    id: int
    jira_project_key: str
    jira_field_value: str
    odoo_project_id: int
    odoo_analytic_account_id: int
    active: bool = True


@dataclass
class AllocationResult:
    """Destino determinado para um worklog: projeto + conta analítica Odoo."""

    odoo_project_id: int
    odoo_analytic_account_id: int
    field_value: str = ""
