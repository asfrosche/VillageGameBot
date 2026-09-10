"""V6 Compact Evaluation — Run tuned V6 engine with concise output.

Usage:
    python -m fifa_data.evaluation.v6_eval [--sims N] [--csv FILE]
"""
from __future__ import annotations

import argparse
import csv
import json
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


# ── Calibration constants (from run_evaluation.py) ──────────────
DRAW_CALIBRATION = 1.18
DRAW_THRESHOLD = 0.82
AWAY_XG_DAMPEN = 0.97
HOST_ADVANTAGE = {"United States", "Mexico", "Canada"}
HOST_ADVANTAGE_FACTOR = 0.08

ET_LAMBDA_SCALE = 0.30
PEN_BASE = 0.50
PEN_ELO_SCALE = 0.0005
MAX_GOALS_KO = 9


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


import math


def _poisson_exact_hda(xg_h: float, xg_a: float, max_goals: int = 9) -> dict:
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
    prob = PEN_BASE + diff * PEN_ELO_SCALE * 10
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
    }


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


def _actual_result(hg, ag):
    if hg > ag:
        return "H"
    elif ag > hg:
        return "A"
    return "D"


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


def run_v6_eval(n_sims: int = 1000, csv_path: str | None = None):
    matches = _load_completed_matches()
    update_elo_from_matches(TEAM_METRICS)
    tfs = TournamentFormService(TEAM_METRICS)
    tfs.compute()
    tournament_form = tfs.get_all_forms()

    v3 = V3DynamicEngine(
        data_dir=FIFA_DATA, team_metrics=TEAM_METRICS,
        tournament_form=tournament_form,
    )

    results = []
    t0 = time.time()

    for idx, m in enumerate(matches):
        home, away = m["home"], m["away"]
        stage = m["stage"]
        ko = _is_knockout(stage)

        try:
            s1 = v3.get_team_strength(home, is_knockout=ko)
            s2 = v3.get_team_strength(away, is_knockout=ko)
            xg_h, xg_a = v3.expected_goals(s1, s2)
            if home in HOST_ADVANTAGE:
                xg_h *= (1.0 + HOST_ADVANTAGE_FACTOR)
            if away in HOST_ADVANTAGE:
                xg_a *= (1.0 + HOST_ADVANTAGE_FACTOR)
            xg_a *= AWAY_XG_DAMPEN
        except Exception:
            continue

        if ko:
            exact = _poisson_exact_knockout(xg_h, xg_a, TEAM_METRICS, home, away)
        else:
            exact = _poisson_exact_hda(xg_h, xg_a)

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
        if ko:
            wid = m.get("winner_id", "")
            hid, aid = m.get("home_id", ""), m.get("away_id", "")
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
            "pred": pred,
            "correct": pred == actual,
        })

    elapsed = time.time() - t0
    total = len(results)
    correct = sum(1 for r in results if r["correct"])

    # ── Compact output ──────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  V6 COMPACT EVAL  |  {total} matches  |  {correct}/{total} ({correct/total*100:.1f}%)")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"{'='*60}\n")

    by_stage = defaultdict(lambda: [0, 0])
    for r in results:
        cat = _stage_cat(r["stage"])
        by_stage[cat][0] += 1
        if r["correct"]:
            by_stage[cat][1] += 1

    print(f"  {'Stage':<16} {'Correct':<12} {'%':>6}")
    print(f"  {'-'*34}")
    for cat in ["Group Stage", "Round of 32", "Round of 16", "Quarterfinals", "Semifinals", "Final", "Third Place"]:
        if cat in by_stage:
            t, c = by_stage[cat]
            print(f"  {cat:<16} {c}/{t:<8} {c/t*100:>5.1f}%")
    print(f"  {'-'*34}")
    print(f"  {'TOTAL':<16} {correct}/{total:<8} {correct/total*100:>5.1f}%")

    # xG error
    xg_err = sum(abs(r["xg_home"] - int(r["actual_score"].split("-")[0]))
                 + abs(r["xg_away"] - int(r["actual_score"].split("-")[1]))
                 for r in results) / (2 * total) if total else 0
    print(f"\n  Mean xG error: {xg_err:.3f}")

    # Wrong predictions (compact list)
    wrong = [r for r in results if not r["correct"]]
    if wrong:
        print(f"\n  Wrong predictions ({len(wrong)}):")
        for r in wrong:
            s = r["actual_score"]
            print(f"    {r['home']:<18} {s:<6} {r['away']:<18}  pred={r['pred']} act={r['actual']}  "
                  f"H{r['hw_pct']:.0f} D{r['dr_pct']:.0f} A{r['aw_pct']:.0f}")

    if csv_path:
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        fields = [
            "date", "stage", "group", "home", "away", "actual_score",
            "actual", "hw_pct", "dr_pct", "aw_pct",
            "xg_home", "xg_away", "pred", "correct",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(results)
        print(f"\n  CSV saved: {csv_path}")

    print()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V6 Compact Evaluation")
    parser.add_argument("--sims", type=int, default=1000, help="Simulations per match (default: 1000)")
    parser.add_argument("--csv", type=str, default=None, help="CSV output path")
    args = parser.parse_args()
    run_v6_eval(n_sims=args.sims, csv_path=args.csv)
