import os
from contextlib import contextmanager
from pathlib import Path

from ..competitions import get_competition
from ..engines.v1_elo_engine import V1EloMatchEngine
from ..engines.v2_player_engine import V2PlayerMatchEngine
from ..engines.v3_dynamic_engine import V3DynamicEngine
from ..engines.v4_tactical_engine import V4TacticalEngine
from ..engines.v5_match_state_engine import V5MatchStateEngine
from ..engines.v6_evaluation_engine import V6AdaptiveEngine
from ._match_config import MATCHES_TEAM_MAP, update_elo_from_matches
from .orchestrator import LeagueOrchestrator, TournamentOrchestrator
from .tournament_form_service import TournamentFormService

HERE = Path(__file__).resolve().parents[1]

# Module-level World Cup data kept for backwards compatibility (draft_cog,
# evaluation scripts and tests import these directly).
#
# Loaded LAZILY: importing this module must not read/exec worldcupsimulator.py,
# because a Premier League run would otherwise pull in national-team data even
# though it never uses it. The first attribute access triggers the load.
TEAM_METRICS: dict = {}
GROUPS: dict = {}
_WORLDCUP_LOADED = False


def _ensure_worldcup_data() -> None:
    global _WORLDCUP_LOADED
    if _WORLDCUP_LOADED:
        return
    from ..competitions.worldcup import load_worldcup_data

    metrics, groups = load_worldcup_data(HERE)
    TEAM_METRICS.update(metrics)
    GROUPS.update(groups)
    _WORLDCUP_LOADED = True


def _load_worldcup_data():
    _ensure_worldcup_data()
    return TEAM_METRICS, GROUPS


def __getattr__(name: str):
    # PEP 562: only resolve the legacy globals when someone actually reads them.
    if name in ("TEAM_METRICS", "GROUPS"):
        _ensure_worldcup_data()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def reset_metrics():
    global _WORLDCUP_LOADED
    TEAM_METRICS.clear()
    GROUPS.clear()
    _WORLDCUP_LOADED = False
    loaded_metrics, loaded_groups = _load_worldcup_data()
    TEAM_METRICS.update(loaded_metrics)
    GROUPS.update(loaded_groups)


def _v1_engine(tournament_form: dict[str, float] | None = None):
    return V1EloMatchEngine(TEAM_METRICS, tournament_form=tournament_form or {})


def sim_match(t1, t2, can_draw=True):
    return _v1_engine().simulate_match(t1, t2, can_draw)


def generate_goals(g1, g2):
    """Generate goal minutes for a given final score."""
    return TournamentOrchestrator._generate_goals(g1, g2)


def _build_squads(config):
    """Build per-team Squad objects for player-based engines (V2-V6).

    The competition config owns the file paths, so a club competition never
    falls through to the World Cup roster/player/squad pipeline.
    """
    from .v2_data_loader import load_v2_squads

    if config.format == "league":
        return load_v2_squads(
            data_dir=HERE,
            matches_file=config.matches_file,
            team_names=config.teams,
            rosters_file=config.rosters_file,
            players_file=config.players_file,
            squads_file=config.squads_file,
        )
    return load_v2_squads(data_dir=HERE)


@contextmanager
def _competition_scope(config):
    """Scope country-keyed data sources to this competition for one run.

    ``national_data=False`` means club football: international experience,
    national-team tactical/manager profiles and the country-keyed known-lineup
    cache are all switched off, leaving neutral defaults. The World Cup leaves
    it on, so its behaviour is unchanged.

    The previous scope is restored on exit, so running the Premier League cannot
    leave national data disabled for whatever runs next in the same process.
    """
    from . import manager_service, tactical_analysis
    from .v2_data_loader import known_lineups_scope

    national = config.national_data
    with (
        known_lineups_scope(national),
        tactical_analysis.national_data_scope(national),
        manager_service.national_data_scope(national),
    ):
        yield


def _competition_engine(model: str, config, tournament_form: dict[str, float] | None = None):
    """Build a match engine for the given model + competition config."""
    normalized_model = (model or "v1").lower()
    metrics = config.team_metrics
    tournament_form = tournament_form or {}
    if normalized_model == "v1":
        return V1EloMatchEngine(metrics, tournament_form=tournament_form)

    squads = _build_squads(config)
    scope = {
        "national_data": config.national_data,
        "matches_file": config.matches_file,
    }
    if normalized_model == "v2":
        return V2PlayerMatchEngine(data_dir=HERE, squads=squads, tournament_form=tournament_form)
    if normalized_model == "v3":
        return V3DynamicEngine(data_dir=HERE, squads=squads, team_metrics=metrics, tournament_form=tournament_form, **scope)
    if normalized_model == "v4":
        return V4TacticalEngine(data_dir=HERE, squads=squads, team_metrics=metrics, tournament_form=tournament_form, **scope)
    if normalized_model == "v5":
        return V5MatchStateEngine(data_dir=HERE, squads=squads, team_metrics=metrics, tournament_form=tournament_form, **scope)
    if normalized_model == "v6":
        return V6AdaptiveEngine(data_dir=HERE, squads=squads, team_metrics=metrics, tournament_form=tournament_form, **scope)
    raise ValueError(f"Unknown simulation model: {model}")


