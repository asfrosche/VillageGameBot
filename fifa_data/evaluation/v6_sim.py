"""V6 Single Match Simulation — Simulate one match between two teams.

Usage:
    python -m fifa_data.evaluation.v6_sim "Argentina" "England" [--knockout] [--sims N] [--detail]
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
FIFA_DATA = HERE.parent
sys.path.insert(0, str(FIFA_DATA.parent))

from fifa_data.services.simulation_service import TEAM_METRICS, update_elo_from_matches
from fifa_data.services._match_config import MATCHES_TEAM_MAP
from fifa_data.services.tournament_form_service import TournamentFormService
from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine


# ── Calibration constants ──────────────────────────────────────
DRAW_CALIBRATION = 1.18
DRAW_THRESHOLD = 0.82
AWAY_XG_DAMPEN = 0.97
HOST_ADVANTAGE = {"United States", "Mexico", "Canada"}
HOST_ADVANTAGE_FACTOR = 0.08
ET_LAMBDA_SCALE = 0.30
PEN_BASE = 0.50
MAX_GOALS_KO = 9


def _poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def _poisson_exact_hda(xg_h, xg_a, max_goals=9):
    hw = dr = aw = 0.0
    for hi in range(max_goals + 1):
        ph = _poisson_pmf(hi, xg_h)
        for ai in range(max_goals + 1):
            pa = _poisson_pmf(ai, xg_a)
            j = ph * pa
            if hi > ai:
                hw += j
            elif hi == ai:
                dr += j
            else:
                aw += j
    dr_cal = dr * DRAW_CALIBRATION
    t = hw + dr_cal + aw
    return {
        "hw_pct": round(hw / t * 100, 1),
        "dr_pct": round(dr_cal / t * 100, 1),
        "aw_pct": round(aw / t * 100, 1),
    }


def _penalty_win_prob(xg_h, xg_a, team_metrics, home, away):
    diff = xg_h - xg_a
    prob = PEN_BASE + diff * 0.005
    mh = team_metrics.get(home, {})
    ma = team_metrics.get(away, {})
    elo_h = (mh.get("ELO", 1500) + mh.get("PELE", 1500)) / 2
    elo_a = (ma.get("ELO", 1500) + ma.get("PELE", 1500)) / 2
    prob += (elo_h - elo_a) * 0.0003
    return max(0.05, min(0.95, prob))


def _poisson_exact_knockout(xg_h, xg_a, team_metrics, home, away):
    hw90 = dr90 = aw90 = 0.0
    for hi in range(MAX_GOALS_KO + 1):
        ph = _poisson_pmf(hi, xg_h)
        for ai in range(MAX_GOALS_KO + 1):
            pa = _poisson_pmf(ai, xg_a)
            j = ph * pa
            if hi > ai:
                hw90 += j
            elif hi == ai:
                dr90 += j
            else:
                aw90 += j
    xg_h_et = xg_h * ET_LAMBDA_SCALE
    xg_a_et = xg_a * ET_LAMBDA_SCALE
    hw_et = dr_et = aw_et = 0.0
    for hi in range(MAX_GOALS_KO + 1):
        ph = _poisson_pmf(hi, xg_h_et)
        for ai in range(MAX_GOALS_KO + 1):
            pa = _poisson_pmf(ai, xg_a_et)
            j = ph * pa
            if hi > ai:
                hw_et += j
            elif hi == ai:
                dr_et += j
            else:
                aw_et += j
    pen_h = _penalty_win_prob(xg_h, xg_a, team_metrics, home, away)
    pen_a = 1.0 - pen_h
    total_h = hw90 + dr90 * hw_et + dr90 * dr_et * pen_h
    total_a = aw90 + dr90 * aw_et + dr90 * dr_et * pen_a
    t = total_h + total_a
    return {
        "hw_pct": round(total_h / t * 100, 1),
        "dr_pct": 0.0,
        "aw_pct": round(total_a / t * 100, 1),
        "90min_hw": round(hw90 * 100, 1),
        "90min_dr": round(dr90 * 100, 1),
        "90min_aw": round(aw90 * 100, 1),
        "et_hw": round(dr90 * hw_et * 100, 1),
        "et_dr": round(dr90 * dr_et * 100, 1),
        "et_aw": round(dr90 * aw_et * 100, 1),
        "pen_h": round(dr90 * dr_et * pen_h * 100, 1),
        "pen_a": round(dr90 * dr_et * pen_a * 100, 1),
    }


def _resolve_team(raw: str) -> str | None:
    """Fuzzy-match a team name against MATCHES_TEAM_MAP keys + GROUPS."""
    raw_lower = raw.strip().lower()
    all_names = set()
    for name in MATCHES_TEAM_MAP:
        all_names.add(name)
        all_names.add(MATCHES_TEAM_MAP[name])
    from fifa_data.services.simulation_service import GROUPS
    for teams in GROUPS.values():
        all_names.update(teams)

    for n in all_names:
        if raw_lower == n.lower():
            return n
    for n in all_names:
        if raw_lower in n.lower() or n.lower() in raw_lower:
            return n
    return None


def run_v6_sim(team_a: str, team_b: str, knockout: bool = False, n_sims: int = 1000, detail: bool = False):
    update_elo_from_matches(TEAM_METRICS)
    tfs = TournamentFormService(TEAM_METRICS)
    tfs.compute()
    tournament_form = tfs.get_all_forms()

    v3 = V3DynamicEngine(
        data_dir=FIFA_DATA, team_metrics=TEAM_METRICS,
        tournament_form=tournament_form,
    )

    ko = knockout
    try:
        s1 = v3.get_team_strength(team_a, is_knockout=ko)
        s2 = v3.get_team_strength(team_b, is_knockout=ko)
        xg_h, xg_a = v3.expected_goals(s1, s2)
        if team_a in HOST_ADVANTAGE:
            xg_h *= (1.0 + HOST_ADVANTAGE_FACTOR)
        if team_b in HOST_ADVANTAGE:
            xg_a *= (1.0 + HOST_ADVANTAGE_FACTOR)
        xg_a *= AWAY_XG_DAMPEN
    except Exception as e:
        print(f"Error computing xG: {e}")
        return

    if ko:
        exact = _poisson_exact_knockout(xg_h, xg_a, TEAM_METRICS, team_a, team_b)
    else:
        exact = _poisson_exact_hda(xg_h, xg_a)

    # Monte Carlo for score distribution
    pmf_h = [_poisson_pmf(g, xg_h) for g in range(10)]
    pmf_a = [_poisson_pmf(g, xg_a) for g in range(10)]
    import random
    score_counter = Counter()
    wins_a = wins_b = draws = 0
    for _ in range(n_sims):
        r = random.random()
        gh = 0
        cum = 0.0
        for g in range(10):
            cum += pmf_h[g]
            if r <= cum:
                gh = g
                break
        r = random.random()
        ga = 0
        cum = 0.0
        for g in range(10):
            cum += pmf_a[g]
            if r <= cum:
                ga = g
                break
        score_counter[(gh, ga)] += 1
        if gh > ga:
            wins_a += 1
        elif ga > gh:
            wins_b += 1
        else:
            draws += 1

    top_scores = score_counter.most_common(5)

    # Print
    mode = "KNOCKOUT" if ko else "GROUP"
    print(f"\n{'='*55}")
    print(f"  V6 SIM  |  {team_a} vs {team_b}  |  {mode}")
    print(f"{'='*55}")
    print(f"  xG:  {xg_h:.2f} - {xg_a:.2f}")
    if ko:
        print(f"  90min:  H {exact['90min_hw']:.0f}%  D {exact['90min_dr']:.0f}%  A {exact['90min_aw']:.0f}%")
        print(f"  ET:     H {exact['et_hw']:.1f}%  D {exact['et_dr']:.1f}%  A {exact['et_aw']:.1f}%")
        print(f"  Pen:    H {exact['pen_h']:.1f}%  A {exact['pen_a']:.1f}%")
        print(f"  FINAL:  {team_a} {exact['hw_pct']:.1f}%  |  {team_b} {exact['aw_pct']:.1f}%")
    else:
        print(f"  H {exact['hw_pct']:.1f}%  D {exact['dr_pct']:.1f}%  A {exact['aw_pct']:.1f}%")

    print(f"\n  Top scores ({n_sims} sims):")
    for (gh, ga), cnt in top_scores:
        pct = cnt / n_sims * 100
        bar = "#" * int(pct / 2)
        print(f"    {gh}-{ga}  {pct:>5.1f}%  {bar}")

    if ko:
        print(f"\n  Win {team_a}: {wins_a/n_sims*100:.1f}%  |  Win {team_b}: {wins_b/n_sims*100:.1f}%  |  Draw: {draws/n_sims*100:.1f}%")

    # Detailed V5 sim (1 run)
    if detail:
        print(f"\n{'='*55}")
        print(f"  DETAILED V5 SIM (1 run)")
        print(f"{'='*55}")
        v5 = V5MatchStateEngine(
            data_dir=FIFA_DATA, team_metrics=TEAM_METRICS,
            tournament_form=tournament_form,
        )
        try:
            score, state, events = v5.simulate_match_detailed(team_a, team_b, can_draw=not ko)
            print(f"  Score: {score[0]}-{score[1]}")
            if state.is_extra_time:
                print(f"  (Extra Time)")
            if state.is_penalty_shootout:
                print(f"  (Penalty Shootout)")
            print(f"  Possession: {state.total_possession_a:.0f}% - {state.total_possession_b:.0f}%")

            # Phase stats
            total_xg_a = sum(ps.xg for ps in state.phase_stats_a.values())
            total_xg_b = sum(ps.xg for ps in state.phase_stats_b.values())
            total_shots_a = sum(ps.shots for ps in state.phase_stats_a.values())
            total_shots_b = sum(ps.shots for ps in state.phase_stats_b.values())
            total_sot_a = sum(ps.shots_on_target for ps in state.phase_stats_a.values())
            total_sot_b = sum(ps.shots_on_target for ps in state.phase_stats_b.values())
            total_fouls_a = sum(ps.fouls for ps in state.phase_stats_a.values())
            total_fouls_b = sum(ps.fouls for ps in state.phase_stats_b.values())

            print(f"  xG:       {total_xg_a:.2f} - {total_xg_b:.2f}")
            print(f"  Shots:    {total_shots_a} - {total_shots_b}")
            print(f"  On target:{total_sot_a} - {total_sot_b}")
            print(f"  Fouls:    {total_fouls_a} - {total_fouls_b}")

            # Key events
            goals = [e for e in events if e.event_type.name == "GOAL"]
            if goals:
                print(f"\n  Goals:")
                for e in goals:
                    detail_str = e.detail if e.detail else ""
                    print(f"    {e.minute:.0f}' {e.team} - {e.player_name or '?'} {detail_str}")

            yellows = [e for e in events if e.event_type.name == "YELLOW_CARD"]
            if yellows:
                print(f"\n  Yellow cards:")
                for e in yellows:
                    print(f"    {e.minute:.0f}' {e.team} - {e.player_name or '?'}")

            reds = [e for e in events if e.event_type.name == "RED_CARD"]
            if reds:
                print(f"\n  Red cards:")
                for e in reds:
                    print(f"    {e.minute:.0f}' {e.team} - {e.player_name or '?'}")

        except Exception as e:
            print(f"  V5 detail sim failed: {e}")

    print(f"\n{'='*55}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V6 Single Match Simulation")
    parser.add_argument("team_a", help="Home / first team")
    parser.add_argument("team_b", help="Away / second team")
    parser.add_argument("--knockout", "-k", action="store_true", help="Knockout mode (no draws)")
    parser.add_argument("--sims", "-n", type=int, default=1000, help="Monte Carlo sims (default: 1000)")
    parser.add_argument("--detail", "-d", action="store_true", help="Run 1 detailed V5 sim with events")
    args = parser.parse_args()

    a = _resolve_team(args.team_a)
    b = _resolve_team(args.team_b)
    if not a:
        print(f"Unknown team: {args.team_a}")
        sys.exit(1)
    if not b:
        print(f"Unknown team: {args.team_b}")
        sys.exit(1)

    run_v6_sim(a, b, knockout=args.knockout, n_sims=args.sims, detail=args.detail)
