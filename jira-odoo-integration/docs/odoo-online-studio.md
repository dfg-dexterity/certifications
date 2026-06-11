# Configuração no Odoo Online (Studio / campos customizados)

O **Odoo Online** (SaaS `*.odoo.com`) **não permite instalar addons
customizados** — o addon `odoo_addons/jira_clockwork_sync` deste repositório
só funciona em Odoo.sh ou on-premise. Em Odoo Online, os modelos de de-para
e os campos técnicos são criados manualmente (Studio ou menu Técnico), e o
serviço de sincronização é apontado para eles com:

```
ODOO_SCHEMA=studio
```

> **Pré-requisito de plano:** no Odoo Online, a **External API (XML-RPC)** e
> o **Studio** são recursos do plano **Custom**. Sem External API o serviço
> não consegue se conectar de forma alguma.

Todos os nomes técnicos abaixo são **obrigatórios e exatos** — o serviço os
referencia literalmente (perfil `studio` em
`sync_service/jira_odoo_sync/schema.py`). No Odoo Online todo modelo/campo
customizado precisa do prefixo `x_`; ao criar campos pelo Studio, ative o
**modo desenvolvedor** e ajuste o nome técnico (o Studio sugere
`x_studio_...` — corrija para os nomes da tabela).

## Parte A — Campos em modelos existentes

### `project.task` (Tarefa)

| Nome técnico | Tipo | Rótulo sugerido |
|---|---|---|
| `x_jira_issue_id` | Char (indexado) | Jira Issue ID |
| `x_jira_issue_key` | Char (indexado) | Jira Issue Key |
| `x_jira_issue_url` | Char | URL Jira |
| `x_jira_project_key` | Char | Projeto Jira |
| `x_jira_status` | Char | Status no Jira |
| `x_integration_source` | Char | Origem da Integração |
| `x_last_sync_at` | Datetime | Última Sincronização |

### `account.analytic.line` (Timesheet)

| Nome técnico | Tipo | Rótulo sugerido |
|---|---|---|
| `x_external_worklog_id` | Char (indexado) | External Worklog ID |
| `x_jira_issue_id` | Char | Jira Issue ID |
| `x_jira_issue_key` | Char (indexado) | Jira Issue Key |
| `x_clockwork_user_id` | Char | Clockwork User ID |
| `x_jira_account_id` | Char | Jira Account ID |
| `x_integration_status` | Selection (valores da Parte C) | Status Integração |
| `x_integration_error_message` | Text | Mensagem da Integração |
| `x_last_sync_at` | Datetime | Última Sincronização |

### `project.project` (Projeto) — opcional/informativo

| Nome técnico | Tipo | Rótulo sugerido |
|---|---|---|
| `x_jira_project_key` | Char | Projeto Jira (Key) |
| `x_integration_enabled` | Boolean | Recebe integração Jira |

## Parte B — Modelos customizados (4 tabelas de de-para/log)

Criar via Studio (Novo Modelo) ou Técnico → Modelos. Cada modelo
customizado ganha automaticamente o campo `x_name` (nome de exibição) — o
serviço o preenche sozinho ao criar registros. Ative o comportamento
**Arquivável** quando o Studio oferecer (cria o campo `x_active`).

### Modelo `x_jira_user_map` — De-para de usuários

| Nome técnico | Tipo | Observação |
|---|---|---|
| `x_jira_account_id` | Char, obrigatório, indexado | Chave (única por usuário) |
| `x_jira_display_name` | Char | |
| `x_jira_email` | Char | |
| `x_clockwork_user_id` | Char | |
| `x_odoo_employee_id` | Many2one → `hr.employee` | Funcionário que recebe os timesheets |
| `x_odoo_user_id` | Many2one → `res.users` | Opcional |
| `x_active` | Boolean, padrão Verdadeiro | |
| `x_last_worklog_at` | Datetime | Preenchido pelo serviço |

### Modelo `x_jira_project_map` — De-para de projetos

