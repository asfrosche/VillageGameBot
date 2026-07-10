from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from numpy.random import poisson

from ..models.dynamic_state import DynamicState
from ..models.squad import Squad
from ..models.team_strength import (
    TeamStrength,
    build_team_strength,
    weighted_average,
)
from ..services.v2_data_loader import load_v2_squads
from ..services.v3_modifiers import (
    ChemistryService, ContinuityService, ExperienceService,
    FormService, LeadershipService, MomentumService,
)
from .base_engine import MatchEngine

HERE = Path(__file__).resolve().parents[1]


def _load_config() -> dict[str, Any]:
    path = HERE / "data" / "calibration_config.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_national_modifiers() -> dict[str, float]:
    path = HERE / "data" / "national_strength_modifiers.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


class V3DynamicEngine(MatchEngine):
    def __init__(
        self,
        data_dir: str | Path | None = None,
        squads: dict[str, Squad] | None = None,
        team_metrics: dict[str, dict[str, float]] | None = None,
        tournament_form: dict[str, float] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else None
        resolved = self.data_dir or HERE
        self.squads = squads if squads is not None else load_v2_squads(resolved)
        self.team_metrics = team_metrics or {}
        self._tournament_form = tournament_form or {}

        cfg = _load_config()
        self.base_goals = cfg.get("base_goals", 1.10)
        self.minimum_lambda = cfg.get("minimum_lambda", 0.05)
        self.attack_weight_defense = cfg.get("attack_weight_defense", 0.70)
        self.attack_weight_goalkeeper = cfg.get("attack_weight_goalkeeper", 0.30)
        self.midfield_control_weight = cfg.get("midfield_control_weight", 0.25)
        sc = cfg.get("strength_curve", {})
        self.curve_factor = sc.get("curve_factor", 3.0)
        self.curve_max = sc.get("max_multiplier", 3.0)
        self.curve_min = sc.get("min_multiplier", 0.20)
        v3_cap = cfg.get("v3_dynamic_multiplier", {})
        self.v3_min = v3_cap.get("min", 0.90)
        self.v3_max = v3_cap.get("max", 1.10)
        self.star_weights = cfg.get("star_player_weights", None)
        self.extra_time_lambda_scale = cfg.get("extra_time_lambda_scale", 0.30)
        self.tiebreaker_base_probability = cfg.get("tiebreaker_base_probability", 0.50)
        self.tiebreaker_delta_scale = cfg.get("tiebreaker_delta_scale", 0.0005)
        self.elo_dampening = cfg.get("elo_dampening", 0.40)

        self.national_modifiers = _load_national_modifiers()

        self.chemistry_service = ChemistryService(resolved)
        self.experience_service = ExperienceService(resolved)
        self.form_service = FormService()
        self.momentum_service = MomentumService()
        self.continuity_service = ContinuityService()
        self.leadership_service = LeadershipService(resolved)

        xg_deltas = self._compute_xg_deltas(resolved)
        self.form_service.set_xg_deltas(xg_deltas)

        self._match_number = 0
        self.last_match_debug = ""

    def simulate_match(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
    ) -> tuple[int, int]:
        score, _ = self.simulate_match_debug(team1, team2, can_draw)
        return score

    def simulate_match_debug(
        self,
        team1: str,
        team2: str,
        can_draw: bool = True,
    ) -> tuple[tuple[int, int], str]:
        self._match_number += 1
        is_knockout = not can_draw

        strength1 = self.get_team_strength(team1, is_knockout)
        strength2 = self.get_team_strength(team2, is_knockout)

        lambda1, lambda2 = self.expected_goals(strength1, strength2)
        g1 = poisson(max(self.minimum_lambda, lambda1))
        g2 = poisson(max(self.minimum_lambda, lambda2))

        extra_time_used = False
        penalties_used = False
        if not can_draw and g1 == g2:
            raw_diff = lambda1 - lambda2
            g1_et = poisson(lambda1 * self.extra_time_lambda_scale)
            g2_et = poisson(lambda2 * self.extra_time_lambda_scale)
            if g1_et != g2_et:
                g1 += g1_et
                g2 += g2_et
                extra_time_used = True
            else:
                leader_prob = self.tiebreaker_base_probability + (raw_diff * self.tiebreaker_delta_scale * 10)
                dyn1 = self._compute_dynamic_state(team1, is_knockout=False)
                dyn2 = self._compute_dynamic_state(team2, is_knockout=False)
                leader_prob += (dyn1.leadership.value - dyn2.leadership.value) * 0.5
                leader_prob += (dyn1.experience.value - dyn2.experience.value) * 0.3
                nat1 = self.national_modifiers.get(team1, 0.0)
                nat2 = self.national_modifiers.get(team2, 0.0)
                leader_prob += (nat1 - nat2) * 2.0
                leader_prob = max(0.05, min(0.95, leader_prob))
                if random.random() < leader_prob:
                    g1 += 1
                else:
                    g2 += 1
                penalties_used = True

        score = (int(g1), int(g2))

        squad1 = self.squads[team1]
        squad2 = self.squads[team2]
        self.continuity_service.record_lineup(team1, [p.name for p in squad1.current_starting_xi])
        self.continuity_service.record_lineup(team2, [p.name for p in squad2.current_starting_xi])

        ls1 = self._compute_dynamic_state(team1, is_knockout, extra_time_used, penalties_used)
        ls2 = self._compute_dynamic_state(team2, is_knockout, extra_time_used, penalties_used)

        self.momentum_service.record_result(team1, int(g1), int(g2), is_real=False)
        self.momentum_service.record_result(team2, int(g2), int(g1), is_real=False)

        self.last_match_debug = self.format_match_debug(
            team1, team2, strength1, strength2, ls1, ls2, (lambda1, lambda2), score,
        )
        return score, self.last_match_debug

    def get_team_strength(
        self,
        team: str,
        is_knockout: bool = False,
    ) -> TeamStrength:
        squad = self.squads[team]
        base = build_team_strength(team, squad.current_starting_xi, squad.formation)

        star_a = weighted_average(base.role_ratings, {"ST", "WINGER"}, self.star_weights)
        star_m = weighted_average(base.role_ratings, {"CM", "DM"}, self.star_weights)
        star_d = weighted_average(base.role_ratings, {"CB", "FB"}, self.star_weights)
        star_g = weighted_average(base.role_ratings, {"GK"}, self.star_weights)

        nat_mod = self.national_modifiers.get(team, 0.0)

        dyn = self._compute_dynamic_state(team, is_knockout)
        dyn_mult = max(self.v3_min, min(self.v3_max, dyn.combined_multiplier()))

        # ELO/PELE strength modifier from real match results
        metrics = self.team_metrics.get(team)
        if metrics:
            elo_avg = (metrics.get("ELO", 1500) + metrics.get("PELE", 1500)) / 2
            elo_mod = 1.0 + 0.003 * (elo_avg - 1500)
            elo_mod = max(0.50, min(elo_mod, 3.0))
        else:
            elo_mod = 1.0

        # Tournament form additive to elo (form already includes ELO/PELE base)
        form_bonus = self._tournament_form.get(team, 0.0)
        form_mod = 1.0 + form_bonus / 1500.0
        elo_mod *= form_mod
        elo_mod = max(0.50, min(elo_mod, 3.0))

        combined_mult = (1.0 + nat_mod) * dyn_mult * elo_mod

        attack_rating = round(star_a * combined_mult, 4)
        midfield_rating = round(star_m * combined_mult, 4)
        defense_rating = round(star_d * combined_mult, 4)
        goalkeeper_rating = round(star_g * combined_mult, 4)

        return TeamStrength(
            team=base.team,
            formation=base.formation,
            attack_rating=attack_rating,
            midfield_rating=midfield_rating,
            defense_rating=defense_rating,
            goalkeeper_rating=goalkeeper_rating,
            role_ratings=base.role_ratings,
            breakdown={
                **base.breakdown,
                "star_attack": star_a,
                "star_midfield": star_m,
                "star_defense": star_d,
                "star_goalkeeper": star_g,
                "national_modifier": nat_mod,
                "elo_multiplier": elo_mod,
                "v3_dynamic_multiplier": dyn_mult,
                "v3_dynamic_state": {
                    "chemistry": dyn.chemistry.value,
                    "experience": dyn.experience.value,
                    "form": dyn.form.value,
                    "momentum": dyn.momentum.value,
                    "continuity": dyn.continuity.value,
                    "leadership": dyn.leadership.value,
                },
            },
        )

    def expected_goals(
        self,
        team1_strength: TeamStrength,
        team2_strength: TeamStrength,
    ) -> tuple[float, float]:
        lambda1 = self._expected_goals_for(team1_strength, team2_strength)
        lambda2 = self._expected_goals_for(team2_strength, team1_strength)
        return round(lambda1, 6), round(lambda2, 6)

    def format_match_debug(
        self,
        team1: str,
        team2: str,
        team1_strength: TeamStrength,
        team2_strength: TeamStrength,
        dyn1: DynamicState,
        dyn2: DynamicState,
        expected_goals: tuple[float, float],
        score: tuple[int, int],
    ) -> str:
        b1 = self._base_strength(team1)
        b2 = self._base_strength(team2)
        bd1 = team1_strength.breakdown
        bd2 = team2_strength.breakdown
        nat1 = bd1.get("national_modifier", 0.0)
        nat2 = bd2.get("national_modifier", 0.0)
        sa1 = bd1.get("star_attack", 0.0)
        sa2 = bd2.get("star_attack", 0.0)
        v3m1 = bd1.get("v3_dynamic_multiplier", 1.0)
        v3m2 = bd2.get("v3_dynamic_multiplier", 1.0)

        lines = [
            f"{team1} vs {team2}",
            "",
            "Starting XI:",
        ]
        lines.extend(self._format_starting_xi_block(team1_strength, dyn1, "1"))
        lines.append("")
        lines.extend(self._format_starting_xi_block(team2_strength, dyn2, "2"))
        lines.append("")
        lines.append("Base Ratings (simple average):")
        lines.append(f"  {team1}: A={b1.attack_rating:.1f} M={b1.midfield_rating:.1f} D={b1.defense_rating:.1f} GK={b1.goalkeeper_rating:.1f}")
        lines.append(f"  {team2}: A={b2.attack_rating:.1f} M={b2.midfield_rating:.1f} D={b2.defense_rating:.1f} GK={b2.goalkeeper_rating:.1f}")
        lines.append("")
        lines.append("Star-Weighted Ratings (star player influence):")
        lines.append(f"  {team1}: A={sa1:.1f}  NatMod={nat1:+.3f}  V3Mult={v3m1:.4f}x")
        lines.append(f"  {team2}: A={sa2:.1f}  NatMod={nat2:+.3f}  V3Mult={v3m2:.4f}x")
        lines.append("")
        lines.append(f"V3 Dynamic State Modifiers ({team1}):")
        for c in dyn1.components():
            lines.append(f"  {c.component}: {c.value:+.2%}  [{c.source}]")
        lines.append(f"  Combined: {dyn1.combined_multiplier():.4f}x")
        lines.append("")
        lines.append(f"V3 Dynamic State Modifiers ({team2}):")
        for c in dyn2.components():
            lines.append(f"  {c.component}: {c.value:+.2%}  [{c.source}]")
        lines.append(f"  Combined: {dyn2.combined_multiplier():.4f}x")
        lines.append("")
        lines.append("Adjusted Ratings (star-weighted * nat_mod * v3_mult):")
        lines.append(f"  {team1}: A={team1_strength.attack_rating:.1f} M={team1_strength.midfield_rating:.1f} D={team1_strength.defense_rating:.1f} GK={team1_strength.goalkeeper_rating:.1f}")
        lines.append(f"  {team2}: A={team2_strength.attack_rating:.1f} M={team2_strength.midfield_rating:.1f} D={team2_strength.defense_rating:.1f} GK={team2_strength.goalkeeper_rating:.1f}")
        lines.append("")
        lines.append("Expected Goals (ratio + non-linear curve):")
        lines.append(f"  {team1}: {expected_goals[0]:.2f}")
        lines.append(f"  {team2}: {expected_goals[1]:.2f}")
        lines.append("")
        lines.append(f"Score: {score[0]}-{score[1]}")
        return "\n".join(lines)

    def notify_match(self, team1: str, team2: str, goals1: int, goals2: int, is_real: bool) -> None:
        self.momentum_service.record_result(team1, goals1, goals2, is_real)
        self.momentum_service.record_result(team2, goals2, goals1, is_real)
        squad1 = self.squads.get(team1)
        squad2 = self.squads.get(team2)
        if squad1:
            self.continuity_service.record_lineup(team1, [p.name for p in squad1.current_starting_xi])
        if squad2:
            self.continuity_service.record_lineup(team2, [p.name for p in squad2.current_starting_xi])

    def get_dynamic_state(
        self,
        team: str,
        is_knockout: bool = False,
        is_extra_time: bool = False,
        is_penalties: bool = False,
    ) -> DynamicState:
        return self._compute_dynamic_state(team, is_knockout, is_extra_time, is_penalties)

    def _compute_dynamic_state(
        self,
        team: str,
        is_knockout: bool = False,
        is_extra_time: bool = False,
        is_penalties: bool = False,
    ) -> DynamicState:
        squad = self.squads.get(team)
        if not squad:
            return DynamicState(team=team)
        chemistry = self.chemistry_service.evaluate_for_xi(team, squad.current_starting_xi, squad.formation)
        experience = self.experience_service.evaluate(team, squad, is_knockout, is_extra_time, is_penalties)
        form = self.form_service.evaluate(team, squad)
        momentum = self.momentum_service.evaluate(team)
        continuity = self.continuity_service.evaluate(team)
        leadership = self.leadership_service.evaluate(team, squad, is_knockout, is_extra_time, is_penalties)
        return DynamicState(
            team=team, chemistry=chemistry, experience=experience, form=form,
            momentum=momentum, continuity=continuity, leadership=leadership,
        )

    def _base_strength(self, team: str) -> TeamStrength:
        squad = self.squads[team]
        return build_team_strength(team, squad.current_starting_xi, squad.formation)

    def _compute_xg_deltas(self, data_dir: Path) -> dict[str, float]:
        matches_path = data_dir / "data" / "matches.json"
        if not matches_path.exists():
            return {}

        with matches_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        deltas: dict[str, list[float]] = {}
        star_weights = None

        for match in raw.get("completed", []):
            if match.get("status") != 0:
                continue
            t1 = match["home"]["name"]
            t2 = match["away"]["name"]
            g1 = match["home"].get("score")
            g2 = match["away"].get("score")
            if t1 not in self.squads or t2 not in self.squads:
                continue
            if g1 is None or g2 is None:
                continue

            b1 = self._base_strength(t1)
            b2 = self._base_strength(t2)
            if star_weights is None:
                from ..models.team_strength import weighted_average
                star_weights = weighted_average
            sw = star_weights
            star_a1 = sw(b1.role_ratings, {"ST", "WINGER"}, self.star_weights)
            star_m1 = sw(b1.role_ratings, {"CM", "DM"}, self.star_weights)
            star_d2 = sw(b2.role_ratings, {"CB", "FB"}, self.star_weights)
            star_g2 = sw(b2.role_ratings, {"GK"}, self.star_weights)
            star_m2 = sw(b2.role_ratings, {"CM", "DM"}, self.star_weights)
            star_a2 = sw(b2.role_ratings, {"ST", "WINGER"}, self.star_weights)
            star_d1 = sw(b1.role_ratings, {"CB", "FB"}, self.star_weights)
            star_g1 = sw(b1.role_ratings, {"GK"}, self.star_weights)

            nat1 = self.national_modifiers.get(t1, 0.0)
            nat2 = self.national_modifiers.get(t2, 0.0)

            for team_a, team_d, actual_g, s_a, s_m_a, s_d, s_gk, s_m_d, nat_a, nat_d in [
                (t1, t2, g1, star_a1, star_m1, star_d2, star_g2, star_m2, nat1, nat2),
                (t2, t1, g2, star_a2, star_m2, star_d1, star_g1, star_m1, nat2, nat1),
            ]:
                def_idx = self.attack_weight_defense * s_d + self.attack_weight_goalkeeper * s_gk
                ratio = s_a / max(def_idx, 1.0)
                curve = ratio ** self.curve_factor
                curve = max(self.curve_min, min(self.curve_max, curve))
                mid_mod = 1.0 + self.midfield_control_weight * ((s_m_a - s_m_d) / 100.0)
                xg = self.base_goals * curve * mid_mod
                xg *= (1.0 + nat_a - nat_d)
                delta = max(-2.0, min(2.0, actual_g - xg))
                deltas.setdefault(team_a, []).append(delta)

        return {team: sum(vals) / len(vals) for team, vals in deltas.items()}

    def _expected_goals_for(
        self,
        attacking: TeamStrength,
        defending: TeamStrength,
    ) -> float:
        bd_a = attacking.breakdown
        bd_d = defending.breakdown

        star_a = bd_a.get("star_attack", attacking.attack_rating)
        star_d = bd_d.get("star_defense", defending.defense_rating)
        star_gk = bd_d.get("star_goalkeeper", defending.goalkeeper_rating)
        star_m_a = bd_a.get("star_midfield", attacking.midfield_rating)
        star_m_d = bd_d.get("star_midfield", defending.midfield_rating)

        nat_mod_a = bd_a.get("national_modifier", 0.0)
        nat_mod_d = bd_d.get("national_modifier", 0.0)
        v3_mult = bd_a.get("v3_dynamic_multiplier", 1.0)
        elo_mod_a = bd_a.get("elo_multiplier", 1.0)
        elo_mod_d = bd_d.get("elo_multiplier", 1.0)

        defensive_index = (
            self.attack_weight_defense * star_d
            + self.attack_weight_goalkeeper * star_gk
        )
        attack_ratio = star_a / max(defensive_index, 1.0)
        curve_value = attack_ratio ** self.curve_factor
        curve_value = max(self.curve_min, min(self.curve_max, curve_value))

        midfield_modifier = 1.0 + self.midfield_control_weight * (
            (star_m_a - star_m_d) / 100.0
        )
        lambda_raw = self.base_goals * curve_value * midfield_modifier

        lambda_raw *= v3_mult
        lambda_raw *= (1.0 + nat_mod_a - nat_mod_d)
        if elo_mod_a != elo_mod_d and self.elo_dampening > 0:
            elo_ratio = elo_mod_a / elo_mod_d
            lambda_raw *= (1.0 + (elo_ratio - 1.0) * self.elo_dampening)

        return max(self.minimum_lambda, lambda_raw)

    def _format_starting_xi_block(
        self, strength: TeamStrength, dyn: DynamicState, side: str,
    ) -> list[str]:
        from ..models.team_strength import assign_roles
        squad = self.squads[strength.team]
        role_assignments = assign_roles(squad.current_starting_xi, squad.formation)
        by_role: dict[str, list[str]] = {"GK": [], "Defense": [], "Midfield": [], "Attack": []}
        for player, role in role_assignments:
            if role == "GK":
                by_role["GK"].append(player.name)
            elif role in {"CB", "FB"}:
                by_role["Defense"].append(player.name)
            elif role in {"CM", "DM"}:
                by_role["Midfield"].append(player.name)
            else:
                by_role["Attack"].append(player.name)
        lines = [f"Team {side}: {strength.team}  Formation: {squad.formation}"]
        for label in ("GK", "Defense", "Midfield", "Attack"):
            lines.append("")
            lines.append(f"  {label}:")
            lines.extend(f"    {name}" for name in by_role[label])
        return lines
