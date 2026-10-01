# Buzz — arquitetura do MVP

## 1. Objetivo arquitetural

Construir um control plane de orquestração de agentes, independente de modelo, que receba
uma demanda em linguagem natural, selecione contexto explícito, escolha um executor e produza
handoffs rastreáveis.

O MVP é Adventure-first, mas o core não pode depender de Osana, de um cliente ou de um provider.

## 2. Camadas

```text
CLI / Codex / IDE
        ↓
Receptionist / Intake
        ↓
Control plane / Harness
  ├── Task state
  ├── Context manager
  ├── Source registry
  ├── Policy engine
  ├── Capability registry
  ├── Model router
  ├── Handoff protocol
  ├── Approval gates
  ├── Trace/event log
  └── Storage adapter
        ↓
Model provider / Executor / Human
```

## 3. Interfaces principais

### `ModelProvider`

Recebe um pedido estruturado e devolve uma saída estruturada. Providers são adapters para
OpenAI, Anthropic, Ollama e outros. O core não deve importar SDK de provider.

### `TaskStore`

Persiste e consulta Tasks. O MVP usa filesystem local; SQLite, Postgres e Supabase são adapters
futuros.

### `SourceRegistry`

Descreve autoridade, status, frescura, proveniência, autenticação e política de fallback de cada
fonte. Uma fonte stale, deprecated ou indisponível não é substituída silenciosamente.

### `ExecutorRegistry`

Cataloga skills, agents, tools, providers e humanos. A seleção é feita por perfil e capability,
não por nomes hardcoded no fluxo.

### `Handoff`

É o contrato entre etapas. Deve carregar objetivo, contexto permitido, resultado, incertezas,
próxima ação e política de autonomia.

### Estado local e trace

`LocalBuzzStore` é o adapter inicial do estado. Ele persiste tasks, runs e handoffs como JSON
independente e mantém `events.jsonl` append-only para reconstruir o trace de uma execução por
`run_id`. O domínio valida os contratos antes de qualquer gravação; um storage futuro pode
substituir esse adapter sem alterar a CLI ou a triagem.

## 4. Estado e autonomia

Pipeline canônica:

```text
captured → triage → ready → in_progress → waiting → in_review
→ approved → completed → archived
```

`blocked` é um estado recuperável da pipeline, com retorno explícito para `ready`,
`in_progress` ou `waiting`.

Níveis de autonomia:

```text
observe → propose → execute-local → execute-external
```

O MVP termina em `propose` para o caso Osana.

## 5. Segurança e confiabilidade

- LLM interpreta; código controla estado, policy, contexto e permissões.
- Toda saída relevante passa por schema validado.
- Conteúdo externo é dado não confiável, nunca instrução de sistema.
- Escritas externas exigem `preview → approval → execute → reread → verify`.
- Segredos nunca entram em chat, logs, prompts ou artefatos.
- Cada run registra versões de código, profile, prompt, schema, policy, modelo e fontes.
- Runs têm timeout, retry, limite de tokens/custo e idempotency key.

## 6. Contexto

O contexto é montado por referência, não por carregamento global:

```text
conversation → context pack → specialist context pack → handoff
```

O usuário/Codex pode fornecer dados ao Buzz por um `context pack` explícito. Memória global,
SSOT geral e outros projetos não entram automaticamente.

## 7. Fora do MVP

OpenClaw, live GitHub connector, login multiusuário, MCP runtime, RAG/vector DB, LangGraph,
LangChain, A2A, dashboard web, banco remoto, telemetria externa e execução externa.
