from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from ._match_config import MATCHES_TEAM_MAP

HERE = Path(__file__).resolve().parents[1]


class TournamentFormService:
    """Computes a per-team Tournament Form bonus based on completed match
    performance residuals.

    Effective Rating = Base Rating + Tournament Form.

    Tournament Form is rebuilt from scratch every time completed match data
    changes.  It is cached to disk so replay only happens when necessary.
    """

    def __init__(
        self,
        team_metrics: dict[str, dict[str, float]],
        matches_file: str | os.PathLike[str] | None = None,
        cache_file: str | os.PathLike[str] | None = None,
        learning_rate: float = 0.05,
        form_cap: float = 4.0,
    ) -> None:
        self._team_metrics = team_metrics
        self._matches_file = Path(matches_file) if matches_file else HERE / "data" / "matches.json"
        self._cache_file = Path(cache_file) if cache_file else HERE / "data" / "tournament_form_cache.json"
        self._learning_rate = learning_rate
        self._form_cap = form_cap
        self._form: dict[str, float] = {}
        self._debug: bool = False
        self._debug_log: list[str] = []

    # ── Public API ────────────────────────────────────────────────

    def compute(self, force: bool = False) -> None:
        if not force and self._cache_is_valid():
            self._form = self._load_cache()
            return

        matches = self._load_matches()
        completed = matches.get("completed", [])
        completed.sort(key=lambda m: m.get("date", ""))

        self._form = {team: 0.0 for team in self._team_metrics}
        self._debug_log.clear()

        for match in completed:
            home_name = MATCHES_TEAM_MAP.get(match["home"]["name"], match["home"]["name"])
            away_name = MATCHES_TEAM_MAP.get(match["away"]["name"], match["away"]["name"])
            if home_name not in self._form or away_name not in self._form:
                continue

            actual_h = match["home"]["score"]
            actual_a = match["away"]["score"]
            if actual_h is None or actual_a is None:
                continue

            self._replay_match(home_name, away_name, actual_h, actual_a)

        self._save_cache(completed)

    def get_form(self, team: str) -> float:
        return self._form.get(team, 0.0)

    def get_all_forms(self) -> dict[str, float]:
        return dict(self._form)

    def effective_rating(self, team: str) -> float:
        """Base (ELO+PELE)/2 + Tournament Form (for V1-style engines)."""
        base = self._base_rating(team)
        return base + self._form.get(team, 0.0)

    def effective_multiplier(self, team: str) -> float:
        """Multiplier ≈ 1.0 + form/1500 (for V2+ player-attribute engines)."""
        return 1.0 + self._form.get(team, 0.0) / 1500.0

    def clear_cache(self) -> None:
        if self._cache_file.exists():
            self._cache_file.unlink()

    def set_debug(self, enabled: bool = True) -> None:
        self._debug = enabled

    def get_debug_log(self) -> list[str]:
        return list(self._debug_log)

    # ── Internal helpers ──────────────────────────────────────────

    def _base_rating(self, team: str) -> float:
        m = self._team_metrics.get(team)
        if not m:
            return 1500.0
        return (float(m.get("ELO", 1500)) + float(m.get("PELE", 1500))) / 2.0

    def _expected_goals(self, rating_a: float, rating_b: float) -> tuple[float, float]:
        delta = rating_a - rating_b
        upset = max(0.4, min(1.6, 1.0 + delta / 800.0))
        lam1 = 1.1 * upset
        lam2 = max(0.05, 1.1 * max(0.20, 1.5 - 0.5 * upset))
        return lam1, lam2

    def _replay_match(
        self, home: str, away: str, actual_h: int, actual_a: int,
    ) -> None:
        home_rating = self._base_rating(home) + self._form.get(home, 0.0)
        away_rating = self._base_rating(away) + self._form.get(away, 0.0)

        exp_h, exp_a = self._expected_goals(home_rating, away_rating)
        exp_gd = exp_h - exp_a
        actual_gd = actual_h - actual_a
        residual = actual_gd - exp_gd

        # ---- weights ----

        opp_weight_home = max(0.5, away_rating / 1500.0)
        opp_weight_away = max(0.5, home_rating / 1500.0)

        gd_mag = abs(actual_gd)
        if gd_mag <= 1:
            gd_weight = 1.0
        elif gd_mag == 2:
            gd_weight = 1.20
        elif gd_mag == 3:
            gd_weight = 1.35
        else:
            gd_weight = 1.50

        home_delta = residual * opp_weight_home * gd_weight * self._learning_rate
        away_residual = -residual
        away_delta = away_residual * opp_weight_away * gd_weight * self._learning_rate

        self._form[home] = max(-self._form_cap, min(self._form_cap, self._form[home] + home_delta))
        self._form[away] = max(-self._form_cap, min(self._form_cap, self._form[away] + away_delta))

        if self._debug:
            self._debug_log.append(
                f"{home:20s} vs {away:20s}  "
                f"Exp {exp_h:.2f}-{exp_a:.2f}  "
                f"Act {actual_h}-{actual_a}  "
                f"R {residual:+.2f}  "
                f"OppW {opp_weight_home:.3f}/{opp_weight_away:.3f}  "
                f"GDW {gd_weight:.2f}  "
                f"Δ {home:20s} {home_delta:+.4f}  {away:20s} {away_delta:+.4f}"
            )

    # ── Cache ─────────────────────────────────────────────────────

    def _cache_path(self) -> str:
        return str(self._cache_file)

    def _cache_data(self, completed: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "match_count": len(completed),
            "match_ids": [m.get("id") for m in completed],
            "form": self._form,
        }

    def _cache_is_valid(self) -> bool:
        if not self._cache_file.exists():
            return False
        try:
            cached = json.loads(self._cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        matches = self._load_matches()
        completed = matches.get("completed", [])
        if cached.get("match_count") != len(completed):
            return False
        cached_ids = cached.get("match_ids", [])
        for m in completed:
            if m.get("id") not in cached_ids:
                return False
        return True

    def _load_cache(self) -> dict[str, float]:
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            return data.get("form", {})
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self, completed: list[dict[str, Any]]) -> None:
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(
                json.dumps(self._cache_data(completed), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _load_matches(self) -> dict[str, Any]:
        if self._matches_file.exists():
            return json.loads(self._matches_file.read_text(encoding="utf-8"))
        return {"completed": []}
