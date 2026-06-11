"""Cliente Jira Cloud (REST API v3).

Usado para:
* Buscar dados completos das issues vinculadas aos worklogs (em lote, via
  ``/rest/api/3/search/jql``), incluindo os campos customizados de decisão
  (ex.: Departamento) configurados nos de-paras ``BY_ISSUE_FIELD``.
* Confirmar exclusão de worklogs antes de cancelar o timesheet no Odoo.

Autenticação: Basic auth com e-mail + API token
(https://id.atlassian.com/manage-profile/security/api-tokens).
"""
from __future__ import annotations

import requests

from ..models import JiraIssue

BASE_ISSUE_FIELDS = ("summary", "status", "project", "assignee")
SEARCH_PAGE_SIZE = 100
KEYS_PER_JQL = 50


class JiraError(Exception):
    pass


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        session: requests.Session | None = None,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------ http
    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise JiraError(f"Falha de comunicação com o Jira ({url}): {exc}") from exc
        if response.status_code >= 400:
            raise JiraError(
                f"Jira retornou HTTP {response.status_code} em {path}: "
                f"{response.text[:500]}"
            )
        if not response.content:
            return {}
        return response.json()

    # ------------------------------------------------------------------- api
    def myself(self) -> dict:
        """Teste de conectividade/credenciais."""
        return self._request("GET", "/rest/api/3/myself")

    def get_issues(
        self, issue_keys: list[str] | set[str], extra_fields: tuple[str, ...] | list[str] = ()
    ) -> dict[str, JiraIssue]:
        """Busca issues em lote por chave; retorna dict indexado pela chave.

        ``extra_fields`` recebe os IDs dos campos customizados de decisão
        (ex.: ``customfield_10045``) usados pelos projetos BY_ISSUE_FIELD.
        """
        keys = sorted({key for key in issue_keys if key})
        if not keys:
            return {}
        fields = list(BASE_ISSUE_FIELDS) + [f for f in extra_fields if f]
        issues: dict[str, JiraIssue] = {}
        for chunk in _chunks(keys, KEYS_PER_JQL):
            jql = "issuekey in ({})".format(", ".join(chunk))
            next_page_token = None
            while True:
                payload = {
                    "jql": jql,
                    "fields": fields,
                    "maxResults": SEARCH_PAGE_SIZE,
                }
                if next_page_token:
                    payload["nextPageToken"] = next_page_token
                data = self._request("POST", "/rest/api/3/search/jql", json=payload)
                for raw in data.get("issues", []):
                    issue = self._parse_issue(raw)
                    issues[issue.key] = issue
                next_page_token = data.get("nextPageToken")
                if not next_page_token or data.get("isLast"):
                    break
        return issues

    def worklog_exists(self, issue_key: str, worklog_id: str) -> bool:
        """Confirma se um worklog ainda existe no Jira (detecção de exclusão).

        Worklogs do Clockwork Pro são gravados como worklogs Jira, então a
        ausência aqui confirma exclusão na origem.
        """
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/worklog/{worklog_id}"
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise JiraError(f"Falha ao verificar worklog {worklog_id}: {exc}") from exc
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise JiraError(
            f"Jira retornou HTTP {response.status_code} ao verificar worklog "
            f"{worklog_id} da issue {issue_key}: {response.text[:300]}"
        )

    # --------------------------------------------------------------- parsing
    def _parse_issue(self, raw: dict) -> JiraIssue:
        fields = raw.get("fields") or {}
        project = fields.get("project") or {}
        status = fields.get("status") or {}
        assignee = fields.get("assignee") or {}
        key = raw.get("key", "")
        return JiraIssue(
            issue_id=str(raw.get("id", "")),
            key=key,
            summary=fields.get("summary") or "",
            project_key=project.get("key") or "",
            status=status.get("name") or "",
            assignee_account_id=assignee.get("accountId"),
            url=f"{self.base_url}/browse/{key}" if key else "",
            fields=fields,
        )
