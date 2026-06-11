# Especificação da Solução — Integração de apontamentos Jira/Clockwork Pro com Odoo

> Documento funcional de referência. O mapeamento espec → código está
> indicado entre colchetes ao longo do texto.

## 1. Objetivo

Automatizar a criação e atualização, no Odoo, das tarefas e apontamentos de
horas registrados atualmente no Jira / Clockwork Pro, permitindo que o custo
dos projetos seja controlado corretamente dentro do Odoo.

A solução deve permitir:

1. Buscar tarefas/issues no Jira.
2. Buscar apontamentos de horas no Clockwork Pro.
3. Criar ou atualizar tarefas correspondentes no Odoo.
4. Criar ou atualizar timesheets/apontamentos no Odoo.
5. Manter tabelas de de-para entre Jira, Clockwork e Odoo.
6. Alocar o esforço na conta analítica correta do Odoo.
7. Tratar exceções quando o projeto Jira não mapear diretamente para um
   projeto/conta analítica única.

O Clockwork Pro possui API para consulta de worklogs (restrita à versão Pro).
O Jira Cloud possui APIs REST para issues, campos e worklogs. No Odoo, contas
analíticas são usadas para apontar custos e despesas por dimensão
gerencial/projeto.

## 2. Visão geral da arquitetura

```
Jira / Clockwork Pro
        ↓
Camada de Integração          [sync_service/jira_odoo_sync]
        ↓
Regras de De-Para e Validação [allocation.py + tabelas no Odoo]
        ↓
Odoo                          [odoo_addons/jira_clockwork_sync]
```

**Componentes**

1. **Jira Cloud** — fonte de: projeto, issue, tipo, status, summary, campos
   customizados (departamento/área), responsável, chave (ex.: TAD-123).
2. **Clockwork Pro** — fonte principal dos apontamentos: worklog ID, usuário,
   data, tempo, comentário, issue vinculada, criação/alteração.
3. **Odoo** — destino: projeto, tarefa, timesheet, funcionário, conta
   analítica, custo por colaborador, centro de custo/departamento gerencial.
4. **Camada de integração** — serviço próprio em Python (recomendado em vez
   de middleware visual, por causa das regras de de-para, controle de erro,
   reprocessamento e exceções por campo customizado).

## 3. Entidades principais

### 3.1 Projeto Jira

| Campo | Exemplo | Observação |
|---|---|---|
| Jira Project Key | TAD | Chave do projeto |
| Jira Project ID | 10001 | ID interno |
| Jira Project Name | Time Administrativo Dexterity | Nome no Jira |
| Status Integração | Ativo/Inativo | Controla se integra ou não |

### 3.2 Projeto Odoo

| Campo | Exemplo |
|---|---|
| Odoo Project ID | 45 |
| Odoo Project Name | AMS Casa dos Ventos |
| Odoo Analytic Account ID | 87 |
| Empresa | Dexterity IT Solutions |

### 3.3 Funcionário / Usuário

| Campo | Exemplo |
|---|---|
| Jira Account ID | abc123 |
| Jira Display Name | João Silva |
| Jira E-mail | joao@dexterity.com.br |
| Clockwork User ID | Quando disponível |
| Odoo Employee ID | 12 |
| Odoo User ID | Quando necessário |
| Custo Hora | Opcional |
| Status | Ativo/Inativo |

**Regra:** não confiar apenas no nome. Nome muda, e-mail muda menos, mas no
Jira Cloud o identificador mais confiável é o `accountId`.

### 3.4 Tarefa Odoo

| Campo Odoo | Origem |
|---|---|
| Nome da tarefa | `[JIRA-KEY] Summary` |
| Descrição | Link do ticket + dados básicos |
| Projeto Odoo | De-para do projeto Jira |
| Conta analítica | Regra de alocação |
| External Jira Key | Campo customizado no Odoo |
| External Jira Issue ID | Campo customizado no Odoo |
| URL Jira | Campo customizado no Odoo |
| Status Integração | Criado/Atualizado/Erro |

Exemplo de nome: `[TAD-123] Ajustar cálculo de IOF no relatório financeiro`

### 3.5 Apontamento / Timesheet Odoo

| Campo Odoo | Origem |
|---|---|
| Funcionário | De-para usuário Jira/Clockwork → funcionário Odoo |
| Projeto | De-para projeto Jira → projeto Odoo |
| Tarefa | Issue Jira sincronizada |
| Data | Data do worklog |
| Horas | Tempo apontado no Clockwork |
| Descrição | Comentário do worklog + chave Jira |
| Conta analítica | Projeto/Departamento calculado |
| External Worklog ID | ID do worklog Clockwork/Jira |
| External Issue ID | ID da issue Jira |
| Status Integração | Sucesso/Erro |

