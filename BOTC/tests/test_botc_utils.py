"""Comprehensive pytest tests for BOTC/utils/botc.py.

Covers data loading, normalisation, fuzzy finding, lookups,
embed building, and data integrity.
"""

import os
import sys

import discord
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
BOTC_DIR = os.path.join(MAY_DIR, "BOTC")
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, os.path.join(MAY_DIR, "BOTC"))

from utils import botc


# ═══════════════════════════════════════════════════════════════════════════
# 1. Module-level data integrity
# ═══════════════════════════════════════════════════════════════════════════

class TestDataLoading:
    """Verify that all data files load correctly with the expected structure."""

    def test_roles_json_loaded(self):
        assert len(botc.ALL_ROLES) >= 100  # core set
        for role in botc.ALL_ROLES:
            assert "id" in role
            assert "name" in role
            assert "team" in role
            assert "ability" in role

    def test_fabled_json_loaded(self):
        assert len(botc.ALL_FABLED) >= 10
        for f in botc.ALL_FABLED:
            assert "id" in f
            assert "name" in f
            assert "ability" in f

    def test_jinxes_json_loaded(self):
        assert len(botc._JINXES_DATA) > 0

    def test_aliases_json_loaded(self):
        assert len(botc._ALIASES_DATA) > 0

    def test_every_role_has_unique_id(self):
        ids = [r["id"] for r in botc.ALL_ROLES]
        assert len(ids) == len(set(ids))

    def test_every_fabled_has_unique_id(self):
        ids = [r["id"] for r in botc.ALL_FABLED]
        assert len(ids) == len(set(ids))

    def test_every_role_has_team(self):
        valid_teams = {"townsfolk", "outsider", "minion", "demon", "traveler", "fabled"}
        for r in botc.ALL_ROLES:
            assert r["team"] in valid_teams, f"{r['name']} has invalid team: {r['team']}"

    def test_every_role_has_edition_or_empty(self):
        for r in botc.ALL_ROLES:
            assert "edition" in r


class TestConstants:
    def test_team_emoji_all_teams(self):
        for team in ("townsfolk", "outsider", "minion", "demon", "traveler", "fabled"):
            assert team in botc.TEAM_EMOJI
            assert len(botc.TEAM_EMOJI[team]) > 0

    def test_team_color_all_teams(self):
        for team in ("townsfolk", "outsider", "minion", "demon", "traveler", "fabled"):
            assert team in botc.TEAM_COLOR

    def test_edition_names(self):
        assert botc.EDITION_NAMES["tb"] == "Trouble Brewing"
        assert botc.EDITION_NAMES["bmr"] == "Bad Moon Rising"
        assert botc.EDITION_NAMES["snv"] == "Sects & Violets"

    def test_image_base_url(self):
        assert botc.IMAGE_BASE.startswith("https://")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Internal helper functions
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalize:
    def test_lowercases(self):
        assert botc._normalize("Washerwoman") == "washerwoman"

    def test_removes_spaces(self):
        assert botc._normalize("Fortune Teller") == "fortuneteller"

    def test_removes_hyphens(self):
        assert botc._normalize("Preacher-man") == "preacherman"

    def test_removes_apostrophe(self):
        assert botc._normalize("Cannibal's") == "cannibals"

    def test_removes_special_chars(self):
        assert botc._normalize("Mr. ?!Käse") == "mrkäse"

    def test_empty_string(self):
        assert botc._normalize("") == ""

    def test_already_normalized(self):
        assert botc._normalize("washerwoman") == "washerwoman"


class TestTokenImageUrl:
    def test_format(self):
        url = botc._token_image_url("washerwoman")
        assert url.startswith("https://")
        assert url.endswith("/washerwoman.png")


class TestGetEditionName:
    def test_known_editions(self):
        assert botc.get_edition_name("tb") == "Trouble Brewing"
        assert botc.get_edition_name("bmr") == "Bad Moon Rising"
        assert botc.get_edition_name("snv") == "Sects & Violets"
        assert botc.get_edition_name("carousel") == "Carousel"

    def test_unknown_edition_capitalizes(self):
        assert botc.get_edition_name("catfishing") == "Catfishing"

    def test_empty_edition_returns_experimental(self):
        assert botc.get_edition_name("") == "Experimental"


