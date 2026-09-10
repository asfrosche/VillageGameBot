from __future__ import annotations

from ..models.match_event import EventType, MatchEvent
from ..models.match_state import MatchState


class GameScriptService:
    def generate_match_story(self, match_state: MatchState) -> list[str]:
        paragraphs: list[str] = []
        events = sorted(match_state.events, key=lambda e: e.minute)

        if not events:
            paragraphs.append(f"{match_state.team_a} and {match_state.team_b} played out a quiet match.")
            return paragraphs

        first_goal = None
        for ev in events:
            if ev.event_type == EventType.GOAL:
                first_goal = ev
                break

        if first_goal:
            paragraphs.append(
                f"{first_goal.player_name or 'A player'} opened the scoring "
                f"for {first_goal.team} in the {int(first_goal.minute)}' minute."
            )
        else:
            if match_state.scoreline.goals_a == 0 and match_state.scoreline.goals_b == 0:
                paragraphs.append("The match ended goalless.")
            else:
                paragraphs.append("Goals were distributed across the match.")

        if match_state.scoreline.goals_a > 0 or match_state.scoreline.goals_b > 0:
            self._add_possession_insight(paragraphs, match_state)
            self._add_momentum_insight(paragraphs, match_state)
            self._add_tactical_insight(paragraphs, match_state)

        if match_state.substitutions:
            key_subs = [
                s for s in match_state.substitutions
                if s.reason in ("tactical", "injury")
            ]
            if key_subs:
                sub = key_subs[-1]
                paragraphs.append(
                    f"A {sub.reason} substitution saw {sub.player_on} replace "
                    f"{sub.player_off} for {sub.team} in the {sub.minute}'."
                )

        cards = [
            ev for ev in events
            if ev.event_type in (EventType.YELLOW_CARD, EventType.RED_CARD)
        ]
        if cards:
            reds = [c for c in cards if c.event_type == EventType.RED_CARD]
            if reds:
                paragraphs.append(
                    f"{reds[0].player_name} was sent off for {reds[0].team}, "
                    f"significantly impacting the match."
                )

        self._add_late_drama(paragraphs, events, match_state)
        self._add_summary(paragraphs, match_state)
        return paragraphs

    def _add_possession_insight(self, paragraphs: list[str], state: MatchState) -> None:
        total = state.total_possession_a + state.total_possession_b
        if total > 0:
            pct_a = (state.total_possession_a / total) * 100
            pct_b = (state.total_possession_b / total) * 100
            if abs(pct_a - pct_b) > 10:
                leader = state.team_a if pct_a > pct_b else state.team_b
                paragraphs.append(
                    f"{leader} controlled possession ({max(pct_a, pct_b):.0f}%), "
                    f"dictating the tempo of the match."
                )

    def _add_momentum_insight(self, paragraphs: list[str], state: MatchState) -> None:
        if state.momentum_a > 30:
            paragraphs.append(f"{state.team_a} carried significant attacking momentum.")
        elif state.momentum_b > 30:
            paragraphs.append(f"{state.team_b} carried significant attacking momentum.")

    def _add_tactical_insight(self, paragraphs: list[str], state: MatchState) -> None:
        if state.game_plan_history_a:
            para = f"{state.team_a} started with a {state.game_plan_a} approach"
            changes = [h for h in state.game_plan_history_a if h[0] > 0]
            if changes:
                last_change = changes[-1]
                para += f", switching to a more {last_change[1]} shape after {last_change[0]}'"
            para += "."
            paragraphs.append(para)

    def _add_late_drama(self, paragraphs: list[str], events: list[MatchEvent], state: MatchState) -> None:
        late_goals = [
            ev for ev in events
            if ev.event_type == EventType.GOAL and ev.minute >= 80
        ]
        if len(late_goals) >= 2:
            paragraphs.append("Late drama unfolded as multiple goals arrived in the closing stages.")

    def _add_summary(self, paragraphs: list[str], state: MatchState) -> None:
        total_goals = state.scoreline.goals_a + state.scoreline.goals_b
        if total_goals >= 5:
            paragraphs.append(f"A {total_goals}-goal thriller between {state.team_a} and {state.team_b}.")

    def format_timeline(self, match_state: MatchState) -> list[str]:
        events = sorted(match_state.events, key=lambda e: e.minute)
        lines: list[str] = []
        for ev in events:
            player = ev.player_name or ""
            team_label = ev.team
            if ev.event_type == EventType.GOAL:
                lines.append(f"{int(ev.minute)}' {player} scores! ({team_label})")
            elif ev.event_type == EventType.YELLOW_CARD:
                lines.append(f"{int(ev.minute)}' {player} booked ({team_label})")
            elif ev.event_type == EventType.RED_CARD:
                lines.append(f"{int(ev.minute)}' {player} SENT OFF ({team_label})")
            elif ev.event_type == EventType.SUBSTITUTION:
                on = ev.data.get("player_on", "")
                off = ev.data.get("player_off", "")
                lines.append(f"{int(ev.minute)}' SUB: {off} OFF, {on} ON ({team_label})")
            elif ev.event_type == EventType.BIG_CHANCE:
                lines.append(f"{int(ev.minute)}' {player} with a big chance ({team_label})")
            elif ev.event_type == EventType.PENALTY:
                lines.append(f"{int(ev.minute)}' PENALTY for {team_label}")
            elif ev.event_type == EventType.PENALTY_MISSED:
                lines.append(f"{int(ev.minute)}' {player} misses penalty ({team_label})")
            elif ev.event_type == EventType.TACTICAL_CHANGE:
                lines.append(f"{int(ev.minute)}' Tactical switch: {ev.detail} ({team_label})")
        return lines

    def get_top_performers(self, match_state: MatchState, top_n: int = 5) -> list[dict]:
        all_players: list[tuple[str, str, float]] = []

        for team, pool in [(match_state.team_a, match_state.team_a_players),
                            (match_state.team_b, match_state.team_b_players)]:
            for name, state in pool.items():
                score = (
                    state.match_rating
                    + state.goals * 1.5
                    + state.assists * 1.0
                    + state.shots_on_target * 0.2
                    + state.key_passes * 0.15
                    + state.tackles * 0.1
                    + state.interceptions * 0.1
                )
                all_players.append((team, name, score))

        all_players.sort(key=lambda x: x[2], reverse=True)
        result = []
        for team, name, score in all_players[:top_n]:
            state = match_state.get_player_state(team, name)
            if state:
                result.append({
                    "team": team,
                    "name": name,
                    "rating": round(score, 1),
                    "goals": state.goals,
                    "assists": state.assists,
                    "shots": state.shots,
                    "shots_on_target": state.shots_on_target,
                    "tackles": state.tackles,
                    "interceptions": state.interceptions,
                    "energy": round(state.energy, 1),
                })
        return result
