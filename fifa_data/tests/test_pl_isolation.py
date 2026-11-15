"""Premier League / World Cup data isolation tests.

The Premier League is club football, so a PL run must never read any of the
country-keyed national-team data sources. The engines and their matchup
formulas are shared; only the *data* is scoped.
"""

from pathlib import Path
import builtins
import io
import random

import pytest

from fifa_data.competitions import get_competition
from fifa_data.services.simulation_service import run_simulation

HERE = Path(__file__).resolve().parents[1]

# Country-keyed national-team sources. None of these may be read by a PL run.
WORLD_CUP_ONLY_FILES = frozenset(
    {
        "worldcupsimulator.py",
        "known_lineups.json",
        "player_experience.json",
        "tactical_profiles.json",
        "manager_profiles.json",
        "national_strength_modifiers.json",
        "matches.json",
        "players.json",
        "squads.json",
        "tournament_form_cache.json",
    }
)


@pytest.fixture(autouse=True)
def _seeded():
    random.seed(2026)
    yield


@pytest.fixture(autouse=True)
def _restore_scope():
    """These tests flip process-global country-data scope, so put it back.

    Without this, a PL test would leave national data disabled and silently
    break the World Cup / tactical unit tests that run afterwards.
    """
    state = _country_data_state()
    yield
    _set_country_data_state(state)


def _country_data_state():
    from fifa_data.services import manager_service, tactical_analysis, v2_data_loader

    return (
        tactical_analysis._NATIONAL_DATA_ENABLED,
        dict(tactical_analysis._TACTICAL_PROFILES),
        manager_service._NATIONAL_DATA_ENABLED,
        dict(manager_service._MANAGER_PROFILES),
        v2_data_loader._KNOWN_LINEUPS_ENABLED,
        dict(v2_data_loader._KNOWN_LINEUPS),
    )


def _set_country_data_state(state):
    from fifa_data.services import manager_service, tactical_analysis, v2_data_loader

    (
        tactical_analysis._NATIONAL_DATA_ENABLED,
        tactical_profiles,
        manager_service._NATIONAL_DATA_ENABLED,
        manager_profiles,
        v2_data_loader._KNOWN_LINEUPS_ENABLED,
        known_lineups,
    ) = state

    tactical_analysis._TACTICAL_PROFILES.clear()
    tactical_analysis._TACTICAL_PROFILES.update(tactical_profiles)
    manager_service._MANAGER_PROFILES.clear()
    manager_service._MANAGER_PROFILES.update(manager_profiles)
    v2_data_loader._KNOWN_LINEUPS.clear()
    v2_data_loader._KNOWN_LINEUPS.update(known_lineups)


def _clear_country_data_caches():
    """Drop cached national data so any read shows up in the trace.

    Without this, a file cached by an earlier test is never reopened, which
    would make a leak invisible to the traced-run assertions.
    """
    from fifa_data.services import manager_service, tactical_analysis, v2_data_loader

    tactical_analysis._TACTICAL_PROFILES.clear()
    manager_service._MANAGER_PROFILES.clear()
    v2_data_loader._KNOWN_LINEUPS.clear()


def _files_opened_during(func, *args, **kwargs):
    """Run `func` and return every fifa_data file path it opens.

    Patches `io.open` (not just `builtins.open`) because `Path.open` calls
    `io.open` directly -- patching only `builtins.open` silently misses every
    `path.open()` read and would report a false "no leaks" result.
    """
    _clear_country_data_caches()
    opened: list[str] = []
    real_open = io.open

    def spy(file, *a, **kw):
        try:
            path = os_fspath(file)
        except Exception:
            path = str(file)
        if isinstance(path, bytes):
            path = path.decode()
        if isinstance(path, str):
            opened.append(path)
        return real_open(file, *a, **kw)

    io.open = spy
    builtins.open = spy
    try:
        result = func(*args, **kwargs)
    finally:
        io.open = real_open
        builtins.open = real_open

    normalized = {p.replace("\\", "/") for p in opened}
    return result, {
        p.rsplit("/", 1)[-1]
        for p in normalized
        if "/fifa_data/data/" in p or "worldcupsimulator" in p
    }