class TestTeamEmoji:
    def test_all_teams_return_emoji(self):
        for team in ("townsfolk", "outsider", "minion", "demon", "traveler", "fabled"):
            assert len(botc.team_emoji(team)) > 0

    def test_unknown_team_returns_empty(self):
        assert botc.team_emoji("alien") == ""


# ═══════════════════════════════════════════════════════════════════════════
# 3. Lookup functions — fuzzy find
# ═══════════════════════════════════════════════════════════════════════════

class TestGetRole:
    def test_exact_name(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        assert role["name"] == "Washerwoman"

    def test_case_insensitive(self):
        role = botc.get_role("washerwoman")
        assert role is not None

    def test_partial_fuzzy(self):
        role = botc.get_role("washer")
        assert role is not None
        assert "washer" in role["name"].lower()

    def test_by_id(self):
        role = botc.get_role("washerwoman")
        assert role is not None
        role_by_id = botc.get_role(role["id"])
        assert role_by_id == role

    def test_by_alias(self):
        aliases = botc._ALIASES_DATA
        if aliases:
            alias = list(aliases.keys())[0]
            role = botc.get_role(alias)
            assert role is not None

    def test_unknown_role_returns_none(self):
        assert botc.get_role("notarolelikethis12345") is None

    def test_empty_query_returns_none(self):
        assert botc.get_role("") is None

    def test_whitespace_query_returns_none(self):
        assert botc.get_role("   ") is None

    def test_all_roles_are_findable_by_name(self):
        for r in botc.ALL_ROLES:
            found = botc.get_role(r["name"])
            assert found is not None, f"Could not find role '{r['name']}'"
            assert found["name"] == r["name"]

    def test_all_roles_are_findable_by_id(self):
        for r in botc.ALL_ROLES:
            found = botc.get_role(r["id"])
            assert found is not None, f"Could not find role by id '{r['id']}'"


class TestGetFabled:
    def test_by_name(self):
        fabled = botc.get_fabled("Djinn")
        assert fabled is not None
        assert fabled["name"] == "Djinn"

    def test_case_insensitive(self):
        assert botc.get_fabled("djinn") is not None

    def test_unknown_returns_none(self):
        assert botc.get_fabled("notafabled") is None

    def test_empty_returns_none(self):
        assert botc.get_fabled("") is None

    def test_all_fabled_findable_by_name(self):
        for f in botc.ALL_FABLED:
            found = botc.get_fabled(f["name"])
            assert found is not None, f"Could not find fabled '{f['name']}'"


class TestGetJinxes:
    def test_get_jinxes_by_id(self):
        if botc._JINXES_DATA:
            first_id = botc._JINXES_DATA[0]["id"]
            jinxes = botc.get_jinxes(first_id)
            assert isinstance(jinxes, list)

    def test_get_jinxes_for_role_name(self):
        role = botc.get_role("Alchemist")
        if role:
            jinxes = botc.get_jinxes_for_role("Alchemist")
            assert isinstance(jinxes, list)

    def test_get_jinxes_for_unknown_role(self):
        assert botc.get_jinxes_for_role("notarole") == []

    def test_jinx_structure(self):
        if botc._JINXES_DATA:
            entry = botc._JINXES_DATA[0]
            assert "id" in entry
            assert "jinx" in entry
            if entry["jinx"]:
                j = entry["jinx"][0]
                assert "id" in j
                assert "reason" in j


class TestGetRoleById:
    def test_known_id(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        assert botc.get_role_by_id(role["id"])["name"] == "Washerwoman"

    def test_unknown_id(self):
        assert botc.get_role_by_id("nonexistent_id") is None


class TestGetFabledById:
    def test_known_id(self):
        fabled = botc.get_fabled("Djinn")
        assert fabled is not None
        assert botc.get_fabled_by_id(fabled["id"])["name"] == "Djinn"

    def test_unknown_id(self):
        assert botc.get_fabled_by_id("nonexistent") is None


class TestGetAliases:
    def test_returns_list(self):
        aliases = botc.get_aliases("not_an_id")
        assert isinstance(aliases, list)

    def test_reverse_mapping_consistency(self):
        for target, aliases in botc._ALIAS_REVERSE.items():
            for alias in aliases:
                assert botc._ALIAS_TARGET.get(alias) == target


# ═══════════════════════════════════════════════════════════════════════════
# 4. Embed builders
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildRoleEmbed:
    def test_returns_embed(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_role_embed(role)
        assert isinstance(embed, discord.Embed)

    def test_title_contains_role_name(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_role_embed(role)
        assert "Washerwoman" in embed.title

    def test_description_contains_ability(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_role_embed(role)
        assert role["ability"] in embed.description

    def test_has_thumbnail(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_role_embed(role)
        assert embed.thumbnail is not None
        assert embed.thumbnail.url.startswith("https://")

    def test_has_footer_with_id(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_role_embed(role)
        assert role["id"] in embed.footer.text

    def test_subtitle_shows_team_and_edition(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_role_embed(role)
        assert role["team"].capitalize() in embed.description
        assert "Trouble Brewing" in embed.description

    def test_role_with_reminders_shows_reminder_tokens_field(self):
        roles_with_reminders = [r for r in botc.ALL_ROLES if r.get("reminders")]
        if roles_with_reminders:
            embed = botc.build_role_embed(roles_with_reminders[0])
            field_names = [f.name for f in embed.fields]
            assert any("Reminder" in name for name in field_names)

    def test_role_with_aliases_shows_aliases_field(self):
        roles_with_aliases = [r for r in botc.ALL_ROLES if r["id"] in botc._ALIAS_REVERSE]
        if roles_with_aliases:
            embed = botc.build_role_embed(roles_with_aliases[0])
            field_names = [f.name for f in embed.fields]
            assert any("Alias" in name for name in field_names)

    def test_setup_role_shows_gear_emoji(self):
        setup_roles = [r for r in botc.ALL_ROLES if r.get("setup")]
        if setup_roles:
            embed = botc.build_role_embed(setup_roles[0])
            assert "⚙️" in embed.description

    def test_all_roles_build_without_error(self):
        for r in botc.ALL_ROLES:
            embed = botc.build_role_embed(r)
            assert isinstance(embed, discord.Embed)

    def test_color_matches_team(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_role_embed(role)
        assert embed.color == botc.TEAM_COLOR[role["team"]]


class TestBuildFabledEmbed:
    def test_returns_embed(self):
        fabled = botc.get_fabled("Djinn")
        assert fabled is not None
        embed = botc.build_fabled_embed(fabled)
        assert isinstance(embed, discord.Embed)

    def test_title_contains_fabled_name(self):
        fabled = botc.get_fabled("Djinn")
        assert fabled is not None
        embed = botc.build_fabled_embed(fabled)
        assert "Djinn" in embed.title

    def test_ability_in_description(self):
        fabled = botc.get_fabled("Djinn")
        assert fabled is not None
        embed = botc.build_fabled_embed(fabled)
        assert fabled["ability"] in embed.description

    def test_has_thumbnail(self):
        fabled = botc.get_fabled("Djinn")
        assert fabled is not None
        embed = botc.build_fabled_embed(fabled)
        assert embed.thumbnail is not None

    def test_has_footer_with_id(self):
        fabled = botc.get_fabled("Djinn")
        assert fabled is not None
        embed = botc.build_fabled_embed(fabled)
        assert fabled["id"] in embed.footer.text

    def test_all_fabled_build_without_error(self):
        for f in botc.ALL_FABLED:
            embed = botc.build_fabled_embed(f)
            assert isinstance(embed, discord.Embed)

    def test_color_is_fabled_green(self):
        fabled = botc.get_fabled("Djinn")
        assert fabled is not None
        embed = botc.build_fabled_embed(fabled)
        assert embed.color == botc.TEAM_COLOR["fabled"]


class TestBuildJinxEmbed:
    def test_returns_embed_when_jinxes_exist(self):
        role = botc.get_role("Alchemist")
        if role:
            jinxes = botc.get_jinxes_for_role("Alchemist")
            embed = botc.build_jinx_embed(role, jinxes)
            assert isinstance(embed, discord.Embed)

    def test_no_jinxes_shows_no_jinxes(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_jinx_embed(role, [])
        assert "No jinxes" in embed.description

    def test_has_thumbnail(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_jinx_embed(role, [])
        assert embed.thumbnail is not None

    def test_title_contains_role_name(self):
        role = botc.get_role("Washerwoman")
        assert role is not None
        embed = botc.build_jinx_embed(role, [])
        assert "Washerwoman" in embed.title


class TestBuildNightOrderEmbed:
    def test_returns_embed(self):
        roles = botc.ALL_ROLES[:3]
        embed = botc.build_night_order_embed(roles, "Test Order")
        assert isinstance(embed, discord.Embed)

    def test_title_set(self):
        embed = botc.build_night_order_embed([], "My Title")
        assert embed.title == "My Title"

    def test_lists_roles_with_numbers(self):
        roles = botc.ALL_ROLES[:2]
        embed = botc.build_night_order_embed(roles, "Test")
        for i, r in enumerate(roles, 1):
            field = embed.fields[i - 1]
            assert str(i) in field.name
            assert r["name"] in field.name

    def test_includes_ability(self):
        roles = botc.ALL_ROLES[:1]
        embed = botc.build_night_order_embed(roles, "Test")
        assert roles[0]["ability"] in embed.fields[0].value


# ═══════════════════════════════════════════════════════════════════════════
# 5. Cross-referencing integrity
# ═══════════════════════════════════════════════════════════════════════════

class TestDataIntegrity:
    def test_all_jinx_ids_reference_valid_roles(self):
        for entry in botc._JINXES_DATA:
            role_id = entry["id"]
            assert role_id in botc._ROLES_BY_ID, f"Jinx entry references unknown role id: {role_id}"
            for j in entry["jinx"]:
                assert j["id"] in botc._ROLES_BY_ID, f"Jinx for {role_id} references unknown role id: {j['id']}"

    def test_all_alias_targets_reference_valid_roles(self):
        for alias, target_id in botc._ALIASES_DATA.items():
            assert target_id in botc._ROLES_BY_ID or target_id in botc._FABLED_BY_ID, \
                f"Alias '{alias}' references unknown id: {target_id}"

    def test_no_duplicate_aliases(self):
        seen = {}
        for alias, target_id in botc._ALIASES_DATA.items():
            if alias in seen:
                assert False, f"Duplicate alias: {alias}"
            seen[alias] = target_id

    def test_all_roles_have_team_in_team_emoji(self):
        for r in botc.ALL_ROLES:
            assert r["team"] in botc.TEAM_EMOJI, f"Role '{r['name']}' has unknown team '{r['team']}'"

    def test_role_id_uniqueness(self):
        ids = [r["id"] for r in botc.ALL_ROLES]
        assert len(ids) == len(set(ids))

    def test_fabled_id_uniqueness(self):
        ids = [r["id"] for r in botc.ALL_FABLED]
        assert len(ids) == len(set(ids))

    def test_shared_ids_refer_to_same_character(self):
        """Some characters appear as both roles and fabled (e.g. Djinn, Angel).
        Verify consistency when they share an ID."""
        role_ids = {r["id"]: r for r in botc.ALL_ROLES}
        fabled_ids = {r["id"]: r for r in botc.ALL_FABLED}
        shared = set(role_ids) & set(fabled_ids)
        for sid in shared:
            assert role_ids[sid]["name"].lower() == fabled_ids[sid]["name"].lower(), \
                f"ID {sid}: role={role_ids[sid]['name']} vs fabled={fabled_ids[sid]['name']}"
