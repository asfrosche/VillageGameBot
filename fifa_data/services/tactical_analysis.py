from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models.player import Player
from ..models.squad import Squad
from ..models.team_strength import role_for_player, DEFAULT_POSITION_FORMULAS
from ..models.tactical_state import (
    DEFENSIVE_STYLES,
    TacticalAdjustment,
    TacticalReport,
    GAME_PLANS,
    FormationProfile,
)
from ..models.tactical_vulnerability import (
    TacticalStrength,
    TeamWeakness,
    TacticalVulnerabilityReport,
    ExploitationOpportunity,
    ExploitationReport,
    MatchArchetypeData,
    MatchArchetypeReport,
    WinCondition,
    WinConditionReport,
)
from ..models.player_influence import (
    OffensiveInfluence,
    DefensiveInfluence,
    GoalkeeperInfluence,
    TeamDependency,
    PlayerMatchup,
    PlayerInfluenceReport,
)
from .formation_service import formation_matchup_advantages

HERE = Path(__file__).resolve().parents[1]


def _load_tactical_profiles() -> dict[str, dict[str, Any]]:
    path = HERE / "data" / "tactical_profiles.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


_TACTICAL_PROFILES = _load_tactical_profiles()

# ── Shared helpers ──────────────────────────────────────────────────────────

def _get_squad_avg(squad: Squad | None, attr: str) -> float:
    if not squad or not squad.current_starting_xi:
        return 50.0
    vals = [p.attributes.get(attr, 50.0) for p in squad.current_starting_xi]
    return sum(vals) / len(vals)


def _get_squad_max(squad: Squad | None, attr: str) -> float:
    if not squad or not squad.current_starting_xi:
        return 50.0
    return max(p.attributes.get(attr, 50.0) for p in squad.current_starting_xi)


def _get_squad_max_avg(squad: Squad | None, attr: str, top_n: int = 3) -> float:
    if not squad or not squad.current_starting_xi:
        return 50.0
    vals = sorted((p.attributes.get(attr, 50.0) for p in squad.current_starting_xi), reverse=True)
    return sum(vals[:top_n]) / len(vals[:top_n])


def _get_attackers_avg(squad: Squad | None, attr: str) -> float:
    if not squad or not squad.current_starting_xi:
        return 50.0
    attackers = [p for p in squad.current_starting_xi if role_for_player(p, squad.formation) in {"ST", "WINGER"}]
    if not attackers:
        return 50.0
    vals = [p.attributes.get(attr, 50.0) for p in attackers]
    return sum(vals) / len(vals)


def _get_defenders_avg(squad: Squad | None, attr: str) -> float:
    if not squad or not squad.current_starting_xi:
        return 50.0
    defenders = [p for p in squad.current_starting_xi if role_for_player(p, squad.formation) in {"CB", "FB"}]
    if not defenders:
        return 50.0
    vals = [p.attributes.get(attr, 50.0) for p in defenders]
    return sum(vals) / len(vals)


def _get_squad_defensive_rating(squad: Squad | None) -> float:
    if not squad or not squad.current_starting_xi:
        return 50.0
    vals = [p.attributes.get("defending", 50.0) for p in squad.current_starting_xi]
    return sum(vals) / len(vals)


def _get_squad_composure_avg(squad: Squad | None) -> float:
    if not squad or not squad.current_starting_xi:
        return 50.0
    vals = [p.attributes.get("composure", 50.0) for p in squad.current_starting_xi]
    return sum(vals) / len(vals)


def _attr(p: Player | None, key: str, default: float = 50.0) -> float:
    if p is None:
        return default
    return p.attributes.get(key, default)


# ── Tactical Matchup ───────────────────────────────────────────────────────

def choose_game_plan(
    team: str,
    opponent: str,
    relative_strength: float,
    context: str = "group",
) -> str:
    prof = _TACTICAL_PROFILES.get(team, {})
    opp_prof = _TACTICAL_PROFILES.get(opponent, {})

    if context == "knockout":
        if relative_strength > 1.10:
            return "balanced"
        if relative_strength < 0.80:
            return "low_block"
        return "balanced"
    if context == "must_win":
        if relative_strength > 0.95:
            return "attacking"
        if relative_strength < 0.75:
            return "high_press"
        return "attacking"
    if context == "need_draw":
        if relative_strength < 0.90:
            return "low_block"
        return "balanced"
    if context == "gd_chase":
        return "high_press" if prof.get("pressing", 50) > 60 else "attacking"

    if relative_strength > 1.15:
        return "attacking"
    if relative_strength < 0.85:
        if opp_prof.get("counter_attack", 50) > 70:
            return "low_block"
        return "counter"
    return "balanced"


MAX_XG_ADJUSTMENT_PCT = 0.10