**Regra essencial:** o campo External Worklog ID deve ser único no Odoo para
evitar duplicidade. [constraint SQL em `account_analytic_line.py`]

## 4. Modelo de de-para

O de-para mora no Odoo (tabelas customizadas), porque o Odoo é o destino
contábil e gerencial — o de-para deve morar onde o impacto financeiro
acontece.

### 4.1 De-para de usuários [`jira.integration.user.mapping`]

| Campo | Descrição |
|---|---|
| jira_account_id | ID único do usuário no Jira |
| jira_email | E-mail do usuário |
| jira_display_name | Nome exibido no Jira |
| clockwork_user_id | ID no Clockwork, se aplicável |
| odoo_employee_id | Funcionário no Odoo |
| odoo_user_id | Usuário Odoo, se necessário |
| active | Ativo/Inativo |
| valid_from / valid_to | Vigência |

**Regra:** worklog → Jira Account ID → Odoo Employee ID. Sem de-para:
status = Erro (`ERROR_USER_MAPPING`), não criar timesheet, enviar para fila
de tratamento.

### 4.2 De-para de projetos [`jira.integration.project.mapping`]

| Campo | Descrição |
|---|---|
| jira_project_key | Chave do projeto Jira |
| jira_project_id | ID do projeto Jira |
| odoo_project_id | Projeto no Odoo |
| odoo_analytic_account_id | Conta analítica padrão |
| allocation_mode | Tipo de regra |
| active | Ativo/Inativo |

**allocation_mode:**

| Valor | Uso |
|---|---|
| DIRECT_PROJECT | Projeto Jira mapeia diretamente para projeto/conta analítica Odoo |
| BY_ISSUE_FIELD | Olhar campo do ticket para definir departamento/conta analítica |
| IGNORE | Projeto não integra |
| ERROR_IF_EMPTY | Integra somente se campos obrigatórios existirem |

## 5. Regra especial: projetos que dependem de campo do ticket

Existem projetos Jira (ex.: TAD) em que não basta olhar o projeto: é preciso
ler um campo do ticket para saber qual departamento da Dexterity recebe o
esforço. No Odoo, esse departamento corresponde a uma conta analítica.

```
Projeto normal:   AMS-CDV → Projeto "AMS Casa dos Ventos" → Conta "AMS Casa dos Ventos"
Projeto especial: TAD + Departamento=TRM            → Conta "Dexterity / TRM"
                  TAD + Departamento=Administrativo → Conta "Dexterity / Administrativo"
```

### 5.2 Tabela de regra por campo [`jira.integration.field.allocation`]

| Campo | Descrição |
|---|---|
| jira_project_key | Projeto Jira especial |
| jira_field_id | Campo customizado do Jira |
| jira_field_name | Nome amigável do campo |
| jira_field_value | Valor esperado |
| odoo_project_id | Projeto Odoo destino |
| odoo_analytic_account_id | Conta analítica destino |
| active | Ativo/Inativo |

Exemplo:

| Projeto | Campo | Valor | Projeto Odoo | Conta Analítica |
|---|---|---|---|---|
| TAD | Departamento | TRM | Interno Dexterity | TRM |
| TAD | Departamento | CLM | Interno Dexterity | CLM |
| TAD | Departamento | MRA | Interno Dexterity | MRA |
| TAD | Departamento | Administrativo | Interno Dexterity | Administrativo |
| TAD | Departamento | Comercial | Interno Dexterity | Comercial |
| TAD | Departamento | Treinamento | Interno Dexterity | Treinamento |

### 5.3 Regra de decisão [`allocation.py`]

1. Ler o projeto Jira da issue.
2. Verificar de-para do projeto.
3. `DIRECT_PROJECT` → usar projeto Odoo e conta analítica do de-para.
4. `BY_ISSUE_FIELD` → ler campo customizado; procurar (projeto + campo +
   valor) na tabela de alocação.
5. Encontrou → usar destino encontrado.
6. Não encontrou → **não integrar**, registrar erro, enviar para fila de
   manutenção de de-para.

## 6. Regras de criação de tarefas no Odoo

- **Quando criar:** issue com worklog integrado + ainda não existe no Odoo +
  projeto integrável + usuário mapeado + alocação determinada.
