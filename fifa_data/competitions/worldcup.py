from __future__ import annotations

import os
from pathlib import Path

from .base import CompetitionConfig

HERE = Path(__file__).resolve().parents[1]


def load_worldcup_data(data_dir: str | Path | None = None) -> tuple[dict, dict]:
    """Load World Cup team metrics + groups from ``worldcupsimulator.py``.

    The dynamic data block is executed with a shared globals dict, which is the
    same behaviour the original bot used before competitions were registry-based.
    """
    base = Path(data_dir) if data_dir else HERE
    path = os.path.join(base, "worldcupsimulator.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    data_block = content.split("RAW_ROSTERS")[0]
    data_block = data_block.replace("from numpy.random import poisson\n", "")
    data_block = data_block.replace("import pandas as pd\n", "")
    g = {"TEAM_METRICS": {}, "GROUPS": {}}
    exec(data_block, g)
    return g.get("TEAM_METRICS", {}), g.get("GROUPS", {})


def get_worldcup_config(data_dir: str | Path | None = None) -> CompetitionConfig:
    base = Path(data_dir) if data_dir else HERE
    from ..services._match_config import MATCHES_TEAM_MAP

    metrics, groups = load_worldcup_data(base)
    teams: list[str] = []
    for members in groups.values():
        teams.extend(members)
    config = CompetitionConfig(
        name="worldcup",
        format="groups_knockout",
        teams=teams,
        groups=groups,
        team_metrics=metrics,
        team_name_map=MATCHES_TEAM_MAP,
        matches_file=str(base / "data" / "matches.json"),
        competition_label="FIFA World Cup 2026",
        stage_names=[
            "Group Stage",
            "Round of 32",
            "Round of 16",
            "Quarter-Finals",
            "Semi-Finals",
            "Final",
            "Third-Place Play-off",
        ],
    )
    return config