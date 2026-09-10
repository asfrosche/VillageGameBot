"""Comprehensive pytest tests for BOTC/cogs/nightorder.py standalone functions.

Covers _get_night_roles, _build_night_embeds, and module-level data.
"""

import os
import sys

import discord
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, os.path.join(MAY_DIR, "BOTC"))

from cogs.nightorder import (
    _get_night_roles,
    _build_night_embeds,
    NIGHT_ORDER_EDITIONS,
    EDITION_KEYS,
    EDITION_ROLES,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Module-level data
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleData:
    def test_edition_keys_match(self):
        assert set(EDITION_KEYS) == set(NIGHT_ORDER_EDITIONS.keys())

    def test_edition_roles_loaded(self):
        for key in EDITION_KEYS:
            assert key in EDITION_ROLES
            assert len(EDITION_ROLES[key]) > 0

    def test_night_order_editions(self):
        assert NIGHT_ORDER_EDITIONS["tb"] == "Trouble Brewing"
        assert NIGHT_ORDER_EDITIONS["bmr"] == "Bad Moon Rising"
        assert NIGHT_ORDER_EDITIONS["snv"] == "Sects & Violets"


# ═══════════════════════════════════════════════════════════════════════════
# 2. _get_night_roles
# ═══════════════════════════════════════════════════════════════════════════

class TestGetNightRoles:
    def test_returns_list(self):
        result = _get_night_roles("tb", "firstNight")
        assert isinstance(result, list)

    def test_first_night_has_content(self):
        result = _get_night_roles("tb", "firstNight")
        assert len(result) > 0

    def test_other_night_has_content(self):
        result = _get_night_roles("tb", "otherNight")
        assert len(result) > 0

    def test_sorted_by_position(self):
        result = _get_night_roles("tb", "firstNight")
        positions = []
        for r in result:
            pos = r.get("firstNight", 0)
            assert isinstance(pos, int)
            positions.append(pos)
        assert positions == sorted(positions)

    def test_excludes_fabled(self):
        for key in EDITION_KEYS:
            roles = _get_night_roles(key, "firstNight")
            for r in roles:
                assert r["team"] != "fabled"

    def test_excludes_traveler(self):
        for key in EDITION_KEYS:
            roles = _get_night_roles(key, "firstNight")
            for r in roles:
                assert r["team"] != "traveler"

    def test_unknown_edition_returns_empty(self):
        assert _get_night_roles("unknown", "firstNight") == []

    def test_unknown_night_key_returns_empty(self):
        result = _get_night_roles("tb", "nonExistentKey")
        assert result == []

    def test_all_editions_have_first_night(self):
        for key in EDITION_KEYS:
            assert len(_get_night_roles(key, "firstNight")) > 0, f"{key} has no first night roles"

    def test_all_editions_have_other_night(self):
        for key in EDITION_KEYS:
            assert len(_get_night_roles(key, "otherNight")) > 0, f"{key} has no other night roles"

    def test_role_integrity(self):
        for key in EDITION_KEYS:
            for role in _get_night_roles(key, "firstNight"):
                assert "name" in role
                assert "team" in role
                assert "ability" in role


# ═══════════════════════════════════════════════════════════════════════════
# 3. _build_night_embeds
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildNightEmbeds:
    def test_returns_list_of_embeds(self):
        embeds = _build_night_embeds("tb")
        assert isinstance(embeds, list)
        assert len(embeds) > 0
        for e in embeds:
            assert isinstance(e, discord.Embed)

    def test_first_embed_is_first_night(self):
        embeds = _build_night_embeds("tb")
        assert "First Night" in embeds[0].title

    def test_second_embed_is_other_nights(self):
        embeds = _build_night_embeds("tb")
        if len(embeds) > 1:
            assert "Other Nights" in embeds[1].title

    def test_short_mode_uses_description(self):
        embeds = _build_night_embeds("tb", short=True)
        for e in embeds:
            assert e.description is not None
            # short mode has no fields, just description text
            assert len(e.fields) == 0

    def test_full_mode_uses_fields(self):
        embeds = _build_night_embeds("tb", short=False)
        for e in embeds:
            if len(e.fields) > 0:
                # At least first field has a number
                assert "1." in e.fields[0].name

    def test_short_lists_role_names_only(self):
        embeds = _build_night_embeds("tb", short=True)
        for e in embeds:
            if e.description:
                lines = e.description.split("\n")
                for line in lines:
                    assert "🟦" not in line  # no team emoji in short
                    assert "🟪" not in line

    def test_unknown_edition_fallback_title(self):
        embeds = _build_night_embeds("unknown")
        assert len(embeds) == 1
        assert "UNKNOWN" in embeds[0].title
        assert "No night order" in embeds[0].description

    def test_bmr_first_night_has_roles(self):
        embeds = _build_night_embeds("bmr")
        assert "First Night" in embeds[0].title
        if len(embeds[0].fields) > 0:
            assert "1." in embeds[0].fields[0].name

    def test_short_bmr(self):
        embeds = _build_night_embeds("bmr", short=True)
        assert len(embeds) > 0
        for e in embeds:
            assert isinstance(e, discord.Embed)
