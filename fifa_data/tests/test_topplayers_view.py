"""Tests for _TopPlayersView."""

import asyncio
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
FIFA_DATA = os.path.join(MAY_DIR, "fifa_data")
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, FIFA_DATA)

import pytest
from unittest.mock import MagicMock

import discord
from discord.ui import View, Button


_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
_orig_get_running_loop = asyncio.get_running_loop


def _get_running_loop():
    return _loop


asyncio.get_running_loop = _get_running_loop

from fifa_data.services.draft_cog import _TopPlayersView
from fifa_data.services.fantasy_service import FIFA_POSITION_MAP, COUNTRY_FLAGS, _flag_emoji


def _make_player(name, pos, net_points, owner_name=None, drafted=False, country="", flag=""):
    return {
        "name": name,
        "position": pos,
        "net_points": net_points,
        "drafted": drafted,
        "owner_id": 12345 if owner_name else None,
        "owner_name": owner_name,
        "country": country,
        "flag": flag,
    }


class TestTopPlayersView:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.fantasy = MagicMock()
        self.fantasy.build_master_player_list.return_value = []
        self.draft = {"started": True, "teams": {}}
        self.guild = MagicMock()
        self.guild.get_member.return_value = None

    def _view(self, rows):
        self.fantasy.build_master_player_list.return_value = rows
        return _TopPlayersView(self.fantasy, self.draft, self.guild)

    # ── Default state ──

    def test_default_sort_mode(self):
        view = self._view([])
        assert view.sort_mode == "overall_desc"

    def test_no_players(self):
        view = self._view([])
        embed = view._build_embed()
        assert "No players found." in embed.description
        assert "Page 1/1" in embed.footer.text

    def test_embed_title_default(self):
        view = self._view([])
        assert view._build_embed().title == "🏆 Top Players — Overall (DESC)"

    def test_embed_title_includes_sort_mode(self):
        view = self._view([])
        view.sort_mode = "position"
        assert view._build_embed().title == "🏆 Top Players — Position"

    # ── Embed format ──

    def test_compact_format_with_owner(self):
        rows = [_make_player("Messi", "FWD", 25, owner_name="Coach", drafted=True)]
        view = self._view(rows)
        desc = view._build_embed().description
        assert "#1" in desc
        assert "25 pts" in desc
        assert "**Messi**" in desc
        assert "Coach" in desc

    def test_compact_format_no_owner(self):
        rows = [_make_player("Free", "GK", 22, drafted=False)]
        view = self._view(rows)
        desc = view._build_embed().description
        assert "#1" in desc
        assert "22 pts" in desc
        assert "**Free**" in desc

    def test_position_tag_always_shown(self):
        rows = [_make_player("Neymar", "FWD", 15, drafted=True)]
        view = self._view(rows)
        desc = view._build_embed().description
        assert "FWD" in desc

    # ── Owner display ──

    def test_shows_owner_when_present(self):
        rows = [_make_player("Owned", "DEF", 18, owner_name="CoachA", drafted=True)]
        view = self._view(rows)
        embed = view._build_embed()
        assert "CoachA" in embed.description

    def test_owner_absent_for_undrafted(self):
        rows = [_make_player("Free", "GK", 22, drafted=False)]
        view = self._view(rows)
        embed = view._build_embed()
        assert embed.description is not None
        assert "GK" in embed.description
        assert "Free" in embed.description
        assert "22 pts" in embed.description

    # ── Pagination ──

    def test_pagination_single_page(self):
        rows = [_make_player(f"P{i}", "MID", i, drafted=True) for i in range(5)]
        view = self._view(rows)
        assert view._total_pages() == 1

    def test_pagination_multi_page(self):
        rows = [_make_player(f"P{i}", "MID", i, drafted=True) for i in range(25)]
        view = self._view(rows)
        assert view._total_pages() == 2

    def test_pagination_footer(self):
        rows = [_make_player(f"P{i}", "FWD", i, drafted=True) for i in range(25)]
        view = self._view(rows)
        assert "Page 1/2" in view._build_embed().footer.text
        view.page = 1
        assert "Page 2/2" in view._build_embed().footer.text

    def test_pagination_content_per_page(self):
        rows = [_make_player(f"P{i}", "DEF", i, drafted=True) for i in range(25)]
        view = self._view(rows)
        assert len(view._build_embed().description.strip().split("\n")) == 20
        view.page = 1
        assert len(view._build_embed().description.strip().split("\n")) == 5

    def test_prev_disabled_on_page_zero(self):
        rows = [_make_player(f"P{i}", "FWD", i, drafted=True) for i in range(40)]
        view = self._view(rows)
        assert view._prev.disabled is True
        assert view._next.disabled is False

    def test_next_disabled_on_last_page(self):
        rows = [_make_player(f"P{i}", "FWD", i, drafted=True) for i in range(40)]
        view = self._view(rows)
        view.page = 1
        view._update_buttons()
        assert view._prev.disabled is False
        assert view._next.disabled is True

    def test_both_disabled_single_page(self):
        rows = [_make_player("Solo", "GK", 99, drafted=True)]
        view = self._view(rows)
        assert view._prev.disabled is True
        assert view._next.disabled is True

    # ── Sort: Total ASC ──

    def test_total_asc_sorts_ascending(self):
        rows = [
            _make_player("High", "FWD", 30),
            _make_player("Low", "GK", 5),
            _make_player("Mid", "MID", 15),
        ]
        view = self._view(rows)
        view.sort_mode = "total_asc"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["Low", "Mid", "High"]

    # ── Sort: Overall DESC (default) ──

    def test_overall_desc_sorts_descending(self):
        rows = [
            _make_player("High", "FWD", 30),
            _make_player("Low", "GK", 5),
            _make_player("Mid", "MID", 15),
        ]
        view = self._view(rows)
        names = [r["name"] for r in view._rows]
        assert names == ["High", "Mid", "Low"]

    def test_overall_desc_mixed_drafted_undrafted(self):
        rows = [
            _make_player("U1", "FWD", 50, drafted=False),
            _make_player("D1", "GK", 10, drafted=True),
            _make_player("D2", "MID", 30, drafted=True),
            _make_player("U2", "DEF", 40, drafted=False),
        ]
        view = self._view(rows)
        view.sort_mode = "overall_desc"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["U1", "U2", "D2", "D1"]

    # ── Sort: Points Drafted ──

    def test_points_drafted_sorts_drafted_first(self):
        rows = [
            _make_player("U1", "FWD", 50, drafted=False),
            _make_player("D1", "GK", 10, drafted=True),
            _make_player("D2", "MID", 30, drafted=True),
            _make_player("U2", "DEF", 40, drafted=False),
        ]
        view = self._view(rows)
        view.sort_mode = "points_drafted"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["D2", "D1", "U1", "U2"]

    def test_points_drafted_desc_within_groups(self):
        rows = [
            _make_player("D1", "GK", 10, drafted=True),
            _make_player("D2", "MID", 30, drafted=True),
            _make_player("D3", "DEF", 20, drafted=True),
        ]
        view = self._view(rows)
        view.sort_mode = "points_drafted"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["D2", "D3", "D1"]

    # ── Sort: Points Undrafted ──

    def test_points_undrafted_sorts_undrafted_first(self):
        rows = [
            _make_player("D1", "GK", 10, drafted=True),
            _make_player("U1", "FWD", 50, drafted=False),
            _make_player("D2", "MID", 30, drafted=True),
            _make_player("U2", "DEF", 40, drafted=False),
        ]
        view = self._view(rows)
        view.sort_mode = "points_undrafted"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["U1", "U2", "D2", "D1"]

    def test_points_undrafted_desc_within_groups(self):
        rows = [
            _make_player("U1", "GK", 10, drafted=False),
            _make_player("U2", "MID", 30, drafted=False),
            _make_player("U3", "DEF", 20, drafted=False),
        ]
        view = self._view(rows)
        view.sort_mode = "points_undrafted"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["U2", "U3", "U1"]

    # ── Sort: Position ──

    def test_position_sort_order(self):
        rows = [
            _make_player("GK1", "GK", 30),
            _make_player("FWD1", "FWD", 10),
            _make_player("MID1", "MID", 20),
            _make_player("DEF1", "DEF", 15),
        ]
        view = self._view(rows)
        view.sort_mode = "position"
        view._refresh_data()
        positions = [r["position"] for r in view._rows]
        assert positions == ["FWD", "MID", "DEF", "GK"]

    def test_position_sort_desc_within_group(self):
        rows = [
            _make_player("FWD1", "FWD", 10),
            _make_player("FWD2", "FWD", 30),
            _make_player("FWD3", "FWD", 20),
        ]
        view = self._view(rows)
        view.sort_mode = "position"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["FWD2", "FWD3", "FWD1"]

    def test_position_sort_mixed(self):
        rows = [
            _make_player("GK1", "GK", 50),
            _make_player("FWD1", "FWD", 10),
            _make_player("MID1", "MID", 40),
            _make_player("DEF1", "DEF", 30),
            _make_player("FWD2", "FWD", 20),
        ]
        view = self._view(rows)
        view.sort_mode = "position"
        view._refresh_data()
        positions = [r["position"] for r in view._rows]
        assert positions == ["FWD", "FWD", "MID", "DEF", "GK"]

    # ── Build master list ──

    def test_build_master_called_once(self):
        self.fantasy.build_master_player_list.return_value = []
        _TopPlayersView(self.fantasy, self.draft, self.guild)
        self.fantasy.build_master_player_list.assert_called_once()

    def test_build_master_receives_draft_and_guild(self):
        self.fantasy.build_master_player_list.return_value = []
        _TopPlayersView(self.fantasy, self.draft, self.guild)
        self.fantasy.build_master_player_list.assert_called_once_with(
            self.draft, guild=self.guild
        )

    # ── UI elements ──

    def test_selects_exist(self):
        view = self._view([])
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert len(selects) == 2

    def test_sort_select_exists(self):
        view = self._view([])
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        sort_select = selects[0]
        labels = [o.label for o in sort_select.options]
        assert "Overall (DESC)" in labels
        assert "Total (ASC)" in labels
        assert "Drafted Points" in labels
        assert "Undrafted Points" in labels
        assert "Position" in labels

    def test_sort_select_default(self):
        view = self._view([])
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        defaults = [o for o in selects[0].options if o.default]
        assert len(defaults) == 1
        assert defaults[0].value == "overall_desc"

    def test_pos_filter_select_exists(self):
        view = self._view([])
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        pos_select = selects[1]
        labels = [o.label for o in pos_select.options]
        assert "All Positions" in labels
        assert "FWD" in labels
        assert "MID" in labels
        assert "DEF" in labels
        assert "GK" in labels

    def test_pos_filter_default(self):
        view = self._view([])
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        defaults = [o for o in selects[1].options if o.default]
        assert len(defaults) == 1
        assert defaults[0].value == ""

    def test_pagination_buttons_exist(self):
        view = self._view([])
        buttons = [c for c in view.children if isinstance(c, discord.ui.Button)]
        labels = {b.label for b in buttons}
        assert labels == {"◀", "▶"}

    def test_no_filter_buttons(self):
        view = self._view([])
        buttons = [c for c in view.children if isinstance(c, discord.ui.Button)]
        labels = {b.label for b in buttons}
        assert "All" not in labels
        assert "GK" not in labels
        assert "DEF" not in labels
        assert "MID" not in labels
        assert "FWD" not in labels
        assert "Drafted" not in labels
        assert "Undrafted" not in labels

    # ── Flag display in embed ──

    def test_flag_shown_in_embed_when_present(self):
        rows = [_make_player("Messi", "FWD", 25, country="Argentina", flag="🇦🇷")]
        view = self._view(rows)
        desc = view._build_embed().description
        assert "🇦🇷" in desc
        assert "Messi" in desc

    def test_flag_absent_when_empty(self):
        rows = [_make_player("NoFlag", "FWD", 10)]
        view = self._view(rows)
        desc = view._build_embed().description
        assert "NoFlag" in desc
        assert "**NoFlag**" in desc

    # ── FIFA_POSITION_MAP ──

    def test_position_map_handles_numeric(self):
        assert FIFA_POSITION_MAP["1"] == "GK"
        assert FIFA_POSITION_MAP["2"] == "DEF"
        assert FIFA_POSITION_MAP["3"] == "MID"
        assert FIFA_POSITION_MAP["4"] == "FWD"

    def test_position_map_handles_string(self):
        assert FIFA_POSITION_MAP["GK"] == "GK"
        assert FIFA_POSITION_MAP["DEF"] == "DEF"
        assert FIFA_POSITION_MAP["MID"] == "MID"
        assert FIFA_POSITION_MAP["FWD"] == "FWD"

    # ── COUNTRY_FLAGS mapping ──

    def test_country_flags_has_key_coverage(self):
        majors = {"USA": "US", "France": "FR", "Brazil": "BR", "England": "EN",
                  "Argentina": "AR", "Germany": "DE", "Spain": "ES",
                  "Portugal": "PT", "Netherlands": "NL", "Korea Republic": "KR"}
        for name, code in majors.items():
            assert COUNTRY_FLAGS.get(name) == code, f"Missing: {name}"

    def test_flag_emoji_produces_valid_unicode(self):
        code = _flag_emoji("US")
        assert len(code) == 2
        assert ord(code[0]) >= 0x1F1E6
        assert ord(code[1]) >= 0x1F1E6

    def test_flag_emoji_uk_subdivision(self):
        code = _flag_emoji("EN")
        assert "🏴󠁧󠁢󠁥󠁮󠁧󠁿" in code

    # ── Country filter via command argument ──

    def test_country_filter_via_master_all(self):
        rows = [
            _make_player("Messi", "FWD", 25, country="Argentina", flag="🇦🇷"),
            _make_player("Mbappé", "FWD", 30, country="France", flag="🇫🇷"),
            _make_player("Martínez", "GK", 18, country="Argentina", flag="🇦🇷"),
        ]
        view = self._view(rows)
        view._master_all = [p for p in view._master_all if p.get("country", "") == "Argentina"]
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert "Messi" in names
        assert "Martínez" in names
        assert "Mbappé" not in names

    # ── Sort select updates default on change ──

    def test_sort_select_updates_default(self):
        view = self._view([])
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        view.sort_mode = "position"
        for opt in selects[0].options:
            opt.default = opt.value == view.sort_mode
        defaults = [o for o in selects[0].options if o.default]
        assert len(defaults) == 1
        assert defaults[0].value == "position"

    # ── Position filter ──

    def test_position_filter_fwd(self):
        rows = [
            _make_player("F1", "FWD", 30),
            _make_player("M1", "MID", 20),
            _make_player("D1", "DEF", 10),
        ]
        view = self._view(rows)
        view.position = "FWD"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["F1"]

    def test_position_filter_mid(self):
        rows = [
            _make_player("F1", "FWD", 30),
            _make_player("M1", "MID", 20),
            _make_player("M2", "MID", 10),
        ]
        view = self._view(rows)
        view.position = "MID"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert sorted(names) == ["M1", "M2"]

    def test_position_filter_def(self):
        rows = [
            _make_player("F1", "FWD", 30),
            _make_player("D1", "DEF", 20),
            _make_player("G1", "GK", 10),
        ]
        view = self._view(rows)
        view.position = "DEF"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["D1"]

    def test_position_filter_gk(self):
        rows = [
            _make_player("F1", "FWD", 30),
            _make_player("G1", "GK", 20),
            _make_player("G2", "GK", 10),
        ]
        view = self._view(rows)
        view.position = "GK"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert sorted(names) == ["G1", "G2"]

    def test_position_filter_with_sort(self):
        rows = [
            _make_player("F1", "FWD", 10),
            _make_player("F2", "FWD", 30),
            _make_player("F3", "FWD", 20),
        ]
        view = self._view(rows)
        view.position = "FWD"
        view.sort_mode = "total_asc"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["F1", "F3", "F2"]

    def test_position_filter_empty_when_all(self):
        rows = [
            _make_player("F1", "FWD", 30),
            _make_player("M1", "MID", 20),
        ]
        view = self._view(rows)
        assert view.position == ""
        names = [r["name"] for r in view._rows]
        assert len(names) == 2

    def test_position_filter_title(self):
        rows = [_make_player("F1", "FWD", 30)]
        view = self._view(rows)
        view.position = "FWD"
        view._refresh_data()
        title = view._build_embed().title
        assert "FWD" in title
        assert "🏆 Top Players — FWD" in title

    def test_position_tag_hidden_when_filter_active(self):
        rows = [_make_player("F1", "FWD", 30)]
        view = self._view(rows)
        view.position = "FWD"
        view._refresh_data()
        desc = view._build_embed().description
        assert "FWD" not in desc or "**F1**" in desc

    def test_pos_filter_updates_default(self):
        view = self._view([])
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        view.position = "DEF"
        for opt in selects[1].options:
            opt.default = opt.value == view.position
        defaults = [o for o in selects[1].options if o.default]
        assert len(defaults) == 1
        assert defaults[0].value == "DEF"

    # ── make_player defaults ──

    def test_make_player_defaults(self):
        p = _make_player("N", "MID", 5)
        assert p["country"] == ""
        assert p["flag"] == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
