from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .player import Player


DEFAULT_POSITION_FORMULAS: dict[str, dict[str, float]] = {
    "ST": {
        "finishing": 0.35,
        "positioning": 0.20,
        "shot_power": 0.15,
        "pace": 0.15,
        "composure": 0.15,
    },
    "WINGER": {
        "pace": 0.30,
        "dribbling": 0.25,
        "crossing": 0.20,
        "finishing": 0.15,
        "vision": 0.10,
    },
    "CM": {
        "passing": 0.30,
        "vision": 0.20,
        "dribbling": 0.20,
        "stamina": 0.15,
        "defending": 0.15,
    },
    "DM": {
        "defending": 0.30,
        "interceptions": 0.25,
        "passing": 0.20,
        "physical": 0.15,
        "stamina": 0.10,
    },
    "FB": {
        "pace": 0.25,
        "defending": 0.20,
        "crossing": 0.20,
        "stamina": 0.15,
        "passing": 0.10,
        "dribbling": 0.10,
    },
    "CB": {
        "defensive_awareness": 0.30,
        "tackling": 0.25,
        "strength": 0.15,
        "pace": 0.15,
        "reactions": 0.15,
    },
    "GK": {
        "reflexes": 0.30,
        "diving": 0.25,
        "positioning": 0.20,
        "handling": 0.15,
        "kicking": 0.10,
    },
}

POSITION_ALIASES = {
    "G": "GK",
    "GK": "GK",
    "KEEPER": "GK",
    "GOALKEEPER": "GK",
    "CB": "CB",
    "CD": "CB",
    "LCB": "CB",
    "RCB": "CB",
    "CENTRE BACK": "CB",
    "CENTER BACK": "CB",
    "CENTRAL DEFENDER": "CB",
    "DF": "DEF",
    "DEF": "DEF",
    "DEFENDER": "DEF",
    "LB": "FB",
    "RB": "FB",
    "LWB": "FB",
    "RWB": "FB",
    "WB": "FB",
    "FULLBACK": "FB",
    "WINGBACK": "FB",
    "DM": "DM",
    "CDM": "DM",
    "MCD": "DM",
    "DEFENSIVE MIDFIELDER": "DM",
    "CM": "CM",
    "MC": "CM",
    "MID": "CM",
    "MIDFIELDER": "CM",
    "CAM": "CM",
    "AM": "CM",
    "ATTACKING MIDFIELDER": "CM",
    "ST": "ST",
    "CF": "ST",
    "FWD": "ST",
    "FW": "ST",
    "FORWARD": "ST",
    "AT": "ST",
    "LW": "WINGER",
    "RW": "WINGER",
    "LF": "WINGER",
    "RF": "WINGER",
    "WF": "WINGER",
    "WINGER": "WINGER",
    "LM": "WINGER",
    "RM": "WINGER",
}


@dataclass(frozen=True)
class RoleRating:
    player_name: str
    role: str
    rating: float
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TeamStrength:
    team: str
    formation: str
    attack_rating: float
    midfield_rating: float
    defense_rating: float
    goalkeeper_rating: float
    role_ratings: list[RoleRating] = field(default_factory=list)
    breakdown: dict[str, object] = field(default_factory=dict)


def role_for_player(player: Player, formation: str | None = None) -> str:
    positions = player.normalized_positions()
    if not positions:
        return "CM"
    mapped = [POSITION_ALIASES.get(position, position) for position in positions]
    if "GK" in mapped:
        return "GK"
    if "DM" in mapped:
        return "DM"
    if any(role in mapped for role in ("ST", "WINGER")):
        if "ST" in mapped:
            return "ST"
        return "WINGER"
    if "FB" in mapped:
        return "FB"
    if "CB" in mapped or "DEF" in mapped:
        return "CB"
    return "CM"


def role_rating(
    player: Player,
    role: str,
    formulas: dict[str, dict[str, float]] | None = None,
) -> float:
    role = role.upper()
    formula = (formulas or DEFAULT_POSITION_FORMULAS).get(role)
    if not formula:
        raise ValueError(f"Unknown role formula: {role}")

    weighted_sum = 0.0
    for attribute, weight in formula.items():
        value = _attribute_value(player.attributes, attribute)
        weighted_sum += value * weight
    return round(weighted_sum, 4)


