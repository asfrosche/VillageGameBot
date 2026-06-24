import json
import os
from pathlib import Path

from ..engines.v1_elo_engine import V1EloMatchEngine
from ..engines.v2_player_engine import V2PlayerMatchEngine
from ..engines.v3_dynamic_engine import V3DynamicEngine
from ..engines.v4_tactical_engine import V4TacticalEngine
from ..engines.v5_match_state_engine import V5MatchStateEngine
from .orchestrator import TournamentOrchestrator

HERE = Path(__file__).resolve().parents[1]

MATCHES_TEAM_MAP = {
    "USA": "United States",
    "Cabo Verde": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "South Korea": "Korea Republic",
    "Czech Republic": "Czechia",
    "Turkey": "Türkiye",
    "Iran": "IR Iran",
}

TEAM_METRICS = {}
GROUPS = {}


def _load_worldcup_data():
    path = os.path.join(HERE, "worldcupsimulator.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    data_block = content.split("RAW_ROSTERS")[0]
    data_block = data_block.replace("from numpy.random import poisson\n", "")
    g = {"TEAM_METRICS": TEAM_METRICS, "GROUPS": GROUPS}
    exec(data_block, g)
    TEAM_METRICS.update(g.get("TEAM_METRICS", {}))
    GROUPS.update(g.get("GROUPS", {}))
    return TEAM_METRICS, GROUPS


TEAM_METRICS, GROUPS = _load_worldcup_data()


def reset_metrics():
    TEAM_METRICS.clear()
    GROUPS.clear()
    _load_worldcup_data()


def update_elo_from_matches(matches_file=None):
    if matches_file is None:
        matches_file = os.path.join(HERE, "data", "matches.json")
    with open(matches_file, encoding="utf-8") as f:
        data = json.load(f)
    completed = data.get("completed", [])
    k_elo = 20
    k_pele = 20
    for match in completed:
        home_name = MATCHES_TEAM_MAP.get(match["home"]["name"], match["home"]["name"])
        away_name = MATCHES_TEAM_MAP.get(match["away"]["name"], match["away"]["name"])
        if home_name not in TEAM_METRICS or away_name not in TEAM_METRICS:
            continue
        home_goals = match["home"]["score"]
        away_goals = match["away"]["score"]
        r1 = (TEAM_METRICS[home_name]["ELO"] + TEAM_METRICS[home_name]["PELE"]) / 2
        r2 = (TEAM_METRICS[away_name]["ELO"] + TEAM_METRICS[away_name]["PELE"]) / 2
        we1 = 1 / (1 + 10 ** ((r2 - r1) / 400))
        if home_goals > away_goals:
            w1 = 1.0
        elif home_goals < away_goals:
            w1 = 0.0
        else:
            w1 = 0.5
        gd = abs(home_goals - away_goals)
        if gd <= 1:
            g_mult = 1.0
        elif gd == 2:
            g_mult = 1.5
        else:
            g_mult = 2.0
        delta = (w1 - we1) * g_mult
        TEAM_METRICS[home_name]["ELO"] = round(TEAM_METRICS[home_name]["ELO"] + k_elo * delta)
        TEAM_METRICS[away_name]["ELO"] = round(TEAM_METRICS[away_name]["ELO"] - k_elo * delta)
        TEAM_METRICS[home_name]["PELE"] = round(TEAM_METRICS[home_name]["PELE"] + k_pele * delta)
        TEAM_METRICS[away_name]["PELE"] = round(TEAM_METRICS[away_name]["PELE"] - k_pele * delta)


def _v1_engine():
    return V1EloMatchEngine(TEAM_METRICS)


def sim_match(t1, t2, can_draw=True):
    return _v1_engine().simulate_match(t1, t2, can_draw)


def generate_goals(g1, g2):
    """Generate goal minutes for a given final score."""
    return TournamentOrchestrator._generate_goals(g1, g2)


def run_simulation(model="v1", debug=False):
    """Run the full simulation and return structured data."""
    normalized_model = (model or "v1").lower()
    if normalized_model == "v1":
        update_elo_from_matches()
        engine = _v1_engine()
    elif normalized_model == "v2":
        engine = V2PlayerMatchEngine(data_dir=HERE)
    elif normalized_model == "v3":
        engine = V3DynamicEngine(data_dir=HERE)
    elif normalized_model == "v4":
        engine = V4TacticalEngine(data_dir=HERE)
    elif normalized_model == "v5":
        engine = V5MatchStateEngine(data_dir=HERE)
    else:
        raise ValueError(f"Unknown simulation model: {model}")

    orchestrator = TournamentOrchestrator(
        groups=GROUPS,
        match_engine=engine,
        matches_file=os.path.join(HERE, "data", "matches.json"),
        team_name_map=MATCHES_TEAM_MAP,
    )
    return orchestrator.run(debug=debug)
