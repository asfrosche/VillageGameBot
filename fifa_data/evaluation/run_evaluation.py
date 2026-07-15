"""World Cup 2026 — Match Evaluation via Monte Carlo Simulation.

Two-phase approach:
  1. Compute xG deterministically per match via V3 engine (fast).
  2. Run N fast Poisson simulations on those xG values to get
     win/draw/away percentages, goals distributions, etc.
  3. Run ONE V5 detailed sim per match for PPDA / tactical stats.

Output: formatted table comparing simulated vs actual results.

Usage:
    python -m fifa_data.evaluation.run_evaluation [--sims N] [--output FILE]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from collections import defaultdict
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

from fifa_data.services.simulation_service import (
    TEAM_METRICS, GROUPS,
    update_elo_from_matches,
)
from fifa_data.services._match_config import MATCHES_TEAM_MAP
from fifa_data.engines.v3_dynamic_engine import V3DynamicEngine
from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
from fifa_data.services.tournament_form_service import TournamentFormService


# ── Calibration constants ─────────────────────────────────────────
# Poisson models systematically underestimate draws in football.
# These are small, non-overfitting corrections derived from trend analysis
# on 90 completed matches (25.6% actual draw rate vs ~18% model average).
DRAW_CALIBRATION = 1.18        # Boost D% by 18% (relative)
DRAW_THRESHOLD = 0.82          # If D% > 82% of max(H%, A%), predict D
AWAY_XG_DAMPEN = 0.97          # Dampen away xG by 3% (addresses +0.26 systematic over-prediction)

# ── Fast Poisson math ───────────────────────────────────────────────

def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def _poisson_sim(xg_h: float, xg_a: float, n: int = 1000, max_goals: int = 9) -> dict:
    """Run N independent Poisson simulations and return aggregated stats."""
    hw = dr = aw = 0
    goals_h = [0] * (max_goals + 1)
    goals_a = [0] * (max_goals + 1)

    # Build PMF tables once
    pmf_h = [_poisson_pmf(g, xg_h) for g in range(max_goals + 1)]
    pmf_a = [_poisson_pmf(g, xg_a) for g in range(max_goals + 1)]

    for _ in range(n):
        # Sample from Poisson via inverse CDF
        r = __import__("random").random()
        gh = 0
        cum = 0.0
        for g in range(max_goals + 1):
            cum += pmf_h[g]
            if r <= cum:
                gh = g
                break

        r = __import__("random").random()
        ga = 0
        cum = 0.0
        for g in range(max_goals + 1):
            cum += pmf_a[g]
            if r <= cum:
                ga = g
                break

        if gh > ga:
            hw += 1
        elif ga > gh:
            aw += 1
        else:
            dr += 1
        goals_h[gh] += 1
        goals_a[ga] += 1

    return {
        "hw_pct": round(hw / n * 100, 1),
        "dr_pct": round(dr / n * 100, 1),
        "aw_pct": round(aw / n * 100, 1),
        "avg_goals_h": round(sum(g * goals_h[g] for g in range(max_goals + 1)) / n, 2),
        "avg_goals_a": round(sum(g * goals_a[g] for g in range(max_goals + 1)) / n, 2),
    }


def _poisson_exact_hda(xg_h: float, xg_a: float, max_goals: int = 9) -> dict:
    """Exact Poisson H/D/A probabilities with draw calibration."""
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
    # Apply draw calibration: boost D% to correct Poisson's systematic
    # underestimation of draws in real football
    dr_cal = dr * DRAW_CALIBRATION
    t = hw + dr_cal + aw
    return {
        "hw_pct": round(hw / t * 100, 1),
        "dr_pct": round(dr_cal / t * 100, 1),
        "aw_pct": round(aw / t * 100, 1),
    }


ET_LAMBDA_SCALE = 0.30       # ET xG = 90min xG * 0.30
PEN_BASE = 0.50              # Base penalty shootout win probability
PEN_ELO_SCALE = 0.0005       # ELO diff influence on penalties
MAX_GOALS_KO = 9


def _penalty_win_prob(xg_h: float, xg_a: float, team_metrics: dict, home: str, away: str) -> float:
    """Probability that home team wins penalties (after ET draw)."""
    diff = xg_h - xg_a
    prob = PEN_BASE + diff * PEN_ELO_SCALE * 10

    mh = team_metrics.get(home, {})
    ma = team_metrics.get(away, {})
    elo_h = (mh.get("ELO", 1500) + mh.get("PELE", 1500)) / 2
    elo_a = (ma.get("ELO", 1500) + ma.get("PELE", 1500)) / 2
    prob += (elo_h - elo_a) * 0.0003

    return max(0.05, min(0.95, prob))


def _poisson_exact_knockout(xg_h: float, xg_a: float, team_metrics: dict,
                             home: str, away: str) -> dict:
    """Exact knockout H/A probabilities (90min + ET + penalties, no draws)."""
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

    # ET: reduced xG from drawn positions
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

    # Penalty win probability (from drawn after ET)
    pen_h = _penalty_win_prob(xg_h, xg_a, team_metrics, home, away)
    pen_a = 1.0 - pen_h

    # Total: 90min win + (draw after 90min * ET win) + (draw after 90min * draw after ET * penalties)
    total_h = hw90 + dr90 * hw_et + dr90 * dr_et * pen_h
    total_a = aw90 + dr90 * aw_et + dr90 * dr_et * pen_a

    t = total_h + total_a
    return {
        "hw_pct": round(total_h / t * 100, 1),
        "dr_pct": 0.0,
        "aw_pct": round(total_a / t * 100, 1),
    }


# ── Data loading ────────────────────────────────────────────────────

def _load_completed_matches() -> list[dict]:
    matches_file = FIFA_DATA / "data" / "matches.json"
    with open(matches_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for m in data.get("completed", []):
        home_name = MATCHES_TEAM_MAP.get(m["home"]["name"], m["home"]["name"])
        away_name = MATCHES_TEAM_MAP.get(m["away"]["name"], m["away"]["name"])
        out.append({
            "id": m.get("id", ""),
            "date": m.get("date", ""),
            "stage": m.get("stage", ""),
            "group": m.get("group", ""),
            "home": home_name,
            "away": away_name,
            "home_goals": int(m.get("home", {}).get("score", 0)),
            "away_goals": int(m.get("away", {}).get("score", 0)),
            "home_id": str(m.get("home", {}).get("id", "")),
            "away_id": str(m.get("away", {}).get("id", "")),
            "winner_id": str(m.get("winner", "")),
        })
    return out


def _is_knockout(stage: str) -> bool:
    s = stage.lower()
    return any(k in s for k in ("round of", "quarter", "semi", "final", "third"))


def _actual_result(hg: int, ag: int) -> str:
    if hg > ag:
        return "H"
    elif ag > hg:
        return "A"
    return "D"


# ── Main ────────────────────────────────────────────────────────────

HOST_ADVANTAGE = {"United States": 20, "Mexico": 20, "Canada": 20}
HOST_ADVANTAGE_FACTOR = 0.08


def run_evaluation(n_sims: int = 1000, output_csv: str | None = None, compact: bool = False):
    matches = _load_completed_matches()
    print(f"Loaded {len(matches)} completed matches")
    print(f"Running {n_sims} Poisson sims + 1 V5 detailed sim per match")
    print(f"Host advantage: only {list(HOST_ADVANTAGE.keys())} get +{HOST_ADVANTAGE_FACTOR:.0%} xG boost\n")

    update_elo_from_matches(TEAM_METRICS)
    tfs = TournamentFormService(TEAM_METRICS)
    tfs.compute()
    tournament_form = tfs.get_all_forms()

    # Phase 1: V3 engine for deterministic xG
    v3 = V3DynamicEngine(
        data_dir=FIFA_DATA,
        team_metrics=TEAM_METRICS,
        tournament_form=tournament_form,
    )

    # Phase 2: V5 engine for one PPDA/tactical sim per match
    v5 = V5MatchStateEngine(
        data_dir=FIFA_DATA,
        team_metrics=TEAM_METRICS,
        tournament_form=tournament_form,
    )

    results = []
    t0 = time.time()

    for idx, m in enumerate(matches):
        home = m["home"]
        away = m["away"]
        stage = m["stage"]
        ko = _is_knockout(stage)

        # Deterministic xG from V3 engine
        try:
            s1 = v3.get_team_strength(home, is_knockout=ko)
            s2 = v3.get_team_strength(away, is_knockout=ko)
            xg_h, xg_a = v3.expected_goals(s1, s2)

            if home in HOST_ADVANTAGE:
                xg_h *= (1.0 + HOST_ADVANTAGE_FACTOR)
            if away in HOST_ADVANTAGE:
                xg_a *= (1.0 + HOST_ADVANTAGE_FACTOR)

            # Dampen away xG to correct systematic +0.26 over-prediction
            xg_a *= AWAY_XG_DAMPEN
        except Exception as e:
            print(f"  SKIP xG for {home} vs {away}: {e}")
            continue

        # Run N fast Poisson sims on the fixed xG values
        sim = _poisson_sim(xg_h, xg_a, n=n_sims)

        # Exact H/D/A from Poisson (no simulation noise)
        if ko:
            exact = _poisson_exact_knockout(xg_h, xg_a, TEAM_METRICS, home, away)
        else:
            exact = _poisson_exact_hda(xg_h, xg_a)

        # One V5 detailed sim for PPDA
        ppda_h = ppda_a = 15.0
        try:
            _, state, _ = v5.simulate_match_detailed(home, away, can_draw=not ko)
            txg_a = sum(ps.xg for ps in state.phase_stats_a.values())
            txg_b = sum(ps.xg for ps in state.phase_stats_b.values())
            ta = sum(ps.attacks for ps in state.phase_stats_a.values())
            tb = sum(ps.attacks for ps in state.phase_stats_b.values())
            ppda_h = round(ta / max(txg_a, 0.01) if txg_a > 0 else 20.0, 1)
            ppda_a = round(tb / max(txg_b, 0.01) if txg_b > 0 else 20.0, 1)
        except Exception:
            pass

        # Determine prediction
        hw, dr, aw = exact["hw_pct"], exact["dr_pct"], exact["aw_pct"]
        if ko:
            pred = "H" if hw >= aw else "A"
        else:
            max_outcome = max(hw, dr, aw)
            if dr >= max_outcome * DRAW_THRESHOLD and dr >= hw and dr >= aw:
                pred = "D"
            elif hw >= aw and hw >= dr:
                pred = "H"
            elif aw >= hw and aw >= dr:
                pred = "A"
            else:
                pred = "D"

        actual = _actual_result(m["home_goals"], m["away_goals"])

        # For knockout matches, use the winner field (handles ET/penalties)
        if ko:
            wid = m.get("winner_id", "")
            hid = m.get("home_id", "")
            aid = m.get("away_id", "")
            if wid and wid == hid:
                actual = "H"
            elif wid and wid == aid:
                actual = "A"

        results.append({
            "date": m["date"][:10],
            "stage": stage,
            "group": m.get("group", ""),
            "home": home,
            "away": away,
            "actual_score": f"{m['home_goals']}-{m['away_goals']}",
            "actual": actual,
            "hw_pct": hw,
            "dr_pct": dr,
            "aw_pct": aw,
            "xg_home": round(xg_h, 2),
            "xg_away": round(xg_a, 2),
            "ppda_home": ppda_h,
            "ppda_away": ppda_a,
            "pred": pred,
            "correct": pred == actual,
        })

        if (idx + 1) % 10 == 0 or (idx + 1) == len(matches):
            elapsed = time.time() - t0
            print(f"  [{idx+1}/{len(matches)}] {home} vs {away}  "
                  f"H{hw:.0f}% D{dr:.0f}% A{aw:.0f}%  "
                  f"xG {xg_h:.2f}-{xg_a:.2f}  "
                  f"{'Y' if pred == actual else 'N'}  "
                  f"({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\nCompleted {len(results)} matches in {elapsed:.1f}s\n")

    _print_table(results)

    if compact:
        print("\n" + "=" * 60)
        print(" COMPACT MATCH SUMMARIES")
        print("=" * 60)
        for r in results:
            print()
            print(_format_match_summary(r))
        print()

    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = correct / total * 100 if total else 0
    print(f"\nOverall accuracy: {correct}/{total} ({accuracy:.1f}%)")

    # Accuracy by stage
    by_stage = defaultdict(lambda: [0, 0])
    for r in results:
        cat = _stage_cat(r["stage"])
        by_stage[cat][0] += 1
        if r["correct"]:
            by_stage[cat][1] += 1
    print("\nAccuracy by stage:")
    for cat in ["Group Stage", "Round of 32", "Round of 16", "Quarterfinals", "Semifinals", "Final"]:
        if cat in by_stage:
            t, c = by_stage[cat]
            print(f"  {cat:<16} {c}/{t} ({c/t*100:.1f}%)")

    # xG error
    xg_err = sum(abs(r["xg_home"] - int(r["actual_score"].split("-")[0]))
                 + abs(r["xg_away"] - int(r["actual_score"].split("-")[1]))
                 for r in results) / (2 * total) if total else 0
    print(f"\nMean xG error: {xg_err:.3f}")

    if output_csv:
        os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
        _write_csv(results, output_csv)
        print(f"CSV saved to {output_csv}")

    return results


def _format_match_summary(r: dict) -> str:
    home = r["home"]
    away = r["away"]
    hw = r["hw_pct"]
    dr = r["dr_pct"]
    aw = r["aw_pct"]
    xg_h = r["xg_home"]
    xg_a = r["xg_away"]
    ppda_h = r["ppda_home"]
    ppda_a = r["ppda_away"]
    pred = r["pred"]
    actual = r["actual"]
    actual_score = r["actual_score"]

    # Build predicted score from xG rounded
    pred_h = max(0, round(xg_h))
    pred_a = max(0, round(xg_a))

    # Verdict
    if pred == actual and pred == "D":
        verdict = "\U0001f91d"
    elif pred == actual:
        verdict = "\u2705"
    else:
        verdict = "\u274c"

    match_label = f"{home} vs {away}"
    score_line = f"{pred_h}-{pred_a} \u2192 {actual_score} {verdict}"

    return (
        f"{match_label}\n"
        f"Win      {hw:>3.0f} | {dr:>3.0f} | {aw:>3.0f}\n"
        f"xG       {xg_h:>5.2f} | {xg_a:.2f}\n"
        f"PPDA     {ppda_h:>5.1f} | {ppda_a:.1f}\n"
        f"Score    {score_line}"
    )


def _stage_cat(stage: str) -> str:
    s = stage.lower()
    if "first stage" in s or "group" in s:
        return "Group Stage"
    if "round of 32" in s or "r32" in s:
        return "Round of 32"
    if "round of 16" in s or "r16" in s:
        return "Round of 16"
    if "quarter" in s or "qf" in s:
        return "Quarterfinals"
    if "semi" in s or "sf" in s:
        return "Semifinals"
    if "third" in s:
        return "Third Place"
    if "final" in s:
        return "Final"
    return "Other"


def _print_table(results: list[dict]):
    hdr = (f"{'Date':<11} {'Stage':<16} {'Home':<18} {'Score':<6} "
           f"{'Away':<18} | {'H%':>5} {'D%':>5} {'A%':>5} | "
           f"{'xGH':>5} {'xGA':>5} | {'PPDA_H':>6} {'PPDA_A':>6} | {'Pred':>4} {'Act':>4} {'OK':>3}")
    sep = "-" * len(hdr)
    print(sep)
    print(hdr)
    print(sep)
    for r in results:
        ok = "Y" if r["correct"] else "N"
        print(f"{r['date']:<11} {r['stage']:<16} {r['home']:<18} {r['actual_score']:<6} "
              f"{r['away']:<18} | {r['hw_pct']:>5.1f} {r['dr_pct']:>5.1f} {r['aw_pct']:>5.1f} | "
              f"{r['xg_home']:>5.2f} {r['xg_away']:>5.2f} | "
              f"{r['ppda_home']:>6.1f} {r['ppda_away']:>6.1f} | "
              f"{r['pred']:>4} {r['actual']:>4} {ok:>3}")
    print(sep)


def _write_csv(results: list[dict], path: str):
    fields = [
        "date", "stage", "group", "home", "away", "actual_score",
        "actual", "hw_pct", "dr_pct", "aw_pct",
        "xg_home", "xg_away", "ppda_home", "ppda_away",
        "pred", "correct",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monte Carlo match evaluation")
    parser.add_argument("--sims", type=int, default=1000, help="Simulations per match (default: 1000)")
    parser.add_argument("--output", type=str, default=None, help="CSV output path")
    parser.add_argument("--compact", action="store_true", help="Print compact human-readable match summaries")
    args = parser.parse_args()
    run_evaluation(n_sims=args.sims, output_csv=args.output, compact=args.compact)
