"""Motor de alocação: determina projeto Odoo + conta analítica para cada worklog.

Implementa a cadeia crítica da especificação (seções 5 e 22):

    Issue -> Projeto Jira -> Regra de alocação -> Projeto Odoo -> Conta Analítica

Modos suportados (campo ``allocation_mode`` do de-para de projetos):

* ``DIRECT_PROJECT``  — usa projeto/conta analítica padrão do de-para.
* ``BY_ISSUE_FIELD``  — lê um campo customizado do ticket (ex.: Departamento)
  e busca a combinação (projeto Jira + valor) na tabela de alocação por campo.
* ``IGNORE``          — projeto não integra (worklogs são pulados).
* ``ERROR_IF_EMPTY``  — usa o destino padrão do projeto, mas exige que o campo
  de decisão esteja preenchido na issue; se vazio, gera erro (qualidade de dados).

A regra NUNCA cai em conta genérica: sem combinação cadastrada, o worklog
não integra e vira pendência de manutenção de de-para (seção 18.5).
"""
from __future__ import annotations

from .models import (
    AllocationMode,
    AllocationResult,
    FieldAllocation,
    IntegrationStatus,
    JiraIssue,
    ProjectMapping,
)


class AllocationError(Exception):
    """Falha de alocação com status de integração associado."""

    def __init__(self, status: IntegrationStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def normalize_field_value(raw) -> str:
    """Extrai o valor textual de um campo customizado do Jira.

    Campos de seleção vêm como ``{"value": "TRM", ...}``; campos de
    múltipla escolha vêm como lista; campos de texto vêm como string.
    """
    if raw is None or raw is False:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("value", "name", "displayName"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if isinstance(raw, (list, tuple)):
        parts = [normalize_field_value(item) for item in raw]
        return ", ".join(part for part in parts if part)
    return str(raw).strip()


class AllocationEngine:
    def __init__(
        self,
        project_mappings: dict[str, ProjectMapping],
        field_allocations: dict[str, dict[str, FieldAllocation]],
    ):
        """``field_allocations`` é indexado por projeto Jira e, dentro dele,
        pelo valor do campo normalizado com ``str.casefold()``."""
        self.project_mappings = project_mappings
        self.field_allocations = field_allocations

    def resolve(self, issue: JiraIssue) -> AllocationResult:
        mapping = self.project_mappings.get(issue.project_key)
        if mapping is None:
            raise AllocationError(
                IntegrationStatus.ERROR_PROJECT_MAPPING,
                f"Projeto Jira '{issue.project_key}' sem de-para cadastrado",
            )
        if not mapping.active:
            # Regra 1: projeto inativo no de-para -> ignorar worklogs.
            raise AllocationError(
                IntegrationStatus.SKIPPED,
                f"Projeto Jira '{issue.project_key}' inativo no de-para",
            )

        mode = mapping.allocation_mode
        if mode == AllocationMode.IGNORE:
            raise AllocationError(
                IntegrationStatus.SKIPPED,
                f"Projeto Jira '{issue.project_key}' marcado como IGNORE",
            )
        if mode == AllocationMode.DIRECT_PROJECT:
            return self._resolve_direct(issue, mapping)
        if mode == AllocationMode.ERROR_IF_EMPTY:
            field_value = self._read_decision_field(issue, mapping)
            result = self._resolve_direct(issue, mapping)
            result.field_value = field_value
            return result
        if mode == AllocationMode.BY_ISSUE_FIELD:
            return self._resolve_by_field(issue, mapping)
        raise AllocationError(
            IntegrationStatus.ERROR_PROJECT_MAPPING,
            f"allocation_mode desconhecido para '{issue.project_key}': {mode}",
        )

    def _resolve_direct(self, issue: JiraIssue, mapping: ProjectMapping) -> AllocationResult:
        if not mapping.odoo_project_id or not mapping.odoo_analytic_account_id:
            raise AllocationError(
                IntegrationStatus.ERROR_PROJECT_MAPPING,
                f"De-para do projeto '{issue.project_key}' sem projeto Odoo "
                "ou conta analítica padrão configurados",
            )
        return AllocationResult(
            odoo_project_id=mapping.odoo_project_id,
            odoo_analytic_account_id=mapping.odoo_analytic_account_id,
        )

    def _read_decision_field(self, issue: JiraIssue, mapping: ProjectMapping) -> str:
        if not mapping.decision_field_id:
            raise AllocationError(
                IntegrationStatus.ERROR_PROJECT_MAPPING,
                f"De-para do projeto '{issue.project_key}' não define o campo "
                "Jira de decisão (jira_field_id)",
            )
        field_value = normalize_field_value(issue.fields.get(mapping.decision_field_id))
        if not field_value:
            field_label = mapping.decision_field_name or mapping.decision_field_id
            raise AllocationError(
                IntegrationStatus.ERROR_ANALYTIC_MAPPING,
                f"Campo obrigatório '{field_label}' não preenchido na issue "
                f"{issue.key} — corrigir no Jira",
            )
        return field_value

    def _resolve_by_field(self, issue: JiraIssue, mapping: ProjectMapping) -> AllocationResult:
        field_value = self._read_decision_field(issue, mapping)
        allocation = self.field_allocations.get(issue.project_key, {}).get(field_value.casefold())
        if allocation is None or not allocation.active:
            field_label = mapping.decision_field_name or mapping.decision_field_id
            raise AllocationError(
                IntegrationStatus.ERROR_ANALYTIC_MAPPING,
                f"Sem alocação cadastrada para projeto '{issue.project_key}' + "
                f"{field_label}='{field_value}' (issue {issue.key}) — "
                "cadastrar na tabela de alocação por campo",
            )
        return AllocationResult(
            odoo_project_id=allocation.odoo_project_id,
            odoo_analytic_account_id=allocation.odoo_analytic_account_id,
            field_value=field_value,
        )
