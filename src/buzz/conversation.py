from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ApprovalOption:
    """A transport-neutral choice shown to a human reviewer."""

    key: str
    label: str
    description: str
    response_kind: str


@dataclass(frozen=True)
class ApprovalPrompt:
    """Human-readable approval request derived from a structured review packet."""

    task_id: str
    approval_id: str
    headline: str
    summary: str
    proposed_action: str
    safeguards: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    options: list[ApprovalOption] = field(default_factory=list)
    question: str = "Posso prosseguir?"
    external_effects: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        lines = [
            self.headline,
            "",
            self.summary,
            "",
            f"Proposta: {self.proposed_action}",
        ]
        if self.safeguards:
            lines.extend(["", "Limites desta etapa:"])
            lines.extend(f"- {item}" for item in self.safeguards)
        if self.uncertainties:
            lines.extend(["", "Ainda não confirmado:"])
            lines.extend(f"- {item}" for item in self.uncertainties)
        if self.options:
            lines.extend(["", "Escolha uma opção ou responda com suas próprias palavras:"])
            lines.extend(f"{option.key}. {option.label} — {option.description}" for option in self.options)
        lines.extend(["", self.question])
        return "\n".join(lines)


@dataclass(frozen=True)
class ApprovalResponse:
    kind: str
    text: str
    option_key: str | None = None


@dataclass(frozen=True)
class ConversationInput:
    """Transport envelope carrying a human response."""

    conversation_id: str
    channel: str
    transport: str
    actor_id: str
    task_id: str
    approval_id: str
    idempotency_key: str
    text: str | None = None
    option_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("Conversation input requires a human actor identity")
        for name in (
            "conversation_id", "channel", "transport", "actor_id", "task_id",
            "approval_id", "idempotency_key",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"Conversation input requires {name}")
        if not (self.text or self.option_key):
            raise ValueError("Conversation input requires text or option_key")


@dataclass(frozen=True)
class ConversationOutput:
    """Transport envelope returned to a channel without sending anything."""

    conversation_id: str
    channel: str
    transport: str
    actor_id: str | None
    task_id: str
    approval_id: str
    idempotency_key: str
    text: str
    response: ApprovalResponse | None = None
    buttons: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


class ConversationTransport(Protocol):
    """Contract implemented by local, Telegram, IDE or future transports."""

    channel: str
    name: str

    def render(self, prompt: ApprovalPrompt, *, conversation_id: str) -> ConversationOutput:
        ...

    def receive(self, envelope: ConversationInput, prompt: ApprovalPrompt) -> ApprovalResponse:
        ...


class _BaseDryRunTransport:
    def __init__(self, *, channel: str, name: str) -> None:
        self.channel = channel
        self.name = name

    def render(self, prompt: ApprovalPrompt, *, conversation_id: str) -> ConversationOutput:
        return ConversationOutput(
            conversation_id=conversation_id,
            channel=self.channel,
            transport=self.name,
            actor_id=None,
            task_id=prompt.task_id,
            approval_id=prompt.approval_id,
            idempotency_key=f"prompt:{conversation_id}:{prompt.approval_id}",
            text=prompt.render(),
            buttons=[
                {"key": option.key, "label": option.label, "description": option.description}
                for option in prompt.options
            ],
        )

    def receive(self, envelope: ConversationInput, prompt: ApprovalPrompt) -> ApprovalResponse:
        envelope.validate()
        if envelope.channel != self.channel or envelope.transport != self.name:
            raise ValueError("Conversation envelope does not match the selected transport")
        if envelope.task_id != prompt.task_id or envelope.approval_id != prompt.approval_id:
            raise ValueError("Conversation envelope correlation does not match the approval")
        return parse_approval_response(envelope.option_key or envelope.text or "", prompt)


class LocalConversationTransport(_BaseDryRunTransport):
    def __init__(self) -> None:
        super().__init__(channel="local", name="local-dry-run")


class TelegramDryRunTransport(_BaseDryRunTransport):
    """Telegram-shaped rendering only; it never imports a client or sends network traffic."""

    def __init__(self) -> None:
        super().__init__(channel="telegram", name="telegram-dry-run")


def build_approval_prompt(task: dict[str, Any], handoff: dict[str, Any], approval: dict[str, Any]) -> ApprovalPrompt:
    """Build a channel-independent prompt; no provider or network is involved."""
    project = task.get("project_id") or "este contexto"
    action = _proposed_action(handoff)
    return ApprovalPrompt(
        task_id=task["task_id"],
        approval_id=approval["approval_id"],
        headline=f"Revisão necessária: {task['objective']}",
        summary=(
            f"Encontrei uma proposta para {project}. "
            "O próximo passo depende da sua decisão humana."
        ),
        proposed_action=action,
        safeguards=[
            "A etapa é local e somente leitura.",
            "Nenhum login, acesso externo, mensagem ou alteração será feito.",
            "A decisão ficará registrada no trace local.",
        ],
        uncertainties=task.get("unknowns", []),
        options=[
            ApprovalOption("1", "Aprovar", "executar somente a proposta descrita acima", "approve"),
            ApprovalOption("2", "Rejeitar", "não executar esta proposta", "reject"),
            ApprovalOption("3", "Ajustar", "alterar escopo ou esclarecer antes de decidir", "adjust"),
        ],
        question="Posso prosseguir com essa proposta? (1/2/3 ou escreva o que deseja ajustar)",
    )


def parse_approval_response(text: str, prompt: ApprovalPrompt) -> ApprovalResponse:
    """Normalize button-like and free-text replies without making a decision."""
    normalized = " ".join(text.strip().lower().split())
    for option in prompt.options:
        if normalized == option.key or normalized.startswith(f"{option.key} "):
            return ApprovalResponse(option.response_kind, text, option.key)
        if normalized == option.label.lower():
            return ApprovalResponse(option.response_kind, text, option.key)

    if normalized in {"sim", "s", "yes", "y", "aprovo", "aprovado", "pode", "pode prosseguir", "ok"}:
        return ApprovalResponse("approve", text)
    if normalized in {"não", "nao", "n", "no", "rejeito", "rejeitado", "pare", "cancelar"} or any(
        marker in normalized for marker in ("não vou aprovar", "nao vou aprovar", "não aprovo", "nao aprovo")
    ):
        return ApprovalResponse("reject", text)
    if any(marker in normalized for marker in ("ajust", "mud", "alter", "mas ", "porém", "porem")):
        return ApprovalResponse("adjust", text)
    if normalized.endswith("?") or any(marker in normalized for marker in ("como ", "qual ", "por que", "porque ")):
        return ApprovalResponse("clarify", text)
    return ApprovalResponse("unknown", text)


def _proposed_action(handoff: dict[str, Any]) -> str:
    actions = handoff.get("next_actions", [])
    if actions:
        return actions[0]
    return handoff.get("objective", "continuar a tarefa proposta")
