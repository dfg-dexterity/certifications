from odoo import fields, models


class JiraIntegrationUserMapping(models.Model):
    """De-para de usuários Jira/Clockwork x funcionários Odoo (seção 4.1).

    Linhas sem funcionário Odoo são criadas automaticamente pelo serviço de
    sincronização quando um usuário desconhecido aponta horas: elas aparecem
    no filtro "Sem vínculo" para o gestor completar. Enquanto o vínculo não
    existir, os worklogs desse usuário ficam com status ERROR_USER_MAPPING.
    """

    _name = "jira.integration.user.mapping"
    _description = "Integração Jira: De-Para de Usuários"
    _order = "jira_display_name, jira_account_id"

    jira_account_id = fields.Char(
        string="Jira Account ID",
        required=True,
        index=True,
        help="Identificador único e estável do usuário no Jira Cloud. "
        "Não confiar em nome ou e-mail: o accountId é a chave.",
    )
    jira_display_name = fields.Char(string="Nome Jira")
    jira_email = fields.Char(string="E-mail Jira")
    clockwork_user_id = fields.Char(string="Clockwork User ID")
    odoo_employee_id = fields.Many2one(
        "hr.employee",
        string="Funcionário Odoo",
        help="Funcionário que receberá os timesheets. Sem este vínculo os "
        "apontamentos do usuário não são integrados (Regra 2).",
    )
    odoo_user_id = fields.Many2one("res.users", string="Usuário Odoo")
    hourly_cost = fields.Float(
        string="Custo Hora",
        help="Opcional; informativo. O custo efetivo do timesheet segue a "
        "configuração do funcionário no Odoo.",
    )
    active = fields.Boolean(default=True)
    valid_from = fields.Date(string="Vigência - Início")
    valid_to = fields.Date(string="Vigência - Fim")
    last_worklog_at = fields.Datetime(
        string="Último apontamento importado", readonly=True
    )

    _sql_constraints = [
        (
            "jira_account_id_uniq",
            "unique(jira_account_id)",
            "Já existe um mapeamento para este Jira Account ID.",
        ),
    ]
