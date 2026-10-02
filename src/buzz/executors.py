from __future__ import annotations

from dataclasses import dataclass

from .models import AUTONOMY_LEVELS


class ExecutorError(ValueError):
    """Raised when an executor cannot safely be selected or assigned."""


@dataclass(frozen=True)
class ExecutorProfile:
    executor_id: str
    description: str
    capabilities: frozenset[str]
    autonomy_levels: frozenset[str]
    requires_human_approval: bool = True

    def supports(self, required_capabilities: list[str]) -> bool:
        return set(required_capabilities).issubset(self.capabilities)

    def supports_autonomy(self, autonomy_level: str) -> bool:
        return autonomy_level in self.autonomy_levels

    def to_dict(self) -> dict[str, object]:
        return {
            "executor_id": self.executor_id,
            "description": self.description,
            "capabilities": sorted(self.capabilities),
            "autonomy_levels": sorted(self.autonomy_levels),
            "requires_human_approval": self.requires_human_approval,
        }


class ExecutorRegistry:
    """Static, local catalog of executors available to the Buzz MVP."""

    def __init__(self, profiles: list[ExecutorProfile]) -> None:
        self._profiles = {profile.executor_id: profile for profile in profiles}

    @classmethod
    def default(cls) -> "ExecutorRegistry":
        safe_levels = frozenset({"observe", "propose"})
        return cls([
            ExecutorProfile(
                executor_id="receptionist",
                description="Receives demands, classifies them and assembles explicit context.",
                capabilities=frozenset({"intake", "classify", "select-context"}),
                autonomy_levels=safe_levels,
                requires_human_approval=False,
            ),
            ExecutorProfile(
                executor_id="software-diagnostic-specialist",
                description="Diagnoses software readiness, dependencies and operational gaps.",
                capabilities=frozenset({"diagnose-readiness", "inspect-repository", "prepare-handoff"}),
                autonomy_levels=safe_levels,
            ),
            ExecutorProfile(
                executor_id="human-operator",
                description="Reviews proposals and records human decisions.",
                capabilities=frozenset({"review", "approve", "reject"}),
                autonomy_levels=safe_levels,
            ),
        ])

    def ids(self) -> list[str]:
        return list(self._profiles)

    def summary(self) -> list[dict[str, object]]:
        return [self._profiles[executor_id].to_dict() for executor_id in self.ids()]

    def get(self, executor_id: str) -> ExecutorProfile:
        try:
            return self._profiles[executor_id]
        except KeyError as exc:
            raise ExecutorError(f"Unknown executor profile: {executor_id}") from exc

    def select(self, *, required_capabilities: list[str], preferred_profile: str | None = None) -> ExecutorProfile:
        if preferred_profile is not None:
            profile = self.get(preferred_profile)
            if not profile.supports(required_capabilities):
                raise ExecutorError(
                    f"Executor {preferred_profile} does not support capabilities: "
                    f"{', '.join(required_capabilities)}"
                )
            return profile
        for profile in self._profiles.values():
            if profile.supports(required_capabilities):
                return profile
        raise ExecutorError(
            "No executor supports capabilities: "
            f"{', '.join(required_capabilities)}"
        )

    def validate_assignment(self, executor_id: str, autonomy_level: str) -> ExecutorProfile:
        if autonomy_level not in AUTONOMY_LEVELS:
            raise ExecutorError(f"Unknown autonomy level: {autonomy_level}")
        profile = self.get(executor_id)
        if not profile.supports_autonomy(autonomy_level):
            raise ExecutorError(
                f"Executor {executor_id} does not support autonomy: {autonomy_level}"
            )
        return profile
