from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import CompetitionConfig
from .premier_league import get_pl_config
from .worldcup import get_worldcup_config

__all__ = ["CompetitionConfig", "get_competition", "worldcup", "premier_league"]

_ALIASES = {
    "worldcup": "worldcup",
    "world-cup": "worldcup",
    "wc": "worldcup",
    "fifa": "worldcup",
    "fifa world cup": "worldcup",
    "pl": "premier-league",
    "epl": "premier-league",
    "premier": "premier-league",
    "premierleague": "premier-league",
    "premier_league": "premier-league",
    "premier-league": "premier-league",
    "premier league": "premier-league",
}


def get_competition(
    name: str = "worldcup",
    data_dir: str | Path | None = None,
) -> CompetitionConfig:
    """Resolve a competition name/alias to its `CompetitionConfig`.

    Raises ``KeyError`` for an unknown name. Silently defaulting to the World
    Cup would run a national-team simulation when the caller asked for a
    competition that does not exist.
    """
    key = str(name or "worldcup").strip().lower()
    try:
        canonical = _ALIASES[key]
    except KeyError:
        raise KeyError(
            f"unknown competition {name!r}; expected one of: "
            + ", ".join(sorted(_ALIASES))
        ) from None
    if canonical == "premier-league":
        return get_pl_config(data_dir)
    return get_worldcup_config(data_dir)


def list_competitions() -> list[str]:
    return ["worldcup", "premier-league"]