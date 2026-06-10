from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class JiraIntegrationProjectMapping(models.Model):
    """De-para de projetos Jira x projetos/contas analíticas Odoo (seção 4.2)."""

    _name = "jira.integration.project.mapping"
    _description = "Integração Jira: De-Para de Projetos"
    _order = "jira_project_key"

    jira_project_key = fields.Char(
        string="Projeto Jira (Key)", required=True, index=True, help="Ex.: TAD, CDV"
    )
    jira_project_id = fields.Char(string="Projeto Jira (ID)")
    jira_project_name = fields.Char(string="Nome no Jira")
    odoo_project_id = fields.Many2one("project.project", string="Projeto Odoo")
    odoo_analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Conta Analítica Padrão",
        help="Usada nos modos DIRECT_PROJECT e ERROR_IF_EMPTY.",
    )
    allocation_mode = fields.Selection(
        [
            ("direct_project", "DIRECT_PROJECT — Projeto direto"),
            ("by_issue_field", "BY_ISSUE_FIELD — Por campo da issue"),
            ("ignore", "IGNORE — Não integrar"),
            (
                "error_if_empty",
                "ERROR_IF_EMPTY — Integrar somente com campo obrigatório preenchido",
            ),
        ],
        string="Modo de Alocação",
        required=True,
        default="direct_project",
    )
    decision_field_id = fields.Char(
        string="Campo Jira de decisão (ID)",
        help="ID técnico do campo customizado no Jira, ex.: customfield_10045. "
        "Obrigatório nos modos BY_ISSUE_FIELD e ERROR_IF_EMPTY.",
    )
    decision_field_name = fields.Char(
        string="Campo Jira de decisão (Nome)", help="Nome amigável, ex.: Departamento"
    )
    field_allocation_ids = fields.One2many(
        "jira.integration.field.allocation",
        "project_mapping_id",
        string="Alocações por valor de campo",
    )
    active = fields.Boolean(
        default=True,
        help="Regra 1: projetos inativos têm seus worklogs ignorados pela integração.",
    )
    last_sync_at = fields.Datetime(string="Última sincronização", readonly=True)

    _sql_constraints = [
        (
            "jira_project_key_uniq",
            "unique(jira_project_key)",
            "Já existe um mapeamento para este projeto Jira.",
        ),
    ]

    @api.constrains(
        "allocation_mode",
        "odoo_project_id",
        "odoo_analytic_account_id",
        "decision_field_id",
    )
    def _check_allocation_mode(self):
        for record in self:
            if record.allocation_mode in ("direct_project", "error_if_empty") and (
                not record.odoo_project_id or not record.odoo_analytic_account_id
            ):
                raise ValidationError(
                    _(
                        "No modo %s o projeto Odoo e a conta analítica padrão "
                        "são obrigatórios (projeto Jira: %s).",
                        record.allocation_mode.upper(),
                        record.jira_project_key,
                    )
                )
            if (
                record.allocation_mode in ("by_issue_field", "error_if_empty")
                and not record.decision_field_id
            ):
                raise ValidationError(
                    _(
                        "No modo %s é obrigatório informar o campo Jira de "
                        "decisão (projeto Jira: %s).",
                        record.allocation_mode.upper(),
                        record.jira_project_key,
                    )
                )
