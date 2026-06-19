# Fantasy service for FIFA World Cup draft - fetches and matches player data from play.fifa.com
# Provides points, squads, and scouting bonus calculations for drafted teams.

import aiohttp
import asyncio
import difflib
import json
import os
import re
import unicodedata


PLAYERS_URL = "https://play.fifa.com/json/fantasy/players.json"
SQUADS_URL = "https://play.fifa.com/json/fantasy/squads.json"
CACHE_TTL = 120

FIFA_POSITION_MAP = {
    "1": "GK", "2": "DEF", "3": "MID", "4": "FWD",
}

ALIASES = {
    "kyllian mbappe": "Kylian Mbappé",
    "christiano ronaldo": "Cristiano Ronaldo",
    "vini jr": "Vinícius Júnior",
    "t curtois": "Thibaut Courtois",
    "f valverde": "Federico Valverde",
    "de jong": "Frenkie de Jong",
    "joao cancelo": "João Cancelo",
    "raphinha": "Raphinha",
    "pedri": "Pedri",
    "rodri": "Rodri",
    "nuno mendez": "Nuno Mendes",
    "raul jiminez": "Raúl Jiménez",
    "bruno fernandez": "Bruno Fernandes",
    "c pulisic": "Christian Pulisic",
    "i saibari": "Ismael Saibari",
    "nico tagliafico": "Nicolás Tagliafico",
    "j van hecke": "Jan Paul van Hecke",
    "victor gyokeres": "Viktor Gyökeres",
    "a isak": "Alexander Isak",
    "pedro gonzalez lopez pedri": "Pedri",
    "rodrigo hernandez cascante rodri": "Rodri",
    "gabriel": "Gabriel Magalhães",
    "martin odegaard": "Martin Ødegaard",
    "israel reyes romero": "Israel Reyes",
}


def norm(s):
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.replace(".", " ").replace("-", " ").replace("'", " ")
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _alias_resolve(name):
    key = norm(name)
    if key in ALIASES:
        return ALIASES[key]
    return name