def os_fspath(file):
    import os

    return os.fspath(file)


def test_pl_run_reads_no_world_cup_data():
    """The real guard: a PL simulation must not touch national-team data."""
    result, files = _files_opened_during(run_simulation, "v3", competition="pl")

    assert result["competition"] == "Premier League 2026/2027"
    assert result["format"] == "league"

    leaked = files & WORLD_CUP_ONLY_FILES
    assert not leaked, f"Premier League run read World Cup data: {sorted(leaked)}"


def test_pl_run_reads_only_pl_data():
    """Sanity check on the positive side: PL data is actually used."""
    _, files = _files_opened_during(run_simulation, "v3", competition="pl")

    assert "pl_matches.json" in files
    assert "pl_rosters.json" in files
    assert "epl_teams.json" in files


def test_worldcup_still_reads_its_national_data():
    """The other direction: scoping must not break the World Cup.

    Uses v5 because v3 never consults tactical/manager profiles -- only the
    v4/v5 tactical and match-state layers do.
    """
    result, files = _files_opened_during(run_simulation, "v5", competition="worldcup")

    assert result["format"] == "groups_knockout"
    for expected in (
        "worldcupsimulator.py",
        "known_lineups.json",
        "player_experience.json",
        "tactical_profiles.json",
        "manager_profiles.json",
        "national_strength_modifiers.json",
    ):
        assert expected in files, f"World Cup run stopped reading {expected}"


def test_worldcup_ignores_pl_data():
    _, files = _files_opened_during(run_simulation, "v5", competition="worldcup")

    pl_only = {"pl_matches.json", "pl_rosters.json", "epl_teams.json"}
    assert not files & pl_only


@pytest.mark.parametrize("order", ["pl_first", "wc_first"])
def test_isolation_is_order_independent(order):
    """Both competitions can run in one process, in either order.

    The country-keyed profile caches are process-global, so switching scope
    must work in both directions without a stale empty cache.
    """
    if order == "pl_first":
        run_simulation("v3", competition="pl")
        run_simulation("v3", competition="worldcup")
    else:
        run_simulation("v3", competition="worldcup")
        run_simulation("v3", competition="pl")

    from fifa_data.services import manager_service, tactical_analysis

    # Re-running the World Cup after a PL run must restore national profiles.
    run_simulation("v3", competition="worldcup")
    assert tactical_analysis._tactical_profiles(), "national tactical profiles did not reload"
    assert "Arsenal" not in tactical_analysis._tactical_profiles(), (
        "club name resolved against national-team tactical profiles"
    )


def test_pl_scope_is_neutral_during_the_run_then_restored():
    """A PL run must see neutral country data, and must not leak that scope.

    The country-keyed scope is process-global state, so a sticky "club mode"
    flag would silently break any later national-team work in the same process.
    """
    from fifa_data.services import manager_service, tactical_analysis, v2_data_loader
    from fifa_data.services.simulation_service import _competition_scope
    from fifa_data.competitions import get_competition

    config = get_competition("pl", HERE)

    with _competition_scope(config):
        assert tactical_analysis._tactical_profiles() == {}
        assert manager_service.get_manager("Brazil") is None
        assert v2_data_loader._load_known_lineups() == {}

    # Scope is restored on exit, so later work is unaffected.
    assert tactical_analysis._NATIONAL_DATA_ENABLED is True
    assert manager_service._NATIONAL_DATA_ENABLED is True
    assert v2_data_loader._KNOWN_LINEUPS_ENABLED is True
    assert "Brazil" in tactical_analysis._tactical_profiles() or tactical_analysis._tactical_profiles()


def test_pl_run_does_not_leak_club_scope_to_later_work():
    """Regression: a PL simulation must not disable national data globally."""
    from fifa_data.services import tactical_analysis

    run_simulation("v3", competition="pl")
    assert tactical_analysis._NATIONAL_DATA_ENABLED is True, (
        "Premier League run left national tactical data disabled"
    )
    run_simulation("v3", competition="worldcup")
    assert tactical_analysis._NATIONAL_DATA_ENABLED is True