| Nome técnico | Tipo | Observação |
|---|---|---|
| `x_jira_project_key` | Char, obrigatório, indexado | Ex.: TAD, CDV |
| `x_jira_project_id` | Char | |
| `x_jira_project_name` | Char | |
| `x_allocation_mode` | Selection (valores da Parte C) | |
| `x_odoo_project_id` | Many2one → `project.project` | |
| `x_odoo_analytic_account_id` | Many2one → `account.analytic.account` | Conta analítica padrão |
| `x_decision_field_id` | Char | Ex.: `customfield_10045` |
| `x_decision_field_name` | Char | Ex.: Departamento |
| `x_active` | Boolean, padrão Verdadeiro | |
| `x_last_sync_at` | Datetime | Preenchido pelo serviço |

### Modelo `x_jira_field_alloc` — Alocação por campo da issue

| Nome técnico | Tipo | Observação |
|---|---|---|
| `x_jira_project_key` | Char, obrigatório | Mesmo valor do de-para do projeto |
| `x_jira_field_value` | Char, obrigatório | Ex.: TRM, Administrativo |
| `x_odoo_project_id` | Many2one → `project.project`, obrigatório | |
| `x_odoo_analytic_account_id` | Many2one → `account.analytic.account`, obrigatório | |
| `x_active` | Boolean, padrão Verdadeiro | |

### Modelo `x_jira_sync_log` — Log de integração / fila de erros

| Nome técnico | Tipo |
|---|---|
| `x_worklog_id` | Char (indexado) |
| `x_jira_issue_key` | Char |
| `x_jira_issue_id` | Char |
| `x_jira_project_key` | Char |
| `x_jira_account_id` | Char |
| `x_jira_display_name` | Char |
| `x_field_value` | Char |
| `x_worklog_date` | Date |
| `x_hours` | Float |
| `x_status` | Selection (valores da Parte C) |
| `x_message` | Text |
| `x_task_id` | Many2one → `project.task` |
| `x_timesheet_id` | Many2one → `account.analytic.line` |

## Parte C — Valores exatos das Selections

Os **valores técnicos** (não os rótulos) precisam ser exatamente estes:

`x_allocation_mode`:

```
direct_project | by_issue_field | ignore | error_if_empty
```

`x_status` e `x_integration_status`:

```
pending | success | error_user_mapping | error_project_mapping |
error_analytic_mapping | error_odoo | error_jira | skipped |
closed_period | cancelled_source
```

## Parte D — Parâmetros de sistema

Em Configurações → Técnico → Parâmetros do Sistema, crie (ou deixe o
serviço criar na primeira execução):

| Chave | Valor inicial |
|---|---|
| `jira_clockwork_sync.closed_until` | (vazio) |
| `jira_clockwork_sync.last_sync_at` | (vazio) |

## Parte E — Telas, permissões e diferenças para o addon

- **Telas**: monte as visões de lista/formulário pelo Studio (arraste os
  campos; crie um filtro "Sem vínculo" = `x_odoo_employee_id` vazio no
  de-para de usuários). Crie um menu "Integração Jira" agrupando os 4
  modelos.
- **Permissões**: revise Técnico → Regras de Acesso dos modelos criados —
  o usuário dono da chave de API precisa de leitura/escrita/criação nos 4
  modelos, além de Projetos, Timesheets e Configurações.
- **Sem constraint de unicidade**: o Studio não cria constraints SQL. A
  idempotência é garantida pelo serviço (busca por `x_external_worklog_id`
  antes de criar), mas **evite editar manualmente** esse campo nos
  timesheets e não cadastre dois de-paras com o mesmo `x_jira_account_id`.
- **Reprocessamento sem botões**: no lugar dos botões do addon, mude o
  campo Status do registro de log para `PENDING` (na lista) e rode
  `jira-odoo-sync reprocess --from-pending`.

## Parte F — Configuração do serviço

No `.env`:

```
ODOO_SCHEMA=studio
```

Validação rápida após criar tudo:

```bash
jira-odoo-sync check          # autentica e conta os de-paras
jira-odoo-sync --dry-run sync # simula sem gravar
```
