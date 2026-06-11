"""Interface de linha de comando do serviço de sincronização.

Comandos:

* ``check``        — testa conectividade/credenciais com Jira, Clockwork e Odoo.
* ``sync``         — sincronização incremental (janela deslizante de
  ``SYNC_LOOKBACK_DAYS`` dias até hoje). Com ``--loop`` roda continuamente
  a cada ``--interval`` segundos (padrão 900 = 15 minutos).
* ``backfill``     — carga inicial/histórica de um intervalo de datas.
  Recomendação da especificação: mês corrente + mês anterior.
* ``reprocess``    — reprocessa worklogs específicos (``--worklog-id``) ou
  todos os marcados como PENDING na tela de erros (``--from-pending``).
* ``close-period`` — define a data limite de competência fechada no Odoo.

Exemplos:

    jira-odoo-sync check
    jira-odoo-sync sync
    jira-odoo-sync sync --loop --interval 900
    jira-odoo-sync backfill --start 2026-05-01 --end 2026-06-30
    jira-odoo-sync reprocess --from-pending
    jira-odoo-sync reprocess --start 2026-06-01 --end 2026-06-10 --worklog-id 12345
    jira-odoo-sync close-period --until 2026-05-31
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import time
from datetime import date, datetime, timedelta

from .clients import ClockworkClient, JiraClient, OdooClient
from .clients.odoo import PARAM_CLOSED_UNTIL
from .config import Settings
from .processor import SyncProcessor

logger = logging.getLogger("jira_odoo_sync")


def _parse_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Data inválida: {raw!r} (use o formato YYYY-MM-DD)"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jira-odoo-sync",
        description="Integração de apontamentos Jira/Clockwork Pro -> Odoo",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Não grava nada no Odoo; apenas simula e mostra o resultado",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Log detalhado")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Testa conectividade com Jira, Clockwork e Odoo")

    sync = sub.add_parser("sync", help="Sincronização incremental")
    sync.add_argument("--loop", action="store_true", help="Executa continuamente")
    sync.add_argument(
        "--interval",
        type=int,
        default=900,
        help="Intervalo entre execuções em segundos no modo --loop (padrão: 900)",
    )

    backfill = sub.add_parser("backfill", help="Carga inicial/histórica")
    backfill.add_argument("--start", type=_parse_date, required=True)
    backfill.add_argument("--end", type=_parse_date, required=True)

    reprocess = sub.add_parser("reprocess", help="Reprocessa worklogs após correção de de-para")
    reprocess.add_argument("--start", type=_parse_date)
    reprocess.add_argument("--end", type=_parse_date)
    reprocess.add_argument(
        "--worklog-id",
        action="append",
        default=[],
        help="ID de worklog específico (pode repetir a opção)",
    )
    reprocess.add_argument(
        "--from-pending",
        action="store_true",
        help="Reprocessa os registros marcados como PENDING na tela de erros do Odoo",
    )

    close = sub.add_parser("close-period", help="Define a competência fechada")
    close.add_argument(
        "--until",
        type=_parse_date,
        required=True,
        help="Data limite (inclusive) da competência fechada, ex.: 2026-05-31",
    )
    return parser


def _build(settings: Settings):
    odoo = OdooClient(
        settings.odoo_url, settings.odoo_db, settings.odoo_username, settings.odoo_password
    )
    jira = JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)
    clockwork = ClockworkClient(
        settings.clockwork_api_token,
        base_url=settings.clockwork_base_url,
        chunk_days=settings.clockwork_chunk_days,
    )
    return odoo, jira, clockwork, SyncProcessor(odoo, jira, clockwork, settings)


def _cmd_check(settings: Settings) -> int:
    odoo, jira, clockwork, _ = _build(settings)
    ok = True
    try:
        me = jira.myself()
        print(f"[OK] Jira: autenticado como {me.get('displayName', '?')}")
    except Exception as exc:
        ok = False
        print(f"[ERRO] Jira: {exc}")
    try:
        today = date.today()
        worklogs = clockwork.list_worklogs(today, today)
        print(f"[OK] Clockwork: API acessível ({len(worklogs)} worklog(s) hoje)")
    except Exception as exc:
        ok = False
        print(f"[ERRO] Clockwork: {exc}")
    try:
        uid = odoo.login()
        users = odoo.load_user_mappings()
        projects = odoo.load_project_mappings()
        print(
            f"[OK] Odoo: autenticado (uid={uid}); de-paras carregados: "
            f"{len(users)} usuário(s), {len(projects)} projeto(s)"
        )
    except Exception as exc:
        ok = False
        print(f"[ERRO] Odoo: {exc}")
    return 0 if ok else 1


def _run_window(processor: SyncProcessor, start: date, end: date, worklog_ids=None) -> int:
    stats = processor.run_window(start, end, worklog_ids=worklog_ids)
    print(f"Janela {start}..{end} -> {stats.summary()}")
    for line in stats.errors:
        print(f"  {line}")
    return 0


def _cmd_sync(settings: Settings, args) -> int:
    _, _, _, processor = _build(settings)
    while True:
        end = date.today()
        start = end - timedelta(days=settings.sync_lookback_days)
        try:
            _run_window(processor, start, end)
        except Exception:
            logger.exception("Execução de sincronização falhou")
            if not args.loop:
                return 1
        if not args.loop:
            return 0
        logger.info("Aguardando %d segundos até a próxima execução", args.interval)
        time.sleep(args.interval)


def _cmd_backfill(settings: Settings, args) -> int:
    if args.end < args.start:
        print("ERRO: --end deve ser maior ou igual a --start", file=sys.stderr)
        return 2
    _, _, _, processor = _build(settings)
    return _run_window(processor, args.start, args.end)


def _cmd_reprocess(settings: Settings, args) -> int:
    odoo, _, _, processor = _build(settings)
    worklog_ids = {str(w) for w in args.worklog_id}
    start, end = args.start, args.end
    if args.from_pending:
        pending = odoo.fetch_pending_logs()
        if not pending:
            print("Nenhum registro PENDING para reprocessar.")
            return 0
        worklog_ids |= {row["worklog_id"] for row in pending}
        dates = sorted(
            datetime.strptime(row["worklog_date"][:10], "%Y-%m-%d").date()
            for row in pending
            if row["worklog_date"]
        )
        if dates:
            start = min(start, dates[0]) if start else dates[0]
            end = max(end, dates[-1]) if end else dates[-1]
    if not start or not end:
        print(
            "ERRO: informe --start/--end ou use --from-pending com registros "
            "que tenham data de worklog",
            file=sys.stderr,
        )
        return 2
    if not worklog_ids:
        print("ERRO: nenhum worklog para reprocessar", file=sys.stderr)
        return 2
    print(f"Reprocessando {len(worklog_ids)} worklog(s) na janela {start}..{end}")
    return _run_window(processor, start, end, worklog_ids=worklog_ids)


def _cmd_close_period(settings: Settings, args) -> int:
    odoo, _, _, _ = _build(settings)
    odoo.set_param(PARAM_CLOSED_UNTIL, args.until.isoformat())
    print(f"Competência fechada até {args.until} (parâmetro {PARAM_CLOSED_UNTIL})")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    if args.dry_run:
        settings = dataclasses.replace(settings, dry_run=True)
    if settings.dry_run:
        logger.info("Modo DRY-RUN: nada será gravado no Odoo")

    if args.command == "check":
        return _cmd_check(settings)
    if args.command == "sync":
        return _cmd_sync(settings, args)
    if args.command == "backfill":
        return _cmd_backfill(settings, args)
    if args.command == "reprocess":
        return _cmd_reprocess(settings, args)
    if args.command == "close-period":
        return _cmd_close_period(settings, args)
    parser.error(f"Comando desconhecido: {args.command}")
    return 2
