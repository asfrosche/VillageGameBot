"""
Regression tests for the safe_add_fields helper and
embed-field length enforcement throughout the library cog.

Run with:  python -m pytest tests/test_safe_add_fields.py -v
"""

import types

# ---------------------------------------------------------------------------
# Minimal discord.Embed stub so we can test without the real library
# ---------------------------------------------------------------------------

class _Embed:
    """Mimics discord.Embed enough for testing field operations."""
    def __init__(self, **kw):
        self.fields = []

    def add_field(self, *, name="", value="", inline=False):
        self.fields.append({"name": name, "value": value, "inline": inline})
        return self


# ---------------------------------------------------------------------------
# Copy of the helper under test (kept in sync with cogs/library_cog.py).
# We duplicate it here to avoid importing the full cog and its heavy deps.
# ---------------------------------------------------------------------------

DISCORD_FIELD_LIMIT = 1024


def safe_add_fields(embed, name: str, text: str, inline: bool = False):
    """Add one or more embed fields, splitting *text* into chunks of at most
    DISCORD_FIELD_LIMIT characters.  Splits prefer line boundaries so role
    lists are never cut mid-line.  If *text* is empty, a single field with
    a placeholder is added instead.
    """
    if not text or not text.strip():
        embed.add_field(name=name, value="*No data.*", inline=inline)
        return

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}{line}\n" if current else f"{line}\n"
        if len(candidate) > DISCORD_FIELD_LIMIT:
            if current:
                chunks.append(current)
            # If a single line itself exceeds the limit, hard-slice it
            while len(line) + 1 > DISCORD_FIELD_LIMIT:
                chunks.append(line[:DISCORD_FIELD_LIMIT])
                line = line[DISCORD_FIELD_LIMIT:]
            current = f"{line}\n" if line else ""
        else:
            current = candidate
    if current:
        chunks.append(current)

    if not chunks:
        embed.add_field(name=name, value="*No data.*", inline=inline)
        return

    for i, chunk in enumerate(chunks):
        field_name = name if i == 0 else f"{name} (cont.)"
        embed.add_field(name=field_name, value=chunk, inline=inline)


# ===========================================================================
# Tests
# ===========================================================================

class TestSafeAddFields:
    """Core unit tests for the safe_add_fields helper."""

    def _embed(self):
        return _Embed()

    def test_short_text_single_field(self):
        embed = self._embed()
        safe_add_fields(embed, "Test", "Hello\n")
        assert len(embed.fields) == 1
        assert embed.fields[0]["name"] == "Test"
        assert embed.fields[0]["value"].strip() == "Hello"

    def test_empty_text_placeholder(self):
        embed = self._embed()
        safe_add_fields(embed, "X", "")
        assert len(embed.fields) == 1
        assert embed.fields[0]["value"] == "*No data.*"

    def test_whitespace_only_placeholder(self):
        embed = self._embed()
        safe_add_fields(embed, "X", "   \n  \n")
        assert len(embed.fields) == 1
        assert embed.fields[0]["value"] == "*No data.*"

    def test_split_on_line_boundary(self):
        """Build text that is >1024 chars and verify it splits."""
        # Each line ~ 55 chars, 25 lines > 1024 chars
        lines = [f"**{i:02d}** - Some Long Role Name - Some Long Player Name ❌\n" for i in range(1, 26)]
        text = "".join(lines)
        assert len(text) > DISCORD_FIELD_LIMIT, f"Test text should exceed limit, got {len(text)}"

        embed = self._embed()
        safe_add_fields(embed, "Roles", text)

        # Must have split into multiple fields
        assert len(embed.fields) >= 2
        # Every field value must be ≤ 1024
        for f in embed.fields:
            assert len(f["value"]) <= DISCORD_FIELD_LIMIT, (
                f"Field '{f['name']}' has {len(f['value'])} chars"
            )
        # Continuation fields should be labelled
        assert embed.fields[0]["name"] == "Roles"
        assert embed.fields[1]["name"] == "Roles (cont.)"

    def test_all_fields_under_limit(self):
        """Stress test: 100 long lines should all produce compliant fields."""
        lines = [f"**{i:03d}** - {'A' * 60} - {'B' * 30} ❌\n" for i in range(100)]
        text = "".join(lines)

        embed = self._embed()
        safe_add_fields(embed, "BigList", text)

        for f in embed.fields:
            assert len(f["value"]) <= DISCORD_FIELD_LIMIT, (
                f"Field '{f['name']}' is {len(f['value'])} chars"
            )

    def test_single_huge_line_hard_sliced(self):
        """A single line > 1024 chars is hard-sliced as a last resort."""
        text = "X" * 2000 + "\n"
        embed = self._embed()
        safe_add_fields(embed, "Huge", text)
        for f in embed.fields:
            assert len(f["value"]) <= DISCORD_FIELD_LIMIT

    def test_exactly_1024_not_split(self):
        """Text exactly at the limit should stay in one field."""
        text = "A" * 1023 + "\n"  # 1024 chars total
        embed = self._embed()
        safe_add_fields(embed, "Exact", text)
        assert len(embed.fields) == 1
        assert len(embed.fields[0]["value"]) == DISCORD_FIELD_LIMIT

    def test_none_text(self):
        embed = self._embed()
        safe_add_fields(embed, "X", None)
        assert embed.fields[0]["value"] == "*No data.*"

    def test_preserves_all_content(self):
        """Splitting must not lose any content."""
        lines = [f"Line {i}: some content here\n" for i in range(50)]
        text = "".join(lines)

        embed = self._embed()
        safe_add_fields(embed, "Data", text)

        reconstructed = "".join(f["value"] for f in embed.fields)
        assert reconstructed.strip() == text.strip()


