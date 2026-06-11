# Integração Jira + Clockwork Pro → Odoo

Automatiza a criação e atualização, no Odoo, das tarefas e apontamentos de
horas registrados no Jira / Clockwork Pro, permitindo controlar o custo dos
projetos dentro do Odoo — com **tabelas de de-para mantidas no próprio Odoo**
e **regra especial de alocação por departamento/conta analítica** para os
projetos que exigem leitura de campo do ticket (ex.: TAD).

A especificação funcional completa está em
[`docs/especificacao.md`](docs/especificacao.md). O guia de operação está em
[`docs/runbook.md`](docs/runbook.md).

## Arquitetura

```
Jira Cloud ──────────┐
                     │  (issues, campos customizados)
Clockwork Pro ───────┤  (worklogs — fonte principal de horas)
                     ▼
        ┌─────────────────────────┐
        │  sync_service (Python)  │  serviço agendado (15/30 min)
        │  - busca worklogs       │
        │  - aplica de-para       │
        │  - regra de alocação    │
        │  - competência fechada  │
        └────────────┬────────────┘
                     │ XML-RPC
                     ▼
        ┌─────────────────────────┐
        │  Odoo                   │
        │  addon jira_clockwork_  │
        │  sync:                  │
        │  - de-paras (3 tabelas) │
        │  - log/fila de erros    │
        │  - campos x_* (tarefas, │
        │    timesheets, projetos)│
        └─────────────────────────┘
```

Decisões de projeto (seções 18 e 23 da especificação):

- **O de-para mora no Odoo** — o impacto é contábil/gerencial, então a
  configuração fica onde o impacto acontece, editável pelo gestor sem
  desenvolvedor.
- **Jira/Clockwork mandam, o Odoo recebe** — dados importados não devem ser
  editados manualmente no Odoo; correções acontecem na origem.
- **Idempotência por IDs externos** — `x_jira_issue_id` (tarefas) e
  `x_external_worklog_id` (timesheets, com unicidade garantida por constraint
  SQL). Rodar duas vezes não duplica nada (RNF03/RNF06).
- **Nada cai em conta genérica** — sem de-para válido, o apontamento não
  integra e vira pendência na fila de erros (seção 18.5).
- **A regra dos projetos especiais é configuração, não código** — tabela de
  alocação por valor de campo, mantida em tela do Odoo.

## Componentes

| Diretório | Conteúdo |
|---|---|
| `odoo_addons/jira_clockwork_sync/` | Addon Odoo (17.0): modelos de de-para, log de integração, campos técnicos `x_*`, telas de manutenção e grupos de segurança |
| `sync_service/jira_odoo_sync/` | Serviço Python: clientes Jira/Clockwork/Odoo, motor de alocação, pipeline de sincronização e CLI |
| `sync_service/tests/` | Testes unitários (pytest) com fakes em memória |
| `docs/` | Especificação funcional e runbook de operação |

## Modos de alocação (`allocation_mode` do de-para de projetos)

| Modo | Comportamento |
|---|---|
| `DIRECT_PROJECT` | Projeto Jira mapeia direto para projeto/conta analítica padrão |
| `BY_ISSUE_FIELD` | Lê um campo do ticket (ex.: Departamento) e busca a conta analítica na tabela de alocação por campo. Campo vazio ou valor não cadastrado ⇒ erro, não integra |
| `IGNORE` | Projeto não integra (worklogs pulados silenciosamente) |
| `ERROR_IF_EMPTY` | Usa o destino padrão do projeto, mas exige o campo de decisão preenchido na issue (qualidade de dados) |

Exemplo da regra especial (projeto TAD):

```
Jira Project = TAD  +  Departamento = TRM            → Conta Analítica "Dexterity / TRM"
Jira Project = TAD  +  Departamento = Administrativo → Conta Analítica "Dexterity / Administrativo"
Jira Project = TAD  +  Departamento = (vazio)        → ERRO: campo obrigatório não preenchido
```

## Status de integração

`PENDING`, `SUCCESS`, `ERROR_USER_MAPPING`, `ERROR_PROJECT_MAPPING`,
`ERROR_ANALYTIC_MAPPING`, `ERROR_ODOO`, `ERROR_JIRA`, `SKIPPED`,
`CLOSED_PERIOD`, `CANCELLED_SOURCE` — conforme seção 10 da especificação.

## Instalação