def compute_tactical_matchup(
    team_a: str,
    team_b: str,
    base_xg_a: float,
    base_xg_b: float,
    squad_a: Squad | None = None,
    squad_b: Squad | None = None,
    context: str = "group",
) -> TacticalReport:
    prof_a = _TACTICAL_PROFILES.get(team_a, {})
    prof_b = _TACTICAL_PROFILES.get(team_b, {})

    relative_a_vs_b = base_xg_a / max(base_xg_b, 0.01)
    relative_b_vs_a = base_xg_b / max(base_xg_a, 0.01)

    plan_a = choose_game_plan(team_a, team_b, relative_a_vs_b, context)
    plan_b = choose_game_plan(team_b, team_a, relative_b_vs_a, context)

    adjustments_a: list[TacticalAdjustment] = []
    adjustments_b: list[TacticalAdjustment] = []
    advantages_a: list[str] = []
    advantages_b: list[str] = []

    _high_line_vs_pace(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _pressing_vs_buildup(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _possession_vs_low_block(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _set_pieces(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _aerial_battles(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _formation_matchup(team_a, team_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _game_plan_effects(plan_a, plan_b, prof_a, prof_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _player_tactic_compatibility(team_a, team_b, squad_a, squad_b, prof_a, prof_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _possession_quality(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _defensive_style_interaction(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _tactical_flexibility_effects(team_a, team_b, prof_a, prof_b, plan_a, plan_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _match_context_effects(team_a, team_b, context, plan_a, plan_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _defensive_stalemate(team_a, team_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)

    max_adj_a = max(base_xg_a * MAX_XG_ADJUSTMENT_PCT, 0.05)
    max_adj_b = max(base_xg_b * MAX_XG_ADJUSTMENT_PCT, 0.05)

    total_adj_a = sum(adj.value for adj in adjustments_a)
    total_adj_b = sum(adj.value for adj in adjustments_b)

    clamped_adj_a = max(-max_adj_a, min(max_adj_a, total_adj_a))
    clamped_adj_b = max(-max_adj_b, min(max_adj_b, total_adj_b))

    if abs(clamped_adj_a - total_adj_a) > 0.001:
        diff = round(clamped_adj_a - total_adj_a, 4)
        adjustments_a.append(TacticalAdjustment("clamp", f"Adjustment capped at ±{MAX_XG_ADJUSTMENT_PCT*100:.0f}% of base xG ({diff:+.4f} xG)", diff))
        if diff > 0:
            advantages_a.append(f"Tactical cap relief: adjustments capped ({diff:+.2f} xG)")
        else:
            advantages_b.append(f"Opponent tactical adjustments capped ({diff:+.2f} xG)")

    if abs(clamped_adj_b - total_adj_b) > 0.001:
        diff = round(clamped_adj_b - total_adj_b, 4)
        adjustments_b.append(TacticalAdjustment("clamp", f"Adjustment capped at ±{MAX_XG_ADJUSTMENT_PCT*100:.0f}% of base xG ({diff:+.4f} xG)", diff))
        if diff > 0:
            advantages_b.append(f"Tactical cap relief: adjustments capped ({diff:+.2f} xG)")
        else:
            advantages_a.append(f"Opponent tactical adjustments capped ({diff:+.2f} xG)")

    total_adj_a = clamped_adj_a
    total_adj_b = clamped_adj_b

    final_xg_a = max(0.01, base_xg_a + total_adj_a)
    final_xg_b = max(0.01, base_xg_b + total_adj_b)

    return TacticalReport(
        team_a=team_a,
        team_b=team_b,
        base_xg_a=base_xg_a,
        base_xg_b=base_xg_b,
        adjustments_a=adjustments_a,
        adjustments_b=adjustments_b,
        final_xg_a=round(final_xg_a, 6),
        final_xg_b=round(final_xg_b, 6),
        game_plan_a=plan_a,
        game_plan_b=plan_b,
        advantages_a=advantages_a,
        advantages_b=advantages_b,
        context=context,
    )


def _high_line_vs_pace(
    team_a: str, team_b: str,
    prof_a: dict, prof_b: dict,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    high_line = prof_a.get("defensive_line", 50)
    if high_line >= 65:
        pace_b = _get_attackers_avg(squad_b, "pace") if squad_b else 50
        drib_b = _get_attackers_avg(squad_b, "dribbling") if squad_b else 50
        pace_factor = max(0, (pace_b + drib_b) / 2 - 50) / 50.0
        boost = round(0.12 * pace_factor, 4)
        if boost > 0.01:
            adj_b.append(TacticalAdjustment("high_line_exploit", f"High line exploited by pace ({pace_b:.0f}/100)", boost))
            adv_b.append(f"High defensive line exploited by pace (+{boost:.2f} xG)")
    high_line_b = prof_b.get("defensive_line", 50)
    if high_line_b >= 65:
        pace_a = _get_attackers_avg(squad_a, "pace") if squad_a else 50
        drib_a = _get_attackers_avg(squad_a, "dribbling") if squad_a else 50
        pace_factor = max(0, (pace_a + drib_a) / 2 - 50) / 50.0
        boost = round(0.12 * pace_factor, 4)
        if boost > 0.01:
            adj_a.append(TacticalAdjustment("high_line_exploit", f"High line exploited by pace ({pace_a:.0f}/100)", boost))
            adv_a.append(f"High defensive line exploited by pace (+{boost:.2f} xG)")


def _pressing_vs_buildup(
    team_a: str, team_b: str,
    prof_a: dict, prof_b: dict,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    press_a = prof_a.get("pressing", 50)
    build_b = prof_b.get("build_up", 50)
    if press_a > 65 and build_b < 60:
        comp_b = _get_squad_avg(squad_b, "composure") if squad_b else 50
        pass_b = _get_squad_avg(squad_b, "passing") if squad_b else 50
        press_gap = (press_a - build_b) / 100.0
        quality_factor = max(0, 1.0 - (comp_b + pass_b) / 200.0)
        boost = round(0.10 * press_gap * quality_factor, 4)
        if boost > 0.01:
            adj_a.append(TacticalAdjustment("pressing", f"Press vs weak build-up (press {press_a:.0f}/100 vs build {build_b:.0f}/100)", boost))
            adv_a.append(f"Aggressive pressing exploits weak buildup (+{boost:.2f} xG)")

    press_b = prof_b.get("pressing", 50)
    build_a = prof_a.get("build_up", 50)
    if press_b > 65 and build_a < 60:
        comp_a = _get_squad_avg(squad_a, "composure") if squad_a else 50
        pass_a = _get_squad_avg(squad_a, "passing") if squad_a else 50
        press_gap = (press_b - build_a) / 100.0
        quality_factor = max(0, 1.0 - (comp_a + pass_a) / 200.0)
        boost = round(0.10 * press_gap * quality_factor, 4)
        if boost > 0.01:
            adj_b.append(TacticalAdjustment("pressing", f"Press vs weak build-up (press {press_b:.0f}/100 vs build {build_a:.0f}/100)", boost))
            adv_b.append(f"Aggressive pressing exploits weak buildup (+{boost:.2f} xG)")


def _possession_vs_low_block(
    team_a: str, team_b: str,
    prof_a: dict, prof_b: dict,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    possession_a = prof_a.get("possession", 50)
    compact_b = prof_b.get("defensive_compactness", 50)
    if possession_a > 70 and compact_b > 70:
        vision_a = _get_squad_avg(squad_a, "vision") if squad_a else 50
        drib_a = _get_squad_avg(squad_a, "dribbling") if squad_a else 50
        crossing_a = _get_squad_avg(squad_a, "crossing") if squad_a else 50
        long_shots_a = _get_squad_avg(squad_a, "long_shots") if squad_a else 50
        creativity = (vision_a + drib_a + crossing_a + long_shots_a) / 4.0
        creativity_factor = max(0, (creativity - 50) / 50.0)
        boost = round(0.08 * creativity_factor, 4)
        if boost > 0.01:
            adj_a.append(TacticalAdjustment("possession_creativity", f"Possession vs low block (creativity {creativity:.0f}/100)", boost))
            adv_a.append(f"Possession control with creative threat (+{boost:.2f} xG)")

    possession_b = prof_b.get("possession", 50)
    compact_a = prof_a.get("defensive_compactness", 50)
    if possession_b > 70 and compact_a > 70:
        vision_b = _get_squad_avg(squad_b, "vision") if squad_b else 50
        drib_b = _get_squad_avg(squad_b, "dribbling") if squad_b else 50
        crossing_b = _get_squad_avg(squad_b, "crossing") if squad_b else 50
        long_shots_b = _get_squad_avg(squad_b, "long_shots") if squad_b else 50
        creativity = (vision_b + drib_b + crossing_b + long_shots_b) / 4.0
        creativity_factor = max(0, (creativity - 50) / 50.0)
        boost = round(0.08 * creativity_factor, 4)
        if boost > 0.01:
            adj_b.append(TacticalAdjustment("possession_creativity", f"Possession vs low block (creativity {creativity:.0f}/100)", boost))
            adv_b.append(f"Possession control with creative threat (+{boost:.2f} xG)")


def _set_pieces(
    team_a: str, team_b: str,
    prof_a: dict, prof_b: dict,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    sp_attack_a = prof_a.get("set_piece_attack", 50)
    sp_defense_b = prof_b.get("set_piece_defense", 50)
    if sp_attack_a > 60 and sp_defense_b < 60:
        heading_a = _get_squad_max_avg(squad_a, "heading_accuracy") if squad_a else 50
        strength_a = _get_squad_max_avg(squad_a, "strength") if squad_a else 50
        crossing_a = _get_squad_avg(squad_a, "crossing") if squad_a else 50
        sp_quality = (heading_a + strength_a + crossing_a) / 3.0
        gap = (sp_attack_a - sp_defense_b) / 100.0
        boost = round(0.10 * gap * max(0, (sp_quality - 50) / 50.0), 4)
        if boost > 0.005:
            adj_a.append(TacticalAdjustment("set_pieces", f"Set-piece mismatch (attack {sp_attack_a:.0f}/100 vs defense {sp_defense_b:.0f}/100)", boost))
            adv_a.append(f"Set-piece advantage (+{boost:.2f} xG)")

    sp_attack_b = prof_b.get("set_piece_attack", 50)
    sp_defense_a = prof_a.get("set_piece_defense", 50)
    if sp_attack_b > 60 and sp_defense_a < 60:
        heading_b = _get_squad_max_avg(squad_b, "heading_accuracy") if squad_b else 50
        strength_b = _get_squad_max_avg(squad_b, "strength") if squad_b else 50
        crossing_b = _get_squad_avg(squad_b, "crossing") if squad_b else 50
        sp_quality = (heading_b + strength_b + crossing_b) / 3.0
        gap = (sp_attack_b - sp_defense_a) / 100.0
        boost = round(0.10 * gap * max(0, (sp_quality - 50) / 50.0), 4)
        if boost > 0.005:
            adj_b.append(TacticalAdjustment("set_pieces", f"Set-piece mismatch (attack {sp_attack_b:.0f}/100 vs defense {sp_defense_a:.0f}/100)", boost))
            adv_b.append(f"Set-piece advantage (+{boost:.2f} xG)")


def _aerial_battles(
    team_a: str, team_b: str,
    prof_a: dict, prof_b: dict,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    aerial_a = prof_a.get("aerial_strength", 50)
    aerial_b = prof_b.get("aerial_strength", 50)
    gap = aerial_a - aerial_b
    if gap > 10:
        jump_a = _get_squad_max_avg(squad_a, "jumping") if squad_a else 50
        heading_a = _get_squad_max_avg(squad_a, "heading_accuracy") if squad_a else 50
        strength_a = _get_squad_max_avg(squad_a, "strength") if squad_a else 50
        aerial_quality = (jump_a + heading_a + strength_a) / 3.0
        boost = round(0.04 * (gap / 50.0) * max(0, (aerial_quality - 50) / 50.0), 4)
        if boost > 0.01:
            adj_a.append(TacticalAdjustment("aerial", f"Aerial dominance (aerial {aerial_a:.0f}/100 vs {aerial_b:.0f}/100)", boost))
            adv_a.append(f"Aerial advantage (+{boost:.2f} xG)")
    elif gap < -10:
        jump_b = _get_squad_max_avg(squad_b, "jumping") if squad_b else 50
        heading_b = _get_squad_max_avg(squad_b, "heading_accuracy") if squad_b else 50
        strength_b = _get_squad_max_avg(squad_b, "strength") if squad_b else 50
        aerial_quality = (jump_b + heading_b + strength_b) / 3.0
        boost = round(0.04 * (abs(gap) / 50.0) * max(0, (aerial_quality - 50) / 50.0), 4)
        if boost > 0.01:
            adj_b.append(TacticalAdjustment("aerial", f"Aerial dominance (aerial {aerial_b:.0f}/100 vs {aerial_a:.0f}/100)", boost))
            adv_b.append(f"Aerial advantage (+{boost:.2f} xG)")


def _formation_matchup(
    team_a: str, team_b: str,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    if not squad_a or not squad_b:
        return
    f_adv_a, f_adv_b = formation_matchup_advantages(squad_a.formation, squad_b.formation)
    adv_a.extend(f_adv_a)
    adv_b.extend(f_adv_b)


def _game_plan_effects(
    plan_a: str, plan_b: str,
    prof_a: dict, prof_b: dict,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    if plan_a == "attacking":
        adj_a.append(TacticalAdjustment("game_plan", "Attacking game plan: more risk, more chances", 0.03))
        adj_a.append(TacticalAdjustment("game_plan_risk", "Attacking game plan: defensive vulnerability", -0.02))
        adv_a.append("Attacking game plan (+0.03 xG, -0.02 defensive)")

    if plan_a == "counter":
        adj_a.append(TacticalAdjustment("game_plan", "Counter game plan: faster transitions", 0.02))
        adj_a.append(TacticalAdjustment("game_plan_possession", "Counter game plan: reduced possession control", -0.02))
        adv_a.append("Counter game plan: transition threat (+0.02 xG)")

    if plan_a == "low_block":
        adj_a.append(TacticalAdjustment("game_plan", "Low block: fewer chances conceded", -0.03))
        adj_a.append(TacticalAdjustment("game_plan_attack", "Low block: reduced attacking threat", -0.02))
        adv_a.append("Low block: defensive solidity (-0.03 xG conceded, -0.02 xG created)")

    if plan_a == "high_press":
        adj_a.append(TacticalAdjustment("game_plan", "High press: ball recovery in dangerous areas", 0.03))
        adj_a.append(TacticalAdjustment("game_plan_risk", "High press: defensive structure risk", -0.02))
        adv_a.append("High press: dangerous recoveries (+0.03 xG, -0.02 defensive)")

    if plan_b == "attacking":
        adj_b.append(TacticalAdjustment("game_plan", "Attacking game plan: more risk, more chances", 0.03))
        adj_b.append(TacticalAdjustment("game_plan_risk", "Attacking game plan: defensive vulnerability", -0.02))
        adv_b.append("Attacking game plan (+0.03 xG, -0.02 defensive)")

    if plan_b == "counter":
        adj_b.append(TacticalAdjustment("game_plan", "Counter game plan: faster transitions", 0.02))
        adj_b.append(TacticalAdjustment("game_plan_possession", "Counter game plan: reduced possession control", -0.02))
        adv_b.append("Counter game plan: transition threat (+0.02 xG)")

    if plan_b == "low_block":
        adj_b.append(TacticalAdjustment("game_plan", "Low block: fewer chances conceded", -0.03))
        adj_b.append(TacticalAdjustment("game_plan_attack", "Low block: reduced attacking threat", -0.02))
        adv_b.append("Low block: defensive solidity (-0.03 xG conceded, -0.02 xG created)")

    if plan_b == "high_press":
        adj_b.append(TacticalAdjustment("game_plan", "High press: ball recovery in dangerous areas", 0.03))
        adj_b.append(TacticalAdjustment("game_plan_risk", "High press: defensive structure risk", -0.02))
        adv_b.append("High press: dangerous recoveries (+0.03 xG, -0.02 defensive)")


def _player_tactic_compatibility(
    team_a: str, team_b: str,
    squad_a: Squad | None, squad_b: Squad | None,
    prof_a: dict, prof_b: dict,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    if not squad_a or not squad_b:
        return
    press_a = prof_a.get("pressing", 50)
    if press_a > 65:
        stamina_b = _get_squad_avg(squad_b, "stamina") if squad_b else 50
        composure_b = _get_squad_avg(squad_b, "composure") if squad_b else 50
        if stamina_b < 65 or composure_b < 65:
            penalty = round(-0.02 * (1.0 - min(stamina_b, composure_b) / 65.0), 4)
            if penalty < -0.005:
                adj_b.append(TacticalAdjustment("press_vulnerability", f"Low press resistance (stamina {stamina_b:.0f}/100, composure {composure_b:.0f}/100)", penalty))
                adv_a.append(f"Opponent vulnerable to pressing (-{abs(penalty):.2f} xG for opponent)")

    press_b = prof_b.get("pressing", 50)
    if press_b > 65:
        stamina_a = _get_squad_avg(squad_a, "stamina") if squad_a else 50
        composure_a = _get_squad_avg(squad_a, "composure") if squad_a else 50
        if stamina_a < 65 or composure_a < 65:
            penalty = round(-0.02 * (1.0 - min(stamina_a, composure_a) / 65.0), 4)
            if penalty < -0.005:
                adj_a.append(TacticalAdjustment("press_vulnerability", f"Low press resistance (stamina {stamina_a:.0f}/100, composure {composure_a:.0f}/100)", penalty))
                adv_b.append(f"Opponent vulnerable to pressing (-{abs(penalty):.2f} xG for opponent)")


def _possession_quality(
    team_a: str, team_b: str,
    prof_a: dict, prof_b: dict,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    pp_a = prof_a.get("progressive_passes", 50)
    f3_a = prof_a.get("final_third_entries", 50)
    bcc_a = prof_a.get("big_chance_creation", 50)
    sq_a = prof_a.get("shot_quality", 50)

    pp_b = prof_b.get("progressive_passes", 50)
    f3_b = prof_b.get("final_third_entries", 50)
    bcc_b = prof_b.get("big_chance_creation", 50)
    sq_b = prof_b.get("shot_quality", 50)

    a_quality = (pp_a * 0.25 + f3_a * 0.25 + bcc_a * 0.30 + sq_a * 0.20)
    b_quality = (pp_b * 0.25 + f3_b * 0.25 + bcc_b * 0.30 + sq_b * 0.20)

    gap = (a_quality - b_quality) / 100.0
    if abs(gap) > 0.08:
        vision_a = _get_squad_avg(squad_a, "vision") if squad_a else 50
        passing_a = _get_squad_avg(squad_a, "passing") if squad_a else 50
        tech_a = (vision_a + passing_a) / 2.0
        quality_factor_a = max(0, (tech_a - 50) / 50.0)

        vision_b = _get_squad_avg(squad_b, "vision") if squad_b else 50
        passing_b = _get_squad_avg(squad_b, "passing") if squad_b else 50
        tech_b = (vision_b + passing_b) / 2.0
        quality_factor_b = max(0, (tech_b - 50) / 50.0)

        if gap > 0:
            boost = round(0.06 * gap * quality_factor_a, 4)
            if boost > 0.005:
                adj_a.append(TacticalAdjustment("possession_quality", f"Superior possession quality (prog_pass {pp_a:.0f}, F3 {f3_a:.0f}, BCC {bcc_a:.0f})", boost))
                adv_a.append(f"Possession quality advantage (+{boost:.2f} xG)")
        else:
            boost = round(0.06 * abs(gap) * quality_factor_b, 4)
            if boost > 0.005:
                adj_b.append(TacticalAdjustment("possession_quality", f"Superior possession quality (prog_pass {pp_b:.0f}, F3 {f3_b:.0f}, BCC {bcc_b:.0f})", boost))
                adv_b.append(f"Possession quality advantage (+{boost:.2f} xG)")


DEFENSIVE_STYLE_MATCHUPS: dict[str, dict[str, tuple[float, str]]] = {
    "low_block": {
        "high_press": (0.02, "Low block absorbs press; organised defense"),
        "mid_block": (0.01, "Low block more compact than mid block"),
        "high_line": (0.03, "Low block exploits space behind high line"),
        "possession": (-0.02, "Low block vulnerable to patient possession"),
        "direct": (0.02, "Low block handles direct play well"),
        "man_marking": (0.01, "Low block vs man marking: similar solidity"),
        "zonal": (0.01, "Low block slightly more rigid than zonal"),
    },
    "mid_block": {
        "low_block": (-0.01, "Mid block less compact than low block"),
        "high_press": (0.01, "Mid block balanced vs press"),
        "high_line": (0.02, "Mid block can cover high line space"),
        "possession": (0.00, "Mid block neutral vs possession"),
        "direct": (0.01, "Mid block handles direct adequately"),
        "man_marking": (0.01, "Mid block structure aids man marking"),
        "zonal": (0.00, "Mid block and zonal: similar philosophy"),
    },
    "high_press": {
        "low_block": (0.01, "High press can force low block errors"),
        "mid_block": (0.01, "High press intensity vs mid block shape"),
        "high_line": (0.02, "High press + high line: risky but rewarding"),
        "possession": (0.02, "High press disrupts possession build-up"),
        "direct": (-0.02, "High press vulnerable to direct balls over top"),
        "man_marking": (0.01, "High press more coordinated than man marking"),
        "zonal": (0.01, "High press more proactive than zonal"),
    },
    "man_marking": {
        "low_block": (0.00, "Man marking vs low block: similar rigidity"),
        "mid_block": (0.00, "Man marking neutral vs mid block"),
        "high_press": (-0.01, "Man marking less coordinated than high press"),
        "high_line": (0.01, "Man marking can track runners behind high line"),
        "possession": (-0.01, "Man marking vulnerable to position-swapping possession"),
        "direct": (-0.01, "Man marking can be pulled out of shape"),
        "zonal": (-0.01, "Man marking less flexible than zonal"),
    },
    "zonal": {
        "low_block": (-0.01, "Zonal less rigid than low block"),
        "mid_block": (0.00, "Zonal and mid block: compatible approaches"),
        "high_press": (-0.01, "Zonal less intense than high press"),
        "high_line": (0.01, "Zonal covers high line intelligently"),
        "possession": (0.01, "Zonal disciplined vs possession"),
        "direct": (0.00, "Zonal neutral vs direct play"),
        "man_marking": (0.01, "Zonal more flexible than man marking"),
    },
}


def _defensive_style_interaction(
    team_a: str, team_b: str,
    prof_a: dict, prof_b: dict,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    style_a = prof_a.get("defensive_style", "mid_block")
    style_b = prof_b.get("defensive_style", "mid_block")

    prof_a_style = style_a if style_a in DEFENSIVE_STYLES else "mid_block"
    prof_b_style = style_b if style_b in DEFENSIVE_STYLES else "mid_block"

    def _style_key(prof: dict) -> str:
        if prof.get("pressing", 50) > 70:
            return "high_press"
        if prof.get("directness", 50) > 65:
            return "direct"
        if prof.get("possession", 50) > 70:
            return "possession"
        if prof.get("defensive_line", 50) > 65:
            return "high_line"
        return "mid_block"

    key_a = _style_key(prof_a)
    key_b = _style_key(prof_b)

    matchups = DEFENSIVE_STYLE_MATCHUPS

    if prof_b_style in matchups and key_a in matchups[prof_b_style]:
        val_b, desc_b = matchups[prof_b_style][key_a]
        if abs(val_b) > 0.005:
            adj_b.append(TacticalAdjustment("defensive_style", f"{prof_b_style} vs {key_a}: {desc_b}", val_b))
            adv_b.append(f"Defensive style advantage ({prof_b_style} vs {key_a})")

    if prof_a_style in matchups and key_b in matchups[prof_a_style]:
        val_a, desc_a = matchups[prof_a_style][key_b]
        if abs(val_a) > 0.005:
            adj_a.append(TacticalAdjustment("defensive_style", f"{prof_a_style} vs {key_b}: {desc_a}", val_a))
            adv_a.append(f"Defensive style advantage ({prof_a_style} vs {key_b})")


def _tactical_flexibility_effects(
    team_a: str, team_b: str,
    prof_a: dict, prof_b: dict,
    plan_a: str, plan_b: str,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    flex_a = prof_a.get("tactical_flexibility", 50)
    flex_b = prof_b.get("tactical_flexibility", 50)

    flex_gap = (flex_a - flex_b) / 100.0
    if abs(flex_gap) > 0.15:
        if flex_gap > 0:
            boost = round(0.02 * flex_gap, 4)
            adj_a.append(TacticalAdjustment("flexibility", f"Tactical flexibility edge (flex {flex_a:.0f} vs {flex_b:.0f})", boost))
            adv_a.append(f"Tactical flexibility advantage (+{boost:.2f} xG)")
        else:
            boost = round(0.02 * abs(flex_gap), 4)
            adj_b.append(TacticalAdjustment("flexibility", f"Tactical flexibility edge (flex {flex_b:.0f} vs {flex_a:.0f})", boost))
            adv_b.append(f"Tactical flexibility advantage (+{boost:.2f} xG)")

    if flex_a < 40 and flex_b > 60:
        penalty = round(-0.015 * (flex_b - flex_a) / 60.0, 4)
        if penalty < -0.005:
            adj_a.append(TacticalAdjustment("rigidity", f"Tactically rigid (flex {flex_a:.0f}) vs flexible opponent (flex {flex_b:.0f})", penalty))
            adv_b.append(f"Opponent's tactical rigidity exploited (-{abs(penalty):.2f} xG)")

    if flex_b < 40 and flex_a > 60:
        penalty = round(-0.015 * (flex_a - flex_b) / 60.0, 4)
        if penalty < -0.005:
            adj_b.append(TacticalAdjustment("rigidity", f"Tactically rigid (flex {flex_b:.0f}) vs flexible opponent (flex {flex_a:.0f})", penalty))
            adv_a.append(f"Opponent's tactical rigidity exploited (-{abs(penalty):.2f} xG)")


def _match_context_effects(
    team_a: str, team_b: str,
    context: str,
    plan_a: str, plan_b: str,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    if context == "knockout":
        adj_a.append(TacticalAdjustment("match_context", "Knockout stage: higher stakes, less risk-taking", -0.01))
        adj_b.append(TacticalAdjustment("match_context", "Knockout stage: higher stakes, less risk-taking", -0.01))
        adv_a.append("Knockout context: slightly subdued xG (-0.01)")
        adv_b.append("Knockout context: slightly subdued xG (-0.01)")
    elif context == "must_win":
        if plan_a in ("attacking", "high_press"):
            adj_a.append(TacticalAdjustment("match_context", "Must-win: attacking urgency", 0.02))
            adv_a.append("Must-win urgency (+0.02 xG)")
        if plan_b in ("attacking", "high_press"):
            adj_b.append(TacticalAdjustment("match_context", "Must-win: attacking urgency", 0.02))
            adv_b.append("Must-win urgency (+0.02 xG)")
    elif context == "need_draw":
        if plan_a == "low_block":
            adj_a.append(TacticalAdjustment("match_context", "Need draw: deep defensive focus", -0.015))
            adv_a.append("Need-draw defensive focus (-0.015 xG)")
        if plan_b == "low_block":
            adj_b.append(TacticalAdjustment("match_context", "Need draw: deep defensive focus", -0.015))
            adv_b.append("Need-draw defensive focus (-0.015 xG)")
    elif context == "gd_chase":
        if plan_a in ("attacking", "high_press"):
            adj_a.append(TacticalAdjustment("match_context", "GD chase: high-risk attacking", 0.025))
            adj_a.append(TacticalAdjustment("match_context_risk", "GD chase: defensive gaps", -0.015))
            adv_a.append("GD chase: high risk/reward (+0.025 xG, -0.015 defensive)")
        if plan_b in ("attacking", "high_press"):
            adj_b.append(TacticalAdjustment("match_context", "GD chase: high-risk attacking", 0.025))
            adj_b.append(TacticalAdjustment("match_context_risk", "GD chase: defensive gaps", -0.015))
            adv_b.append("GD chase: high risk/reward (+0.025 xG, -0.015 defensive)")


def _defensive_stalemate(
    team_a: str, team_b: str,
    squad_a: Squad | None, squad_b: Squad | None,
    adj_a: list, adj_b: list,
    adv_a: list, adv_b: list,
) -> None:
    def_a = _get_squad_defensive_rating(squad_a)
    def_b = _get_squad_defensive_rating(squad_b)
    comp_a = _get_squad_composure_avg(squad_a)
    comp_b = _get_squad_composure_avg(squad_b)

    stalemate_threshold = 55.0
    if def_a >= stalemate_threshold and def_b >= stalemate_threshold:
        avg_def = (def_a + def_b) / 2.0
        above = (avg_def - stalemate_threshold) / 20.0
        above = max(0.0, min(1.0, above))

        reduction = round(-0.35 * above, 4)
        if reduction < -0.005:
            adj_a.append(TacticalAdjustment("defensive_stalemate",
                f"Defensive stalemate (def {def_a:.0f} vs {def_b:.0f}, comp {comp_a:.0f}/{comp_b:.0f})",
                reduction))
            adj_b.append(TacticalAdjustment("defensive_stalemate",
                f"Defensive stalemate (def {def_b:.0f} vs {def_a:.0f}, comp {comp_b:.0f}/{comp_a:.0f})",
                reduction))
            adv_a.append(f"Defensive stalemate: both teams solid in defense ({reduction:.2f} xG)")
            adv_b.append(f"Defensive stalemate: both teams solid in defense ({reduction:.2f} xG)")

    if comp_a >= 60.0 and comp_b >= 60.0:
        comp_reduction = round(-0.05, 4)
        adj_a.append(TacticalAdjustment("composure_stalemate",
            f"High composure match: fewer defensive errors (comp {comp_a:.0f}/{comp_b:.0f})",
            comp_reduction))
        adj_b.append(TacticalAdjustment("composure_stalemate",
            f"High composure match: fewer defensive errors (comp {comp_b:.0f}/{comp_a:.0f})",
            comp_reduction))
        adv_a.append(f"Composure stalemate: both teams composed under pressure ({comp_reduction:.3f} xG)")
        adv_b.append(f"Composure stalemate: both teams composed under pressure ({comp_reduction:.3f} xG)")


def format_tactical_report(report: TacticalReport) -> str:
    lines = [
        f"Tactical Matchup Report: {report.team_a} vs {report.team_b}",
        f"Match Context: {report.context}",
        "",
        f"Game Plans: {report.team_a} ({report.game_plan_a}) vs {report.team_b} ({report.game_plan_b})",
        "",
        "Base xG (from V3):",
        f"  {report.team_a}: {report.base_xg_a:.2f}",
        f"  {report.team_b}: {report.base_xg_b:.2f}",
        "",
        f"Tactical Advantages ({report.team_a}):",
    ]
    if report.advantages_a:
        for adv in report.advantages_a:
            lines.append(f"  + {adv}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append(f"Tactical Advantages ({report.team_b}):")
    if report.advantages_b:
        for adv in report.advantages_b:
            lines.append(f"  + {adv}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append("V4 Tactical Adjustments:")
    lines.append(f"  {report.team_a}:")
    if report.adjustments_a:
        for adj in report.adjustments_a:
            lines.append(f"    {adj.category}: {adj.value:+.4f} xG  [{adj.description}]")
        lines.append(f"    Total: {report.total_adjustment_a():+.4f} xG")
    else:
        lines.append("    No adjustments")

    lines.append(f"  {report.team_b}:")
    if report.adjustments_b:
        for adj in report.adjustments_b:
            lines.append(f"    {adj.category}: {adj.value:+.4f} xG  [{adj.description}]")
        lines.append(f"    Total: {report.total_adjustment_b():+.4f} xG")
    else:
        lines.append("    No adjustments")

    lines.append("")
    lines.append("Final xG (V3 + V4 tactical):")
    lines.append(f"  {report.team_a}: {report.final_xg_a:.4f}")
    lines.append(f"  {report.team_b}: {report.final_xg_b:.4f}")

    return "\n".join(lines)


# ── Tactical Vulnerability ──────────────────────────────────────────────────

STRENGTH_CATEGORIES = {
    "possession": "Possession control",
    "pressing": "Aggressive pressing",
    "high_line": "High defensive line",
    "aerial_strength": "Aerial dominance",
    "set_piece_attack": "Set-piece threat",
    "transition": "Transition speed",
    "finishing": "Clinical finishing",
    "creativity": "Creative midfield",
    "defensive_compactness": "Defensive organization",
    "counter": "Counter-attacking threat",
    "build_up": "Build-up quality",
}

WEAKNESS_CATEGORIES = {
    "low_possession": "Struggles to maintain possession",
    "low_pressing": "Low pressing intensity",
    "space_behind": "Space behind defensive line",
    "aerial_weakness": "Aerial vulnerability",
    "set_piece_defense": "Set-piece defensive weakness",
    "build_up_pressure": "Vulnerable to press in build-up",
    "defensive_width": "Defensive width issues",
    "counter_vulnerability": "Vulnerable to counter-attacks",
    "creativity_gap": "Lack of creative threat",
    "low_block_struggle": "Struggles vs low block",
}


def compute_strengths(
    team: str,
    squad: Squad,
    profile: dict,
) -> list[TacticalStrength]:
    strengths: list[TacticalStrength] = []

    checks = [
        ("possession", profile.get("possession", 50) > 65, (profile.get("possession", 50) - 50) / 50.0),
        ("pressing", profile.get("pressing", 50) > 65, (profile.get("pressing", 50) - 50) / 50.0),
        ("transition", profile.get("directness", 50) > 60 and _get_squad_avg(squad, "pace") > 65,
         (profile.get("directness", 50) - 50 + _get_squad_avg(squad, "pace") - 50) / 100.0),
        ("aerial_strength", profile.get("aerial_strength", 50) > 60, (profile.get("aerial_strength", 50) - 50) / 50.0),
        ("set_piece_attack", profile.get("set_piece_attack", 50) > 60, (profile.get("set_piece_attack", 50) - 50) / 50.0),
        ("finishing", _get_squad_avg(squad, "finishing") > 65, (_get_squad_avg(squad, "finishing") - 50) / 50.0),
        ("creativity", profile.get("big_chance_creation", 50) > 60, (profile.get("big_chance_creation", 50) - 50) / 50.0),
        ("defensive_compactness", profile.get("defensive_compactness", 50) > 65,
         (profile.get("defensive_compactness", 50) - 50) / 50.0),
        ("counter", profile.get("directness", 50) > 65 and profile.get("possession", 50) < 55,
         (profile.get("directness", 50) - 50) / 50.0),
        ("build_up", profile.get("build_up", 50) > 65 and _get_squad_avg(squad, "passing") > 65,
         (profile.get("build_up", 50) - 50 + _get_squad_avg(squad, "passing") - 50) / 100.0),
        ("high_line", profile.get("defensive_line", 50) > 65, (profile.get("defensive_line", 50) - 50) / 50.0),
    ]

    for category, condition, magnitude in checks:
        if condition:
            desc = STRENGTH_CATEGORIES.get(category, category)
            strengths.append(TacticalStrength(
                category=category,
                description=desc,
                magnitude=round(magnitude, 3),
                confidence=min(1.0, 0.5 + magnitude * 0.5),
            ))

    strengths.sort(key=lambda s: s.magnitude, reverse=True)
    return strengths[:6]


def compute_weaknesses(
    team: str,
    squad: Squad,
    profile: dict,
    opp_profile: dict | None = None,
) -> list[TeamWeakness]:
    weaknesses: list[TeamWeakness] = []

    checks = [
        ("low_possession", profile.get("possession", 50) < 45, 1.0 - profile.get("possession", 50) / 50.0),
        ("low_pressing", profile.get("pressing", 50) < 45, 1.0 - profile.get("pressing", 50) / 50.0),
        ("space_behind", profile.get("defensive_line", 50) > 65,
         (profile.get("defensive_line", 50) - 50) / 50.0),
        ("aerial_weakness", profile.get("aerial_strength", 50) < 45, 1.0 - profile.get("aerial_strength", 50) / 50.0),
        ("set_piece_defense", profile.get("set_piece_defense", 50) < 45, 1.0 - profile.get("set_piece_defense", 50) / 50.0),
        ("build_up_pressure", profile.get("build_up", 50) < 50 or _get_squad_avg(squad, "composure") < 55,
         1.0 - min(profile.get("build_up", 50), _get_squad_avg(squad, "composure")) / 60.0),
        ("defensive_width", profile.get("defensive_width", 50) < 45,
         1.0 - profile.get("defensive_width", 50) / 55.0),
        ("counter_vulnerability", profile.get("directness", 50) < 45 and profile.get("pressing", 50) > 60,
         (profile.get("pressing", 50) - profile.get("directness", 50)) / 100.0),
        ("creativity_gap", profile.get("big_chance_creation", 50) < 45,
         1.0 - profile.get("big_chance_creation", 50) / 55.0),
        ("low_block_struggle", profile.get("possession", 50) > 65 and profile.get("big_chance_creation", 50) < 50,
         (profile.get("possession", 50) - profile.get("big_chance_creation", 50)) / 100.0),
    ]

    for category, condition, severity in checks:
        if condition:
            desc = WEAKNESS_CATEGORIES.get(category, category)
            weaknesses.append(TeamWeakness(
                category=category,
                description=desc,
                severity=round(min(1.0, severity), 3),
            ))

    weaknesses.sort(key=lambda w: w.severity, reverse=True)
    return weaknesses[:5]


def compute_vulnerability_report(
    team: str,
    squad: Squad,
    profile: dict,
) -> TacticalVulnerabilityReport:
    strengths = compute_strengths(team, squad, profile)
    weaknesses = compute_weaknesses(team, squad, profile)
    return TacticalVulnerabilityReport(
        team=team,
        strengths=strengths,
        weaknesses=weaknesses,
    )


EXPLOIT_MAP = [
    ("high_line", "space_behind", "pace behind high line"),
    ("pressing", "build_up_pressure", "press against weak buildup"),
    ("aerial_strength", "aerial_weakness", "aerial attack"),
    ("set_piece_attack", "set_piece_defense", "set-piece exploitation"),
    ("possession", "low_block_struggle", "possession vs low block"),
    ("counter", "counter_vulnerability", "counter-attack"),
]


def compute_exploitation(
    team_a: str,
    team_b: str,
    squad_a: Squad,
    squad_b: Squad,
    profile_a: dict,
    profile_b: dict,
    tactical_report: TacticalReport | None = None,
) -> ExploitationReport:
    vuln_a = compute_vulnerability_report(team_a, squad_a, profile_a)
    vuln_b = compute_vulnerability_report(team_b, squad_b, profile_b)

    strengths_a = {s.category: s for s in vuln_a.strengths}
    strengths_b = {s.category: s for s in vuln_b.strengths}
    weaknesses_a = {w.category: w for w in vuln_a.weaknesses}
    weaknesses_b = {w.category: w for w in vuln_b.weaknesses}

    opportunities: list[ExploitationOpportunity] = []

    for a_strength, b_weakness, label in EXPLOIT_MAP:
        if a_strength in strengths_a and b_weakness in weaknesses_b:
            impact = round(min(0.20, strengths_a[a_strength].magnitude * weaknesses_b[b_weakness].severity * 0.3), 4)
            if impact > 0.005:
                opportunities.append(ExploitationOpportunity(
                    attacker=team_a, defender=team_b,
                    category=a_strength,
                    description=f"{label}: {strengths_a[a_strength].description} vs {weaknesses_b[b_weakness].description}",
                    xg_impact=impact,
                ))
        if b_weakness in weaknesses_a and a_strength in strengths_b:
            impact = round(min(0.20, strengths_b[a_strength].magnitude * weaknesses_a[b_weakness].severity * 0.3), 4)
            if impact > 0.005:
                opportunities.append(ExploitationOpportunity(
                    attacker=team_b, defender=team_a,
                    category=a_strength,
                    description=f"{label}: {strengths_b[a_strength].description} vs {weaknesses_a[b_weakness].description}",
                    xg_impact=impact,
                ))

    if tactical_report:
        for adj in tactical_report.adjustments_a:
            if adj.value > 0.005:
                cat = adj.category
                if cat not in {o.category for o in opportunities if o.attacker == team_a}:
                    opportunities.append(ExploitationOpportunity(
                        attacker=team_a, defender=team_b,
                        category=cat,
                        description=adj.description,
                        xg_impact=round(adj.value, 4),
                    ))
        for adj in tactical_report.adjustments_b:
            if adj.value > 0.005:
                cat = adj.category
                if cat not in {o.category for o in opportunities if o.attacker == team_b}:
                    opportunities.append(ExploitationOpportunity(
                        attacker=team_b, defender=team_a,
                        category=cat,
                        description=adj.description,
                        xg_impact=round(adj.value, 4),
                    ))

    opportunities.sort(key=lambda o: abs(o.xg_impact), reverse=True)
    return ExploitationReport(
        team_a=team_a,
        team_b=team_b,
        vulnerabilities_a=vuln_a,
        vulnerabilities_b=vuln_b,
        opportunities=opportunities[:8],
    )


ARCHETYPE_RULES = [
    ("Tactical Chess Match", 0.15, lambda p_a, p_b, tr: abs(p_a.get("possession", 50) - p_b.get("possession", 50)) < 10
     and abs(p_a.get("pressing", 50) - p_b.get("pressing", 50)) < 15),
    ("Possession Dominance", 0.25, lambda p_a, p_b, tr: max(p_a.get("possession", 50), p_b.get("possession", 50)) > 70
     and abs(p_a.get("possession", 50) - p_b.get("possession", 50)) > 15),
    ("Transition Battle", 0.20, lambda p_a, p_b, tr: p_a.get("directness", 50) > 60
     and p_b.get("directness", 50) > 60),
    ("Counter Attack Showcase", 0.15, lambda p_a, p_b, tr:
     (p_a.get("directness", 50) > 65 and p_b.get("possession", 50) > 65)
     or (p_b.get("directness", 50) > 65 and p_a.get("possession", 50) > 65)),
    ("Set Piece Battle", 0.08, lambda p_a, p_b, tr:
     max(p_a.get("set_piece_attack", 50), p_b.get("set_piece_attack", 50)) > 65
     and min(p_a.get("set_piece_defense", 50), p_b.get("set_piece_defense", 50)) < 55),
    ("End-to-End Chaos", 0.10, lambda p_a, p_b, tr:
     p_a.get("directness", 50) > 65 and p_b.get("directness", 50) > 65
     and p_a.get("defensive_line", 50) > 60 and p_b.get("defensive_line", 50) > 60),
    ("One-Sided Control", 0.07, lambda p_a, p_b, tr:
     abs(p_a.get("possession", 50) - p_b.get("possession", 50)) > 25
     and (tr and abs(tr.final_xg_a - tr.final_xg_b) > 1.0) if tr else False),
]


def classify_match_archetypes(
    team_a: str,
    team_b: str,
    profile_a: dict,
    profile_b: dict,
    tactical_report: TacticalReport | None = None,
) -> MatchArchetypeReport:
    scores: dict[str, float] = {}
    for archetype, base_prob, rule in ARCHETYPE_RULES:
        if rule(profile_a, profile_b, tactical_report):
            scores[archetype] = base_prob

    if not scores:
        scores = {"Tactical Chess Match": 0.40, "Possession Dominance": 0.30, "Transition Battle": 0.30}

    total = sum(scores.values())
    archetypes = [
        MatchArchetypeData(
            archetype=name,
            probability=round(prob / total * 100, 1),
            description=_archetype_desc(name),
        )
        for name, prob in sorted(scores.items(), key=lambda x: x[1], reverse=True)
    ]

    return MatchArchetypeReport(team_a=team_a, team_b=team_b, archetypes=archetypes)


def _archetype_desc(archetype: str) -> str:
    descs = {
        "Tactical Chess Match": "Both teams evenly matched. Fine margins decide the game.",
        "Possession Dominance": "One team controls possession and dictates tempo.",
        "Transition Battle": "Both teams prefer fast transitions over controlled build-up.",
        "Counter Attack Showcase": "One team dominates possession while the other threatens on the break.",
        "Set Piece Battle": "Dead-ball situations are the primary scoring threat.",
        "End-to-End Chaos": "Open game with both teams attacking aggressively.",
        "One-Sided Control": "One team completely dominates proceedings.",
    }
    return descs.get(archetype, "")


def analyze_win_conditions(
    team: str,
    profile: dict,
    squad: Squad,
) -> WinConditionReport:
    conditions: list[WinCondition] = []
    poss = profile.get("possession", 50)
    press = profile.get("pressing", 50)
    direct = profile.get("directness", 50)
    sp_attack = profile.get("set_piece_attack", 50)
    finishing_avg = _get_squad_avg(squad, "finishing")
    pace_avg = _get_squad_avg(squad, "pace")

    if direct > 60 and pace_avg > 65:
        conditions.append(WinCondition("Transition attacks", 0.35 + (direct - 50) / 200.0,
                                       "Fast breaks and counter-attacks"))
    if poss > 65:
        conditions.append(WinCondition("Possession dominance", 0.30 + (poss - 50) / 200.0,
                                       "Controlling the ball and probing for openings"))
    if press > 65:
        conditions.append(WinCondition("Pressing turnovers", 0.15 + (press - 50) / 300.0,
                                       "Winning ball high up the pitch"))
    if sp_attack > 60:
        conditions.append(WinCondition("Set pieces", 0.12 + (sp_attack - 50) / 300.0,
                                       "Corners, free-kicks, and throw-ins"))
    if finishing_avg > 70:
        conditions.append(WinCondition("Individual brilliance", 0.10 + (finishing_avg - 50) / 400.0,
                                       "Star quality in decisive moments"))
    if poss > 60 and press > 55:
        conditions.append(WinCondition("Midfield control", 0.12 + (poss - 50 + press - 50) / 400.0,
                                       "Dominating the middle of the park"))

    total = sum(c.probability for c in conditions) or 1.0
    for c in conditions:
        c.probability = round(c.probability / total * 100, 1)

    conditions.sort(key=lambda c: c.probability, reverse=True)
    return WinConditionReport(team=team, conditions=conditions[:5])


# ── Player Influence ───────────────────────────────────────────────────────

def _avg_attr(players: list[Player], key: str) -> float:
    if not players:
        return 50.0
    return sum(_attr(p, key) for p in players) / len(players)


def _max_attr(players: list[Player], key: str) -> float:
    if not players:
        return 50.0
    return max(_attr(p, key) for p in players)


def _role_group(players: list[Player], formation: str, roles: set[str]) -> list[Player]:
    return [p for p in players if role_for_player(p, formation) in roles]


def compute_offensive_influence(
    player: Player,
    squad: Squad,
    team_xg: float,
) -> OffensiveInfluence:
    role = role_for_player(player, squad.formation)
    formula = DEFAULT_POSITION_FORMULAS.get(role, {})
    base_rating = sum(_attr(player, attr) * weight for attr, weight in formula.items())

    finishing = _attr(player, "finishing")
    positioning = _attr(player, "positioning")
    vision = _attr(player, "vision")
    passing = _attr(player, "passing")
    dribbling = _attr(player, "dribbling")
    pace = _attr(player, "pace")
    composure = _attr(player, "composure")
    crossing = _attr(player, "crossing")
    long_shots = _attr(player, "long_shots")
    reactions = _attr(player, "reactions")
    strength = _attr(player, "strength")
    stamina = _attr(player, "stamina")

    role_xg_weight = {"ST": 0.35, "WINGER": 0.25, "CM": 0.15, "DM": 0.08, "FB": 0.06, "CB": 0.04, "GK": 0.01}.get(role, 0.10)
    role_xa_weight = {"ST": 0.10, "WINGER": 0.20, "CM": 0.25, "DM": 0.15, "FB": 0.18, "CB": 0.05, "GK": 0.02}.get(role, 0.10)

    finishing_score = finishing / 100.0
    positioning_score = positioning / 100.0
    vision_score = vision / 100.0
    passing_score = passing / 100.0
    dribble_score = dribbling / 100.0
    pace_score = pace / 100.0
    composure_score = composure / 100.0

    xg_contrib = round(team_xg * role_xg_weight * (0.3 + 0.7 * (finishing_score * 0.4 + positioning_score * 0.3 + composure_score * 0.3)), 4)
    xa_contrib = round(team_xg * role_xa_weight * (0.3 + 0.7 * (vision_score * 0.4 + passing_score * 0.3 + dribble_score * 0.3)), 4)
    chance_creation = round((vision_score * 0.35 + passing_score * 0.25 + dribble_score * 0.2 + crossing / 100.0 * 0.2) * 10, 2)
    progressive_actions = round((passing_score * 0.3 + dribble_score * 0.3 + pace_score * 0.2 + reactions / 100.0 * 0.2) * 10, 2)
    dangerous_touches = round((dribble_score * 0.3 + positioning_score * 0.3 + pace_score * 0.2 + composure_score * 0.2) * 10, 2)
    transition_impact = round((pace_score * 0.35 + dribble_score * 0.25 + passing_score * 0.2 + positioning_score * 0.2) * 10, 2)
    press_resistance = round((composure_score * 0.3 + dribble_score * 0.25 + passing_score * 0.25 + strength / 100.0 * 0.2) * 10, 2)

    overall = round(
        (xg_contrib / max(team_xg, 0.01)) * 30
        + (xa_contrib / max(team_xg, 0.01)) * 15
        + chance_creation * 0.15
        + progressive_actions * 0.10
        + dangerous_touches * 0.10
        + transition_impact * 0.10
        + press_resistance * 0.10,
        2,
    )
    overall = min(10.0, max(1.0, overall))

    if role in ("ST", "WINGER"):
        overall = min(10.0, overall + 0.5)
    elif role in ("CB", "GK"):
        overall = min(10.0, max(1.0, overall * 0.6))

    return OffensiveInfluence(
        player_name=player.name,
        role=role,
        xg_contribution=xg_contrib,
        xa_contribution=xa_contrib,
        chance_creation=chance_creation,
        progressive_actions=progressive_actions,
        dangerous_touches=dangerous_touches,
        transition_impact=transition_impact,
        press_resistance=press_resistance,
        overall_influence=round(overall, 1),
        breakdown={
            "finishing": finishing,
            "positioning": positioning,
            "vision": vision,
            "passing": passing,
            "dribbling": dribbling,
            "pace": pace,
            "composure": composure,
            "strength": strength,
            "stamina": stamina,
        },
    )


def compute_defensive_influence(
    player: Player,
    squad: Squad,
    opp_xg: float,
) -> DefensiveInfluence:
    role = role_for_player(player, squad.formation)

    defending = _attr(player, "defending")
    tackling = _attr(player, "tackling")
    interceptions = _attr(player, "interceptions")
    defensive_awareness = _attr(player, "defensive_awareness")
    strength = _attr(player, "strength")
    pace = _attr(player, "pace")
    stamina = _attr(player, "stamina")
    reactions = _attr(player, "reactions")
    jumping = _attr(player, "jumping")
    heading = _attr(player, "heading_accuracy")

    role_def_weight = {"CB": 0.30, "FB": 0.20, "DM": 0.20, "CM": 0.12, "ST": 0.03, "WINGER": 0.03, "GK": 0.05}.get(role, 0.08)

    def_score = defending / 100.0
    tack_score = tackling / 100.0
    int_score = interceptions / 100.0
    awr_score = defensive_awareness / 100.0
    str_score = strength / 100.0
    pace_score = pace / 100.0
    react_score = reactions / 100.0
    jump_score = jumping / 100.0
    head_score = heading / 100.0

    opp_xg_prevented = round(opp_xg * role_def_weight * (0.2 + 0.8 * (def_score * 0.3 + awr_score * 0.25 + tack_score * 0.25 + int_score * 0.2)), 4)
    defensive_stability = round((def_score * 0.25 + awr_score * 0.25 + tack_score * 0.2 + str_score * 0.15 + react_score * 0.15) * 10, 2)
    interceptions_rating = round((int_score * 0.4 + awr_score * 0.3 + react_score * 0.3) * 10, 2)
    tackling_rating = round((tack_score * 0.5 + def_score * 0.25 + strength / 100.0 * 0.25) * 10, 2)
    aerial_win_rate = round((jump_score * 0.4 + head_score * 0.3 + str_score * 0.3) * 10, 2)
    recovery_rating = round((pace_score * 0.35 + react_score * 0.25 + stamina / 100.0 * 0.2 + int_score * 0.2) * 10, 2)

    overall = round(
        (opp_xg_prevented / max(opp_xg, 0.01)) * 25
        + defensive_stability * 0.20
        + interceptions_rating * 0.15
        + tackling_rating * 0.15
        + aerial_win_rate * 0.10
        + recovery_rating * 0.15,
        2,
    )
    overall = min(10.0, max(1.0, overall))

    if role in ("CB", "DM"):
        overall = min(10.0, overall + 0.5)
    elif role in ("ST", "WINGER"):
        overall = max(1.0, overall * 0.5)

    return DefensiveInfluence(
        player_name=player.name,
        role=role,
        opp_xg_prevented=opp_xg_prevented,
        defensive_stability=defensive_stability,
        interceptions_rating=interceptions_rating,
        tackling_rating=tackling_rating,
        aerial_win_rate=aerial_win_rate,
        recovery_rating=recovery_rating,
        overall_influence=round(overall, 1),
        breakdown={
            "defending": defending,
            "tackling": tackling,
            "interceptions": interceptions,
            "defensive_awareness": defensive_awareness,
            "strength": strength,
            "pace": pace,
            "stamina": stamina,
            "jumping": jumping,
            "heading": heading,
        },
    )


def compute_goalkeeper_influence(
    player: Player,
    squad: Squad,
    opp_shots_on_target: float = 5.0,
) -> GoalkeeperInfluence:
    reflexes = _attr(player, "reflexes")
    diving = _attr(player, "diving")
    positioning = _attr(player, "positioning")
    handling = _attr(player, "handling")
    kicking = _attr(player, "kicking")
    reactions = _attr(player, "reactions")
    strength = _attr(player, "strength")

    reflex_score = reflexes / 100.0
    dive_score = diving / 100.0
    pos_score = positioning / 100.0
    hand_score = handling / 100.0
    kick_score = kicking / 100.0
    react_score = reactions / 100.0
    jump = _attr(player, "jumping")
    composure = _attr(player, "composure")

    expected_save_rate = 0.60 + (reflex_score * 0.15 + dive_score * 0.10 + pos_score * 0.10 + react_score * 0.10) * 0.30
    expected_saves = opp_shots_on_target * expected_save_rate
    actual_saves = opp_shots_on_target * min(1.0, expected_save_rate + (reflex_score * 0.1 + react_score * 0.1))

    goals_prevented = round(actual_saves - expected_saves, 4)
    save_expectation = round(expected_save_rate * 10, 2)
    claim_rating = round((hand_score * 0.4 + strength / 100.0 * 0.3 + jump / 100.0 * 0.3) * 10, 2)
    distribution_rating = round((kick_score * 0.5 + pos_score * 0.3 + composure / 100.0 * 0.2) * 10, 2)
    one_on_one_rating = round((reflex_score * 0.35 + dive_score * 0.25 + react_score * 0.2 + pos_score * 0.2) * 10, 2)

    overall = round(
        max(0, goals_prevented) * 15
        + save_expectation * 0.15
        + claim_rating * 0.10
        + distribution_rating * 0.10
        + one_on_one_rating * 0.15,
        2,
    )
    overall = min(10.0, max(1.0, overall))

    return GoalkeeperInfluence(
        player_name=player.name,
        goals_prevented=goals_prevented,
        save_expectation=save_expectation,
        claim_rating=claim_rating,
        distribution_rating=distribution_rating,
        one_on_one_rating=one_on_one_rating,
        overall_influence=round(overall, 1),
        breakdown={
            "reflexes": reflexes,
            "diving": diving,
            "positioning": positioning,
            "handling": handling,
            "kicking": kicking,
            "reactions": reactions,
            "jumping": jump,
            "composure": composure,
        },
    )


def compute_team_dependency(
    team: str,
    squad: Squad,
    team_xg: float,
    opp_xg: float,
) -> TeamDependency:
    offensive = []
    for player in squad.current_starting_xi:
        role = role_for_player(player, squad.formation)
        if role in ("ST", "WINGER", "CM"):
            inf = compute_offensive_influence(player, squad, team_xg)
            offensive.append((player.name, inf.xg_contribution))

    offensive.sort(key=lambda x: x[1], reverse=True)
    total_off = sum(x[1] for x in offensive) or 0.001
    top3_off = sum(x[1] for x in offensive[:3])
    top3_share = top3_off / total_off

    if top3_share > 0.55:
        dep_level = "High"
    elif top3_share > 0.40:
        dep_level = "Moderate"
    else:
        dep_level = "Low"

    defensive = []
    for player in squad.current_starting_xi:
        role = role_for_player(player, squad.formation)
        if role in ("CB", "FB", "DM"):
            inf = compute_defensive_influence(player, squad, opp_xg)
            defensive.append((player.name, inf.opp_xg_prevented))

    defensive.sort(key=lambda x: x[1], reverse=True)
    total_def = sum(x[1] for x in defensive) or 0.001
    top3_def = sum(x[1] for x in defensive[:3])
    top3_def_share = top3_def / total_def

    return TeamDependency(
        team=team,
        top_n_attackers=3,
        attack_output_share=round(top3_share * 100, 1),
        top_attackers_names=[x[0] for x in offensive[:3]],
        dependency_level=dep_level,
        top_n_defenders=3,
        defense_output_share=round(top3_def_share * 100, 1),
        top_defenders_names=[x[0] for x in defensive[:3]],
    )


def compute_player_matchups(
    squad_a: Squad,
    squad_b: Squad,
    tactical_profiles: dict[str, dict] | None = None,
) -> list[PlayerMatchup]:
    matchups: list[PlayerMatchup] = []

    def _best_at(squad: Squad, roles: set[str]) -> Player | None:
        candidates = [p for p in squad.current_starting_xi if role_for_player(p, squad.formation) in roles]
        if not candidates:
            return None
        return max(candidates, key=lambda p: sum(p.attributes.get(a, 50) for a in ("finishing", "pace", "dribbling")))

    def _best_defender(squad: Squad, roles: set[str]) -> Player | None:
        candidates = [p for p in squad.current_starting_xi if role_for_player(p, squad.formation) in roles]
        if not candidates:
            return None
        return max(candidates, key=lambda p: sum(p.attributes.get(a, 50) for a in ("defending", "tackling", "pace")))

    duo_categories = [
        ("ST vs CB", {"ST"}, {"CB"}),
        ("Winger vs FB", {"WINGER"}, {"FB"}),
        ("Midfield Battle", {"CM", "DM"}, {"CM", "DM"}),
    ]

    for title, off_roles, def_roles in duo_categories:
        att_a = _best_at(squad_a, off_roles)
        att_b = _best_at(squad_b, off_roles)
        def_a = _best_defender(squad_a, def_roles)
        def_b = _best_defender(squad_b, def_roles)

        if att_a and def_b:
            pace_a = _attr(att_a, "pace")
            drib_a = _attr(att_a, "dribbling")
            def_b_val = _attr(def_b, "defending")
            tack_b = _attr(def_b, "tackling")
            pace_b = _attr(def_b, "pace")
            adv_mag_a = (pace_a + drib_a) / 2 - (def_b_val + tack_b + pace_b) / 3
            impact_a = round(max(0, adv_mag_a / 100.0) * 0.12, 4)
            matchups.append(PlayerMatchup(
                player_a=att_a.name, player_b=def_b.name,
                category=title, advantage_team=squad_a.country,
                advantage_magnitude=round(max(0, adv_mag_a / 10.0), 1),
                net_xg_impact=impact_a,
                key_stats={"pace": (pace_a, pace_b), "dribbling": (drib_a, _attr(def_b, "defending"))},
                description=f"{att_a.name} ({pace_a:.0f} pace, {drib_a:.0f} drib) vs {def_b.name} ({def_b_val:.0f} def, {pace_b:.0f} pace)",
            ))

        if att_b and def_a:
            pace_b_val = _attr(att_b, "pace")
            drib_b = _attr(att_b, "dribbling")
            def_a_val = _attr(def_a, "defending")
            tack_a = _attr(def_a, "tackling")
            pace_a_val = _attr(def_a, "pace")
            adv_mag_b = (pace_b_val + drib_b) / 2 - (def_a_val + tack_a + pace_a_val) / 3
            impact_b = round(max(0, adv_mag_b / 100.0) * 0.12, 4)
            matchups.append(PlayerMatchup(
                player_a=att_b.name, player_b=def_a.name,
                category=title, advantage_team=squad_b.country,
                advantage_magnitude=round(max(0, adv_mag_b / 10.0), 1),
                net_xg_impact=impact_b,
                key_stats={"pace": (pace_b_val, pace_a_val), "dribbling": (drib_b, _attr(def_a, "defending"))},
                description=f"{att_b.name} ({pace_b_val:.0f} pace, {drib_b:.0f} drib) vs {def_a.name} ({def_a_val:.0f} def, {pace_a_val:.0f} pace)",
            ))

    return matchups


def compute_player_influence(
    team_a: str,
    team_b: str,
    squad_a: Squad,
    squad_b: Squad,
    team_xg_a: float,
    team_xg_b: float,
    tactical_profiles: dict[str, dict] | None = None,
) -> PlayerInfluenceReport:
    off_a = [compute_offensive_influence(p, squad_a, team_xg_a) for p in squad_a.current_starting_xi]
    off_b = [compute_offensive_influence(p, squad_b, team_xg_b) for p in squad_b.current_starting_xi]
    def_a = [compute_defensive_influence(p, squad_a, team_xg_b) for p in squad_a.current_starting_xi]
    def_b = [compute_defensive_influence(p, squad_b, team_xg_a) for p in squad_b.current_starting_xi]

    gk_a = None
    gk_b = None
    for p in squad_a.current_starting_xi:
        if role_for_player(p, squad_a.formation) == "GK":
            gk_a = compute_goalkeeper_influence(p, squad_a, 5.0)
            break
    for p in squad_b.current_starting_xi:
        if role_for_player(p, squad_b.formation) == "GK":
            gk_b = compute_goalkeeper_influence(p, squad_b, 5.0)
            break

    dep_a = compute_team_dependency(team_a, squad_a, team_xg_a, team_xg_b)
    dep_b = compute_team_dependency(team_b, squad_b, team_xg_b, team_xg_a)
    matchups = compute_player_matchups(squad_a, squad_b, tactical_profiles)

    return PlayerInfluenceReport(
        team_a=team_a,
        team_b=team_b,
        offensive_a=off_a,
        offensive_b=off_b,
        defensive_a=def_a,
        defensive_b=def_b,
        goalkeeper_a=gk_a,
        goalkeeper_b=gk_b,
        dependency_a=dep_a,
        dependency_b=dep_b,
        matchups=matchups,
    )
