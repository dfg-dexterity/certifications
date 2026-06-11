from odoo import fields, models

from .sync_log import INTEGRATION_STATUSES


class AccountAnalyticLine(models.Model):
    """Campos técnicos do timesheet importado (seções 7 e 13).

    ``x_external_worklog_id`` é a chave única que garante a idempotência
    (Regra 5): 1 worklog Clockwork/Jira = 1 linha de timesheet no Odoo.
    """

    _inherit = "account.analytic.line"

    x_external_worklog_id = fields.Char(
        string="External Worklog ID", index=True, copy=False, readonly=True
    )
    x_jira_issue_id = fields.Char(string="Jira Issue ID", readonly=True)
    x_jira_issue_key = fields.Char(string="Jira Issue Key", index=True, readonly=True)
    x_clockwork_user_id = fields.Char(string="Clockwork User ID", readonly=True)
    x_jira_account_id = fields.Char(string="Jira Account ID", readonly=True)
    x_integration_status = fields.Selection(
        INTEGRATION_STATUSES, string="Status Integração", readonly=True
    )
    x_integration_error_message = fields.Text(
        string="Mensagem da Integração", readonly=True
    )
    x_last_sync_at = fields.Datetime(string="Última Sincronização", readonly=True)

    _sql_constraints = [
        (
            "x_external_worklog_id_uniq",
            "unique(x_external_worklog_id)",
            "Já existe um apontamento com este External Worklog ID.",
        ),
    ]
