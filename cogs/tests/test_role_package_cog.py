from types import SimpleNamespace

from cogs.library_cog import LibraryDatabase
from cogs.role_package_cog import RolePackageCog


def test_role_help_command_exists():
    assert hasattr(RolePackageCog, 'role_help')


def test_message_sections_include_content_and_embed_fields():
    message = SimpleNamespace(
        content="Overview text",
        embeds=[SimpleNamespace(
            title="Ability",
            description="Can protect a player.",
            fields=[SimpleNamespace(name="Example", value="Protect Alice")],
        )],
    )

    sections = RolePackageCog._message_sections(message)

    assert sections == [
        ("", "Overview text"),
        ("Ability", "Can protect a player."),
        ("Example", "Protect Alice"),
    ]


def test_library_game_info_parses_channel_name():
    channel = SimpleNamespace(
        name="12│ Custom Ranked Game",
        category=SimpleNamespace(name="📖 Library A"),
    )

    assert RolePackageCog._library_game_info(channel) == (12, "Custom Ranked Game")


def test_library_game_info_rejects_non_library_channel():
    channel = SimpleNamespace(
        name="12│ Custom Ranked Game",
        category=SimpleNamespace(name="ROLES"),
    )

    assert RolePackageCog._library_game_info(channel) is None


def _message(content="", embeds=None):
    return SimpleNamespace(
        id=len(content) or hash(content),
        content=content,
        embeds=[SimpleNamespace(title=None, description=None, fields=[])] if embeds is None else embeds,
    )


def test_split_text_never_breaks_a_line():
    lines = [f"Line {i} - " + "x" * 90 for i in range(40)]
    text = "\n".join(lines)

    chunks = RolePackageCog._split_text(text)

    assert "\n".join(chunks).split("\n") == lines
    assert all(len(chunk) <= 1024 for chunk in chunks)


def test_package_embeds_paginate_long_content():
    cog = RolePackageCog(bot=SimpleNamespace())
    long_text = "A" * 7000
    messages = [_message(content=long_text)]
    embeds = cog._package_embeds(messages, SimpleNamespace(name="RC"))

    assert len(embeds) >= 2
    for embed in embeds:
        assert all(len(field.value) <= 1024 for field in embed.fields)
        assert len(embed.fields) <= 25


def test_package_embeds_exclude_card_message():
    cog = RolePackageCog(bot=SimpleNamespace())
    card_id = 999
    messages = [_message(content="Overview"), _message(content="Card")]
    messages[1].id = card_id
    embeds = cog._package_embeds(messages, SimpleNamespace(name="RC"), exclude_message_id=card_id)

    values = [field.value for embed in embeds for field in embed.fields]
    assert "Card" not in values
    assert "Overview" in values


def test_package_embeds_add_single_jump_link_at_end():
    cog = RolePackageCog(bot=SimpleNamespace())
    messages = [
        SimpleNamespace(id=1, content="Overview text", jump_url="https://discord.com/channels/a/1/1",
                        embeds=[SimpleNamespace(title=None, description=None, fields=[])]),
        SimpleNamespace(id=2, content="Ability text", jump_url="https://discord.com/channels/a/2/2",
                        embeds=[SimpleNamespace(title=None, description=None, fields=[])]),
    ]
    embeds = cog._package_embeds(messages, SimpleNamespace(name="RC"))

    fields = [field for embed in embeds for field in embed.fields]
    assert len(fields) == 2
    assert not any(field.name.startswith("Message ") for field in fields)
    assert sum("[jump]" in field.value for field in fields) == 1
    assert fields[-1].value.endswith("[jump](https://discord.com/channels/a/1/1)")
    assert "Overview text" in fields[0].value
    assert "Ability text" in fields[1].value


def test_package_embeds_preserve_full_text_with_jump_link():
    cog = RolePackageCog(bot=SimpleNamespace())
    text = "Start\n" + "x" * 1100 + "\nEnd"
    messages = [
        SimpleNamespace(id=1, content=text, jump_url="https://discord.com/channels/a/1/1",
                        embeds=[SimpleNamespace(title=None, description=None, fields=[])]),
    ]
    embeds = cog._package_embeds(messages, SimpleNamespace(name="RC"))

    combined = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert combined.count("x") == 1100
    assert "Start" in combined
    assert "End" in combined
    assert combined.count("[jump]") == 1
    assert all(len(field.value) <= 1024 for embed in embeds for field in embed.fields)


def test_package_embeds_handle_missing_jump_url():
    cog = RolePackageCog(bot=SimpleNamespace())
    messages = [_message(content="Overview")]
    embeds = cog._package_embeds(messages, SimpleNamespace(name="RC"))

    fields = [field for embed in embeds for field in embed.fields]
    assert not any("[jump]" in field.value for field in fields)
    assert fields[0].value == "Overview"


def test_atomic_library_import(tmp_path):
    db = LibraryDatabase(str(tmp_path / "library.db"))
    roles = [
        {
            "role_name": "Doctor",
            "team": 1,
            "player_name": "Alice",
            "player_id": 10,
            "sponsor_name": "Bob",
            "sponsor_id": 11,
            "description1": "Overview",
            "description2": "Ability",
            "description3": None,
            "description4": None,
        },
        {
            "role_name": "Mafia Goon",
            "team": 2,
            "player_name": "Charlie",
            "player_id": 12,
            "sponsor_name": None,
            "sponsor_id": None,
            "description1": "Mafia ability",
            "description2": None,
            "description3": None,
            "description4": None,
        },
    ]

    assert db.import_roles_atomic(12, "Custom Ranked Game", roles) == 2
    assert db.get_role_details(12, 1)["role_name"] == "Doctor"
    assert db.get_role_details(12, 1)["description2"] == "Ability"
    assert db.get_role_details(12, 2)["role_name"] == "Mafia Goon"
