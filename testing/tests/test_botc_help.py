"""Comprehensive pytest tests for BOTC/cogs/help.py standalone functions.

Covers _load_refs, _save_refs, _resolve_target, _build_help_embed.
"""

import asyncio
import json
import os
import sys
from unittest.mock import MagicMock, patch

import discord
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, os.path.join(MAY_DIR, "BOTC"))

from cogs.help import (
    _load_refs,
    _save_refs,
    _resolve_target,
    PAGES,
    REFS_FILE,
)


# ── Synchronous helper for _resolve_target (async but no awaits in link path) ─

def _resolve_target_sync(target: str | None):
    ctx = MagicMock()
    ctx.message.reference = None
    return asyncio.run(_resolve_target(ctx, target))


# ═══════════════════════════════════════════════════════════════════════════
# 1. References file I/O
# ═══════════════════════════════════════════════════════════════════════════

class TestRefsLoadSave:
    def test_load_missing_file(self, tmp_path):
        from cogs import help as hmod
        original = hmod.REFS_FILE
        hmod.REFS_FILE = str(tmp_path / "nonexistent.json")
        try:
            assert hmod._load_refs() == {}
        finally:
            hmod.REFS_FILE = original

    def test_save_and_load_cycle(self, tmp_path):
        from cogs import help as hmod
        original = hmod.REFS_FILE
        refs_file = tmp_path / "refs.json"
        hmod.REFS_FILE = str(refs_file)
        try:
            data = {"123": {"script": {"channel_id": 1, "message_id": 2}}}
            hmod._save_refs(data)
            assert refs_file.exists()
            loaded = hmod._load_refs()
            assert loaded == data
        finally:
            hmod.REFS_FILE = original

    def test_save_creates_directory(self, tmp_path):
        from cogs import help as hmod
        d = tmp_path / "a" / "b"
        original_data = hmod.DATA_DIR
        original_refs = hmod.REFS_FILE
        hmod.DATA_DIR = str(d)
        hmod.REFS_FILE = str(d / "refs.json")
        try:
            hmod._save_refs({})
            assert (d / "refs.json").exists()
        finally:
            hmod.DATA_DIR = original_data
            hmod.REFS_FILE = original_refs


# ═══════════════════════════════════════════════════════════════════════════
# 2. _resolve_target
# ═══════════════════════════════════════════════════════════════════════════

class TestResolveTarget:
    def test_discord_link_parses(self):
        link = "https://discord.com/channels/123/456/789"
        assert _resolve_target_sync(link) == (456, 789)

    def test_short_link_parses(self):
        link = "https://discordapp.com/channels/1/2/3"
        assert _resolve_target_sync(link) == (2, 3)

    def test_channel_message_hyphen_format(self):
        assert _resolve_target_sync("555-666") == (555, 666)

    def test_invalid_link_returns_none(self):
        assert _resolve_target_sync("not-a-link") is None

    def test_empty_string_returns_none(self):
        assert _resolve_target_sync("") is None

    def test_none_returns_none_no_reply(self):
        assert _resolve_target_sync(None) is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. _build_help_embed
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildHelpEmbed:
    """The help is now split across three page builders in PAGES (was one _build_help_embed)."""

    def test_three_pages(self):
        assert len(PAGES) == 3

    def test_returns_embed(self):
        for page in PAGES:
            assert isinstance(page(), discord.Embed)

    def test_title(self):
        for page in PAGES:
            assert "Blood on the Clocktower" in (page().title or "")

    def test_contains_all_command_names(self):
        all_text = ""
        for page in PAGES:
            e = page()
            all_text += (e.title or "") + (e.description or "") + " " + " ".join(
                f.name + f.value for f in e.fields
            )
        for cmd in [".rr", ".jinx", ".fabled", ".scripts", ".nightorder",
                    ".setref", ".ref", ".bnominate", ".baccuse", ".bdefend",
                    ".bnomtimeout", ".bclose", ".bnoms", ".bsetseating",
                    ".bseating", ".bkill", ".brevive", ".bsponsor",
                    ".bunsponsor", ".bdead"]:
            assert cmd in all_text, f"Missing {cmd} from help pages"

    def test_footer_shows_pagination(self):
        for i, page in enumerate(PAGES, 1):
            footer = page().footer.text or ""
            assert f"Page {i}/{len(PAGES)}" in footer

    def test_color_is_teal(self):
        for page in PAGES:
            assert page().color == discord.Color.teal()
