# Adventure Receptionist

`adventure-receptionist` é o núcleo inicial do Adventure Agent Orchestration Control Plane.
`buzz` é a persona e o comando de entrada.

## O que significa Buzz

Neste projeto, Buzz não significa buzz de marketing, tendência, hype ou volume de conversa.
Buzz é o sistema local-first de recepção, triagem, contexto explícito, handoff e controle
operacional dos agentes da Adventure — uma camada para separar sinal de ruído.

O MVP é local-first, model-agnostic e read-only por padrão. Ele valida o fluxo de intake,
triagem, contexto explícito, handoff e observabilidade antes de adicionar conectores externos.

## Desenvolvimento local

```bash
uv sync
uv run buzz --help
uv run buzz doctor
uv run buzz providers
uv run buzz executors
uv run buzz github-read --repo OWNER/REPOSITORY --snapshot path/to/github.json
uv run buzz init --scope project
```

Também é possível usar o pacote sem `uv`:

```bash
python -m buzz --help
```

## Fluxos de avaliação

```bash
buzz init --scope project
buzz intake --text "Diagnosticar o que falta para finalizar o Osana"
buzz triage --fixture evals/osana/diagnose-readiness.json
buzz eval
buzz sources --manifest examples/osana/manifest.yaml
buzz preflight <task_id> --manifest examples/osana/manifest.yaml
buzz handoff <task_id>
buzz blocked
buzz stale --manifest examples/liara/manifest.yaml
buzz pending-approvals
buzz review <task_id>
buzz prompt <task_id>
buzz respond <task_id> --by <human-id> --option 1
buzz respond <task_id> --by <human-id> --text "quero ajustar o escopo"
buzz diagnose <task_id>
buzz inventory --fixture examples/osana/snapshots/runtime-inventory.json
buzz inventory --connector github --repo OWNER/REPOSITORY --timeout 20
buzz approve <task_id> --by <human-id> --reason "reviewed locally"
buzz reject <task_id> --by <human-id> --reason "needs more evidence"
buzz confirm-execution <task_id> --by <human-id>
buzz briefing
```

Segundo caso, Liara como produto interno da Adventure:

```bash
buzz triage \
  --fixture evals/liara/diagnose-readiness.json \
  --manifest examples/liara/manifest.yaml
buzz triage \
  --fixture evals/liara/diagnose-readiness.json \
  --manifest examples/liara/manifest.yaml \
  --provider ollama
buzz sources --manifest examples/liara/manifest.yaml
```

Osana permanece como o caso principal; Liara verifica se o mesmo pipeline separa produto,
agente, runtime, dependências externas e estado confirmado por snapshot.

O protótipo não executa escrita externa. O connector GitHub só é acionado explicitamente por
`github-read`; o preflight usa somente as fontes explicitamente declaradas no manifesto e bloqueia fontes materialmente stale,
deprecated, parciais ou indisponíveis.

`buzz providers` mostra capacidades locais sem autenticar ou enviar contexto. O provider
determinístico é o padrão offline; Ollama é uma opção explícita e, se indisponível, falha sem
fallback automático. O provider recebe somente os documentos selecionados pelo preflight.

`buzz executors` mostra o catálogo local de perfis (`receptionist`,
`software-diagnostic-specialist` e `human-operator`). O registry valida capabilities, autonomia
e aprovação humana antes de criar um handoff. O `triage` cria uma aprovação pendente local;
`approve` e `reject` registram a decisão humana e o trace, sem executar qualquer efeito externo.
`buzz review` reúne o pacote read-only para a decisão humana: task, handoff, aprovação, contexto,
incertezas, próximos passos e trace.
`buzz prompt` transforma esse pacote em uma pergunta conversacional, com opções para aprovar,
rejeitar ou ajustar. `buzz respond` é somente um simulador local do protocolo: opções e texto livre
podem pedir esclarecimento/ajuste sem fechar a aprovação; apenas uma aprovação ou rejeição explícita
registra decisão. CLI é harness de desenvolvimento, não o transporte final.
`buzz diagnose` gera um relatório de prontidão determinístico a partir do snapshot selecionado
por um handoff aprovado; não persiste resultados nem acessa serviços externos.
`buzz confirm-execution` apenas registra que uma pessoa confirmou a execução e move a task de
`approved` para `completed`; o Buzz não executa a ação nem afirma ter produzido um efeito externo.

`buzz eval` executa os fixtures oficiais de Osana e Liara sem persistir tasks, runs ou handoffs.
Ele valida classificação, fontes, provider e handoff; use `--fixture` para executar apenas um
caso e `--provider ollama` para selecionar Ollama explicitamente.

O connector GitHub é explicitamente read-only. `buzz github-read` usa `gh` somente para
autenticação e leitura via `GET`; para integrar o resultado ao contexto, informe também um
`--manifest` e uma fonte allowlisted com `--source`. `--snapshot` permite validar o mesmo fluxo
offline sem chamar GitHub.

O manifesto de Osana aponta para `examples/osana/snapshots/github.json`, um snapshot read-only
provisório e sanitizado. Ele distingue o repositório dedicado vazio (`osana-aaas`), a implementação
em `adventure-labs` e as decisões canônicas em `ssot`, e oferece ao Buzz somente o contexto local
selecionado: identidade, capacidades, fronteiras, dependências, gates e perguntas abertas. Ele não
representa o MAP canônico nem estado live. O repositório `buzz` é explicitamente excluído: é o
produto Buzz, não contexto da Osana.

Os comandos `status`, `blocked`, `stale`, `pending-approvals` e `briefing` leem somente o estado
local já existente. Eles não criam `.buzz`, não chamam providers e organizam as próximas ações
em `must_do`, `unblock`, `delegate`, `waiting` e `watch`.

## Documentação

- [MVP specification](docs/mvp-spec.md)
- [Architecture](docs/architecture.md)
- [Implementation plan](docs/implementation-plan.md)

## Princípios

- contexto explícito e mínimo;
- fontes com autoridade, frescura e proveniência;
- saída estruturada antes de qualquer handoff;
- políticas e permissões controladas por código;
- incerteza material sempre marcada;
- qualquer efeito externo exige preview e aprovação.

O inventário aceita exatamente uma entrada explícita: `--fixture <path>` para snapshot local ou
`--connector github --repo OWNER/REPOSITORY` para a leitura live read-only do repositório e do
último sinal de workflow via `gh`. O connector GitHub não prova host, deploy ou canal: essas
afirmações permanecem `unavailable` quando não há evidência. Cada afirmação carrega fonte,
timestamp, modo e limitações; nenhum fallback, SSH implícito ou escrita externa é usado.
