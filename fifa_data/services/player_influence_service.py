from __future__ import annotations

from ..models.player import Player
from ..models.squad import Squad
from ..models.team_strength import role_for_player, DEFAULT_POSITION_FORMULAS
from ..models.player_influence import (
    OffensiveInfluence,
    DefensiveInfluence,
    GoalkeeperInfluence,
    TeamDependency,
    PlayerMatchup,
    PlayerInfluenceReport,
)
from ..services.tactical_matchup_service import _get_squad_avg, _get_squad_max, _get_attackers_avg, _get_defenders_avg


def _attr(player: Player | None, key: str, default: float = 50.0) -> float:
    if player is None:
        return default
    return player.attributes.get(key, default)


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
