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

- schemas para `Task`, `Entity`, `Source`, `ContextPack`, `Handoff`, `Run` e `Finding`;
- estados canônicos e transições válidas;
- storage local substituível;
- IDs estáveis e versionamento de schema;
- política de incerteza `material_only`.

Critério de saída: estado válido rejeita transições inválidas e pode ser salvo/reaberto.

### Fase 2 — intake e triagem

- intake natural ou por CLI;
- limite de três rodadas;
- classificação de entidade, ownership, purpose, lifecycle e client relation;
- detecção de ambiguidade;
- classificação de complexidade;
- criação de Task interna;
- resultado estruturado e validado.

Critério de saída: fixture Osana produz classificação provisória sem inventar dados ausentes.

### Fase 3 — contexto e fontes

- `SourceRegistry` local;
- manifesto de projeto;
- allowlist de fontes;
- status `verified`, `stale`, `deprecated`, `partial` e `unavailable`;
- preflight antes do raciocínio;
- snapshot local do MAP;
- bloqueio quando fonte material não está disponível.

Critério de saída: uma fonte não autenticada não é substituída silenciosamente por contexto antigo.

### Fase 4 — handoff e executores

- `ExecutorRegistry`;
- profiles `receptionist`, `software-diagnostic-specialist` e `human-operator`;
- handoff estruturado;
- seleção de um executor por etapa;
- autonomia `observe`/`propose`;
- aprovação humana registrada.

Critério de saída: o caso Osana gera um handoff revisável pelo operador.

### Fase 5 — provider LLM

- interface `ModelProvider`;
- adapter inicial para um provider selecionado;
- Ollama e provider por API como adapters separados;
- limites de tokens, custo, timeout e retry;
- structured output validado;
- nenhum SDK de provider vazando para o domínio.

Critério de saída: o mesmo intake funciona com dois providers sem mudar o domínio.

### Fase 6 — observabilidade e evals

- event log JSONL;
- `run_id`, `task_id`, `step_id` e `idempotency_key`;
- trace de calls, handoffs, policy checks e approvals;
- `buzz run show` e `buzz run trace`;
- dataset de fixtures;
- evals de classificação, contexto, handoff, segurança e custo;
- comparação entre versões de prompt/modelo.

Critério de saída: uma regressão de roteamento ou contexto é detectável em eval local.

### Fase 7 — briefing operacional

- `buzz status`;
- `buzz blocked`;
- `buzz stale`;
- `buzz pending-approvals`;
- `buzz briefing`;
- sinais de idade, bloqueio, espera, WIP e dependência;
- recomendações `must_do`, `unblock`, `delegate`, `waiting` e `watch`.

Critério de saída: o usuário recebe próximas ações explicadas, não apenas uma lista de status.

### Fase 8 — primeiro connector externo

- GitHub read-only;
- verificação de autenticação via `gh` sem expor token;
- snapshot e live read claramente diferenciados;
- deduplicação de issues/PRs;
- reread após qualquer futura escrita;
- nenhuma escrita no primeiro release do connector.

Critério de saída: o Buzz consegue consultar o MAP real sem usar fontes stale silenciosamente.

## Ordem de execução recomendada

```text
Fase 0 → Fase 1 → Fase 2 → Fase 3 → Fase 4
→ Fase 5 → Fase 6 → Fase 7 → Fase 8
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
- GitHub live e efeitos externos continuam bloqueados.

## Decisões adiadas

- provider LLM inicial;
- formato final do catálogo remoto;
- SQLite versus Postgres/Supabase;
- MCP e ferramentas remotas;
- notificações agendadas;
- extensão visual de VS Code;
- sincronização bidirecional com gestores de tarefas.
