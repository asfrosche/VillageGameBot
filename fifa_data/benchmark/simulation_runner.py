"""V5 Benchmark - Simulation Runner.

Runs V5 simulations for all matches and captures detailed predictions.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIFA_DATA = HERE.parent

from fifa_data.services.simulation_service import (
    TEAM_METRICS, GROUPS,
    _load_worldcup_data, update_elo_from_matches,
)
from fifa_data.services._match_config import MATCHES_TEAM_MAP
from fifa_data.engines.v5_match_state_engine import V5MatchStateEngine
from fifa_data.services.tournament_form_service import TournamentFormService


def simulate_all_matches(
    real_matches: list[dict],
    groups: dict[str, list[str]],
    team_metrics: dict,
    verbose: bool = True,
) -> list[dict]:
    """Run V5 simulations for all matches.

    For each real match, runs the V5 engine to produce predictions.
    Returns list of dicts with simulation results.
    """
    update_elo_from_matches(TEAM_METRICS)
    tfs = TournamentFormService(TEAM_METRICS)
    tfs.compute()
    tournament_form = tfs.get_all_forms()

    engine = V5MatchStateEngine(
        data_dir=FIFA_DATA,
        team_metrics=TEAM_METRICS,
        tournament_form=tournament_form,
    )

    results = []
    total = len(real_matches)

    for idx, match in enumerate(real_matches):
        home = match["home_name"]
        away = match["away_name"]
        stage = match["stage"]
        is_knockout = "round" in stage.lower() or "quarter" in stage.lower() or \
                      "semi" in stage.lower() or "final" in stage.lower() or \
                      "third" in stage.lower()

        if verbose and (idx + 1) % 10 == 0:
            print(f"  Simulating match {idx+1}/{total}: {home} vs {away}")

        try:
            if is_knockout:
                sim_result, state, events = engine.simulate_match_detailed(
                    home, away, can_draw=False
                )
            else:
                sim_result, state, events = engine.simulate_match_detailed(
                    home, away, can_draw=True
                )

            predicted_home_goals, predicted_away_goals = sim_result

            total_xg_a = sum(
                ps.xg for ps in state.phase_stats_a.values()
            )
            total_xg_b = sum(
                ps.xg for ps in state.phase_stats_b.values()
            )

            total_shots_a = sum(
                ps.shots for ps in state.phase_stats_a.values()
            )
            total_shots_b = sum(
                ps.shots for ps in state.phase_stats_b.values()
            )

            total_sot_a = sum(
                ps.shots_on_target for ps in state.phase_stats_a.values()
            )
            total_sot_b = sum(
                ps.shots_on_target for ps in state.phase_stats_b.values()
            )

            total_attacks_a = sum(
                ps.attacks for ps in state.phase_stats_a.values()
            )
            total_attacks_b = sum(
                ps.attacks for ps in state.phase_stats_b.values()
            )

            total_da_a = sum(
                ps.dangerous_attacks for ps in state.phase_stats_a.values()
            )
            total_da_b = sum(
                ps.dangerous_attacks for ps in state.phase_stats_b.values()
            )

            total_corners_a = sum(
                ps.corners for ps in state.phase_stats_a.values()
            )
            total_corners_b = sum(
                ps.corners for ps in state.phase_stats_b.values()
            )

            total_yellows_a = sum(
                ps.yellow_cards for ps in state.phase_stats_a.values()
            )
            total_yellows_b = sum(
                ps.yellow_cards for ps in state.phase_stats_b.values()
            )
            total_reds_a = state.red_card_count_a
            total_reds_b = state.red_card_count_b

            total_poss_a = state.total_possession_a
            total_poss_b = state.total_possession_b
            total_poss = total_poss_a + total_poss_b
            if total_poss > 0:
                possession_a = (total_poss_a / total_poss) * 100
                possession_b = (total_poss_b / total_poss) * 100
            else:
                possession_a = 50.0
                possession_b = 50.0

            ppda_a = total_attacks_a / max(total_xg_a, 0.01) if total_xg_a > 0 else 20.0
            ppda_b = total_attacks_b / max(total_xg_b, 0.01) if total_xg_b > 0 else 20.0

            predicted_winner = home if predicted_home_goals > predicted_away_goals else (
                away if predicted_away_goals > predicted_home_goals else "Draw"
            )

            actual_winner = "Draw"
            if match["home_goals"] > match["away_goals"]:
                actual_winner = home
            elif match["away_goals"] > match["home_goals"]:
                actual_winner = away

            tactical_report = engine._v4.last_tactical_report
            tactical_summary = ""
            game_plan_a = state.game_plan_a
            game_plan_b = state.game_plan_b
            if tactical_report:
                tactical_summary = getattr(tactical_report, "summary", "")

            top_performers = []
            if state.team_a_players or state.team_b_players:
                all_players = []
                for pname, ps in state.team_a_players.items():
                    all_players.append({
                        "name": pname, "team": home,
                        "rating": ps.match_rating, "goals": ps.goals,
                        "assists": ps.assists, "shots": ps.shots,
                    })
                for pname, ps in state.team_b_players.items():
                    all_players.append({
                        "name": pname, "team": away,
                        "rating": ps.match_rating, "goals": ps.goals,
                        "assists": ps.assists, "shots": ps.shots,
                    })
                all_players.sort(key=lambda x: x["rating"], reverse=True)
                top_performers = all_players[:3]

            most_likely_score = f"{max(0, round(total_xg_a))}-{max(0, round(total_xg_b))}"

            shots_xg_ratio_a = total_xg_a / max(total_shots_a, 1)
            shots_xg_ratio_b = total_xg_b / max(total_shots_b, 1)

            results.append({
                "home": home,
                "away": away,
                "stage": stage,
                "group": match.get("group", ""),
                "date": match.get("date", ""),
                "predicted_home_goals": predicted_home_goals,
                "predicted_away_goals": predicted_away_goals,
                "predicted_winner": predicted_winner,
                "actual_home_goals": match["home_goals"],
                "actual_away_goals": match["away_goals"],
                "actual_winner": actual_winner,
                "predicted_xg_home": round(total_xg_a, 3),
                "predicted_xg_away": round(total_xg_b, 3),
                "predicted_possession_home": round(possession_a, 1),
                "predicted_possession_away": round(possession_b, 1),
                "predicted_shots_home": total_shots_a,
                "predicted_shots_away": total_shots_b,
                "predicted_sot_home": total_sot_a,
                "predicted_sot_away": total_sot_b,
                "predicted_attacks_home": total_attacks_a,
                "predicted_attacks_away": total_attacks_b,
                "predicted_da_home": total_da_a,
                "predicted_da_away": total_da_b,
                "predicted_corners_home": total_corners_a,
                "predicted_corners_away": total_corners_b,
                "predicted_yellows_home": total_yellows_a,
                "predicted_yellows_away": total_yellows_b,
                "predicted_reds_home": total_reds_a,
                "predicted_reds_away": total_reds_b,
                "predicted_ppda_home": round(ppda_a, 2),
                "predicted_ppda_away": round(ppda_b, 2),
                "game_plan_home": game_plan_a,
                "game_plan_away": game_plan_b,
                "tactical_summary": tactical_summary,
                "top_performers": top_performers,
                "most_likely_score": most_likely_score,
                "xg_per_shot_home": round(shots_xg_ratio_a, 3),
                "xg_per_shot_away": round(shots_xg_ratio_b, 3),
                "home_energy_avg": round(state.get_team_energy_avg(home), 1),
                "away_energy_avg": round(state.get_team_energy_avg(away), 1),
                "is_extra_time": state.is_extra_time,
                "is_penalty_shootout": state.is_penalty_shootout,
                "total_events": len(events),
                "real_xg_home": match.get("real_xg_home"),
                "real_xg_away": match.get("real_xg_away"),
                "real_shots_home": match.get("real_shots_home"),
                "real_shots_away": match.get("real_shots_away"),
                "real_sot_home": match.get("real_sot_home"),
                "real_sot_away": match.get("real_sot_away"),
                "real_possession_home": match.get("real_possession_home"),
                "real_possession_away": match.get("real_possession_away"),
                "real_corners_home": match.get("real_corners_home"),
                "real_corners_away": match.get("real_corners_away"),
                "real_yellows_home": match.get("real_yellows_home"),
                "real_yellows_away": match.get("real_yellows_away"),
                "real_reds_home": match.get("real_reds_home"),
                "real_reds_away": match.get("real_reds_away"),
                "real_ppda_home": match.get("real_ppda_home"),
                "real_ppda_away": match.get("real_ppda_away"),
            })

        except Exception as e:
            if verbose:
                print(f"  ERROR simulating {home} vs {away}: {e}")
            results.append({
                "home": home,
                "away": away,
                "stage": stage,
                "group": match.get("group", ""),
                "date": match.get("date", ""),
                "error": str(e),
            })

    return results