def assign_roles(
    starting_xi: list[Player],
    formation: str,
) -> list[tuple[Player, str]]:
    if not starting_xi:
        return []

    counts = parse_formation(formation)
    goalkeepers = [player for player in starting_xi if role_for_player(player, formation) == "GK"]
    outfield = [player for player in starting_xi if player not in goalkeepers]
    assigned: list[tuple[Player, str]] = []

    if goalkeepers:
        assigned.append((goalkeepers[0], "GK"))

    attack_candidates = [
        player for player in outfield if role_for_player(player, formation) in {"ST", "WINGER"}
    ]
    defense_candidates = [
        player for player in outfield if role_for_player(player, formation) in {"CB", "FB", "DEF"}
    ]
    midfield_candidates = [
        player for player in outfield if player not in attack_candidates and player not in defense_candidates
    ]

    attack_count = counts.get("AT", 3)
    defense_count = counts.get("DF", 4)
    dm_count = counts.get("DM", 0)
    cm_count = max(0, counts.get("MF", 3) - dm_count)

    attack_pool = _take(attack_candidates, attack_count)
    remaining_outfield = [player for player in outfield if player not in attack_pool]

    defense_pool = _take(
        [player for player in remaining_outfield if role_for_player(player, formation) in {"CB", "FB", "DEF"}],
        defense_count,
    )
    remaining_outfield = [player for player in remaining_outfield if player not in defense_pool]

    midfield_pool = _take(
        [player for player in remaining_outfield if role_for_player(player, formation) in {"CM", "DM"}],
        dm_count + cm_count,
    )
    if len(midfield_pool) < dm_count + cm_count:
        midfield_pool.extend(
            player
            for player in remaining_outfield
            if player not in midfield_pool
        )
        midfield_pool = midfield_pool[: dm_count + cm_count]

    assigned.extend(_assign_attack_roles(attack_pool))
    assigned.extend(_assign_defense_roles(defense_pool))
    assigned.extend(_assign_midfield_roles(midfield_pool, dm_count))

    used_names = {player.name for player, _ in assigned}
    for player in starting_xi:
        if player.name not in used_names and len(assigned) < 11:
            assigned.append((player, _fallback_role(player, formation)))
            used_names.add(player.name)

    return assigned[:11]


def build_team_strength(
    team: str,
    starting_xi: list[Player],
    formation: str,
    formulas: dict[str, dict[str, float]] | None = None,
) -> TeamStrength:
    role_assignments = assign_roles(starting_xi, formation)
    role_ratings = [
        RoleRating(
            player_name=player.name,
            role=role,
            rating=role_rating(player, role, formulas),
            breakdown=_rating_breakdown(player, role, formulas),
        )
        for player, role in role_assignments
    ]

    attack = _average(role_ratings, {"ST", "WINGER"})
    midfield = _average(role_ratings, {"CM", "DM"})
    defense = _average(role_ratings, {"CB", "FB"})
    goalkeeper = _average(role_ratings, {"GK"})

    return TeamStrength(
        team=team,
        formation=formation,
        attack_rating=round(attack, 4),
        midfield_rating=round(midfield, 4),
        defense_rating=round(defense, 4),
        goalkeeper_rating=round(goalkeeper, 4),
        role_ratings=role_ratings,
        breakdown={
            "attack": _component_breakdown(role_ratings, {"ST", "WINGER"}),
            "midfield": _component_breakdown(role_ratings, {"CM", "DM"}),
            "defense": _component_breakdown(role_ratings, {"CB", "FB"}),
            "goalkeeper": _component_breakdown(role_ratings, {"GK"}),
        },
    )


def parse_formation(formation: str) -> dict[str, int]:
    parts = [int(part) for part in str(formation).split("-") if part.isdigit()]
    if len(parts) == 3:
        return {"DF": parts[0], "MF": parts[1], "AT": parts[2], "DM": 0}
    if len(parts) == 4:
        return {"DF": parts[0], "DM": parts[1], "MF": parts[2], "AT": parts[3]}
    raise ValueError(f"Unsupported formation: {formation}")


