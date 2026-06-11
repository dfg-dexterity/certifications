{
    "name": "Integração Jira / Clockwork Pro",
    "summary": (
        "Tabelas de de-para, campos técnicos e telas de manutenção para a "
        "integração de tarefas e apontamentos Jira + Clockwork Pro -> Odoo"
    ),
    "description": """
Integração Jira / Clockwork Pro -> Odoo
=======================================

Este módulo NÃO chama as APIs do Jira/Clockwork: ele fornece a base de
configuração e rastreabilidade usada pelo serviço externo de sincronização
(``sync_service`` no mesmo repositório):

* De-para de usuários (Jira Account ID -> funcionário Odoo)
* De-para de projetos (projeto Jira -> projeto/conta analítica Odoo)
* Alocação por campo da issue (projetos especiais, ex.: TAD por Departamento)
* Log de integração com fila de erros e reprocessamento
* Campos técnicos x_* em tarefas e timesheets (idempotência e rastreabilidade)

Parâmetros de sistema:

* ``jira_clockwork_sync.closed_until`` — competência fechada (YYYY-MM-DD)
* ``jira_clockwork_sync.last_sync_at`` — última sincronização bem-sucedida
""",
    "version": "17.0.1.0.0",
    "category": "Services/Timesheets",
    "author": "Dexterity IT Solutions",
    "license": "LGPL-3",
    "depends": ["project", "hr_timesheet", "analytic", "hr"],
    "data": [
        "security/jira_integration_security.xml",
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "views/user_mapping_views.xml",
        "views/project_mapping_views.xml",
        "views/field_allocation_views.xml",
        "views/sync_log_views.xml",
        "views/project_task_views.xml",
        "views/project_project_views.xml",
        "views/account_analytic_line_views.xml",
        "views/menus.xml",
    ],
    "application": True,
    "installable": True,
}
