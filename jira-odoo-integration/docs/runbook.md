# Runbook — Integração Jira/Clockwork Pro → Odoo

Guia de operação do dia a dia. Para o desenho completo, ver
[`especificacao.md`](especificacao.md).

## 1. Pré-requisitos

| Sistema | O que é preciso |
|---|---|
| Jira Cloud | Conta de serviço com acesso de leitura aos projetos integrados + API token |
| Clockwork **Pro** | Token de API (a API de worklogs é recurso da versão Pro) |
| Odoo (Odoo.sh/on-premise) | Addon `jira_clockwork_sync` instalado + usuário de serviço no grupo "Integração Jira / Gestor" com acesso a Projetos, Timesheets e Configurações |
| Odoo (**Online**) | Plano Custom (External API + Studio); modelos/campos criados conforme [`odoo-online-studio.md`](odoo-online-studio.md); `ODOO_SCHEMA=studio` no `.env`; usuário da chave de API com acesso aos 4 modelos, Projetos, Timesheets e Configurações |

Credenciais ficam **somente** no `.env` (ou no cofre de segredos do
orquestrador). Nunca em código nem no repositório (RNF02).

## 2. Implantação inicial

1. Instalar o addon e criar o usuário de serviço (ver README).
2. Cadastrar os de-paras:
   - **De-Para → Projetos**: um registro por projeto Jira. Projetos normais:
     `DIRECT_PROJECT` + projeto/conta padrão. Projetos especiais (TAD etc.):
     `BY_ISSUE_FIELD` + ID do campo (ex.: `customfield_10045`) + aba
     "Alocações por valor" com um destino por departamento.
   - **De-Para → Usuários**: pode começar vazio — o serviço cria as linhas
     automaticamente no primeiro erro; o gestor só completa o funcionário.
3. Validar credenciais: `jira-odoo-sync check`.
4. Ensaiar sem gravar: `jira-odoo-sync --dry-run backfill --start ... --end ...`
   e revisar o resumo impresso.
5. Carga inicial recomendada (seção 12): mês corrente + mês anterior:
   `jira-odoo-sync backfill --start 2026-05-01 --end 2026-06-30`.
6. Tratar a primeira leva de erros (usuários sem vínculo etc.) e
   `jira-odoo-sync reprocess --from-pending`.
7. Subir o serviço contínuo: `docker compose up -d` (loop de 15 min).

### Como descobrir o ID do campo "Departamento" no Jira

`GET https://<site>.atlassian.net/rest/api/3/field` e procurar pelo nome do
campo; o ID tem o formato `customfield_NNNNN`. É esse ID que vai no de-para
do projeto especial.

## 3. Rotina mensal de fechamento

1. Conferir pendências em **Monitoramento → Erros de Integração**.
2. Rodar um backfill de segurança do mês que está fechando (pega alterações
   tardias): `jira-odoo-sync backfill --start <1º dia do mês> --end <hoje>`.
3. Fechar a competência: `jira-odoo-sync close-period --until 2026-05-31`.
4. A partir daí, qualquer criação/alteração/exclusão retroativa vira
   pendência `CLOSED_PERIOD` (Regra 6) e exige decisão administrativa:
   - aprovado: reabrir temporariamente (`close-period --until` com data
     anterior), reprocessar, fechar de novo; ou
   - lançar ajuste manual no mês corrente; ou
   - recusar e corrigir na origem.

## 4. Tratamento de erros

| Status | Causa | Ação |
|---|---|---|
| `ERROR_USER_MAPPING` | Usuário sem vínculo com funcionário | De-Para → Usuários, filtro "Sem vínculo", preencher funcionário, reprocessar |
| `ERROR_PROJECT_MAPPING` | Projeto Jira sem de-para (ou de-para incompleto) | Criar/completar o registro em De-Para → Projetos, reprocessar |
| `ERROR_ANALYTIC_MAPPING` | Campo de departamento vazio na issue, ou valor sem alocação cadastrada | Campo vazio: corrigir **no Jira**. Valor novo: cadastrar na aba "Alocações por valor", reprocessar |
| `ERROR_JIRA` | Issue não encontrada / falha de API | Verificar permissões da conta de serviço e se a issue existe |
| `ERROR_ODOO` | Erro técnico ao gravar | Ver mensagem; checar permissões do usuário de serviço |
| `CLOSED_PERIOD` | Alteração retroativa em mês fechado | Decisão administrativa (seção 3 acima) |
| `CANCELLED_SOURCE` | Worklog excluído na origem | Informativo: horas foram zeradas, registro preservado |

Reprocessamento: botão **Reprocessar** no registro (status → `PENDING`) e
depois `jira-odoo-sync reprocess --from-pending`. O comando roda a janela das
datas dos worklogs pendentes filtrando apenas esses IDs; é idempotente.

## 5. Monitoramento

- **Última sincronização**: parâmetro `jira_clockwork_sync.last_sync_at`
  (Configurações → Técnico → Parâmetros do Sistema). Se parar de avançar,
  o serviço caiu — ver logs do container (`docker compose logs -f`).
- **Fila de erros**: Monitoramento → Erros de Integração (exportável para
  Excel pela própria lista).
- O processador **não aborta o lote** por erro em um worklog individual:
  cada um é registrado e o restante segue.

## 6. Janela de sincronização e edições antigas

`sync` processa de `hoje - SYNC_LOOKBACK_DAYS` até hoje (padrão 7 dias) —
toda execução revarre a janela inteira, o que é seguro por idempotência.
Edições/exclusões de worklogs **fora** da janela não são vistas pelo `sync`;
por isso a recomendação de `backfill` semanal do mês corrente + anterior
(ex.: cron de domingo). Aumentar `SYNC_LOOKBACK_DAYS` para 35–45 dias é uma
alternativa se o volume permitir.

## 7. Homologação da conta analítica (atenção)

Em algumas versões/configurações do Odoo, o campo `account_id` do timesheet
é recomputado a partir do projeto. O serviço grava `account_id` explicitamente
na criação e em toda atualização, mas **valide na homologação**: crie um
apontamento de teste num projeto `BY_ISSUE_FIELD` e confira se a conta
analítica da linha ficou a do departamento (e não a conta do projeto). Se a
sua versão sobrescrever o valor, será necessário um pequeno override no addon
(remover o recompute para linhas com `x_external_worklog_id`).

## 8. Migração deste projeto para repositório próprio

O projeto é autocontido nesta pasta. Para movê-lo:

```bash
git clone <repo-atual> tmp && cd tmp
git checkout <branch>
cp -r jira-odoo-integration /caminho/novo-repo
cd /caminho/novo-repo && git init && git add -A && git commit -m "Import inicial"
git remote add origin git@github.com:dfg-dexterity/jira-odoo-integration.git
git push -u origin main
```

O workflow de CI (`.github/workflows/ci.yml`) passa a executar
automaticamente quando a pasta estiver na raiz do repositório.
