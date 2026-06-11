"""Cliente Clockwork Pro (fonte principal dos apontamentos de horas).

API: ``GET https://api.clockwork.report/v1/worklogs`` com header
``Authorization: Token <CLOCKWORK_API_TOKEN>``. A consulta de worklogs via
API é um recurso da versão Pro do Clockwork.

A janela de consulta é fatiada em blocos de ``chunk_days`` dias para manter
as respostas pequenas e previsíveis. O parse é defensivo quanto a snake_case
vs camelCase e quanto a comentários em texto puro ou em Atlassian Document
Format (ADF).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import requests

from ..models import Worklog


class ClockworkError(Exception):
    pass


def _date_chunks(start: date, end: date, chunk_days: int):
    cursor = start
    step = timedelta(days=max(chunk_days, 1) - 1)
    while cursor <= end:
        chunk_end = min(cursor + step, end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def _flatten_adf(node) -> str:
    """Extrai texto de um documento ADF (comentários do Jira/Clockwork)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(part for part in (_flatten_adf(item) for item in node) if part)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return _flatten_adf(node.get("content"))
    return ""


def _parse_started(raw) -> date:
    if raw is None:
        raise ClockworkError("Worklog sem data de início ('started')")
    text = str(raw).strip()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    # Formatos Jira como 2026-06-01T09:00:00.000-0300
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ClockworkError(f"Data de worklog não reconhecida: {raw!r}") from exc


class ClockworkClient:
    def __init__(
        self,
        api_token: str,
        base_url: str = "https://api.clockwork.report/v1",
        session: requests.Session | None = None,
        chunk_days: int = 7,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.chunk_days = chunk_days
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Authorization": f"Token {api_token}", "Accept": "application/json"}
        )

    def list_worklogs(self, starting_at: date, ending_at: date) -> list[Worklog]:
        """Busca worklogs no intervalo (inclusive), sem duplicados."""
        collected: dict[str, Worklog] = {}
        for chunk_start, chunk_end in _date_chunks(starting_at, ending_at, self.chunk_days):
            for worklog in self._fetch(chunk_start, chunk_end):
                collected[worklog.worklog_id] = worklog
        return sorted(collected.values(), key=lambda w: (w.started, w.worklog_id))

    def _fetch(self, start: date, end: date) -> list[Worklog]:
        params = {
            "starting_at": start.isoformat(),
            "ending_at": end.isoformat(),
            "expand[]": ["authors", "issues"],
        }
        url = f"{self.base_url}/worklogs"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ClockworkError(f"Falha de comunicação com o Clockwork: {exc}") from exc
        if response.status_code >= 400:
            raise ClockworkError(
                f"Clockwork retornou HTTP {response.status_code}: {response.text[:500]}"
            )
        data = response.json()
        if isinstance(data, dict):
            data = data.get("worklogs") or data.get("data") or []
        return [self._parse_worklog(item) for item in data]

    @staticmethod
    def _parse_worklog(item: dict) -> Worklog:
        author = item.get("author") or {}
        issue = item.get("issue") or {}
        worklog_id = item.get("id") or item.get("worklog_id")
        if worklog_id is None:
            raise ClockworkError(f"Worklog sem ID: {item!r}")
        seconds = (
            item.get("time_spent_seconds")
            or item.get("timeSpentSeconds")
            or 0
        )
        issue_id = issue.get("id") or item.get("issue_id")
        updated_raw = item.get("updated") or item.get("updated_at")
        updated_at = None
        if updated_raw:
            try:
                updated_at = datetime.fromisoformat(str(updated_raw))
            except ValueError:
                updated_at = None
        return Worklog(
            worklog_id=str(worklog_id),
            issue_id=str(issue_id) if issue_id else None,
            issue_key=issue.get("key") or item.get("issue_key") or "",
            jira_account_id=author.get("accountId") or author.get("account_id"),
            author_display_name=(
                author.get("displayName") or author.get("display_name") or ""
            ),
            clockwork_user_id=(
                str(author.get("id")) if author.get("id") is not None else None
            ),
            started=_parse_started(item.get("started") or item.get("started_at")),
            time_spent_seconds=int(seconds),
            comment=_flatten_adf(item.get("comment")).strip(),
            updated_at=updated_at,
        )