def test_wc_scope_is_on_during_a_wc_run():
    from fifa_data.services import tactical_analysis
    from fifa_data.services.simulation_service import _competition_scope
    from fifa_data.competitions import get_competition

    with _competition_scope(get_competition("worldcup", HERE)):
        assert tactical_analysis._tactical_profiles(), "World Cup lost its tactical profiles"


def test_pl_config_declares_national_data_off_and_owns_its_files():
    config = get_competition("pl", HERE)

    assert config.national_data is False
    # The season's own data must exist...
    for attr in ("matches_file", "rosters_file", "form_cache_file"):
        path = Path(getattr(config, attr))
        assert path.exists(), f"{attr} points at a missing file: {path}"
    # ...and no PL path may point at the World Cup's files.
    for attr in ("matches_file", "rosters_file", "form_cache_file"):
        name = Path(getattr(config, attr)).name
        assert name not in WORLD_CUP_ONLY_FILES, f"{attr} points at World Cup data: {name}"
    # The PL form cache must be namespaced, never the shared World Cup one.
    assert Path(config.form_cache_file).name != "tournament_form_cache.json"


def test_worldcup_config_keeps_national_data_on():
    assert get_competition("worldcup", HERE).national_data is True


def test_known_lineups_are_not_read_for_a_club_competition():
    """`known_lineups.json` is keyed by country, so PL must not use it."""
    from fifa_data.services.simulation_service import _competition_scope
    from fifa_data.services import v2_data_loader

    with _competition_scope(get_competition("pl", HERE)):
        assert v2_data_loader._load_known_lineups() == {}


def test_unknown_competition_raises_instead_of_defaulting_to_worldcup():
    """A typo must not silently run a national-team simulation."""
    with pytest.raises(KeyError):
        get_competition("premier-leagues", HERE)


def test_every_pl_club_resolves_through_the_name_map():
    """All 20 clubs must be resolvable as map keys, not just as values."""
    config = get_competition("pl", HERE)

    for club in config.teams:
        assert club in config.team_name_map, f"{club} cannot be resolved by team_name_map"
        assert config.team_name_map[club] == club


def test_pl_rosters_cover_every_club_and_exclude_metadata():
    import json

    config = get_competition("pl", HERE)
    with Path(config.rosters_file).open(encoding="utf-8") as handle:
        rosters = json.load(handle)

    clubs = {k: v for k, v in rosters.items() if not k.startswith("_")}
    assert len(clubs) == 20
    assert set(clubs) == set(config.teams)

    # Entries are [name, tier, rating]; no player may be a bare numeric FC26 id.
    for club, groups in clubs.items():
        for players in groups.values():
            for player in players:
                name = player[0] if isinstance(player, list) else player["name"]
                assert not str(name).strip().isdigit(), f"{club}: {name}"
                assert str(name).strip(), f"{club}: empty player name"


def test_roster_entries_are_not_merged_as_the_player_name():
    """Regression: JSON list records must be unpacked, not stringified.

    The PL roster stores players as JSON lists, and the loader only unpacked
    tuples, so every Premier League player got the whole record as their name
    and a flat 75.0 rating.
    """
    from fifa_data.services.v2_data_loader import _parse_raw_record

    name, tier, rating = _parse_raw_record(["Bernardo Silva", "STAR", 84.0])
    assert name == "Bernardo Silva"
    assert tier == "STAR"
    assert rating == 84.0

    # Tuples and bare names must keep working for the World Cup roster.
    assert _parse_raw_record(("Rodri", "SUPERSTAR", 90.0)) == ("Rodri", "SUPERSTAR", 90.0)
    assert _parse_raw_record("Solo Name") == ("Solo Name", "BASIS", 75.0)


