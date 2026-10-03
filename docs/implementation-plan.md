# Buzz — plano de implementação do MVP

## Resultado esperado

Executar localmente este fluxo:

```text
demanda natural
→ intake
→ classificação provisória
→ seleção de contexto Osana
→ complexidade alta
→ handoff ao especialista
→ briefing para revisão humana
→ trace local verificável
```

Sem autenticação externa, escrita externa ou uso de contexto global.

## Fases

### Fase 0 — fundação do repositório

Status: iniciada.

- pacote Python instalável via `uv`;
- comando `buzz`;
- CI para macOS, Linux e Windows;
- README e especificação;
- `.gitignore` para estado local;
- teste de instalação e `buzz doctor`.

Critério de saída: instalação local reproduzível e CLI com `--help`, `--version` e `doctor`.

### Fase 1 — domínio mínimo

Status: concluída no primeiro slice local.

- schemas para `Task`, `Entity`, `Source`, `ContextPack`, `Handoff`, `Run` e `Finding`;
- estados canônicos e transições válidas;
- storage local substituível para tasks, runs e handoffs;
- eventos JSONL append-only filtráveis por `run_id`;
- IDs estáveis; versionamento formal de schema fica como próximo hardening do domínio;
- política de incerteza `material_only`.

Critério de saída: estado válido rejeita transições inválidas, pode ser salvo/reaberto e deixa
trace local ordenado.

### Fase 2 — intake e triagem

Status: concluída no primeiro fluxo local Osana.

- intake natural ou por CLI;
- limite de três rodadas;
- classificação de entidade, ownership, purpose, lifecycle e client relation;
- detecção de ambiguidade;
- classificação de complexidade;
- criação de Task interna;
- resultado estruturado e validado.

Critério de saída: fixtures Osana e Liara produzem classificação provisória sem inventar dados
ausentes.

### Fase 3 — contexto e fontes

Status: concluída no primeiro registry local Osana.

- `SourceRegistry` local;
- manifesto de projeto;
- allowlist de fontes;
- status `verified`, `stale`, `deprecated`, `partial` e `unavailable`;
- preflight antes do raciocínio;
- snapshot local do MAP;
- bloqueio quando fonte material não está disponível;
- comandos locais `sources`, `preflight` e `handoff`.

Critério de saída: uma fonte não autenticada não é substituída silenciosamente por contexto antigo;
Liara usa snapshots locais sem simular estado live.

### Fase 4 — handoff e executores

Status: concluída no catálogo local de executores.

- `ExecutorRegistry` estático e versionado;
- profiles `receptionist`, `software-diagnostic-specialist` e `human-operator`;
- seleção por capability sem fallback silencioso;
- validação de autonomia `observe`/`propose`;
- aprovação humana e dados do executor registrados no handoff e no trace;
- comando `buzz executors` para inspeção local.

Critério de saída: o caso Osana gera um handoff revisável pelo operador.

### Fase 5 — provider LLM

Status: contrato offline iniciado.

- interface `ModelProvider`;
- contrato estruturado offline;
- adapter inicial para um provider selecionado;
- Ollama e provider por API como adapters separados;
- limites de tokens, custo, timeout e retry;
- structured output validado;
- nenhum SDK de provider vazando para o domínio.

Critério de saída: o mesmo intake funciona com dois providers sem mudar o domínio.

### Fase 6 — observabilidade e evals

- event log JSONL; (slice inicial entregue na Fase 1)
- `run_id`, `task_id`, `step_id` e `idempotency_key`;
- trace de calls, handoffs, policy checks e approvals;
- aprovação local pendente, decisão humana e transição de estado via CLI;
- confirmação humana pós-aprovação via `buzz confirm-execution`, com `execution.confirmed` no trace;
- prompt conversacional transport-neutral com opções e resposta livre;
- ajustes e dúvidas não fecham aprovação nem executam efeitos;
- `buzz run <run_id>` e `buzz run <run_id> --trace`;
- dataset de fixtures;
- evals de classificação, contexto, handoff, segurança e custo;
- comparação entre versões de prompt/modelo.

Critério de saída: uma regressão de roteamento ou contexto é detectável em eval local, e uma task
aprovada pode ser encerrada por confirmação humana sem executar efeitos externos.

### Slice transversal — approval gate conversacional

Status: concluído localmente; transporte externo ainda não iniciado. A confirmação humana de
execução também é local e não representa execução feita pelo Buzz.

