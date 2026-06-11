import pytest

from jira_odoo_sync.schema import (
    ADDON_SCHEMA,
    STUDIO_SCHEMA,
    get_schema,
    translate_domain,
    translate_row,
    translate_vals,
)


class TestGetSchema:
    def test_perfis_validos(self):
        assert get_schema("addon") is ADDON_SCHEMA
        assert get_schema("studio") is STUDIO_SCHEMA
        assert get_schema("  STUDIO ") is STUDIO_SCHEMA

    def test_perfil_invalido(self):
        with pytest.raises(ValueError, match="ODOO_SCHEMA inválido"):
            get_schema("sheets")


class TestAddonSchema:
    def test_nomes_identicos(self):
        ms = ADDON_SCHEMA.user_mapping
        assert ms.model == "jira.integration.user.mapping"
        assert ms.tech("jira_account_id") == "jira_account_id"
        assert ms.name_field is None


class TestStudioSchema:
    def test_modelos_e_campos_com_prefixo_x(self):
        for ms in (
            STUDIO_SCHEMA.user_mapping,
            STUDIO_SCHEMA.project_mapping,
            STUDIO_SCHEMA.field_allocation,
            STUDIO_SCHEMA.sync_log,
        ):
            assert ms.model.startswith("x_"), ms.model
            assert ms.name_field == "x_name"
            for logical, tech in ms.fields.items():
                assert tech == f"x_{logical}", (logical, tech)

    def test_campos_usados_pelo_cliente_estao_mapeados(self):
        # Campos lógicos consultados/escritos por clients/odoo.py
        assert set(STUDIO_SCHEMA.user_mapping.fields) >= {
            "jira_account_id", "jira_display_name", "jira_email",
            "clockwork_user_id", "odoo_employee_id", "odoo_user_id",
            "active", "last_worklog_at",
        }
        assert set(STUDIO_SCHEMA.project_mapping.fields) >= {
            "jira_project_key", "allocation_mode", "odoo_project_id",
            "odoo_analytic_account_id", "decision_field_id",
            "decision_field_name", "active", "last_sync_at",
        }
        assert set(STUDIO_SCHEMA.field_allocation.fields) >= {
            "jira_project_key", "jira_field_value", "odoo_project_id",
            "odoo_analytic_account_id", "active",
        }
        assert set(STUDIO_SCHEMA.sync_log.fields) >= {
            "worklog_id", "jira_issue_key", "jira_project_key",
            "jira_account_id", "field_value", "worklog_date", "hours",
            "status", "message", "timesheet_id",
        }


class TestTranslate:
    ms = STUDIO_SCHEMA.user_mapping

    def test_domain(self):
        domain = [["jira_account_id", "=", "abc"], ["active", "=", True]]
        assert translate_domain(self.ms, domain) == [
            ["x_jira_account_id", "=", "abc"],
            ["x_active", "=", True],
        ]

    def test_domain_preserva_operadores(self):
        domain = ["|", ["jira_email", "=", "a@b"], ["jira_display_name", "=", "Ana"]]
        assert translate_domain(self.ms, domain) == [
            "|",
            ["x_jira_email", "=", "a@b"],
            ["x_jira_display_name", "=", "Ana"],
        ]

    def test_vals_e_row_ida_e_volta(self):
        vals = {"jira_account_id": "abc", "odoo_employee_id": 12}
        tech = translate_vals(self.ms, vals)
        assert tech == {"x_jira_account_id": "abc", "x_odoo_employee_id": 12}
        row = translate_row(self.ms, {"id": 7, **tech})
        assert row == {"id": 7, **vals}

    def test_campo_desconhecido_passa_intacto(self):
        assert translate_vals(self.ms, {"id": 1})["id"] == 1
        assert translate_row(self.ms, {"write_date": "x"})["write_date"] == "x"
