"""Reusable stage pipeline.

A competition is modelled as an ordered list of *stages*. A stage is a
self-contained chunk of the flow (a group round, a knockout round, a matchday
phase, a standings resolution) that reads shared context and writes public
state.

:class:`StagePipeline` is the single shared logical loop that drives any
competition. Each competition supplies its OWN stage list, so the World Cup
(group stage + knockout rounds) and the Premier League (season + standings)
never share stage logic - only the match engine underneath. This mirrors how
the club game maps the tournament's stages onto a league calendar.

A partial run stops the loop after one named stage, which makes a simulation
resumable and lets callers inspect the competition at any checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..engines.base_engine import MatchEngine
    from .orchestrator import LeagueOrchestrator, TournamentOrchestrator


@dataclass
class StageContext:
    """Mutable state flowing through a pipeline.

    ``orchestrator`` owns the real-result lookups, fixture helpers and the
    match engine, so the concrete stages in ``orchestrator.py`` reuse the
    exact existing simulation behaviour (RNG order, debug capture, goal
    minutes, real-result merging) while the pipeline stays generic.
    """

    orchestrator: "TournamentOrchestrator | LeagueOrchestrator"
    debug: bool = False
    matches_data: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)

    @property
    def match_engine(self) -> "MatchEngine":
        return self.orchestrator.match_engine


class Stage:
    """One atomic unit of a competition's flow."""

    name: str = ""
    """Public label shown in ``result["stages"]``."""

    def run(self, ctx: StageContext) -> Any:
        """Execute this stage. Return value is stored under ``ctx.outputs[self.name]``."""
        raise NotImplementedError


class StagePipeline:
    """The shared logical loop: run a competition's stages in order."""

    def __init__(self, stages: list[Stage]) -> None:
        self.stages = list(stages)

    def run(self, ctx: StageContext, stop_after: str | None = None) -> list[str]:
        """Run stages until ``stop_after`` (inclusive) or the list is exhausted.

        Returns the names of the stages that actually ran this time.
        """
        completed: list[str] = []
        for stage in self.stages:
            payload = stage.run(ctx)
            if payload is not None:
                ctx.outputs[stage.name] = payload
            completed.append(stage.name)
            if stop_after is not None and stage.name == stop_after:
                break
        return completed

    @property
    def names(self) -> list[str]:
        return [stage.name for stage in self.stages]