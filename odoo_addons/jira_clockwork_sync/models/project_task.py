from odoo import fields, models


class ProjectTask(models.Model):
    """Campos técnicos de rastreabilidade Jira na tarefa (seções 6 e 13).

    A busca de tarefa existente é feita por ``x_jira_issue_id`` (ID interno,
    estável), nunca apenas pela chave textual.
    """

    _inherit = "project.task"

    x_jira_issue_id = fields.Char(
        string="Jira Issue ID", index=True, copy=False, readonly=True
    )
    x_jira_issue_key = fields.Char(
        string="Jira Issue Key", index=True, copy=False, readonly=True
    )
    x_jira_issue_url = fields.Char(string="URL Jira", readonly=True)
    x_jira_project_key = fields.Char(string="Projeto Jira", readonly=True)
    x_jira_status = fields.Char(string="Status no Jira", readonly=True)
    x_integration_source = fields.Char(string="Origem da Integração", readonly=True)
    x_last_sync_at = fields.Datetime(string="Última Sincronização", readonly=True)

    _sql_constraints = [
        (
            "x_jira_issue_id_uniq",
            "unique(x_jira_issue_id)",
            "Já existe uma tarefa vinculada a esta issue do Jira.",
        ),
    ]