- `ApprovalPrompt` separa a pergunta humana do armazenamento estruturado de `Approval`;
- opções explícitas para aprovar, rejeitar ou ajustar;
- normalização local de respostas por opção ou texto livre;
- dúvidas, ajustes e respostas ambíguas preservam o estado pendente;
- `buzz prompt` e `buzz respond` são harness local para validar o protocolo, não a UX final;
- nenhum canal, provider, host ou produto específico entra no contrato.

Critério de saída: uma aprovação humana pode ser conduzida como conversa e só uma decisão explícita
altera o estado local.

### Fase 7 — briefing operacional

- Status: concluída no primeiro briefing operacional local.

- `buzz status`;
- `buzz blocked`;
- `buzz stale`;
- `buzz pending-approvals`;
- `buzz briefing`;
- sinais de idade, bloqueio, espera, WIP e dependência;
- recomendações `must_do`, `unblock`, `delegate`, `waiting` e `watch`.

Critério de saída: o usuário recebe próximas ações explicadas, não apenas uma lista de status.

### Fase 8 — primeiro connector externo

- Status: concluída no primeiro adapter GitHub read-only.

- GitHub read-only;
- verificação de autenticação via `gh` sem expor token;
- snapshot e live read claramente diferenciados;
- deduplicação de issues/PRs;
- reread após qualquer futura escrita;
- nenhuma escrita no primeiro release do connector.

Critério de saída: o Buzz consegue consultar o MAP real sem usar fontes stale silenciosamente.

### Fase 9 — descoberta de runtime e proveniência

Status: primeiro slice local implementado; conectores live continuam adiados.

O Buzz deve conseguir responder de onde um produto/agente está operando sem confundir canal,
host e serviço. Essa capacidade é transversal e não pertence apenas ao Osana.

- inventário read-only de hosts e runtimes registrados, independentemente do provedor;
- descoberta de metadados de deploy e serviço, sem executar SSH implícito;
- identificação de canais e transportes (CLI, mensageria, webhook e similares);
- correlação entre produto, runtime, banco, deploy e canal;
- proveniência explícita no trace: `runtime_id`, `host_id`, `channel`, `transport` e modo live/snapshot;
- estado `unavailable` quando uma fonte não responder, sem fallback silencioso ou inferência;
- credenciais e efeitos externos continuam fora do diagnóstico por padrão;
- consultas live somente por connector explicitamente selecionado e read-only.

O primeiro slice local implementado é o comando `buzz inventory --fixture <path>`, que lê um único
snapshot JSON local explicitamente selecionado. O primeiro connector live implementado é
`buzz inventory --connector github --repo OWNER/REPOSITORY`: ele consulta apenas a autoridade
GitHub via `gh` em modo read-only. O contrato normaliza fontes e afirmações com autoridade,
timestamp, modo, status e limitações; também expõe no trace `runtime_id`, `host_id`, `channel` e
`transport`. GitHub não prova host, deploy ou canal; essas afirmações ficam `unavailable`. Não há
fallback entre connector e snapshot, SSH implícito, deploy ou escrita externa.

Critério de saída: dado um produto/agente, o Buzz produz um inventário estruturado que distingue
onde o código está, onde o serviço está rodando e por qual canal recebe tráfego, com evidência,
timestamp, autoridade e limitações de cada fonte.

MacBook, Xeon, VPS, Osana e Telegram são exemplos de adapters/contextos possíveis da Adventure,
não dependências do core nem nomes fixos do contrato.

## Ordem de execução recomendada

```text
Fase 0 → Fase 1 → Fase 2 → Fase 3 → Fase 4
→ Fase 5 → Fase 6 → Fase 7 → Fase 8 → Fase 9
```

Não iniciar Fase 8 antes de o preflight de fontes e a observabilidade local estarem funcionando.

## Definition of Done do MVP

- `uv sync` funciona;
- `buzz init`, `doctor`, `status`, `briefing`, `intake` e `triage` funcionam;
- o fluxo Osana roda sem login e sem rede;
- o contexto usado é explícito;
- o resultado identifica incertezas materiais;
- o handoff é estruturado;
- cada run deixa trace local;
- o eval passa com fixture conhecida;
- não há segredo em arquivos versionáveis;
- macOS é validado e CI está preparado para Linux/Windows;
- Escritas GitHub e demais efeitos externos continuam bloqueados.
- Descoberta de runtime fica planejada para a Fase 9, sem ser requisito do primeiro MVP.

## Decisões adiadas

- provider LLM inicial;
- formato final do catálogo remoto;
- SQLite versus Postgres/Supabase;
- MCP e ferramentas remotas;
- notificações agendadas;
- extensão visual de VS Code;
- sincronização bidirecional com gestores de tarefas.
