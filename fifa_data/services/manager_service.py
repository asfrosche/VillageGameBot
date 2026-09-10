from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models.tactical_state import ManagerProfile

HERE = Path(__file__).resolve().parents[1]


def _load_manager_profiles() -> dict[str, dict[str, Any]]:
    path = HERE / "data" / "manager_profiles.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


_MANAGER_PROFILES = _load_manager_profiles()


def get_manager(team: str) -> ManagerProfile | None:
    raw = _MANAGER_PROFILES.get(team)
    if raw is None:
        return None
    return ManagerProfile(
        name=raw.get("name", f"Manager of {team}"),
        risk_tolerance=raw.get("risk_tolerance", 50.0),
        tactical_flexibility=raw.get("tactical_flexibility", 50.0),
        pressing_preference=raw.get("pressing_preference", 50.0),
        defensive_discipline=raw.get("defensive_discipline", 50.0),
        source=raw.get("source", ""),
        confidence=raw.get("confidence", 0.5),
    )


def manager_game_plan_modifier(team: str, base_plan: str, relative_strength: float) -> str:
    mgr = get_manager(team)
    if mgr is None:
        return base_plan

    risk = mgr.risk_tolerance
    flex = mgr.tactical_flexibility

    if base_plan == "balanced":
        if flex > 70:
            base_plan = "attacking" if risk > 65 else "counter"
        elif flex < 40:
            pass
    elif base_plan == "attacking":
        if risk < 40 and relative_strength < 1.05:
            base_plan = "balanced"
    elif base_plan == "counter":
        if risk > 70 and relative_strength > 0.95:
            base_plan = "attacking"
    elif base_plan == "low_block":
        if risk > 65 and relative_strength > 0.90:
            base_plan = "balanced"
    elif base_plan == "high_press":
        if mgr.pressing_preference < 55:
            base_plan = "balanced"

    return base_plan


def manager_adjustment_modifier(team: str) -> float:
    mgr = get_manager(team)
    if mgr is None:
        return 1.0
    disc = mgr.defensive_discipline
    return 1.0 + (disc - 50) / 200.0


def apply_manager_context_adjustment(
    team: str,
    context: str,
    plan: str,
) -> list[tuple[str, str, float]]:
    mgr = get_manager(team)
    if mgr is None:
        return []
    adjustments: list[tuple[str, str, float]] = []

    risk = mgr.risk_tolerance
    disc = mgr.defensive_discipline

    if context == "knockout":
        if risk > 70:
            adjustments.append(("manager_context", f"Bold knockout approach (risk {risk:.0f})", 0.015))
        elif risk < 45:
            adjustments.append(("manager_context", f"Cautious knockout approach (risk {risk:.0f})", -0.015))
        if disc > 70:
            adjustments.append(("manager_discipline", f"Defensive discipline in KO (disc {disc:.0f})", -0.01))
    elif context == "must_win":
        risk_boost = (risk - 50) / 100.0 * 0.03
        if risk_boost > 0.005:
            adjustments.append(("manager_context", f"Must-win aggression (risk {risk:.0f})", risk_boost))
    elif context == "gd_chase":
        if risk > 55:
            adjustments.append(("manager_context", f"GD chase risk-taking (risk {risk:.0f})", 0.02))
        else:
            adjustments.append(("manager_context", f"GD chase controlled (risk {risk:.0f})", 0.01))

    return adjustments