def _make_orchestrator(config, engine):
    if config.format == "league":
        return LeagueOrchestrator(
            teams=config.teams,
            match_engine=engine,
            matches_file=config.matches_file,
            team_name_map=config.team_name_map,
            home_elo_bonus=config.home_elo_bonus,
        )
    return TournamentOrchestrator(
        groups=config.groups,
        match_engine=engine,
        matches_file=config.matches_file,
        team_name_map=config.team_name_map,
    )


def run_simulation(model="v1", debug=False, competition="worldcup"):
    """Run the full simulation and return structured data.

    `competition` accepts registry names/aliases: "worldcup"/"wc"/"fifa" for
    the World Cup and "premier-league"/"pl"/"epl"/"premier" for the league.
    """
    normalized_model = (model or "v1").lower()
    config = get_competition(competition, HERE)
    metrics = config.team_metrics
    # Club competitions must not read country-keyed (World Cup) data sources.
    with _competition_scope(config):
        # Update ELO/PELE from real match results for all models
        update_elo_from_matches(metrics, config.matches_file, config.team_name_map)
        # Compute Tournament Form once (per-competition cache, never shared)
        tfs = TournamentFormService(
            metrics,
            matches_file=config.matches_file,
            team_name_map=config.team_name_map,
            cache_file=config.form_cache_file,
        )
        tfs.compute()
        tournament_form = tfs.get_all_forms()

        engine = _competition_engine(normalized_model, config, tournament_form)
        orchestrator = _make_orchestrator(config, engine)
        result = orchestrator.run(debug=debug)
    result["competition"] = config.competition_label
    result["format"] = config.format
    return result


def simulate_stage(model="v1", stage="Group Stage", competition="worldcup", debug=False):
    """Run one competition's stage loop up to (and including) a named stage.

    The logical loop is shared, but each competition owns its own stage list:
    the World Cup runs "Group Stage" -> ... -> "Final"/"Third-Place Play-off",
    while the Premier League runs "Premier League Season" -> "Standings
    Resolution". Stopping early returns a partial result flagged ``is_partial``
    so callers can inspect a competition at any checkpoint.

    Exactly matches ``run_simulation`` for ``stage`` set to the final stage.
    """
    normalized_model = (model or "v1").lower()
    config = get_competition(competition, HERE)
    if stage not in config.stage_names:
        raise ValueError(
            f"Unknown stage {stage!r} for {config.competition_label}; "
            f"expected one of {config.stage_names}"
        )
    with _competition_scope(config):
        update_elo_from_matches(config.team_metrics, config.matches_file, config.team_name_map)
        tfs = TournamentFormService(
            config.team_metrics,
            matches_file=config.matches_file,
            team_name_map=config.team_name_map,
            cache_file=config.form_cache_file,
        )
        tfs.compute()
        engine = _competition_engine(normalized_model, config, tfs.get_all_forms())
        orchestrator = _make_orchestrator(config, engine)
        result = orchestrator.run_through(stage, debug=debug)
    result["competition"] = config.competition_label
    result["format"] = config.format
    return result


def run_monte_carlo(model="v5", n=100, verbose=True, competition="worldcup"):
    """Run N full simulations and aggregate results.

    For league competitions the aggregation keys differ: ``champion`` is the
    title count, and per-position standings are tallied.
    """
    from collections import defaultdict
    import time

    config = get_competition(competition, HERE)
    metrics = config.team_metrics
    update_elo_from_matches(metrics, config.matches_file, config.team_name_map)

    tfs = TournamentFormService(metrics, matches_file=config.matches_file, team_name_map=config.team_name_map)
    tfs.compute()
    tournament_form = tfs.get_all_forms()

    champion = defaultdict(int)
    positions = defaultdict(lambda: defaultdict(int))
    medal_counts = defaultdict(int)
    relegation_counts = defaultdict(int)

    start = time.time()
    for i in range(n):
        engine = _competition_engine(model, config, tournament_form)
        orch = _make_orchestrator(config, engine)
        result = orch.run(debug=False)

        if config.format == "league":
            champion[result["champion"]] += 1
            for position, (team, _row) in enumerate(result["table"], start=1):
                positions[position][team] += 1
            for team in result["top4"]:
                medal_counts[team] += 1
            for team in result["relegated"]:
                relegation_counts[team] += 1
        else:
            champ = result["champion"]
            if champ:
                champion[champ] += 1

            ko = result.get("knockout", [])
            if len(ko) >= 4:
                for match in ko[3]:  # SF participants
                    if match:
                        medal_counts[match["home"]] += 1
                        medal_counts[match["away"]] += 1
            if len(ko) >= 3:
                for match in ko[2]:  # QF participants
                    if match:
                        positions[3][match["home"]] += 1
                        positions[3][match["away"]] += 1
            if len(ko) >= 1:
                for match in ko[0]:
                    if match:
                        positions[1][match["home"]] += 1
                        positions[1][match["away"]] += 1
            for gid, gdata in result.get("groups", {}).items():
                table = gdata.get("table", [])
                if table:
                    positions[0][table[0][1]] += 1

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

    result = {
        "champion": _sorted(champion),
        "medal_contenders": _sorted(medal_counts),
        "relegation_zone": _sorted(relegation_counts),
        "positions": {position: _sorted(counts) for position, counts in sorted(positions.items())},
        "format": config.format,
        "competition": config.competition_label,
        "total": n,
        "elapsed": round(elapsed, 1),
        "sims_per_sec": round(n / elapsed, 1) if elapsed else 0,
    }

    if config.format != "league":
        result["final_four"] = _sorted(medal_counts)
        result["group_win"] = _sorted(positions.get(0, {}))
    return result