> **Odoo Online (SaaS `*.odoo.com`)?** Addons customizados não podem ser
> instalados no Online. Nesse caso, **pule a etapa do addon**: crie os
> modelos/campos via Studio seguindo
> [`docs/odoo-online-studio.md`](docs/odoo-online-studio.md) e configure o
> serviço com `ODOO_SCHEMA=studio`. A External API (XML-RPC) e o Studio
> exigem o plano Custom do Odoo Online.

### 1. Addon Odoo (somente Odoo.sh / on-premise)

1. Copie `odoo_addons/jira_clockwork_sync` para o caminho de addons do Odoo
   (alvo: Odoo 17; para 16 é necessário converter os atributos
   `invisible`/`required` das views para a sintaxe `attrs`).
2. Atualize a lista de apps e instale **Integração Jira / Clockwork Pro**.
3. Crie um usuário de serviço (ex.: `integracao-jira@dexterity.com.br`) com:
   - grupo **Integração Jira / Gestor**;
   - acesso a Projetos e Timesheets (criação/edição);
   - **Administração: Configurações** (para ler/gravar `ir.config_parameter`).
4. Cadastre os de-paras em **Integração Jira → De-Para**.

### 2. Serviço de sincronização

```bash
cp .env.example .env        # preencher credenciais
pip install -r requirements.txt
PYTHONPATH=sync_service python -m jira_odoo_sync check   # valida credenciais
```

Ou via Docker:

```bash
docker compose up -d        # roda "sync --loop" a cada 15 minutos
```

## Uso

```bash
# Conectividade com os três sistemas
jira-odoo-sync check

# Sincronização incremental (janela: hoje - SYNC_LOOKBACK_DAYS até hoje)
jira-odoo-sync sync

# Execução contínua a cada 15 minutos
jira-odoo-sync sync --loop --interval 900

# Carga inicial recomendada: mês corrente + mês anterior (seção 12)
jira-odoo-sync backfill --start 2026-05-01 --end 2026-06-30

# Reprocessar pendências marcadas na tela de erros do Odoo
jira-odoo-sync reprocess --from-pending

# Reprocessar worklogs específicos
jira-odoo-sync reprocess --start 2026-06-01 --end 2026-06-10 --worklog-id 12345

# Fechar competência (bloqueia alterações retroativas — Regra 6)
jira-odoo-sync close-period --until 2026-05-31

# Simulação sem gravar nada
jira-odoo-sync --dry-run sync
```

## Fluxo de tratamento de erros

1. O serviço registra o erro em **Integração Jira → Monitoramento → Erros de
   Integração** (com usuário, issue, projeto, valor do campo e mensagem).
2. Usuários desconhecidos ganham automaticamente uma linha no de-para de
   usuários (filtro **"Sem vínculo"**) para o gestor completar.
3. O gestor corrige o de-para e clica em **Reprocessar** no registro de erro
   (status volta a `PENDING`).
4. `jira-odoo-sync reprocess --from-pending` reintegra os pendentes; ao ter
   sucesso, as pendências antigas do worklog são fechadas automaticamente.

## Exclusões e competência fechada

- **Worklog excluído na origem** (seção 8.2, Opção B): o timesheet **não é
  excluído fisicamente** — as horas são zeradas e o registro marcado como
  `CANCELLED_SOURCE`. Antes de cancelar, o serviço confirma no Jira que o
  worklog realmente não existe (um worklog que apenas mudou de data não é
  cancelado).
- **Competência fechada** (seção 9): worklogs com data ≤
  `jira_clockwork_sync.closed_until` não são criados/alterados/cancelados
  automaticamente; viram pendência `CLOSED_PERIOD` para aprovação
  administrativa.

## Testes

```bash
pip install pytest
python -m pytest -v
```

Cobrem o motor de alocação (incluindo os dois casos da seção 16), conversão
de tempo, competência fechada, idempotência, exclusões e dry-run.

## Limitações conhecidas / próximos passos

- O comando `sync` usa janela deslizante (`SYNC_LOOKBACK_DAYS`, padrão 7
  dias). Alterações em worklogs mais antigos só entram via `backfill` —
  recomenda-se um `backfill` semanal do mês corrente + anterior (cron).
- Fase 3/4 da especificação (alertas por e-mail/Teams, dashboards de custo,
  comparativo Jira × Odoo) ainda não implementadas.
- Em algumas configurações do Odoo a conta analítica do timesheet pode ser
  recalculada a partir do projeto; o serviço grava `account_id` explicitamente
  em criação e atualização, mas valide o comportamento na sua versão durante
  a homologação (ver runbook).
