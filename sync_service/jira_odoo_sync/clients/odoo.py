"""Cliente Odoo via XML-RPC (External API).

Responsável por:
* Carregar os de-paras mantidos no addon ``jira_clockwork_sync``.
* Criar/atualizar tarefas (``project.task``) e timesheets
  (``account.analytic.line``) com os campos técnicos ``x_*``.
* Registrar o log de integração (``jira.integration.sync.log``).
* Ler/gravar parâmetros (última sincronização, competência fechada).

O usuário de API no Odoo precisa de acesso de escrita a projetos,
timesheets e aos modelos do addon (grupo "Integração Jira / Gestor"),
além de leitura/escrita em ``ir.config_parameter`` (grupo Configurações).
"""
from __future__ import annotations

import xmlrpc.client
from datetime import date, datetime

from ..models import (
    AllocationMode,
    FieldAllocation,
    ProjectMapping,
    UserMapping,
)

PARAM_LAST_SYNC = "jira_clockwork_sync.last_sync_at"
PARAM_CLOSED_UNTIL = "jira_clockwork_sync.closed_until"

_ERROR_LIKE_STATUSES = [
    "pending",
    "error_user_mapping",
    "error_project_mapping",
    "error_analytic_mapping",
    "error_odoo",
    "error_jira",
    "closed_period",
]


class OdooError(Exception):
    pass


def _m2o_id(value) -> int | None:
    """XML-RPC retorna many2one como ``[id, "nome"]`` ou ``False``."""
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if isinstance(value, int):
        return value
    return None


def odoo_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


