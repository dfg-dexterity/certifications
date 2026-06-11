from datetime import date

from conftest import FakeClockwork, FakeJira, FakeOdoo, make_settings

from jira_odoo_sync.clients.odoo import PARAM_CLOSED_UNTIL, PARAM_LAST_SYNC
from jira_odoo_sync.models import (
    AllocationMode,
    JiraIssue,
    ProjectMapping,
    UserMapping,
    Worklog,
)
from jira_odoo_sync.processor import SyncProcessor

WINDOW = (date(2026, 6, 1), date(2026, 6, 10))


def build_processor(odoo, jira, clockwork, **settings_overrides):
    return SyncProcessor(odoo, jira, clockwork, make_settings(**settings_overrides))


def cdv_setup():
    """Cenário da seção 16, caso 1: projeto direto CDV."""
    users = {
        "julian-id": UserMapping(id=2, jira_account_id="julian-id", odoo_employee_id=33)
    }
    projects = {
        "CDV": ProjectMapping(
            id=20,
            jira_project_key="CDV",
            allocation_mode=AllocationMode.DIRECT_PROJECT,
            odoo_project_id=45,
            odoo_analytic_account_id=87,
        )
    }
    issue = JiraIssue(
        issue_id="10001",
        key="CDV-102",
        summary="Configurar curva DI x Pré",
        project_key="CDV",
        status="Em andamento",
        url="https://example.atlassian.net/browse/CDV-102",
    )
    worklog = Worklog(
        worklog_id="901",
        issue_id="10001",
        issue_key="CDV-102",
        jira_account_id="julian-id",
        author_display_name="Julian",
        started=date(2026, 6, 3),
        time_spent_seconds=7200,
        comment="",
    )
    return users, projects, issue, worklog


class TestCriacao:
    def test_caso_1_projeto_direto(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))

        stats = processor.run_window(*WINDOW)

        assert stats.created_tasks == 1
        assert stats.created_timesheets == 1
        task = next(iter(odoo.tasks.values()))
        assert task["name"] == "[CDV-102] Configurar curva DI x Pré"
        assert task["project_id"] == 45
        assert task["x_jira_issue_id"] == "10001"
        line = next(iter(odoo.timesheets.values()))
        assert line["unit_amount"] == 2.0
        assert line["employee_id"] == 33
        assert line["account_id"] == 87
        assert line["x_external_worklog_id"] == "901"
        assert line["name"] == "[CDV-102] Apontamento importado do Clockwork"
        assert odoo.params[PARAM_LAST_SYNC]

    def test_caso_2_projeto_especial_por_departamento(self, tad_setup):
        users, projects, allocations, issue, worklog = tad_setup
        odoo = FakeOdoo(
            user_mappings=users,
            project_mappings=projects,
            field_allocations=allocations,
        )
        jira = FakeJira({"TAD-458": issue})
        processor = build_processor(odoo, jira, FakeClockwork([worklog]))

        stats = processor.run_window(*WINDOW)

        assert stats.created_timesheets == 1
        line = next(iter(odoo.timesheets.values()))
        assert line["unit_amount"] == 1.5
        assert line["project_id"] == 70
        assert line["account_id"] == 81  # Dexterity / Administrativo
        assert line["name"] == "[TAD-458] Revisão do procedimento"
        # O campo de decisão foi solicitado ao Jira em lote.
        assert ("customfield_10045",) in jira.requested_fields


class TestIdempotencia:
    def test_rodar_duas_vezes_nao_duplica(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))

        processor.run_window(*WINDOW)
        stats2 = processor.run_window(*WINDOW)

        assert len(odoo.tasks) == 1
        assert len(odoo.timesheets) == 1
        assert stats2.created_timesheets == 0
        assert stats2.updated_timesheets == 0
        assert stats2.unchanged == 1

    def test_alteracao_de_worklog_atualiza_timesheet(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))
        processor.run_window(*WINDOW)

        worklog.time_spent_seconds = 3600  # usuário corrigiu de 2h para 1h
        worklog.comment = "Ajuste de horas"
        stats = processor.run_window(*WINDOW)

        assert stats.updated_timesheets == 1
        assert len(odoo.timesheets) == 1
        line = next(iter(odoo.timesheets.values()))
        assert line["unit_amount"] == 1.0
        assert line["name"] == "[CDV-102] Ajuste de horas"


class TestErros:
    def test_regra_2_usuario_sem_de_para(self):
        _, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings={}, project_mappings=projects)
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))

        stats = processor.run_window(*WINDOW)

        assert not odoo.timesheets
        assert stats.counts.get("ERROR_USER_MAPPING") == 1
        assert any(log["status"] == "error_user_mapping" for log in odoo.logs)
        # O stub do usuário foi criado para a tela de manutenção (11.1).
        assert odoo.user_stubs and odoo.user_stubs[0]["jira_account_id"] == "julian-id"

    def test_projeto_sem_de_para(self):
        users, _, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings={})
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))

        stats = processor.run_window(*WINDOW)

        assert not odoo.timesheets
        assert stats.counts.get("ERROR_PROJECT_MAPPING") == 1

    def test_campo_departamento_vazio(self, tad_setup):
        users, projects, allocations, issue, worklog = tad_setup
        issue.fields = {}  # ticket sem departamento
        odoo = FakeOdoo(
            user_mappings=users, project_mappings=projects, field_allocations=allocations
        )
        processor = build_processor(odoo, FakeJira({"TAD-458": issue}), FakeClockwork([worklog]))

        stats = processor.run_window(*WINDOW)

        assert not odoo.timesheets
        assert stats.counts.get("ERROR_ANALYTIC_MAPPING") == 1
        log = next(l for l in odoo.logs if l["status"] == "error_analytic_mapping")
        assert "Departamento" in log["message"]

    def test_issue_inexistente_no_jira(self):
        users, projects, _, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(odoo, FakeJira({}), FakeClockwork([worklog]))

        stats = processor.run_window(*WINDOW)

        assert stats.counts.get("ERROR_JIRA") == 1

    def test_projeto_ignore_apenas_pula(self):
        users, projects, issue, worklog = cdv_setup()
        projects["CDV"].allocation_mode = AllocationMode.IGNORE
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))

        stats = processor.run_window(*WINDOW)

        assert stats.counts.get("SKIPPED") == 1
        assert not odoo.timesheets
        assert not odoo.logs  # pulado por regra não polui a fila de erros

    def test_sucesso_resolve_erros_antigos(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        odoo.logs.append(
            {
                "id": 1,
                "worklog_id": "901",
                "status": "error_user_mapping",
                "message": "Usuário sem mapeamento",
            }
        )
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))

        processor.run_window(*WINDOW)

        assert odoo.logs[0]["status"] == "success"


