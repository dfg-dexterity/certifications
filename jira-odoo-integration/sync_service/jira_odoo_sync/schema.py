"""Perfis de esquema do Odoo.

O serviço funciona com dois layouts de banco no Odoo:

* ``addon``  — modelos do addon ``jira_clockwork_sync`` (Odoo.sh/on-premise).
* ``studio`` — modelos e campos criados manualmente via Odoo Studio /
  Técnico > Modelos (Odoo **Online**, que não permite instalar addons
  customizados). Modelos e campos customizados no Online precisam do
  prefixo ``x_``; o guia de criação está em ``docs/odoo-online-studio.md``.

O restante do serviço usa sempre os nomes lógicos (iguais aos do addon);
a tradução para os nomes técnicos acontece somente em ``clients/odoo.py``.

Os campos ``x_*`` de ``project.task``, ``account.analytic.line`` e
``project.project`` são idênticos nos dois perfis (a especificação já os
definia com prefixo ``x_``), então não precisam de tradução.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSchema:
    model: str
    fields: dict
    # Modelos customizados (Studio) têm um campo x_name obrigatório usado
    # como nome de exibição; o cliente preenche um valor padrão ao criar.
    name_field: str | None = None
    _reverse: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        object.__setattr__(
            self, "_reverse", {tech: logical for logical, tech in self.fields.items()}
        )

    def tech(self, logical_name: str) -> str:
        return self.fields.get(logical_name, logical_name)

    def logical(self, technical_name: str) -> str:
        return self._reverse.get(technical_name, technical_name)


@dataclass(frozen=True)
class OdooSchema:
    name: str
    user_mapping: ModelSchema
    project_mapping: ModelSchema
    field_allocation: ModelSchema
    sync_log: ModelSchema


def translate_domain(ms: ModelSchema, domain: list) -> list:
    """Traduz os nomes de campo das triplas de um domínio Odoo."""
    translated = []
    for item in domain:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            translated.append([ms.tech(item[0]), item[1], item[2]])
        else:
            translated.append(item)  # operadores '|', '&', '!'
    return translated


def translate_vals(ms: ModelSchema, vals: dict) -> dict:
    return {ms.tech(key): value for key, value in vals.items()}


def translate_row(ms: ModelSchema, row: dict) -> dict:
    return {ms.logical(key): value for key, value in row.items()}


def _identity(model: str, logical_fields: list[str]) -> ModelSchema:
    return ModelSchema(model=model, fields={name: name for name in logical_fields})


_USER_FIELDS = [
    "jira_account_id",
    "jira_display_name",
    "jira_email",
    "clockwork_user_id",
    "odoo_employee_id",
    "odoo_user_id",
    "active",
    "last_worklog_at",
]
_PROJECT_FIELDS = [
    "jira_project_key",
    "jira_project_id",
    "jira_project_name",
    "allocation_mode",
    "odoo_project_id",
    "odoo_analytic_account_id",
    "decision_field_id",
    "decision_field_name",
    "active",
    "last_sync_at",
]
_ALLOCATION_FIELDS = [
    "jira_project_key",
    "jira_field_value",
    "odoo_project_id",
    "odoo_analytic_account_id",
    "active",
]
_LOG_FIELDS = [
    "worklog_id",
    "jira_issue_key",
    "jira_issue_id",
    "jira_project_key",
    "jira_account_id",
    "jira_display_name",
    "field_value",
    "worklog_date",
    "hours",
    "status",
    "message",
    "task_id",
    "timesheet_id",
]

ADDON_SCHEMA = OdooSchema(
    name="addon",
    user_mapping=_identity("jira.integration.user.mapping", _USER_FIELDS),
    project_mapping=_identity("jira.integration.project.mapping", _PROJECT_FIELDS),
    field_allocation=_identity("jira.integration.field.allocation", _ALLOCATION_FIELDS),
    sync_log=_identity("jira.integration.sync.log", _LOG_FIELDS),
)


def _studio(model: str, logical_fields: list[str]) -> ModelSchema:
    return ModelSchema(
        model=model,
        fields={name: f"x_{name}" for name in logical_fields},
        name_field="x_name",
    )


STUDIO_SCHEMA = OdooSchema(
    name="studio",
    user_mapping=_studio("x_jira_user_map", _USER_FIELDS),
    project_mapping=_studio("x_jira_project_map", _PROJECT_FIELDS),
    field_allocation=_studio("x_jira_field_alloc", _ALLOCATION_FIELDS),
    sync_log=_studio("x_jira_sync_log", _LOG_FIELDS),
)

_SCHEMAS = {schema.name: schema for schema in (ADDON_SCHEMA, STUDIO_SCHEMA)}


def get_schema(name: str) -> OdooSchema:
    try:
        return _SCHEMAS[name.strip().lower()]
    except KeyError:
        raise ValueError(
            f"ODOO_SCHEMA inválido: {name!r} (use 'addon' ou 'studio')"
        ) from None