class OdooClient:
    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self._uid: int | None = None
        self._common = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common", allow_none=True
        )
        self._models = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", allow_none=True
        )

    # ------------------------------------------------------------------- rpc
    def login(self) -> int:
        if self._uid is None:
            try:
                uid = self._common.authenticate(self.db, self.username, self.password, {})
            except Exception as exc:  # xmlrpc levanta Fault/ProtocolError/OSError
                raise OdooError(f"Falha de comunicação com o Odoo: {exc}") from exc
            if not uid:
                raise OdooError(
                    f"Autenticação no Odoo recusada para '{self.username}' "
                    f"(db={self.db})"
                )
            self._uid = int(uid)
        return self._uid

    def execute(self, model: str, method: str, args: list, kwargs: dict | None = None):
        uid = self.login()
        try:
            return self._models.execute_kw(
                self.db, uid, self.password, model, method, args, kwargs or {}
            )
        except xmlrpc.client.Fault as exc:
            raise OdooError(f"Odoo {model}.{method}: {exc.faultString}") from exc
        except Exception as exc:
            raise OdooError(f"Falha de comunicação com o Odoo ({model}.{method}): {exc}") from exc

    def search_read(
        self, model: str, domain: list, fields: list[str], limit: int | None = None
    ) -> list[dict]:
        kwargs: dict = {"fields": fields}
        if limit:
            kwargs["limit"] = limit
        return self.execute(model, "search_read", [domain], kwargs)

    # ------------------------------------------------------------- de-paras
    def load_user_mappings(self) -> dict[str, UserMapping]:
        rows = self.search_read(
            "jira.integration.user.mapping",
            [["active", "=", True]],
            [
                "jira_account_id",
                "jira_display_name",
                "jira_email",
                "odoo_employee_id",
                "odoo_user_id",
            ],
        )
        mappings: dict[str, UserMapping] = {}
        for row in rows:
            mapping = UserMapping(
                id=row["id"],
                jira_account_id=row["jira_account_id"] or "",
                odoo_employee_id=_m2o_id(row["odoo_employee_id"]),
                odoo_user_id=_m2o_id(row["odoo_user_id"]),
                jira_display_name=row["jira_display_name"] or "",
                jira_email=row["jira_email"] or "",
                active=True,
            )
            if mapping.jira_account_id:
                mappings[mapping.jira_account_id] = mapping
        return mappings

    def load_project_mappings(self) -> dict[str, ProjectMapping]:
        # Inclui inativos: o motor de alocação precisa diferenciar
        # "sem de-para" (erro) de "de-para inativo" (ignorar, Regra 1).
        rows = self.execute(
            "jira.integration.project.mapping",
            "search_read",
            [[]],
            {
                "fields": [
                    "jira_project_key",
                    "allocation_mode",
                    "odoo_project_id",
                    "odoo_analytic_account_id",
                    "decision_field_id",
                    "decision_field_name",
                    "active",
                ],
                "context": {"active_test": False},
            },
        )
        mappings: dict[str, ProjectMapping] = {}
        for row in rows:
            key = row["jira_project_key"] or ""
            if not key:
                continue
            mappings[key] = ProjectMapping(
                id=row["id"],
                jira_project_key=key,
                allocation_mode=AllocationMode(row["allocation_mode"]),
                odoo_project_id=_m2o_id(row["odoo_project_id"]),
                odoo_analytic_account_id=_m2o_id(row["odoo_analytic_account_id"]),
                decision_field_id=row["decision_field_id"] or "",
                decision_field_name=row["decision_field_name"] or "",
                active=bool(row["active"]),
            )
        return mappings

    def load_field_allocations(self) -> dict[str, dict[str, FieldAllocation]]:
        rows = self.search_read(
            "jira.integration.field.allocation",
            [["active", "=", True]],
            [
                "jira_project_key",
                "jira_field_value",
                "odoo_project_id",
                "odoo_analytic_account_id",
            ],
        )
        allocations: dict[str, dict[str, FieldAllocation]] = {}
        for row in rows:
            allocation = FieldAllocation(
                id=row["id"],
                jira_project_key=row["jira_project_key"] or "",
                jira_field_value=row["jira_field_value"] or "",
                odoo_project_id=_m2o_id(row["odoo_project_id"]) or 0,
                odoo_analytic_account_id=_m2o_id(row["odoo_analytic_account_id"]) or 0,
                active=True,
            )
            if allocation.jira_project_key and allocation.jira_field_value:
                allocations.setdefault(allocation.jira_project_key, {})[
                    allocation.jira_field_value.casefold()
                ] = allocation
        return allocations

    def upsert_user_stub(
        self,
        jira_account_id: str,
        display_name: str = "",
        email: str = "",
        clockwork_user_id: str | None = None,
    ) -> int:
        """Garante uma linha de de-para para o usuário desconhecido.

        A linha nasce SEM funcionário Odoo: aparece na tela de manutenção
        no filtro "Sem vínculo" para o gestor completar (seção 11.1).
        """
        rows = self.execute(
            "jira.integration.user.mapping",
            "search_read",
            [[["jira_account_id", "=", jira_account_id]]],
            {
                "fields": ["id", "jira_display_name", "jira_email"],
                "limit": 1,
                "context": {"active_test": False},
            },
        )
        if rows:
            row = rows[0]
            updates = {}
            if display_name and not row.get("jira_display_name"):
                updates["jira_display_name"] = display_name
            if email and not row.get("jira_email"):
                updates["jira_email"] = email
            if updates:
                self.execute(
                    "jira.integration.user.mapping", "write", [[row["id"]], updates]
                )
            return row["id"]
        return self.execute(
            "jira.integration.user.mapping",
            "create",
            [
                {
                    "jira_account_id": jira_account_id,
                    "jira_display_name": display_name,
                    "jira_email": email,
                    "clockwork_user_id": clockwork_user_id,
                }
            ],
        )

    def touch_user_last_worklog(self, mapping_ids: list[int], when: datetime) -> None:
        if mapping_ids:
            self.execute(
                "jira.integration.user.mapping",
                "write",
                [mapping_ids, {"last_worklog_at": odoo_datetime(when)}],
            )

    def touch_project_last_sync(self, mapping_ids: list[int], when: datetime) -> None:
        if mapping_ids:
            self.execute(
                "jira.integration.project.mapping",
                "write",
                [mapping_ids, {"last_sync_at": odoo_datetime(when)}],
            )

    # -------------------------------------------------------------- parâmetros
    def get_param(self, key: str) -> str | None:
        rows = self.search_read("ir.config_parameter", [["key", "=", key]], ["value"], limit=1)
        if rows and rows[0].get("value"):
            return str(rows[0]["value"])
        return None

    def set_param(self, key: str, value: str) -> None:
        rows = self.search_read("ir.config_parameter", [["key", "=", key]], ["id"], limit=1)
        if rows:
            self.execute("ir.config_parameter", "write", [[rows[0]["id"]], {"value": value}])
        else:
            self.execute("ir.config_parameter", "create", [{"key": key, "value": value}])

    # ----------------------------------------------------------------- tarefas
    def find_task_by_issue_id(self, jira_issue_id: str) -> dict | None:
        rows = self.search_read(
            "project.task",
            [["x_jira_issue_id", "=", str(jira_issue_id)]],
            ["name", "project_id", "x_jira_status", "x_jira_issue_url"],
            limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "id": row["id"],
            "name": row["name"] or "",
            "project_id": _m2o_id(row["project_id"]),
            "x_jira_status": row["x_jira_status"] or "",
            "x_jira_issue_url": row["x_jira_issue_url"] or "",
        }

    def create_task(self, vals: dict) -> int:
        return self.execute("project.task", "create", [vals])

    def update_task(self, task_id: int, vals: dict) -> None:
        self.execute("project.task", "write", [[task_id], vals])

    # -------------------------------------------------------------- timesheets
    def find_timesheet_by_worklog_id(self, worklog_id: str) -> dict | None:
        rows = self.search_read(
            "account.analytic.line",
            [["x_external_worklog_id", "=", str(worklog_id)]],
            [
                "date",
                "unit_amount",
                "name",
                "employee_id",
                "project_id",
                "task_id",
                "account_id",
                "x_integration_status",
                "x_jira_issue_key",
            ],
            limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "id": row["id"],
            "date": str(row["date"]) if row["date"] else "",
            "unit_amount": float(row["unit_amount"] or 0.0),
            "name": row["name"] or "",
            "employee_id": _m2o_id(row["employee_id"]),
            "project_id": _m2o_id(row["project_id"]),
            "task_id": _m2o_id(row["task_id"]),
            "account_id": _m2o_id(row["account_id"]),
            "x_integration_status": row["x_integration_status"] or "",
            "x_jira_issue_key": row["x_jira_issue_key"] or "",
        }

    def create_timesheet(self, vals: dict) -> int:
        return self.execute("account.analytic.line", "create", [vals])

    def update_timesheet(self, line_id: int, vals: dict) -> None:
        self.execute("account.analytic.line", "write", [[line_id], vals])

    def cancel_timesheet(self, line_id: int, message: str, when: datetime) -> None:
        """Opção B da seção 8.2: marca como cancelado na origem e zera horas."""
        self.execute(
            "account.analytic.line",
            "write",
            [
                [line_id],
                {
                    "unit_amount": 0.0,
                    "x_integration_status": "cancelled_source",
                    "x_integration_error_message": message,
                    "x_last_sync_at": odoo_datetime(when),
                },
            ],
        )

    def search_timesheets_in_window(self, start: date, end: date) -> list[dict]:
        rows = self.search_read(
            "account.analytic.line",
            [
                ["x_external_worklog_id", "!=", False],
                ["date", ">=", start.isoformat()],
                ["date", "<=", end.isoformat()],
            ],
            ["date", "x_external_worklog_id", "x_integration_status", "x_jira_issue_key"],
        )
        return [
            {
                "id": row["id"],
                "date": str(row["date"]) if row["date"] else "",
                "x_external_worklog_id": str(row["x_external_worklog_id"]),
                "x_integration_status": row["x_integration_status"] or "",
                "x_jira_issue_key": row["x_jira_issue_key"] or "",
            }
            for row in rows
        ]

    # --------------------------------------------------------------------- log
    def create_sync_log(self, vals: dict) -> int:
        return self.execute("jira.integration.sync.log", "create", [vals])

    def resolve_error_logs(self, worklog_id: str, when: datetime) -> None:
        """Após sucesso, fecha pendências antigas do mesmo worklog."""
        ids = self.execute(
            "jira.integration.sync.log",
            "search",
            [
                [
                    ["worklog_id", "=", str(worklog_id)],
                    ["status", "in", _ERROR_LIKE_STATUSES],
                ]
            ],
        )
        if ids:
            self.execute(
                "jira.integration.sync.log",
                "write",
                [
                    ids,
                    {
                        "status": "success",
                        "message": "Reprocessado com sucesso em "
                        + odoo_datetime(when),
                    },
                ],
            )

    def fetch_pending_logs(self) -> list[dict]:
        """Linhas marcadas para reprocesso na tela de erros (status PENDING)."""
        rows = self.search_read(
            "jira.integration.sync.log",
            [["status", "=", "pending"], ["worklog_id", "!=", False]],
            ["worklog_id", "worklog_date"],
        )
        return [
            {
                "worklog_id": str(row["worklog_id"]),
                "worklog_date": str(row["worklog_date"]) if row["worklog_date"] else "",
            }
            for row in rows
        ]