class FantasyService:
    def __init__(self):
        self._players = None
        self._squads = None
        self._cache_time = 0

    async def fetch_data(self, local_dir=None, force=False):
        loop = asyncio.get_event_loop()
        now = loop.time()
        if not force and self._players is not None and now - self._cache_time < CACHE_TTL:
            return self._players, self._squads

        if local_dir and not force:
            players_file = os.path.join(local_dir, "data", "players.json")
            squads_file = os.path.join(local_dir, "data", "squads.json")
            if os.path.exists(players_file):
                with open(players_file, "r", encoding="utf-8") as f:
                    self._players = json.load(f)
                if os.path.exists(squads_file):
                    with open(squads_file, "r", encoding="utf-8") as f:
                        squads_raw = json.load(f)
                    self._squads = {s["id"]: s for s in squads_raw}
                self._cache_time = now
                return self._players, self._squads

        async with aiohttp.ClientSession() as session:
            async with session.get(PLAYERS_URL) as r:
                self._players = await r.json()
            async with session.get(SQUADS_URL) as r:
                squads_raw = await r.json()

        self._squads = {s["id"]: s for s in squads_raw}
        self._cache_time = now
        return self._players, self._squads

    def get_player_squad(self, squad_id):
        if self._squads is None:
            return None
        return self._squads.get(squad_id)

    def get_player_points(self, player):
        if player is None:
            return 0, 0, {}
        stats = player.get("stats", {})
        total = stats.get("totalPoints", 0)
        last = stats.get("lastRoundPoints", 0)
        round_pts = stats.get("roundPoints", {})
        return total, last, round_pts

    def get_games_played(self, player):
        if player is None:
            return 0
        stats = player.get("stats", {})
        round_pts = stats.get("roundPoints", {})
        return len(round_pts)

    def get_scouting_bonus(self, player):
        if player is None:
            return 0, {}
        stats = player.get("stats", {})
        raw = stats.get("roundPoints", {})
        round_pts = raw if isinstance(raw, dict) else {}
        rounds_sel = player.get("roundsSelected", {})
        breakdown = {}
        total = 0
        for rnd, pts in round_pts.items():
            if pts > 4 and float(rounds_sel.get(rnd, 100)) < 5:
                breakdown[rnd] = {"pts": pts, "ownership": rounds_sel.get(rnd)}
                total += 2
        return total, breakdown

    def match_player(self, name, fifa_id=None, squad_id=None, position=None):
        if fifa_id is not None and self._players is not None:
            for p in self._players:
                if p["id"] == fifa_id:
                    return p

        # Build squad_id to country mapping for country-based filtering
        squad_country_map = {}
        if self._squads:
            for sid, s in self._squads.items():
                squad_country_map[sid] = s.get("name", "")

        q = norm(name)
        resolved = _alias_resolve(name)
        rq = norm(resolved)

        if self._players is None:
            return None

        best = None
        best_score = 0

        for p in self._players:
            known = p.get("knownName") or ""
            full = norm(f"{p['firstName']} {p['lastName']}")
            kn = norm(known)
            fn = norm(p["firstName"])
            ln = norm(p["lastName"])

            scores = []

            # Position match boost
            if position and p.get("position") == position:
                scores.append((10, "position_match"))

            # Squad/country match boost (if we have draft country info)
            if squad_id and p.get("squadId") == squad_id:
                scores.append((10, "squad_match"))
            elif squad_country_map and p.get("squadId") in squad_country_map:
                # Check if draft country matches player's squad country
                player_squad_country = squad_country_map.get(p.get("squadId"), "")
                if player_squad_country and q and player_squad_country.lower() in q:
                    scores.append((15, "country_in_query"))

            if full == rq or kn == rq:
                scores.append((100, "alias_exact"))

            if full == q or kn == q:
                scores.append((99, "exact"))

            if known and q == kn:
                scores.append((98, "known_exact"))

            if q in full or full in q:
                scores.append((70, "substr_full"))
            if kn and (q in kn or kn in q):
                scores.append((68, "substr_known"))
            if fn and q in fn:
                scores.append((60, "substr_first"))
            if ln and q in ln:
                scores.append((60, "substr_last"))

            q_words = [w for w in q.split() if len(w) >= 2]
            if len(q_words) >= 2:
                if q_words[-1] == ln:
                    scores.append((85, "word_last"))
                if len(q_words) >= 2 and q_words[-1] == ln and (fn.startswith(q_words[0]) or q_words[0] == fn):
                    scores.append((95, "word_first_last"))
                for w in q_words:
                    if w == ln:
                        scores.append((80, "word_last"))
                    if fn and w == fn:
                        scores.append((80, "word_first"))

            if len(q) >= 4:
                if q in fn or q in ln:
                    scores.append((65, "substr_name_part"))

            display = norm(f"{p['firstName']} {p['lastName']}")
            ratio = difflib.SequenceMatcher(None, q, display).ratio()
            if ratio > 0.85:
                scores.append((int(ratio * 50), "fuzzy"))
            if known:
                kratio = difflib.SequenceMatcher(None, q, kn).ratio()
                if kratio > 0.85:
                    scores.append((int(kratio * 50), "fuzzy_known"))

            if scores:
                score = max(s[0] for s in scores)
                if score > best_score:
                    best_score = score
                    best = p

        if best is not None and best_score >= 50:
            return best
        return None

    def resolve_players(self, draft_players):
        players, squads = None, None
        for dp in draft_players:
            if self._players is None:
                asyncio.create_task(self.fetch_data())
                break
        if self._players is not None:
            players, squads = self._players, self._squads
        results = []
        for dp in draft_players:
            # Derive squad_id from draft country if we have it
            squad_id = None
            if self._squads and "country" in dp:
                for sid, s in self._squads.items():
                    if s.get("name", "").lower() == dp["country"].lower():
                        squad_id = sid
                        break
            match = self.match_player(dp["name"], fifa_id=dp.get("fifa_id"), squad_id=squad_id, position=dp.get("position"))
            total, last, round_pts = self.get_player_points(match)
            gp = self.get_games_played(match)
            squad_name = None
            if match:
                sq = self.get_player_squad(match.get("squadId"))
                if sq:
                    squad_name = sq.get("name")
            scouting_bonus, _ = self.get_scouting_bonus(match)
            results.append({
                **dp,
                "match": match,
                "total_points": total,
                "scouting_bonus": scouting_bonus,
                "net_points": total - scouting_bonus,
                "last_round_points": last,
                "round_points": round_pts,
                "games_played": gp,
                "squad_name": squad_name,
            })
        return results

    def get_standings(self, draft_data, guild=None):
        teams = {}
        for uid_str, team in draft_data["teams"].items():
            uid = int(uid_str)
            resolved = self.resolve_players(team["players"])
            net = sum(r["net_points"] for r in resolved)
            gross = sum(r["total_points"] for r in resolved)
            name = None
            if guild:
                member = guild.get_member(uid)
                if member:
                    name = member.display_name
            if not name:
                name = f"<@{uid}>"
            teams[uid] = {
                "name": name,
                "net_points": net,
                "total_points": gross,
                "scouting_points": gross - net,
                "players": resolved,
                "pick_count": len(resolved),
            }
        standings = sorted(teams.values(), key=lambda x: x["net_points"], reverse=True)
        return standings

    def get_top_drafted_players(self, draft_data, limit=10):
        all_players = []
        for team in draft_data["teams"].values():
            all_players.extend(team["players"])
        resolved = self.resolve_players(all_players)
        resolved.sort(key=lambda x: x["net_points"], reverse=True)
        return resolved[:limit]
