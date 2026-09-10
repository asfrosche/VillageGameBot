"""Comprehensive pytest tests for BOTC/utils/script_image.py.

Covers font loading, cache directory helpers, and image generation
(offline where possible).
"""

import os
import sys
from unittest.mock import patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MAY_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, MAY_DIR)
sys.path.insert(0, os.path.join(MAY_DIR, "BOTC"))

from utils.script_image import (
    _get_font,
    _ensure_cache_dirs,
    _load_icon,
    generate_script_image,
    _ICON_SIZE,
    _TEAM_ORDER,
    _TEAM_LABELS,
    _TEAM_HEADER_COLORS,
    ICON_CACHE,
    SCRIPT_CACHE,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Module-level constants
# ═══════════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_team_order_all_expected(self):
        assert _TEAM_ORDER == ["townsfolk", "outsider", "minion", "demon", "traveler", "fabled"]

    def test_team_labels_all_teams(self):
        for team in _TEAM_ORDER:
            assert team in _TEAM_LABELS

    def test_team_header_colors_all_teams(self):
        for team in _TEAM_ORDER:
            assert team in _TEAM_HEADER_COLORS

    def test_icon_size_positive(self):
        assert _ICON_SIZE > 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. Font loading
# ═══════════════════════════════════════════════════════════════════════════

class TestGetFont:
    def test_returns_font_object(self):
        font = _get_font(12)
        from PIL import ImageFont
        assert isinstance(font, ImageFont.FreeTypeFont | ImageFont.ImageFont)

    def test_different_sizes(self):
        f1 = _get_font(12)
        f2 = _get_font(18)
        # Different sizes produce different font objects
        assert str(f1) != str(f2)

    def test_caches_fonts(self):
        from utils.script_image import _FONT_CACHE
        _FONT_CACHE.clear()
        f1 = _get_font(14)
        f2 = _get_font(14)
        assert f1 is f2  # same cached object
        assert "font_14" in _FONT_CACHE


# ═══════════════════════════════════════════════════════════════════════════
# 3. Cache directory helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestEnsureCacheDirs:
    def test_creates_cache_dirs(self, tmp_path):
        from utils import script_image as simod
        with patch.object(simod, "ICON_CACHE", str(tmp_path / "icons")):
            with patch.object(simod, "SCRIPT_CACHE", str(tmp_path / "scripts")):
                _ensure_cache_dirs()
                assert os.path.isdir(str(tmp_path / "icons"))
                assert os.path.isdir(str(tmp_path / "scripts"))

    def test_idempotent(self, tmp_path):
        from utils import script_image as simod
        with patch.object(simod, "ICON_CACHE", str(tmp_path / "ic")):
            with patch.object(simod, "SCRIPT_CACHE", str(tmp_path / "sc")):
                _ensure_cache_dirs()
                _ensure_cache_dirs()  # no error


# ═══════════════════════════════════════════════════════════════════════════
# 4. Icon loading (offline path)
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadIcon:
    def test_cached_icon_returns_image(self, tmp_path):
        role_id = "test_role"
        cache_dir = tmp_path / "icons"
        cache_dir.mkdir(parents=True)
        from PIL import Image
        fake_icon = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (255, 0, 0, 255))
        fake_icon.save(str(cache_dir / f"{role_id}.png"))

        from utils import script_image as simod
        with patch.object(simod, "ICON_CACHE", str(cache_dir)):
            img = _load_icon(role_id)
            assert img.size == (_ICON_SIZE, _ICON_SIZE)
            assert img.mode == "RGBA"

    def test_missing_icon_returns_fallback(self, tmp_path):
        from utils import script_image as simod
        from unittest.mock import patch as _patch
        with _patch.object(simod, "ICON_CACHE", str(tmp_path / "empty")):
            img = _load_icon("nonexistent_role")
            assert img.size == (_ICON_SIZE, _ICON_SIZE)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Image generation (requires network for icons — test structure only)
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateScriptImage:
    def test_returns_bytes_for_known_edition(self):
        result = generate_script_image("tb")
        assert isinstance(result, bytes)
        assert len(result) > 100  # valid PNG
        assert result[:8] == b'\x89PNG\r\n\x1a\n'  # PNG magic

    def test_unknown_edition_returns_png(self):
        result = generate_script_image("unknown_edition")
        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_bmr_generates(self):
        result = generate_script_image("bmr")
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_snv_generates(self):
        result = generate_script_image("snv")
        assert result[:8] == b'\x89PNG\r\n\x1a\n'
