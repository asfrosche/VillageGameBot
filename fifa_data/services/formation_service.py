from __future__ import annotations

from ..models.tactical_state import FormationProfile

FORMATION_PROFILES: dict[str, FormationProfile] = {
    "4-3-3": FormationProfile(
        name="4-3-3",
        width=0.80,
        central_control=0.55,
        defensive_stability=0.50,
        pressing_capability=0.80,
        space_behind_fullbacks=0.60,
        counter_risk=0.45,
        build_up_support=0.65,
    ),
    "4-2-3-1": FormationProfile(
        name="4-2-3-1",
        width=0.65,
        central_control=0.75,
        defensive_stability=0.70,
        pressing_capability=0.60,
        space_behind_fullbacks=0.40,
        counter_risk=0.35,
        build_up_support=0.55,
    ),
    "4-4-2": FormationProfile(
        name="4-4-2",
        width=0.70,
        central_control=0.50,
        defensive_stability=0.65,
        pressing_capability=0.55,
        space_behind_fullbacks=0.35,
        counter_risk=0.30,
        build_up_support=0.50,
    ),
    "3-4-3": FormationProfile(
        name="3-4-3",
        width=0.85,
        central_control=0.50,
        defensive_stability=0.40,
        pressing_capability=0.65,
        space_behind_fullbacks=0.70,
        counter_risk=0.55,
        build_up_support=0.70,
    ),
    "3-5-2": FormationProfile(
        name="3-5-2",
        width=0.70,
        central_control=0.75,
        defensive_stability=0.55,
        pressing_capability=0.60,
        space_behind_fullbacks=0.60,
        counter_risk=0.50,
        build_up_support=0.60,
    ),
    "5-3-2": FormationProfile(
        name="5-3-2",
        width=0.50,
        central_control=0.60,
        defensive_stability=0.85,
        pressing_capability=0.35,
        space_behind_fullbacks=0.25,
        counter_risk=0.20,
        build_up_support=0.40,
    ),
    "5-4-1": FormationProfile(
        name="5-4-1",
        width=0.45,
        central_control=0.55,
        defensive_stability=0.90,
        pressing_capability=0.30,
        space_behind_fullbacks=0.20,
        counter_risk=0.15,
        build_up_support=0.35,
    ),
    "4-1-4-1": FormationProfile(
        name="4-1-4-1",
        width=0.65,
        central_control=0.65,
        defensive_stability=0.75,
        pressing_capability=0.55,
        space_behind_fullbacks=0.35,
        counter_risk=0.30,
        build_up_support=0.55,
    ),
}


def get_formation_profile(formation: str) -> FormationProfile:
    parts = formation.split("-")
    if len(parts) == 3:
        key = f"{parts[0]}-{parts[1]}-{parts[2]}"
        if key in FORMATION_PROFILES:
            return FORMATION_PROFILES[key]
    if len(parts) == 4:
        key = f"{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"
        if key in FORMATION_PROFILES:
            return FORMATION_PROFILES[key]
    return FORMATION_PROFILES.get("4-3-3", FormationProfile("4-3-3", 0.70, 0.50, 0.50, 0.50, 0.40, 0.35, 0.50))


def formation_matchup_advantages(
    formation_a: str, formation_b: str,
) -> tuple[list[str], list[str]]:
    prof_a = get_formation_profile(formation_a)
    prof_b = get_formation_profile(formation_b)
    adv_a: list[str] = []
    adv_b: list[str] = []

    if prof_a.width > prof_b.width + 0.10:
        adv_a.append("Width advantage: wide play vs narrow defense")
    elif prof_b.width > prof_a.width + 0.10:
        adv_b.append("Width advantage: wide play vs narrow defense")

    if prof_a.central_control > prof_b.central_control + 0.10:
        adv_a.append("Midfield numerical advantage")
    elif prof_b.central_control > prof_a.central_control + 0.10:
        adv_b.append("Midfield numerical advantage")

    if prof_a.space_behind_fullbacks > prof_b.space_behind_fullbacks + 0.10:
        adv_b.append("Space behind fullbacks can be exploited")
    elif prof_b.space_behind_fullbacks > prof_a.space_behind_fullbacks + 0.10:
        adv_a.append("Space behind fullbacks can be exploited")

    return adv_a, adv_b
