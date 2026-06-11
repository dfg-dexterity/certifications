"""Fakes em memória que espelham as interfaces dos clientes reais."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from jira_odoo_sync.config import Settings
from jira_odoo_sync.models import (
    AllocationMode,
    FieldAllocation,
    JiraIssue,
    ProjectMapping,
    UserMapping,
    Worklog,
)


def make_settings(**overrides) -> Settings:
    base = dict(
        jira_base_url="https://example.atlassian.net",
        jira_email="bot@example.com",
        jira_api_token="token",
        clockwork_api_token="token",
        clockwork_base_url="https://api.clockwork.report/v1",
        odoo_url="https://odoo.example.com",
        odoo_db="db",
        odoo_username="bot",
        odoo_password="secret",
    )
    base.update(overrides)
    return Settings(**base)


class FakeJira:
    def __init__(self, issues: dict[str, JiraIssue], existing_worklogs: set | None = None):
        self.issues = issues
        # Conjunto de tuplas (issue_key, worklog_id) que ainda existem no Jira.
        self.existing_worklogs = existing_worklogs if existing_worklogs is not None else set()
        self.requested_fields: list = []

    def get_issues(self, issue_keys, extra_fields=()):
        self.requested_fields.append(tuple(extra_fields))
        wanted = set(issue_keys)
        return {key: issue for key, issue in self.issues.items() if key in wanted}

    def worklog_exists(self, issue_key, worklog_id):
        return (issue_key, str(worklog_id)) in self.existing_worklogs


class FakeClockwork:
    def __init__(self, worklogs: list[Worklog]):
        self.worklogs = worklogs

    def list_worklogs(self, starting_at: date, ending_at: date):
        return [w for w in self.worklogs if starting_at <= w.started <= ending_at]


class FakeOdoo:
    def __init__(
        self,
        user_mappings: dict[str, UserMapping] | None = None,
        project_mappings: dict[str, ProjectMapping] | None = None,
        field_allocations: dict[str, dict[str, FieldAllocation]] | None = None,
        params: dict[str, str] | None = None,
    ):
        self.user_mappings = user_mappings or {}
        self.project_mappings = project_mappings or {}
        self.field_allocations = field_allocations or {}
        self.params = params or {}
        self.tasks: dict[int, dict] = {}
        self.timesheets: dict[int, dict] = {}
        self.logs: list[dict] = []
        self.user_stubs: list[dict] = []
        self.task_updates: list[tuple[int, dict]] = []
        self.timesheet_updates: list[tuple[int, dict]] = []
        self._next_id = 1000

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    # ------------------------------------------------------------- de-paras
    def load_user_mappings(self):
        return dict(self.user_mappings)

    def load_project_mappings(self):
        return dict(self.project_mappings)

    def load_field_allocations(self):
        return {key: dict(value) for key, value in self.field_allocations.items()}

    def upsert_user_stub(self, jira_account_id, display_name="", email="", clockwork_user_id=None):
        for stub in self.user_stubs:
            if stub["jira_account_id"] == jira_account_id:
                return stub["id"]
        stub = {
            "id": self._new_id(),
            "jira_account_id": jira_account_id,
            "jira_display_name": display_name,
            "jira_email": email,
            "clockwork_user_id": clockwork_user_id,
        }
        self.user_stubs.append(stub)
        return stub["id"]

    def touch_user_last_worklog(self, mapping_ids, when):
        self.touched_users = (list(mapping_ids), when)

    def touch_project_last_sync(self, mapping_ids, when):
        self.touched_projects = (list(mapping_ids), when)

    # ------------------------------------------------------------ parâmetros
    def get_param(self, key):
        return self.params.get(key)

    def set_param(self, key, value):
        self.params[key] = value

    # --------------------------------------------------------------- tarefas
    def find_task_by_issue_id(self, jira_issue_id):
        for task_id, vals in self.tasks.items():
            if vals.get("x_jira_issue_id") == str(jira_issue_id):
                return {
                    "id": task_id,
                    "name": vals.get("name", ""),
                    "project_id": vals.get("project_id"),
                    "x_jira_status": vals.get("x_jira_status", ""),
                    "x_jira_issue_url": vals.get("x_jira_issue_url", ""),
                }
        return None

    def create_task(self, vals):
        task_id = self._new_id()
        self.tasks[task_id] = dict(vals)
        return task_id

    def update_task(self, task_id, vals):
        self.tasks[task_id].update(vals)
        self.task_updates.append((task_id, dict(vals)))

    # ------------------------------------------------------------ timesheets
    def find_timesheet_by_worklog_id(self, worklog_id):
        for line_id, vals in self.timesheets.items():
            if vals.get("x_external_worklog_id") == str(worklog_id):
                return {
                    "id": line_id,
                    "date": vals.get("date", ""),
                    "unit_amount": vals.get("unit_amount", 0.0),
                    "name": vals.get("name", ""),
                    "employee_id": vals.get("employee_id"),
                    "project_id": vals.get("project_id"),
                    "task_id": vals.get("task_id"),
                    "account_id": vals.get("account_id"),
                    "x_integration_status": vals.get("x_integration_status", ""),
                    "x_jira_issue_key": vals.get("x_jira_issue_key", ""),
                }
        return None

    def create_timesheet(self, vals):
        line_id = self._new_id()
        self.timesheets[line_id] = dict(vals)
        return line_id

    def update_timesheet(self, line_id, vals):
        self.timesheets[line_id].update(vals)
        self.timesheet_updates.append((line_id, dict(vals)))

    def cancel_timesheet(self, line_id, message, when):
        self.timesheets[line_id].update(
            {
                "unit_amount": 0.0,
                "x_integration_status": "cancelled_source",
                "x_integration_error_message": message,
            }
        )

    def search_timesheets_in_window(self, start, end):
        rows = []
        for line_id, vals in self.timesheets.items():
            if not vals.get("x_external_worklog_id"):
                continue
            line_date = datetime.strptime(vals["date"][:10], "%Y-%m-%d").date()
            if start <= line_date <= end:
                rows.append(
                    {
                        "id": line_id,
                        "date": vals["date"],
                        "x_external_worklog_id": str(vals["x_external_worklog_id"]),
                        "x_integration_status": vals.get("x_integration_status", ""),
                        "x_jira_issue_key": vals.get("x_jira_issue_key", ""),
                    }
                )
        return rows

    # -------------------------------------------------------------------- log
    def create_sync_log(self, vals):
        log_id = self._new_id()
        self.logs.append({"id": log_id, **vals})
        return log_id

    def resolve_error_logs(self, worklog_id, when):
        for row in self.logs:
            if row.get("worklog_id") == str(worklog_id) and row.get("status") != "success":
                row["status"] = "success"
                row["message"] = "Reprocessado com sucesso"

    def fetch_pending_logs(self):
        return [
            {"worklog_id": row["worklog_id"], "worklog_date": row.get("worklog_date", "")}
            for row in self.logs
            if row.get("status") == "pending" and row.get("worklog_id")
        ]


# --------------------------------------------------------------------- dados
@pytest.fixture
def tad_setup():
    """Cenário da seção 16, caso 2: projeto especial TAD por departamento."""
    users = {
        "ana-account-id": UserMapping(
            id=1, jira_account_id="ana-account-id", odoo_employee_id=12,
            jira_display_name="Ana",
        )
    }
    projects = {
        "TAD": ProjectMapping(
            id=10,
            jira_project_key="TAD",
            allocation_mode=AllocationMode.BY_ISSUE_FIELD,
            decision_field_id="customfield_10045",
            decision_field_name="Departamento",
        )
    }
    allocations = {
        "TAD": {
            "administrativo": FieldAllocation(
                id=100,
                jira_project_key="TAD",
                jira_field_value="Administrativo",
                odoo_project_id=70,
                odoo_analytic_account_id=81,
            ),
            "trm": FieldAllocation(
                id=101,
                jira_project_key="TAD",
                jira_field_value="TRM",
                odoo_project_id=70,
                odoo_analytic_account_id=80,
            ),
        }
    }
    issue = JiraIssue(
        issue_id="20001",
        key="TAD-458",
        summary="Criar procedimento interno de apontamento",
        project_key="TAD",
        status="Em andamento",
        url="https://example.atlassian.net/browse/TAD-458",
        fields={"customfield_10045": {"value": "Administrativo"}},
    )
    worklog = Worklog(
        worklog_id="555",
        issue_id="20001",
        issue_key="TAD-458",
        jira_account_id="ana-account-id",
        author_display_name="Ana",
        started=date(2026, 6, 5),
        time_spent_seconds=5400,
        comment="Revisão do procedimento",
    )
    return users, projects, allocations, issue, worklog
