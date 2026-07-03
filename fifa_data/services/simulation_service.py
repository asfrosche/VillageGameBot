import os
from pathlib import Path

from ..engines.v1_elo_engine import V1EloMatchEngine
from ..engines.v2_player_engine import V2PlayerMatchEngine
from ..engines.v3_dynamic_engine import V3DynamicEngine
from ..engines.v4_tactical_engine import V4TacticalEngine
from ..engines.v5_match_state_engine import V5MatchStateEngine
from ._match_config import MATCHES_TEAM_MAP, update_elo_from_matches
from .orchestrator import TournamentOrchestrator

HERE = Path(__file__).resolve().parents[1]

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
    # Update ELO/PELE from real match results for all models
    update_elo_from_matches(TEAM_METRICS)
    if normalized_model == "v1":
        engine = _v1_engine()
    elif normalized_model == "v2":
        engine = V2PlayerMatchEngine(data_dir=HERE)
    elif normalized_model == "v3":
        engine = V3DynamicEngine(data_dir=HERE, team_metrics=TEAM_METRICS)
    elif normalized_model == "v4":
        engine = V4TacticalEngine(data_dir=HERE, team_metrics=TEAM_METRICS)
    elif normalized_model == "v5":
        engine = V5MatchStateEngine(data_dir=HERE, team_metrics=TEAM_METRICS)
    else:
        raise ValueError(f"Unknown simulation model: {model}")

    orchestrator = TournamentOrchestrator(
        groups=GROUPS,
        match_engine=engine,
        matches_file=os.path.join(HERE, "data", "matches.json"),
        team_name_map=MATCHES_TEAM_MAP,
    )
    return orchestrator.run(debug=debug)


def run_monte_carlo(model="v5", n=100, verbose=True):
    """Run N full tournament simulations and aggregate results.

    Returns dict with:
      champion:   {team: count} sorted descending
      final_four: {team: count}
      quarter:    {team: count}
      r16:        {team: count}
      group_win:  {team: count}
      total:      n
      elapsed:    seconds
    """
    from collections import defaultdict
    import time

    update_elo_from_matches(TEAM_METRICS)

    champion = defaultdict(int)
    final_four = defaultdict(int)
    quarter = defaultdict(int)
    r16 = defaultdict(int)
    group_win = defaultdict(int)

    start = time.time()
    for i in range(n):
        if model in ("v3", "v4", "v5"):
            engine_cls = {"v3": V3DynamicEngine, "v4": V4TacticalEngine, "v5": V5MatchStateEngine}[model]
            engine = engine_cls(data_dir=HERE, team_metrics=TEAM_METRICS)
        elif model == "v2":
            engine = V2PlayerMatchEngine(data_dir=HERE)
        else:
            engine = _v1_engine()

        orch = TournamentOrchestrator(
            groups=GROUPS,
            match_engine=engine,
            matches_file=os.path.join(HERE, "data", "matches.json"),
            team_name_map=MATCHES_TEAM_MAP,
        )
        result = orch.run(debug=False)

        champ = result["champion"]
        if champ:
            champion[champ] += 1

        ko = result.get("knockout", [])
        if len(ko) >= 4:
            for match in ko[3]:  # SF participants
                if match:
                    final_four[match["home"]] += 1
                    final_four[match["away"]] += 1
        if len(ko) >= 3:
            for match in ko[2]:  # QF participants
                if match:
                    quarter[match["home"]] += 1
                    quarter[match["away"]] += 1
        if len(ko) >= 1:
            for match in ko[0]:  # R32 participants (all qualifiers)
                if match:
                    r16[match["home"]] += 1
                    r16[match["away"]] += 1

        for gid, gdata in result.get("groups", {}).items():
            table = gdata.get("table", [])
            if table:
                group_win[table[0][1]] += 1

        if verbose and (i + 1) % max(1, n // 20) == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            eta = (n - i - 1) / rate
            print(f"  [{i+1}/{n}] {elapsed:.0f}s elapsed, ~{eta:.0f}s remaining")

    elapsed = time.time() - start
    if verbose:
        print(f"\nCompleted {n} simulations in {elapsed:.1f}s ({n/elapsed:.1f} sims/s)")

    def _sorted(d):
        return sorted(d.items(), key=lambda x: -x[1])

    return {
        "champion": _sorted(champion),
        "final_four": _sorted(final_four),
        "quarter": _sorted(quarter),
        "r32": _sorted(r16),
        "group_win": _sorted(group_win),
        "total": n,
        "elapsed": round(elapsed, 1),
        "sims_per_sec": round(n / elapsed, 1) if elapsed else 0,
    }
