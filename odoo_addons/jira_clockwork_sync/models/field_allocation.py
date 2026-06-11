from odoo import fields, models


class JiraIntegrationFieldAllocation(models.Model):
    """Alocação por valor de campo da issue (seção 5.2).

    Para projetos especiais (allocation_mode = BY_ISSUE_FIELD), cada valor
    possível do campo de decisão (ex.: Departamento = TRM, CLM, Administrativo)
    aponta para um projeto Odoo e uma conta analítica de destino.

    A comparação de valores feita pelo serviço é case-insensitive.
    """

    _name = "jira.integration.field.allocation"
    _description = "Integração Jira: Alocação por Campo da Issue"
    _order = "jira_project_key, jira_field_value"

    project_mapping_id = fields.Many2one(
        "jira.integration.project.mapping",
        string="De-Para do Projeto",
        required=True,
        ondelete="cascade",
        domain=[("allocation_mode", "=", "by_issue_field")],
    )
    jira_project_key = fields.Char(
        related="project_mapping_id.jira_project_key",
        string="Projeto Jira",
        store=True,
        index=True,
    )
    jira_field_id = fields.Char(
        related="project_mapping_id.decision_field_id",
        string="Campo Jira (ID)",
        store=True,
    )
    jira_field_name = fields.Char(
        related="project_mapping_id.decision_field_name",
        string="Campo Jira (Nome)",
        store=True,
    )
    jira_field_value = fields.Char(
        string="Valor do Campo", required=True, help="Ex.: TRM, Administrativo"
    )
    odoo_project_id = fields.Many2one(
        "project.project", string="Projeto Odoo Destino", required=True
    )
    odoo_analytic_account_id = fields.Many2one(
        "account.analytic.account", string="Conta Analítica Destino", required=True
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "project_value_uniq",
            "unique(project_mapping_id, jira_field_value)",
            "Já existe uma alocação para este projeto Jira com este valor de campo.",
        ),
    ]