class TestGame62Regression:
    """
    Reproduce the exact game-62 scenario:
    20 Village-team roles with the real role names that summed to 1088 chars.
    """

    GAME_62_VILLAGE_LINES = [
        "**1** - All fine/ eniF llA - Stain the Canvas - Fan ❌\n",
        "**2** - Deja vu - A Scent Like Wolves - FalconLuci ❌\n",
        "**3** - Forever and a Day - Blackbriar - Diffi ❌\n",
        "**4** - Ghost - Imminence - LordTig ❌\n",
        "**5** - Grey Days - Dreamshade - FreeFeed ❌\n",
        "**6** - Hard Feelings - blessthefall - Pizzazy ❌\n",
        "**7** - House Of Rats - Modern Day Escape - Rebel ❌\n",
        "**8** - I Feel Better - Call Me Cryptic - speak22 ❌\n",
        "**9** - Infamous - Motionless In White - Wulkan ❌\n",
        "**10** - Irl.exe - Munro - Werdna ❌\n",
        "**11** - Let Me Leave - Currents - FirePhoenix ❌\n",
        "**12** - Make Me Believe It - Dead Rabbitts - goodatchessplus ❌\n",
        "**13** - Perfect Weather - Words Like Daggers - Wyx, Hearthside's resident gay ❌\n",
        "**14** - Promised Ones - blessthefall - Boobie ❌\n",
        "**15** - Savages - Fit For An Autopsy - gummybeartje (beertjeenhuub) ❌\n",
        "**16** - Sempiternal - Bring Me the Horizon - Masha ❌\n",
        "**17** - Set to Stun and the Desperado Undead - Set to Stun - Psychosis ❌\n",
        "**18** - The Ego's Weight - Mirrors - zombode ❌\n",
        "**19** - The Puppets Strings Are Broken - Mirrors - Gearworkz ❌\n",
        "**20** - Valley of Kings - The Wise Man's Fear - Mihra ❌\n",
    ]

    def test_game62_roles_text_no_longer_errors(self):
        text = "".join(self.GAME_62_VILLAGE_LINES)
        assert len(text) == 1088, f"Expected 1088 chars, got {len(text)}"

        embed = _Embed()
        safe_add_fields(embed, "Roles (1-20 of 21)", text)

        # Must NOT be in a single field (would be >1024)
        assert len(embed.fields) >= 2

        # Every field is safe
        for f in embed.fields:
            assert len(f["value"]) <= DISCORD_FIELD_LIMIT, (
                f"Field '{f['name']}' is {len(f['value'])} chars — still oversized!"
            )

        # All original content is preserved (minus trailing whitespace)
        reconstructed = "".join(f["value"] for f in embed.fields)
        assert reconstructed.strip() == text.strip()
