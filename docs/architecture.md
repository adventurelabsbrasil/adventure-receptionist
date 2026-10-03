# Buzz — arquitetura do MVP

## 1. Objetivo arquitetural

Construir um control plane de orquestração de agentes, independente de modelo, que receba
uma demanda em linguagem natural, selecione contexto explícito, escolha um executor e produza
handoffs rastreáveis.

O MVP começa com casos da Adventure, mas o core não pode depender da Adventure, de Osana, de um
cliente ou de um provider. Produtos, hosts, serviços e canais entram como entidades/contextos
explícitos, não como constantes do domínio.

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
  ├── Conversational approval protocol
  ├── Trace/event log
  ├── Runtime/provenance discovery (fase posterior)
  └── Storage adapter
        ↓
Model provider / Executor / Human
```

## 3. Interfaces principais

### `ModelProvider`

Recebe um pedido estruturado e devolve uma saída estruturada. Providers são adapters para
OpenAI, Anthropic, Ollama e outros. O core não deve importar SDK de provider.

O MVP começa com `DeterministicProvider` para testes sem rede. `provider_inventory()` apenas
detecta capabilities locais; não autentica, inicia servidor ou envia contexto.

### `TaskStore`

Persiste e consulta Tasks. O MVP usa filesystem local; SQLite, Postgres e Supabase são adapters
futuros.

### `SourceRegistry`

Descreve autoridade, status, frescura, proveniência, autenticação e política de fallback de cada
fonte. Uma fonte stale, deprecated ou indisponível não é substituída silenciosamente.

### `ExecutorRegistry`

O MVP mantém um catálogo local de perfis de executor (`receptionist`,
`software-diagnostic-specialist` e `human-operator`). A seleção é feita por perfil e capability,
com autonomia e aprovação validadas antes do handoff; nenhum fallback silencioso é permitido.

### `Handoff`

É o contrato entre etapas. Deve carregar objetivo, contexto permitido, resultado, incertezas,
próxima ação e política de autonomia.

### Estado local e trace

`LocalBuzzStore` é o adapter inicial do estado. Ele persiste tasks, runs e handoffs como JSON
independente e mantém `events.jsonl` append-only para reconstruir o trace de uma execução por
`run_id`. O domínio valida os contratos antes de qualquer gravação; um storage futuro pode
substituir esse adapter sem alterar a CLI ou a triagem.

A aprovação humana é estado local explícito: cada handoff que exige revisão cria um `Approval`
pendente. Os comandos `approve` e `reject` apenas persistem a decisão, atualizam o estado local
da task e registram o evento correspondente; não existe executor externo neste fluxo. Depois de
uma aprovação, `confirm-execution` pode registrar uma atestação humana idempotente e mover a task
para `completed`; esse comando não executa a proposta.

O protocolo conversacional é separado do transporte. Um `ApprovalPrompt` apresenta resumo,
proposta, limites, incertezas e opções de aprovar/rejeitar/ajustar. Uma resposta pode vir como
opção ou texto livre e é normalizada para `approve`, `reject`, `adjust`, `clarify` ou `unknown`.
Somente as duas primeiras fecham o `Approval`; ajuste, dúvida ou resposta ambígua mantém a
aprovação pendente. A CLI fornece apenas um simulador local; Telegram, IDE e outros canais são
adapters futuros, não dependências do core.

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

O MVP termina em `propose` para o caso Osana. `completed` significa execução confirmada por uma
pessoa, não execução realizada pelo Buzz.

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

OpenClaw, GitHub write connector, login multiusuário, MCP runtime, RAG/vector DB, LangGraph,
LangChain, A2A, dashboard web, banco remoto, telemetria externa e execução externa.

Descoberta de runtime também fica fora do primeiro MVP. Quando implementada, deverá separar, de
forma provider-neutral:

- host onde um processo está executando;
- serviço/deploy que hospeda o produto;
- canal que transporta a demanda;
- banco ou dependência consultada.

Cada afirmação deverá carregar fonte, timestamp, modo (`live` ou `snapshot`) e limitações.
Fonte indisponível será reportada como `unavailable`; o Buzz não abrirá túnel SSH ou escolherá
um host alternativo silenciosamente.

O primeiro slice local dessa capacidade está em `buzz inventory --fixture <path>`. Ele usa um
snapshot JSON explícito, sem rede ou fallback, e mantém conectados no trace os identificadores de
runtime e host e os campos de canal e transporte. Isso não constitui descoberta live nem prova que
um serviço esteja em operação.