- **Identificação:** busca por `x_jira_issue_id` (ID interno), nunca apenas
  pela chave textual. Campos técnicos: `x_jira_issue_id`, `x_jira_issue_key`,
  `x_jira_issue_url`.
- **Nome:** `[JIRA_KEY] Summary`.
- **Atualização:** apenas campos seguros (nome, status Jira, link,
  conta analítica/projeto se a regra mudou e for permitido). **Não**
  atualizar a descrição depois da primeira carga (o time pode ter editado).

## 7. Regras de criação dos apontamentos

- **Unidade:** 1 worklog = 1 linha de timesheet (não consolidar por dia;
  consolidar perde rastreabilidade).
- **Chave única:** `x_external_worklog_id` — existe? atualiza; não existe?
  cria. [Regra 5]
- **Conversão de tempo:** segundos → horas decimais (3600 = 1,00; 1800 =
  0,50; 900 = 0,25). [`time_utils.py`]
- **Descrição:** `[JIRA_KEY] comentário` ou, sem comentário,
  `[JIRA_KEY] Apontamento importado do Clockwork`.

## 8. Alterações e exclusões

- **Alteração:** localizar por `x_external_worklog_id` e atualizar data,
  horas, descrição, funcionário (se permitido), projeto/conta (se a regra
  mudou).
- **Exclusão:** adotada a **Opção B** — não excluir fisicamente: marcar
  `x_integration_status = cancelled_source` e zerar horas. Período fechado →
  gerar exceção em vez de alterar.

## 9. Controle de competência e fechamento

Parâmetro: data limite de fechamento mensal
(`jira_clockwork_sync.closed_until`). Worklog alterado após o fechamento →
status `CLOSED_PERIOD`, pendente de aprovação administrativa. Para empresa de
consultoria: **bloquear alteração retroativa sem aprovação**.

## 10. Estados da integração

| Status | Significado |
|---|---|
| PENDING | Encontrado, ainda não processado / marcado para reprocesso |
| SUCCESS | Integrado com sucesso |
| ERROR_USER_MAPPING | Usuário sem de-para |
| ERROR_PROJECT_MAPPING | Projeto sem de-para |
| ERROR_ANALYTIC_MAPPING | Conta analítica não determinada |
| ERROR_ODOO | Erro técnico no Odoo |
| ERROR_JIRA | Erro técnico no Jira/Clockwork |
| SKIPPED | Ignorado por regra |
| CLOSED_PERIOD | Competência fechada |
| CANCELLED_SOURCE | Worklog excluído/cancelado na origem |

## 11. Telas de manutenção (menu "Integração Jira" no Odoo)

1. **Usuários** — listar usuários encontrados, mostrar sem vínculo,
   selecionar funcionário Odoo, ativar/inativar, último apontamento.
2. **Projetos** — mapear projeto Jira → projeto Odoo, conta analítica
   padrão, modo de alocação, última sincronização.
3. **Alocação por campo** — regra especial por projeto: campo Jira usado +
   valor → conta analítica destino.
4. **Erros de integração** — ver pendências, corrigir de-para, reprocessar,
   ignorar, exportar para Excel.

## 12. Frequência de execução

Executar a cada 15 ou 30 minutos: buscar worklogs alterados desde a última
execução → buscar issues → aplicar de-para → criar/atualizar tarefas →
criar/atualizar timesheets → registrar log.

**Carga inicial:** começar com mês corrente + mês anterior; expandir
histórico depois, se fizer sentido.

## 13. Campos customizados no Odoo

- **Tarefa:** `x_jira_issue_id`, `x_jira_issue_key`, `x_jira_issue_url`,
  `x_jira_project_key`, `x_jira_status`, `x_integration_source`,
  `x_last_sync_at`.
- **Timesheet:** `x_external_worklog_id`, `x_jira_issue_id`,
  `x_jira_issue_key`, `x_clockwork_user_id`, `x_jira_account_id`,
  `x_integration_status`, `x_integration_error_message`, `x_last_sync_at`.
- **Projeto:** `x_jira_project_key`, `x_integration_enabled`.

## 14. Regras de negócio consolidadas

1. **Só integrar projeto ativo** — projeto inativo no de-para: ignorar.
2. **Usuário precisa estar mapeado** — sem de-para: erro, sem timesheet.
3. **Projeto normal usa conta analítica padrão** (DIRECT_PROJECT).
4. **Projeto especial usa campo do ticket** (BY_ISSUE_FIELD); campo vazio →
   erro "campo de departamento obrigatório não preenchido".
