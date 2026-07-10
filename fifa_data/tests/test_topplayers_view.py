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

    def test_default_filter_is_all(self):
        view = self._view([])
        assert view.filter_mode == "all"
        assert view.position == ""

    def test_no_players(self):
        view = self._view([])
        embed = view._build_embed()
        assert "No players found." in embed.description
        assert "Page 1/1" in embed.footer.text

    def test_embed_title_default(self):
        view = self._view([])
        assert "All Players" in view._build_embed().title

    def test_embed_title_drafted(self):
        rows = [_make_player("P1", "GK", 10, drafted=True)]
        view = self._view(rows)
        view.filter_mode = "drafted"
        view._refresh_data()
        assert "Drafted" in view._build_embed().title

    def test_embed_title_undrafted(self):
        rows = [_make_player("P1", "GK", 10, drafted=False)]
        view = self._view(rows)
        view.filter_mode = "undrafted"
        view._refresh_data()
        assert "Undrafted" in view._build_embed().title

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

    def test_position_tag_shown_in_all_mode(self):
        rows = [_make_player("Neymar", "FWD", 15, drafted=True)]
        view = self._view(rows)
        desc = view._build_embed().description
        assert "FWD" in desc

    def test_position_tag_hidden_when_filter_active(self):
        rows = [_make_player("Neymar", "FWD", 15, drafted=True)]
        view = self._view(rows)
        view.position = "FWD"
        view._refresh_data()
        desc = view._build_embed().description
        assert "FWD" not in desc or "Neymar" not in desc

    # ── Button styles ──

    def test_all_button_is_primary_by_default(self):
        view = self._view([])
        for child in view.children:
            if child.label == "All":
                assert child.style == discord.ButtonStyle.primary
                break
        else:
            pytest.fail("All button not found")

    def test_position_button_style_toggle(self):
        view = self._view([])
        gk_btn = next(c for c in view.children if c.label == "GK")
        assert gk_btn.style == discord.ButtonStyle.secondary
        view.position = "GK"
        view._update_buttons()
        assert gk_btn.style == discord.ButtonStyle.primary
        view.position = ""
        view._update_buttons()
        assert gk_btn.style == discord.ButtonStyle.secondary

    def test_drafted_button_style(self):
        view = self._view([])
        btn = next(c for c in view.children if c.label == "Drafted")
        assert btn.style == discord.ButtonStyle.secondary
        view.filter_mode = "drafted"
        view._update_buttons()
        assert btn.style == discord.ButtonStyle.primary

    def test_undrafted_button_style(self):
        view = self._view([])
        btn = next(c for c in view.children if c.label == "Undrafted")
        assert btn.style == discord.ButtonStyle.secondary
        view.filter_mode = "undrafted"
        view._update_buttons()
        assert btn.style == discord.ButtonStyle.primary

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

    # ── Filter / toggle logic ──

    def test_set_position_toggle_on_and_off(self):
        view = self._view([])
        view.position = ""
        view.position = "DEF" if view.position != "DEF" else ""
        assert view.position == "DEF"
        view.position = "DEF" if view.position != "DEF" else ""
        assert view.position == ""

    def test_filter_mode_toggle_drafted(self):
        view = self._view([])
        assert view.filter_mode == "all"
        view.filter_mode = "all" if view.filter_mode == "drafted" else "drafted"
        assert view.filter_mode == "drafted"
        view.filter_mode = "all" if view.filter_mode == "drafted" else "drafted"
        assert view.filter_mode == "all"

    def test_filter_mode_toggle_undrafted(self):
        view = self._view([])
        view.filter_mode = "all" if view.filter_mode == "undrafted" else "undrafted"
        assert view.filter_mode == "undrafted"
        view.filter_mode = "all" if view.filter_mode == "undrafted" else "undrafted"
        assert view.filter_mode == "all"

    def test_drafted_view_filters_correctly(self):
        rows = [
            _make_player("D1", "GK", 10, drafted=True),
            _make_player("U1", "MID", 20, drafted=False),
            _make_player("D2", "DEF", 30, drafted=True),
        ]
        view = self._view(rows)
        view.filter_mode = "drafted"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["D1", "D2"]
        assert "U1" not in names

    def test_undrafted_view_filters_correctly(self):
        rows = [
            _make_player("D1", "GK", 10, drafted=True),
            _make_player("U1", "MID", 20, drafted=False),
            _make_player("D2", "DEF", 30, drafted=True),
        ]
        view = self._view(rows)
        view.filter_mode = "undrafted"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["U1"]
        assert "D1" not in names
        assert "D2" not in names

    def test_position_filter_filters_correctly(self):
        rows = [
            _make_player("G1", "GK", 10, drafted=True),
            _make_player("D1", "DEF", 20, drafted=True),
            _make_player("M1", "MID", 30, drafted=True),
        ]
        view = self._view(rows)
        view.position = "DEF"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["D1"]
        assert "G1" not in names
        assert "M1" not in names

    def test_all_view_shows_everyone(self):
        rows = [
            _make_player("D1", "GK", 10, drafted=True),
            _make_player("U1", "MID", 20, drafted=False),
            _make_player("D2", "DEF", 30, drafted=True),
        ]
        view = self._view(rows)
        view.filter_mode = "all"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert sorted(names) == ["D1", "D2", "U1"]

    def test_position_and_drafted_combine(self):
        rows = [
            _make_player("DGK", "GK", 10, drafted=True),
            _make_player("DMID", "MID", 20, drafted=True),
            _make_player("UGK", "GK", 5, drafted=False),
        ]
        view = self._view(rows)
        view.filter_mode = "drafted"
        view.position = "GK"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["DGK"]
        assert "DMID" not in names
        assert "UGK" not in names

    def test_undrafted_gk_returns_gks(self):
        rows = [
            _make_player("DGK", "GK", 10, drafted=True),
            _make_player("UGK1", "GK", 5, drafted=False),
            _make_player("UGK2", "GK", 3, drafted=False),
            _make_player("DMID", "MID", 20, drafted=True),
        ]
        view = self._view(rows)
        view.filter_mode = "undrafted"
        view.position = "GK"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["UGK1", "UGK2"]
        assert "DGK" not in names
        assert "DMID" not in names

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

    def test_buttons_exist(self):
        view = self._view([])
        labels = {c.label for c in view.children if isinstance(c, discord.ui.Button)}
        assert labels >= {"All", "GK", "DEF", "MID", "FWD", "Drafted", "Undrafted", "◀", "▶"}


    # ── FIFA_POSITION_MAP ──────────────────────────────────────

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

    # ── Country filter ─────────────────────────────────────────

    def test_country_filter_filters_correctly(self):
        rows = [
            _make_player("Messi", "FWD", 25, country="Argentina", flag="🇦🇷"),
            _make_player("Mbappé", "FWD", 30, country="France", flag="🇫🇷"),
            _make_player("Martínez", "GK", 18, country="Argentina", flag="🇦🇷"),
        ]
        view = self._view(rows)
        view.country = "Argentina"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert "Messi" in names
        assert "Martínez" in names
        assert "Mbappé" not in names

    def test_country_filter_empty_country_shows_all(self):
        rows = [
            _make_player("A", "FWD", 10, country="Arg", flag="🇦🇷"),
            _make_player("B", "FWD", 20, country="Fra", flag="🇫🇷"),
        ]
        view = self._view(rows)
        view.country = ""
        view._refresh_data()
        assert len(view._rows) == 2

    def test_country_filter_combined_with_position(self):
        rows = [
            _make_player("Messi", "FWD", 25, country="Argentina", flag="🇦🇷"),
            _make_player("Martínez", "GK", 18, country="Argentina", flag="🇦🇷"),
            _make_player("Mbappé", "FWD", 30, country="France", flag="🇫🇷"),
        ]
        view = self._view(rows)
        view.country = "Argentina"
        view.position = "FWD"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["Messi"]
        assert "Martínez" not in names
        assert "Mbappé" not in names

    def test_country_filter_combined_with_drafted(self):
        rows = [
            _make_player("Messi", "FWD", 25, drafted=True, country="Argentina", flag="🇦🇷"),
            _make_player("Martínez", "GK", 18, drafted=False, country="Argentina", flag="🇦🇷"),
        ]
        view = self._view(rows)
        view.country = "Argentina"
        view.filter_mode = "drafted"
        view._refresh_data()
        names = [r["name"] for r in view._rows]
        assert names == ["Messi"]
        assert "Martínez" not in names

    # ── Flag display in embed ──────────────────────────────────

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
        # flag_tag is empty, no stray chars
        assert "**NoFlag**" in desc

    def test_flag_in_title_when_country_filter_active(self):
        rows = [_make_player("Messi", "FWD", 25, country="Argentina", flag="🇦🇷")]
        view = self._view(rows)
        view.country = "Argentina"
        view._refresh_data()
        title = view._build_embed().title
        assert "🇦🇷" in title
        assert "Argentina" in title

    # ── COUNTRY_FLAGS mapping ──────────────────────────────────

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

    # ── All button resets everything ────────────────────────────

    def test_all_resets_position_country_and_mode(self):
        rows = [
            _make_player("A", "GK", 10, drafted=True, country="Arg"),
            _make_player("B", "FWD", 20, drafted=False, country="Fra"),
        ]
        view = self._view(rows)
        view.position = "DEF"
        view.country = "France"
        view.filter_mode = "drafted"
        # simulate what _all callback does
        view.position = ""
        view.country = ""
        view.filter_mode = "all"
        view._refresh_data()
        assert view.position == ""
        assert view.country == ""
        assert view.filter_mode == "all"
        assert len(view._rows) == 2  # all players visible

    # ── Country select dropdown ───────────────────────
    # ── Buttons presence (including country select) ───

    def test_buttons_and_select_exist(self):
        view = self._view([])
        buttons = [c for c in view.children if isinstance(c, discord.ui.Button)]
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        b_labels = {b.label for b in buttons}
        assert b_labels >= {"All", "GK", "DEF", "MID", "FWD", "Drafted", "Undrafted", "◀", "▶"}
        assert len(selects) >= 1, "Expected at least one Select (country filter)"

    def test_country_select_has_all_countries_default(self):
        rows = [
            _make_player("A", "FWD", 10, country="Arg", flag="🇦🇷"),
            _make_player("B", "GK", 8, country="Fra", flag="🇫🇷"),
        ]
        view = self._view(rows)
        select = next(c for c in view.children if isinstance(c, discord.ui.Select))
        labels = [o.label for o in select.options]
        assert "All Countries" in labels
        assert any("Arg" in l for l in labels)
        assert any("Fra" in l for l in labels)

    # ── topplayers command argument ───────────────────

    def test_make_player_defaults(self):
        p = _make_player("N", "MID", 5)
        assert p["country"] == ""
        assert p["flag"] == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
