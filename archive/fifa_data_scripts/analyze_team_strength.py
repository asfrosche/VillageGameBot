#!/usr/bin/env python3
"""Analyze team strength distribution across all 48 World Cup teams.

Outputs V2 base ratings and V3 adjusted ratings in sorted tables.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from may.fifa_data.models.team_strength import build_team_strength
from may.fifa_data.services.v2_data_loader import load_v2_squads


def rating_to_tier(rating: float) -> str:
    if rating >= 82:
        return "ELITE"
    if rating >= 78:
        return "STRONG"
    if rating >= 74:
        return "GOOD"
    if rating >= 70:
        return "AVERAGE"
    return "WEAK"


def main():
    squads = load_v2_squads(data_dir=HERE)

    rows = []
    for team_name in sorted(squads.keys()):
        squad = squads[team_name]
        ts = build_team_strength(team_name, squad.current_starting_xi, squad.formation)
        overall_v2 = round(
            (ts.attack_rating * 0.25
             + ts.midfield_rating * 0.25
             + ts.defense_rating * 0.25
             + ts.goalkeeper_rating * 0.25), 1)
        rows.append({
            "team": team_name,
            "attack": ts.attack_rating,
            "midfield": ts.midfield_rating,
            "defense": ts.defense_rating,
            "gk": ts.goalkeeper_rating,
            "overall": overall_v2,
            "tier": rating_to_tier(overall_v2),
        })

    rows.sort(key=lambda r: r["overall"], reverse=True)

    print(f"\n{'=' * 90}")
    print("  V2 TEAM STRENGTH DISTRIBUTION (48 World Cup Teams)")
    print(f"{'=' * 90}")
    print(f"  {'Rank':<5} {'Team':<28} {'ATK':<8} {'MID':<8} {'DEF':<8} {'GK':<8} {'OVR':<8} {'TIER':<10}")
    print(f"  {'-' * 5} {'-' * 28} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 10}")

    for i, r in enumerate(rows, 1):
        print(f"  {i:<5} {r['team']:<28} {r['attack']:<8.1f} {r['midfield']:<8.1f} {r['defense']:<8.1f} {r['gk']:<8.1f} {r['overall']:<8.1f} {r['tier']:<10}")

    print(f"\n{'=' * 90}")
    print("  TOP 10")
    print(f"{'=' * 90}")
    for r in rows[:10]:
        print(f"  {r['team']:<28} OVR={r['overall']:<6.1f} A={r['attack']:<6.1f} M={r['midfield']:<6.1f} D={r['defense']:<6.1f} GK={r['gk']:<6.1f} [{r['tier']}]")

    print(f"\n{'=' * 90}")
    print("  MIDDLE 10")
    print(f"{'=' * 90}")
    for r in rows[19:29]:
        print(f"  {r['team']:<28} OVR={r['overall']:<6.1f} A={r['attack']:<6.1f} M={r['midfield']:<6.1f} D={r['defense']:<6.1f} GK={r['gk']:<6.1f} [{r['tier']}]")

    print(f"\n{'=' * 90}")
    print("  BOTTOM 10")
    print(f"{'=' * 90}")
    for r in rows[-10:]:
        print(f"  {r['team']:<28} OVR={r['overall']:<6.1f} A={r['attack']:<6.1f} M={r['midfield']:<6.1f} D={r['defense']:<6.1f} GK={r['gk']:<6.1f} [{r['tier']}]")

    # Summary stats
    overalls = [r["overall"] for r in rows]
    print(f"\n{'=' * 90}")
    print("  DISTRIBUTION SUMMARY")
    print(f"{'=' * 90}")
    print(f"  Min OVR: {min(overalls):.1f}  Max OVR: {max(overalls):.1f}  Mean OVR: {sum(overalls)/len(overalls):.1f}")
    print(f"  Range: {max(overalls) - min(overalls):.1f} points")
    print(f"  Std Dev: {__import__('statistics').stdev(overalls):.1f}")

    tiers = {}
    for r in rows:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    for t in ["ELITE", "STRONG", "GOOD", "AVERAGE", "WEAK"]:
        if t in tiers:
            print(f"  {t}: {tiers[t]} teams")

    # Top 5 gaps
    print(f"\n  Gap 1st-5th: {overalls[0] - overalls[4]:.1f}")
    print(f"  Gap 5th-10th: {overalls[4] - overalls[9]:.1f}")
    print(f"  Gap 10th-20th: {overalls[9] - overalls[19]:.1f}")
    print(f"  Gap 20th-30th: {overalls[19] - overalls[29]:.1f}")
    print(f"  Gap 30th-48th: {overalls[29] - overalls[-1]:.1f}")


if __name__ == "__main__":
    main()
