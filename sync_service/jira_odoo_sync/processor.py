"""Pipeline de sincronização (seção 15 da especificação).

Para cada worklog do Clockwork Pro dentro da janela:

1.  Identificar a issue Jira e buscar seus dados completos (em lote).
2.  Resolver o de-para de usuário (Jira Account ID -> funcionário Odoo).
3.  Resolver o de-para de projeto e a regra de alocação
    (DIRECT_PROJECT / BY_ISSUE_FIELD / IGNORE / ERROR_IF_EMPTY).
4.  Verificar competência fechada.
5.  Buscar ou criar a tarefa Odoo (chave: ``x_jira_issue_id``).
6.  Criar ou atualizar o timesheet (chave única: ``x_external_worklog_id``).
7.  Registrar log de sucesso/erro no Odoo.

Idempotência (RNF03): rodar duas vezes a mesma janela não duplica nada —
tarefas são localizadas por ``x_jira_issue_id`` e timesheets por
``x_external_worklog_id``; atualizações só acontecem quando algum valor
realmente mudou.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .allocation import AllocationEngine, AllocationError
from .clients.odoo import PARAM_CLOSED_UNTIL, PARAM_LAST_SYNC, odoo_datetime
from .config import Settings
from .models import (
    AllocationResult,
    IntegrationStatus,
    JiraIssue,
    UserMapping,
    Worklog,
)
from .period import is_in_closed_period, parse_closed_until
from .time_utils import seconds_to_hours

logger = logging.getLogger(__name__)

INTEGRATION_SOURCE = "jira_clockwork"

# Campos comparados para decidir se um timesheet existente precisa de update.
_COMPARABLE_FIELDS = (
    "date",
    "unit_amount",
    "name",
    "employee_id",
    "project_id",
    "task_id",
    "account_id",
)


@dataclass
class SyncStats:
    counts: dict = field(default_factory=dict)
    created_tasks: int = 0
    created_timesheets: int = 0
    updated_timesheets: int = 0
    unchanged: int = 0
    cancelled: int = 0
    errors: list = field(default_factory=list)

    def add(self, status: IntegrationStatus, detail: str = "") -> None:
        key = status.name
        self.counts[key] = self.counts.get(key, 0) + 1
        if detail and status not in (IntegrationStatus.SUCCESS, IntegrationStatus.SKIPPED):
            self.errors.append(f"[{key}] {detail}")

    def summary(self) -> str:
        parts = [f"{name}={count}" for name, count in sorted(self.counts.items())]
        parts.append(f"tarefas_criadas={self.created_tasks}")
        parts.append(f"timesheets_criados={self.created_timesheets}")
        parts.append(f"timesheets_atualizados={self.updated_timesheets}")
        parts.append(f"sem_alteracao={self.unchanged}")
        parts.append(f"cancelados={self.cancelled}")
        return " | ".join(parts)


def timesheet_description(issue_key: str, comment: str) -> str:
    """Padrão da seção 7.4: ``[JIRA_KEY] comentário`` ou texto padrão."""
    comment = (comment or "").strip()
    if comment:
        return f"[{issue_key}] {comment}"
    return f"[{issue_key}] Apontamento importado do Clockwork"


def task_name(issue: JiraIssue) -> str:
    """Padrão da seção 6.3: ``[JIRA_KEY] Summary``."""
    return f"[{issue.key}] {issue.summary}".strip()


class SyncProcessor:
    def __init__(self, odoo, jira, clockwork, settings: Settings):
        self.odoo = odoo
        self.jira = jira
        self.clockwork = clockwork
        self.settings = settings

    # ------------------------------------------------------------------- run
    def run_window(
        self,
        start: date,
        end: date,
        worklog_ids: set[str] | None = None,
    ) -> SyncStats:
        """Processa a janela [start, end]. ``worklog_ids`` filtra para
        reprocessamento seletivo (nesse caso a detecção de exclusões é
        desligada, pois a visão da janela fica incompleta)."""
        run_started = datetime.now(timezone.utc).replace(tzinfo=None)
        stats = SyncStats()

        users = self.odoo.load_user_mappings()
        projects = self.odoo.load_project_mappings()
        allocations = self.odoo.load_field_allocations()
        engine = AllocationEngine(projects, allocations)
        closed_until = parse_closed_until(self.odoo.get_param(PARAM_CLOSED_UNTIL))

        worklogs = self.clockwork.list_worklogs(start, end)
        if worklog_ids is not None:
            wanted = {str(w) for w in worklog_ids}
            worklogs = [w for w in worklogs if w.worklog_id in wanted]
        logger.info(
            "Janela %s..%s: %d worklog(s) para processar", start, end, len(worklogs)
        )

        decision_fields = sorted(
            {m.decision_field_id for m in projects.values() if m.decision_field_id}
        )
        issue_keys = {w.issue_key for w in worklogs if w.issue_key}
        issues = self.jira.get_issues(issue_keys, extra_fields=decision_fields)

        touched_users: set[int] = set()
        touched_projects: set[int] = set()
        for worklog in worklogs:
            try:
                self._process_worklog(
                    worklog,
                    issues,
                    users,
                    projects,
                    engine,
                    closed_until,
                    run_started,
                    stats,
                    touched_users,
                    touched_projects,
                )
            except Exception as exc:  # erro técnico inesperado: não derruba o lote
                logger.exception("Erro técnico ao processar worklog %s", worklog.worklog_id)
                self._log(
                    worklog,
                    IntegrationStatus.ERROR_ODOO,
                    f"Erro técnico: {exc}",
                    stats,
                )

        if worklog_ids is None:
            self._detect_deletions(worklogs, start, end, closed_until, run_started, stats)

        if not self.settings.dry_run:
            self.odoo.touch_user_last_worklog(sorted(touched_users), run_started)
            self.odoo.touch_project_last_sync(sorted(touched_projects), run_started)
            self.odoo.set_param(PARAM_LAST_SYNC, odoo_datetime(run_started))

        logger.info("Resumo: %s", stats.summary())
        return stats

    # -------------------------------------------------------------- pipeline
    def _process_worklog(
        self,
        worklog: Worklog,
        issues: dict[str, JiraIssue],
        users: dict[str, UserMapping],
        projects: dict,
        engine: AllocationEngine,
        closed_until: date | None,
        now: datetime,
        stats: SyncStats,
        touched_users: set[int],
        touched_projects: set[int],
    ) -> None:
        # 3.1/3.2 — issue
        issue = issues.get(worklog.issue_key)
        if issue is None:
            self._log(
                worklog,
                IntegrationStatus.ERROR_JIRA,
                f"Issue {worklog.issue_key or '(sem chave)'} não encontrada no Jira",
                stats,
            )
            return

        # 3.4/3.5 — usuário (Regra 2: precisa estar mapeado)
        user = users.get(worklog.jira_account_id or "")
        if user is None or not user.is_complete:
            if worklog.jira_account_id and not self.settings.dry_run:
                self.odoo.upsert_user_stub(
                    worklog.jira_account_id,
                    display_name=worklog.author_display_name,
                    clockwork_user_id=worklog.clockwork_user_id,
                )
            self._log(
                worklog,
                IntegrationStatus.ERROR_USER_MAPPING,
                "Usuário sem mapeamento para funcionário Odoo: "
                f"{worklog.author_display_name or worklog.jira_account_id or '(desconhecido)'}",
                stats,
                issue=issue,
            )
            return

        # 3.6/3.7/3.8 — projeto + conta analítica
        try:
            allocation = engine.resolve(issue)
        except AllocationError as exc:
            if exc.status == IntegrationStatus.SKIPPED:
                stats.add(IntegrationStatus.SKIPPED)
                logger.debug("Worklog %s ignorado: %s", worklog.worklog_id, exc.message)
            else:
                self._log(worklog, exc.status, exc.message, stats, issue=issue)
            return

        # 3.11 — timesheet existente (Regra 5: chave única por worklog)
        existing = self.odoo.find_timesheet_by_worklog_id(worklog.worklog_id)

        # 3.9 — competência fechada (Regra 6)
        if is_in_closed_period(worklog.started, closed_until):
            if existing and not self._values_changed_for_closed(
                existing, worklog, issue, user, allocation
            ):
                stats.unchanged += 1
                stats.add(IntegrationStatus.SUCCESS)
                return
            action = "alterado" if existing else "criado"
            self._log(
                worklog,
                IntegrationStatus.CLOSED_PERIOD,
                f"Apontamento em competência fechada (até {closed_until}) não pode "
                f"ser {action} automaticamente — pendente de aprovação administrativa",
                stats,
                issue=issue,
                field_value=allocation.field_value,
            )
            return

        # 3.10 — tarefa (Regra 7: nasce automaticamente)
        task_id = self._get_or_create_task(issue, allocation, now, stats)

        # 3.12 — criar/atualizar timesheet
        desired = self._build_timesheet_vals(worklog, issue, user, allocation, task_id, now)
        if existing:
            changes = {
                key: desired[key]
                for key in _COMPARABLE_FIELDS
                if self._normalize(desired.get(key)) != self._normalize(existing.get(key))
            }
            if changes:
                changes.update(
                    {
                        "x_integration_status": IntegrationStatus.SUCCESS.value,
                        "x_integration_error_message": False,
                        "x_last_sync_at": odoo_datetime(now),
                    }
                )
                if not self.settings.dry_run:
                    self.odoo.update_timesheet(existing["id"], changes)
                stats.updated_timesheets += 1
            else:
                stats.unchanged += 1
        else:
            if not self.settings.dry_run:
                self.odoo.create_timesheet(desired)
            stats.created_timesheets += 1

        if not self.settings.dry_run:
            self.odoo.resolve_error_logs(worklog.worklog_id, now)
        touched_users.add(user.id)
        mapping = projects.get(issue.project_key)
        if mapping is not None:
            touched_projects.add(mapping.id)
        stats.add(IntegrationStatus.SUCCESS)
        if self.settings.log_success:
            self._log(
                worklog,
                IntegrationStatus.SUCCESS,
                "Integrado com sucesso",
                stats,
                issue=issue,
                field_value=allocation.field_value,
                count=False,
            )

    # ---------------------------------------------------------------- tarefas
    def _get_or_create_task(
        self,
        issue: JiraIssue,
        allocation: AllocationResult,
        now: datetime,
        stats: SyncStats,
    ) -> int | None:
        existing = self.odoo.find_task_by_issue_id(issue.issue_id)
        if existing:
            updates: dict = {}
            new_name = task_name(issue)
            if new_name and existing.get("name") != new_name:
                updates["name"] = new_name
            if issue.status and existing.get("x_jira_status") != issue.status:
                updates["x_jira_status"] = issue.status
            if issue.url and existing.get("x_jira_issue_url") != issue.url:
                updates["x_jira_issue_url"] = issue.url
            if (
                self.settings.allow_task_project_update
                and existing.get("project_id") != allocation.odoo_project_id
            ):
                updates["project_id"] = allocation.odoo_project_id
            if updates:
                updates["x_last_sync_at"] = odoo_datetime(now)
                if not self.settings.dry_run:
                    self.odoo.update_task(existing["id"], updates)
            return existing["id"]

        vals = {
            "name": task_name(issue),
            "project_id": allocation.odoo_project_id,
            "description": (
                f'<p>Importado do Jira: <a href="{issue.url}">{issue.key}</a><br/>'
                f"Projeto Jira: {issue.project_key} | Status: {issue.status}</p>"
            ),
            "x_jira_issue_id": str(issue.issue_id),
            "x_jira_issue_key": issue.key,
            "x_jira_issue_url": issue.url,
            "x_jira_project_key": issue.project_key,
            "x_jira_status": issue.status,
            "x_integration_source": INTEGRATION_SOURCE,
            "x_last_sync_at": odoo_datetime(now),
        }
        stats.created_tasks += 1
        if self.settings.dry_run:
            return None
        return self.odoo.create_task(vals)

    # -------------------------------------------------------------- timesheets
    def _build_timesheet_vals(
        self,
        worklog: Worklog,
        issue: JiraIssue,
        user: UserMapping,
        allocation: AllocationResult,
        task_id: int | None,
        now: datetime,
    ) -> dict:
        return {
            "date": worklog.started.isoformat(),
            "unit_amount": seconds_to_hours(worklog.time_spent_seconds),
            "name": timesheet_description(issue.key, worklog.comment),
            "employee_id": user.odoo_employee_id,
            "project_id": allocation.odoo_project_id,
            "task_id": task_id,
            "account_id": allocation.odoo_analytic_account_id,
            "x_external_worklog_id": worklog.worklog_id,
            "x_jira_issue_id": str(issue.issue_id),
            "x_jira_issue_key": issue.key,
            "x_jira_account_id": worklog.jira_account_id,
            "x_clockwork_user_id": worklog.clockwork_user_id,
            "x_integration_status": IntegrationStatus.SUCCESS.value,
            "x_integration_error_message": False,
            "x_last_sync_at": odoo_datetime(now),
        }

    def _values_changed_for_closed(
        self,
        existing: dict,
        worklog: Worklog,
        issue: JiraIssue,
        user: UserMapping,
        allocation: AllocationResult,
    ) -> bool:
        """Em competência fechada, compara apenas o que pode ser comparado sem
        criar registros (a tarefa pode ainda não existir)."""
        desired = {
            "date": worklog.started.isoformat(),
            "unit_amount": seconds_to_hours(worklog.time_spent_seconds),
            "name": timesheet_description(issue.key, worklog.comment),
            "employee_id": user.odoo_employee_id,
            "project_id": allocation.odoo_project_id,
            "account_id": allocation.odoo_analytic_account_id,
        }
        return any(
            self._normalize(desired[key]) != self._normalize(existing.get(key))
            for key in desired
        )

    @staticmethod
    def _normalize(value):
        if value is None or value is False:
            return None
        if isinstance(value, float):
            return round(value, 2)
        return value

    # --------------------------------------------------------------- exclusões
    def _detect_deletions(
        self,
        worklogs: list[Worklog],
        start: date,
        end: date,
        closed_until: date | None,
        now: datetime,
        stats: SyncStats,
    ) -> None:
        """Seção 8.2 (Opção B): timesheets cuja origem sumiu são marcados como
        ``CANCELLED_SOURCE`` com horas zeradas — nunca excluídos fisicamente.

        Antes de cancelar, confirma no Jira que o worklog realmente não existe
        mais (ele pode apenas ter mudado de data para fora da janela)."""
        source_ids = {w.worklog_id for w in worklogs}
        for line in self.odoo.search_timesheets_in_window(start, end):
            worklog_id = line["x_external_worklog_id"]
            if worklog_id in source_ids:
                continue
            if line.get("x_integration_status") == IntegrationStatus.CANCELLED_SOURCE.value:
                continue
            issue_key = line.get("x_jira_issue_key")
            if issue_key:
                try:
                    if self.jira.worklog_exists(issue_key, worklog_id):
                        # Worklog ainda existe (provavelmente mudou de data);
                        # será sincronizado quando a janela cobrir a nova data.
                        continue
                except Exception as exc:
                    logger.warning(
                        "Não foi possível confirmar exclusão do worklog %s: %s",
                        worklog_id,
                        exc,
                    )
                    continue
            line_date = datetime.strptime(line["date"][:10], "%Y-%m-%d").date()
            if is_in_closed_period(line_date, closed_until):
                self._log_raw(
                    worklog_id=worklog_id,
                    issue_key=issue_key or "",
                    status=IntegrationStatus.CLOSED_PERIOD,
                    message=(
                        "Worklog excluído na origem, mas a competência está "
                        f"fechada (até {closed_until}) — requer tratamento manual"
                    ),
                    worklog_date=line_date,
                    stats=stats,
                    timesheet_id=line["id"],
                )
                continue
            if not self.settings.dry_run:
                self.odoo.cancel_timesheet(
                    line["id"],
                    "Worklog excluído no Jira/Clockwork — horas zeradas pela integração",
                    now,
                )
            stats.cancelled += 1
            self._log_raw(
                worklog_id=worklog_id,
                issue_key=issue_key or "",
                status=IntegrationStatus.CANCELLED_SOURCE,
                message="Worklog excluído na origem; timesheet cancelado (horas zeradas)",
                worklog_date=line_date,
                stats=stats,
                timesheet_id=line["id"],
            )

    # --------------------------------------------------------------------- log
    def _log(
        self,
        worklog: Worklog,
        status: IntegrationStatus,
        message: str,
        stats: SyncStats,
        issue: JiraIssue | None = None,
        field_value: str = "",
        count: bool = True,
    ) -> None:
        if count:
            stats.add(status, f"worklog {worklog.worklog_id}: {message}")
        level = logging.INFO if status == IntegrationStatus.SUCCESS else logging.WARNING
        logger.log(level, "worklog %s [%s]: %s", worklog.worklog_id, status.name, message)
        if self.settings.dry_run:
            return
        self.odoo.create_sync_log(
            {
                "worklog_id": worklog.worklog_id,
                "jira_issue_key": issue.key if issue else worklog.issue_key,
                "jira_issue_id": issue.issue_id if issue else (worklog.issue_id or ""),
                "jira_project_key": issue.project_key if issue else "",
                "jira_account_id": worklog.jira_account_id or "",
                "jira_display_name": worklog.author_display_name,
                "field_value": field_value,
                "worklog_date": worklog.started.isoformat(),
                "hours": seconds_to_hours(worklog.time_spent_seconds),
                "status": status.value,
                "message": message,
            }
        )

    def _log_raw(
        self,
        worklog_id: str,
        issue_key: str,
        status: IntegrationStatus,
        message: str,
        worklog_date: date,
        stats: SyncStats,
        timesheet_id: int | None = None,
    ) -> None:
        stats.add(status, f"worklog {worklog_id}: {message}")
        logger.warning("worklog %s [%s]: %s", worklog_id, status.name, message)
        if self.settings.dry_run:
            return
        vals = {
            "worklog_id": worklog_id,
            "jira_issue_key": issue_key,
            "worklog_date": worklog_date.isoformat(),
            "status": status.value,
            "message": message,
        }
        if timesheet_id:
            vals["timesheet_id"] = timesheet_id
        self.odoo.create_sync_log(vals)
