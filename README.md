# Adventure Receptionist

`adventure-receptionist` é o núcleo inicial do Adventure Agent Orchestration Control Plane.
`buzz` é a persona e o comando de entrada.

O MVP é local-first, model-agnostic e read-only por padrão. Ele valida o fluxo de intake,
triagem, contexto explícito, handoff e observabilidade antes de adicionar conectores externos.

## Desenvolvimento local

```bash
uv sync
uv run buzz --help
uv run buzz doctor
uv run buzz providers
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
buzz sources --manifest examples/osana/manifest.yaml
buzz preflight <task_id> --manifest examples/osana/manifest.yaml
buzz handoff <task_id>
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

O protótipo não autentica, não consulta GitHub e não executa escrita externa. O preflight usa
somente as fontes explicitamente declaradas no manifesto e bloqueia fontes materialmente stale,
deprecated, parciais ou indisponíveis.

`buzz providers` mostra capacidades locais sem autenticar ou enviar contexto. O provider
determinístico é o padrão offline; Ollama é uma opção explícita e, se indisponível, falha sem
fallback automático. O provider recebe somente os documentos selecionados pelo preflight.

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
