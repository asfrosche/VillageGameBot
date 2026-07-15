from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ComponentScore:
    component: str
    value: float
    source: str
    confidence: float = 1.0


@dataclass(frozen=True)
class DynamicState:
    team: str
    chemistry: ComponentScore = field(default_factory=lambda: ComponentScore("chemistry", 0.0, "No chemistry data"))
    experience: ComponentScore = field(default_factory=lambda: ComponentScore("experience", 0.0, "No experience data"))
    form: ComponentScore = field(default_factory=lambda: ComponentScore("form", 0.0, "No form data"))
    momentum: ComponentScore = field(default_factory=lambda: ComponentScore("momentum", 0.0, "No momentum data"))
    continuity: ComponentScore = field(default_factory=lambda: ComponentScore("continuity", 0.0, "No continuity data"))
    leadership: ComponentScore = field(default_factory=lambda: ComponentScore("leadership", 0.0, "No leadership data"))

    def combined_multiplier(self) -> float:
        total = (
            self.chemistry.value
            + self.experience.value
            + self.form.value
            + self.momentum.value
            + self.continuity.value
            + self.leadership.value
        )
        return max(0.80, min(1.20, 1.0 + total))

    def components(self) -> list[ComponentScore]:
        return [self.chemistry, self.experience, self.form, self.momentum, self.continuity, self.leadership]
