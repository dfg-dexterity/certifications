from odoo import fields, models

INTEGRATION_STATUSES = [
    ("pending", "PENDING — Aguardando (re)processamento"),
    ("success", "SUCCESS — Integrado com sucesso"),
    ("error_user_mapping", "ERROR_USER_MAPPING — Usuário sem de-para"),
    ("error_project_mapping", "ERROR_PROJECT_MAPPING — Projeto sem de-para"),
    ("error_analytic_mapping", "ERROR_ANALYTIC_MAPPING — Conta analítica não determinada"),
    ("error_odoo", "ERROR_ODOO — Erro técnico no Odoo"),
    ("error_jira", "ERROR_JIRA — Erro técnico no Jira/Clockwork"),
    ("skipped", "SKIPPED — Ignorado por regra"),
    ("closed_period", "CLOSED_PERIOD — Competência fechada"),
    ("cancelled_source", "CANCELLED_SOURCE — Excluído/cancelado na origem"),
]


class JiraIntegrationSyncLog(models.Model):
    """Log de integração e fila de erros (seções 10 e 11.4).

    Fluxo de reprocessamento: o gestor corrige o de-para, clica em
    "Reprocessar" (status volta a PENDING) e o serviço de sincronização
    recolhe os pendentes na próxima execução de
    ``jira-odoo-sync reprocess --from-pending``. Quando o worklog integra
    com sucesso, as pendências antigas dele são fechadas automaticamente.
    """

    _name = "jira.integration.sync.log"
    _description = "Integração Jira: Log de Sincronização"
    _order = "create_date desc, id desc"
    _rec_name = "worklog_id"

    worklog_id = fields.Char(string="Worklog ID", index=True)
    jira_issue_key = fields.Char(string="Jira Key", index=True)
    jira_issue_id = fields.Char(string="Jira Issue ID")
    jira_project_key = fields.Char(string="Projeto Jira")
    jira_account_id = fields.Char(string="Jira Account ID")
    jira_display_name = fields.Char(string="Usuário")
    field_value = fields.Char(
        string="Campo Departamento",
        help="Valor do campo de decisão lido na issue, quando aplicável.",
    )
    worklog_date = fields.Date(string="Data do Apontamento")
    hours = fields.Float(string="Horas")
    status = fields.Selection(
        INTEGRATION_STATUSES, string="Status", required=True, default="pending", index=True
    )
    message = fields.Text(string="Mensagem")
    payload = fields.Text(string="Payload (debug)")
    task_id = fields.Many2one("project.task", string="Tarefa Odoo")
    timesheet_id = fields.Many2one("account.analytic.line", string="Timesheet Odoo")

    def action_mark_pending(self):
        """Marca para reprocessamento após correção do de-para."""
        self.write(
            {
                "status": "pending",
                "message": "Marcado para reprocessamento pela tela de erros",
            }
        )

    def action_ignore(self):
        """Descarta o erro sem reprocessar."""
        self.write({"status": "skipped", "message": "Ignorado manualmente"})
