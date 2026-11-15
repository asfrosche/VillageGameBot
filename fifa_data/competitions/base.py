from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CompetitionConfig:
    """Configuration for a simulation competition.

    `format` is either ``"groups_knockout"`` (World Cup style) or ``"league``
    (double round-robin, e.g. Premier League).

    The data-file fields make each competition the single source of truth for
    the files its squads are built from, so callers never hard-code paths.

    `national_data` gates every national-team-keyed data source
    (``player_experience.json``, ``tactical_profiles.json``,
    ``manager_profiles.json``, ``national_strength_modifiers.json``,
    ``known_lineups.json``). Those files describe countries, not clubs, so a
    club competition must set this to ``False`` to keep World Cup squads and
    international caps out of club ratings.
    """

    name: str
    format: str = "groups_knockout"
    teams: list[str] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)
    team_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    codes: dict[str, str] = field(default_factory=dict)
    team_name_map: dict[str, str] = field(default_factory=dict)
    matches_file: str | None = None
    rosters_file: str | None = None
    players_file: str | None = None
    squads_file: str | None = None
    form_cache_file: str | None = None
    national_data: bool = True
    home_elo_bonus: float = 0.0
    matchdays: int = 0
    competition_label: str = ""
    stage_names: list[str] = field(default_factory=list)



def resolve_matches_file(data_dir: Path, config: CompetitionConfig) -> Path:
    if config.matches_file:
        path = Path(config.matches_file)
        if not path.is_absolute():
            path = data_dir / path
        return path
    return data_dir / "data" / "matches.json"