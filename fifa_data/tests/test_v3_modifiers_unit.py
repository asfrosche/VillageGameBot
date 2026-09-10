from __future__ import annotations

import json
from pathlib import Path

import pytest

from fifa_data.models.dynamic_state import ComponentScore
from fifa_data.models.player import Player
from fifa_data.models.squad import Squad
from fifa_data.services.v3_modifiers import (
    ChemistryService,
    ContinuityService,
    ExperienceService,
    FormService,
    LeadershipService,
    MomentumService,
    _normalize,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_player(
    name: str,
    country: str = "Test",
    position: str = "CM",
    attrs: dict | None = None,
    stats: dict | None = None,
) -> Player:
    return Player(
        name=name,
        country=country,
        positions=(position,),
        attributes=attrs or {},
        stats=stats,
    )


def _make_squad(players: list[Player] | None = None, formation: str = "4-3-3") -> Squad:
    xi = players or []
    return Squad(
        country="Test",
        players=list(xi),
        formation=formation,
        preferred_starting_xi=list(xi),
    )


def _cb_position() -> tuple[str, ...]:
    return ("CB",)


def _fb_position() -> tuple[str, ...]:
    return ("FB",)


def _cm_position() -> tuple[str, ...]:
    return ("CM",)


def _dm_position() -> tuple[str, ...]:
    return ("DM",)


def _st_position() -> tuple[str, ...]:
    return ("ST",)


def _winger_position() -> tuple[str, ...]:
    return ("WINGER",)


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercase_and_strip(self) -> None:
        assert _normalize("  Lionel Messi  ") == "lionel messi"

    def test_unicode_accents(self) -> None:
        assert _normalize("José") == "jose"

    def test_special_characters(self) -> None:
        # Ø is stripped entirely by the ascii encoding pass
        assert _normalize("Ronaldo-Ø") == "ronaldo"

    def test_multiple_spaces(self) -> None:
        assert _normalize("  cristiano   ronaldo  ") == "cristiano ronaldo"

    def test_already_normal(self) -> None:
        assert _normalize("kylian mbappe") == "kylian mbappe"


# ---------------------------------------------------------------------------
# ChemistryService
# ---------------------------------------------------------------------------

class TestChemistryService:
    # -- init ---------------------------------------------------------------
    def test_init_without_data_dir(self, tmp_path: Path) -> None:
        # Point to empty tmp dir so real data files aren't loaded
        svc = ChemistryService(data_dir=str(tmp_path))
        assert svc.club_links == {}
        assert svc.club_links_norm == {}
        assert svc.relationships == {}

    def test_init_with_data_dir(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "club_links.json").write_text(
            json.dumps({"Lionel Messi": "FC Barcelona"}), encoding="utf-8"
        )
        (data_dir / "player_relationships.json").write_text(
            json.dumps({"ARG": ["Messi, Di Maria"]}), encoding="utf-8"
        )
        svc = ChemistryService(data_dir=str(tmp_path))
        assert svc.club_links["lionel messi"] == "FC Barcelona"
        assert svc.club_links_norm["lionel messi"] == "Lionel Messi"
        assert svc.relationships == {"ARG": ["Messi, Di Maria"]}

    def test_init_data_dir_missing_files(self, tmp_path: Path) -> None:
        svc = ChemistryService(data_dir=str(tmp_path))
        assert svc.club_links == {}

    # -- evaluate_for_xi ---------------------------------------------------
    def test_evaluate_empty_xi(self) -> None:
        svc = ChemistryService()
        result = svc.evaluate_for_xi("BRA", [], "4-3-3")
        assert result == ComponentScore("chemistry", 0.0, "Empty squad", 1.0)

    def test_evaluate_no_club_links(self, tmp_path: Path) -> None:
        svc = ChemistryService(data_dir=str(tmp_path))
        p = _make_player("A", position="ST")
        squad = _make_squad([p])
        result = svc.evaluate_for_xi("BRA", squad.current_starting_xi, squad.formation)
        assert result.value == 0.0
        assert result.source == "No club links found"
        assert result.confidence == 0.7

    def test_evaluate_club_single_member_no_pair_bonus(self, tmp_path: Path) -> None:
        """Club with only 1 member should not trigger pair_bonus (branch 64->63)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        club_data = {"P01": "Club A", "P02": "Club B"}
        (data_dir / "club_links.json").write_text(json.dumps(club_data), encoding="utf-8")
        (data_dir / "player_relationships.json").write_text(json.dumps({}), encoding="utf-8")
        svc = ChemistryService(data_dir=str(tmp_path))
        players = [_make_player("P01"), _make_player("P02")]
        result = svc.evaluate_for_xi("BRA", players, "4-3-3")
        assert "Club pairings" not in result.source
        assert result.value == 0.0

    def test_evaluate_some_players_without_club(self, tmp_path: Path) -> None:
        """One player has a club link, another doesn't (branch coverage for
        if club: being False while other players do have clubs)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        club_data = {"Alice": "Real Madrid"}
        (data_dir / "club_links.json").write_text(json.dumps(club_data), encoding="utf-8")
        (data_dir / "player_relationships.json").write_text(json.dumps({}), encoding="utf-8")
        svc = ChemistryService(data_dir=str(tmp_path))
        players = [
            _make_player("Alice", position="ST"),
            _make_player("Bob", position="CM"),  # not in club_links
        ]
        result = svc.evaluate_for_xi("BRA", players, "4-3-3")
        # Only Alice has a club link with 1 member from Real Madrid → no pair bonus
        assert "Real Madrid" in result.source or "No club links found" in result.source

    def test_evaluate_club_pairs_generate_bonus(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        club_data = {f"P{i:02d}": "Same Club" for i in range(3)}
        (data_dir / "club_links.json").write_text(json.dumps(club_data), encoding="utf-8")
        (data_dir / "player_relationships.json").write_text(json.dumps({}), encoding="utf-8")
        svc = ChemistryService(data_dir=str(tmp_path))
        players = [
            _make_player("P00", position="CB"),
            _make_player("P01", position="FB"),
            _make_player("P02", position="CM"),
        ]
        result = svc.evaluate_for_xi("BRA", players, "4-3-3")
        assert result.value > 0.0
        assert "Club pairings" in result.source

    def test_evaluate_pair_bonus_capped_display(self, tmp_path: Path) -> None:
        """When raw pair_bonus > 0.04 the displayed source should show the
        capped value (4.00%) not the raw value."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # 6 players from same club → C(6,2)=15 pairs, each >= 0.005 → >0.04
        club_data = {f"X{i:02d}": "United" for i in range(6)}
        (data_dir / "club_links.json").write_text(json.dumps(club_data), encoding="utf-8")
        (data_dir / "player_relationships.json").write_text(json.dumps({}), encoding="utf-8")
        svc = ChemistryService(data_dir=str(tmp_path))
        players = [_make_player(f"X{i:02d}") for i in range(6)]
        result = svc.evaluate_for_xi("BRA", players, "4-3-3")
        # The pair_bonus is min(pair_bonus, 0.04), then bonus is min(bonus, 0.05)
        assert result.value <= 0.05
        # Display should say +4.00% (the capped value)
        assert "+4.00%" in result.source

    def test_evaluate_partnerships(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "club_links.json").write_text(json.dumps({}), encoding="utf-8")
        (data_dir / "player_relationships.json").write_text(
            json.dumps({"BRA": ["Alice, Bob"]}), encoding="utf-8"
        )
        svc = ChemistryService(data_dir=str(tmp_path))
        players = [
            _make_player("Alice", position="ST"),
            _make_player("Bob", position="CM"),
        ]
        result = svc.evaluate_for_xi("BRA", players, "4-3-3")
        assert "known partnerships" in result.source
        assert result.value == 0.005  # 1 hit * 0.005, capped at 0.01

    def test_evaluate_partnerships_capped(self, tmp_path: Path) -> None:
        """3 partnership hits should be capped at 0.01."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "club_links.json").write_text(json.dumps({}), encoding="utf-8")
        (data_dir / "player_relationships.json").write_text(
            json.dumps({"BRA": ["A, B", "C, D", "E, F"]}), encoding="utf-8"
        )
        svc = ChemistryService(data_dir=str(tmp_path))
        players = [
            _make_player("A", position="ST"),
            _make_player("B", position="CM"),
            _make_player("C", position="CB"),
            _make_player("D", position="FB"),
            _make_player("E", position="WINGER"),
            _make_player("F", position="DM"),
        ]
        result = svc.evaluate_for_xi("BRA", players, "4-3-3")
        # 3 hits * 0.005 = 0.015, capped at 0.01
        assert "3 known partnerships" in result.source
        assert "+1.00%" in result.source

    def test_evaluate_partnerships_pair_not_matching(self, tmp_path: Path) -> None:
        """Partnership data exists but the pair doesn't match XI (branch 82->80)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "club_links.json").write_text(json.dumps({}), encoding="utf-8")
        (data_dir / "player_relationships.json").write_text(
            json.dumps({"BRA": ["Alice, Bob"]}), encoding="utf-8"
        )
        svc = ChemistryService(data_dir=str(tmp_path))
        # Only Bob is in XI → pair doesn't match
        players = [_make_player("Bob", position="CM")]
        result = svc.evaluate_for_xi("BRA", players, "4-3-3")
        assert "known partnerships" not in result.source
        assert result.source == "No club links found"

    def test_evaluate_partnerships_no_hits(self, tmp_path: Path) -> None:
        """known_partnerships exists but partnership_hits stays 0 (branch 84->89)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "club_links.json").write_text(json.dumps({}), encoding="utf-8")
        (data_dir / "player_relationships.json").write_text(
            json.dumps({"BRA": ["X, Y"]}), encoding="utf-8"
        )
        svc = ChemistryService(data_dir=str(tmp_path))
        players = [_make_player("Bob", position="CM")]
        result = svc.evaluate_for_xi("BRA", players, "4-3-3")
        assert "known partnerships" not in result.source
        assert result.value == 0.0

    # -- get_club_groupings ------------------------------------------------
    def test_get_club_groupings(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "club_links.json").write_text(
            json.dumps({"Alice": "Club A"}), encoding="utf-8"
        )
        (data_dir / "player_relationships.json").write_text(
            json.dumps({"BRA": ["Alice, Bob"]}), encoding="utf-8"
        )
        svc = ChemistryService(data_dir=str(tmp_path))
        players = [
            _make_player("Alice", position="ST"),
            _make_player("Bob", position="CM"),
        ]
        groups = svc.get_club_groupings("BRA", players, "4-3-3")
        assert "club_groups" in groups
        assert "partnerships" in groups
        assert isinstance(groups["club_groups"], dict)

    # -- _pair_bonus -------------------------------------------------------
    @pytest.mark.parametrize(
        ("r1", "r2", "exp"),
        [
            ("CB", "FB", 0.015),
            ("FB", "CB", 0.015),
            ("FB", "WINGER", 0.010),
            ("WINGER", "FB", 0.010),
            ("CM", "DM", 0.010),
            ("DM", "CM", 0.010),
            ("ST", "WINGER", 0.008),
            ("WINGER", "ST", 0.008),
            ("GK", "CB", 0.005),
            ("ST", "GK", 0.005),
            ("ST", "CM", 0.005),  # default
        ],
    )
    def test_pair_bonus(self, r1: str, r2: str, exp: float) -> None:
        assert ChemistryService._pair_bonus(r1, r2) == exp


