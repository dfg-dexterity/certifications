import pytest

from jira_odoo_sync.allocation import AllocationEngine, AllocationError, normalize_field_value
from jira_odoo_sync.models import (
    AllocationMode,
    FieldAllocation,
    IntegrationStatus,
    JiraIssue,
    ProjectMapping,
)


def issue(project_key="CDV", key="CDV-102", fields=None):
    return JiraIssue(
        issue_id="10001",
        key=key,
        summary="Configurar curva DI x Pré",
        project_key=project_key,
        fields=fields or {},
    )


def direct_mapping(**overrides):
    base = dict(
        id=1,
        jira_project_key="CDV",
        allocation_mode=AllocationMode.DIRECT_PROJECT,
        odoo_project_id=45,
        odoo_analytic_account_id=87,
    )
    base.update(overrides)
    return ProjectMapping(**base)


class TestNormalizeFieldValue:
    def test_string(self):
        assert normalize_field_value("  TRM ") == "TRM"

    def test_option_dict(self):
        assert normalize_field_value({"value": "Administrativo", "id": "1"}) == "Administrativo"

    def test_dict_com_name(self):
        assert normalize_field_value({"name": "Comercial"}) == "Comercial"

    def test_lista(self):
        assert normalize_field_value([{"value": "TRM"}, {"value": "CLM"}]) == "TRM, CLM"

    def test_vazios(self):
        assert normalize_field_value(None) == ""
        assert normalize_field_value(False) == ""
        assert normalize_field_value({}) == ""
        assert normalize_field_value("   ") == ""


class TestDirectProject:
    def test_caso_1_projeto_direto(self):
        engine = AllocationEngine({"CDV": direct_mapping()}, {})
        result = engine.resolve(issue())
        assert result.odoo_project_id == 45
        assert result.odoo_analytic_account_id == 87

    def test_sem_de_para_cadastrado(self):
        engine = AllocationEngine({}, {})
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue())
        assert exc.value.status == IntegrationStatus.ERROR_PROJECT_MAPPING

    def test_de_para_inativo_ignora(self):
        engine = AllocationEngine({"CDV": direct_mapping(active=False)}, {})
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue())
        assert exc.value.status == IntegrationStatus.SKIPPED

    def test_modo_ignore(self):
        mapping = direct_mapping(allocation_mode=AllocationMode.IGNORE)
        engine = AllocationEngine({"CDV": mapping}, {})
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue())
        assert exc.value.status == IntegrationStatus.SKIPPED

    def test_de_para_incompleto(self):
        mapping = direct_mapping(odoo_analytic_account_id=None)
        engine = AllocationEngine({"CDV": mapping}, {})
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue())
        assert exc.value.status == IntegrationStatus.ERROR_PROJECT_MAPPING


def by_field_mapping(**overrides):
    base = dict(
        id=2,
        jira_project_key="TAD",
        allocation_mode=AllocationMode.BY_ISSUE_FIELD,
        decision_field_id="customfield_10045",
        decision_field_name="Departamento",
    )
    base.update(overrides)
    return ProjectMapping(**base)


def tad_allocations():
    return {
        "TAD": {
            "trm": FieldAllocation(
                id=10, jira_project_key="TAD", jira_field_value="TRM",
                odoo_project_id=70, odoo_analytic_account_id=80,
            ),
            "administrativo": FieldAllocation(
                id=11, jira_project_key="TAD", jira_field_value="Administrativo",
                odoo_project_id=70, odoo_analytic_account_id=81,
            ),
        }
    }


class TestByIssueField:
    def test_caso_2_departamento_administrativo(self):
        engine = AllocationEngine({"TAD": by_field_mapping()}, tad_allocations())
        result = engine.resolve(
            issue("TAD", "TAD-458", {"customfield_10045": {"value": "Administrativo"}})
        )
        assert result.odoo_project_id == 70
        assert result.odoo_analytic_account_id == 81
        assert result.field_value == "Administrativo"

    def test_lookup_case_insensitive(self):
        engine = AllocationEngine({"TAD": by_field_mapping()}, tad_allocations())
        result = engine.resolve(issue("TAD", "TAD-1", {"customfield_10045": "trm"}))
        assert result.odoo_analytic_account_id == 80

    def test_regra_4_campo_vazio_gera_erro(self):
        engine = AllocationEngine({"TAD": by_field_mapping()}, tad_allocations())
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue("TAD", "TAD-2", {}))
        assert exc.value.status == IntegrationStatus.ERROR_ANALYTIC_MAPPING
        assert "não preenchido" in exc.value.message
        assert "Departamento" in exc.value.message

    def test_valor_sem_alocacao_cadastrada(self):
        engine = AllocationEngine({"TAD": by_field_mapping()}, tad_allocations())
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue("TAD", "TAD-3", {"customfield_10045": {"value": "Comercial"}}))
        assert exc.value.status == IntegrationStatus.ERROR_ANALYTIC_MAPPING
        assert "Comercial" in exc.value.message

    def test_de_para_sem_campo_de_decisao(self):
        engine = AllocationEngine(
            {"TAD": by_field_mapping(decision_field_id="")}, tad_allocations()
        )
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue("TAD", "TAD-4", {"customfield_10045": "TRM"}))
        assert exc.value.status == IntegrationStatus.ERROR_PROJECT_MAPPING

    def test_alocacao_inativa_nao_e_usada(self):
        allocations = tad_allocations()
        allocations["TAD"]["trm"].active = False
        engine = AllocationEngine({"TAD": by_field_mapping()}, allocations)
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue("TAD", "TAD-5", {"customfield_10045": "TRM"}))
        assert exc.value.status == IntegrationStatus.ERROR_ANALYTIC_MAPPING


class TestErrorIfEmpty:
    def make_engine(self):
        mapping = direct_mapping(
            allocation_mode=AllocationMode.ERROR_IF_EMPTY,
            decision_field_id="customfield_10099",
            decision_field_name="Departamento",
        )
        return AllocationEngine({"CDV": mapping}, {})

    def test_integra_quando_campo_preenchido(self):
        engine = self.make_engine()
        result = engine.resolve(issue(fields={"customfield_10099": "TRM"}))
        assert result.odoo_project_id == 45
        assert result.field_value == "TRM"

    def test_erro_quando_campo_vazio(self):
        engine = self.make_engine()
        with pytest.raises(AllocationError) as exc:
            engine.resolve(issue(fields={}))
        assert exc.value.status == IntegrationStatus.ERROR_ANALYTIC_MAPPING