def test_pl_players_keep_their_real_ratings_and_names():
    """A PL squad must expose usable per-player names, tiers and ratings."""
    from fifa_data.services.simulation_service import _competition_scope
    from fifa_data.services.v2_data_loader import load_v2_squads

    config = get_competition("pl", HERE)
    with _competition_scope(config):
        squads = load_v2_squads(
            data_dir=HERE,
            matches_file=config.matches_file,
            team_names=config.teams,
            rosters_file=config.rosters_file,
            players_file=config.players_file,
            squads_file=config.squads_file,
        )

    assert len(squads) == 20
    ratings = set()
    tiers = set()
    for club, squad in squads.items():
        assert squad.players, f"{club} has no players"
        for player in squad.players:
            assert isinstance(player.name, str)
            # A stringified list record keeps its brackets; a real name does not.
            assert "[" not in player.name and "]" not in player.name, (
                f"{club}: player name was not unpacked -> {player.name!r}"
            )
            assert "SUPERSTAR" not in player.name and "RESERVE" not in player.name, (
                f"{club}: player name contains its tier -> {player.name!r}"
            )
            ratings.add(player.roster_rating)
            tiers.add(player.roster_tier)

    # If the list records were not unpacked, every rating would be the 75.0
    # default and every tier "BASIS".
    assert len(ratings) > 1, "all PL players share one rating; records were not unpacked"
    assert tiers - {"BASIS"}, "no PL player kept its roster tier"


def test_same_player_is_not_listed_twice_under_two_names():
    """Regression: FPL surnames and fc26 full names must not both survive.

    Otherwise "David Raya" and "Raya" are treated as two squad members and the
    synthetic entry can win selection the real player should win.
    """
    import json

    from fifa_data.scripts.fetch_epl_data import _is_same_player

    config = get_competition("pl", HERE)
    with Path(config.rosters_file).open(encoding="utf-8") as handle:
        rosters = json.load(handle)

    duplicates = []
    for club, groups in rosters.items():
        if club.startswith("_"):
            continue
        for players in groups.values():
            names = [p[0] for p in players]
            for index, first in enumerate(names):
                for second in names[index + 1 :]:
                    if first != second and _is_same_player(first, second):
                        duplicates.append((club, first, second))

    assert not duplicates, f"same player listed twice: {duplicates[:5]}"


def test_alias_matching_keeps_genuinely_different_players():
    """The surname rule must not collapse two different people."""
    from fifa_data.scripts.fetch_epl_data import _is_same_player

    # Same person, named two ways by the two sources.
    assert _is_same_player("Raya", "David Raya")
    assert _is_same_player("Haaland", "Erling Haaland")
    assert _is_same_player("Son", "Heung-min Son")
    assert _is_same_player("Mac Allister", "Alexis Mac Allister")
    assert _is_same_player("B.Fernandes", "Bruno Fernandes")
    # Compound surnames: FPL's "David Raya Martín" is the same keeper as "David Raya".
    assert _is_same_player("David Raya Martín", "David Raya")
    # Reversed name order is the same player too (FC26 vs FPL Japanese order).
    assert _is_same_player("Ao Tanaka", "Tanaka Ao")

    # Different people must stay separate.
    assert not _is_same_player("Virgil", "Virgil van Dijk")
    assert not _is_same_player("Saka", "Rice")
    assert not _is_same_player("Rice", "Ridley")
    assert not _is_same_player("Dias", "Dion Dublin")
    assert not _is_same_player("Hall", "Hallam")
    # A shared first name never merges two Arsenal players.
    assert not _is_same_player("Gabriel", "Gabriel Martinelli Silva")
    assert not _is_same_player("Gabriel", "Gabriel dos Santos Magalhães")


def test_every_club_can_field_a_full_xi():
    """Each club needs enough players per position group to field 11."""
    import json

    config = get_competition("pl", HERE)
    with Path(config.rosters_file).open(encoding="utf-8") as handle:
        rosters = json.load(handle)

    for club in config.teams:
        groups = rosters[club]
        assert len(groups.get("GK", [])) >= 1, f"{club} has no goalkeeper"
        for group in ("DF", "MF", "AT"):
            assert len(groups.get(group, [])) >= 2, (
                f"{club} has only {len(groups.get(group, []))} {group} players"
            )
