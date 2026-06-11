from odoo import fields, models


class ProjectProject(models.Model):
    """Campos informativos de integração no projeto Odoo (seção 13)."""

    _inherit = "project.project"

    x_jira_project_key = fields.Char(
        string="Projeto Jira (Key)",
        help="Preenchido para referência. O controle efetivo da integração "
        "fica no de-para de projetos (Integração Jira > De-Para > Projetos).",
    )
    x_integration_enabled = fields.Boolean(
        string="Recebe integração Jira", default=False
    )