def infer_formation(starting_xi: list[Player]) -> str:
    roles = [role_for_player(player) for player in starting_xi]
    defense = sum(1 for role in roles if role in {"CB", "FB", "DEF"})
    midfield = sum(1 for role in roles if role in {"CM", "DM"})
    attack = sum(1 for role in roles if role in {"ST", "WINGER"})
    if defense + midfield + attack != 10:
        return "4-3-3"
    return f"{defense}-{midfield}-{attack}"


def _attribute_value(attributes: dict[str, float], attribute: str) -> float:
    normalized = attribute.lower().replace(" ", "_")
    for key, value in attributes.items():
        if key.lower().replace(" ", "_") == normalized:
            return float(value)
    return 70.0


def _rating_breakdown(
    player: Player,
    role: str,
    formulas: dict[str, dict[str, float]] | None,
) -> dict[str, float]:
    formula = (formulas or DEFAULT_POSITION_FORMULAS).get(role.upper(), {})
    return {
        attribute: _attribute_value(player.attributes, attribute)
        for attribute in formula
    }


def _average(role_ratings: list[RoleRating], roles: set[str]) -> float:
    values = [item.rating for item in role_ratings if item.role in roles]
    return mean(values) if values else 70.0


def _component_breakdown(
    role_ratings: list[RoleRating],
    roles: set[str],
) -> list[dict[str, object]]:
    return [
        {"name": item.player_name, "role": item.role, "rating": item.rating}
        for item in role_ratings
        if item.role in roles
    ]


def _assign_attack_roles(players: list[Player]) -> list[tuple[Player, str]]:
    if not players:
        return []
    roles = ["ST"] + ["WINGER"] * (len(players) - 1)
    return list(zip(players, roles))


def _assign_defense_roles(players: list[Player]) -> list[tuple[Player, str]]:
    if not players:
        return []
    center_backs = min(2, len(players))
    roles = ["CB"] * center_backs + ["FB"] * (len(players) - center_backs)
    return list(zip(players, roles))


def _assign_midfield_roles(players: list[Player], dm_count: int) -> list[tuple[Player, str]]:
    if not players:
        return []
    defensive_mids = min(dm_count, len(players))
    roles = ["DM"] * defensive_mids + ["CM"] * (len(players) - defensive_mids)
    return list(zip(players, roles))


def _take(players: list[Player], count: int) -> list[Player]:
    return players[: max(0, count)]


def _fallback_role(player: Player, formation: str) -> str:
    role = role_for_player(player, formation)
    if role == "DEF":
        return "CB"
    return role


POSITION_WEIGHTS: dict[str, dict[str, float]] = {
    "attack": {"ST": 0.40, "WINGER": 0.30},
    "midfield": {"CM": 0.35, "DM": 0.30},
    "defense": {"CB": 0.35, "FB": 0.15},
    "goalkeeper": {"GK": 1.00},
}


ROLE_TO_LINE: dict[str, str] = {
    "ST": "attack",
    "WINGER": "attack",
    "CM": "midfield",
    "DM": "midfield",
    "CB": "defense",
    "FB": "defense",
    "GK": "goalkeeper",
}


def weighted_average(
    role_ratings: list[RoleRating],
    roles: set[str],
    weights: dict[str, dict[str, float]] | None = None,
) -> float:
    """Weighted average using positional importance weights.

    Star players at key positions (ST, CB) contribute more than role players.
    """
    role_weights = weights or POSITION_WEIGHTS
    items = [item for item in role_ratings if item.role in roles]
    if not items:
        return 70.0

    line = None
    for item in items:
        candidate = ROLE_TO_LINE.get(item.role)
        if candidate:
            line = candidate
            break
    if not line or line not in role_weights:
        return mean(item.rating for item in items)

    line_w = role_weights[line]
    total_weight = 0.0
    weighted_sum = 0.0
    for item in items:
        w = line_w.get(item.role, 0.0)
        if w > 0:
            weighted_sum += item.rating * w
            total_weight += w
    if total_weight == 0:
        return mean(item.rating for item in items)
    return weighted_sum / total_weight


def average_rating(role_ratings: list[RoleRating], roles: set[str]) -> float:
    """Simple unweighted average (original V2 behavior)."""
    values = [item.rating for item in role_ratings if item.role in roles]
    return mean(values) if values else 70.0