class TestCompetenciaFechada:
    def test_regra_6_nao_cria_em_periodo_fechado(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(
            user_mappings=users,
            project_mappings=projects,
            params={PARAM_CLOSED_UNTIL: "2026-06-30"},
        )
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))

        stats = processor.run_window(*WINDOW)

        assert not odoo.timesheets
        assert not odoo.tasks
        assert stats.counts.get("CLOSED_PERIOD") == 1

    def test_existente_sem_alteracao_em_periodo_fechado_nao_gera_pendencia(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))
        processor.run_window(*WINDOW)  # cria com período aberto

        odoo.params[PARAM_CLOSED_UNTIL] = "2026-06-30"  # fecha o mês
        stats = processor.run_window(*WINDOW)

        assert stats.counts.get("CLOSED_PERIOD") is None
        assert stats.unchanged == 1

    def test_alteracao_em_periodo_fechado_vira_pendencia(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]))
        processor.run_window(*WINDOW)

        odoo.params[PARAM_CLOSED_UNTIL] = "2026-06-30"
        worklog.time_spent_seconds = 900  # alteração retroativa
        stats = processor.run_window(*WINDOW)

        assert stats.counts.get("CLOSED_PERIOD") == 1
        line = next(iter(odoo.timesheets.values()))
        assert line["unit_amount"] == 2.0  # NÃO foi alterado


class TestExclusao:
    def test_worklog_excluido_cancela_timesheet(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        jira = FakeJira({"CDV-102": issue}, existing_worklogs=set())
        processor = build_processor(odoo, jira, FakeClockwork([worklog]))
        processor.run_window(*WINDOW)

        # Worklog some da origem e o Jira confirma a exclusão (404).
        processor_2 = build_processor(odoo, jira, FakeClockwork([]))
        stats = processor_2.run_window(*WINDOW)

        line = next(iter(odoo.timesheets.values()))
        assert line["unit_amount"] == 0.0
        assert line["x_integration_status"] == "cancelled_source"
        assert stats.cancelled == 1
        assert stats.counts.get("CANCELLED_SOURCE") == 1

    def test_worklog_que_mudou_de_data_nao_e_cancelado(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        # O Jira ainda conhece o worklog: ele só saiu da janela.
        jira = FakeJira({"CDV-102": issue}, existing_worklogs={("CDV-102", "901")})
        processor = build_processor(odoo, jira, FakeClockwork([worklog]))
        processor.run_window(*WINDOW)

        processor_2 = build_processor(odoo, jira, FakeClockwork([]))
        stats = processor_2.run_window(*WINDOW)

        line = next(iter(odoo.timesheets.values()))
        assert line["unit_amount"] == 2.0
        assert stats.cancelled == 0

    def test_exclusao_em_periodo_fechado_vira_pendencia(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        jira = FakeJira({"CDV-102": issue}, existing_worklogs=set())
        processor = build_processor(odoo, jira, FakeClockwork([worklog]))
        processor.run_window(*WINDOW)

        odoo.params[PARAM_CLOSED_UNTIL] = "2026-06-30"
        processor_2 = build_processor(odoo, jira, FakeClockwork([]))
        stats = processor_2.run_window(*WINDOW)

        line = next(iter(odoo.timesheets.values()))
        assert line["unit_amount"] == 2.0  # intocado
        assert stats.counts.get("CLOSED_PERIOD") == 1


class TestReprocessamento:
    def test_filtro_por_worklog_id(self):
        users, projects, issue, worklog = cdv_setup()
        other = Worklog(
            worklog_id="902",
            issue_id="10001",
            issue_key="CDV-102",
            jira_account_id="julian-id",
            started=date(2026, 6, 4),
            time_spent_seconds=3600,
        )
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(
            odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog, other])
        )

        stats = processor.run_window(*WINDOW, worklog_ids={"902"})

        assert stats.created_timesheets == 1
        line = next(iter(odoo.timesheets.values()))
        assert line["x_external_worklog_id"] == "902"


class TestDryRun:
    def test_dry_run_nao_grava_nada(self):
        users, projects, issue, worklog = cdv_setup()
        odoo = FakeOdoo(user_mappings=users, project_mappings=projects)
        processor = build_processor(
            odoo, FakeJira({"CDV-102": issue}), FakeClockwork([worklog]), dry_run=True
        )

        stats = processor.run_window(*WINDOW)

        assert not odoo.tasks
        assert not odoo.timesheets
        assert not odoo.logs
        assert PARAM_LAST_SYNC not in odoo.params
        assert stats.created_tasks == 1  # contabiliza o que SERIA criado
        assert stats.created_timesheets == 1
