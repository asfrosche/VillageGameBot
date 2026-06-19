from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models.player import Player
from ..models.squad import Squad
from ..models.tactical_state import (
    DEFENSIVE_STYLES,
    TacticalAdjustment,
    TacticalReport,
    GAME_PLANS,
)
from .formation_service import get_formation_profile, formation_matchup_advantages

HERE = Path(__file__).resolve().parents[1]


def _load_tactical_profiles() -> dict[str, dict[str, Any]]:
    path = HERE / "data" / "tactical_profiles.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


_TACTICAL_PROFILES = _load_tactical_profiles()


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

    # Original 7 matchups
    _high_line_vs_pace(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _pressing_vs_buildup(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _possession_vs_low_block(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _set_pieces(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _aerial_battles(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _formation_matchup(team_a, team_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _game_plan_effects(plan_a, plan_b, prof_a, prof_b, adjustments_a, adjustments_b, advantages_a, advantages_b)
    _player_tactic_compatibility(team_a, team_b, squad_a, squad_b, prof_a, prof_b, adjustments_a, adjustments_b, advantages_a, advantages_b)

    # NEW: Possession quality
    _possession_quality(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)

    # NEW: Defensive style interaction
    _defensive_style_interaction(team_a, team_b, prof_a, prof_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)

    # NEW: Tactical flexibility
    _tactical_flexibility_effects(team_a, team_b, prof_a, prof_b, plan_a, plan_b, squad_a, squad_b, adjustments_a, adjustments_b, advantages_a, advantages_b)

    # NEW: Match context
    _match_context_effects(team_a, team_b, context, plan_a, plan_b, adjustments_a, adjustments_b, advantages_a, advantages_b)

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
    from ..models.team_strength import role_for_player
    attackers = [p for p in squad.current_starting_xi if role_for_player(p, squad.formation) in {"ST", "WINGER"}]
    if not attackers:
        return 50.0
    vals = [p.attributes.get(attr, 50.0) for p in attackers]
    return sum(vals) / len(vals)


def _get_defenders_avg(squad: Squad | None, attr: str) -> float:
    if not squad or not squad.current_starting_xi:
        return 50.0
    from ..models.team_strength import role_for_player
    defenders = [p for p in squad.current_starting_xi if role_for_player(p, squad.formation) in {"CB", "FB"}]
    if not defenders:
        return 50.0
    vals = [p.attributes.get(attr, 50.0) for p in defenders]
    return sum(vals) / len(vals)


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
        if boost > 0.01:
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


# ────────────────────────────────────────────────────────────────────────────
# NEW: Possession Quality  (FBref / StatsBomb / Opta-based)
# ────────────────────────────────────────────────────────────────────────────

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

    # Team A possession quality advantage
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


# ────────────────────────────────────────────────────────────────────────────
# NEW: Defensive Style Interaction
# ────────────────────────────────────────────────────────────────────────────

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

    # Interaction: how does Team A's defensive style handle Team B's approach?
    # We map Team B's predominant style into one of the matchup keys.

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

    # Team A's defensive style vs Team B's attacking style
    if prof_b_style in matchups and key_a in matchups[prof_b_style]:
        val_b, desc_b = matchups[prof_b_style][key_a]
        if abs(val_b) > 0.005:
            adj_b.append(TacticalAdjustment("defensive_style", f"{prof_b_style} vs {key_a}: {desc_b}", val_b))
            adv_b.append(f"Defensive style advantage ({prof_b_style} vs {key_a})")

    # Team B's defensive style vs Team A's attacking style
    if prof_a_style in matchups and key_b in matchups[prof_a_style]:
        val_a, desc_a = matchups[prof_a_style][key_b]
        if abs(val_a) > 0.005:
            adj_a.append(TacticalAdjustment("defensive_style", f"{prof_a_style} vs {key_b}: {desc_a}", val_a))
            adv_a.append(f"Defensive style advantage ({prof_a_style} vs {key_b})")


# ────────────────────────────────────────────────────────────────────────────
# NEW: Tactical Flexibility
# ────────────────────────────────────────────────────────────────────────────

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

    # Flexible team can partially counter opponent's game plan advantage
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

    # Extremely rigid team (< 40 flex) suffers more vs adaptable opponent
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


# ────────────────────────────────────────────────────────────────────────────
# NEW: Match Context Effects
# ────────────────────────────────────────────────────────────────────────────

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


# ────────────────────────────────────────────────────────────────────────────
# Formatting
# ────────────────────────────────────────────────────────────────────────────

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