5. **Não duplicar apontamento** — upsert por `x_external_worklog_id`.
6. **Não mexer em competência fechada sem aprovação.**
7. **Tarefa Odoo nasce automaticamente** quando há worklog válido de issue
   inexistente no Odoo.

## 15. Fluxo de processamento [`processor.py`]

1. Ler data/hora da última sincronização.
2. Buscar worklogs criados/alterados na janela.
3. Para cada worklog: identificar issue → buscar dados → identificar projeto
   → identificar usuário → de-para usuário → de-para projeto → projeto Odoo
   → conta analítica → competência aberta? → buscar/criar tarefa → buscar
   timesheet por External Worklog ID → criar/atualizar → registrar.
4. Registrar resumo da execução.

## 16. Exemplos práticos (cobertos por testes automatizados)

**Caso 1 — Projeto direto:** CDV-102 / Julian / 2h →
Projeto "Casa dos Ventos", tarefa `[CDV-102] Configurar curva DI x Pré`,
2,00h, conta analítica do de-para.

**Caso 2 — Projeto especial:** TAD-458 / Ana / 1,5h / Departamento =
Administrativo → Projeto "Interno Dexterity", tarefa
`[TAD-458] Criar procedimento interno de apontamento`, 1,50h, conta
"Dexterity / Administrativo".

## 17. Fases (roadmap)

- **Fase 1 — Base** *(implementada)*: de-paras, busca de worklogs, criação
  de tarefas/timesheets, chave externa anti-duplicidade, log.
- **Fase 2 — Projetos especiais** *(implementada)*: BY_ISSUE_FIELD, tabela
  de alocação, erro de campo vazio, tela de manutenção.
- **Fase 3 — Governança** *(parcial)*: tela de erros e reprocessamento ✔;
  competência fechada ✔; alertas por e-mail/Teams e relatório de
  divergências pendentes.
- **Fase 4 — Refinamento gerencial** *(pendente)*: dashboards de custo,
  comparativo Jira × Odoo, alertas de qualidade.

## 18. Decisões técnicas

- **De-para no Odoo** (impacto contábil mora lá).
- **Jira/Clockwork mandam; Odoo recebe** — não editar dados importados no
  Odoo; corrigir na origem.
- **Anti-duplicidade por IDs externos** (issue ID, worklog ID, account ID) —
  nunca por texto/nome/data.
- **Tarefa sem apontamento não é criada** no MVP (reduz volume e sujeira).
- **Campo de departamento vazio = não integra** — sem conta genérica.

## 19. Requisitos funcionais

| RF | Descrição | Status |
|---|---|---|
| RF01 | Sincronizar usuários (de-para) | ✔ |
| RF02 | Sincronizar projetos (de-para) | ✔ |
| RF03 | Criar tarefas a partir de issues com apontamento válido | ✔ |
| RF04 | Criar/atualizar timesheets a partir dos worklogs | ✔ |
| RF05 | Alocação direta (DIRECT_PROJECT) | ✔ |
| RF06 | Alocação por campo da issue (BY_ISSUE_FIELD) | ✔ |
| RF07 | Registrar erros com dados suficientes para correção | ✔ |
| RF08 | Reprocessamento após correção do de-para | ✔ |
| RF09 | Evitar duplicidade (tarefas e apontamentos) | ✔ |
| RF10 | Controlar período fechado | ✔ |

## 20. Requisitos não funcionais

| RNF | Descrição | Implementação |
|---|---|---|
| RNF01 | Rastreabilidade | Campos `x_*` em tarefa e timesheet |
| RNF02 | Segurança de credenciais | Variáveis de ambiente / `.env` fora do git |
| RNF03 | Idempotência | Upsert por IDs externos + constraints SQL |
| RNF04 | Auditabilidade | Log de integração + status/timestamps nas linhas |
| RNF05 | Baixo acoplamento | Regras de de-para 100% em tabela, zero hardcode |
| RNF06 | Reprocessamento de janelas sem duplicar | `backfill`/`reprocess` idempotentes |

## 21. Ponto crítico

A cadeia que precisa ser explícita e auditável:

```
Worklog → Usuário → Issue → Projeto Jira → Regra de alocação
       → Projeto Odoo → Conta Analítica → Timesheet
```

Se essa cadeia falhar silenciosamente, horas caem no lugar errado e o custo
do projeto distorce. Por isso: erro explícito + fila de manutenção, nunca
fallback para conta genérica.