# ---------------------------------------------------------------------------
# ContinuityService
# ---------------------------------------------------------------------------

class TestContinuityService:
    def test_no_history(self) -> None:
        svc = ContinuityService()
        result = svc.evaluate("BRA")
        assert result == ComponentScore("continuity", 0.0, "First match of tournament", 0.7)

    def test_single_entry(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A", "B", "C"])
        result = svc.evaluate("BRA")
        assert result.source == "First match of tournament"

    def test_changes_0_identical_xi(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A", "B", "C"])
        svc.record_lineup("BRA", ["A", "B", "C"])
        result = svc.evaluate("BRA")
        assert result.value == 0.025
        assert "Identical XI" in result.source

    def test_changes_1(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A", "B", "C"])
        svc.record_lineup("BRA", ["A", "B", "D"])
        result = svc.evaluate("BRA")
        assert result.value == 0.015
        assert "1 change" in result.source

    def test_changes_2(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A", "B", "C"])
        svc.record_lineup("BRA", ["A", "D", "E"])
        result = svc.evaluate("BRA")
        assert result.value == 0.005
        assert "2 changes" in result.source

    def test_changes_3(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A", "B", "C", "D"])
        svc.record_lineup("BRA", ["A", "E", "F", "G"])
        result = svc.evaluate("BRA")
        assert result.value == -0.005
        assert "3 changes" in result.source

    def test_changes_4_or_more(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A", "B", "C", "D"])
        svc.record_lineup("BRA", ["W", "X", "Y", "Z"])
        result = svc.evaluate("BRA")
        assert result.value == -0.01
        assert "4 changes" in result.source

    def test_changes_large(self) -> None:
        """changes >= 4 (e.g. 5 changes) → -0.01."""
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A", "B", "C", "D", "E"])
        svc.record_lineup("BRA", ["V", "W", "X", "Y", "Z"])
        result = svc.evaluate("BRA")
        assert result.value == -0.01
        assert "5 changes" in result.source

    def test_total_zero_both_empty(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", [])
        svc.record_lineup("BRA", [])
        result = svc.evaluate("BRA")
        assert result.value == 0.0
        assert result.source == "No lineup data"
        assert result.confidence == 0.5

    def test_record_lineup_new_team(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A"])
        assert "BRA" in svc.lineup_history
        assert svc.lineup_history["BRA"] == [["A"]]

    def test_record_lineup_appends(self) -> None:
        svc = ContinuityService()
        svc.record_lineup("BRA", ["A"])
        svc.record_lineup("BRA", ["B"])
        assert svc.lineup_history["BRA"] == [["A"], ["B"]]

    def test_bonus_value_bounds(self) -> None:
        """Verify bonus is clamped to [-0.01, 0.03] (values already in range)."""
        svc = ContinuityService()
        # Identical XI produces 0.025, which is in bounds
        svc.record_lineup("BRA", ["A", "B", "C"])
        svc.record_lineup("BRA", ["A", "B", "C"])
        result = svc.evaluate("BRA")
        assert -0.01 <= result.value <= 0.03


# ---------------------------------------------------------------------------
# ExperienceService
# ---------------------------------------------------------------------------

def _exp_svc(tmp_path: Path, data: dict | None = None) -> ExperienceService:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    if data is not None:
        (data_dir / "player_experience.json").write_text(json.dumps(data), encoding="utf-8")
    return ExperienceService(data_dir=str(tmp_path))


class _FakeEmptyIterXi:
    """Mimics a list that is truthy but yields no items, exercising
    dead-code guards like `if player_count == 0:` that normally
    can't be reached because `not xi` catches empty lists first."""

    def __bool__(self) -> bool:
        return True

    def __iter__(self):
        return iter([])

    def __len__(self) -> int:
        return 0


class TestExperienceService:
    # -- init ---------------------------------------------------------------
    def test_init_without_data_dir(self, tmp_path: Path) -> None:
        svc = ExperienceService(data_dir=str(tmp_path))
        assert svc.exp_norm == {}

    def test_init_with_data_dir(self, tmp_path: Path) -> None:
        data = {"Messi": {"international_caps": 150, "world_cups": 1, "is_captain": True}}
        svc = _exp_svc(tmp_path, data)
        assert "messi" in svc.exp_norm

    # -- get_player_details ------------------------------------------------
    def test_get_player_details_found(self, tmp_path: Path) -> None:
        data = {"Messi": {"international_caps": 150, "world_cups": 2, "is_captain": True}}
        svc = _exp_svc(tmp_path, data)
        details = svc.get_player_details([_make_player("Messi")])
        assert details == [
            {"name": "Messi", "caps": 150, "world_cups": 2, "is_captain": True},
        ]

    def test_get_player_details_missing(self, tmp_path: Path) -> None:
        svc = _exp_svc(tmp_path, None)
        details = svc.get_player_details([_make_player("Unknown")])
        assert details == [
            {"name": "Unknown", "caps": 0, "world_cups": 0, "is_captain": False},
        ]

    def test_get_player_details_empty_xi(self, tmp_path: Path) -> None:
        svc = _exp_svc(tmp_path, None)
        assert svc.get_player_details([]) == []

    # -- evaluate ----------------------------------------------------------
    def test_evaluate_empty_xi(self, tmp_path: Path) -> None:
        svc = _exp_svc(tmp_path, None)
        squad = _make_squad([])
        result = svc.evaluate("BRA", squad)
        assert result == ComponentScore("experience", 0.0, "Empty starting XI", 1.0)

    def test_evaluate_avg_caps_ge_80(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 100}, "B": {"international_caps": 100}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A"), _make_player("B")])
        result = svc.evaluate("BRA", squad)
        assert "Avg 100 caps: +2%" in result.source
        assert result.value == pytest.approx(0.02, abs=1e-4)

    def test_evaluate_avg_caps_ge_50(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 60}, "B": {"international_caps": 60}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A"), _make_player("B")])
        result = svc.evaluate("BRA", squad)
        assert "Avg 60 caps: +1%" in result.source
        assert result.value == pytest.approx(0.01, abs=1e-4)

    def test_evaluate_avg_caps_ge_30(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 35}, "B": {"international_caps": 35}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A"), _make_player("B")])
        result = svc.evaluate("BRA", squad)
        assert "Avg 35 caps: +0.5%" in result.source
        assert result.value == pytest.approx(0.005, abs=1e-4)

    def test_evaluate_avg_caps_lt_30(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 5}, "B": {"international_caps": 5}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A"), _make_player("B")])
        result = svc.evaluate("BRA", squad)
        assert "inexperienced" in result.source
        assert result.value == pytest.approx(-0.01, abs=1e-4)

    def test_evaluate_avg_wc_ge_2(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 50, "world_cups": 2}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad)
        assert "Avg 2.0 WCs: +1%" in result.source

    def test_evaluate_avg_wc_ge_1(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 50, "world_cups": 1}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad)
        assert "Avg 1.0 WCs: +0.5%" in result.source

    def test_evaluate_avg_wc_lt_1_no_bonus(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 50, "world_cups": 0}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad)
        assert "WCs" not in result.source

    def test_evaluate_captain_count_ge_3(self, tmp_path: Path) -> None:
        data = {f"P{i}": {"international_caps": 50, "is_captain": True} for i in range(3)}
        svc = _exp_svc(tmp_path, data)
        players = [_make_player(f"P{i}") for i in range(3)]
        squad = _make_squad(players)
        result = svc.evaluate("BRA", squad)
        assert "3 leaders: +0.5%" in result.source

    def test_evaluate_captain_count_lt_3(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 50, "is_captain": True}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad)
        assert "leaders" not in result.source

    def test_evaluate_is_knockout(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 50}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad, is_knockout=True)
        assert "Knockout experience: +0.5%" in result.source

    def test_evaluate_is_extra_time(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 50}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad, is_extra_time=True)
        assert "Extra time experience: +0.5%" in result.source

    def test_evaluate_is_penalties(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 50}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad, is_penalties=True)
        assert "Penalty experience: +0.5%" in result.source

    def test_evaluate_all_context_flags(self, tmp_path: Path) -> None:
        data = {"A": {"international_caps": 100, "world_cups": 2, "is_captain": True}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad, is_knockout=True, is_extra_time=True, is_penalties=True)
        # caps >= 80 → +0.02, wc >= 2 → +0.01, captain < 3 → 0, flags → 3*0.005
        # total = 0.02 + 0.01 + 0.005 + 0.005 + 0.005 = 0.045 → clamped to 0.03
        assert result.value == 0.03

    def test_evaluate_bonus_clamped_lower(self, tmp_path: Path) -> None:
        """Low caps should give -0.01, not below -0.02."""
        data = {"A": {"international_caps": 5}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([_make_player("A")])
        result = svc.evaluate("BRA", squad)
        assert result.value >= -0.02

    def test_evaluate_player_count_zero_dead_branch(self, tmp_path: Path) -> None:
        """Cover the unreachable player_count == 0 branch by using a
        custom squad that is truthy but yields no items."""
        data = {"A": {"international_caps": 5}}
        svc = _exp_svc(tmp_path, data)
        squad = _make_squad([])
        squad.current_starting_xi = _FakeEmptyIterXi()
        result = svc.evaluate("BRA", squad)
        assert result.value == 0.0
        assert "No players in XI" in result.source


# ---------------------------------------------------------------------------
# FormService
# ---------------------------------------------------------------------------

class TestFormService:
    def test_player_count_zero_dead_branch(self) -> None:
        """Cover the unreachable player_count == 0 branch."""
        svc = FormService()
        squad = _make_squad([])
        squad.current_starting_xi = _FakeEmptyIterXi()
        result = svc.evaluate("BRA", squad)
        assert result.value == 0.0
        assert "No fantasy form data" in result.source
    def test_empty_xi(self) -> None:
        svc = FormService()
        squad = _make_squad([])
        result = svc.evaluate("BRA", squad)
        assert result == ComponentScore("form", 0.0, "Empty starting XI", 1.0)

    def test_stats_is_none(self) -> None:
        """Player with stats=None should not crash (treated as empty dict).
        form=0 / pts=0 triggers pts <=20 penalty, not 'no sources'."""
        svc = FormService()
        p = Player(
            name="A",
            country="Test",
            positions=("CM",),
            attributes={},
            stats=None,
        )
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg 0 pts (low): -1%" in result.source
        assert result.value == -0.01

    def test_stats_empty_dict(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg 0 pts (low): -1%" in result.source
        assert result.value == -0.01

    def test_avg_form_ge_4(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={"form": 5.0, "totalPoints": 100})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg form 5.0: +4%" in result.source
        assert "Avg 100 pts: +1%" in result.source

    def test_avg_form_ge_2(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={"form": 3.0, "totalPoints": 100})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg form 3.0: +2%" in result.source

    def test_avg_form_ge_0_5(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={"form": 1.0, "totalPoints": 100})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg form 1.0: +0.5%" in result.source

    def test_avg_form_le_neg_1(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={"form": -2.0, "totalPoints": 100})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg form -2.0 (poor): -3%" in result.source

    def test_avg_form_le_neg_0_5(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={"form": -0.8, "totalPoints": 100})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg form -0.8: -1%" in result.source

    def test_avg_form_mid_range(self) -> None:
        """avg_form between -0.5 and 0.5 → no form bonus/penalty."""
        svc = FormService()
        p = _make_player("A", stats={"form": 0.0, "totalPoints": 100})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "form" not in result.source.lower()
        assert "pts" in result.source

    def test_avg_pts_ge_80(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={"form": 1.0, "totalPoints": 90})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg 90 pts: +1%" in result.source

    def test_avg_pts_ge_50(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={"form": 1.0, "totalPoints": 60})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg 60 pts: +0.5%" in result.source

    def test_avg_pts_le_20(self) -> None:
        svc = FormService()
        p = _make_player("A", stats={"form": 1.0, "totalPoints": 10})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "Avg 10 pts (low): -1%" in result.source

    def test_avg_pts_mid_range_no_bonus(self) -> None:
        """avg_pts between 20 and 50 → no pts bonus/penalty."""
        svc = FormService()
        p = _make_player("A", stats={"form": 1.0, "totalPoints": 35})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert "pts" not in result.source

    def test_avg_form_and_pts_mid_no_sources(self) -> None:
        """When both form and pts fall through all branches → no sources → default."""
        svc = FormService()
        p = _make_player("A", stats={"form": 0.0, "totalPoints": 35})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert result.source == "No form data available"
        assert result.confidence == 0.3

    def test_bonus_clamped_upper(self) -> None:
        """Bonus is clamped to max 0.05."""
        svc = FormService()
        # form >= 4 gives 0.04, pts >= 80 gives 0.01 → total 0.05 (at limit)
        p = _make_player("A", stats={"form": 5.0, "totalPoints": 90})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert result.value == 0.05

    def test_bonus_clamped_lower(self) -> None:
        """Bonus is clamped to min -0.05."""
        svc = FormService()
        # form <= -1 gives -0.03, pts <= 20 gives -0.01 → total -0.04
        # still above -0.05
        p = _make_player("A", stats={"form": -2.0, "totalPoints": 10})
        squad = _make_squad([p])
        result = svc.evaluate("BRA", squad)
        assert result.value == -0.04


# ---------------------------------------------------------------------------
# LeadershipService
# ---------------------------------------------------------------------------

def _lead_svc(tmp_path: Path, data: dict | None = None) -> LeadershipService:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    if data is not None:
        (data_dir / "player_experience.json").write_text(json.dumps(data), encoding="utf-8")
    return LeadershipService(data_dir=str(tmp_path))


class TestLeadershipService:
    # -- init ---------------------------------------------------------------
    def test_init_without_data_dir(self, tmp_path: Path) -> None:
        svc = LeadershipService(data_dir=str(tmp_path))
        assert svc.exp_norm == {}

    def test_init_with_data_dir(self, tmp_path: Path) -> None:
        data = {"A": {"is_captain": True, "international_caps": 80, "world_cups": 2}}
        svc = _lead_svc(tmp_path, data)
        assert "a" in svc.exp_norm

    # -- get_leadership_details --------------------------------------------
    def test_get_leadership_details_all(self, tmp_path: Path) -> None:
        data = {
            "A": {"is_captain": True, "international_caps": 100, "world_cups": 3},
            "B": {"is_captain": False, "international_caps": 50, "world_cups": 1},
            "C": {"is_captain": True, "international_caps": 90, "world_cups": 2},
        }
        svc = _lead_svc(tmp_path, data)
        players = [_make_player("A"), _make_player("B"), _make_player("C")]
        details = svc.get_leadership_details(players)
        assert details["captain_count"] == 2
        assert details["captain_names"] == ["A", "C"]
        assert details["veteran_count"] == 2  # A(100>=80), C(90>=80)
        assert details["wc_veterans"] == 2  # A(3>=2), C(2>=2)

    def test_get_leadership_details_none(self, tmp_path: Path) -> None:
        svc = _lead_svc(tmp_path, None)
        players = [_make_player("X")]
        details = svc.get_leadership_details(players)
        assert details["captain_count"] == 0
        assert details["captain_names"] == []
        assert details["veteran_count"] == 0
        assert details["wc_veterans"] == 0

    # -- evaluate ----------------------------------------------------------
    def test_evaluate_empty_xi(self, tmp_path: Path) -> None:
        svc = _lead_svc(tmp_path, None)
        squad = _make_squad([])
        result = svc.evaluate("BRA", squad)
        assert result == ComponentScore("leadership", 0.0, "Empty starting XI", 1.0)

    def test_evaluate_captains_ge_2(self, tmp_path: Path) -> None:
        data = {f"P{i}": {"is_captain": True} for i in range(2)}
        svc = _lead_svc(tmp_path, data)
        players = [_make_player(f"P{i}") for i in range(2)]
        squad = _make_squad(players)
        result = svc.evaluate("BRA", squad)
        assert "2 captains: +1%" in result.source
        assert result.value == 0.01

    def test_evaluate_captains_eq_1(self, tmp_path: Path) -> None:
        data = {"P0": {"is_captain": True}}
        svc = _lead_svc(tmp_path, data)
        squad = _make_squad([_make_player("P0")])
        result = svc.evaluate("BRA", squad)
        assert "1 captain: +0.5%" in result.source
        assert result.value == 0.005

    def test_evaluate_captains_0_no_bonus(self, tmp_path: Path) -> None:
        data = {"P0": {"is_captain": False}}
        svc = _lead_svc(tmp_path, data)
        squad = _make_squad([_make_player("P0")])
        result = svc.evaluate("BRA", squad)
        assert "captain" not in result.source.lower()

    def test_evaluate_veterans_ge_5(self, tmp_path: Path) -> None:
        data = {f"P{i}": {"international_caps": 80} for i in range(5)}
        svc = _lead_svc(tmp_path, data)
        players = [_make_player(f"P{i}") for i in range(5)]
        squad = _make_squad(players)
        result = svc.evaluate("BRA", squad)
        assert "5 veterans: +0.5%" in result.source

    def test_evaluate_veterans_ge_3(self, tmp_path: Path) -> None:
        data = {f"P{i}": {"international_caps": 80} for i in range(3)}
        svc = _lead_svc(tmp_path, data)
        players = [_make_player(f"P{i}") for i in range(3)]
        squad = _make_squad(players)
        result = svc.evaluate("BRA", squad)
        assert "3 veterans: +0.3%" in result.source

    def test_evaluate_veterans_lt_3_no_bonus(self, tmp_path: Path) -> None:
        data = {"P0": {"international_caps": 80}}
        svc = _lead_svc(tmp_path, data)
        squad = _make_squad([_make_player("P0")])
        result = svc.evaluate("BRA", squad)
        assert "veterans" not in result.source.lower()

    def test_evaluate_wc_veterans_ge_4(self, tmp_path: Path) -> None:
        data = {f"P{i}": {"world_cups": 2} for i in range(4)}
        svc = _lead_svc(tmp_path, data)
        players = [_make_player(f"P{i}") for i in range(4)]
        squad = _make_squad(players)
        result = svc.evaluate("BRA", squad)
        assert "4 WC veterans: +0.5%" in result.source

    def test_evaluate_wc_veterans_lt_4_no_bonus(self, tmp_path: Path) -> None:
        data = {"P0": {"world_cups": 2}}
        svc = _lead_svc(tmp_path, data)
        squad = _make_squad([_make_player("P0")])
        result = svc.evaluate("BRA", squad)
        assert "WC veterans" not in result.source

    def test_evaluate_knockout(self, tmp_path: Path) -> None:
        data = {"P0": {"is_captain": True}}
        svc = _lead_svc(tmp_path, data)
        squad = _make_squad([_make_player("P0")])
        result = svc.evaluate("BRA", squad, is_knockout=True)
        assert "Knockout composure: +0.3%" in result.source

    def test_evaluate_extra_time(self, tmp_path: Path) -> None:
        data = {"P0": {"is_captain": True}}
        svc = _lead_svc(tmp_path, data)
        squad = _make_squad([_make_player("P0")])
        result = svc.evaluate("BRA", squad, is_extra_time=True)
        assert "Extra time composure: +0.2%" in result.source

    def test_evaluate_penalties(self, tmp_path: Path) -> None:
        data = {"P0": {"is_captain": True}}
        svc = _lead_svc(tmp_path, data)
        squad = _make_squad([_make_player("P0")])
        result = svc.evaluate("BRA", squad, is_penalties=True)
        assert "Penalty composure: +0.5%" in result.source

    def test_evaluate_no_sources(self, tmp_path: Path) -> None:
        svc = _lead_svc(tmp_path, None)
        squad = _make_squad([_make_player("Nobody")])
        result = svc.evaluate("BRA", squad)
        assert result.source == "No notable leadership"
        assert result.confidence == 0.6

    def test_evaluate_bonus_clamped_upper(self, tmp_path: Path) -> None:
        """Max bonus is 0.02."""
        data = {}
        for i in range(2):
            data[f"P{i}"] = {"is_captain": True, "international_caps": 80, "world_cups": 2}
        for i in range(2, 7):
            data[f"P{i}"] = {"international_caps": 80}
        svc = _lead_svc(tmp_path, data)
        players = [_make_player(f"P{i}") for i in range(7)]
        squad = _make_squad(players)
        result = svc.evaluate("BRA", squad)
        # 2 captains: 0.01, 5 veterans: 0.005, 2 wc_veterans (<4): 0 = 0.015
        assert result.value <= 0.02

    def test_evaluate_bonus_clamped_lower(self, tmp_path: Path) -> None:
        """Min bonus is 0.0 (no negative)."""
        svc = _lead_svc(tmp_path, None)
        squad = _make_squad([_make_player("Nobody")])
        result = svc.evaluate("BRA", squad)
        assert result.value >= 0.0


# ---------------------------------------------------------------------------
# MomentumService
# ---------------------------------------------------------------------------

class TestMomentumService:
    def test_no_history(self) -> None:
        svc = MomentumService()
        result = svc.evaluate("BRA")
        assert result == ComponentScore("momentum", 0.0, "No tournament history yet", 0.5)

    def test_record_result_new_team(self) -> None:
        svc = MomentumService()
        svc.record_result("BRA", 2, 1, is_real=True)
        assert "BRA" in svc.team_history
        assert svc.team_history["BRA"] == [{"gf": 2, "ga": 1, "is_real": True}]

    def test_record_result_appends(self) -> None:
        svc = MomentumService()
        svc.record_result("BRA", 2, 1, True)
        svc.record_result("BRA", 0, 0, False)
        assert len(svc.team_history["BRA"]) == 2

    def test_win_pct_ge_0_8(self) -> None:
        svc = MomentumService()
        for _ in range(4):
            svc.record_result("BRA", 2, 0, True)
        result = svc.evaluate("BRA")
        assert "4/4 wins: +2.5%" in result.source
        # 0.025 (wins) + 0.005 (GD+8) + 0.005 (4 clean sheets) = 0.035, clamped to 0.03
        assert result.value == 0.03

    def test_win_pct_ge_0_6(self) -> None:
        svc = MomentumService()
        for _ in range(3):
            svc.record_result("BRA", 2, 1, True)
        for _ in range(2):
            svc.record_result("BRA", 0, 2, True)
        result = svc.evaluate("BRA")
        assert "3/5 wins: +1.5%" in result.source
        assert result.value == pytest.approx(0.015, abs=1e-4)

    def test_win_pct_ge_0_4(self) -> None:
        svc = MomentumService()
        svc.record_result("BRA", 2, 1, True)
        svc.record_result("BRA", 2, 1, True)
        svc.record_result("BRA", 0, 2, True)
        svc.record_result("BRA", 0, 2, True)
        svc.record_result("BRA", 0, 2, True)
        result = svc.evaluate("BRA")
        # 2/5 = 0.4 win_pct
        assert "2/5 wins: +0.5%" in result.source

    def test_losses_ge_2(self) -> None:
        """win_pct < 0.4 and losses >= 2 → -2%."""
        svc = MomentumService()
        svc.record_result("BRA", 0, 1, True)
        svc.record_result("BRA", 0, 1, True)
        svc.record_result("BRA", 1, 0, True)
        result = svc.evaluate("BRA")
        # wins=1, losses=2, win_pct=0.33 (<0.4), losses=2 >= 2
        assert "2/3 losses: -2%" in result.source
        assert result.value == pytest.approx(-0.02, abs=1e-4)

    def test_losses_ge_half_single_loss(self) -> None:
        """Single match with a loss → losses=1 >= 0.5 → -1%."""
        svc = MomentumService()
        svc.record_result("BRA", 0, 1, True)
        result = svc.evaluate("BRA")
        assert "1/1 losses: -1%" in result.source
        assert result.value == pytest.approx(-0.01, abs=1e-4)

    def test_total_gd_ge_8(self) -> None:
        svc = MomentumService()
        for _ in range(4):
            svc.record_result("BRA", 3, 1, True)
        result = svc.evaluate("BRA")
        # GD=8
        assert "GD +8" in result.source or "GD +8:" in result.source
        assert result.value == 0.03  # 0.025 + 0.005

    def test_total_gd_le_neg_4(self) -> None:
        svc = MomentumService()
        svc.record_result("BRA", 0, 5, True)
        svc.record_result("BRA", 1, 0, True)  # 1 win
        result = svc.evaluate("BRA")
        # GD = -5 + 1 = -4
        assert "GD -4" in result.source or "GD -4:" in result.source

    def test_clean_sheets_ge_2(self) -> None:
        svc = MomentumService()
        svc.record_result("BRA", 1, 0, True)
        svc.record_result("BRA", 2, 0, True)
        svc.record_result("BRA", 0, 1, True)
        result = svc.evaluate("BRA")
        # 2 clean sheets
        assert "2 clean sheets" in result.source

    def test_neutral_momentum(self) -> None:
        """When no source triggers, return neutral."""
        svc = MomentumService()
        # 5 matches: 2 wins, 2 losses, 1 draw → win_pct=0.4 >= 0.4 → triggers that branch
        # Actually even simple case: 1 draw → win_pct=0, losses=0
        svc.record_result("BRA", 1, 1, True)
        result = svc.evaluate("BRA")
        assert result.source == "Neutral momentum"
        assert result.confidence == 0.6

    def test_bonus_clamped_upper(self) -> None:
        """Max bonus is 0.03."""
        svc = MomentumService()
        for _ in range(5):
            svc.record_result("BRA", 5, 0, True)  # 5 wins, GD=25, 5 clean sheets
        result = svc.evaluate("BRA")
        assert result.value == 0.03  # clamped from 0.025+0.005+0.005 = 0.035

    def test_bonus_clamped_lower(self) -> None:
        """Min bonus is -0.03."""
        svc = MomentumService()
        for _ in range(5):
            svc.record_result("BRA", 0, 4, True)
        result = svc.evaluate("BRA")
        # 5 losses → win_pct=0 (<0.4), losses=5 >=2 → -0.02, GD=-20 <= -4 → -0.01
        # total = -0.03 (at limit)
        assert result.value == -0.03


# ---------------------------------------------------------------------------
# Integration-style: all services on an XI
# ---------------------------------------------------------------------------

class TestAllServicesOnXi:
    """Make sure every service can run without crashing on a typical XI."""

    def test_all_services_happy_path(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "club_links.json").write_text(
            json.dumps({"A": "Club A", "B": "Club A"}), encoding="utf-8"
        )
        (data_dir / "player_relationships.json").write_text(json.dumps({}), encoding="utf-8")
        (data_dir / "player_experience.json").write_text(
            json.dumps({"A": {"international_caps": 80, "world_cups": 1, "is_captain": True}}),
            encoding="utf-8",
        )

        players = [
            _make_player("A", position="ST", stats={"form": 7.0, "totalPoints": 90}),
            _make_player("B", position="CM", stats={"form": 6.0, "totalPoints": 85}),
        ]
        squad = _make_squad(players)

        chem = ChemistryService(data_dir=str(tmp_path)).evaluate_for_xi("BRA", squad.current_starting_xi, "4-3-3")
        assert chem.component == "chemistry"

        cont = ContinuityService()
        cont.record_lineup("BRA", [p.name for p in squad.current_starting_xi])
        cont.record_lineup("BRA", [p.name for p in squad.current_starting_xi])
        cont_result = cont.evaluate("BRA")
        assert cont_result.component == "continuity"

        exp = ExperienceService(data_dir=str(tmp_path)).evaluate("BRA", squad)
        assert exp.component == "experience"

        form = FormService().evaluate("BRA", squad)
        assert form.component == "form"

        lead = LeadershipService(data_dir=str(tmp_path)).evaluate("BRA", squad)
        assert lead.component == "leadership"

        mom = MomentumService()
        mom.record_result("BRA", 2, 1, True)
        mom_result = mom.evaluate("BRA")
        assert mom_result.component == "momentum"
